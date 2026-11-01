#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-107：开旗测交卷窄面（只量、不合入、不灌系数）。

输入：R44 artifacts 盒序（rank_order／k）＋由盒∩金标重建的 tree17 close_read
与 conflict_pairs（无权威浮点／无 feats）。主尺＝刘翔 3 题；冒烟＝吉隆／中美AI 各 1。

对照：旗关 A0 pack vs 旗开 apply＋max_segments=k。
禁百炼；本脚本零 LLM（focus／pairs 走提示词与报告渲染面）。

用法：
  VERITAS_KG_SUBMIT_SURFACE=1 PYTHONPATH=. .venv/bin/python \\
    scripts/probe_c107_kg_submit_surface.py --out artifacts/C107_surface_measure.md
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

from app.agents.prompts import render_segments_block  # noqa: E402
from app.core.kg_submit_surface import (  # noqa: E402
    FORBIDDEN_PACK_KEYS,
    apply_kg_submit_surface,
    assert_clean_pack_kwargs,
    assert_submit_no_coeff,
    audit_forbidden_keys,
    build_submit_surface,
    kg_focus_segment_ids,
    pack_kwargs_for_kg,
    stage2_box_export,
)
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from app.pipeline import _render_kg_conflict_pairs_section  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

R44_JSON = Path.home().parent.joinpath(
    # fallback; overridden below
    "Developer/veritas-obsidian-kg-exp/artifacts/R44_six_case_gate.json"
)
# prefer sibling exp repo
_EXP = Path("/Users/liuboyu/Developer/veritas-obsidian-kg-exp/artifacts/R44_six_case_gate.json")
if _EXP.exists():
    R44_JSON = _EXP

CASES_ROOT = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
C85 = Path("/tmp/c85_k180")

SLUG_TO_CASE = {
    "liuxiang": "刘翔编制“二选一”事件",
    "jilong": "2026·8·26 吉隆口岸泥石流灾害",
    "us_cn_ai": "中美AI事故预警提议（2026.9）",
    "wanghong": "王虹“北大discouraged”事件",
    "kh_th": "柬泰边境争端（2025.12–2026.9）",
    "ai171": "印度航空 AI171 空难（2025.6–2026.5）",
}

# 刘翔 3 全量；吉隆／中美 各 q_001 冒烟
MEASURE_PLAN_SMOKE = [
    ("liuxiang", "q_001", "regression"),
    ("liuxiang", "q_002", "regression"),
    ("liuxiang", "q_003", "regression"),
    ("jilong", "q_001", "smoke"),
    ("us_cn_ai", "q_001", "smoke"),
]

# holdout 三案 × 三题
MEASURE_PLAN_HOLDOUT = [
    ("wanghong", "q_001", "holdout"),
    ("wanghong", "q_002", "holdout"),
    ("wanghong", "q_003", "holdout"),
    ("kh_th", "q_001", "holdout"),
    ("kh_th", "q_002", "holdout"),
    ("kh_th", "q_003", "holdout"),
    ("ai171", "q_001", "holdout"),
    ("ai171", "q_002", "holdout"),
    ("ai171", "q_003", "holdout"),
]

MEASURE_PLAN = MEASURE_PLAN_SMOKE  # 默认兼容旧调用


def _lock_local() -> None:
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1/v1"
    os.environ["OPENAI_API_KEY"] = "ollama-local-only"
    os.environ["VERITAS_KG_SUBMIT_SURFACE"] = "1"


def _queries_from_c85() -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not (C85 / "score_input.json").exists():
        return out
    for j in json.loads((C85 / "score_input.json").read_text(encoding="utf-8")):
        out[(j["case"], j["qid"])] = j
    return out


def _r44_by_slug() -> dict[str, dict]:
    raw = json.loads(R44_JSON.read_text(encoding="utf-8"))
    return {c["slug"]: c for c in raw["cases"]}


def _surface_from_r44_q(qrow: dict) -> dict[str, Any]:
    """R44 盒序作 rank；close_read／pairs 由盒∩金标重建（零系数）。"""
    dens = qrow["density"]
    box = [str(x) for x in (dens.get("box") or [])]
    k = int(dens.get("k") or len(box) or 0)
    cuts = (qrow.get("cuts") or {}).get(str(k)) or {}
    gold_hits = {str(x) for x in (cuts.get("hit_ids") or [])}
    close = [x for x in box if x in gold_hits] or list(box[: min(3, len(box))])
    support = [{"id": x, "option": "采信／金标侧"} for x in box if x in gold_hits]
    oppose_ids = [x for x in box if x not in gold_hits]
    oppose = [{"id": x, "option": "对立／非金标侧"} for x in oppose_ids[: max(1, len(support))]]
    conflicts = []
    for i, srow in enumerate(support):
        if i >= len(oppose):
            break
        conflicts.append({
            "support_id": srow["id"],
            "oppose_id": oppose[i]["id"],
            "support_option": srow["option"],
            "oppose_option": oppose[i]["option"],
            "preferred": srow["id"],
            "reason": "r44_box_gold_vs_filler",
        })
    auth = {
        "top_ids": box,
        "k": k,
        "conflict_pairs": {
            "options": ["采信／金标侧", "对立／非金标侧"],
            "support": support,
            "oppose": oppose,
            "conflicts": conflicts,
        },
        "density": {"k": k, "n_core": len(close), "met_target": True,
                    "route": dens.get("route") or ""},
        "intent": {"route": dens.get("route") or qrow.get("intent", {}).get("route") or ""},
    }
    box_ex = stage2_box_export(auth)
    return build_submit_surface(box_ex, tree17_plan={
        "close_read": close,
        "pair_required": bool(conflicts),
        "conflict_route": bool(conflicts),
        "items": [
            {"para_id": x, "in_close_read": True, "label": "采信",
             "side": "support", "stance": "support"}
            for x in close
        ],
    })


def _measure_one(
    *,
    slug: str,
    qid: str,
    role: str,
    r44_case: dict,
    qmeta: dict[str, Any] | None,
    gold_dir: Path,
) -> dict[str, Any]:
    case = SLUG_TO_CASE[slug]
    qrow = next(q for q in r44_case["questions"] if q["qid"] == qid)
    surface = _surface_from_r44_q(qrow)
    assert_submit_no_coeff(surface)
    leaks = audit_forbidden_keys(surface)
    if leaks:
        raise SystemExit(f"surface leaks {case} {qid}: {leaks}")

    dossier = load_official_case(CASES_ROOT / case)
    query = (qmeta or {}).get("query") or dossier.question or ""
    dossier.question = query
    budget = int((qmeta or {}).get("budget") or 12_000)
    gold, denom = _gold_keys(gold_dir, case, qid)

    present = {seg.id for src in dossier.sources for seg in src.segments}
    missing = [x for x in surface["rank_order"] if x not in present]
    rank_ok = [x for x in surface["rank_order"] if x in present]

    # —— 旗关基线 ——
    d_off = load_official_case(CASES_ROOT / case)
    d_off.question = query
    p_off = pack_material(d_off, budget_chars=budget)
    sel_off = {str(x) for x in (p_off.get("selected") or [])}
    loc_off = selected_locs(d_off, sel_off)
    hits_off = l2_hits(gold, loc_off)

    # —— 旗开窄面 ——
    d_on = load_official_case(CASES_ROOT / case)
    d_on.question = query
    d_on.accounting["kg_submit"] = surface
    hints = apply_kg_submit_surface(d_on, surface, enabled=True)
    assert hints is not None
    kw = pack_kwargs_for_kg(d_on)
    assert_clean_pack_kwargs(kw)
    # 禁键不得进 kwargs
    assert not (set(kw) & FORBIDDEN_PACK_KEYS)
    p_on = pack_material(d_on, budget_chars=budget, **kw)
    sel_on = {str(x) for x in (p_on.get("selected") or [])}
    loc_on = selected_locs(d_on, sel_on)
    hits_on = l2_hits(gold, loc_on)
    lost = len((gold & loc_off) - loc_on)
    gained = len((gold & loc_on) - loc_off)

    k = int(surface["k"])
    max_seg_ok = len(sel_on) <= k
    # priority：开旗后先装 rank 前缀（在预算／k 内）
    prefix = rank_ok[:k]
    priority_hit = sum(1 for x in prefix if x in sel_on)
    priority_rate = (priority_hit / len(prefix)) if prefix else None

    focus = kg_focus_segment_ids(d_on) or []
    # 注入分析师侧：focus 进提示词（钉死已装箱，避免二次 pack）
    d_on.accounting["material_pack_selected"] = sorted(sel_on)
    block = render_segments_block(d_on, focus_segment_ids=focus)
    focus_in_prompt = all(fid in block for fid in focus) if focus else False
    close = list((surface.get("tree17") or {}).get("close_read_ids") or [])
    close_in_pack = sum(1 for x in close if x in sel_on)
    close_cover = (close_in_pack / len(close)) if close else None

    # conflict_pairs → 报告节
    lines: list[str] = []
    _render_kg_conflict_pairs_section(lines, d_on)
    report_blob = "\n".join(lines)
    pairs = surface.get("conflict_pairs") or {}
    pair_ids = []
    if isinstance(pairs, dict):
        for p in pairs.get("conflicts") or []:
            if isinstance(p, dict):
                pair_ids.extend([p.get("support_id"), p.get("oppose_id")])
    if not pair_ids:
        # fact_check／单点盒无成对：无泄漏即过（节可空）
        pairs_in_report = True
    else:
        pairs_in_report = bool(report_blob) and all(
            (pid in report_blob) for pid in pair_ids if pid
        )

    # 开旗盒内金标微密度（对照 R44 density.gold_density）
    on_micro = (hits_on / k) if k else None
    r44_micro = qrow.get("density", {}).get("gold_density")

    return {
        "slug": slug,
        "case": case,
        "qid": qid,
        "role": role,
        "query": query[:80],
        "budget": budget,
        "k": k,
        "denom": denom,
        "n_gold": len(gold),
        "rank_n": len(surface["rank_order"]),
        "rank_missing_in_dossier": missing,
        "n_close_read": len(close),
        "n_conflict_pairs": len((pairs.get("conflicts") if isinstance(pairs, dict) else []) or []),
        "surface_leaks": leaks,
        "pack_kwargs": kw,
        "r44_gold_density": r44_micro,
        "on_box_micro": round(on_micro, 4) if on_micro is not None else None,
        "off": {"l2": hits_off, "n_selected": len(sel_off)},
        "on": {
            "l2": hits_on,
            "n_selected": len(sel_on),
            "lost": lost,
            "gained": gained,
            "max_segments_ok": max_seg_ok,
            "priority_in_box": priority_hit,
            "priority_n": len(prefix),
            "priority_rate": round(priority_rate, 3) if priority_rate is not None else None,
            "focus_n": len(focus),
            "focus_in_analyst_prompt": focus_in_prompt,
            "close_in_pack": close_in_pack,
            "close_cover": round(close_cover, 3) if close_cover is not None else None,
            "pairs_in_report": pairs_in_report,
        },
        "delta_l2": hits_on - hits_off,
    }


def _verdict(rows: list[dict], *, plan: str = "smoke") -> dict[str, Any]:
    """三选一：窄面够用／不够（列缺口）／建议整套替换（列范围）。"""
    plumbing_ok = all(
        r["on"]["max_segments_ok"]
        and r["on"]["focus_in_analyst_prompt"]
        and r["on"]["pairs_in_report"]
        and not r["surface_leaks"]
        and not r["rank_missing_in_dossier"]
        for r in rows
    )
    tot_off = sum(r["off"]["l2"] for r in rows)
    tot_on = sum(r["on"]["l2"] for r in rows)
    tot_denom = sum(r["denom"] for r in rows)
    flat_or_up = all(r["delta_l2"] >= 0 for r in rows)

    by_slug: dict[str, dict[str, int]] = {}
    for r in rows:
        s = by_slug.setdefault(r["slug"], {"off": 0, "on": 0, "denom": 0})
        s["off"] += r["off"]["l2"]
        s["on"] += r["on"]["l2"]
        s["denom"] += r["denom"]

    gaps = []
    if not plumbing_ok:
        gaps.append("接通缺口：max_segments／focus／pairs／id 对齐未全过")
    if any(r["rank_missing_in_dossier"] for r in rows):
        gaps.append("部分 rank_order id 不在主线案卷（见各题 rank_missing）")
    if tot_on < tot_off:
        gaps.append(
            f"合计 L2 旗开 {tot_on}/{tot_denom} < 旗关 {tot_off}/{tot_denom} "
            f"（k 硬顶裁箱；窄面只接序不接密度扫描）"
        )
    if not flat_or_up:
        dropped = [f"{r['slug']}/{r['qid']} Δ={r['delta_l2']:+d}" for r in rows if r["delta_l2"] < 0]
        gaps.append("有题 L2 相对旗关下降：" + "；".join(dropped))

    close_weak = [r for r in rows if (r["on"].get("close_cover") or 0) < 1.0]
    if close_weak:
        gaps.append(
            "细读 close_read 未 100% 进箱（"
            + ", ".join(f"{r['slug']}/{r['qid']}={r['on']['close_cover']}" for r in close_weak)
            + "）"
        )

    # R44 微密度对照：开旗盒 L2/k 应贴 R44 gold_density
    micro_mismatch = []
    for r in rows:
        a, b = r.get("on_box_micro"), r.get("r44_gold_density")
        if a is None or b is None:
            continue
        if abs(float(a) - float(b)) > 0.02:
            micro_mismatch.append(
                f"{r['slug']}/{r['qid']} 主线{a} vs R44{b}"
            )
    if micro_mismatch:
        gaps.append("开旗盒微密度与 R44 不一致：" + "；".join(micro_mismatch))

    need_density = (not flat_or_up) or (tot_on + 1 < tot_off) or bool(close_weak)

    if plumbing_ok and not gaps:
        kind = "窄面够用"
        detail = (
            "holdout 接通全绿；L2 未掉；细读全进箱；微密度贴 R44。"
            "可维持只借鉴；暂不必开 density_submit。"
            if plan == "holdout"
            else "接通面全绿；L2 未掉；细读全进箱。可维持只借鉴、不整包。"
        )
    elif plumbing_ok and gaps and all(
        any(x in g for x in ("裁箱", "细读", "L2", "微密度", "下降")) for g in gaps
    ):
        kind = "不够（列缺口）"
        detail = (
            "交付接通已够；L2／细读／密度仍有缺口。"
            + ("建议下一步开 density_submit 实验旗（勿灌系数进 pack）。"
               if need_density else "先补细读／对齐，再议 density_submit。")
        )
    elif not plumbing_ok:
        kind = "不够（列缺口）"
        detail = "接通面未齐，先补缺口；勿先开 density_submit。"
    else:
        kind = "建议整套替换（列替换范围，勿直接开干）"
        detail = "当前读数未强制整包；若强推见 replace_scope。"

    replace_scope = []
    if need_density:
        replace_scope = [
            "可开实验：density_submit（可变 k＋通稿 keep-one）默认关",
            "勿迁：R9／R21 多维系数、DEFAULT_WEIGHTS 进 pack_material",
        ]

    return {
        "kind": kind,
        "detail": detail,
        "gaps": gaps,
        "replace_scope_if_any": replace_scope,
        "plan": plan,
        "total_l2_off": f"{tot_off}/{tot_denom}",
        "total_l2_on": f"{tot_on}/{tot_denom}",
        "by_slug": {
            s: f"{v['on']}/{v['denom']} (off {v['off']})" for s, v in by_slug.items()
        },
        "need_density_submit": need_density,
        "plumbing_ok": plumbing_ok,
        # 兼容旧字段
        "liuxiang_l2_off": (
            f"{by_slug['liuxiang']['off']}/{by_slug['liuxiang']['denom']}"
            if "liuxiang" in by_slug else "n/a"
        ),
        "liuxiang_l2_on": (
            f"{by_slug['liuxiang']['on']}/{by_slug['liuxiang']['denom']}"
            if "liuxiang" in by_slug else "n/a"
        ),
    }


def _md(rows: list[dict], verdict: dict, wall_s: float, *, plan: str) -> str:
    title = (
        "C-107 holdout 三案开旗测量"
        if plan == "holdout"
        else "C-107 交卷窄面开旗测量"
    )
    lines = [
        f"# {title}",
        "",
        f"> 枝 `cursor/c107-kg-submit-surface`；旗 `VERITAS_KG_SUBMIT_SURFACE=1`（测完不改默认）。",
        f"> plan=`{plan}`；窄面源：`{_EXP}` 盒序；close_read／pairs＝盒∩金标重建（零系数）。零 LLM。",
        f"> 墙钟 {wall_s:.1f}s。禁百炼。",
        "",
        "## 结论",
        "",
        f"**{verdict['kind']}** — {verdict['detail']}",
        "",
        f"- 要否开 density_submit：{'建议实验旗下一步' if verdict.get('need_density_submit') else '暂不必'}",
        f"- 合计 L2：旗关 `{verdict['total_l2_off']}` → 旗开 `{verdict['total_l2_on']}`",
        f"- 接通面：{'✓' if verdict['plumbing_ok'] else '✗'}",
        "",
    ]
    if verdict.get("by_slug"):
        lines.append("分案 L2（开／分母，括号内旗关）：")
        for s, blob in verdict["by_slug"].items():
            lines.append(f"- {s}: {blob}")
        lines.append("")
    if verdict["gaps"]:
        lines.append("缺口：")
        for g in verdict["gaps"]:
            lines.append(f"- {g}")
        lines.append("")
    if verdict["replace_scope_if_any"]:
        lines.append("density_submit／替换范围（勿直接开干）：")
        for g in verdict["replace_scope_if_any"]:
            lines.append(f"- {g}")
        lines.append("")

    lines += [
        "## 分题读数（无表，便于复制）",
        "",
    ]
    for r in rows:
        o, n = r["off"], r["on"]
        lines.append(
            f"- {r['slug']}/{r['qid']} role={r['role']} k={r['k']}："
            f"旗关 L2 {o['l2']}/{r['denom']} n_sel={o['n_selected']}；"
            f"旗开 L2 {n['l2']}/{r['denom']} n_sel={n['n_selected']} Δ={r['delta_l2']:+d}；"
            f"max≤k={'Y' if n['max_segments_ok'] else 'N'}；"
            f"priority={n['priority_in_box']}/{n['priority_n']}；"
            f"focus→提示词={'Y' if n['focus_in_analyst_prompt'] else 'N'}；"
            f"pairs→报告={'Y' if n['pairs_in_report'] else 'N'}；"
            f"close进箱={n['close_in_pack']}/{r['n_close_read']}；"
            f"微密度 主线={r.get('on_box_micro')} / R44={r.get('r44_gold_density')}"
        )
    lines += [
        "",
        "## 方法说明",
        "",
        "1. 开旗写入 accounting['kg_submit']；旗关裸 pack；旗开 apply＋max_segments=k。",
        "2. L2＝金标 locator 进箱；微密度＝旗开 L2/k，对照 R44 density.gold_density。",
        "3. kwargs 仅 max_segments；禁系数。零 LLM。",
        "",
        "## 原始摘要 JSON",
        "",
        "```json",
        json.dumps({"verdict": verdict}, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", choices=("smoke", "holdout", "all"), default="smoke")
    ap.add_argument("--out", default="")
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    args = ap.parse_args()
    _lock_local()

    if args.plan == "smoke":
        plan_rows = MEASURE_PLAN_SMOKE
        default_out = ROOT / "artifacts/C107_surface_measure.md"
    elif args.plan == "holdout":
        plan_rows = MEASURE_PLAN_HOLDOUT
        default_out = ROOT / "artifacts/C107_holdout_measure.md"
    else:
        plan_rows = MEASURE_PLAN_SMOKE + MEASURE_PLAN_HOLDOUT
        default_out = ROOT / "artifacts/C107_all_measure.md"
    out = Path(args.out) if args.out else default_out

    t0 = time.perf_counter()
    r44 = _r44_by_slug()
    qmeta = _queries_from_c85()
    rows = []
    for slug, qid, role in plan_rows:
        case = SLUG_TO_CASE[slug]
        meta = qmeta.get((case, qid))
        print(f"… {slug}/{qid} ({role})", flush=True)
        row = _measure_one(
            slug=slug, qid=qid, role=role,
            r44_case=r44[slug], qmeta=meta,
            gold_dir=Path(args.gold_dir),
        )
        rows.append(row)
        print(
            f"   off L2={row['off']['l2']}/{row['denom']} "
            f"on L2={row['on']['l2']} Δ={row['delta_l2']:+d} "
            f"k={row['k']} n={row['off']['n_selected']}→{row['on']['n_selected']} "
            f"micro={row.get('on_box_micro')}/{row.get('r44_gold_density')} "
            f"focus={'Y' if row['on']['focus_in_analyst_prompt'] else 'N'} "
            f"pairs={'Y' if row['on']['pairs_in_report'] else 'N'}",
            flush=True,
        )

    wall = time.perf_counter() - t0
    verdict = _verdict(rows, plan=args.plan)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_md(rows, verdict, wall, plan=args.plan), encoding="utf-8")
    raw = out.with_suffix(".json")
    raw.write_text(
        json.dumps({"verdict": verdict, "rows": rows, "wall_s": wall, "plan": args.plan},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n======== 结论 ========", flush=True)
    print(verdict["kind"], "—", verdict["detail"], flush=True)
    print("density_submit?", verdict.get("need_density_submit"), flush=True)
    for g in verdict["gaps"]:
        print("  ·", g, flush=True)
    print(f"wrote {out}", flush=True)
    print(f"wrote {raw}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
