#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-109：一筛进池默认路径 vs 旗关 vs C-108／R44（不手工灌 R44 盒）。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c109_stage1_pool.py \\
      --out artifacts/C109_stage1_measure.md
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
C108 = ROOT / "artifacts/C108_density_default_measure.json"
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


def _lock() -> None:
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1/v1"
    os.environ["OPENAI_API_KEY"] = "ollama-local-only"
    os.environ.pop("VERITAS_KG_CAP_SEGMENTS", None)
    os.environ["VERITAS_KG_STAGE1"] = "1"
    os.environ["VERITAS_KG_SUBMIT_SURFACE"] = "1"


def _meta() -> dict[tuple[str, str], dict]:
    if not (C85 / "score_input.json").exists():
        return {}
    return {
        (j["case"], j["qid"]): j
        for j in json.loads((C85 / "score_input.json").read_text(encoding="utf-8"))
    }


def _r44() -> dict[str, dict]:
    return {c["slug"]: c for c in json.loads(R44.read_text(encoding="utf-8"))["cases"]}


def _c108_holdout_on() -> int | None:
    if not C108.exists():
        return None
    d = json.loads(C108.read_text(encoding="utf-8"))
    return int(d.get("holdout_on") or 0)


def _l2_at7(dossier, selected: set[str], gold: set) -> int:
    pri = [str(x) for x in (dossier.accounting or {}).get("kg_priority_segment_ids") or []]
    head = [x for x in pri if x in selected][:7]
    if len(head) < 7:
        head = head + sorted(selected - set(head))[: 7 - len(head)]
    return l2_hits(gold, selected_locs(dossier, set(head)))


def _one(slug, qid, role, r44c, meta, gold_dir) -> dict[str, Any]:
    case = SLUG_CASE[slug]
    qrow = next(q for q in r44c["questions"] if q["qid"] == qid)
    r44_micro = qrow["density"].get("gold_density")
    query = (meta or {}).get("query") or ""
    budget = int((meta or {}).get("budget") or 12_000)
    gold, denom = _gold_keys(gold_dir, case, qid)
    gold_seg = {str(loc) if "#" in str(loc) else f"{doc}#{loc}" for doc, loc in gold}

    d_off = load_official_case(CASES / case)
    d_off.question = query
    p_off = pack_material(d_off, budget_chars=budget)
    sel_off = {str(x) for x in (p_off.get("selected") or [])}
    hits_off = l2_hits(gold, selected_locs(d_off, sel_off))

    # 默认开：一筛→密度→窄面；**不**灌 R44 盒
    d_on = load_official_case(CASES / case)
    d_on.question = query
    bridge = density_submit_surface(
        d_on, top_n=180, order=None, gold_ids=gold_seg or None, use_stage1=True,
    )
    leaks = audit_forbidden_keys(bridge["surface"])
    if bridge.get("stage1"):
        leaks += audit_forbidden_keys(bridge["stage1"].get("export") or {})
    d_on.accounting["kg_submit"] = bridge["surface"]
    d_on.accounting["kg_cap_segments"] = False
    apply_kg_submit_surface(d_on, enabled=True)
    kw = pack_kwargs_for_kg(d_on)
    p_on = pack_material(d_on, budget_chars=budget, **kw)
    sel_on = {str(x) for x in (p_on.get("selected") or [])}
    hits_on = l2_hits(gold, selected_locs(d_on, sel_on))
    at7 = _l2_at7(d_on, sel_on, gold)

    dens = bridge["density"]
    box = list((bridge["surface"].get("density_public") or {}).get("box")
               or dens.get("submission") or [])
    dens_k = int((bridge["surface"].get("density_public") or {}).get("dens_k")
                 or dens.get("k") or len(box) or 1)
    box_hits = l2_hits(gold, selected_locs(d_on, set(box))) if box else 0
    on_micro = round(box_hits / dens_k, 4) if dens_k else None

    return {
        "slug": slug, "qid": qid, "role": role, "denom": denom,
        "off_l2": hits_off, "on_l2": hits_on, "delta": hits_on - hits_off,
        "n_off": len(sel_off), "n_on": len(sel_on), "at7": at7,
        "box_hits": box_hits, "dens_k": dens_k,
        "on_micro": on_micro, "r44_micro": r44_micro,
        "leaks": leaks,
        "stage1_pool_n": len((bridge.get("stage1") or {}).get("pool_ids") or []),
        "pool_order_n": bridge.get("pool_order_n"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "artifacts/C109_stage1_measure.md"))
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    args = ap.parse_args()
    _lock()
    t0 = time.perf_counter()
    r44, meta = _r44(), _meta()
    c108_ho = _c108_holdout_on()
    rows = []
    for slug, qid, role in PLAN:
        print(f"… {slug}/{qid}", flush=True)
        row = _one(slug, qid, role, r44[slug], meta.get((SLUG_CASE[slug], qid)),
                   Path(args.gold_dir))
        rows.append(row)
        print(
            f"   off={row['off_l2']}/{row['denom']} on={row['on_l2']} "
            f"Δ={row['delta']:+d} at7={row['at7']} "
            f"micro={row['on_micro']}/{row['r44_micro']} "
            f"pool={row['stage1_pool_n']}",
            flush=True,
        )

    lx = [r for r in rows if r["slug"] == "liuxiang"]
    ho = [r for r in rows if r["role"] == "holdout"]
    lx_at7 = sum(r["at7"] for r in lx)
    ho_off = sum(r["off_l2"] for r in ho)
    ho_on = sum(r["on_l2"] for r in ho)
    ho_den = sum(r["denom"] for r in ho)
    leaks = sum(len(r["leaks"]) for r in rows)
    # C-108 holdout=29 含手工 R44 盒；C-109 默认路径不灌盒。
    # 硬闸：泄漏0、刘翔@7≥11、holdout≥旗关；C-108 对照只披露。
    gate = {
        "leaks_zero": leaks == 0,
        "liuxiang_at7_ge_11": lx_at7 >= 11,
        "holdout_ge_flag_off": ho_on >= ho_off,
    }
    gate_soft = {
        "holdout_ge_c108_r44_box_path": (
            c108_ho is None or ho_on >= int(c108_ho)
        ),
    }
    passed = all(gate.values())
    wall = time.perf_counter() - t0
    lines = [
        "# C-109 一筛进池测量（无手工 R44 盒）",
        "",
        f"> 墙钟 {wall:.1f}s；STAGE1=1；不灌 R44 盒；禁百炼。",
        f"> 过线：{'YES' if passed else 'NO'} — {gate}",
        f"> C-108 holdout_on 对照：{c108_ho}",
        "",
        f"- 刘翔@7={lx_at7}（≥11）",
        f"- holdout L2 旗关 {ho_off}/{ho_den} → 开 {ho_on}/{ho_den}",
        f"- 泄漏={leaks}",
        "",
    ]
    for r in rows:
        lines.append(
            f"- {r['slug']}/{r['qid']}: 关 {r['off_l2']}/{r['denom']} "
            f"开 {r['on_l2']} Δ={r['delta']:+d} at7={r['at7']} "
            f"micro {r['on_micro']} vs R44 {r['r44_micro']} "
            f"dens_k={r['dens_k']} pool_n={r['stage1_pool_n']}"
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "passed": passed, "gate": gate, "gate_soft": gate_soft,
        "liuxiang_at7": lx_at7,
        "holdout_off": ho_off, "holdout_on": ho_on, "holdout_denom": ho_den,
        "c108_holdout_on": c108_ho, "leaks": leaks, "rows": rows, "wall_s": wall,
    }
    lines.append(f"- 软对照 holdout≥C-108(R44盒路径): {gate_soft}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n======== GATE ========", flush=True)
    print(passed, gate, "soft", gate_soft,
          f"lx@7={lx_at7}", f"ho {ho_off}->{ho_on} c108={c108_ho}", flush=True)
    print("wrote", out, flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
