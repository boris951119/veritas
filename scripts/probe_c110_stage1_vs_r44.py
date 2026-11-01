#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-110：只读诊断——一筛池 vs R44 手工盒落差（不合 main）。

三路：
  A＝C-108 默认（灌 R44 短盒）
  B＝C-109 默认一筛池（无短盒）
  C＝旗关／无池基线（纯 pack_material）

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c110_stage1_vs_r44.py \\
      --out artifacts/C110_stage1_vs_r44.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.kg_density_bridge import density_submit_surface  # noqa: E402
from app.core.kg_submit_surface import (  # noqa: E402
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

R44 = Path("/Users/liuboyu/Developer/veritas-obsidian-kg-exp/artifacts/R44_six_case_gate.json")
CASES = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
C85 = Path("/tmp/c85_k180")

SLUG_CASE = {
    "liuxiang": "刘翔编制“二选一”事件",
    "wanghong": "王虹“北大discouraged”事件",
    "kh_th": "柬泰边境争端（2025.12–2026.9）",
    "ai171": "印度航空 AI171 空难（2025.6–2026.5）",
}
PLAN = (
    [("liuxiang", f"q_00{i}", "regression") for i in (1, 2, 3)]
    + [("wanghong", f"q_00{i}", "holdout") for i in (1, 2, 3)]
    + [("kh_th", f"q_00{i}", "holdout") for i in (1, 2, 3)]
    + [("ai171", f"q_00{i}", "holdout") for i in (1, 2, 3)]
)

BUCKETS = (
    "miss_gold_pool",      # 金标未进一筛池
    "pool_dilute",         # 池过大过稀（金标在池但位次差）
    "density_squeeze",     # 入池后被密度盒挤出
    "submit_narrow_drop",  # 窄面／priority 头丢段
    "role_cluster_kill",   # 角色／通稿簇误杀（启发式）
)


def _lock() -> None:
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1/v1"
    os.environ["OPENAI_API_KEY"] = "ollama-local-only"
    os.environ.pop("VERITAS_KG_CAP_SEGMENTS", None)
    os.environ["VERITAS_KG_SUBMIT_SURFACE"] = "1"
    os.environ["VERITAS_KG_STAGE1"] = "1"


def _meta() -> dict[tuple[str, str], dict]:
    if not (C85 / "score_input.json").exists():
        return {}
    return {
        (j["case"], j["qid"]): j
        for j in json.loads((C85 / "score_input.json").read_text(encoding="utf-8"))
    }


def _r44() -> dict[str, dict]:
    return {c["slug"]: c for c in json.loads(R44.read_text(encoding="utf-8"))["cases"]}


def _gold_seg(gold: set) -> set[str]:
    out: set[str] = set()
    for doc, loc in gold:
        s = str(loc) if "#" in str(loc) else f"{doc}#{loc}"
        out.add(s)
    return out


def _at7_ids(dossier, selected: set[str]) -> list[str]:
    pri = [str(x) for x in (dossier.accounting or {}).get("kg_priority_segment_ids") or []]
    head = [x for x in pri if x in selected][:7]
    if len(head) < 7:
        head = head + sorted(selected - set(head))[: 7 - len(head)]
    return head


def _l2_at7(dossier, selected: set[str], gold: set) -> int:
    return l2_hits(gold, selected_locs(dossier, set(_at7_ids(dossier, selected))))


def _gold_in_ids(gold_seg: set[str], ids: list[str] | set[str]) -> list[str]:
    s = set(ids)
    return sorted(g for g in gold_seg if g in s)


def _rank_of(pool: list[str], pid: str) -> int | None:
    try:
        return pool.index(pid) + 1
    except ValueError:
        return None


def _pack_path(
    case: str,
    query: str,
    budget: int,
    *,
    mode: str,
    r44_box: list[str] | None,
    gold_seg: set[str],
) -> dict[str, Any]:
    """mode: A=r44_box, B=stage1, C=off。只回结构；L2 由调用方用原始 gold 算。"""
    d = load_official_case(CASES / case)
    d.question = query
    stage1 = None
    box: list[str] = []
    pool: list[str] = []
    dens_k = 0
    leaks: list[str] = []

    if mode == "C":
        p = pack_material(d, budget_chars=budget)
        sel = {str(x) for x in (p.get("selected") or [])}
        return {
            "sel": sel,
            "n_sel": len(sel),
            "at7_ids": sorted(sel)[:7],
            "pool": [],
            "box": [],
            "dens_k": 0,
            "leaks": [],
            "dossier": d,
            "priority": [],
            "stage1": None,
            "box_gold": [],
        }

    if mode == "A":
        bridge = density_submit_surface(
            d, top_n=180, order=list(r44_box or []) or None,
            gold_ids=gold_seg or None, use_stage1=False,
        )
        pool = list(r44_box or [])
    else:  # B
        bridge = density_submit_surface(
            d, top_n=180, order=None, gold_ids=gold_seg or None, use_stage1=True,
        )
        stage1 = bridge.get("stage1")
        pool = list((stage1 or {}).get("pool_ids") or [])

    leaks = audit_forbidden_keys(bridge["surface"])
    if bridge.get("stage1"):
        leaks += audit_forbidden_keys(bridge["stage1"].get("export") or {})
    dens = bridge["density"]
    surface = bridge["surface"]
    box = list((surface.get("density_public") or {}).get("box")
               or dens.get("submission") or [])
    dens_k = int((surface.get("density_public") or {}).get("dens_k")
                 or dens.get("k") or len(box) or 0)
    d.accounting["kg_submit"] = surface
    d.accounting["kg_cap_segments"] = False
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    bad_kw = {k.lower() for k in kw}
    for bad in ("weights", "coeffs", "default_weights", "r9", "r21"):
        assert bad not in bad_kw, kw
    p = pack_material(d, budget_chars=budget, **kw)
    sel = {str(x) for x in (p.get("selected") or [])}
    return {
        "sel": sel,
        "n_sel": len(sel),
        "at7_ids": _at7_ids(d, sel),
        "pool": pool,
        "box": box,
        "dens_k": dens_k,
        "leaks": leaks,
        "dossier": d,
        "priority": list(
            (d.accounting or {}).get("kg_priority_segment_ids") or []
        ),
        "stage1": stage1,
        "box_gold": _gold_in_ids(gold_seg, box),
    }


def _attribute(
    gold_seg: set[str],
    *,
    r44_box: list[str],
    pool_b: list[str],
    box_b: list[str],
    at7_a: list[str],
    at7_b: list[str],
    dens_k_b: int,
) -> dict[str, Any]:
    """对「A@7 有、B@7 无」的金标段分桶。"""
    gold_a7 = set(_gold_in_ids(gold_seg, at7_a))
    gold_b7 = set(_gold_in_ids(gold_seg, at7_b))
    lost = sorted(gold_a7 - gold_b7)
    gained = sorted(gold_b7 - gold_a7)
    detail = []
    buckets: dict[str, int] = {b: 0 for b in BUCKETS}
    pool_set = set(pool_b)
    box_set = set(box_b)
    r44_set = set(r44_box)

    for g in lost:
        tags: list[str] = []
        rank = _rank_of(pool_b, g)
        in_pool = g in pool_set
        in_box = g in box_set
        in_r44 = g in r44_set
        if not in_pool:
            tags.append("miss_gold_pool")
            buckets["miss_gold_pool"] += 1
        else:
            if rank is not None and rank > 50:
                tags.append("pool_dilute")
                buckets["pool_dilute"] += 1
            if dens_k_b and dens_k_b <= 3 and not in_box:
                tags.append("density_squeeze")
                buckets["density_squeeze"] += 1
            elif in_pool and not in_box:
                tags.append("density_squeeze")
                buckets["density_squeeze"] += 1
            if in_box and g not in set(at7_b):
                tags.append("submit_narrow_drop")
                buckets["submit_narrow_drop"] += 1
        # 启发式：R44 盒内官方通稿位次 vs 一筛远离
        if in_r44 and (not in_pool or (rank or 999) > 30):
            tags.append("role_cluster_kill")
            buckets["role_cluster_kill"] += 1
        if not tags:
            tags.append("density_squeeze")
            buckets["density_squeeze"] += 1
        detail.append({
            "seg": g,
            "in_stage1_pool": in_pool,
            "pool_rank": rank,
            "in_density_box": in_box,
            "in_r44_box": in_r44,
            "tags": tags,
        })
    return {
        "lost_from_a7": lost,
        "gained_vs_a7": gained,
        "lost_detail": detail,
        "buckets": buckets,
    }


def _one(slug, qid, role, r44c, meta, gold_dir) -> dict[str, Any]:
    case = SLUG_CASE[slug]
    qrow = next(q for q in r44c["questions"] if q["qid"] == qid)
    r44_box = [str(x) for x in (qrow.get("density") or {}).get("box") or []]
    r44_micro = (qrow.get("density") or {}).get("gold_density")
    query = (meta or {}).get("query") or ""
    budget = int((meta or {}).get("budget") or 12_000)
    gold, denom = _gold_keys(gold_dir, case, qid)
    gold_seg = _gold_seg(gold)

    path_c = _pack_path(case, query, budget, mode="C", r44_box=None, gold_seg=gold_seg)
    path_a = _pack_path(
        case, query, budget, mode="A", r44_box=r44_box, gold_seg=gold_seg,
    )
    path_b = _pack_path(
        case, query, budget, mode="B", r44_box=None, gold_seg=gold_seg,
    )

    def _finish(path: dict) -> dict:
        d = path["dossier"]
        path["l2"] = l2_hits(gold, selected_locs(d, path["sel"]))
        path["at7"] = (
            _l2_at7(d, path["sel"], gold)
            if path.get("priority") is not None and path.get("dens_k")
            else l2_hits(gold, selected_locs(d, set(path["at7_ids"])))
        )
        if path.get("priority") is not None and (d.accounting or {}).get(
            "kg_priority_segment_ids"
        ):
            path["at7_ids"] = _at7_ids(d, path["sel"])
            path["at7"] = _l2_at7(d, path["sel"], gold)
        path["box_gold"] = _gold_in_ids(gold_seg, path["box"])
        if path["dens_k"] and path["box"]:
            path["micro"] = round(
                l2_hits(gold, selected_locs(d, set(path["box"])))
                / path["dens_k"],
                4,
            )
        else:
            path["micro"] = None
        return path

    path_c = _finish(path_c)
    path_a = _finish(path_a)
    path_b = _finish(path_b)

    pool_b = path_b["pool"]
    gold_in_pool = _gold_in_ids(gold_seg, pool_b)
    gold_ranks = {g: _rank_of(pool_b, g) for g in gold_seg}
    gold_in_pool_at50 = [g for g, r in gold_ranks.items() if r is not None and r <= 50]
    gold_in_pool_at7 = [g for g, r in gold_ranks.items() if r is not None and r <= 7]
    gold_in_r44 = _gold_in_ids(gold_seg, r44_box)

    attr = _attribute(
        gold_seg,
        r44_box=r44_box,
        pool_b=pool_b,
        box_b=path_b["box"],
        at7_a=path_a["at7_ids"],
        at7_b=path_b["at7_ids"],
        dens_k_b=path_b["dens_k"],
    )

    # 全金标相对池／盒的覆盖（不只看 A@7 丢失）
    miss_pool = sorted(g for g in gold_seg if g not in set(pool_b))
    in_pool_not_box = sorted(
        g for g in gold_in_pool if g not in set(path_b["box"])
    )

    return {
        "slug": slug,
        "qid": qid,
        "role": role,
        "denom": denom,
        "r44_box": r44_box,
        "r44_micro": r44_micro,
        "gold_seg": sorted(gold_seg),
        "A": {
            "l2": path_a["l2"],
            "at7": path_a["at7"],
            "n_sel": path_a["n_sel"],
            "dens_k": path_a["dens_k"],
            "box": path_a["box"],
            "box_gold": path_a["box_gold"],
            "micro": path_a.get("micro"),
            "at7_ids": path_a["at7_ids"],
            "at7_gold": _gold_in_ids(gold_seg, path_a["at7_ids"]),
            "leaks": path_a["leaks"],
        },
        "B": {
            "l2": path_b["l2"],
            "at7": path_b["at7"],
            "n_sel": path_b["n_sel"],
            "pool_n": len(pool_b),
            "gold_in_pool": gold_in_pool,
            "gold_in_pool_n": len(gold_in_pool),
            "gold_in_pool_at50_n": len(gold_in_pool_at50),
            "gold_in_pool_at7_n": len(gold_in_pool_at7),
            "gold_ranks": {k: gold_ranks[k] for k in sorted(gold_ranks)},
            "dens_k": path_b["dens_k"],
            "box": path_b["box"],
            "box_gold": path_b["box_gold"],
            "micro": path_b.get("micro"),
            "at7_ids": path_b["at7_ids"],
            "at7_gold": _gold_in_ids(gold_seg, path_b["at7_ids"]),
            "miss_pool": miss_pool,
            "in_pool_not_box": in_pool_not_box,
            "leaks": path_b["leaks"],
        },
        "C": {
            "l2": path_c["l2"],
            "at7": path_c["at7"],
            "n_sel": path_c["n_sel"],
        },
        "delta_l2_AB": path_a["l2"] - path_b["l2"],
        "delta_l2_BC": path_b["l2"] - path_c["l2"],
        "delta_at7_AB": path_a["at7"] - path_b["at7"],
        "gold_in_r44_box": gold_in_r44,
        "attr": attr,
    }


def _render(rows: list[dict], wall: float) -> tuple[str, dict]:
    lx = [r for r in rows if r["slug"] == "liuxiang"]
    ho = [r for r in rows if r["role"] == "holdout"]
    sum_a7 = sum(r["A"]["at7"] for r in lx)
    sum_b7 = sum(r["B"]["at7"] for r in lx)
    sum_c7 = sum(r["C"]["at7"] for r in lx)
    ho_a = sum(r["A"]["l2"] for r in ho)
    ho_b = sum(r["B"]["l2"] for r in ho)
    ho_c = sum(r["C"]["l2"] for r in ho)
    ho_den = sum(r["denom"] for r in ho)
    leaks = sum(
        len(r["A"]["leaks"]) + len(r["B"]["leaks"]) for r in rows
    )

    # 全局桶合计（刘翔 lost 为主 + 全 holdout lost）
    bucket_tot = {b: 0 for b in BUCKETS}
    for r in rows:
        for b, n in r["attr"]["buckets"].items():
            bucket_tot[b] += n

    # 下一刀建议
    miss = bucket_tot["miss_gold_pool"]
    dilute = bucket_tot["pool_dilute"]
    squeeze = bucket_tot["density_squeeze"]
    narrow = bucket_tot["submit_narrow_drop"]
    role = bucket_tot["role_cluster_kill"]
    if sum_b7 < 11 and (miss + dilute) >= squeeze:
        next_cut = "改池（一筛召回／位次）为主；勿先改系数。"
        next_kind = "fix_pool"
    elif sum_b7 < 11 and squeeze > miss:
        next_cut = (
            "池内有金标但密度盒过短挤出 → 保底回灌短盒（或抬 dens_k／核心保金）"
            "；仍不修系数。"
        )
        next_kind = "rehydrate_box"
    else:
        next_cut = "对照看 holdout；下一刀仍禁系数进 pack。"
        next_kind = "observe"

    # 刘翔专项叙述
    lx_lines = []
    for r in lx:
        lx_lines.append(
            f"### {r['slug']}/{r['qid']}  "
            f"A@7={r['A']['at7']} B@7={r['B']['at7']} C≈{r['C']['at7']}  "
            f"denom={r['denom']}"
        )
        lx_lines.append(
            f"- 金标段：{', '.join(r['gold_seg']) or '∅'}"
        )
        lx_lines.append(
            f"- R44 盒金标 {len(r['gold_in_r44_box'])}/{r['denom']}："
            f"{', '.join(r['gold_in_r44_box']) or '∅'}"
        )
        lx_lines.append(
            f"- 一筛池 n={r['B']['pool_n']}；金标入池 "
            f"{r['B']['gold_in_pool_n']}/{r['denom']} "
            f"（@50={r['B']['gold_in_pool_at50_n']} @7={r['B']['gold_in_pool_at7_n']}）"
        )
        ranks = r["B"]["gold_ranks"]
        rank_s = ", ".join(
            f"{g}→{ranks[g] if ranks[g] is not None else 'MISS'}"
            for g in r["gold_seg"]
        )
        lx_lines.append(f"- 金标池位次：{rank_s}")
        lx_lines.append(
            f"- 密度盒 dens_k={r['B']['dens_k']} 盒内金标="
            f"{', '.join(r['B']['box_gold']) or '∅'}；"
            f"micro B={r['B']['micro']} vs R44={r['r44_micro']}"
        )
        lx_lines.append(
            f"- A@7 金标：{', '.join(r['A']['at7_gold']) or '∅'}"
        )
        lx_lines.append(
            f"- B@7 金标：{', '.join(r['B']['at7_gold']) or '∅'}"
        )
        lost = r["attr"]["lost_from_a7"]
        lx_lines.append(f"- A→B @7 丢失：{', '.join(lost) or '∅'}")
        for d in r["attr"]["lost_detail"]:
            lx_lines.append(
                f"  - `{d['seg']}`：入池={d['in_stage1_pool']} "
                f"rank={d['pool_rank']} 入密度盒={d['in_density_box']} "
                f"在R44盒={d['in_r44_box']} 桶={'+'.join(d['tags'])}"
            )
        lx_lines.append("")

    # 对照表（纯文本，方便贴）
    table = [
        "slug/qid | role | denom | C_L2 | B_L2 | A_L2 | ΔA−B | "
        "B_pool_n | gold∈pool | @50 | @7池 | B_dens_k | B_box金 | "
        "A@7 | B@7 | microB/R44",
        "---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---",
    ]
    for r in rows:
        table.append(
            f"{r['slug']}/{r['qid']} | {r['role']} | {r['denom']} | "
            f"{r['C']['l2']} | {r['B']['l2']} | {r['A']['l2']} | "
            f"{r['delta_l2_AB']:+d} | {r['B']['pool_n']} | "
            f"{r['B']['gold_in_pool_n']} | {r['B']['gold_in_pool_at50_n']} | "
            f"{r['B']['gold_in_pool_at7_n']} | {r['B']['dens_k']} | "
            f"{len(r['B']['box_gold'])} | {r['A']['at7']} | {r['B']['at7']} | "
            f"{r['B']['micro']}/{r['r44_micro']}"
        )

    # 主因一句话
    if miss >= max(dilute, squeeze, 1) and sum_b7 < 11:
        verdict = (
            f"主因＝漏金标进池／池头位次不够（miss={miss} dilute={dilute}）；"
            f"密度挤出次之（squeeze={squeeze}）。下一刀＝改池，不修系数、不灌权重进 pack。"
        )
    elif squeeze > miss and sum_b7 < 11:
        verdict = (
            f"主因＝入池后被密度短盒挤出（squeeze={squeeze} miss={miss}）；"
            f"下一刀＝保底回灌短盒或抬 dens 核心，仍只动池／盒接口。"
        )
    else:
        verdict = (
            f"桶分布 miss={miss} dilute={dilute} squeeze={squeeze} "
            f"narrow={narrow} role={role}；刘翔@7 A={sum_a7}→B={sum_b7}。"
        )

    lines = [
        "# C-110 一筛池 vs R44 手工盒落差（只读诊断）",
        "",
        f"> 墙钟 {wall:.1f}s；禁百炼；禁 R9／权重进 pack；本枝不合 main。",
        f"> 三路：A＝C-108+R44短盒；B＝C-109一筛池；C＝旗关纯装箱。",
        "",
        "## 结论",
        "",
        verdict,
        "",
        f"- 刘翔@7：A={sum_a7}／B={sum_b7}／C≈{sum_c7}（门槛对照≥11）",
        f"- holdout L2：A={ho_a}／B={ho_b}／C={ho_c}（分母 {ho_den}）",
        f"- 泄漏合计={leaks}",
        f"- 归因桶合计：{bucket_tot}",
        f"- **下一刀建议**：{next_cut}（kind=`{next_kind}`）",
        "",
        "## 三路对照",
        "",
        *table,
        "",
        "## 刘翔专项（@7 从 ≥11→低的丢段）",
        "",
        *lx_lines,
        "## holdout 摘要（A 有而 B 丢的 @7 金标）",
        "",
    ]
    for r in ho:
        lost = r["attr"]["lost_from_a7"]
        if not lost and r["delta_l2_AB"] == 0:
            continue
        lines.append(
            f"- {r['slug']}/{r['qid']}: L2 A={r['A']['l2']} B={r['B']['l2']} C={r['C']['l2']}；"
            f"池金标 {r['B']['gold_in_pool_n']}/{r['denom']} dens_k={r['B']['dens_k']}；"
            f"@7丢 {', '.join(lost) or '∅'}；"
            f"未入池 {', '.join(r['B']['miss_pool']) or '∅'}；"
            f"入池未进盒 {', '.join(r['B']['in_pool_not_box']) or '∅'}"
        )
    lines.append("")
    lines.append("## 桶说明")
    lines.append("")
    lines.append("- `miss_gold_pool`：金标根本没进 stage1 pool_ids")
    lines.append("- `pool_dilute`：进了池但位次很靠后（>50）")
    lines.append("- `density_squeeze`：在池内却没进密度盒（短 dens_k 挤出）")
    lines.append("- `submit_narrow_drop`：进了密度盒但没进 @7 priority 头")
    lines.append("- `role_cluster_kill`：R44 盒里有、一筛却漏／很远（角色／通稿簇启发式）")
    lines.append("")

    payload = {
        "verdict": verdict,
        "next_cut": next_cut,
        "next_kind": next_kind,
        "liuxiang_at7": {"A": sum_a7, "B": sum_b7, "C": sum_c7},
        "holdout_l2": {"A": ho_a, "B": ho_b, "C": ho_c, "denom": ho_den},
        "buckets": bucket_tot,
        "leaks": leaks,
        "rows": [
            {k: v for k, v in r.items()}
            for r in rows
        ],
        "wall_s": wall,
    }
    # json 可序列化：去掉不可序列化残留
    def _clean(o):
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items() if k != "dossier"}
        if isinstance(o, list):
            return [_clean(x) for x in o]
        if isinstance(o, set):
            return sorted(o)
        return o

    return "\n".join(lines) + "\n", _clean(payload)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "artifacts/C110_stage1_vs_r44.md"))
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    args = ap.parse_args()
    _lock()
    t0 = time.perf_counter()
    r44, meta = _r44(), _meta()
    rows = []
    for slug, qid, role in PLAN:
        print(f"… {slug}/{qid}", flush=True)
        row = _one(
            slug, qid, role, r44[slug],
            meta.get((SLUG_CASE[slug], qid)), Path(args.gold_dir),
        )
        rows.append(row)
        print(
            f"   C={row['C']['l2']} B={row['B']['l2']} A={row['A']['l2']} "
            f"at7 A/B={row['A']['at7']}/{row['B']['at7']} "
            f"pool金={row['B']['gold_in_pool_n']}/{row['denom']} "
            f"dens_k={row['B']['dens_k']} "
            f"lost={row['attr']['lost_from_a7']}",
            flush=True,
        )
    wall = time.perf_counter() - t0
    text, payload = _render(rows, wall)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print("\n======== C-110 ========", flush=True)
    print(payload["verdict"], flush=True)
    print("next:", payload["next_kind"], payload["next_cut"], flush=True)
    print(
        "lx@7", payload["liuxiang_at7"],
        "ho", payload["holdout_l2"],
        "buckets", payload["buckets"],
        flush=True,
    )
    print("wrote", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
