#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R33：一筛可核验槽进池（拉丁／数额／引号／CJK↔拉丁桥）。

锁 R19–R30；禁止 holdout 案专名硬编码；二筛系数不动。
对照 R31 池20／盒密度；刘翔 @7≥11；吉隆／中美AI 冒烟。
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

from app.kg_lab.stage1_claim_holes import (  # noqa: E402
    extract_verifiable_slots,
    slots_actionable,
)
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question  # noqa: E402
from scripts.kg_lab.run_r22_intent_density import (  # noqa: E402
    OUT,
    _case,
    _coeff_names,
    _eval_case,
)
from scripts.kg_lab.run_r31_holdout3 import HOLDOUT  # noqa: E402
from scripts.kg_lab.run_r32_holdout_diag import _label_cause  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

# R31 基线（池20 累计／案均盒密度／@7）
R31 = {
    "liuxiang": {"pool20": 8, "at7": 12, "micro": 0.5714, "sum_g": 12, "sum_k": 21},
    "wanghong": {"pool20": 3, "at7": 1, "micro": 0.1111, "sum_g": 1, "sum_k": 9},
    "kh_th": {"pool20": 3, "at7": 0, "micro": 0.0, "sum_g": 0, "sum_k": 9},
    "ai171": {"pool20": 5, "at7": 3, "micro": 0.2222, "sum_g": 2, "sum_k": 9},
    # 冒烟对照取 R27（末次含池20 的密度票）；R30/R31 微密度同为 67%
    "jilong": {"pool20": 5, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
    "us_cn_ai": {"pool20": 8, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
}
# R32 池外题数（holdout 9 题）
R32_POOL_OUT = 6
GATE_DENS = 2.0 / 3.0
LIUXIANG_AT7_MIN = 11


def _pool_positions(slug: str, mark: str) -> list[dict[str, Any]]:
    """每题池位＋主因（与 R32 同口径）。"""
    from app.kg_lab.index_build import KgIndex, build_corpus_rows
    from app.kg_lab.slices import union_pack_ids
    from app.kg_lab.stage2_authority import authority_rerank
    from app.kg_lab.event_frame import extract_event_frame
    from app.kg_lab.intent_routes import classify_route
    from app.kg_lab.multidim_weight import build_bundle
    from app.kg_lab.portable_tags import apply_portable_features
    from app.kg_lab.r8_fit import augment_features, evaluate
    from app.kg_lab.r9_buckets import apply_r9
    from app.kg_lab.source_role import _meta_from_row
    from app.kg_lab.case_lexicon import lexicon_for_question
    from app.kg_lab.config import DEFAULT_K

    case = _case(mark, prefer_local=(slug == "liuxiang"))
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw}
    coeff, names = _coeff_names()
    out_rows: list[dict[str, Any]] = []
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, _ = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {
            pid: v for pid, v in index.embeddings.items() if pid in universe
        }
        fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
        pool_ranked = fr.get("pool_ranked") or fr["ranked"]
        pool_pos = {pid: i for i, (pid, _) in enumerate(pool_ranked, 1)}
        n_pool20 = sum(1 for g in l2 if pool_pos.get(g, 10**9) <= 20)
        slots = extract_verifiable_slots(question)
        frame = extract_event_frame(question)
        route_obj = classify_route(question, frame)
        route = getattr(route_obj, "route", None) or str(route_obj)
        prefer = None
        bundle = build_bundle(
            sub_rows, fr["ranked"], question, frames=True,
            prefer_ids=prefer, case_slug=slug,
        )
        by_row = {r["para_id"]: r for r in sub_rows}
        lex = lexicon_for_question(question, case_slug=slug)
        for pid, _sc in pool_ranked[:50]:
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
        stage1 = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)
        ranked = stage1["ranked"][qid]
        texts = {
            pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
            for pid in set([p for p, _ in ranked[:30]] + [p for p, _ in pool_ranked[:30]])
        }
        out = authority_rerank(
            ranked, pool_ranked,
            texts=texts, feats=bundle["feats"], metas=bundle["metas"],
            question=question, frame=frame, url_of=url_of, publish_of=publish_of,
            pool=20, k=20, head_keep=1, max_inject=8, density_cut=True,
            gold_ids=set(l2), k_min=3, k_max=7,
        )
        dens = out.get("density") or {}
        k_sel = int(dens.get("k") or 3)
        box = list(out.get("top_ids") or dens.get("submission") or [])[:k_sel]
        n_box = sum(1 for g in l2 if g in set(box))
        dens_v = (n_box / k_sel) if k_sel else 0.0
        cause = _label_cause(
            n_gold=len(l2), n_pool20=n_pool20, n_box=n_box, k=k_sel, dens=dens_v,
        )
        out_rows.append({
            "qid": qid,
            "question": question,
            "n_gold": len(l2),
            "n_pool20": n_pool20,
            "n_box": n_box,
            "k": k_sel,
            "gold_density": round(dens_v, 4),
            "cause": cause,
            "gold_pos": {g: pool_pos.get(g) for g in l2},
            "slots": {k: v for k, v in slots.items() if v},
            "slots_actionable": slots_actionable(slots),
            "route": route,
            "claim_inj20": fr.get("n_claim_injected_in_pool20"),
        })
    return out_rows


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R33 — stage1 可核验槽进池（拉丁／数额／引号）",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。规则优先；本机 14B 嵌入既有缓存；"
        "禁百炼；无 holdout 案专名词表；二筛系数未动。",
        "",
        "## 改了什么",
        "",
        "1. `extract_verifiable_slots`：从问句表面抽拉丁词／代码／数额／引号尾核／发言人／方军标／年月。",
        "2. `slots_actionable`：裸数额不触发注入（保刘翔）；词拉丁／引号／冲突桥／数额×代码才 actionable。",
        "3. 补洞臂：可核验强对齐＋CJK↔拉丁年月桥＋注入按槽优先级＋同 doc 限注＋经典强槽钉住。",
        "4. 航班号类含数字拉丁单独弱抬，防灌池。",
        "",
        "## vs R31（池20／盒密度）",
        "",
        "| 案 | 角色 | R31池20 | R33池20 | Δ池 | R31微密度 | R33微密度 | R31@7 | R33@7 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R31.get(c["slug"], {})
        lines.append(
            f"| {c['slug']} | {c.get('role')} | {b.get('pool20', '—')} | "
            f"{c['pool_hits']['20']} | "
            f"{c['pool_hits']['20'] - int(b.get('pool20') or 0):+d} | "
            f"{b.get('micro', 0):.0%} | {c['micro_gold_density']:.0%} | "
            f"{b.get('at7', '—')} | {c['cut_hits']['7']} |"
        )
    lines += [
        "",
        "## 池外题数（holdout）",
        "",
        f"- R32 池外 **{R32_POOL_OUT}**／9 → R33 池外 **{report['holdout_pool_out']}**／9"
        f"（Δ {report['holdout_pool_out'] - R32_POOL_OUT:+d}）。",
        "",
        "### 分题池位／主因",
        "",
        "| 案 | qid | 池20 | 盒 | 密度 | 主因 | actionable 槽 |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for c in report["cases"]:
        if c.get("role") not in {"holdout", "regression"}:
            continue
        for r in c.get("diag_rows") or []:
            slot_keys = ",".join((r.get("slots") or {}).keys()) or "—"
            lines.append(
                f"| {c['slug']} | {r['qid']} | {r['n_pool20']}/{r['n_gold']} | "
                f"{r['n_box']}/{r['k']} | {r['gold_density']:.0%} | "
                f"**{r['cause']}** | {slot_keys} |"
            )
    lines += [
        "",
        "## 回归／冒烟",
        "",
        f"- 刘翔 @7≥{LIUXIANG_AT7_MIN}："
        f"{'✓' if report['gate']['liuxiang_ok'] else '✗'}"
        f"（@7={report['gate']['liuxiang_at7']}）。",
        f"- 吉隆微密度相对 R31 不显著掉："
        f"{'✓' if report['gate']['jilong_ok'] else '✗'}。",
        f"- 中美AI 微密度相对 R31 不显著掉："
        f"{'✓' if report['gate']['us_ok'] else '✗'}。",
        "",
        "## 未解洞",
        "",
    ]
    for hole in report.get("open_holes") or []:
        lines.append(f"- {hole}")
    lines += [
        "",
        "## 纪律",
        "",
        "- 未写 holdout 案专名词表；未扫参过拟合。",
        "- 二筛／authority 系数未改；更高盒密度冲刺仍冻结到下一刀。",
        "",
        "## 路径",
        "- `artifacts/R33_stage1_pool.json`",
        "- `artifacts/R33_stage1_pool.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    coeff, names = _coeff_names()
    lx = _eval_case("liuxiang", "刘翔", coeff, names, prefer_gold=True)
    lx["role"] = "regression"
    jl = _eval_case("jilong", "吉隆", coeff, names, prefer_gold=False)
    jl["role"] = "smoke"
    us = _eval_case("us_cn_ai", "中美AI", coeff, names, prefer_gold=False)
    us["role"] = "smoke"

    holdout_cases: list[dict[str, Any]] = []
    for h in HOLDOUT:
        c = _eval_case(h["slug"], h["mark"], coeff, names, prefer_gold=False)
        c["role"] = "holdout"
        c["title"] = h["title"]
        holdout_cases.append(c)

    # 分题池位诊断（holdout + 刘翔）
    mark_of = {"liuxiang": "刘翔", **{h["slug"]: h["mark"] for h in HOLDOUT}}
    for c in [lx, *holdout_cases]:
        c["diag_rows"] = _pool_positions(c["slug"], mark_of[c["slug"]])

    pool_out = 0
    for c in holdout_cases:
        for r in c.get("diag_rows") or []:
            if r.get("cause") == "池外":
                pool_out += 1

    bullets: list[str] = []
    bullets.append(
        f"holdout 池外题 {R32_POOL_OUT}→**{pool_out}**／9；"
        f"三案池20 合计 "
        f"{sum(R31[h['slug']]['pool20'] for h in HOLDOUT)}→"
        f"**{sum(c['pool_hits']['20'] for c in holdout_cases)}**。"
    )
    for c in holdout_cases:
        b = R31[c["slug"]]
        bullets.append(
            f"`{c['slug']}`：池20 {b['pool20']}→**{c['pool_hits']['20']}**；"
            f"案均 {b['micro']:.0%}→**{c['micro_gold_density']:.0%}**"
            f"（{c['sum_gold_in_boxes']}/{c['sum_k']}）。"
        )
    bullets.append(
        f"刘翔回归：@7 **{lx['cut_hits']['7']}**／{lx['gold_total']}"
        f"（门槛 ≥{LIUXIANG_AT7_MIN}）；池20 {R31['liuxiang']['pool20']}→"
        f"{lx['pool_hits']['20']}；微密度 {lx['micro_gold_density']:.0%}。"
    )
    bullets.append(
        f"冒烟 吉隆微密度 {R31['jilong']['micro']:.0%}→{jl['micro_gold_density']:.0%}；"
        f"中美AI {R31['us_cn_ai']['micro']:.0%}→{us['micro_gold_density']:.0%}。"
    )

    open_holes: list[str] = []
    for c in holdout_cases:
        if c["micro_gold_density"] + 1e-12 < GATE_DENS:
            open_holes.append(
                f"`{c['slug']}` 案均仍 {c['micro_gold_density']:.0%}，"
                f"距 2/3 差 {GATE_DENS - c['micro_gold_density']:.0%}；"
                f"池内挤题仍需二筛保位。"
            )
        for r in c.get("diag_rows") or []:
            if r["cause"] == "池外":
                open_holes.append(
                    f"`{c['slug']}` {r['qid']} 仍池外"
                    f"（池20={r['n_pool20']}/{r['n_gold']}）。"
                )
            elif r["cause"] == "池内挤":
                open_holes.append(
                    f"`{c['slug']}` {r['qid']} 池内挤"
                    f"（池20={r['n_pool20']} 盒={r['n_box']}/{r['k']}）。"
                )

    jilong_ok = jl["micro_gold_density"] + 1e-12 >= R31["jilong"]["micro"] - 0.05
    us_ok = us["micro_gold_density"] + 1e-12 >= R31["us_cn_ai"]["micro"] - 0.05
    lx_ok = lx["cut_hits"]["7"] >= LIUXIANG_AT7_MIN
    gate = {
        "liuxiang_ok": lx_ok,
        "liuxiang_at7": lx["cut_hits"]["7"],
        "jilong_ok": jilong_ok,
        "us_ok": us_ok,
        "holdout_pool_out_down": pool_out < R32_POOL_OUT,
        "holdout_dens_up": all(
            c["micro_gold_density"] + 1e-12 >= R31[c["slug"]]["micro"]
            for c in holdout_cases
        ),
    }

    report = {
        "ticket": "R33-stage1-pool",
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "holdout_pool_out": pool_out,
        "gate": gate,
        "open_holes": open_holes[:12],
        "cases": [lx, *holdout_cases, jl, us],
        "changes": [
            "extract_verifiable_slots + slots_actionable",
            "claim hole R33 scoring / pin / tiered inject",
            "no stage2 coeff change",
        ],
    }
    def _jsonable(o: Any) -> Any:
        if isinstance(o, dict):
            return {str(k): _jsonable(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_jsonable(x) for x in o]
        if isinstance(o, (str, int, float, bool)) or o is None:
            return o
        if hasattr(o, "route") and not isinstance(o, type):
            try:
                return getattr(o, "route")
            except Exception:
                pass
        return str(o)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R33_stage1_pool.json").write_text(
        json.dumps(_jsonable(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md = _markdown(report)
    (OUT / "R33_stage1_pool.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
