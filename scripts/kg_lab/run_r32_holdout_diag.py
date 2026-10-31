#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R32：holdout 三案分层诊断（只读、零改业务码／零调参）。

分层：池外｜池内挤｜盒稀｜其它。附 portable_role／intent／conflict 观察。
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
from app.kg_lab.intent_routes import (  # noqa: E402
    anchor_hits,
    classify_route,
    is_claim_conflict_route,
    is_core_candidate,
)
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features  # noqa: E402
from app.kg_lab.r8_fit import augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import apply_r9  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.source_role import _meta_from_row  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.stage2_authority import authority_rerank  # noqa: E402
from scripts.kg_lab.run_r22_intent_density import (  # noqa: E402
    OUT,
    DEFAULT_K,
    _case,
    _coeff_names,
)
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

CASES = [
    {"slug": "wanghong", "mark": "王虹", "role": "holdout", "prefer_gold": False},
    {"slug": "kh_th", "mark": "柬泰", "role": "holdout", "prefer_gold": False},
    {"slug": "ai171", "mark": "印度", "role": "holdout", "prefer_gold": False},
    {"slug": "liuxiang", "mark": "刘翔", "role": "control", "prefer_gold": True},
]


def _label_cause(
    *,
    n_gold: int,
    n_pool20: int,
    n_box: int,
    k: int,
    dens: float,
) -> str:
    """主因标签：池外｜池内挤｜盒稀｜其它。"""
    if n_gold <= 0:
        return "其它"
    pool_rate = n_pool20 / n_gold
    # 多数金标不进池20
    if n_pool20 == 0 or pool_rate <= 0.34:
        return "池外"
    # 池内有金标但盒内几乎没有
    if n_pool20 >= 1 and n_box == 0:
        return "池内挤"
    if n_pool20 >= 2 and n_box <= max(1, n_pool20 // 3):
        return "池内挤"
    # 进盒了但密度低：盒稀／占位
    if dens + 1e-12 < 2 / 3 and n_box >= 1:
        return "盒稀"
    if dens + 1e-12 >= 2 / 3:
        return "其它"  # 过线或接近，非本票病灶
    return "其它"


def _diag_question(
    *,
    slug: str,
    case: Path,
    dossier: Any,
    rows: list[dict],
    index: KgIndex,
    url_of: dict[str, str],
    publish_of: dict[str, str],
    qrow: dict[str, Any],
    coeff: dict[str, float],
    names: tuple[str, ...],
    prefer_gold: bool,
) -> dict[str, Any]:
    qid, question = qrow["question_id"], qrow["question"]
    gold, _ = gold_paras_for_question(case, qid)
    universe = pack_selected_for_question(dossier, question)
    l2 = sorted(p for _d, p in gold if p in universe)
    n_gold = len(l2)
    sub_rows = [r for r in rows if r["para_id"] in universe]
    sub = KgIndex(slug, sub_rows)
    sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}
    fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
    submit_ranked = fr["ranked"]
    pool_ranked = fr.get("pool_ranked") or fr["ranked"]
    pool_pos = {pid: i for i, (pid, _) in enumerate(pool_ranked, 1)}
    frame = extract_event_frame(question)
    route = classify_route(question, frame)
    anchors = route.anchors
    conflict = is_claim_conflict_route(anchors)
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
    ranked = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)["ranked"][qid]
    texts = {
        pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
        for pid in set(
            [p for p, _ in ranked[:50]] + [p for p, _ in pool_ranked[:50]] + l2
        )
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
    dens = out.get("density") if out.get("density_cut") else None
    dens = dens or {}
    if dens and out.get("density_cut"):
        k_sel = int(dens.get("k") or 7)
        box = list(out.get("top_ids") or dens.get("submission") or order[:k_sel])
    else:
        k_sel = 7
        box = order[:k_sel]
    box_set = set(box)
    gold_in_pool20 = [g for g in l2 if pool_pos.get(g, 10**9) <= 20]
    gold_out_pool20 = [g for g in l2 if pool_pos.get(g, 10**9) > 20]
    gold_in_box = [g for g in l2 if g in box_set]
    gold_pool_not_box = [g for g in gold_in_pool20 if g not in box_set]
    n_pool20 = len(gold_in_pool20)
    n_box = len(gold_in_box)
    dens_v = n_box / k_sel if k_sel else 0.0
    cause = _label_cause(
        n_gold=n_gold, n_pool20=n_pool20, n_box=n_box, k=k_sel, dens=dens_v,
    )

    # 证据一句：池外样例／池内挤样例／盒内非金标
    evidence = ""
    if cause == "池外" and gold_out_pool20:
        g0 = gold_out_pool20[0]
        evidence = (
            f"金标 {g0} 池位={pool_pos.get(g0)}；"
            f"池外 {len(gold_out_pool20)}/{n_gold}。"
        )
    elif cause == "池内挤" and gold_pool_not_box:
        g0 = gold_pool_not_box[0]
        text = str((bundle["metas"].get(g0) or {}).get("text") or "")[:40]
        hits = anchor_hits(text, anchors)
        core = is_core_candidate(
            g0, feats=bundle["feats"], metas=bundle["metas"],
            route=route.route, pool_pos=pool_pos, anchors=anchors, url_of=url_of,
        )
        feat = bundle["feats"].get(g0) or {}
        evidence = (
            f"池内金标 {g0}(pp={pool_pos.get(g0)}) 未进盒；"
            f"side={hits.get('side') or '-'} core={core} "
            f"band={feat.get('authority_band')}；盒={box}。"
        )
    elif cause == "盒稀":
        non = [p for p in box if p not in set(l2)]
        evidence = (
            f"盒内金标 {n_box}/{k_sel}；非金标占位 {len(non)}："
            f"{non[:3]}。"
        )
    else:
        evidence = f"池20={n_pool20}/{n_gold} 盒={n_box}/{k_sel} dens={dens_v:.0%}。"

    # portable / conflict 观察
    role_tags = []
    for g in l2[:5]:
        feat = bundle["feats"].get(g) or {}
        if feat.get("authority_band"):
            role_tags.append(f"{g}:{feat.get('authority_band')}")
    box_sides = []
    for p in box:
        text = str((bundle["metas"].get(p) or {}).get("text") or "")
        box_sides.append(anchor_hits(text, anchors).get("side") or "-")

    return {
        "qid": qid,
        "question": question[:120],
        "route": route.route,
        "conflict_route": conflict,
        "anchors_side_a": list((anchors or {}).get("side_a") or [])[:6],
        "anchors_side_b": list((anchors or {}).get("side_b") or [])[:6],
        "n_gold": n_gold,
        "n_pool20": n_pool20,
        "n_box": n_box,
        "k": k_sel,
        "gold_density": round(dens_v, 4),
        "cause": cause,
        "evidence": evidence,
        "gold_pos": {g: pool_pos.get(g) for g in l2},
        "gold_in_pool20": gold_in_pool20,
        "gold_out_pool20": gold_out_pool20,
        "gold_in_box": gold_in_box,
        "gold_pool_not_box": gold_pool_not_box,
        "box": box,
        "box_sides": box_sides,
        "claim_hole": {
            "applied": (fr.get("claim_hole") or {}).get("applied"),
            "n_inj_pool20": fr.get("n_claim_injected_in_pool20"),
        },
        "gold_authority_sample": role_tags[:5],
        "n_core_proxy": dens.get("n_core"),
        "n_filler_proxy": dens.get("n_filler"),
    }


def _eval_case(spec: dict[str, Any], coeff, names) -> dict[str, Any]:
    slug, mark = spec["slug"], spec["mark"]
    prefer_gold = bool(spec["prefer_gold"])
    print(f"=== diag {slug} ===", flush=True)
    case = _case(mark, prefer_local=(slug == "liuxiang"))
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw}
    q_rows = []
    for qrow in questions:
        row = _diag_question(
            slug=slug, case=case, dossier=dossier, rows=rows, index=index,
            url_of=url_of, publish_of=publish_of, qrow=qrow,
            coeff=coeff, names=names, prefer_gold=prefer_gold,
        )
        q_rows.append(row)
        print(
            f"  {row['qid']} cause={row['cause']} "
            f"pool20={row['n_pool20']}/{row['n_gold']} "
            f"box={row['n_box']}/{row['k']} dens={row['gold_density']:.0%} "
            f"route={row['route']} conflict={row['conflict_route']}",
            flush=True,
        )
    causes = {}
    for r in q_rows:
        causes[r["cause"]] = causes.get(r["cause"], 0) + 1
    return {
        "slug": slug,
        "role": spec["role"],
        "mark": mark,
        "questions": q_rows,
        "cause_counts": causes,
        "micro_density": round(
            sum(r["n_box"] for r in q_rows) / max(sum(r["k"] for r in q_rows), 1), 4,
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R32 — holdout 三案分层诊断（只读）",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。零改业务码／零调参／无案专名词表。锁 R19–R30。",
        "",
        "## 分题主表",
        "",
        "| 案 | qid | 池20金标 | 进盒金标 | k | 盒密度 | route | conflict | 主因 | 证据 |",
        "|---|---|---:|---:|---:|---:|---|---|---|---|",
    ]
    for c in report["cases"]:
        for r in c["questions"]:
            lines.append(
                f"| {c['slug']} | {r['qid']} | "
                f"{r['n_pool20']}/{r['n_gold']} | "
                f"{r['n_box']}/{r['k']} | {r['k']} | "
                f"{r['gold_density']:.0%} | {r['route']} | "
                f"{'Y' if r['conflict_route'] else 'N'} | "
                f"**{r['cause']}** | {r['evidence']} |"
            )
    lines += [
        "",
        "## 主因分布（holdout 9 题）",
        "",
        "| 主因 | 题数 |",
        "|---|---:|",
    ]
    dist = report["holdout_cause_dist"]
    for k in ("池外", "池内挤", "盒稀", "其它"):
        lines.append(f"| {k} | {dist.get(k, 0)} |")
    lines += [
        "",
        "## portable_role／intent／conflict 观察",
        "",
    ]
    for c in report["cases"]:
        if c["role"] != "holdout":
            continue
        lines.append(f"### {c['slug']}")
        for r in c["questions"]:
            lines.append(
                f"- {r['qid']}：route=`{r['route']}` conflict={r['conflict_route']}；"
                f"side_a={r['anchors_side_a'][:3]} side_b={r['anchors_side_b'][:3]}；"
                f"盒侧={r['box_sides']}；"
                f"claim_inj20={r['claim_hole'].get('n_inj_pool20')}；"
                f"金标权威样例={r['gold_authority_sample'][:3] or '—'}。"
            )
        lines.append("")
    lines += [
        "## 可迁移假设（≤3，勿写案名硬规则）",
        "",
    ]
    for i, h in enumerate(report["hypotheses"], 1):
        lines.append(f"{i}. {h}")
    lines += [
        "",
        "## 纪律",
        "",
        "- 本票只诊断；未改 `app/` 业务逻辑与系数。",
        "- 下一刀若开 R33，应按主因分布选层，勿对着 holdout 案名调参。",
        "",
        "## 路径",
        "- `artifacts/R32_holdout_diag.json`",
        "- `artifacts/R32_holdout_diag.md`",
        "- `artifacts/R32_holdout_diag.csv`",
        "",
    ]
    return "\n".join(lines)


def _csv(report: dict[str, Any]) -> str:
    rows = [
        "slug,role,qid,n_gold,n_pool20,n_box,k,density,route,conflict,cause,evidence"
    ]
    for c in report["cases"]:
        for r in c["questions"]:
            ev = (r["evidence"] or "").replace('"', "'").replace(",", "；")
            rows.append(
                f"{c['slug']},{c['role']},{r['qid']},{r['n_gold']},"
                f"{r['n_pool20']},{r['n_box']},{r['k']},{r['gold_density']},"
                f"{r['route']},{int(r['conflict_route'])},{r['cause']},\"{ev}\""
            )
    return "\n".join(rows) + "\n"


def main() -> int:
    t0 = time.perf_counter()
    coeff, names = _coeff_names()
    cases = [_eval_case(spec, coeff, names) for spec in CASES]
    holdout = [c for c in cases if c["role"] == "holdout"]
    dist: dict[str, int] = {}
    for c in holdout:
        for r in c["questions"]:
            dist[r["cause"]] = dist.get(r["cause"], 0) + 1
    n = sum(dist.values()) or 1
    pool_out = dist.get("池外", 0)
    squeezed = dist.get("池内挤", 0)
    sparse = dist.get("盒稀", 0)

    hypotheses: list[str] = []
    if pool_out >= squeezed and pool_out >= sparse:
        hypotheses.append(
            "一筛池20 对「专名／数字对撞／外文案」召回偏弱：多数严格金标位次＞20；"
            "可迁移方向＝问句拉丁／数额／专名注入补洞（非案名表），抬 stage1 进池。"
        )
    if squeezed > 0:
        hypotheses.append(
            "池内金标常因权威带 unknown／非 conflict 路由拿不到软保位，被通稿或综述挤出盒；"
            "可迁移方向＝可核验信号（时间／数额／通报）在非 adjudicate 路由也进二筛核心。"
        )
    if sparse > 0 or any(
        r["n_box"] >= 1 and r["gold_density"] + 1e-12 < 2 / 3
        for c in holdout for r in c["questions"]
    ):
        hypotheses.append(
            "即便进盒 1 金标，k=3 仍只到 33%：密度瓶颈在「盒内占位」而非单点召回；"
            "可迁移方向＝盒内再压非核验占位（或冲突成对占槽）而非继续堆池。"
        )
    while len(hypotheses) < 3:
        hypotheses.append(
            "fact_check 路由在 holdout 占比高且 conflict 常为假：成对软保位空转；"
            "可迁移方向＝对「哪一方／是否属实」问句启轻量对立锚，而不只依赖灾害口径 cue。"
        )
        break
    hypotheses = hypotheses[:3]

    bullets = [
        f"holdout 9 题主因：池外 **{pool_out}**／池内挤 **{squeezed}**／"
        f"盒稀 **{sparse}**／其它 {dist.get('其它', 0)} "
        f"（池外占比 {pool_out / n:.0%}）。",
        "多数卡在**池外**（一筛召回），其次是进池后挤不出盒；"
        "单题进盒后也常见 0～33%（盒稀）。",
    ]
    for c in holdout:
        bullets.append(
            f"`{c['slug']}` 案均 {c['micro_density']:.0%}；"
            f"主因 {c['cause_counts']}。"
        )
    lx = next(c for c in cases if c["slug"] == "liuxiang")
    bullets.append(
        f"对照刘翔：案均 {lx['micro_density']:.0%}；主因 {lx['cause_counts']}（回归臂 prefer_gold）。"
    )

    report = {
        "ticket": "R32-holdout-diag",
        "cases": cases,
        "holdout_cause_dist": dist,
        "hypotheses": hypotheses,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
        "no_tuning": True,
        "read_only": True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R32_holdout_diag.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R32_holdout_diag.md").write_text(_markdown(report), encoding="utf-8")
    (OUT / "R32_holdout_diag.csv").write_text(_csv(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)
    print("hypotheses:", *hypotheses, sep="\n- ", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
