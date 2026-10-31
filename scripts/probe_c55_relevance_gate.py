#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-55 件①：金标段所在源的 high/low/zero 分布＋关零级整源出局反事实。

零模型、只读。口径＝金标 (doc_id, para_id) 段键逐字；L2＝pack_material 选中。
反事实＝同案卷同预算，只让 pack 不再因 level==zero 整源出局。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c55_relevance_gate.py \\
    --run-dir /tmp/s4runs/time-20261023-173124
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material, set_material_budget  # noqa: E402
from app.core.relevance import classify_sources  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    discover_reports,
    gold_paras_for_question,
)


def _seg_to_source(dossier: Dossier) -> dict[str, str]:
    out: dict[str, str] = {}
    for src in dossier.sources:
        for seg in src.segments:
            out[str(seg.id)] = src.id
    return out


def _pack_selected(dossier: Dossier, budget: int, *, skip_zero: bool) -> set[str]:
    """skip_zero=True＝生产口径；False＝反事实（零级源仍可入箱）。"""
    set_material_budget(budget)
    if skip_zero:
        pack = pack_material(dossier)
        return {str(x) for x in (pack.get("selected") or [])}

    # 反事实：临时把 zero 改写成 low，再装箱（不改案卷、不改写 seg.text）
    import app.core.relevance as rel_mod
    real = rel_mod.classify_sources

    def _no_zero(d):
        rows = real(d)
        for r in rows:
            if r.get("level") == "zero" and "人工强制排除" not in str(r.get("reason") or ""):
                r["level"] = "low"
                r["reason"] = (r.get("reason") or "") + "【C-55 反事实：关零级整源出局】"
        return rows

    rel_mod.classify_sources = _no_zero
    try:
        # material.pack_material 内 from … import 已绑名；需补丁 material 侧引用
        import app.core.material as mat_mod
        mat_mod.classify_sources = _no_zero
        pack = pack_material(dossier)
        return {str(x) for x in (pack.get("selected") or [])}
    finally:
        rel_mod.classify_sources = real
        mat_mod.classify_sources = real


def measure(run_dir: Path, gold_dir: Path) -> dict:
    per_case: dict[str, dict] = {}
    tot = {
        "denom": 0,
        "l2_now": 0,
        "l2_cf": 0,
        "gold_in_zero": 0,
        "level_of_gold_src": Counter(),
    }
    zero_sources: list[dict] = []

    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        gold, _sk = gold_paras_for_question(gold_dir / case, qid)
        if not gold:
            continue
        budget = int(((rep.get("accounting") or {}).get(
            "pack_window") or {}).get("budget") or 0)
        levels = {r["source_id"]: r for r in classify_sources(dossier)}
        seg2src = _seg_to_source(dossier)

        sel_now = _pack_selected(dossier, budget, skip_zero=True)
        sel_cf = _pack_selected(dossier, budget, skip_zero=False)

        c = per_case.setdefault(case, {
            "denom": 0, "l2_now": 0, "l2_cf": 0, "gold_in_zero": 0,
            "levels": Counter(), "zero_gold_paras": [],
            "gained": [], "lost": [],
        })
        for doc, para in gold:
            src_id = seg2src.get(para, "")
            lv = (levels.get(src_id) or {}).get("level") or "?"
            c["levels"][lv] += 1
            tot["level_of_gold_src"][lv] += 1
            c["denom"] += 1
            tot["denom"] += 1
            in_now = para in sel_now
            in_cf = para in sel_cf
            if in_now:
                c["l2_now"] += 1
                tot["l2_now"] += 1
            if in_cf:
                c["l2_cf"] += 1
                tot["l2_cf"] += 1
            if lv == "zero":
                c["gold_in_zero"] += 1
                tot["gold_in_zero"] += 1
                c["zero_gold_paras"].append((qid, para, src_id))
            if in_cf and not in_now:
                c["gained"].append((qid, para, src_id, lv))
            if in_now and not in_cf:
                c["lost"].append((qid, para, src_id, lv))

        # 登记零级源（含几个金标段）
        gold_paras = {para for _d, para in gold}
        for sid, row in levels.items():
            if row.get("level") != "zero":
                continue
            n_g = sum(1 for seg in next(
                (s for s in dossier.sources if s.id == sid),
                type("X", (), {"segments": []})()).segments
                if str(seg.id) in gold_paras)
            zero_sources.append({
                "case": case, "qid": qid, "source_id": sid,
                "title": row.get("title"), "n_gold_segs": n_g,
                "reason": row.get("reason"),
            })

    return {"per_case": per_case, "tot": tot, "zero_sources": zero_sources}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="C-55 资格线件① 探针")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    args = p.parse_args(argv)
    run_dir = Path(args.run_dir)
    gold_dir = Path(args.gold_dir)
    if not run_dir.is_dir():
        print(f"跑次不存在：{run_dir}", file=sys.stderr)
        return 2
    if not gold_dir.is_dir():
        print(f"金标不存在：{gold_dir}", file=sys.stderr)
        return 2

    out = measure(run_dir, gold_dir)
    tot = out["tot"]
    print(f"=== C-55 件① run={run_dir.name} gold={gold_dir} ===")
    print(f"分母={tot['denom']}  金标段落在 zero 源＝{tot['gold_in_zero']}")
    print(f"金标段所在源 level 分布＝{dict(tot['level_of_gold_src'])}")
    print(f"L2 现值（零级出局开）＝{tot['l2_now']}/{tot['denom']}")
    print(f"L2 反事实（关零级整源出局）＝{tot['l2_cf']}/{tot['denom']}")
    delta = tot["l2_cf"] - tot["l2_now"]
    print(f"Δ＝{delta:+d}  （判据 b：必须 ≠0；Δ=0 ⇒ 件② 逃逸披露）")
    print()
    print(f"{'case':32} {'den':>4} {'zero金标':>6} {'L2现':>6} {'L2反':>6} "
          f"{'high':>4} {'low':>4} {'zero':>4}")
    for case, c in sorted(out["per_case"].items()):
        lv = c["levels"]
        print(f"  {case[:30]:30} {c['denom']:4} {c['gold_in_zero']:6} "
              f"{c['l2_now']:3}/{c['denom']:<3} {c['l2_cf']:3}/{c['denom']:<3} "
              f"{lv.get('high', 0):4} {lv.get('low', 0):4} {lv.get('zero', 0):4}")

    # 判据 a 目标：柬泰 9/16＋印航 6/24＝15
    kh = [k for k in out["per_case"] if "柬泰" in k]
    yin = [k for k in out["per_case"] if "印度航空" in k or "印航" in k]
    a_ok = False
    if kh and yin:
        z_k = out["per_case"][kh[0]]["gold_in_zero"]
        z_y = out["per_case"][yin[0]]["gold_in_zero"]
        d_k = out["per_case"][kh[0]]["denom"]
        d_y = out["per_case"][yin[0]]["denom"]
        print()
        print(f"判据 a 对照：柬泰 zero金标={z_k}/{d_k}  印航={z_y}/{d_y}  "
              f"合计={z_k + z_y}/{d_k + d_y}  （目标 9/16＋6/24＝15/105 子集）")
        a_ok = (z_k == 9 and d_k == 16 and z_y == 6 and d_y == 24
                and tot["gold_in_zero"] == 15 and tot["denom"] == 105)
        # 若分母不是 105（缺吉隆），仍核对柬泰＋印航子集
        if not a_ok and tot["denom"] != 105:
            a_ok = (z_k == 9 and d_k == 16 and z_y == 6 and d_y == 24
                    and z_k + z_y == 15)
        print(f"判据 a 复现 15（柬泰9＋印航6）：{'✅' if (z_k == 9 and z_y == 6) else '❌'}")
    print(f"判据 b 反事实≠现值：{'✅' if delta != 0 else '❌ → 逃逸口披露'}")

    # 零级源清单（含金标段的）
    hit = [z for z in out["zero_sources"] if z["n_gold_segs"] > 0]
    print(f"\n含金标段的零级源条数＝{len(hit)}（按题展开）")
    for z in hit[:40]:
        print(f"  {z['case'][:20]}/{z['qid']} {z['source_id']} "
              f"n_gold={z['n_gold_segs']} 《{str(z['title'])[:24]}》")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
