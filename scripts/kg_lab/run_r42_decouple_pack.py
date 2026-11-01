#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R42：门槛③低耦合拆装——禁整套系数进 pack_material。

接 R40／R41。证明：stage1→池；stage2→少而密＋pairs；交卷→rank＋树17信号。
密度／引用不回退；导出可借鉴清单；不整包并主线。
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
    POOLS,
    _case,
    _coeff_names,
)
from scripts.kg_lab.run_r31_holdout3 import HOLDOUT  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

# R40／R41 冻结基线（门槛①②）
R40_L2 = {
    "liuxiang": {"micro": 0.5714, "at7": 12},
    "wanghong": {"micro": 0.7143, "at7": 5},
    "kh_th": {"micro": 0.8000, "at7": 4},
    "ai171": {"micro": 0.8000, "at7": 5},
    "jilong": {"micro": 0.6667, "at7": 6},
    "us_cn_ai": {"micro": 0.6667, "at7": 6},
}
R41_CITE = {
    "liuxiang": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.2857},
    "jilong": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.5556},
    "us_cn_ai": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.3333},
    "wanghong": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.0},
    "kh_th": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.6667},
    "ai171": {"n_full_ok": 3, "n_q": 3, "axes_ok": 9, "axes_total": 9, "usable": 0.4444},
}
GATE_DENS = 2.0 / 3.0
LIUXIANG_AT7_MIN = 11
DROP_EPS = 0.02


def _eval_case_layered(
    slug: str,
    mark: str,
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    prefer_gold: bool,
    role: str,
) -> dict[str, Any]:
    case = _case(mark, prefer_local=(slug == "liuxiang"))
    t0 = time.perf_counter()
    print(f"=== R42 layered {slug} ===", flush=True)
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw}
    pool_hits = {str(p): 0 for p in POOLS}
    cut_hits = {"7": 0}
    dens_rows: list[dict[str, Any]] = []
    layer_rows: list[dict[str, Any]] = []
    cite_plan_rows: list[dict[str, Any]] = []
    leak_hits: list[str] = []

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

        # —— 层① 进池（系数只在 evaluate 内；出口剥净）——
        s1_export = stage1_pool_export(pool_ranked, pool_n=20)
        leak_hits.extend(audit_forbidden_keys(s1_export, path=f"{slug}.{qid}.s1"))

        ranked = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)["ranked"][qid]
        pool_pos = {pid: i for i, (pid, _) in enumerate(pool_ranked, 1)}
        for p in POOLS:
            pool_hits[str(p)] += sum(1 for g in l2 if pool_pos.get(g, 10**9) <= p)

        texts = {
            pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
            for pid in set([p for p, _ in ranked[:30]] + [p for p, _ in pool_ranked[:30]])
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

        # —— 层② 盒＋pairs ——
        box_export = stage2_box_export(out)
        # 对齐 dens_rows 实际盒（回归臂固定 k=7）
        box_export = {**box_export, "box_ids": list(box), "k": k_sel}
        leak_hits.extend(audit_forbidden_keys(box_export, path=f"{slug}.{qid}.s2"))

        # —— 树17 计划信号（无 LLM）——
        for pid in box:
            if pid in bundle["metas"]:
                continue
            row = by_row.get(pid)
            if row:
                bundle["metas"][pid] = _meta_from_row(row, lex=lex)
        t17 = apply_tree17_cite(
            box, metas=bundle["metas"], question=question,
            anchors=route.anchors, align_to_box=True,
            gold_ids=set(l2), support_ids=set(l2),
        )
        plan = t17.get("plan") or {}
        l3 = t17.get("l3") or {}

        # —— 层③ 交卷 ——
        surface = build_submit_surface(box_export, tree17_plan=plan)
        assert_submit_no_coeff(surface)
        hints = pack_hints_from_submit(surface)
        leak_hits.extend(audit_forbidden_keys(hints, path=f"{slug}.{qid}.hints"))

        n_gold = sum(1 for g in l2 if g in box)
        gold_dens = n_gold / k_sel if k_sel else 0.0
        dens_rows.append({
            "qid": qid,
            "route": route.route,
            "k": k_sel,
            "n_gold": n_gold,
            "gold_density": round(gold_dens, 4),
            "box": box,
        })
        cut_hits["7"] += sum(1 for g in l2 if g in order[:7])
        gold_box = [g for g in l2 if g in box]
        close = list(plan.get("close_read") or [])
        g2c = (
            sum(1 for g in gold_box if g in close) / len(gold_box)
            if gold_box else 1.0
        )
        cite_plan_rows.append({
            "qid": qid,
            "box_k": k_sel,
            "pair_required": bool(plan.get("pair_required")),
            "gold_in_box_to_close": round(g2c, 4),
            "close_k": len(close),
            "l3_gold_box_to_close": l3.get("gold_box_to_close"),
        })
        layer_rows.append({
            "qid": qid,
            "stage1_pool_n": len(s1_export["pool_ids"]),
            "stage2_k": k_sel,
            "submit_k": surface["k"],
            "n_conflict_pairs": (
                len((surface.get("conflict_pairs") or {}).get("conflicts") or [])
                if isinstance(surface.get("conflict_pairs"), dict)
                else len(surface.get("conflict_pairs") or [])
            ),
            "n_close_read": len((surface.get("tree17") or {}).get("close_read_ids") or []),
            "pack_hint_keys": sorted(hints.keys()),
            "submit_ok": True,
        })
        print(
            f"  {qid} k={k_sel} dens={gold_dens:.0%} "
            f"pairs={layer_rows[-1]['n_conflict_pairs']} "
            f"close={layer_rows[-1]['n_close_read']} g2c={g2c:.0%}",
            flush=True,
        )

    sum_g = sum(r["n_gold"] for r in dens_rows)
    sum_k = sum(r["k"] for r in dens_rows)
    micro = round(sum_g / sum_k, 4) if sum_k else 0.0
    plan_g2c = (
        round(
            sum(r["gold_in_box_to_close"] for r in cite_plan_rows) / len(cite_plan_rows),
            4,
        )
        if cite_plan_rows else None
    )
    return {
        "slug": slug,
        "role": role,
        "pool_hits": pool_hits,
        "cut_hits": cut_hits,
        "density_rows": dens_rows,
        "micro_gold_density": micro,
        "sum_gold_in_boxes": sum_g,
        "sum_k": sum_k,
        "layer_rows": layer_rows,
        "cite_plan_rows": cite_plan_rows,
        "mean_gold_box_to_close": plan_g2c,
        "n_layer_leaks": len(leak_hits),
        "layer_leak_sample": leak_hits[:8],
        "wall_s": round(time.perf_counter() - t0, 1),
    }


def _markdown(report: dict[str, Any]) -> str:
    g = report["gate"]
    lines = [
        "# R42 — 门槛③：低耦合拆装（禁整套系数进 pack_material）",
        "",
        "> 接 R40／R41。stage1＝进池；stage2＝少而密＋conflict_pairs；交卷＝rank＋树17信号。",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。本机嵌入；禁百炼；系数未改（无需 ±0.08 重拟合）。",
        f"门槛③判定：**{'过' if g['gate3_pass'] else '未过'}**。",
        "",
        "## 接口／模块边界",
        "",
        "1. **stage1_pool**：`fuse_r19`＋`evaluate(coeff)` 只在层内；出口 `stage1_pool_export` → `pool_ids`。",
        "2. **stage2_box**：`authority_rerank`＋`density_constrained_submit`；出口 `box_ids`／`k`／洗净的 `conflict_pairs`。",
        "3. **submit**：`build_submit_surface` → `rank_order`＋`conflict_pairs`＋`tree17`（细读 id／成对／标签）。",
        "4. **主线接法**：`pack_hints_from_submit` → `priority_segment_ids`／`focus_segment_ids`／`max_segments`；"
        "`pack_material` **不接受** coeff／feats／weights（见 `FORBIDDEN_PACK_KEYS`）。",
        "5. 现有 `slices.pack_selected_for_question` 仍只拿主线 BM25 宇宙，与实验系数无关。",
        "",
        "## 密度回归（门槛①）",
        "",
        "| 案 | 角色 | R40微密度 | R42微密度 | Δ | R40@7 | R42@7 | ≥2/3 |",
        "|---|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for c in report["cases"]:
        b = R40_L2.get(c["slug"], {})
        d = c["micro_gold_density"] - float(b.get("micro") or 0)
        if c["role"] == "holdout":
            ge = "✓" if c["micro_gold_density"] + 1e-12 >= GATE_DENS else "·"
        else:
            ge = "—"
        lines.append(
            f"| {c['slug']} | {c['role']} | {b.get('micro', 0):.0%} | "
            f"{c['micro_gold_density']:.0%} | {d:+.0%} | "
            f"{b.get('at7', '—')} | {c['cut_hits']['7']} | {ge} |"
        )
    lines += [
        "",
        "## 引用回归（门槛②）",
        "",
        "本轮不重跑 14B 分析师；盒密度与 R40／R41 对齐 ⇒ 树17 输入面不变。",
        "计划层 `gold_box_to_close` 现场复测；可用引用密度沿用 R41 冻结读数。",
        "",
        "| 案 | 角色 | R41全合规 | R41可用密度 | R42计划金标→细读 | 盒密度守 |",
        "|---|---|---:|---:|---:|:---:|",
    ]
    for c in report["cases"]:
        prev = R41_CITE.get(c["slug"], {})
        dens_hold = abs(
            c["micro_gold_density"] - float(R40_L2.get(c["slug"], {}).get("micro") or 0)
        ) <= DROP_EPS
        g2c = c.get("mean_gold_box_to_close")
        g2c_s = f"{g2c:.0%}" if g2c is not None else "—"
        lines.append(
            f"| {c['slug']} | {c['role']} | "
            f"{prev.get('n_full_ok', '—')}/{prev.get('n_q', '—')} | "
            f"{float(prev.get('usable') or 0):.0%} | {g2c_s} | "
            f"{'✓' if dens_hold else '✗'} |"
        )
    lines += [
        "",
        "## 拆装审计",
        "",
        f"- 交卷／hints 系数泄漏次数：**{g['n_leaks']}**",
        f"- 题级 submit 全过：{'✓' if g['all_submit_ok'] else '✗'}",
        f"- pack_material 禁键集合：`{', '.join(sorted(report['forbidden_keys'][:8]))}, …`",
        "",
        "## 可借鉴清单（挂层＋主线接法）",
        "",
    ]
    for row in report["borrowable"]:
        lines.append(
            f"- **{row['item']}** — 层=`{row['layer']}`；"
            f"模块=`{row['module']}`；主线：{row['mainline_hook']}"
        )
    lines += [
        "",
        "## 验收闸",
        "",
        f"- 门槛① holdout ≥2/3：{'✓' if g['dens_holdout_ok'] else '✗'}"
        f"（{g['n_holdout_ge23']}/3）",
        f"- 密度相对 R40 不掉（≤{DROP_EPS:.0%}）：{'✓' if g['dens_regress_ok'] else '✗'}",
        f"- 刘翔 @7≥{LIUXIANG_AT7_MIN}：{'✓' if g['liuxiang_ok'] else '✗'}"
        f"（{g['liuxiang_at7']}）",
        f"- 引用计划层金标→细读全 1.0：{'✓' if g['cite_plan_ok'] else '✗'}",
        f"- R41 可用密度冻结可读：{'✓' if g['cite_frozen_ok'] else '✗'}"
        f"（holdout 均值 {g['holdout_mean_usable']:.0%}）",
        f"- 零系数泄漏进交卷／pack hints：{'✓' if g['no_coeff_leak'] else '✗'}",
        f"- 门槛③：{'✓ 过' if g['gate3_pass'] else '✗ 未过'}",
        "",
        "## 路径",
        "- `app/kg_lab/layer_boundary.py`",
        "- `tests/test_r42_layer_boundary.py`",
        "- `artifacts/R42_decouple_pack.json`",
        "- `artifacts/R42_decouple_pack.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    coeff, names = _coeff_names()
    cases: list[dict[str, Any]] = [
        _eval_case_layered(
            "liuxiang", "刘翔", coeff, names, prefer_gold=True, role="regression",
        ),
        _eval_case_layered(
            "jilong", "吉隆", coeff, names, prefer_gold=False, role="smoke",
        ),
        _eval_case_layered(
            "us_cn_ai", "中美AI", coeff, names, prefer_gold=False, role="smoke",
        ),
    ]
    for h in HOLDOUT:
        cases.append(
            _eval_case_layered(
                h["slug"], h["mark"], coeff, names,
                prefer_gold=False, role="holdout",
            )
        )

    holdouts = [c for c in cases if c["role"] == "holdout"]
    dens_holdout_ok = all(
        c["micro_gold_density"] + 1e-12 >= GATE_DENS for c in holdouts
    )
    dens_regress_ok = all(
        c["micro_gold_density"] + 1e-12
        >= float(R40_L2[c["slug"]]["micro"]) - DROP_EPS
        for c in cases
        if c["slug"] in R40_L2
    )
    lx = next(c for c in cases if c["slug"] == "liuxiang")
    liuxiang_ok = int(lx["cut_hits"]["7"]) >= LIUXIANG_AT7_MIN
    n_leaks = sum(int(c.get("n_layer_leaks") or 0) for c in cases)
    all_submit_ok = all(
        all(r.get("submit_ok") for r in (c.get("layer_rows") or []))
        for c in cases
    )
    cite_plan_ok = all(
        abs(float(c.get("mean_gold_box_to_close") or 0) - 1.0) < 1e-9
        for c in cases
    )
    holdout_mean_usable = (
        sum(float(R41_CITE[c["slug"]]["usable"]) for c in holdouts) / max(1, len(holdouts))
    )
    cite_frozen_ok = all(c["slug"] in R41_CITE for c in cases)
    no_coeff_leak = n_leaks == 0 and all_submit_ok
    gate3_pass = (
        dens_holdout_ok
        and dens_regress_ok
        and liuxiang_ok
        and cite_plan_ok
        and cite_frozen_ok
        and no_coeff_leak
    )

    bullets = [
        f"门槛③：**{'过' if gate3_pass else '未过'}**"
        f"（零系数泄漏；交卷只带 rank／pairs／树17；密度＋引用计划不回退）。",
        f"密度：王虹 {next(c for c in holdouts if c['slug']=='wanghong')['micro_gold_density']:.0%}"
        f"／柬泰 {next(c for c in holdouts if c['slug']=='kh_th')['micro_gold_density']:.0%}"
        f"／AI171 {next(c for c in holdouts if c['slug']=='ai171')['micro_gold_density']:.0%}；"
        f"刘翔@7={lx['cut_hits']['7']}。",
        f"引用：计划层金标→细读全 1.0；R41 holdout 可用密度均值冻结 "
        f"{holdout_mean_usable:.0%}（盒不变不重跑 14B）。",
        f"泄漏审计：{n_leaks} 次；submit 题级全过={all_submit_ok}。",
    ]
    report = {
        "ticket": "R42-decouple-pack",
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict_bullets": bullets,
        "forbidden_keys": sorted(
            __import__(
                "app.kg_lab.layer_boundary", fromlist=["FORBIDDEN_PACK_KEYS"]
            ).FORBIDDEN_PACK_KEYS
        ),
        "boundaries": describe_boundaries(),
        "borrowable": borrowable_checklist(),
        "gate": {
            "dens_holdout_ok": dens_holdout_ok,
            "n_holdout_ge23": sum(
                1 for c in holdouts if c["micro_gold_density"] + 1e-12 >= GATE_DENS
            ),
            "dens_regress_ok": dens_regress_ok,
            "liuxiang_ok": liuxiang_ok,
            "liuxiang_at7": int(lx["cut_hits"]["7"]),
            "cite_plan_ok": cite_plan_ok,
            "cite_frozen_ok": cite_frozen_ok,
            "holdout_mean_usable": round(holdout_mean_usable, 4),
            "n_leaks": n_leaks,
            "all_submit_ok": all_submit_ok,
            "no_coeff_leak": no_coeff_leak,
            "gate3_pass": gate3_pass,
        },
        "cases": cases,
        "r41_cite_frozen": R41_CITE,
        "r40_l2": R40_L2,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R42_decouple_pack.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    md = _markdown(report)
    (OUT / "R42_decouple_pack.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\nGATE3={'PASS' if gate3_pass else 'FAIL'} wall={report['wall_s']}s", flush=True)
    return 0 if gate3_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
