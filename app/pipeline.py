"""端到端研判管线（veritas v1：多智能体协同研判 + 冲突消解）。

案例目录 → 摄取切段 → 多分析师并行独立研判（硬隔离）→ 零 LLM 引文
核对（坏证据在此打回，不进归并与仲裁）→ 同义结论归并 → 冲突检测 →
一轮质证 → 仲裁（败方保留为少数意见）→ 置信度融合 → 报告（JSON +
Markdown）+ 研判日志 chain.jsonl。

全程穿插零 LLM 机械闸（模型负责主张，程序负责复算）：
议题前提核对 → 引文核对 → 数字核对（计算复算+溯源）→ 话语核对
（归并守恒+质证/仲裁引用）。前三道在协同段之前拦坏证据；话语闸在
协同段之后亮灯（黄牌警示不剔除内容）。警示为派生视图（core/audit
即时重算），人工修改与文件篡改天然被覆盖。

编排原则：协同段（归并/冲突/辩论/仲裁）每一步失败都降级继续——
最坏情况退化为「多结论并列、无消解记录」，主报告永远能出。
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.arbiter import Coordinator
from app.agents.panel import (
    DEFAULT_ROSTER,
    Analyst,
    build_panel,
    load_roster,
    run_panel,
)
from app.config import Settings
from app.core.audit import audit_all, audit_scan, summarize
from app.core.gate_applicability import not_evaluated_note
from app.core.citation_check import audit_dossier
from app.core.confidence import recompute_all
from app.core.conflicts import (
    apply_resolution,
    dissent_conclusions,
    majority_conclusions,
)
from app.core.discourse_check import (
    audit_discourse,
    audit_hedge,
    audit_level_tone,
)
from app.core.dup_check import duplicate_map, near_dup_pairs
from app.core.evidence import Dossier
from app.core.fact_ledger import _scan, find_collisions
from app.core.hashchain import HashChain
from app.core.material import (
    align_budget_to_window,
    pack_material,
    set_material_budget,
)
from app.core.numeric_check import audit_conservation, audit_counting, audit_numeric
from app.core.premise_check import premise_flags, premise_record
from app.core.relevance import classify_sources
from app.core.skills import detect_skills, set_skills_enabled, skills_enabled
from app.core.untrusted import scan_injections
from app.core.run_progress import ensure_progress, get_active_progress, set_active_progress
from app.ingest.case_loader import count_case_files, load_case, peek_case_question
from app.llm.budget import BudgetGuard, set_active_budget_guard
from app.llm.model_client import ModelClient, ModelClientFactory
from app.llm.profile import probe_model


def _load_case_dossier(case_dir: Path, settings: Settings, *,
                       on_file=None,
                       search_queries: list[str] | None = None) -> Dossier:
    """摄取案卷：达到选料阈值才收窄；未达阈值整卷研判且不建磁盘索引。"""
    min_sel = int(settings.corpus_select_min_sources or 0)
    fetch = settings.fetch_links_enabled
    if min_sel <= 0:
        return _attach_max_disclosures(
            load_case(case_dir, fetch_links=fetch, on_file=on_file), settings)

    # 文件数先预判：演示小案不到阈值，跳过 .corpus，零额外成本。
    if count_case_files(case_dir) >= min_sel:
        from app.core.corpus_store import dossier_from_case_index

        out = dossier_from_case_index(
            case_dir,
            project_id=case_dir.name,
            min_sources=min_sel,
            max_sources=settings.corpus_select_max_sources,
            material_budget=settings.material_char_budget,
            fetch_links=fetch,
            on_file=on_file,
            queries=search_queries,
        )
        return _attach_max_disclosures(out, settings)

    dossier = load_case(case_dir, fetch_links=fetch, on_file=on_file)
    # 压缩包拆封后信源数可能越过阈值——内存收窄，并写出选料披露。
    if len(dossier.sources) >= min_sel:
        from app.core.corpus_index import narrow_dossier

        out = narrow_dossier(
            dossier,
            project_id=case_dir.name,
            max_sources=settings.corpus_select_max_sources,
            material_budget=settings.material_char_budget,
            queries=search_queries,
        )
        return _attach_max_disclosures(out, settings)
    return _attach_max_disclosures(dossier, settings)


def _attach_max_disclosures(dossier: Dossier, settings: Settings) -> Dossier:
    """把 MAX 解析／冲突回落的披露挂进 accounting（有则并入 corpus_select）。"""
    notes = list(getattr(settings, "corpus_select_max_disclosures", None) or [])
    if not notes:
        return dossier
    acc = dossier.accounting if isinstance(dossier.accounting, dict) else {}
    dossier.accounting = acc
    acc["corpus_select_max_disclosures"] = notes
    cs = acc.get("corpus_select")
    if isinstance(cs, dict):
        cs = dict(cs)
        cs["max_disclosures"] = list(notes)
        acc["corpus_select"] = cs
    return dossier


def _prepare_search_queries(question: str, prior: str, client,
                            settings: Settings, prog) -> dict:
    """原问 + 词表兜底；有模型时按规则做同义拓展（机械闸防换主体/捏造）。"""
    from app.core.query_rewrite import prepare_search_info

    original = (question or "").strip()
    model = (settings.models[0] if settings.models else "") or ""
    call = (settings.query_rewrite_enabled and bool(original)
            and client is not None and bool(model))
    if call:
        with prog.stage("query_rewrite", "检索问句同义拓展（约束+机械闸）"):
            info = prepare_search_info(
                original, prior=prior, client=client, model=model,
                enabled=settings.query_rewrite_enabled,
            )
            prog.note(n_variants=len(info.get("variants") or []),
                      status=info.get("status"))
        return info
    return prepare_search_info(
        original, prior=prior, client=None, model=model,
        enabled=settings.query_rewrite_enabled,
    )


def touch_progress() -> None:
    """LLM 成功响应后的心跳：刷新当前环节瞬时耗时。"""
    prog = get_active_progress()
    if prog is not None:
        prog.note(llm_heartbeat=True)


@dataclass
class PipelineResult:
    dossier: Dossier
    chain: HashChain
    rejected: list[dict] = field(default_factory=list)
    out_dir: Path | None = None

    @property
    def report_md(self) -> str:
        return render_report_md(self.dossier, self.chain, self.rejected)


@dataclass
class RunSpec:
    """编排输入（重构 T0：run_case 9 参收拢为 spec+deps 两参）。

    case_dir/out_dir：案例与产物目录；settings：配置（None 走环境）；
    dossier：直接注入案卷（MCP 外部信源路径，此时可不带 case_dir）；
    roster：自定义编队（CLI --roster / MCP）；probe：模型画像自适应
    开关——None 时仅生产路径（未注入 client）启用，注入桩的测试/
    离线演示路径固定关闭（确定性与零额外调用）。"""

    case_dir: Path | None = None
    out_dir: Path | None = None
    settings: Settings | None = None
    dossier: Dossier | None = None
    roster: list | None = None
    probe: bool | None = None
    run_id: str = ""


@dataclass
class RunDeps:
    """测试/调用方注入面：桩 client、预构建 analysts、coordinator。"""

    client: ModelClient | None = None
    analysts: list[Analyst] | None = None
    coordinator: Coordinator | None = None


def pack_window_for_panel(
    dossier: Dossier,
    settings: Settings,
    analysts: list,
    *,
    persona: str,
    profile_tier: str = "standard",
) -> dict:
    """C-67：解析编队最小窗并 align（从 run_case 材料段抽出，行为不变）。

    R-C67-1 件②：测试可 monkeypatch resolve_panel_min_window 再走本函数，
    证明 window_tokens 实参真接到 align（删实参那行必须红）。
    """
    from app.config import resolve_panel_min_window

    panel_models = [a.model for a in analysts if getattr(a, "model", None)]
    # model_context_tokens≤0＝既有关检查口（unchecked、不缩档），不走解析。
    if int(getattr(settings, "model_context_tokens", 0) or 0) <= 0:
        return align_budget_to_window(
            dossier, settings,
            persona=persona, profile_tier=profile_tier)
    resolved = resolve_panel_min_window(settings, panel_models)
    pack_window = align_budget_to_window(
        dossier, settings,
        persona=persona, profile_tier=profile_tier,
        window_tokens=int(resolved["window_tokens"]))
    # 走保守值／未检查假定值时 rule／detail 必须留得下「为什么」
    src = str(resolved.get("source") or "")
    if src in ("fallback", "unchecked_global") or "未检查" in str(
            resolved.get("rule") or ""):
        pack_window["rule"] = str(
            resolved.get("rule") or "align_to_window_未检查")
        pack_window["window_source"] = src or "fallback"
        pack_window["window_detail"] = str(resolved.get("detail") or "")
    else:
        pack_window["window_source"] = src
        pack_window["window_detail"] = str(resolved.get("detail") or "")
    return pack_window


def run_case(spec: RunSpec | None = None,
             deps: RunDeps | None = None) -> PipelineResult:
    """跑一次完整研判。deps 可注入桩（测试零 key）。"""
    spec = spec or RunSpec()
    deps = deps or RunDeps()
    settings = spec.settings or Settings.from_env()
    client = deps.client
    analysts = deps.analysts
    injected_client = client is not None
    t0 = time.monotonic()
    from app.ingest.pdf_backend import set_pdf_backend

    set_pdf_backend(settings.pdf_backend)
    # C-69：两个时间轴开关落到模块旗（须在 ingest／facts_block 之前）
    from app.core.temporal_check import set_source_time_unified
    from app.core.fact_ledger import (
        set_ledger_outlier_tag, set_ledger_time_class, set_metric_canon,
    )
    from app.core.precedent import set_evolve_value_change
    from app.core.relevance import set_relevance_soft_gate
    set_source_time_unified(bool(getattr(settings, "source_time_unified", True)))
    set_ledger_time_class(bool(getattr(settings, "ledger_time_class", True)))
    # C-78：对撞行派生标签（默认开；只影响报告渲染，不进提示词）
    set_ledger_outlier_tag(bool(getattr(settings, "ledger_outlier_tag", True)))
    # C-80：规范量名（默认开；须在 _scan／对撞／对照之前）
    set_metric_canon(bool(getattr(settings, "metric_canon", True)))
    # C-79：演变只认数值变化（默认开；须在对照台账／audit 之前）
    set_evolve_value_change(bool(getattr(settings, "evolve_value_change", True)))
    # C-70：相关性软闸（默认开；须在 classify_sources／装箱之前）
    set_relevance_soft_gate(bool(getattr(settings, "relevance_soft_gate", True)))
    # C-72：要点槽（默认关；须在分析师提示词／主席后评估之前）
    from app.core.claim_slots import set_claim_slots
    set_claim_slots(bool(getattr(settings, "claim_slots", False)))
    created_progress = get_active_progress() is None
    prog = ensure_progress(spec.out_dir)

    # 选料前准备检索问句。完整问句只用原问+词表。
    # 不完整且有上一句时，生产路径才调模型补成一条独立问句。
    # 注入桩不调模型，避免打乱脚本化响应。
    search_queries: list[str] | None = None
    rewrite_info: dict | None = None
    if settings.query_rewrite_enabled:
        from app.core.query_rewrite import prior_question

        peek_q = ""
        if spec.dossier is not None:
            peek_q = spec.dossier.question
        elif spec.case_dir is not None:
            peek_q = peek_case_question(Path(spec.case_dir))
        prior = ""
        if peek_q and spec.case_dir is not None:
            prior = prior_question(
                peek_q, Path(spec.case_dir), skip_dir=spec.out_dir)
        # 生产路径：有网关就做同义拓展。注入桩的测试/离线演示不调拓展，
        # 避免桩 JSON 污染检索；单测直接打 prepare_search_info。
        rewrite_client = None
        if peek_q and not injected_client:
            rewrite_client = client
            if rewrite_client is None:
                try:
                    rewrite_client = ModelClientFactory(settings).create()
                    client = rewrite_client
                except Exception:
                    rewrite_client = None
        if peek_q:
            rewrite_info = _prepare_search_queries(
                peek_q, prior, rewrite_client, settings, prog)
            search_queries = list(rewrite_info.get("queries") or [])

    if spec.dossier is None:
        prog.start("ingest", "读取资料并切片（PDF/文本）")

        def _on_file(rel: str, index: int, total: int) -> None:
            name = rel.rsplit("/", 1)[-1]
            prog.note(file=name, index=index, total=total,
                      hint=f"{index}/{total} {name}")

        dossier = _load_case_dossier(
            Path(spec.case_dir), settings, on_file=_on_file,
            search_queries=search_queries)
        prog.finish(
            n_sources=len(dossier.sources),
            n_segments=sum(len(s.segments) for s in dossier.sources),
        )
    else:
        dossier = spec.dossier

    if rewrite_info:
        dossier.accounting["query_rewrite"] = rewrite_info

    chain = HashChain()
    chain.append("case_loaded", "pipeline", {
        "question": dossier.question,
        "n_sources": len(dossier.sources),
        "n_segments": sum(len(s.segments) for s in dossier.sources),
    })
    if rewrite_info:
        chain.append("query_rewrite", "pipeline", {
            "status": rewrite_info.get("status"),
            "reason": rewrite_info.get("reason"),
            "n_queries": rewrite_info.get("n_queries"),
            "n_variants": len(rewrite_info.get("variants") or []),
        })

    with prog.stage("hygiene", "议题预检·对撞·去重·相关性"):
        premise_rec = premise_record(dossier)
        dossier.accounting["premise"] = premise_rec
        premise = list(premise_rec.get("flags") or [])
        chain.append("premise_check", "pipeline", {
            **summarize(premise),
            "status": premise_rec.get("status"),
            "n_candidates": premise_rec.get("n_candidates"),
            "note": premise_rec.get("note"),
        })
        # 一次 _scan 同时拿 facts + 未采信数字分类计数（禁止再调 extract_facts
        # 造成第三次全扫；改前此处 find_collisions + extract_facts = 2 次）
        facts, fact_stats = _scan(dossier)
        dossier.accounting["fact_ledger_stats"] = fact_stats
        collisions = find_collisions(dossier, facts=facts)
        # C-78：派生标签只进 accounting／报告；默认关不写键（产物面与改前同）
        from app.core.fact_ledger import (
            dispersion_accounting, ledger_outlier_tag_enabled,
        )
        if ledger_outlier_tag_enabled():
            dossier.accounting["ledger_outlier_tag"] = dispersion_accounting(facts)
        # C-115：冲突三类＋处置留痕（默认关；只写 accounting，不改检出）
        if bool(getattr(settings, "conflict_trace", False)):
            from app.core.conflict_trace import apply_conflict_trace
            apply_conflict_trace(
                dossier, collisions=collisions, enabled=True, settings=settings,
            )
        chain.append("fact_ledger", "pipeline", {
            "n_facts": fact_stats["n_facts"],
            "n_collisions": len(collisions),
            "cross_source": sum(1 for c in collisions if c.cross_source),
            "fact_ledger_stats": fact_stats,
        })
        from app.core.precedent import build_precedent_ledger
        # hygiene 早于 material：此处先落台账＋链事件；material 钉选段后再回填进窗标注。
        _prec = build_precedent_ledger(dossier)
        dossier.accounting["precedent"] = _prec.to_dict()
        chain.append("precedent", "pipeline", {
            "n_rows": len(_prec.rows),
            "time_sortable": _prec.time_sortable,
            "n_external_prior": _prec.n_external_prior,
        })
        chain.append("injection_scan", "pipeline",
                     {"n_suspects": len(scan_injections(dossier))})
        chain.append("dup_check", "pipeline", {
            "n_duplicates": len(duplicate_map(dossier)),
            "n_near_dup_pairs": len(near_dup_pairs(dossier)),
        })
        if dossier.ingest_notes:
            chain.append("ingest_notes", "pipeline",
                         {"n_notes": len(dossier.ingest_notes),
                          "kinds": sorted({n["kind"]
                                           for n in dossier.ingest_notes})})
        relevance = classify_sources(dossier)
        from app.core.relevance import (
            relevance_aggregate, relevance_soft_gate_enabled,
        )
        rel_agg = relevance_aggregate(dossier) if relevance_soft_gate_enabled() else {}
        if rel_agg:
            dossier.accounting["relevance_soft"] = rel_agg
        chain.append("relevance_layered", "pipeline", {
            "high": sum(1 for r in relevance if r["level"] == "high"),
            "low": sum(1 for r in relevance if r["level"] == "low"),
            "zero": sum(1 for r in relevance if r["level"] == "zero"),
            "soft_gate": bool(relevance_soft_gate_enabled()),
        })
        prog.note(n_collisions=len(collisions),
                  n_zero_rel=sum(1 for r in relevance if r["level"] == "zero"))

    # 口语议题槽位不齐 → 不烧分析师/修复环，直接回读确认
    from app.core.answer_slots import (
        apply_answer_contract, clarify_headline, slot_intent,
    )

    intent = slot_intent(dossier.question, dossier)
    disclosures = list(intent.get("disclosures") or [])
    if disclosures:
        dossier.accounting["slot_disclosures"] = disclosures
    import os
    force_judgment = (os.environ.get("VERITAS_FORCE_JUDGMENT") or "").strip() in (
        "1", "true", "TRUE", "yes", "YES",
    )
    if intent["clarify"] and not force_judgment:
        set_skills_enabled(settings.skills_enabled)
        with prog.stage("clarify", "议题回读确认（槽位未齐）"):
            synthesis = apply_answer_contract(dossier, {
                "mode": "clarify",
                "headline": clarify_headline(intent),
                "points": [],
                "open_issues": [],
                "gate_notes": [],
            })
            dossier.synthesis = synthesis
            chain.append("slot_clarify_early_exit", "pipeline", {
                "metrics": intent["metrics"],
                "time_kind": intent.get("time_kind"),
                "clarify": intent["clarify"],
                "skipped": ["probe", "panel", "repair", "collab", "chair"],
            })
            prog.note(n_clarify=len(intent["clarify"]),
                      n_metrics=len(intent["metrics"]),
                      clarify=list(intent["clarify"]),
                      hint="请先补齐下面几项，再开始研判")
        kept = {k: v for k, v in (dossier.accounting or {}).items()
                if k in ("corpus_select", "query_rewrite", "slot_disclosures",
                         "panel_attrition", "repair_accept_rate", "premise",
                         "fact_ledger_stats", "prompt_window", "pack_window",
                         "window_ledger")}
        dossier.accounting = {
            **kept,
            "elapsed_s": round(time.monotonic() - t0, 1),
            "tokens": 0,
            "n_calls": 0,
            "budget": "",
            "confidence_note": "议题槽位未齐，未发起模型研判",
            "steps": [
                {"id": s.get("id"), "label": s.get("label"),
                 "elapsed_s": s.get("elapsed_s")}
                for s in prog.steps if s.get("id") != "done"
            ],
        }
        from app.core.retrieval import retrieval_record

        dossier.accounting["retrieval"] = retrieval_record(
            dossier.accounting.get("query_rewrite"))
        chain.append("report_finalized", "pipeline", {
            "question": dossier.question,
            **{k: v for k, v in dossier.accounting.items() if k != "steps"},
        })
        prog.complete(**{k: v for k, v in dossier.accounting.items()
                         if k != "steps"})
        if created_progress:
            set_active_progress(None)
        result = PipelineResult(dossier=dossier, chain=chain, rejected=[])
        if spec.out_dir is not None:
            from app.core.pii import mask_pii

            out_dir = Path(spec.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            dossier.to_json(out_dir / "report.json")
            (out_dir / "report.md").write_text(
                mask_pii(result.report_md), encoding="utf-8")
            chain.to_jsonl(out_dir / "chain.jsonl")
            result.out_dir = out_dir
        return result

    set_skills_enabled(settings.skills_enabled)
    set_material_budget(settings.material_char_budget)
    if client is None:
        client = ModelClientFactory(settings).create()

    if settings.ocr_enabled and dossier.ingest_notes and client is not None:
        from app.ingest.ocr import transcode_images

        try:
            ocr_result = transcode_images(dossier, client, settings.models[0])
            if ocr_result.get("n_pending"):
                chain.append("image_ocr", "pipeline", ocr_result)
        except Exception as exc:
            chain.append("image_ocr", "pipeline",
                         {"error": f"{type(exc).__name__}: {exc}"})

    chain.append("skills_triggered", "pipeline",
                 {"skills": [s.name for s in detect_skills(dossier)],
                  "injection": skills_enabled()})

    guard = BudgetGuard(settings.budget_tokens, settings.budget_throttle_threshold)
    case_key = Path(spec.case_dir).name if spec.case_dir else ""
    run_id = (spec.run_id or "").strip()
    if case_key:
        from app.core.run_cancel import is_cancelled

        guard.attach_cancel_check(
            lambda k=case_key, r=run_id: is_cancelled(k, r or None))
    set_active_budget_guard(guard)

    if analysts is None:
        analysts = build_panel(client, settings.models[0], roster=spec.roster)

    adaptive = bool(spec.probe) if spec.probe is not None else not injected_client
    tiers: dict[str, str] = {}
    force_tier = (settings.force_profile_tier or "").strip().lower()
    if force_tier in ("noncompliant", "compliant", "standard"):
        # 答辩演示：强制档位，跳过真实探测（省一次调用，链上记 forced）
        with prog.stage("probe", "模型纪律画像探测（强制档）"):
            models = sorted({a.model for a in analysts} or set(settings.models))
            for m in models:
                profile = {"tier": force_tier, "model": m, "forced": True,
                           "scores": None}
                tiers[m] = force_tier
                chain.append("model_profile", "pipeline", profile)
                prog.note(model=m, tier=force_tier, forced=True)
    elif adaptive and settings.model_probe_enabled and settings.models:
        with prog.stage("probe", "模型纪律画像探测"):
            for m in sorted({a.model for a in analysts}):
                try:
                    profile = probe_model(client, m)
                    tiers[m] = profile["tier"]
                    chain.append("model_profile", "pipeline", profile)
                    prog.note(model=m, tier=profile["tier"])
                except Exception as exc:
                    tiers[m] = "standard"
                    chain.append("model_profile", "pipeline",
                                 {"model": m, "tier": "standard",
                                  "error": f"{type(exc).__name__}: {exc}"})
    for a in analysts:
        a.profile_tier = tiers.get(a.model, "standard")
        a.settings = settings  # 与对齐／C-9 丙同一份窗口设定

    # C-19：窗口对齐装箱（在档位已知后，用生产同形 messages 估）
    with prog.stage("material", "BM25 精排与预算装箱"):
        from app.agents.prompts import render_system_prompt
        from app.core.skills import render_skills_rules

        align_persona = analysts[0].persona if analysts else "独立分析师"
        align_tier = analysts[0].profile_tier if analysts else "standard"
        best_len = -1
        for a in analysts or []:
            sys_len = len(render_system_prompt(
                a.persona,
                skills_rules=render_skills_rules(dossier, a.profile_tier)))
            if sys_len > best_len:
                best_len = sys_len
                align_persona, align_tier = a.persona, a.profile_tier
        # C-67：装箱窗＝编队所用模型窗的最小值（甲）；落点在本文件而非
        # panel.py——align 只在这里调用，panel 只建 Analyst（零字节）。
        # 实现收到 pack_window_for_panel（R-C67-1 件② 可测接线）。
        pack_window = pack_window_for_panel(
            dossier, settings, analysts or [],
            persona=align_persona, profile_tier=align_tier)
        dossier.accounting["pack_window"] = dict(pack_window)
        if pack_window.get("rule") == "align_to_window" and not pack_window.get("fits"):
            detail = (
                f"窗口对齐后仍超窗：est≈{pack_window.get('est_tokens')} token，"
                f"假定窗口 {pack_window.get('window_tokens')}，"
                f"迭代 {pack_window.get('n_iters')} 次仍无法装入"
            )
            if not any(n.get("kind") == "pack_window_unfit"
                       for n in dossier.ingest_notes):
                dossier.ingest_notes.append({
                    "file": "",
                    "kind": "pack_window_unfit",
                    "detail": detail,
                    "est_tokens": pack_window.get("est_tokens"),
                    "window_tokens": pack_window.get("window_tokens"),
                    "budget": pack_window.get("budget"),
                    "n_iters": pack_window.get("n_iters"),
                })
        # 钉死后全员同料：不许再传 settings.material_char_budget 实参

        # C-108：默认开——测试树交卷 → kg_submit 窄面 → priority／可选 max_segments
        # 关旗 VERITAS_KG_SUBMIT_SURFACE=0 回退旧装满。
        # C-132：主线＝测试树（总旗 VERITAS_TEST_TREE_LINE 出厂开）。旧密度桥
        # 主路径已删（Boyu 2026-11-03 硬令：删旧路、测试树作唯一主线）；
        # 显式 0/false/off/no＝紧急停用交卷面（跳过，绝不回密度桥）。
        # （KG 前端→一筛多维→二筛密度盒→窄面→tree17）；出口仍走 C-107 窄面契约。
        _kg_pack_kw: dict = {}
        if bool(getattr(settings, "kg_submit_surface", True)):
            if bool(getattr(settings, "test_tree_line", True)):
                from app.core.kg_submit_surface import (
                    apply_kg_submit_surface, assert_clean_pack_kwargs,
                    pack_kwargs_for_kg,
                )
                from app.core.kg_test_tree_line import ensure_test_tree_submit
                ensure_test_tree_submit(dossier)
                apply_kg_submit_surface(dossier, enabled=True)
                _kg_pack_kw = pack_kwargs_for_kg(dossier)
                assert_clean_pack_kwargs(_kg_pack_kw)
                # C-140：交卷硬 Top-7＋冲突成对保位（只重写分析师焦点面；
                # 盒／tree17／dens／pack kwargs／续盒核心不动）。关旗＝零行为。
                if bool(getattr(settings, "submit_top7", True)):
                    from app.core.submit_top7 import apply_submit_top7
                    apply_submit_top7(dossier, enabled=True)
            else:
                acc = getattr(dossier, "accounting", None)
                if acc is None:
                    dossier.accounting = {}
                    acc = dossier.accounting
                acc["kg_submit_skipped"] = {
                    "reason": "test_tree_line_off",
                    "note": "C-132 主线＝测试树；旧密度桥主路径已删，"
                            "显式关＝跳过交卷面（回退无 KG 面装箱）",
                }

        pack = pack_material(dossier, **_kg_pack_kw)
        # C-99：锚审支撑分 + A0 软保底（默认开；失败／桩／测试守卫 → 回退 A0）
        # 只在真实 ModelClient 上跑——注入桩会吃脚本应答；测试会话守卫上膛也不跑
        review_disc: dict = {"applied": False, "reason": "skipped"}
        from app.llm.model_client import real_call_guard_armed
        _rb_on = bool(getattr(settings, "review_boost", True))
        if not _rb_on:
            review_disc = {"applied": False, "reason": "flag_off"}
        elif client is None:
            review_disc = {"applied": False, "reason": "no_client"}
        elif real_call_guard_armed():
            review_disc = {"applied": False, "reason": "test_guard_fallback_a0"}
        elif not isinstance(client, ModelClient):
            review_disc = {"applied": False, "reason": "non_model_client"}
        else:
            from app.core.review_boost import try_review_boost_pack

            model_name = (
                settings.models[0] if settings.models else ""
            ) or ""

            def _review_chat(prompt: str, _m=model_name) -> str:
                resp = client.chat(
                    _m, [{"role": "user", "content": prompt}],
                    json_mode=False,
                )
                return str(getattr(resp, "content", "") or "")

            pack, review_disc = try_review_boost_pack(
                dossier,
                chat=_review_chat,
                budget_chars=pack.get("budget"),
                enabled=True,
                B=float(getattr(settings, "review_boost_b", 7000) or 7000),
                k=int(getattr(settings, "review_boost_k", 180) or 180),
                refill_n=int(getattr(settings, "review_boost_refill", 40) or 0),
                do_refill=int(
                    getattr(settings, "review_boost_refill", 40) or 0) > 0,
            )
        dossier.accounting["review_boost"] = dict(review_disc)
        # C-117：树15 满箱有界加窗（默认关；只 +1 档预算／可选 +1 续盒）
        _depress_max_boxes = int(getattr(settings, "multi_box_max", 3) or 3)
        if bool(getattr(settings, "tree15_depress", False)):
            from app.core.tree15_depress import apply_tree15_depress
            pack, _dep = apply_tree15_depress(
                dossier, pack, enabled=True, settings=settings,
                pack_kwargs=dict(_kg_pack_kw),
            )
            _depress_max_boxes = int(
                (_dep or {}).get("depress_max_boxes") or _depress_max_boxes
            )
        # C-29：进窗标注只读这份 accounting，不许再调 pack_material（task #60）
        # 首箱 selected＝主编队同料；续盒并集另记 multi_box（树16）
        dossier.accounting["material_pack_selected"] = sorted(pack["selected"])
        multi_plan = None
        if bool(getattr(settings, "multi_box", True)):
            from app.core.material import (
                multi_box_accounting, pack_continuation_boxes,
            )
            multi_plan = pack_continuation_boxes(
                dossier,
                budget_chars=pack.get("budget"),
                max_boxes=_depress_max_boxes,
            )
            dossier.accounting["multi_box"] = multi_box_accounting(multi_plan)
            dossier.accounting["material_pack_union"] = sorted(
                multi_plan.get("union_selected") or [])
        from app.core.precedent import build_precedent_ledger
        dossier.accounting["precedent"] = build_precedent_ledger(dossier).to_dict()
        chain.append("material_pack", "pipeline", {
            "budget": pack["budget"],
            "n_total": pack["n_total"],
            "n_selected": len(pack["selected"]),
            "n_excluded": len(pack.get("excluded") or []),
            "pack_window": dict(pack_window),
            "multi_box_n": (multi_plan or {}).get("n_boxes"),
            "review_boost_applied": bool(review_disc.get("applied")),
        })
        prog.note(n_total=pack["n_total"], n_selected=len(pack["selected"]),
                  n_excluded=len(pack.get("excluded") or []),
                  budget=pack["budget"],
                  pack_fits=pack_window.get("fits"),
                  multi_box_n=(multi_plan or {}).get("n_boxes"),
                  review_boost=bool(review_disc.get("applied")))

    model_of = {a.name: a.model for a in analysts}

    def _on_analyst_done(name, cons):
        chain.append(
            "analyst_done", name,
            {"n_conclusions": len(cons), "model": model_of.get(name, "")})
        prog.note(last_analyst=name, n_conclusions=len(cons))

    if case_key:
        from app.core.run_cancel import check_cancel
        check_cancel(case_key)

    roster_names = [a.name for a in analysts]
    with prog.stage("panel", "三分析师并行研判", n_analysts=len(analysts)):
        results = run_panel(dossier, analysts, on_done=_on_analyst_done)
        by_name = {a.name: a for a in analysts}
        for name, err in results.get("_failures", {}).items():
            raw = str(getattr(by_name.get(name), "last_raw", "") or "")
            chain.append("analyst_failed", name, {
                "error": err,
                "content_head": raw[:200],
            })
        from app.core.panel_attrition import (
            apply_panel_attrition, failures_from_panel_results,
        )

        fail_map = failures_from_panel_results(roster_names, results)
        for name, err in fail_map.items():
            if name not in (results.get("_failures") or {}):
                chain.append("analyst_empty", name, {"error": err})
        attrition = apply_panel_attrition(dossier, roster_names, fail_map)
        if attrition:
            chain.append("panel_attrition", "pipeline", {
                "n_roster": attrition.get("n_roster"),
                "n_failed": attrition.get("n_failed"),
                "failures": attrition.get("failures"),
                "agreement_cap": attrition.get("agreement_cap"),
            })
        dossier.conclusions.sort(key=lambda c: (c.statement, c.author))
        _ev_key = lambda e: (e.quote, tuple(e.segment_ids), e.level.value,
                              e.relation.value, e.author, e.note,
                              e.conclusion_id)
        dossier.evidences.sort(key=_ev_key)
        # 硬失败（抛错）且无人产出才炸；空交付只显影减员，仍出报告。
        exc_fails = results.get("_failures") or {}
        if exc_fails and not majority_conclusions(dossier):
            raise RuntimeError(
                f"全部分析师研判失败: {exc_fails}")
        prog.note(n_conclusions=len(dossier.conclusions),
                  n_failures=len(exc_fails),
                  n_empty=sum(1 for e in fail_map.values()
                              if str(e).startswith("empty")))

    with prog.stage("citation", "引文逐字核对"):
        rejected = _reject_failed_citations(dossier, chain)
        dossier.rejected = rejected
        numeric = audit_numeric(dossier) + audit_counting(dossier)
        prog.note(n_rejected=len(rejected), n_numeric_flags=len(numeric))

    # 树16／C-66：续盒——第 2‥N 箱定向补答（真模型路径；桩路径跳过保确定性）
    if (bool(getattr(settings, "multi_box", True)) and not injected_client
            and analysts and client is not None):
        from app.agents.multi_box import run_multi_box_passes

        with prog.stage("multi_box", "续盒定向研判"):
            mb_budget = (dossier.accounting.get("multi_box") or {}).get(
                "budget")
            if mb_budget is None:
                mb_budget = (dossier.accounting.get("pack_window") or {}).get(
                    "budget")
            mb = run_multi_box_passes(
                dossier, analysts,
                max_boxes=int(getattr(settings, "multi_box_max", 3) or 3),
                budget_chars=mb_budget,
                on_done=_on_analyst_done,
            )
            # 合并到已有装箱账（保留 per_box 装入面）
            prev = dict(dossier.accounting.get("multi_box") or {})
            prev.update({
                "status": mb.get("status"),
                "passes": mb.get("passes") or [],
                "n_conclusions": mb.get("n_conclusions") or 0,
                "reason": mb.get("reason") or "",
            })
            dossier.accounting["multi_box"] = prev
            chain.append("multi_box", "pipeline", {
                "status": mb.get("status"),
                "n_boxes": mb.get("n_boxes"),
                "n_conclusions": mb.get("n_conclusions"),
                "n_passes": len(mb.get("passes") or []),
            })
            if mb.get("n_conclusions"):
                more_rej = _reject_failed_citations(dossier, chain)
                rejected = list(dossier.rejected or []) + more_rej
                dossier.rejected = rejected
                numeric = audit_numeric(dossier) + audit_counting(dossier)
            prog.note(status=mb.get("status"),
                      n_boxes=mb.get("n_boxes"),
                      n_conclusions=mb.get("n_conclusions"))

    # 刀十一：第一轮引文闸后，就未引用的议题关键段再定向补一轮。
    # 注入桩路径默认跳过（离线演示/单测确定性）；真模型路径默认开。
    if (settings.second_pass_enabled and not injected_client
            and analysts and client is not None):
        from app.agents.second_pass import run_second_pass

        with prog.stage("second_pass", "未用关键段二次定向研判"):
            sp = run_second_pass(
                dossier, analysts,
                max_segments=settings.second_pass_max_segments,
                on_done=_on_analyst_done,
            )
            dossier.accounting["second_pass"] = sp
            chain.append("second_pass", "pipeline", {
                "status": sp.get("status"),
                "focus_ids": sp.get("focus_ids"),
                "n_conclusions": sp.get("n_conclusions"),
                "analyst": sp.get("analyst"),
                "error": sp.get("error") or "",
            })
            if sp.get("n_conclusions"):
                more_rej = _reject_failed_citations(dossier, chain)
                rejected = list(dossier.rejected or []) + more_rej
                dossier.rejected = rejected
                numeric = audit_numeric(dossier) + audit_counting(dossier)
            prog.note(status=sp.get("status"),
                      n_focus=len(sp.get("focus_ids") or []),
                      n_conclusions=sp.get("n_conclusions"))

    if adaptive and numeric:
        with prog.stage("repair", "打回修复环"):
            from app.agents.repair import RepairCtx, run_repair_round

            repair = run_repair_round(dossier, numeric, RepairCtx(
                client=client, model=settings.models[0], analysts=analysts))
            numeric = audit_numeric(dossier) + audit_counting(dossier)
            dossier.accounting["repair_accept_rate"] = repair.get(
                "repair_accept_rate")
            chain.append("repair_round", "pipeline",
                         {**repair, "flags_after": summarize(numeric)})
            prog.note(attempted=repair.get("attempted"),
                      accepted=repair.get("accepted"),
                      repair_accept_rate=repair.get("repair_accept_rate"),
                      stopped_early=repair.get("stopped_early"))
    chain.append("numeric_audit", "pipeline", summarize(numeric))

    if len(analysts) >= 2:
        if case_key:
            from app.core.run_cancel import check_cancel
            check_cancel(case_key)
        with prog.stage("collab", "归并·冲突·质证·仲裁"):
            _run_collaboration(dossier, CollabCtx(
                chain=chain, client=client, model=settings.models[0],
                analysts=analysts, coordinator=deps.coordinator))
            prog.note(n_conflicts=len(dossier.conflicts or []))

    _ev_key = lambda e: (e.quote, tuple(e.segment_ids), e.level.value,
                          e.relation.value, e.author, e.note, e.conclusion_id)
    dossier.evidences.sort(key=_ev_key)

    # C-13：归并之后、置信度回填之前——一遍依赖抽取（失败 → 0 边＋披露）
    with prog.stage("dependency", "结论依赖边"):
        from app.core.dependency import (
            extract_dependencies,
            refresh_premise_broken,
        )
        dep_rec = extract_dependencies(
            dossier, client, settings.models[0] if settings.models else "m")
        chain.append("dependency_extract", "pipeline", {
            "n_edges": dep_rec.get("n_edges", 0),
            "note": dep_rec.get("note"),
            "n_rejected": len(dep_rec.get("rejected") or []),
        })
        prog.note(n_edges=dep_rec.get("n_edges", 0),
                  note=dep_rec.get("note"))

    discourse = (audit_conservation(dossier) + audit_discourse(dossier)
                 + audit_hedge(dossier) + audit_level_tone(dossier))
    chain.append("discourse_audit", "pipeline", summarize(discourse))

    with prog.stage("finalize", "置信度融合"):
        # C-32：主张卡校验／降级须在 recompute_all 之前（改 relation 值，
        # confidence.py 一行不碰；1.15 加成自然失效）
        from app.core.causal_claim import apply_causal_claim_gates
        claim_rec = apply_causal_claim_gates(dossier)
        dossier.accounting["causal_claim"] = claim_rec
        chain.append("causal_claim_gate", "pipeline", claim_rec)
        # 一致性按原编队人数计（减员已在 panel_attrition 披露）
        recompute_all(dossier, n_panel=len(roster_names) or len(analysts))
        # C-116：置信档校准闸（默认关；只调交卷档／披露，不改合式分数）
        if bool(getattr(settings, "conf_calib", False)):
            from app.core.conf_calib import apply_conf_calib
            apply_conf_calib(dossier, enabled=True, settings=settings)
        refresh_premise_broken(dossier)
        chain.append("confidence_computed", "pipeline", {
            "n_majority": len(majority_conclusions(dossier)),
            "n_dissent": len(dissent_conclusions(dossier)),
        })

    from app.agents.chair import build_synthesis

    if case_key:
        from app.core.run_cancel import check_cancel
        check_cancel(case_key)
    with prog.stage("chair", "主席汇总"):
        chair_client = None if injected_client else client
        synthesis = build_synthesis(dossier, chair_client, settings.models[0])
        from app.core.coverage_gap import (
            ledger_limitation,
            subquestion_status,
            unused_topic_note,
            unused_topic_segments,
        )

        unused = unused_topic_segments(dossier)
        if unused:
            dossier.accounting["unused_topic_segments"] = unused
            note = unused_topic_note(unused)
            if note:
                issues = list(synthesis.get("open_issues") or [])
                issues.insert(0, {
                    "kind": "gap", "ref": "资料",
                    "text": note[:120],
                })
                synthesis["open_issues"] = issues
        subs = subquestion_status(dossier, synthesis)
        if subs:
            dossier.accounting["subquestion_status"] = subs
            # 台账来源偏弱（主题词/整题兜底）时必须留下一句声明：
            # 「拆不出来」不等于「没有要做的事」
            limitation = ledger_limitation(subs)
            if limitation:
                dossier.accounting["obligation_limitation"] = limitation
            issues = list(synthesis.get("open_issues") or [])
            for sq in subs:
                if sq.get("status") != "unanswered":
                    continue
                text = f"子问未答：{(sq.get('text') or '')[:40]}"
                if not any(text[:16] in str(o.get("text") or "") for o in issues):
                    issues.append({
                        "kind": "question", "ref": "议题",
                        "text": text,
                    })
            synthesis["open_issues"] = issues
        dossier.synthesis = synthesis
        # C-72：主席落卷后评估要点槽覆盖＋主席支撑披露旗（关旗＝空操作）
        from app.core.claim_slots import apply_claim_slots
        apply_claim_slots(dossier)
        chain.append("chair_summary", "pipeline", {
            "mode": synthesis.get("mode"),
            "n_points": len(synthesis.get("points") or []),
            "n_auto_filled": sum(1 for p in synthesis.get("points") or []
                                 if p.get("auto")),
            "n_open_issues": len(synthesis.get("open_issues") or []),
            "gate_notes": synthesis.get("gate_notes") or [],
            "n_unused_topic": len(unused),
            "n_subquestions": len(subs),
            "ledger_sources": sorted({str(s.get("source") or "") for s in subs}),
            "ledger_weak": bool(dossier.accounting.get("obligation_limitation")),
        })
        prog.note(mode=synthesis.get("mode"),
                  n_points=len(synthesis.get("points") or []))

    n_calls = len(getattr(client, "call_log", []) or [])
    # C-73：窗口账（服务端真报）——只聚合、不改预算／选段
    from app.core.prompt_guard import build_window_ledger
    win_decl = int(getattr(settings, "model_context_tokens", 0) or 0)
    dossier.accounting["window_ledger"] = build_window_ledger(
        getattr(client, "call_log", []) or [],
        window_tokens=win_decl if win_decl > 0 else None,
    )
    kept = {k: v for k, v in (dossier.accounting or {}).items()
            if k in ("corpus_select", "query_rewrite", "slot_disclosures",
                     "repair_accept_rate", "panel_attrition",
                     "unused_topic_segments", "subquestion_status",
                     "obligation_limitation", "n_unused",
                     "premise", "second_pass", "conflict_drops",
                     "mechanical_merge", "fact_ledger_stats",
                     "prompt_window", "pack_window", "dependency",
                     "corpus_select_max_disclosures", "causal_claim",
                     "claim_slots", "ledger_outlier_tag",
                     "multi_box", "material_pack_union", "review_boost",
                     "window_ledger",
                     # C-107／C-108 交卷窄面（旗关时不会写入这些键）
                     "kg_submit_active", "kg_submit", "kg_pack_hints",
                     "kg_conflict_pairs", "kg_focus_segment_ids",
                     "kg_priority_segment_ids", "tree17_cite",
                     "kg_density", "kg_cap_segments", "kg_stage1",
                     "kg_rehydrate", "kg_test_tree",
                     "kg_submit_skipped",
                     "cite_accept", "submit_top7")}
    dossier.accounting = {
        **kept,
        "elapsed_s": round(time.monotonic() - t0, 1),
        "tokens": int(getattr(client, "total_tokens_used", 0) or 0),
        "n_calls": n_calls,
        "budget": guard.summary() if guard else "",
        "confidence_note": "规则融合分（强度×覆盖×一致性×链完整性），不是命中率",
        "steps": [
            {"id": s.get("id"), "label": s.get("label"),
             "elapsed_s": s.get("elapsed_s")}
            for s in prog.steps if s.get("id") != "done"
        ],
    }
    from app.core.retrieval import retrieval_record

    dossier.accounting["retrieval"] = retrieval_record(
        dossier.accounting.get("query_rewrite"))
    chain.append("report_finalized", "pipeline", {
        "question": dossier.question,
        **{k: v for k, v in dossier.accounting.items() if k != "steps"},
    })
    prog.complete(**{k: v for k, v in dossier.accounting.items()
                     if k != "steps"})
    if created_progress:
        set_active_progress(None)

    result = PipelineResult(dossier=dossier, chain=chain, rejected=rejected)

    if spec.out_dir is not None:
        from app.core.pii import mask_pii

        out_dir = Path(spec.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        dossier.to_json(out_dir / "report.json")
        (out_dir / "report.md").write_text(
            mask_pii(result.report_md), encoding="utf-8")
        chain.to_jsonl(out_dir / "chain.jsonl")
        result.out_dir = out_dir
    return result


# ----------------------------------------------------------------------


def _reject_failed_citations(dossier: Dossier, chain: HashChain) -> list[dict]:
    """引文打回：不合格证据移除并留痕，返回打回清单。

    证据被全部打回的结论改为 status=insufficient 留在案卷（不进归并
    与主表置信度）——评委要看「敢报证据不足」，不得从主表蒸发。打回
    明细在本清单与 chain 中可查。"""
    failures = audit_dossier(dossier)
    rejected: list[dict] = []
    for f in failures:
        ev = dossier.evidence(f.evidence_id)
        rejected.append({
            "evidence_id": f.evidence_id,
            "conclusion_id": f.conclusion_id,
            "quote": ev.quote if ev else "",
            "problems": f.problems,
        })
        dossier.remove_evidence(f.evidence_id)
    empties = [c for c in dossier.conclusions if not dossier.evidences_of(c.id)
               and c.status != "merged"]
    for con in empties:
        con.status = "insufficient"
        if "资料不足" not in (con.statement or ""):
            con.statement = f"资料不足：{con.statement}" if con.statement \
                else "资料不足，无法形成可核验结论"
        con.confidence = 0.0
    chain.append("citation_audit", "pipeline", {
        "n_verified": sum(1 for e in dossier.evidences if e.verified),
        "n_rejected": len(rejected),
        "n_conclusions_dropped": len(empties),
        "n_parse_dropped": len(dossier.parse_drops or []),
    })
    return rejected


@dataclass
class CollabCtx:
    """协同段执行资源（重构 T1 提前：6 参收拢）。"""

    chain: HashChain
    client: ModelClient
    model: str
    analysts: list[Analyst]
    coordinator: Coordinator | None = None


def _run_collaboration(dossier: Dossier, ctx: CollabCtx) -> None:
    """归并 → 冲突检测 → 质证 → 仲裁。任一步失败降级继续。"""
    coordinator = ctx.coordinator
    if coordinator is None:
        coordinator = Coordinator(
            ctx.client, ctx.model, personas=dict(DEFAULT_ROSTER))

    chain = ctx.chain
    active = [c.id for c in majority_conclusions(dossier)]
    active = coordinator.merge_conclusions(dossier, active)
    chain.append("merged", "coordinator", {"n_active": len(active)})

    pairs = coordinator.detect_conflicts(dossier, active)
    drops_acc = (dossier.accounting or {}).get("conflict_drops") or {}
    chain.append("conflicts_detected", "coordinator", {
        "n_pairs": len(pairs),
        "n_candidates": drops_acc.get("n_candidates"),
        "n_dropped": drops_acc.get("n_dropped"),
        "conflict_drops_note": drops_acc.get("note") or "",
    })

    for pair in pairs:
        rebuts = coordinator.run_rebuttals(dossier, pair)      # 内部单侧降级
        pair.resolution = coordinator.arbitrate(dossier, pair, rebuts)
        problems = apply_resolution(pair, dossier)
        dossier.conflicts.append(pair.to_dict())
        if pair.resolution is None or problems:
            chain.append("conflict_unresolved", "coordinator", {
                "pair": pair.to_dict(), "problems": problems or {"reason": "仲裁失败"}})
        else:
            chain.append("conflict_resolved", "coordinator", {
                "pair_id": pair.id,
                "winner": pair.resolution.winner_id,
                "method": pair.resolution.method,
            })
    # C-115：仲裁后刷新留痕（并入 conflict_pair；旗关不写）
    from app.core.conflict_trace import apply_conflict_trace, conflict_trace_enabled
    if conflict_trace_enabled():
        apply_conflict_trace(dossier, collisions=None, enabled=True)


def _decorate_attrition(note: str, empty_runs: list[dict] | None) -> str:
    """减员行的「空交付」后面带形态。账本里的短因仍是「空交付」。"""
    out = note
    for run in empty_runs or []:
        author = str(run.get("author") or "")
        old = f"{author}（空交付）"
        if old not in out:
            continue
        chars = int(run.get("content_chars") or 0)
        shape = str(run.get("shape") or "其他")
        new = f"{author}（空交付（{shape}，响应 {chars:,} 字））"
        out = out.replace(old, new, 1)
    return out


def _render_empty_runs(lines: list[str], dossier: Dossier) -> None:
    runs = list(getattr(dossier, "empty_runs", None) or [])
    if not runs:
        return
    lines += ["## 空交付明细", ""]
    for run in runs:
        lines.append(
            f"- {run.get('author') or 'N/A'}／{run.get('model') or ''}："
            f"{run.get('shape')}；响应 {run.get('content_chars')} 字；"
            f"节选「{run.get('head') or ''}」…「{run.get('tail') or ''}」"
        )
    lines.append("")


def render_report_md(dossier: Dossier, chain: HashChain, rejected: list[dict]) -> str:
    """研判报告 Markdown（主表结论 + 分歧消解 + 少数意见 + 打回 + 防篡改）。"""
    verify = chain.verify_chain()
    lines: list[str] = [
        f"# 研判报告：{dossier.title or dossier.question}",
        "",
        f"**议题**：{dossier.question}",
        "",
        f"**研判编队**：{('、'.join(dossier.panel) or 'N/A')}"
        f"（独立研判，互不可见对方结论）",
        "",
    ]
    acc = dossier.accounting or {}
    attrition_note = str(
        (acc.get("panel_attrition") or {}).get("note") or "").strip()
    if attrition_note:
        lines += [
            f"**编队减员**：{_decorate_attrition(attrition_note, dossier.empty_runs)}",
            "",
        ]
    _render_empty_runs(lines, dossier)
    mech = acc.get("mechanical_merge") or {}
    if mech:
        # 协同是否真的发生，写在首屏：0 条会签就是 0 条，不藏
        _majors = majority_conclusions(dossier)
        n_signed = sum(1 for c in _majors if len(c.author_names()) >= 2)
        lines += [
            "**协同归并**："
            f"主表 {len(_majors)} 条中 **{n_signed} 条为多人共同署名**"
            + (f"；{str(mech.get('note') or '').strip()}"
               if str(mech.get("note") or "").strip() else ""),
            "",
        ]
    lines += [
        f"**资料**：{len(dossier.sources)} 份信源 / "
        f"{sum(len(s.segments) for s in dossier.sources)} 个段落",
        "",
    ]
    select_note = str((acc.get("corpus_select") or {}).get("note") or "").strip()
    if select_note:
        lines += [
            f"**选料范围**：{select_note}",
            "",
        ]
    rewrite_note = str((acc.get("query_rewrite") or {}).get("note") or "").strip()
    if rewrite_note and (acc.get("query_rewrite") or {}).get("variants"):
        lines += [
            f"**检索问法**：{rewrite_note}",
            "",
        ]
    slot_notes = [str(x).strip() for x in (acc.get("slot_disclosures") or [])
                  if str(x).strip()]
    if slot_notes:
        lines += [
            f"**议题披露**：{'；'.join(slot_notes)}",
            "",
        ]
    subs = acc.get("subquestion_status") or []
    if subs:
        from app.core.coverage_gap import LEDGER_SOURCE_CN

        st_cn = {"answered": "已答", "gap": "缺口", "unanswered": "未答"}
        srcs = "、".join(sorted({LEDGER_SOURCE_CN.get(
            s.get("source"), s.get("source") or "未知") for s in subs}))
        bits = [f"{st_cn.get(s.get('status'), s.get('status'))}｜"
                f"{(s.get('text') or '')[:36]}" for s in subs]
        lines += [
            f"**完整性判据**（{len(subs)} 条 · 来源：{srcs}）：{'；'.join(bits)}",
            "",
        ]
        limitation = str(acc.get("obligation_limitation") or "").strip()
        if limitation:
            lines += [f"> ⚠️ {limitation}", ""]
    from app.core.retrieval import retrieval_note

    lines += [
        f"**检索边界**：{retrieval_note(acc)}",
        "",
    ]
    if acc:
        lines += [
            f"**本次研判**：{acc.get('elapsed_s', '-')} 秒 · "
            f"{acc.get('n_calls', 0)} 次模型调用 · {acc.get('tokens', 0)} token"
            f"（{acc.get('confidence_note') or '规则分，不是命中率'}）",
            "",
        ]
    _render_confidence_bands(lines, dossier)
    _render_dependency_section(lines, dossier)
    lines += [
        "## 结论",
        "",
    ]
    majors = majority_conclusions(dossier)
    if not majors:
        lines.append("（无结论——检查资料覆盖或分析师输出）")
    majors.sort(key=lambda c: c.confidence, reverse=True)
    from app.core.merge_mechanical import merge_label
    from app.core.panel_attrition import author_count_label

    for con in majors:
        lines.append(f"### {con.statement}")
        lines.append("")
        lines.append(f"- 置信度：**{con.confidence:.2f}**"
                     f"{confidence_label(con.confidence_parts)}")
        lines.append(
            f"- 研判方：{'、'.join(con.author_names()) or 'N/A'}"
            f"{author_count_label(con)}{merge_label(dossier, con)}")
        if con.depends_on:
            lines.append(
                f"- 前提结论：{'、'.join(f'`{x}`' for x in con.depends_on)}")
        if con.premise_broken:
            lines.append(
                f"- ⚠️ 前提失效黄牌：上游 "
                f"{'、'.join(f'`{x}`' for x in con.premise_broken)} "
                f"已失效（report.md 只亮牌，未改写本结论）")
        _render_evidence_table(lines, dossier, con)
        lines.append("")

    cause_ids = {
        str(r.get("conclusion_id") or "")
        for r in (list(rejected or []) + list(dossier.parse_drops or []))
        if r.get("conclusion_id")
    }
    insuff = [c for c in dossier.conclusions if c.status == "insufficient"]
    if insuff:
        lines += ["## 证据不足（未进入主表）", ""]
        for con in insuff:
            line = (
                f"- {con.statement}（研判方："
                f"{'、'.join(con.author_names()) or 'N/A'}"
                f"{author_count_label(con)}）"
            )
            if con.id not in cause_ids:
                line += " —— 成因缺失（异常）"
            lines.append(line)
        lines.append("")

    _render_question_preflight(lines, dossier)
    _render_synthesis(lines, dossier)
    _render_triage_ledger(lines, dossier)
    _render_conflicts_section(lines, dossier)
    _render_kg_conflict_pairs_section(lines, dossier)
    _render_dissent_section(lines, dossier)
    _render_fact_collisions(lines, dossier)
    # C-29 R1：同类对照节插在对撞与窗口披露之间；字数闸分母＝其余节合计，
    # 先渲后续节一次算清 rest，再按双上限把本节插回原位（输出序不变）。
    _prec_at = len(lines)
    _render_prompt_window(lines, dossier)
    _render_window_ledger(lines, dossier)
    _render_excluded_sources(lines, dossier)

    if rejected:
        lines += ["## 被打回的证据（引文核对未通过）", ""]
        for r in rejected:
            lines.append(f"- `{r['evidence_id']}`：{'; '.join(r['problems'])}"
                         f"（引文：{r['quote'][:60]}…）")
        lines.append("")

    parse_drops = list(dossier.parse_drops or [])
    if parse_drops:
        lines += ["## 引用未落地的证据与丢失的结论条目（段落不存在／未编号／条目非法）", ""]
        for r in parse_drops:
            lines.append(
                f"- `{r.get('conclusion_id')}`／{r.get('author') or 'N/A'}："
                f"{r.get('reason')}"
                f"（segment_id={r.get('segment_id') or '（空）'}；"
                f"引文：{str(r.get('quote_head') or '')}…）"
            )
        lines.append("")

    _render_flags_section(lines, dossier)

    rest_chars = len("\n".join(lines))
    prec_block = _render_precedent_section_lines(dossier, rest_chars=rest_chars)
    lines[_prec_at:_prec_at] = prec_block

    lines += [
        "## 防篡改校验",
        "",
        f"- 研判日志 {len(chain.records)} 条，哈希链校验："
        f"{'✅ 通过' if verify else f'❌ 失败（#{verify.bad_index}: {verify.reason}）'}",
        "",
    ]
    return "\n".join(lines)


_KIND_LABEL = {
    "calc": "计算复算不符",
    "provenance": "来源外数字",
    "counting": "计数断言无法复核",
    "merge_conservation": "归并概括漂移",
    "rebut_quote": "质证引文未命中",
    "rebut_ref": "质证引用不存在编号",
    "arbiter_ref": "仲裁理由引用不存在编号",
    "hedge": "低可信信源配断言语气",
    "level_tone": "措辞强度超过证据等级",
    "stale": "引用旧时点资料",
    "as_of": "结论未锚定时点",
    "injection": "疑似指令注入内容",
    "near_dup": "疑似同源转述",
    "question": "议题表述待聚焦",
    "premise": "议题前提未覆盖",
    "percent_no_base": "涨跌百分比未见基数",
    "unit_mismatch": "人民币与美元口径混用",
    "source_unverified": "信源出处未核验",
    "level_consistency": "证据等级与信源类型不符",
    "causation_support": "因果标注缺乏机制词",
    "causal_claim_missing": "因果主张卡不完整已降级",
    "warrant_theme": "理由与主张无共同主题词",
    "scope": "声称范围却无覆盖声明",
}


def confidence_label(parts: dict) -> str:
    """置信度分量 → 一行可读表述（榜单硬需求 3「给分并说明依据」）。

    四分量各自命名清楚，第四分量（推理链完整性）还要说清断在哪一环——
    综合是加权和＋硬门，只报一个总分等于把依据又藏回黑箱。
    """
    from app.core.chain_integrity import CHECK_LABEL_CN

    p = parts or {}
    if not p:
        return ""
    chain = p.get("chain")
    detail = p.get("chain_detail") or {}
    applicable = detail.get("applicable") or []
    if chain is None:
        # 无从判定（链上一环都没触发）与存量产物缺键是两回事，分开说：
        # 前者是「这条结论没东西可核」，后者是「这份产物落盘时还没这个分量」
        chain_txt = ("链完整性 无从判定" if detail.get("unknown")
                     else "链完整性 —（旧口径产物，未计该分量）")
    else:
        broken = "、".join(CHECK_LABEL_CN.get(k, k)
                           for k in (detail.get("broken") or []))
        # 明说「核了几环」：只触发一环的结论不能写成「六环全闭合」
        chain_txt = (f"链完整性 {chain:.2f}〔核 {len(applicable)} 环｜"
                     f"{('断：' + broken) if broken else '全闭合'}〕")
    bits = [f"强度 {p.get('strength', 0):.2f}",
            f"覆盖 {p.get('coverage', 0):.2f}",
            f"一致性 {p.get('agreement', 0):.2f}",
            chain_txt,
            f"{p.get('n_evidence', 0)} 条证据"]
    gates = p.get("gates") if isinstance(p.get("gates"), dict) else {}
    fired = [k for k, g in gates.items()
             if isinstance(g, dict) and g.get("fired")]
    if fired:
        bits.append("硬门 " + "、".join(fired))
    note = str(p.get("note") or "").strip()
    if note:
        bits.append(note)
    return "（" + " · ".join(bits) + "）"


def _render_flags_section(lines: list[str], dossier: Dossier) -> None:
    """机械核对警示（零 LLM 复算）：报告落定后再全案卷扫一遍。

    红（high）=算式复算不符/输入造假；黄（medium）=来源外数字、归并
    概括漂移、质证疑似歪曲、前提未覆盖等。警示不剔除内容——语义取舍
    仍归分析师与读者，机械侧只保证「每个数字都能对账」。

    「全部通过 ✅」是有条件的说法：**有闸本次没进场就不许写**。
    2026-10-13 实测计数闸在 32/34 份存量产物里一个对象都没碰到，
    旧文案把「没查」写成了「查过且干净」。未执行清单见 not_evaluated。"""
    scan = audit_scan(dossier)
    flags = scan["flags"]
    ne = scan["not_evaluated"]
    ne_note = not_evaluated_note(ne)
    lines += ["## 机械核对警示（零 LLM 复算）", ""]
    prem = (dossier.accounting or {}).get("premise") or {}
    prem_status = prem.get("status")
    prem_note = str(prem.get("note") or "").strip()
    unchecked = prem_status in ("no_candidates", "no_corpus")
    exempt = prem_status == "exempt_template"
    if not flags:
        if ne:
            lines += [f"- ⚪ {ne_note}", ""]
            if unchecked and prem_note:
                lines += [f"- {prem_note}", ""]
            return
        if unchecked:
            fallback = {
                "no_candidates": "议题前提：未核（议题未抽出可比对实体）",
                "no_corpus": "议题前提：未核（案卷无信源正文）",
            }.get(str(prem_status), "议题前提：未核")
            lines += [
                f"- {prem_note or fallback}",
                "- 计算复算、数字溯源、质证/仲裁引用：全部通过 ✅",
                "",
            ]
        else:
            # checked_ok / exempt_template：议题前提项算过关（免核单独注明）
            lines += [
                "- 计算复算、数字溯源、议题前提、质证/仲裁引用：全部通过 ✅"
                + (f"（{prem_note}）" if prem_note else ""),
                "",
            ]
        return
    if ne_note:
        lines.append(f"- ⚪ {ne_note}")
    if unchecked and prem_note:
        lines.append(f"- ⚪ {prem_note}")
    elif exempt and prem_note:
        lines.append(f"- ⚪ {prem_note}")
    high = [f for f in flags if f["severity"] == "high"]
    medium = [f for f in flags if f["severity"] == "medium"]
    if high:
        lines.append(f"- 🔴 未通过 {len(high)} 项：")
        lines += [f"  - [{_KIND_LABEL.get(f['kind'], f['kind'])}] {f['detail']}"
                  for f in high]
    if medium:
        lines.append(f"- 🟡 警示 {len(medium)} 项：")
        lines += [f"  - [{_KIND_LABEL.get(f['kind'], f['kind'])}] {f['detail']}"
                  for f in medium]
    lines.append("")


def _render_evidence_table(lines: list[str], dossier: Dossier, con) -> None:
    from app.core.causal_claim import missing_links_cn

    evs = dossier.evidences_of(con.id)
    if not evs:
        return
    lines += ["", "| 逐字引文 | 出处 | 等级 | 关系 | 说明 |", "|---|---|---|---|---|"]
    for ev in evs:
        seg = dossier.segment(ev.segment_ids[0]) if ev.segment_ids else None
        where = ev.segment_ids[0] + (f"（{seg.locator}）" if seg else "")
        quote = ev.quote.replace("|", "\\|").replace("\n", " ")
        note_bits = [ev.note] if ev.note else []
        if (ev.declared_relation or "") == "causation" and ev.relation.value != "causation":
            rel = "correlation（原声明：因果｜已降级：相关）"
            if ev.degraded_reason:
                note_bits.append(ev.degraded_reason)
        else:
            rel = ev.relation.value
        note_bits.extend(missing_links_cn(ev))
        note = "；".join(note_bits).replace("|", "\\|")
        from app.export.official import level_official_of
        try:
            level_cell = f"{ev.level.value}（{level_official_of(ev.level.value)}）"
        except KeyError:
            level_cell = ev.level.value
        lines.append(
            f"| {quote} | {where} | {level_cell} | {rel} | {note} |")


def _render_question_preflight(lines: list[str], dossier: Dossier) -> None:
    """议题体检：分级 + 机械回读（二次确认语义）+ 澄清建议（批处理形态）。

    不改写问题——回读只把系统抽到的要素摆出来；澄清建议改 manifest
    的 question 重跑即新研判（链上留议题演化史）。"""
    from app.core.question_check import question_preflight, readback_line

    pf = question_preflight(dossier.question)
    lines += [f"## 议题体检（{pf['tier_cn']}）", "",
              f"- {readback_line(dossier.question)}"]
    for s in pf["signals"]:
        lines.append(f"- {s}")
    if pf["clarify"]:
        lines.append("- 澄清建议（可选，聚焦后重跑可获更高置信结论）：")
        lines += [f"  - {c}" for c in pf["clarify"]]
    lines.append("")


def _render_synthesis(lines: list[str], dossier: Dossier) -> None:
    """综合研判意见（主席层）：快照缺失时 live 回退零 LLM 模板。"""
    from app.agents.chair import render_chair_template

    synthesis = dossier.synthesis or render_chair_template(dossier)
    lines += ["## 综合研判意见", ""]
    mode = synthesis.get("mode")
    if mode == "template":
        lines.append("> （零 LLM 模板汇总——按置信度逐条渲染，确定性）")
    lines.append(f"**{synthesis['headline']}**")
    lines.append("")
    for p in synthesis.get("points") or []:
        auto = "（程序自动补全）" if (mode == "llm" and p.get("auto")) else ""
        lines.append(f"- {p['gloss']}`{p['con_id']}` · 置信度 "
                     f"{p.get('confidence', 0):.2f}{auto}")
    unused = (dossier.accounting or {}).get("unused_topic_segments") or []
    if unused:
        from app.core.coverage_gap import unused_topic_note

        lines += ["", f"**含议题词但未引用**：{unused_topic_note(unused)}", ""]
    issues = synthesis.get("open_issues") or []
    if issues:
        lines += ["", "**分歧与缺口（明示，不抹平）**："]
        kind_cn = {"conflict": "冲突", "dissent": "少数意见",
                   "gap": "资料缺口", "note": "说明", "question": "待确认"}
        for o in issues:
            lines.append(f"- ⚠ [{kind_cn.get(o.get('kind'), o.get('kind'))}]"
                         f" {o.get('text')}（{o.get('ref')}）")
    notes = synthesis.get("gate_notes") or []
    if notes:
        lines += ["", f"<!-- 主席层闸记事：{'；'.join(notes)} -->"]
    lines.append("")


def _render_triage_ledger(lines: list[str], dossier: Dossier) -> None:
    """输入分诊账本：每个文件的路由与理由（含派生的零相关/重复/兜底）。"""
    from app.ingest.triage import ROUTE_LABEL, ROUTE_ORDER

    records = list(dossier.triage)
    # 派生路由并入账本（classify/dup 为即时重算视图）
    from app.core.dup_check import duplicate_map
    from app.core.relevance import classify_sources

    for s in classify_sources(dossier):
        if s["level"] == "zero":
            records.append({"file": f"{s['source_id']}《{s['title']}》",
                            "route": "zero", "reason": s["reason"]})
        elif s["level"] == "low" and "兜底" in (s["reason"] or ""):
            records.append({"file": f"{s['source_id']}《{s['title']}》",
                            "route": "promoted_low", "reason": s["reason"]})
    dups = duplicate_map(dossier)
    for src in dossier.sources:
        if src.id in dups:
            records.append({"file": f"{src.id}《{src.title}》", "route": "dup",
                            "reason": f"与 {dups[src.id]} 内容完全重复"})
    if not records:
        return
    lines += ["## 输入分诊账本（每个文件的路由与理由）", ""]
    records.sort(key=lambda r: ROUTE_ORDER.get(r.get("route"), 99))
    for r in records:
        label = ROUTE_LABEL.get(r.get("route"), r.get("route"))
        reason = f"——{r['reason']}" if r.get("reason") else ""
        lines.append(f"- `{r['file']}` → **{label}**{reason}")
    lines.append("")


def _render_kg_conflict_pairs_section(
        lines: list[str], dossier: Dossier) -> None:
    """C-107：交卷窄面 conflict_pairs → 报告冲突节（旗开且已 apply）。"""
    acc = dossier.accounting or {}
    if not acc.get("kg_submit_active"):
        return
    pairs = acc.get("kg_conflict_pairs")
    if not pairs:
        return
    lines += ["## 交付窄面冲突成对（KG）", ""]
    if isinstance(pairs, dict):
        for side, label in (("support", "支持"), ("oppose", "反对")):
            rows = pairs.get(side) or []
            if not rows:
                continue
            lines.append(f"- **{label}**：")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sid = str(row.get("id") or "")
                opt = str(row.get("option") or "")
                lines.append(f"  - `{sid}`" + (f" · {opt}" if opt else ""))
        for p in pairs.get("conflicts") or []:
            if not isinstance(p, dict):
                continue
            a = str(p.get("support_id") or "")
            b = str(p.get("oppose_id") or "")
            reason = str(p.get("reason") or "")
            lines.append(
                f"- 成对：`{a}` ↔ `{b}`"
                + (f"（{reason}）" if reason else "")
            )
    elif isinstance(pairs, list):
        for p in pairs:
            if not isinstance(p, dict):
                continue
            a = str(p.get("support_id") or p.get("a") or "")
            b = str(p.get("oppose_id") or p.get("b") or "")
            lines.append(f"- 成对：`{a}` ↔ `{b}`")
    lines.append("")


def _render_conflicts_section(lines: list[str], dossier: Dossier) -> None:
    drop_note = str(
        ((dossier.accounting or {}).get("conflict_drops") or {}).get("note")
        or "").strip()
    if not dossier.conflicts and not drop_note:
        return
    lines += ["## 分歧识别与消解", ""]
    if drop_note:
        lines += [f"**配对丢弃**：{drop_note}", ""]
    if not dossier.conflicts:
        lines += ["（无进入裁决的冲突对）", ""]
        return
    for c in dossier.conflicts:
        pair_lines = [
            f"### 冲突：{c.get('topic') or '结论对立'}",
            "",
            f"- 甲方：`{c['a_id']}` {dossier.statement_of(c['a_id'])}",
            f"- 乙方：`{c['b_id']}` {dossier.statement_of(c['b_id'])}",
        ]
        res = c.get("resolution")
        if res:
            winner = res.get("winner_id")
            winner_text = ("未决（tie，双方证据势均力敌）" if winner == "tie"
                           else f"`{winner}` {dossier.statement_of(winner)}")
            method = res.get("method") or "arbitration"
            method_cn = {
                "evidence_weight": "程序按证据强度否决票数",
                "tie": "证据势均力敌（未决）",
                "arbitration": "仲裁",
                "source_majority": "独立信源数破平",
            }.get(method, method)
            pair_lines += [f"- **裁决**：{winner_text}",
                           f"- 裁决方式：{method_cn}",
                           f"- 理由：{res.get('rationale', '')}",
                           f"- 证据强度对比：{res.get('evidence_weight')}"]
            if res.get("resolution_type"):
                pair_lines.append(f"- 消解类型：{res.get('resolution_type')}")
            basis = res.get("basis") if isinstance(res.get("basis"), dict) else {}
            path = res.get("decision_path") or basis.get("decision_path") or ""
            if path:
                pair_lines.append(f"- 判定路径：{path}")
            if basis.get("type_applies"):
                pair_lines.append(f"- 类型为何适用：{basis['type_applies']}")
            if basis.get("loser_excluded"):
                pair_lines.append(f"- 冲突侧为何被排除：{basis['loser_excluded']}")
            if res.get("重启条件"):
                pair_lines.append(f"- 重启条件：{res.get('重启条件')}")
            if path == "source_majority":
                pair_lines.append(
                    "- 破平说明：依据用户口径 2026-10-16＋官方 decks:325 "
                    "可扩展条款，未经 A/B")
            rebuts = res.get("rebuts") or {}
            if rebuts:
                pair_lines.append("- 质证摘要：" + "；".join(
                    f"{side}方『{text[:80]}…』" for side, text in rebuts.items()))
        else:
            pair_lines.append("- **裁决**：未消解（仲裁不可用，双方并列保留）")
        lines += pair_lines + [""]


def _render_dissent_section(lines: list[str], dossier: Dossier) -> None:
    from app.core.panel_attrition import author_count_label

    dissents = dissent_conclusions(dossier)
    if not dissents:
        return
    human_losers: dict[str, str] = {}
    for raw in dossier.conflicts or []:
        if not isinstance(raw, dict):
            continue
        res = raw.get("resolution") if isinstance(raw.get("resolution"), dict) else {}
        if str(res.get("decision_path") or "") != "human_override":
            continue
        winner = str(res.get("winner_id") or "")
        a_id, b_id = str(raw.get("a_id") or ""), str(raw.get("b_id") or "")
        if winner not in (a_id, b_id):
            continue
        loser = b_id if winner == a_id else a_id
        mech = ""
        basis = res.get("basis") if isinstance(res.get("basis"), dict) else {}
        mech = str(basis.get("mechanical_path") or "")
        human_losers[loser] = mech or "llm_arbitration"
    lines += ["## 少数意见（依规保留）", ""]
    for con in dissents:
        if con.id in human_losers:
            tag = f"人工改判后未采信（原机械判断：{human_losers[con.id]}）"
        else:
            tag = "经仲裁证据加权后列为少数意见，原始证据保留可查"
        lines.append(
            f"- 「{con.statement}」（研判方："
            f"{'、'.join(con.author_names()) or 'N/A'}"
            f"{author_count_label(con)}）——{tag}")
    lines.append("")


def _render_dependency_section(lines: list[str], dossier: Dossier) -> None:
    """C-13：依赖边披露（report.md 内对本文为真；点名工件与端点）。"""
    dep = (dossier.accounting or {}).get("dependency")
    if not dep and not any(c.depends_on or c.premise_broken
                           for c in dossier.conclusions):
        return
    lines += ["## 结论依赖（推理中间层）", ""]
    from app.core.dependency import NOTE_AB, NOTE_NARROW

    lines.append(f"- {NOTE_NARROW}（见 report.md 本节）")
    lines.append(f"- {NOTE_AB}")
    if dep:
        note = str(dep.get("note") or "").strip()
        n_edges = int(dep.get("n_edges") or 0)
        lines.append(f"- 本跑次机械落边 **{n_edges}** 条"
                     + (f"；{note}" if note else ""))
        for d in dep.get("disclosures") or []:
            text = str(d).strip()
            if not text or text in (NOTE_NARROW, NOTE_AB):
                continue
            lines.append(f"- ⚠️ {text}")
    broken = [
        c for c in dossier.conclusions if c.premise_broken
    ]
    if broken:
        lines.append("- 前提失效黄牌（只亮牌，未自动删除或改写下游）：")
        for c in broken:
            lines.append(
                f"  - `{c.id}` ← 失效上游 "
                f"{'、'.join(f'`{x}`' for x in c.premise_broken)}")
    lines.append("")


def _render_confidence_bands(lines: list[str], dossier: Dossier) -> None:
    """首屏两套档条数（本案卷面；含 0 条的档；不进 confidence_note）。"""
    from app.core.confidence import band_count_dict, row_score_of

    scores = [
        row_score_of(c.confidence_parts)
        for c in dossier.conclusions
        if c.status == "majority"
    ]
    n = len(scores)
    abs_c = band_count_dict(scores, absolute=True)
    rel_c = band_count_dict(scores, absolute=False)
    lines += [
        f"**置信度档（本案卷 {n} 条）**：",
        (
            f"- 绝对档 band（高阈值 0.8＝官方达标行原文；中阈值 0.5＝我方设定）："
            f"高置信（≥0.8）：{abs_c['高']} 条 · 中：{abs_c['中']} 条 · 低：{abs_c['低']} 条"
        ),
        (
            f"- 相对档 band_rel（同跑次 34%/67% 分位，本案卷面）："
            f"高：{rel_c['高']} 条 · 中：{rel_c['中']} 条 · 低：{rel_c['低']} 条"
            f" · 不可分：{rel_c.get('不可分', 0)} 条"
        ),
    ]
    from app.core.evidence import conclusion_face, format_conclusion_face_line

    face = conclusion_face(dossier)
    lines += [
        f"- {format_conclusion_face_line(face, surface='本案卷')}",
        "",
    ]


def _render_fact_collisions(lines: list[str], dossier: Dossier) -> None:
    """资料内数字冲突（事实层对撞，独立于结论级冲突）：分析师漏看也兜底。

    章旁一行写「未采信数字分类计数」（真分母机械不可知，只披露分类计数）。
    优先用 accounting 里已落盘的 stats；否则一次 _scan 兼得对撞与计数。
    C-78：开关开时在对撞行末追加「组内相对偏差」派生标签（不改检出）。
    """
    from app.core.fact_ledger import (
        _collisions_from_facts,
        _scan,
        build_dispersion_tag_map,
        dispersion_notes_for_facts,
        format_canon_disclosure,
        format_dropped_disclosure,
        ledger_outlier_tag_enabled,
        metric_canon_enabled,
    )

    stats = (dossier.accounting or {}).get("fact_ledger_stats")
    tag_on = ledger_outlier_tag_enabled()
    if stats is None:
        facts, stats = _scan(dossier)
        collisions = _collisions_from_facts(facts)
    elif tag_on:
        facts, _ = _scan(dossier)
        collisions = find_collisions(dossier, facts=facts)
    else:
        facts = []
        collisions = find_collisions(dossier)
    dropped = stats.get("dropped") or {}
    has_drop = any(int(v or 0) > 0 for v in dropped.values())
    if not collisions and not has_drop:
        return
    # 三分支章名：有对撞保留「冲突」；仅未采信改名，避免读者以为有冲突没列
    if collisions:
        lines += ["## 资料内数字冲突（事实层对撞）", ""]
    else:
        lines += ["## 台账未采信数字分类计数", ""]
    lines.append(f"- {format_dropped_disclosure(stats)}")
    # C-80：规范量名覆盖一行（生产者披露；「缺规范量名」预检贴标后置）
    if metric_canon_enabled() and (stats.get("metric_canon") is not None):
        lines.append(f"- {format_canon_disclosure(stats)}")
    tag_map = build_dispersion_tag_map(facts, k=3) if tag_on else {}
    for c in collisions:
        detail = "；".join(
            f"`{f.source_id}` 说 **{f.entity or '（未指明主体）'}{f.metric}** {f.raw}"
            + (f"（时点 {f.date}）" if f.date else "")
            for f in c.facts)
        tag = "跨信源" if c.cross_source else "同信源前后矛盾"
        line = f"- [{tag}] {detail}"
        notes = dispersion_notes_for_facts(c.facts, tag_map)
        if notes:
            line += "；" + "；".join(notes)
        lines.append(line)
    lines.append("")



def _render_precedent_section_lines(
    dossier: Dossier, *, rest_chars: int,
) -> list[str]:
    """同类事件对照（案卷内）节正文；rest_chars＝其余节合计（C-29 R1 双上限）。"""
    from app.core.precedent import render_precedent_lines
    return render_precedent_lines(dossier, rest_chars=rest_chars)


def _render_precedent_section(lines: list[str], dossier: Dossier) -> None:
    """兼容入口：无 rest 时只走行数帽（单测／探针直调）。"""
    from app.core.precedent import render_precedent_lines
    lines += render_precedent_lines(dossier)


def _render_window_ledger(lines: list[str], dossier: Dossier) -> None:
    """C-73：窗口账一行。无真数也必须在场（「服务端未报，未据此判定」）。"""
    from app.core.prompt_guard import format_window_ledger_line

    led = (dossier.accounting or {}).get("window_ledger")
    # 无账也渲一行（离线重放旧产物／早退）——不许省略
    line = format_window_ledger_line(led if isinstance(led, dict) else {})
    lines += [line, ""]


def _render_prompt_window(lines: list[str], dossier: Dossier) -> None:
    """模型窗口出口披露（C-9）：超窗一条；关闭检查写「未检查」。"""
    notes = [n for n in dossier.ingest_notes
             if n.get("kind") == "prompt_over_window"]
    pw = (dossier.accounting or {}).get("prompt_window") or {}
    pack_w = (dossier.accounting or {}).get("pack_window") or {}
    unfit = [n for n in dossier.ingest_notes
             if n.get("kind") == "pack_window_unfit"]
    if notes or unfit or pack_w or pw.get("status") == "unchecked":
        lines += ["## 模型窗口出口披露", ""]
        if pack_w:
            rule = str(pack_w.get("rule") or "")
            if rule in ("disabled", "unchecked"):
                reason = ("VERITAS_PACK_TO_WINDOW=0" if rule == "disabled"
                          else "model_context_tokens≤0")
                lines.append(
                    f"- 窗口对齐装箱未启用（原因＝{reason}），"
                    f"本次按字预算 {pack_w.get('budget')} 装箱"
                )
            else:
                win = pack_w.get("window_tokens")
                base = (
                    f"- 本次按假定窗口 {win} 装箱"
                    f"（budget={pack_w.get('budget')}，"
                    f"est≈{pack_w.get('est_tokens')} token，"
                    f"迭代 {pack_w.get('n_iters')}，"
                    f"fits={pack_w.get('fits')}）"
                )
                if ("未检查" in rule
                        or pack_w.get("window_source") in (
                            "fallback", "unchecked_global")):
                    detail = str(pack_w.get("window_detail") or (
                        f"窗口未检查（端点不可探，沿用全局 {win}）"
                        f"＝假定值，不是实测"
                    ))
                    lines.append(
                        f"{base}；窗口来源＝{detail}；"
                        f"若现场更大请调 `VERITAS_MODEL_CTX_TOKENS`／"
                        f"`model_context_tokens_by_model`；"
                        f"关闭＝`VERITAS_PACK_TO_WINDOW=0`"
                    )
                else:
                    lines.append(
                        f"{base}；"
                        f"若现场模型窗口更大请调 `VERITAS_MODEL_CTX_TOKENS`；"
                        f"关闭＝`VERITAS_PACK_TO_WINDOW=0`"
                    )
        for n in unfit:
            lines.append(f"- {n.get('detail') or ''}")
        for n in notes:
            lines.append(f"- {n.get('detail') or ''}")
        if not notes and not unfit and pw.get("status") == "unchecked" and not pack_w:
            lines.append(f"- 未检查：{pw.get('detail') or 'model_context_tokens≤0'}")
        lines.append("")
        return
    if pw.get("status") == "unchecked":
        lines += ["## 模型窗口出口披露", ""]
        lines.append(f"- 未检查：{pw.get('detail') or 'model_context_tokens≤0'}")
        lines.append("")


def _render_excluded_sources(lines: list[str], dossier: Dossier) -> None:
    """丢弃必须可见：预算裁剪、零相关/重复排除、摄取失败三类披露。"""
    from app.core.dup_check import duplicate_map
    from app.core.kg_submit_surface import pack_kwargs_for_kg
    from app.core.material import WINDOW_EXCLUDE_REASON, pack_material
    from app.core.relevance import classify_sources

    pack = pack_material(dossier, **pack_kwargs_for_kg(dossier))
    mb = (dossier.accounting or {}).get("multi_box") or {}
    if isinstance(mb, dict) and int(mb.get("n_boxes") or 0) > 1:
        lines += ["## 续盒（多箱）", ""]
        per = mb.get("per_box") or []
        parts = [
            f"第{b.get('index')}箱 {b.get('n_selected')} 段"
            for b in per if isinstance(b, dict)
        ]
        lines.append(
            f"- 共 {mb.get('n_boxes')} 箱"
            f"（上限 {mb.get('max_boxes')}）："
            + ("；".join(parts) if parts else "无明细")
        )
        lines.append(
            f"- 并集装入 {mb.get('n_union')} 段"
            f"（首箱 {len(pack.get('selected') or [])} 段；"
            f"续盒状态 {mb.get('status') or 'planned'}）"
        )
        lines.append(
            "- 墙钟随盒数上升；并集到达 ≠ 官方得分涨分。"
        )
        lines.append("")
    if pack["excluded"]:
        lines += ["## 因预算未进入研判的段落", ""]
        # 续盒开启时：名单仍按首箱 excluded；并集已覆盖段在文案里注明
        union = set()
        if isinstance(mb, dict):
            union = {str(x) for x in (mb.get("union_selected") or [])}
        by_source: dict[str, list[tuple[str, str]]] = {}
        for e in pack["excluded"]:
            by_source.setdefault(e["source_id"], []).append(
                (e["seg_id"], str(e.get("reason") or "")))
        for sid in sorted(by_source):
            items = sorted(by_source[sid], key=lambda x: x[0])
            segs = [g for g, _ in items]
            reasons = {r for _, r in items if r}
            sample = "、".join(segs[:3]) + (" 等" if len(segs) > 3 else "")
            covered = sum(1 for g in segs if g in union)
            if WINDOW_EXCLUDE_REASON in reasons:
                why = WINDOW_EXCLUDE_REASON
            elif "BM25 排序未入预算" in reasons:
                why = "BM25 排序后超出资料预算，未进入分析师视野"
            else:
                why = "超出资料预算，未进入分析师视野"
            extra = (
                f"；其中 {covered} 段已由续盒补入"
                if covered else ""
            )
            lines.append(
                f"- `{sid}`：{len(segs)} 段（{sample}）——{why}{extra}")
        lines.append("")

    from app.core.relevance import (
        relevance_aggregate, relevance_soft_gate_enabled,
    )

    entries: list[tuple[str, str, str]] = []  # (source_id, title, reason)
    soft_on = relevance_soft_gate_enabled()
    agg_line = ""
    if soft_on:
        # C-70 件⑥：聚合披露、不许留白；禁用比率词
        agg = relevance_aggregate(dossier)
        agg_line = str(agg.get("line") or "")
        dossier.accounting.setdefault("relevance_soft", agg)
    else:
        for s in classify_sources(dossier):
            if s["level"] == "zero":
                entries.append((s["source_id"], s["title"], s["reason"]))
    dups = duplicate_map(dossier)
    for src in dossier.sources:
        if src.id in dups:
            entries.append((src.id, src.title,
                            f"与 {dups[src.id]} 内容完全重复——不重复进入研判，"
                            "防止一致性虚增"))
    # 出口披露单列，不混进摄取披露章（pack_window_unfit 已在「模型窗口出口披露」）
    ingest = [n for n in dossier.ingest_notes
              if n.get("kind") not in (
                  "corpus_select", "prompt_over_window", "pack_window_unfit")]
    if not entries and not ingest and not agg_line:
        return
    lines += ["## 未采信信源（未进入分析师视野）", ""]
    if soft_on and agg_line:
        lines.append(f"- {agg_line}")
    for sid, title, reason in entries:
        lines.append(f"- `{sid}`《{title}》——{reason}")
    if not entries and not agg_line:
        lines.append("（无——全部信源均进入研判）")
    lines.append("")
    if ingest:
        lines += ["## 摄取披露（解析失败 / 空文件 / 图像内容）", ""]
        for n in ingest:
            lines.append(f"- `{n['file']}`[{n['kind']}]：{n['detail']}")
        lines.append("")


def run_official_case(case_dir: Path, questions: list[dict], out_dir: Path,
                      settings: Settings | None = None,
                      roster: list | None = None,
                      deps: RunDeps | None = None) -> list[PipelineResult]:
    """一案多题：官方文档只载入一次，每题各跑一遍，再导出四份 JSON。

    不读取证据样例或结论样例里的答案字段。
    """
    from app.export.official import export_official
    from app.ingest.official_case import load_official_case
    from app.core.temporal_check import set_source_time_unified
    from app.core.fact_ledger import (
        set_ledger_outlier_tag, set_ledger_time_class, set_metric_canon,
    )
    from app.core.precedent import set_evolve_value_change
    from app.core.relevance import set_relevance_soft_gate

    # 须在 load_official_case 前落地（件③ 三态 detail 读旗）
    _settings = settings or Settings.from_env()
    set_source_time_unified(bool(getattr(_settings, "source_time_unified", True)))
    set_ledger_time_class(bool(getattr(_settings, "ledger_time_class", True)))
    set_ledger_outlier_tag(bool(getattr(_settings, "ledger_outlier_tag", True)))
    set_metric_canon(bool(getattr(_settings, "metric_canon", True)))
    set_evolve_value_change(bool(getattr(_settings, "evolve_value_change", True)))
    set_relevance_soft_gate(bool(getattr(_settings, "relevance_soft_gate", True)))
    from app.core.claim_slots import set_claim_slots
    set_claim_slots(bool(getattr(_settings, "claim_slots", False)))

    base = load_official_case(case_dir)
    deps = deps or RunDeps()
    settings = _settings
    results: list[PipelineResult] = []
    runs: list[tuple[dict, Dossier]] = []
    for question in questions:
        snap = Dossier.from_dict(base.to_dict())
        snap.question = str(question["question"])
        result = run_case(RunSpec(
            dossier=snap,
            out_dir=Path(out_dir) / "questions" / str(question["question_id"]),
            settings=settings,
            roster=roster,
            probe=False if deps.client is not None or deps.analysts is not None else None,
        ), deps)
        results.append(result)
        runs.append((question, result.dossier))
    export_official(runs, out_dir)
    return results


def main() -> int:
    # Windows 防线：stdout 被重定向/管道时 Python 落回 GBK 代码页，
    # print 中文报告会 UnicodeEncodeError（token-burner 实证教训）——
    # 进 main 即钉死 UTF-8，乱码最多一行，绝不假红。
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="veritas 研判管线")
    parser.add_argument("case_dir", help="案例目录（含 manifest.yaml 与资料文件）")
    parser.add_argument("--out", default=None, help="报告输出目录（默认 cases/<case>/out）")
    parser.add_argument("--model", default=None, help="覆盖编队模型")
    parser.add_argument("--roster", default=None,
                        help="自定义编队 YAML 路径（{roster:[{name,persona}...]}，至少 2 人）")
    parser.add_argument("--fetch-links", action="store_true",
                        help="抓取链接清单文件中的网页为信源（默认关；"
                             "逐条披露成败，抓回内容过全套机械闸）")
    parser.add_argument("--questions", default=None,
                        help="官方案卷问题清单 JSON（仅 question_id 与 question；"
                             "默认 <case>/questions.json）")
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.fetch_links:
        settings.fetch_links_enabled = True
    if args.model:
        settings.models = [args.model, *settings.models]
    roster = None
    if args.roster:
        try:
            roster = load_roster(Path(args.roster))
        except (ValueError, OSError) as exc:
            raise SystemExit(f"编队配置加载失败: {exc}")

    case_dir = Path(args.case_dir)
    out_dir = Path(args.out or (case_dir / "out"))
    if (case_dir / "raw_documents.json").is_file():
        from app.ingest.official_case import load_question_list

        qpath = Path(args.questions) if args.questions else (case_dir / "questions.json")
        if not qpath.is_file():
            raise SystemExit(
                "官方案卷需要问题清单（--questions 或 questions.json），"
                "且只读取 question_id 与 question")
        questions = load_question_list(qpath)
        run_official_case(case_dir, questions, out_dir, settings=settings, roster=roster)
        print(f"官方提交物已写入 {out_dir}")
        return 0

    result = run_case(RunSpec(
        case_dir=case_dir, out_dir=out_dir, roster=roster))
    print(result.report_md)
    print(f"报告与日志已写入 {result.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
