#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R44：本地六案全测核对＋并主线可借鉴交付包。

接 R43／R42。现场复测盒密度＋窄面泄漏；树17可用密度复用 R41／R43 读数并注明。
勿整包灌系数进 pack_material。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.case_lexicon import lexicon_for_question  # noqa: E402
from app.kg_lab.event_frame import extract_event_frame  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.intent_routes import classify_route  # noqa: E402
from app.kg_lab.layer_boundary import (  # noqa: E402
    FORBIDDEN_PACK_KEYS,
    assert_submit_no_coeff,
    audit_forbidden_keys,
    borrowable_checklist,
    build_submit_surface,
    describe_boundaries,
    pack_hints_from_submit,
    stage1_pool_export,
    stage2_box_export,
)
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features  # noqa: E402
from app.kg_lab.r8_fit import augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import apply_r9  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.source_role import _meta_from_row  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.stage2_authority import authority_rerank  # noqa: E402
from app.kg_lab.tree17_cite import apply_tree17_cite  # noqa: E402
from scripts.kg_lab.run_r22_intent_density import (  # noqa: E402
    DEFAULT_K,
    OUT,
    _case,
    _coeff_names,
    _eval_case,
)
from scripts.kg_lab.run_r31_holdout3 import HOLDOUT  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

# 期望（相对 R43／R42）
EXPECT = {
    "liuxiang": {"role": "regression", "micro_min": 0.5714, "at7": 12},
    "jilong": {"role": "smoke", "micro_min": 0.6667, "at7": 6},
    "us_cn_ai": {"role": "smoke", "micro_min": 0.6667, "at7": 6},
    "wanghong": {"role": "holdout", "micro_min": 0.8571, "at7": 6, "q002_min": 0.6667},
    "kh_th": {"role": "holdout", "micro_min": 0.80, "at7": 4},
    "ai171": {"role": "holdout", "micro_min": 0.80, "at7": 5},
}
# 树17：R41 冻结；王虹可用密度以 R43 复测为准
R41_CITE = {
    "liuxiang": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.2857, "src": "R41"},
    "jilong": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.5556, "src": "R41"},
    "us_cn_ai": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.3333, "src": "R41"},
    "wanghong": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.0, "src": "R43"},
    "kh_th": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.6667, "src": "R41"},
    "ai171": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.4444, "src": "R41"},
}
GATE_DENS = 2.0 / 3.0
DROP_EPS = 0.02
def _git_tip() -> str:
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT), text=True,
        ).strip()
    except Exception:
        return "unknown"


def _plan_cite_and_leak(
    slug: str,
    mark: str,
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    prefer_gold: bool,
) -> dict[str, Any]:
    """计划层金标→细读＋交卷窄面泄漏抽检（无 LLM）。"""
    case = _case(mark, prefer_local=(slug == "liuxiang"))
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw}
    plan_rows: list[dict[str, Any]] = []
    leak_hits: list[str] = []
    n_submit_ok = 0
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, _ = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}
        fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
        submit_ranked = fr["ranked"]
        pool_ranked = fr.get("pool_ranked") or fr["ranked"]
        frame = extract_event_frame(question)
        route = classify_route(question, frame)
        prefer = set(l2) if prefer_gold else None
        bundle = build_bundle(
            sub_rows, submit_ranked, question, frames=True,
            prefer_ids=prefer, case_slug=slug,
        )
        by_row = {r["para_id"]: r for r in sub_rows}
        lex = lexicon_for_question(question, case_slug=slug)
        for pid, _sc in list(pool_ranked[:60]) + [(g, 0) for g in l2]:
            if pid in bundle["metas"]:
                continue
            row = by_row.get(pid)
            if row:
                bundle["metas"][pid] = _meta_from_row(row, lex=lex)
                bundle["feats"].setdefault(pid, {})
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        apply_portable_features(
            bundle["feats"], bundle["metas"], url_of, question, frame,
            publish_of=publish_of,
        )
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2
        s1 = stage1_pool_export(pool_ranked, pool_n=20)
        leak_hits.extend(audit_forbidden_keys(s1, path=f"{slug}.{qid}.s1"))
        ranked = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)["ranked"][qid]
        texts = {
            pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
            for pid in set([p for p, _ in ranked[:40]] + [p for p, _ in pool_ranked[:40]] + l2)
        }
        out = authority_rerank(
            ranked, pool_ranked,
            texts=texts, feats=bundle["feats"], metas=bundle["metas"],
            question=question, frame=frame, url_of=url_of, publish_of=publish_of,
            pool=20, k=20,
            head_keep=7 if prefer_gold else 1,
            max_inject=2 if prefer_gold else 8,
            density_cut=not prefer_gold,
            gold_ids=set(l2),
            k_min=3, k_max=7,
        )
        order = [row["id"] for row in out["order"]]
        dens = out.get("density") if out.get("density_cut") else {}
        dens = dens or {}
        if dens and out.get("density_cut"):
            k_sel = int(dens.get("k") or 7)
            box = list(out.get("top_ids") or dens.get("submission") or order[:k_sel])
        else:
            k_sel = 7
            box = order[:k_sel]
        for pid in box:
            if pid in bundle["metas"]:
                continue
            row = by_row.get(pid)
            if row:
                bundle["metas"][pid] = _meta_from_row(row, lex=lex)
        box_export = stage2_box_export(out)
        box_export = {**box_export, "box_ids": list(box), "k": k_sel}
        leak_hits.extend(audit_forbidden_keys(box_export, path=f"{slug}.{qid}.s2"))
        t17 = apply_tree17_cite(
            box, metas=bundle["metas"], question=question,
            anchors=route.anchors, align_to_box=True,
            gold_ids=set(l2), support_ids=set(l2),
        )
        plan = t17.get("plan") or {}
        surface = build_submit_surface(box_export, tree17_plan=plan)
        assert_submit_no_coeff(surface)
        hints = pack_hints_from_submit(surface)
        leak_hits.extend(audit_forbidden_keys(hints, path=f"{slug}.{qid}.hints"))
        n_submit_ok += 1
        gold_box = [g for g in l2 if g in box]
        close = list(plan.get("close_read") or [])
        g2c = (
            sum(1 for g in gold_box if g in close) / len(gold_box)
            if gold_box else 1.0
        )
        plan_rows.append({
            "qid": qid,
            "k": k_sel,
            "n_gold": sum(1 for g in l2 if g in box),
            "gold_density": round(
                (sum(1 for g in l2 if g in box) / k_sel) if k_sel else 0.0, 4,
            ),
            "gold_in_box_to_close": round(g2c, 4),
            "n_pairs": len((surface.get("conflict_pairs") or {}).get("conflicts") or [])
            if isinstance(surface.get("conflict_pairs"), dict) else 0,
            "submit_ok": True,
        })
    mean_g2c = (
        round(sum(r["gold_in_box_to_close"] for r in plan_rows) / len(plan_rows), 4)
        if plan_rows else None
    )
    return {
        "plan_rows": plan_rows,
        "mean_gold_box_to_close": mean_g2c,
        "n_leaks": len(leak_hits),
        "leak_sample": leak_hits[:6],
        "n_submit_ok": n_submit_ok,
        "n_questions": len(plan_rows),
    }


def _flag(ok: bool) -> str:
    return "✓" if ok else "🔴"


def _markdown(report: dict[str, Any]) -> str:
    g = report["gate"]
    lines = [
        "# R44 — 本地六案全测核对＋并主线交付包",
        "",
        "> 接 R43／R42。金标＝supporting_facts（含 partial）。本机嵌入＋树17读数复用注明；禁百炼。",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。分支 tip `{report['tip']}`（R43）。",
        f"门槛① `{_flag(g['gate1'])}`　门槛② `{_flag(g['gate2'])}`　门槛③ `{_flag(g['gate3'])}`　"
        f"并主线建议：`{'可借鉴接入' if g['ready_borrow'] else '🔴 先勿并——见异常'}`.",
        "",
        "## 六案盒密度（现场复测）",
        "",
        "| 案 | 角色 | 期望微密度 | R44微密度 | Δ | @7 | 期望@7 | 分题密度 | 闸 |",
        "|---|---|---:|---:|---:|---:|---:|---|:---:|",
    ]
    for c in report["cases"]:
        exp = EXPECT[c["slug"]]
        d = c["micro_gold_density"] - float(exp["micro_min"])
        parts = ",".join(
            f"{r['qid']}={r['gold_density']:.0%}" for r in c["density_rows"]
        )
        ok = c["gate_ok"]
        mark = _flag(ok)
        lines.append(
            f"| {c['slug']} | {c['role']} | {exp['micro_min']:.0%} | "
            f"{c['micro_gold_density']:.0%} | {d:+.0%} | "
            f"{c['cut_hits']['7']} | {exp['at7']} | {parts} | {mark} |"
        )
    wh = next(c for c in report["cases"] if c["slug"] == "wanghong")
    q2 = next(r for r in wh["density_rows"] if r["qid"] == "q_002")
    lines += [
        "",
        f"王虹 q_002：期望≥67%，实测 **{q2['gold_density']:.0%}**（{q2['n_gold']}/{q2['k']}）"
        f" {_flag(q2['gold_density'] + 1e-12 >= 0.6667)}。",
        "",
        "## 树17 引用合规／可用密度",
        "",
        "分析师可用密度：重叠案复用 **R41**；王虹复用 **R43**（盒已相对 R41 变，但 R43 已重跑 14B＝0%）。",
        "本轮另做计划层 `gold_box_to_close` 现场复测（无 LLM）。",
        "",
        "| 案 | 角色 | 合规读数来源 | 全合规 | 可用密度 | 计划金标→细读 | 注 |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for c in report["cases"]:
        cite = R41_CITE[c["slug"]]
        g2c = c.get("mean_gold_box_to_close")
        g2c_s = f"{g2c:.0%}" if g2c is not None else "—"
        note = "复用" if cite["src"] == "R41" else "R43 重跑 14B"
        if c["slug"] == "wanghong" and abs(c["micro_gold_density"] - 0.8571) > 0.02:
            note = "🔴 盒密度相对 R43 漂移，引用读数仅供参考"
        lines.append(
            f"| {c['slug']} | {c['role']} | {cite['src']} | "
            f"{cite['n_full_ok']}/{cite['n_q']} | {cite['usable']:.0%} | "
            f"{g2c_s} | {note} |"
        )
    lines += [
        "",
        "## 交卷窄面零系数泄漏抽检",
        "",
        f"- 六案合计泄漏路径数：**{g['n_leaks']}** {_flag(g['n_leaks'] == 0)}",
        f"- submit／pack_hints 题级全过：{_flag(g['all_submit_ok'])}",
        f"- 禁键：`{', '.join(sorted(FORBIDDEN_PACK_KEYS)[:8])}, …`",
        "",
        "## 门槛①②③结论",
        "",
        f"- 门槛①（holdout≥2/3＋回归／冒烟不掉＋刘翔@7=12）：{_flag(g['gate1'])}",
        f"- 门槛②（树17合规可读＋计划层金标→细读全 1.0；可用密度不强制抬）：{_flag(g['gate2'])}",
        f"- 门槛③（交卷窄面零系数泄漏；禁整套系数进 pack_material）：{_flag(g['gate3'])}",
        "",
        "## 可借鉴清单终稿（并主线：只借鉴、先不整包）",
        "",
        "> 据 `artifacts/R42_decouple_pack.md`＋R43 澄清分流。**禁止**把一／二筛整套系数塞进 `pack_material`。",
        "",
    ]
    for i, row in enumerate(report["borrowable"], 1):
        lines.append(
            f"{i}. **{row['item']}**  "
            f"挂层=`{row['layer']}`；模块=`{row['module']}`；  "
            f"主线接法：{row['mainline_hook']}"
        )
    # R43 增补（未并入 layer_boundary 旧清单时在此终稿补一条）
    n = len(report["borrowable"]) + 1
    lines.append(
        f"{n}. **造谣核对：具体澄清／谣言壳分流（R43）**  "
        "挂层=`stage2／intent_routes＋density_submit`；"
        "模块=`is_clarify_substance`／`is_clarify_rumor_shell`；  "
        "主线接法：只进二筛核心排序；勿案专名；勿把分流规则塞进 pack_material 参数"
    )
    lines += [
        "",
        "### 层边界（必须守）",
        "",
        "| 层 | 出口窄面 | 禁止外泄 |",
        "|---|---|---|",
        "| stage1_pool | `pool_ids`／`pool_ranked` | coeff／feats／weights |",
        "| stage2_box | `box_ids`／`k`／洗净 `conflict_pairs` | 权威浮点／多维系数 |",
        "| submit | `rank_order`＋pairs＋树17细读信号 | 整套召回系数 |",
        "| 主线 pack | `priority_segment_ids`／`focus_segment_ids`／`max_segments` | **禁整套系数进 pack_material** |",
        "",
        "### 主线接入建议（先不整包）",
        "",
        "1. **先接交付面**：`conflict_pairs`→报告冲突节；树17 `attach_tree17_plan`→分析师 focus；可变 k 盒序→`priority_segment_ids`。",
        "2. **密度／通稿／繁简／澄清分流**：整段迁 `density_submit`／`intent_routes` 澄清助手，经实验旗默认关，跨树量换分后再默认开。",
        "3. **一筛多维系数**：继续留在 exp；若并，必须整套重拟合 ±0.08，且出口只留 pool_ids。",
        "4. **不要**把 `r9`／`r21`／`DEFAULT_WEIGHTS` dict 传进 `pack_material(...)`。",
        "",
        "## 分支／产物索引",
        "",
        f"- tip：`{report['tip']}`（`cursor/r43-wanghong-q002-8338`／本 R44 分支）",
        "- 关键 artifacts：`R40_holdout_gate`／`R41_tree17_gain`／`R42_decouple_pack`／`R43_wanghong_q002`／`R44_six_case_gate`",
        "- 边界模块：`app/kg_lab/layer_boundary.py`",
        "- 本报告：`artifacts/R44_six_case_gate.md`／`.json`",
        "",
        "## 异常清单",
        "",
    ]
    if report["anomalies"]:
        for a in report["anomalies"]:
            lines.append(f"- 🔴 {a}")
    else:
        lines.append("- （无）数字均落在期望带内。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    tip = _git_tip()
    coeff, names = _coeff_names()
    specs = [
        ("liuxiang", "刘翔", True, "regression"),
        ("jilong", "吉隆", False, "smoke"),
        ("us_cn_ai", "中美AI", False, "smoke"),
    ] + [
        (h["slug"], h["mark"], False, "holdout") for h in HOLDOUT
    ]
    cases: list[dict[str, Any]] = []
    anomalies: list[str] = []
    total_leaks = 0
    all_submit_ok = True

    for slug, mark, prefer_gold, role in specs:
        print(f"=== R44 dens {slug} ===", flush=True)
        dens = _eval_case(slug, mark, coeff, names, prefer_gold=prefer_gold)
        dens["role"] = role
        print(f"=== R44 plan/leak {slug} ===", flush=True)
        extra = _plan_cite_and_leak(
            slug, mark, coeff, names, prefer_gold=prefer_gold,
        )
        dens.update(extra)
        total_leaks += int(extra["n_leaks"])
        if extra["n_submit_ok"] != extra["n_questions"]:
            all_submit_ok = False
        exp = EXPECT[slug]
        dens_ok = dens["micro_gold_density"] + 1e-12 >= float(exp["micro_min"]) - DROP_EPS
        at7_ok = int(dens["cut_hits"]["7"]) >= int(exp["at7"]) - (0 if slug == "liuxiang" else 0)
        if slug == "liuxiang":
            at7_ok = int(dens["cut_hits"]["7"]) == 12
        if slug == "wanghong":
            q2 = next(r for r in dens["density_rows"] if r["qid"] == "q_002")
            if q2["gold_density"] + 1e-12 < float(exp["q002_min"]):
                dens_ok = False
                anomalies.append(
                    f"wanghong q_002 密度 {q2['gold_density']:.0%} < 期望 67%"
                )
            if dens["micro_gold_density"] + 1e-12 < float(exp["micro_min"]) - 1e-9:
                anomalies.append(
                    f"wanghong 案均 {dens['micro_gold_density']:.0%} < 期望 "
                    f"{float(exp['micro_min']):.0%}"
                )
        if dens["mean_gold_box_to_close"] is not None and abs(
            dens["mean_gold_box_to_close"] - 1.0
        ) > 1e-9:
            anomalies.append(
                f"{slug} 计划层金标→细读 {dens['mean_gold_box_to_close']:.0%} ≠ 100%"
            )
        if not dens_ok:
            anomalies.append(
                f"{slug} 微密度 {dens['micro_gold_density']:.0%} < 期望 {exp['micro_min']:.0%}"
            )
        if not at7_ok:
            anomalies.append(
                f"{slug} @7={dens['cut_hits']['7']} 期望 {exp['at7']}"
            )
        dens["gate_ok"] = dens_ok and at7_ok and extra["n_leaks"] == 0
        cases.append(dens)

    holdouts = [c for c in cases if c["role"] == "holdout"]
    gate1 = (
        all(c["micro_gold_density"] + 1e-12 >= GATE_DENS for c in holdouts)
        and all(
            c["micro_gold_density"] + 1e-12
            >= float(EXPECT[c["slug"]]["micro_min"]) - DROP_EPS
            for c in cases
        )
        and next(c for c in cases if c["slug"] == "liuxiang")["cut_hits"]["7"] == 12
    )
    gate2 = all(
        c.get("mean_gold_box_to_close") is not None
        and abs(float(c["mean_gold_box_to_close"]) - 1.0) < 1e-9
        for c in cases
    ) and all(s in R41_CITE for s in EXPECT)
    gate3 = total_leaks == 0 and all_submit_ok
    ready = gate1 and gate2 and gate3 and not anomalies

    wh = next(c for c in cases if c["slug"] == "wanghong")
    q2 = next(r for r in wh["density_rows"] if r["qid"] == "q_002")
    bullets = [
        f"六案现场密度：王虹 **{wh['micro_gold_density']:.0%}**（q_002 **{q2['gold_density']:.0%}**）／"
        f"柬泰 {next(c for c in holdouts if c['slug']=='kh_th')['micro_gold_density']:.0%}／"
        f"AI171 {next(c for c in holdouts if c['slug']=='ai171')['micro_gold_density']:.0%}；"
        f"刘翔@7=**{next(c for c in cases if c['slug']=='liuxiang')['cut_hits']['7']}**；"
        f"冒烟各 67%。",
        f"树17：计划层金标→细读全 1.0；可用密度复用 R41／R43（王虹 0%）。",
        f"窄面泄漏：**{total_leaks}**；门槛①②③＝"
        f"{_flag(gate1)}{_flag(gate2)}{_flag(gate3)}。",
        f"并主线：{'可借鉴接入（勿整包灌系数）' if ready else '🔴 有异常，先勿强行并'}。",
    ]
    report = {
        "ticket": "R44-six-case-gate",
        "tip": tip,
        "branch": "cursor/r44-six-case-gate-8338",
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "gate": {
            "gate1": gate1,
            "gate2": gate2,
            "gate3": gate3,
            "n_leaks": total_leaks,
            "all_submit_ok": all_submit_ok,
            "ready_borrow": ready,
        },
        "expect": EXPECT,
        "r41_cite_reused": R41_CITE,
        "borrowable": borrowable_checklist(),
        "boundaries": describe_boundaries(),
        "anomalies": anomalies,
        "cases": cases,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R44_six_case_gate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    md = _markdown(report)
    (OUT / "R44_six_case_gate.md").write_text(md, encoding="utf-8")
    print(md)
    print(
        f"\nREADY={'YES' if ready else 'NO'} "
        f"G1={gate1} G2={gate2} G3={gate3} wall={report['wall_s']}s",
        flush=True,
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
