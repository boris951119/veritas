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
from app.core.audit import audit_all, summarize
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
from app.core.fact_ledger import extract_facts, find_collisions
from app.core.hashchain import HashChain
from app.core.material import pack_material, set_material_budget
from app.core.numeric_check import audit_conservation, audit_counting, audit_numeric
from app.core.premise_check import premise_flags
from app.core.relevance import classify_sources
from app.core.skills import detect_skills, set_skills_enabled, skills_enabled
from app.core.untrusted import scan_injections
from app.ingest.case_loader import load_case
from app.llm.budget import BudgetGuard, set_active_budget_guard
from app.llm.model_client import ModelClient, ModelClientFactory
from app.llm.profile import probe_model


def touch_progress() -> None:
    """进展心跳钩子（model_client 每次成功响应后调用；当前 no-op，
    预留给工作台的看门狗与 SSE 流）。"""
    return None


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


@dataclass
class RunDeps:
    """测试/调用方注入面：桩 client、预构建 analysts、coordinator。"""

    client: ModelClient | None = None
    analysts: list[Analyst] | None = None
    coordinator: Coordinator | None = None


def run_case(spec: RunSpec | None = None,
             deps: RunDeps | None = None) -> PipelineResult:
    """跑一次完整研判。deps 可注入桩（测试零 key）。"""
    spec = spec or RunSpec()
    deps = deps or RunDeps()
    settings = spec.settings or Settings.from_env()
    client = deps.client
    analysts = deps.analysts
    injected_client = client is not None
    dossier = spec.dossier or load_case(
        Path(spec.case_dir), fetch_links=settings.fetch_links_enabled)
    chain = HashChain()
    chain.append("case_loaded", "pipeline", {
        "question": dossier.question,
        "n_sources": len(dossier.sources),
        "n_segments": sum(len(s.segments) for s in dossier.sources),
    })
    # 0) 议题前提核对（零 LLM）：问题实体在信源零命中 → 亮灯前置
    premise = premise_flags(dossier)
    chain.append("premise_check", "pipeline", summarize(premise))
    # 0.2) 事实对撞台账：同(实体,指标)不同值的信源打架（分析师漏看也兜底）
    collisions = find_collisions(dossier)
    chain.append("fact_ledger", "pipeline", {
        "n_facts": len(extract_facts(dossier)),
        "n_collisions": len(collisions),
        "cross_source": sum(1 for c in collisions if c.cross_source),
    })
    # 0.3) 输入防御：注入扫描 + 重复/同源检测（摄入隔离披露随案卷落盘）
    chain.append("injection_scan", "pipeline",
                 {"n_suspects": len(scan_injections(dossier))})
    chain.append("dup_check", "pipeline", {
        "n_duplicates": len(duplicate_map(dossier)),
        "n_near_dup_pairs": len(near_dup_pairs(dossier)),
    })
    if dossier.ingest_notes:
        chain.append("ingest_notes", "pipeline",
                     {"n_notes": len(dossier.ingest_notes),
                      "kinds": sorted({n["kind"] for n in dossier.ingest_notes})})
    # 0.4) 相关性分层：零相关信源不进分析师视野（报告披露，绝不静默）
    relevance = classify_sources(dossier)
    chain.append("relevance_layered", "pipeline", {
        "high": sum(1 for r in relevance if r["level"] == "high"),
        "low": sum(1 for r in relevance if r["level"] == "low"),
        "zero": sum(1 for r in relevance if r["level"] == "zero"),
    })
    # 0.5) skill 注册表按案卷特征触发（命中才注入分析师提示词，入链留痕；
    #      VERITAS_SKILLS=0 可整体关注入入——A/B 对照组只关「教」不关「验」）
    set_skills_enabled(settings.skills_enabled)
    set_material_budget(settings.material_char_budget)
    if client is None:
        client = ModelClientFactory(settings).create()

    # 0.55) 图片转码（模型只当转码器）：网关有视觉端点且开启时，
    # 已披露图片逐张转写为低可信派生信源；失败逐张降级回披露。
    # 桩客户端（测试注入）不触发，离线演示不受影响。
    if settings.ocr_enabled and dossier.ingest_notes and client is not None:
        from app.ingest.ocr import transcode_images

        try:
            ocr_result = transcode_images(dossier, client, settings.models[0])
            if ocr_result.get("n_pending"):
                chain.append("image_ocr", "pipeline", ocr_result)
        except Exception as exc:  # 转码整体失败：维持披露，不炸 run
            chain.append("image_ocr", "pipeline",
                         {"error": f"{type(exc).__name__}: {exc}"})

    chain.append("skills_triggered", "pipeline",
                 {"skills": [s.name for s in detect_skills(dossier)],
                  "injection": skills_enabled()})
    # 0.6) 资料预算装箱：BM25 精排 + 跨信源轮转，装不下的全披露
    pack = pack_material(dossier, settings.material_char_budget)
    chain.append("material_pack", "pipeline", {
        "budget": pack["budget"],
        "n_total": pack["n_total"],
        "n_selected": len(pack["selected"]),
        "n_excluded": len(pack["excluded"]),
    })

    guard = BudgetGuard(settings.budget_tokens, settings.budget_throttle_threshold)
    set_active_budget_guard(guard)

    if analysts is None:
        analysts = build_panel(client, settings.models[0], roster=spec.roster)

    # 0.8) 模型画像自适应：探测档位 → 回填分析师（决定建议版/强化版规则）
    adaptive = bool(spec.probe) if spec.probe is not None else not injected_client
    tier = "standard"
    if adaptive and settings.model_probe_enabled and settings.models:
        try:
            profile = probe_model(client, settings.models[0])
            tier = profile["tier"]
            chain.append("model_profile", "pipeline", profile)
        except Exception as exc:  # 探测失败不炸管线：维持 standard 档
            chain.append("model_profile", "pipeline",
                         {"tier": "standard", "error": f"{type(exc).__name__}: {exc}"})
    for a in analysts:
        a.profile_tier = tier

    # 1) 并行独立研判（硬隔离；单分析师失败只降级）
    results = run_panel(dossier, analysts, on_done=lambda name, cons: chain.append(
        "analyst_done", name, {"n_conclusions": len(cons)}))
    for name, err in results.get("_failures", {}).items():
        chain.append("analyst_failed", name, {"error": err})
    # 并行完成次序不定 → 物化次序随机：统一排序固化产物确定性
    # （内容全同仅次序不同的两跑差异，归一化 diff 验收逼出来的收口）
    dossier.conclusions.sort(key=lambda c: (c.statement, c.author))
    # 键不以 conclusion_id 打头（组 id 是 uuid，跨跑随机）——语义字段
    # 定序、id 只做全同兜底：组内/组间次序与随机 id 无关
    _ev_key = lambda e: (e.quote, tuple(e.segment_ids), e.level.value,
                          e.relation.value, e.author, e.note, e.conclusion_id)
    dossier.evidences.sort(key=_ev_key)
    if results.get("_failures") and not majority_conclusions(dossier):
        raise RuntimeError(f"全部分析师研判失败: {results['_failures']}")

    # 2) 引文机械核对（协同段之前：坏证据不进归并与仲裁）
    rejected = _reject_failed_citations(dossier, chain)
    dossier.rejected = rejected  # 持久化进 report.json（工作台展示）
    # 2.5) 数字机械核对（计算复算 + 数字溯源 + 计数，零 LLM；警示不剔除结论）
    numeric = audit_numeric(dossier) + audit_counting(dossier)
    # 2.6) 打回修复环（自适应档）：把违规明细定向发回原分析师重写一次，
    #      变好才接受；仅生产路径启用，桩/离线演示保持确定不变
    if adaptive and numeric:
        from app.agents.repair import RepairCtx, run_repair_round

        repair = run_repair_round(dossier, numeric, RepairCtx(
            client=client, model=settings.models[0], analysts=analysts))
        numeric = audit_numeric(dossier) + audit_counting(dossier)
        chain.append("repair_round", "pipeline",
                     {**repair, "flags_after": summarize(numeric)})
    chain.append("numeric_audit", "pipeline", summarize(numeric))

    # 3) 协同段：归并 → 冲突 → 质证 → 仲裁（≥2 分析师才走；逐步降级）
    if len(analysts) >= 2:
        _run_collaboration(dossier, CollabCtx(
            chain=chain, client=client, model=settings.models[0],
            analysts=analysts, coordinator=deps.coordinator))

    # 3.45) 归并改写了证据归属 → 再排序固化组内次序（确定性收口之二）
    # 键不以 conclusion_id 打头（组 id 是 uuid，跨跑随机）——语义字段
    # 定序、id 只做全同兜底：组内/组间次序与随机 id 无关
    _ev_key = lambda e: (e.quote, tuple(e.segment_ids), e.level.value,
                          e.relation.value, e.author, e.note, e.conclusion_id)
    dossier.evidences.sort(key=_ev_key)

    # 3.5) 协同段话语机械核对：归并守恒 + 质证/仲裁引用 + 措辞匹配（零 LLM）
    discourse = (audit_conservation(dossier) + audit_discourse(dossier)
                 + audit_hedge(dossier) + audit_level_tone(dossier))
    chain.append("discourse_audit", "pipeline", summarize(discourse))

    # 4) 置信度融合 + 收口
    recompute_all(dossier, n_panel=len(analysts))
    chain.append("confidence_computed", "pipeline", {
        "n_majority": len(majority_conclusions(dossier)),
        "n_dissent": len(dissent_conclusions(dossier)),
    })

    # 4.5) 主席汇总（仲裁汇总的「汇总」半边）：把已过闸结论组装成面向
    # 议题的答案。生产路径走 LLM+四道闸（违规点模板顶替），桩/离线
    # 直接模板——报告永远有综合意见。
    from app.agents.chair import build_synthesis

    chair_client = None if injected_client else client
    synthesis = build_synthesis(dossier, chair_client, settings.models[0])
    chain.append("chair_summary", "pipeline", {
        "mode": synthesis.get("mode"),
        "n_points": len(synthesis.get("points") or []),
        "n_auto_filled": sum(1 for p in synthesis.get("points") or []
                             if p.get("auto")),
        "n_open_issues": len(synthesis.get("open_issues") or []),
        "gate_notes": synthesis.get("gate_notes") or [],
    })
    chain.append("report_finalized", "pipeline", {"question": dossier.question})

    result = PipelineResult(dossier=dossier, chain=chain, rejected=rejected)

    if spec.out_dir is not None:
        out_dir = Path(spec.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        dossier.to_json(out_dir / "report.json")
        (out_dir / "report.md").write_text(result.report_md, encoding="utf-8")
        chain.to_jsonl(out_dir / "chain.jsonl")
        result.out_dir = out_dir
    return result


# ----------------------------------------------------------------------


def _reject_failed_citations(dossier: Dossier, chain: HashChain) -> list[dict]:
    """引文打回：不合格证据移除并留痕，返回打回清单。

    证据被全部打回的结论一并移出案卷（不进归并与报告）——零证据结论
    留在主表只会展示 0 置信度空壳；打回明细在本清单与 chain 中可查。"""
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
    empties = [c for c in dossier.conclusions if not dossier.evidences_of(c.id)]
    for con in empties:
        dossier.conclusions.remove(con)
    chain.append("citation_audit", "pipeline", {
        "n_verified": sum(1 for e in dossier.evidences if e.verified),
        "n_rejected": len(rejected),
        "n_conclusions_dropped": len(empties),
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
    chain.append("conflicts_detected", "coordinator", {"n_pairs": len(pairs)})

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
                "pair_id": pair.id, "winner": pair.resolution.winner_id})


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
        f"**资料**：{len(dossier.sources)} 份信源 / "
        f"{sum(len(s.segments) for s in dossier.sources)} 个段落",
        "",
        "## 结论",
        "",
    ]
    majors = majority_conclusions(dossier)
    if not majors:
        lines.append("（无结论——检查资料覆盖或分析师输出）")
    majors.sort(key=lambda c: c.confidence, reverse=True)
    for con in majors:
        lines.append(f"### {con.statement}")
        lines.append("")
        lines.append(f"- 置信度：**{con.confidence:.2f}**（{con.confidence_parts}）")
        lines.append(f"- 研判方：{'、'.join(con.author_names()) or 'N/A'}")
        _render_evidence_table(lines, dossier, con)
        lines.append("")

    _render_question_preflight(lines, dossier)
    _render_synthesis(lines, dossier)
    _render_triage_ledger(lines, dossier)
    _render_conflicts_section(lines, dossier)
    _render_dissent_section(lines, dossier)
    _render_fact_collisions(lines, dossier)
    _render_excluded_sources(lines, dossier)

    if rejected:
        lines += ["## 被打回的证据（引文核对未通过）", ""]
        for r in rejected:
            lines.append(f"- `{r['evidence_id']}`：{'; '.join(r['problems'])}"
                         f"（引文：{r['quote'][:60]}…）")
        lines.append("")

    _render_flags_section(lines, dossier)

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
}


def _render_flags_section(lines: list[str], dossier: Dossier) -> None:
    """机械核对警示（零 LLM 复算）：报告落定后再全案卷扫一遍。

    红（high）=算式复算不符/输入造假；黄（medium）=来源外数字、归并
    概括漂移、质证疑似歪曲、前提未覆盖等。警示不剔除内容——语义取舍
    仍归分析师与读者，机械侧只保证「每个数字都能对账」。"""
    flags = audit_all(dossier)
    lines += ["## 机械核对警示（零 LLM 复算）", ""]
    if not flags:
        lines += ["- 计算复算、数字溯源、议题前提、质证/仲裁引用：全部通过 ✅", ""]
        return
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
    evs = dossier.evidences_of(con.id)
    if not evs:
        return
    lines += ["", "| 逐字引文 | 出处 | 等级 | 关系 | 说明 |", "|---|---|---|---|---|"]
    for ev in evs:
        seg = dossier.segment(ev.segment_ids[0]) if ev.segment_ids else None
        where = ev.segment_ids[0] + (f"（{seg.locator}）" if seg else "")
        quote = ev.quote.replace("|", "\\|").replace("\n", " ")
        note = ev.note.replace("|", "\\|")
        lines.append(f"| {quote} | {where} | {ev.level.value} | {ev.relation.value} | {note} |")


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
    issues = synthesis.get("open_issues") or []
    if issues:
        lines += ["", "**分歧与缺口（明示，不抹平）**："]
        kind_cn = {"conflict": "冲突", "dissent": "少数意见",
                   "gap": "资料缺口", "note": "说明"}
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


def _render_conflicts_section(lines: list[str], dossier: Dossier) -> None:
    if not dossier.conflicts:
        return
    lines += ["## 分歧识别与消解", ""]
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
            pair_lines += [f"- **裁决**：{winner_text}",
                           f"- 理由：{res.get('rationale', '')}",
                           f"- 证据强度对比：{res.get('evidence_weight')}"]
            rebuts = res.get("rebuts") or {}
            if rebuts:
                pair_lines.append("- 质证摘要：" + "；".join(
                    f"{side}方『{text[:80]}…』" for side, text in rebuts.items()))
        else:
            pair_lines.append("- **裁决**：未消解（仲裁不可用，双方并列保留）")
        lines += pair_lines + [""]


def _render_dissent_section(lines: list[str], dossier: Dossier) -> None:
    dissents = dissent_conclusions(dossier)
    if not dissents:
        return
    lines += ["## 少数意见（依规保留）", ""]
    for con in dissents:
        lines.append(f"- 「{con.statement}」（研判方："
                     f"{'、'.join(con.author_names()) or 'N/A'}）——"
                     "经仲裁证据加权后列为少数意见，原始证据保留可查")
    lines.append("")


def _render_fact_collisions(lines: list[str], dossier: Dossier) -> None:
    """资料内数字冲突（事实层对撞，独立于结论级冲突）：分析师漏看也兜底。"""
    from app.core.fact_ledger import find_collisions

    collisions = find_collisions(dossier)
    if not collisions:
        return
    lines += ["## 资料内数字冲突（事实层对撞）", ""]
    for c in collisions:
        detail = "；".join(
            f"`{f.source_id}` 说 **{f.entity or '（未指明主体）'}{f.metric}** {f.raw}"
            + (f"（时点 {f.date}）" if f.date else "")
            for f in c.facts)
        tag = "跨信源" if c.cross_source else "同信源前后矛盾"
        lines.append(f"- [{tag}] {detail}")
    lines.append("")


def _render_excluded_sources(lines: list[str], dossier: Dossier) -> None:
    """丢弃必须可见：预算裁剪、零相关/重复排除、摄取失败三类披露。"""
    from app.core.dup_check import duplicate_map
    from app.core.material import pack_material
    from app.core.relevance import classify_sources

    pack = pack_material(dossier)
    if pack["excluded"]:
        lines += ["## 因预算未进入研判的段落", ""]
        by_source: dict[str, list[str]] = {}
        for e in pack["excluded"]:
            by_source.setdefault(e["source_id"], []).append(e["seg_id"])
        for sid in sorted(by_source):
            segs = sorted(by_source[sid])
            sample = "、".join(segs[:3]) + (" 等" if len(segs) > 3 else "")
            lines.append(f"- `{sid}`：{len(segs)} 段（{sample}）"
                         "——BM25 排序后超出资料预算，未进入分析师视野")
        lines.append("")

    entries: list[tuple[str, str, str]] = []  # (source_id, title, reason)
    for s in classify_sources(dossier):
        if s["level"] == "zero":
            entries.append((s["source_id"], s["title"], s["reason"]))
    dups = duplicate_map(dossier)
    for src in dossier.sources:
        if src.id in dups:
            entries.append((src.id, src.title,
                            f"与 {dups[src.id]} 内容完全重复——不重复进入研判，"
                            "防止一致性虚增"))
    if not entries and not dossier.ingest_notes:
        return
    lines += ["## 未采信信源（未进入分析师视野）", ""]
    for sid, title, reason in entries:
        lines.append(f"- `{sid}`《{title}》——{reason}")
    if not entries:
        lines.append("（无——全部信源均进入研判）")
    lines.append("")
    if dossier.ingest_notes:
        lines += ["## 摄取披露（解析失败 / 空文件 / 图像内容）", ""]
        for n in dossier.ingest_notes:
            lines.append(f"- `{n['file']}`[{n['kind']}]：{n['detail']}")
        lines.append("")


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

    result = run_case(RunSpec(
        case_dir=Path(args.case_dir),
        out_dir=Path(args.out or (Path(args.case_dir) / "out")),
        roster=roster))
    print(result.report_md)
    print(f"报告与日志已写入 {result.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
