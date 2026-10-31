#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R34：二筛保位——可核验抗通稿占盒。

锁一筛（R33）；禁止 holdout 案专名硬编码；二筛加规则／槽维，非整套系数扫参。
对照 R33 盒密度；刘翔 @7≥11；吉隆／中美AI 冒烟不显著掉。
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

from app.kg_lab.intent_routes import (  # noqa: E402
    slot_align_detail,
    stage2_verifiable_slots,
)
from app.kg_lab.stage1_claim_holes import extract_verifiable_slots  # noqa: E402
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

# R33 基线（本票对照＝一筛收口后的池／盒）
R33 = {
    "liuxiang": {"pool20": 8, "at7": 12, "micro": 0.5714, "sum_g": 12, "sum_k": 21},
    "wanghong": {"pool20": 4, "at7": 1, "micro": 0.1111, "sum_g": 1, "sum_k": 9},
    "kh_th": {"pool20": 6, "at7": 0, "micro": 0.0, "sum_g": 0, "sum_k": 9},
    "ai171": {"pool20": 5, "at7": 3, "micro": 0.2222, "sum_g": 2, "sum_k": 9},
    "jilong": {"pool20": 5, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
    "us_cn_ai": {"pool20": 8, "at7": 6, "micro": 0.6667, "sum_g": 6, "sum_k": 9},
}
GATE_DENS = 2.0 / 3.0
LIUXIANG_AT7_MIN = 11


def _diag_rows(slug: str, mark: str) -> list[dict[str, Any]]:
    """分题：池位／盒密度／主因／槽强对齐披露。"""
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
        slots = stage2_verifiable_slots(question)
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
        box_set = set(box)
        n_box = sum(1 for g in l2 if g in box_set)
        dens_v = (n_box / k_sel) if k_sel else 0.0
        cause = _label_cause(
            n_gold=len(l2), n_pool20=n_pool20, n_box=n_box, k=k_sel, dens=dens_v,
        )
        gold_slot = {}
        for g in l2:
            t = str((bundle["metas"].get(g) or {}).get("text") or "")
            s, w = slot_align_detail(t, slots)
            gold_slot[g] = {
                "strong": s, "weak": w,
                "in_pool20": pool_pos.get(g, 10**9) <= 20,
                "in_box": g in box_set,
                "pos": pool_pos.get(g),
            }
        out_rows.append({
            "qid": qid,
            "question": question,
            "n_gold": len(l2),
            "n_pool20": n_pool20,
            "n_box": n_box,
            "k": k_sel,
            "gold_density": round(dens_v, 4),
            "cause": cause,
            "route": route,
            "slots": {k: v for k, v in slots.items() if v},
            "s1_slots": {
                k: v for k, v in extract_verifiable_slots(question).items() if v
            },
            "gold_slot": gold_slot,
            "box": box,
        })
    return out_rows


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R34 — stage2 可核验抗通稿占盒",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。一筛冻结（R33）；二筛规则／槽维保位；"
        "本机 14B 嵌入既有缓存；禁百炼；无 holdout 案专名词表。",
        "",
        "## 改了什么",
        "",
        "1. `stage2_verifiable_slots`：复用一筛槽＋问句内容名词（无案专名）。",
        "2. `slot_align_detail`／`slot_align_hits`：强槽（拉丁／数额／引号／年月冲突）与弱名词分计。",
        "3. `looks_like_wire_shell`：无强槽的时间线／综合报道壳（事实核对题不进补位＋排序降权）。",
        "4. `is_core_candidate`：事实核对题池内强槽→核心；裁决题强槽须侧锚；短独占主张段进核心。",
        "5. `core_rank_score`：事实核对题强槽抬分；通稿壳罚分。",
        "6. `pack_core_first`：强槽核心优先装箱；簇代表质量含槽对齐。",
        "7. `authority_rerank` 密度路径透传 `slots`。一筛系数／池注入不动。",
        "",
        "## vs R33（池20／盒密度）",
        "",
        "| 案 | 角色 | R33池20 | R34池20 | Δ池 | R33微密度 | R34微密度 | Δ密度 | R33@7 | R34@7 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b = R33.get(c["slug"], {})
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
        f"- Holdout 案均相对 R33 可见抬升："
        f"{'✓' if g['holdout_dens_up'] else '✗'}"
        f"（均值 {g['holdout_micro_mean_r33']:.0%}→{g['holdout_micro_mean']:.0%}）。",
        f"- 门槛① 另 3 案各自 ≥2/3："
        f"{'✓' if g['holdout_all_ge_23'] else '✗'}"
        f"（通过 {g['n_holdout_pass']}/3）。",
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
        "- 一筛冻结；二筛未整套系数重拟合（规则＋槽维，单维未超 ±0.08 扫参）。",
        "",
        "## 路径",
        "- `artifacts/R34_stage2_protect.json`",
        "- `artifacts/R34_stage2_protect.md`",
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

    mean_r33 = sum(R33[h["slug"]]["micro"] for h in HOLDOUT) / 3.0
    mean_now = sum(c["micro_gold_density"] for c in holdout_cases) / 3.0
    n_pass = sum(
        1 for c in holdout_cases
        if c["micro_gold_density"] + 1e-12 >= GATE_DENS
    )
    holdout_up = mean_now + 1e-12 >= mean_r33 + 0.02  # 可见抬升 ≈ ≥+2pp 均值
    # 亦认单案有显著抬且无案相对 R33 掉超 5pp
    no_big_drop = all(
        c["micro_gold_density"] + 1e-12 >= R33[c["slug"]]["micro"] - 0.05
        for c in holdout_cases
    )
    any_lift = any(
        c["micro_gold_density"] + 1e-12 >= R33[c["slug"]]["micro"] + 0.05
        for c in holdout_cases
    )
    holdout_dens_up = (holdout_up or (any_lift and no_big_drop)) and no_big_drop

    bullets: list[str] = []
    bullets.append(
        f"holdout 三案案均 {mean_r33:.0%}→**{mean_now:.0%}**"
        f"（Σ金标/Σk "
        f"{sum(R33[h['slug']]['sum_g'] for h in HOLDOUT)}/"
        f"{sum(R33[h['slug']]['sum_k'] for h in HOLDOUT)}→"
        f"{sum(c['sum_gold_in_boxes'] for c in holdout_cases)}/"
        f"{sum(c['sum_k'] for c in holdout_cases)}）。"
    )
    for c in holdout_cases:
        b = R33[c["slug"]]
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
        f"冒烟 吉隆 {R33['jilong']['micro']:.0%}→{jl['micro_gold_density']:.0%}；"
        f"中美AI {R33['us_cn_ai']['micro']:.0%}→{us['micro_gold_density']:.0%}。"
    )

    open_holes: list[str] = []
    for c in holdout_cases:
        if c["micro_gold_density"] + 1e-12 < GATE_DENS:
            open_holes.append(
                f"`{c['slug']}` 案均仍 {c['micro_gold_density']:.0%}，"
                f"距 2/3 差 {GATE_DENS - c['micro_gold_density']:.0%}。"
            )
        for r in c.get("diag_rows") or []:
            if r["cause"] == "池外":
                open_holes.append(
                    f"`{c['slug']}` {r['qid']} 仍池外"
                    f"（池20={r['n_pool20']}/{r['n_gold']}）。"
                )
            elif r["cause"] == "池内挤":
                open_holes.append(
                    f"`{c['slug']}` {r['qid']} 仍池内挤"
                    f"（池20={r['n_pool20']} 盒={r['n_box']}/{r['k']}）。"
                )
            elif r["gold_density"] + 1e-12 < GATE_DENS:
                open_holes.append(
                    f"`{c['slug']}` {r['qid']} 密度 {r['gold_density']:.0%}"
                    f"（{r['n_box']}/{r['k']}，{r['cause']}）。"
                )

    jilong_ok = jl["micro_gold_density"] + 1e-12 >= R33["jilong"]["micro"] - 0.05
    us_ok = us["micro_gold_density"] + 1e-12 >= R33["us_cn_ai"]["micro"] - 0.05
    lx_ok = lx["cut_hits"]["7"] >= LIUXIANG_AT7_MIN
    gate = {
        "holdout_dens_up": holdout_dens_up,
        "holdout_micro_mean_r33": round(mean_r33, 4),
        "holdout_micro_mean": round(mean_now, 4),
        "holdout_all_ge_23": n_pass == 3,
        "n_holdout_pass": n_pass,
        "liuxiang_ok": lx_ok,
        "liuxiang_at7": lx["cut_hits"]["7"],
        "jilong_ok": jilong_ok,
        "us_ok": us_ok,
    }

    report = {
        "ticket": "R34-stage2-protect",
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "gate": gate,
        "open_holes": open_holes[:16],
        "cases": [lx, *holdout_cases, jl, us],
        "changes": [
            "stage2_verifiable_slots + slot_align_detail/hits",
            "wire_shell filter on fact_check filler",
            "strong-slot core prefer + pack sort",
            "fact_check slot_b / shell_pen",
            "no stage1 coeff / pool inject change",
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
    (OUT / "R34_stage2_protect.json").write_text(
        json.dumps(_jsonable(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "R34_stage2_protect.md").write_text(
        _markdown(report), encoding="utf-8",
    )
    print(
        f"R34 mean {mean_r33:.0%}→{mean_now:.0%} "
        f"lx@7={lx['cut_hits']['7']} "
        f"jl={jl['micro_gold_density']:.0%} us={us['micro_gold_density']:.0%} "
        f"gate1={n_pass}/3 dens_up={holdout_dens_up} "
        f"wall={report['wall_s']}s"
    )
    for c in holdout_cases:
        print(
            f"  {c['slug']}: {R33[c['slug']]['micro']:.0%}→"
            f"{c['micro_gold_density']:.0%} "
            f"({c['sum_gold_in_boxes']}/{c['sum_k']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
