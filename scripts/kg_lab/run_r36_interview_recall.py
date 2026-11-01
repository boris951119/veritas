#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R36：评价题专访短段装箱＋池外可核验召回加力。

对照 R35 盒密度；刘翔 @7≥11；吉隆／中美AI 不显著掉。
禁止 holdout 案专名硬编码。
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

from app.kg_lab.intent_routes import stage2_verifiable_slots  # noqa: E402
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

R35 = {
    "liuxiang": {"pool20": 8, "at7": 12, "micro": 0.5714, "sum_g": 12, "sum_k": 21},
    "wanghong": {"pool20": 9, "at7": 2, "micro": 0.2222, "sum_g": 2, "sum_k": 9},
    "kh_th": {"pool20": 6, "at7": 4, "micro": 0.4444, "sum_g": 4, "sum_k": 9},
    "ai171": {"pool20": 3, "at7": 4, "micro": 0.3333, "sum_g": 3, "sum_k": 9},
    "jilong": {"pool20": 5, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
    "us_cn_ai": {"pool20": 8, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
}
GATE_DENS = 2.0 / 3.0
LIUXIANG_AT7_MIN = 11


def _diag_rows(slug: str, mark: str) -> list[dict[str, Any]]:
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
        s1 = extract_verifiable_slots(question)
        slots = stage2_verifiable_slots(question)
        frame = extract_event_frame(question)
        route_obj = classify_route(question, frame)
        route = getattr(route_obj, "route", None) or str(route_obj)
        bundle = build_bundle(
            sub_rows, fr["ranked"], question, frames=True,
            prefer_ids=None, case_slug=slug,
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
            "n_gold": len(l2),
            "n_pool20": n_pool20,
            "n_box": n_box,
            "k": k_sel,
            "gold_density": round(dens_v, 4),
            "cause": cause,
            "route": route,
            "slots_actionable": slots_actionable(s1, question),
            "claim_alts": list(slots.get("claim_alts") or [])[:6],
            "eval_attitude": bool(slots.get("eval_attitude")),
            "codes": list(slots.get("codes") or [])[:4],
            "claim_inj20": fr.get("n_claim_injected_in_pool20"),
        })
    return out_rows


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R36 — 专访短段装箱＋池外可核验召回加力",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。本机 14B 嵌入缓存；禁百炼；无 holdout 案专名。",
        "",
        "## 改了什么",
        "",
        "1. 二筛：评价题 `eval_attitude`＋`is_interview_voice_segment`"
        "（冒号引语／专访声部）装箱保位，谣言澄清壳降权。",
        "2. 一筛：主张核共现（关闭／切断×燃油×开关）＋调查声部抬分；"
        "短核「燃油开关」不进 `claim_alts`（防评论通稿灌池）。",
        "3. 事实核对装箱：开关调查声部／缺陷侧（加强检测）优先于伤亡通稿。",
        "4. 未整套系数扫参；禁案专名硬编码。",
        "",
        "## vs R35（池20／盒密度）",
        "",
        "| 案 | 角色 | R35池20 | R36池20 | Δ池 | R35微密度 | R36微密度 | Δ密度 | R35@7 | R36@7 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R35.get(c["slug"], {})
        d_micro = c["micro_gold_density"] - float(b.get("micro") or 0)
        lines.append(
            f"| {c['slug']} | {c.get('role')} | {b.get('pool20', '—')} | "
            f"{c['pool_hits']['20']} | "
            f"{c['pool_hits']['20'] - int(b.get('pool20') or 0):+d} | "
            f"{b.get('micro', 0):.0%} | {c['micro_gold_density']:.0%} | "
            f"{d_micro:+.0%} | "
            f"{b.get('at7', '—')} | {c['cut_hits']['7']} |"
        )
    lines += [
        "",
        "### 分题主因",
        "",
        "| 案 | qid | 池20 | 盒 | 密度 | 主因 | route |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for c in report["cases"]:
        if c.get("role") not in {"holdout", "regression"}:
            continue
        for r in c.get("diag_rows") or []:
            lines.append(
                f"| {c['slug']} | {r['qid']} | {r['n_pool20']}/{r['n_gold']} | "
                f"{r['n_box']}/{r['k']} | {r['gold_density']:.0%} | "
                f"**{r['cause']}** | {r.get('route') or '—'} |"
            )
    g = report["gate"]
    lines += [
        "",
        "## 回归／冒烟／门槛",
        "",
        f"- Holdout 案均相对 R35 可见抬升："
        f"{'✓' if g['holdout_dens_up'] else '✗'}"
        f"（均值 {g['holdout_micro_mean_r35']:.0%}→{g['holdout_micro_mean']:.0%}）。",
        f"- 门槛① 另 3 案各自 ≥2/3："
        f"{'✓' if g['holdout_all_ge_23'] else '✗'}"
        f"（通过 {g['n_holdout_pass']}/3；本刀不要求一次过）。",
        f"- 刘翔 @7≥{LIUXIANG_AT7_MIN}："
        f"{'✓' if g['liuxiang_ok'] else '✗'}"
        f"（@7={g['liuxiang_at7']}）。",
        f"- 吉隆微密度不显著掉：{'✓' if g['jilong_ok'] else '✗'}。",
        f"- 中美AI 微密度不显著掉：{'✓' if g['us_ok'] else '✗'}。",
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
        "- 未写 holdout 案专名词表；未为三案扫参过拟合。",
        "- 未整套二筛系数重拟合（规则＋槽维）。",
        "",
        "## 路径",
        "- `artifacts/R36_interview_recall.json`",
        "- `artifacts/R36_interview_recall.md`",
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

    mark_of = {"liuxiang": "刘翔", **{h["slug"]: h["mark"] for h in HOLDOUT}}
    for c in [lx, *holdout_cases]:
        c["diag_rows"] = _diag_rows(c["slug"], mark_of[c["slug"]])

    mean_r35 = sum(R35[h["slug"]]["micro"] for h in HOLDOUT) / 3.0
    mean_now = sum(c["micro_gold_density"] for c in holdout_cases) / 3.0
    n_pass = sum(
        1 for c in holdout_cases
        if c["micro_gold_density"] + 1e-12 >= GATE_DENS
    )
    no_big_drop = all(
        c["micro_gold_density"] + 1e-12 >= R35[c["slug"]]["micro"] - 0.05
        for c in holdout_cases
    )
    holdout_dens_up = mean_now + 1e-12 >= mean_r35 + 0.02 and no_big_drop

    bullets: list[str] = []
    bullets.append(
        f"holdout 三案案均 {mean_r35:.0%}→**{mean_now:.0%}**"
        f"（Σ金标/Σk "
        f"{sum(R35[h['slug']]['sum_g'] for h in HOLDOUT)}/"
        f"{sum(R35[h['slug']]['sum_k'] for h in HOLDOUT)}→"
        f"{sum(c['sum_gold_in_boxes'] for c in holdout_cases)}/"
        f"{sum(c['sum_k'] for c in holdout_cases)}）。"
    )
    for c in holdout_cases:
        b = R35[c["slug"]]
        bullets.append(
            f"`{c['slug']}`：案均 {b['micro']:.0%}→**{c['micro_gold_density']:.0%}**"
            f"（{c['sum_gold_in_boxes']}/{c['sum_k']}）；"
            f"池20 {b['pool20']}→{c['pool_hits']['20']}；"
            f"@7 {b['at7']}→{c['cut_hits']['7']}。"
        )
    bullets.append(
        f"刘翔回归：@7 **{lx['cut_hits']['7']}**／{lx['gold_total']}"
        f"（门槛 ≥{LIUXIANG_AT7_MIN}）；微密度 {lx['micro_gold_density']:.0%}。"
    )
    bullets.append(
        f"冒烟 吉隆 {R35['jilong']['micro']:.0%}→{jl['micro_gold_density']:.0%}；"
        f"中美AI {R35['us_cn_ai']['micro']:.0%}→{us['micro_gold_density']:.0%}。"
    )

    open_holes: list[str] = []
    for c in holdout_cases:
        if c["micro_gold_density"] + 1e-12 < GATE_DENS:
            open_holes.append(
                f"`{c['slug']}` 案均仍 {c['micro_gold_density']:.0%}，"
                f"距 2/3 差 {GATE_DENS - c['micro_gold_density']:.0%}。"
            )
        for r in c.get("diag_rows") or []:
            if r["cause"] in {"池外", "池内挤"} or r["gold_density"] + 1e-12 < GATE_DENS:
                open_holes.append(
                    f"`{c['slug']}` {r['qid']} {r['cause']} "
                    f"（池20={r['n_pool20']}/{r['n_gold']} "
                    f"盒={r['n_box']}/{r['k']}）。"
                )

    jilong_ok = jl["micro_gold_density"] + 1e-12 >= R35["jilong"]["micro"] - 0.05
    us_ok = us["micro_gold_density"] + 1e-12 >= R35["us_cn_ai"]["micro"] - 0.05
    lx_ok = lx["cut_hits"]["7"] >= LIUXIANG_AT7_MIN
    gate = {
        "holdout_dens_up": holdout_dens_up,
        "holdout_micro_mean_r35": round(mean_r35, 4),
        "holdout_micro_mean": round(mean_now, 4),
        "holdout_all_ge_23": n_pass == 3,
        "n_holdout_pass": n_pass,
        "liuxiang_ok": lx_ok,
        "liuxiang_at7": lx["cut_hits"]["7"],
        "jilong_ok": jilong_ok,
        "us_ok": us_ok,
    }

    report = {
        "ticket": "R36-interview-recall",
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "gate": gate,
        "open_holes": open_holes[:16],
        "cases": [lx, *holdout_cases, jl, us],
        "changes": [
            "eval_attitude + interview voice pack",
            "claim_alts long-phrase only; switch co-occurrence + report voice",
            "fact_check switch/defect-side pack vs casualty wire",
            "no case-name lexicon; no full coeff refit",
        ],
    }

    def _jsonable(o: Any) -> Any:
        if isinstance(o, dict):
            return {str(k): _jsonable(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_jsonable(x) for x in o]
        if isinstance(o, (str, int, float, bool)) or o is None:
            return o
        return str(o)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R36_interview_recall.json").write_text(
        json.dumps(_jsonable(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "R36_interview_recall.md").write_text(
        _markdown(report), encoding="utf-8",
    )
    print(
        f"R36 mean {mean_r35:.0%}→{mean_now:.0%} "
        f"lx@7={lx['cut_hits']['7']} "
        f"jl={jl['micro_gold_density']:.0%} us={us['micro_gold_density']:.0%} "
        f"gate1={n_pass}/3 dens_up={holdout_dens_up} "
        f"wall={report['wall_s']}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
