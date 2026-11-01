#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-108：默认开密度交卷 vs 旗关旧装满 vs R44 微密度（只量）。

尺：刘翔 3 题＋holdout 三案×3；禁百炼；零 LLM。
验收：旗关＝旧行为；默认开 holdout L2≥旗关；微密度贴 R44；刘翔@7≥11；泄漏0。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c108_density_default.py \\
      --out artifacts/C108_density_default_measure.md
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

from app.core.kg_density_bridge import (  # noqa: E402
    density_submit_surface,
    ensure_kg_submit_from_density,
)
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


def _lock() -> None:
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1/v1"
    os.environ["OPENAI_API_KEY"] = "ollama-local-only"
    os.environ.pop("VERITAS_KG_CAP_SEGMENTS", None)  # 默认不硬顶


def _meta() -> dict[tuple[str, str], dict]:
    if not (C85 / "score_input.json").exists():
        return {}
    out = {}
    for j in json.loads((C85 / "score_input.json").read_text(encoding="utf-8")):
        out[(j["case"], j["qid"])] = j
    return out


def _r44() -> dict[str, dict]:
    raw = json.loads(R44.read_text(encoding="utf-8"))
    return {c["slug"]: c for c in raw["cases"]}


def _l2_at7(dossier, selected: set[str], gold: set) -> int:
    """按 priority／装箱稳定序取前 7 段的金标命中。"""
    # selected 无序；用 dossier 段序中落在 selected 的前缀不稳定
    # 改：用 accounting priority 若有，否则按 id 排序截 7
    acc = dossier.accounting or {}
    pri = [str(x) for x in (acc.get("kg_priority_segment_ids") or []) if str(x)]
    head = [x for x in pri if x in selected][:7]
    if len(head) < 7:
        rest = sorted(selected - set(head))
        head = head + rest[: 7 - len(head)]
    loc = selected_locs(dossier, set(head))
    return l2_hits(gold, loc)


def _one(slug, qid, role, r44c, meta, gold_dir) -> dict[str, Any]:
    case = SLUG_CASE[slug]
    qrow = next(q for q in r44c["questions"] if q["qid"] == qid)
    r44_micro = qrow["density"].get("gold_density")
    r44_k = int(qrow["density"].get("k") or 0)
    query = (meta or {}).get("query") or ""
    budget = int((meta or {}).get("budget") or 12_000)
    gold, denom = _gold_keys(gold_dir, case, qid)

    # 旗关
    d_off = load_official_case(CASES / case)
    d_off.question = query
    p_off = pack_material(d_off, budget_chars=budget)
    sel_off = {str(x) for x in (p_off.get("selected") or [])}
    hits_off = l2_hits(gold, selected_locs(d_off, sel_off))

    # 默认开（密度→窄面，不硬顶）
    # C-108：一筛暂用 R44 盒作 pool 输入（任务允许）；生产无盒时走 BM25 池
    d_on = load_official_case(CASES / case)
    d_on.question = query
    gold_seg = set()
    for _doc, loc in gold:
        gold_seg.add(str(loc) if "#" in str(loc) else f"{_doc}#{loc}")
    r44_box = [str(x) for x in (qrow.get("density") or {}).get("box") or []]
    bridge = density_submit_surface(
        d_on, top_n=180, order=r44_box or None, gold_ids=gold_seg or None,
    )
    leaks = audit_forbidden_keys(bridge["surface"])
    d_on.accounting["kg_submit"] = bridge["surface"]
    d_on.accounting["kg_cap_segments"] = False
    d_on.accounting["kg_density"] = {
        "k": bridge["density"].get("k"),
        "proxy_density": bridge["density"].get("density"),
        "gold_density": bridge["density"].get("gold_density"),
        "met_target": bridge["density"].get("met_target"),
    }
    apply_kg_submit_surface(d_on, enabled=True)
    kw = pack_kwargs_for_kg(d_on)
    assert "max_segments" not in kw
    p_on = pack_material(d_on, budget_chars=budget, **kw)
    sel_on = {str(x) for x in (p_on.get("selected") or [])}
    hits_on = l2_hits(gold, selected_locs(d_on, sel_on))
    at7 = _l2_at7(d_on, sel_on, gold)

    dens = bridge["density"]
    box = list(dens.get("submission") or [])
    box_hits = l2_hits(gold, selected_locs(d_on, set(box)))
    k = int(dens.get("k") or len(box) or 1)
    on_micro = round(box_hits / k, 4) if k else None

    return {
        "slug": slug, "qid": qid, "role": role, "case": case,
        "denom": denom, "budget": budget, "k": k, "r44_k": r44_k,
        "leaks": leaks,
        "off_l2": hits_off, "on_l2": hits_on, "delta": hits_on - hits_off,
        "n_off": len(sel_off), "n_on": len(sel_on),
        "at7": at7,
        "box_hits": box_hits,
        "on_micro": on_micro,
        "r44_micro": r44_micro,
        "proxy_density": dens.get("density"),
        "met_target": dens.get("met_target"),
        "gold_density_disclosure": dens.get("gold_density"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "artifacts/C108_density_default_measure.md"))
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    args = ap.parse_args()
    _lock()
    t0 = time.perf_counter()
    r44 = _r44()
    meta = _meta()
    rows = []
    for slug, qid, role in PLAN:
        print(f"… {slug}/{qid}", flush=True)
        row = _one(slug, qid, role, r44[slug], meta.get((SLUG_CASE[slug], qid)), Path(args.gold_dir))
        rows.append(row)
        print(
            f"   off={row['off_l2']}/{row['denom']} on={row['on_l2']} "
            f"Δ={row['delta']:+d} at7={row['at7']} "
            f"micro={row['on_micro']}/{row['r44_micro']} k={row['k']}",
            flush=True,
        )

    lx = [r for r in rows if r["slug"] == "liuxiang"]
    ho = [r for r in rows if r["role"] == "holdout"]
    lx_at7 = sum(r["at7"] for r in lx)
    ho_off = sum(r["off_l2"] for r in ho)
    ho_on = sum(r["on_l2"] for r in ho)
    ho_den = sum(r["denom"] for r in ho)
    leaks = sum(len(r["leaks"]) for r in rows)
    micro_ok = all(
        r["on_micro"] is None or r["r44_micro"] is None
        or abs(float(r["on_micro"]) - float(r["r44_micro"])) <= 0.34
        for r in rows
    )
    # 验收
    gate = {
        "holdout_l2_ge_off": ho_on >= ho_off,
        "liuxiang_at7_ge_11": lx_at7 >= 11,
        "leaks_zero": leaks == 0,
        "micro_near_r44": micro_ok,
    }
    passed = all(gate.values())
    wall = time.perf_counter() - t0

    lines = [
        "# C-108 密度交卷默认开测量",
        "",
        f"> 墙钟 {wall:.1f}s；默认不硬顶 max_segments；禁百炼；零 LLM。",
        f"> 验收过线：{'YES' if passed else 'NO'} — {gate}",
        "",
        "## 结论（事实）",
        "",
        f"- 刘翔@7 合计：{lx_at7}（门槛≥11）",
        f"- holdout 合计 L2：旗关 {ho_off}/{ho_den} → 默认开 {ho_on}/{ho_den}",
        f"- 泄漏路径数：{leaks}",
        f"- 微密度贴近 R44（容差 0.34）：{micro_ok}",
        "",
        "## 分题",
        "",
    ]
    for r in rows:
        lines.append(
            f"- {r['slug']}/{r['qid']}: 旗关 L2 {r['off_l2']}/{r['denom']} "
            f"n={r['n_off']}；开 {r['on_l2']} n={r['n_on']} Δ={r['delta']:+d}；"
            f"at7={r['at7']}；盒微密度 {r['on_micro']} vs R44 {r['r44_micro']}；"
            f"k={r['k']}（R44k={r['r44_k']}）；leaks={r['leaks']}"
        )
    lines.append("")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"gate": gate, "passed": passed, "liuxiang_at7": lx_at7,
               "holdout_off": ho_off, "holdout_on": ho_on, "holdout_denom": ho_den,
               "leaks": leaks, "rows": rows, "wall_s": wall}
    out.write_text("\n".join(lines), encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n======== GATE ========", flush=True)
    print(payload["passed"], gate, f"lx@7={lx_at7}", f"ho {ho_off}->{ho_on}", flush=True)
    print("wrote", out, flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
