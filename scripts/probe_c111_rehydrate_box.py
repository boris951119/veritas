#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-111：短盒回灌测量（无外仓 R44 文件；对照 C-108／C-110）。

三路：
  A＝C-108 灌 R44 短盒（外仓对照）
  B＝C-111 默认回灌（仓内种子／垫 k）
  C＝回灌关（C-109 一筛）

验收：刘翔@7≥11；holdout L2≥C-108(29)；泄漏＝0。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c111_rehydrate_box.py \\
      --out artifacts/C111_rehydrate_box.md
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


def _lock_base() -> None:
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


def _c108_holdout() -> int:
    if C108.exists():
        return int(json.loads(C108.read_text(encoding="utf-8")).get("holdout_on") or 29)
    return 29


def _gold_seg(gold: set) -> set[str]:
    return {
        str(loc) if "#" in str(loc) else f"{doc}#{loc}"
        for doc, loc in gold
    }


def _at7(dossier, selected: set[str], gold: set) -> int:
    pri = [str(x) for x in (dossier.accounting or {}).get("kg_priority_segment_ids") or []]
    head = [x for x in pri if x in selected][:7]
    if len(head) < 7:
        head = head + sorted(selected - set(head))[: 7 - len(head)]
    return l2_hits(gold, selected_locs(dossier, set(head)))


def _run(
    case: str,
    query: str,
    budget: int,
    gold: set,
    gold_seg: set[str],
    *,
    mode: str,
    r44_box: list[str] | None,
) -> dict[str, Any]:
    """mode A=r44, B=rehydrate default, C=rehydrate off."""
    d = load_official_case(CASES / case)
    d.question = query
    if mode == "A":
        os.environ["VERITAS_KG_REHYDRATE_BOX"] = "0"  # 对照不走种子
        bridge = density_submit_surface(
            d, top_n=180, order=list(r44_box or []) or None,
            gold_ids=gold_seg or None, use_stage1=False,
        )
    elif mode == "B":
        os.environ["VERITAS_KG_REHYDRATE_BOX"] = "1"
        bridge = density_submit_surface(
            d, top_n=180, order=None, gold_ids=gold_seg or None, use_stage1=True,
        )
    else:
        os.environ["VERITAS_KG_REHYDRATE_BOX"] = "0"
        bridge = density_submit_surface(
            d, top_n=180, order=None, gold_ids=gold_seg or None, use_stage1=True,
        )

    leaks = audit_forbidden_keys(bridge["surface"])
    if bridge.get("stage1"):
        leaks += audit_forbidden_keys(bridge["stage1"].get("export") or {})
    rh = bridge.get("rehydrate") or {}
    dens = bridge["density"]
    box = list(
        (bridge["surface"].get("density_public") or {}).get("box")
        or dens.get("submission") or []
    )
    dens_k = int(
        (bridge["surface"].get("density_public") or {}).get("dens_k")
        or dens.get("k") or len(box) or 0
    )
    d.accounting["kg_submit"] = bridge["surface"]
    d.accounting["kg_cap_segments"] = False
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    assert audit_forbidden_keys(kw) == []
    for bad in ("weights", "coeffs", "r9", "r21", "default_weights"):
        assert bad not in {k.lower() for k in kw}
    p = pack_material(d, budget_chars=budget, **kw)
    sel = {str(x) for x in (p.get("selected") or [])}
    return {
        "l2": l2_hits(gold, selected_locs(d, sel)),
        "at7": _at7(d, sel, gold),
        "n_sel": len(sel),
        "dens_k": dens_k,
        "box": box,
        "leaks": leaks,
        "seed_hit": bool(rh.get("seed_hit")),
        "rehydrate_kind": rh.get("kind"),
        "micro": (
            round(
                l2_hits(gold, selected_locs(d, set(box))) / dens_k, 4
            )
            if dens_k and box else None
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "artifacts/C111_rehydrate_box.md"))
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    args = ap.parse_args()
    _lock_base()
    t0 = time.perf_counter()
    r44, meta = _r44(), _meta()
    c108_ho = _c108_holdout()
    rows = []
    for slug, qid, role in PLAN:
        print(f"… {slug}/{qid}", flush=True)
        case = SLUG_CASE[slug]
        qrow = next(q for q in r44[slug]["questions"] if q["qid"] == qid)
        r44_box = [str(x) for x in (qrow.get("density") or {}).get("box") or []]
        r44_micro = (qrow.get("density") or {}).get("gold_density")
        m = meta.get((case, qid)) or {}
        query = m.get("query") or ""
        budget = int(m.get("budget") or 12_000)
        gold, denom = _gold_keys(Path(args.gold_dir), case, qid)
        gs = _gold_seg(gold)
        a = _run(case, query, budget, gold, gs, mode="A", r44_box=r44_box)
        b = _run(case, query, budget, gold, gs, mode="B", r44_box=None)
        c = _run(case, query, budget, gold, gs, mode="C", r44_box=None)
        row = {
            "slug": slug, "qid": qid, "role": role, "denom": denom,
            "r44_micro": r44_micro,
            "A": a, "B": b, "C": c,
            "delta_at7_AB": a["at7"] - b["at7"],
            "delta_l2_AB": a["l2"] - b["l2"],
        }
        rows.append(row)
        print(
            f"   A={a['l2']}/{a['at7']} B={b['l2']}/{b['at7']} "
            f"C={c['l2']}/{c['at7']} seed={b['seed_hit']} "
            f"dens_k B/C={b['dens_k']}/{c['dens_k']}",
            flush=True,
        )

    lx = [r for r in rows if r["slug"] == "liuxiang"]
    ho = [r for r in rows if r["role"] == "holdout"]
    lx_a = sum(r["A"]["at7"] for r in lx)
    lx_b = sum(r["B"]["at7"] for r in lx)
    lx_c = sum(r["C"]["at7"] for r in lx)
    ho_a = sum(r["A"]["l2"] for r in ho)
    ho_b = sum(r["B"]["l2"] for r in ho)
    ho_c = sum(r["C"]["l2"] for r in ho)
    ho_den = sum(r["denom"] for r in ho)
    leaks = sum(
        len(r["A"]["leaks"]) + len(r["B"]["leaks"]) + len(r["C"]["leaks"])
        for r in rows
    )
    gate = {
        "leaks_zero": leaks == 0,
        "liuxiang_at7_ge_11": lx_b >= 11,
        "holdout_ge_c108": ho_b >= c108_ho,
    }
    passed = all(gate.values())
    wall = time.perf_counter() - t0

    lines = [
        "# C-111 短盒回灌测量（rehydrate_box）",
        "",
        f"> 墙钟 {wall:.1f}s；禁百炼；禁 R9／权重进 pack；"
        f"{'过线 YES' if passed else '过线 NO'} — {gate}",
        f"> 对照：A＝外仓 R44 盒；B＝C-111 默认回灌；C＝回灌关（C-109）。",
        f"> C-108 holdout_on 门槛＝{c108_ho}",
        "",
        "## 结论",
        "",
        f"- 刘翔@7：A={lx_a}／B={lx_b}／C={lx_c}（门槛 B≥11）",
        f"- holdout L2：A={ho_a}／B={ho_b}／C={ho_c}（分母 {ho_den}；门槛 B≥{c108_ho}）",
        f"- 泄漏={leaks}",
        f"- 合入建议：{'可建议合 main' if passed else '不合 main（未过线）'}",
        "",
        "## 三路对照（对齐 C-110 表）",
        "",
        "slug/qid | role | denom | C_L2 | B_L2 | A_L2 | C@7 | B@7 | A@7 | "
        "B_seed | B_dens_k | C_dens_k | microB/R44",
        "---|---|---|---|---|---|---|---|---|---|---|---|---",
    ]
    for r in rows:
        lines.append(
            f"{r['slug']}/{r['qid']} | {r['role']} | {r['denom']} | "
            f"{r['C']['l2']} | {r['B']['l2']} | {r['A']['l2']} | "
            f"{r['C']['at7']} | {r['B']['at7']} | {r['A']['at7']} | "
            f"{r['B']['seed_hit']} | {r['B']['dens_k']} | {r['C']['dens_k']} | "
            f"{r['B']['micro']}/{r['r44_micro']}"
        )
    lines.append("")
    lines.append("## 回退")
    lines.append("")
    lines.append("- `VERITAS_KG_REHYDRATE_BOX=0` → C-109（一筛池→短 dens_k，无冻结盒）")
    lines.append("- 有上游短盒仍优先于种子／垫 k")
    lines.append("- 系数仍隔离；交付只多短盒回灌窄面")
    lines.append("")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "passed": passed, "gate": gate,
        "liuxiang_at7": {"A": lx_a, "B": lx_b, "C": lx_c},
        "holdout_l2": {"A": ho_a, "B": ho_b, "C": ho_c, "denom": ho_den},
        "c108_holdout_on": c108_ho, "leaks": leaks,
        "rows": rows, "wall_s": wall,
        "merge_advice": "merge_ok" if passed else "do_not_merge",
    }
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n======== GATE ========", flush=True)
    print(passed, gate, f"lx@7={lx_b}", f"ho={ho_b} c108={c108_ho}", flush=True)
    print("wrote", out, flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
