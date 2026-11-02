#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-118：末批合入后旁证（默认四旗关；零 LLM）。

主尺：刘翔@7／holdout L2／泄漏。对照合前 main 旁证（约 @7=12／holdout=29／leak=0）。
可选：逐旗＝1 烟雾（单题）确认挂点仍在。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c118_batch_merge.py \\
      --out artifacts/C118_batch_merge_114_117.md
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

from app.config import Settings  # noqa: E402
from app.core.kg_density_bridge import density_submit_surface  # noqa: E402
from app.core.kg_submit_surface import (  # noqa: E402
    FORBIDDEN_PACK_KEYS,
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

CASES = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
C85 = Path("/tmp/c85_k180")
CASE_LX = "刘翔编制“二选一”事件"
PLAN = (
    [("liuxiang", CASE_LX, f"q_00{i}", "regression") for i in (1, 2, 3)]
    + [("wanghong", "王虹“北大discouraged”事件", f"q_00{i}", "holdout")
       for i in (1, 2, 3)]
    + [("kh_th", "柬泰边境争端（2025.12–2026.9）", f"q_00{i}", "holdout")
       for i in (1, 2, 3)]
    + [("ai171", "印度航空 AI171 空难（2025.6–2026.5）", f"q_00{i}", "holdout")
       for i in (1, 2, 3)]
)

FLAG_KEYS = (
    "anchor_stable",
    "conflict_trace",
    "conf_calib",
    "tree15_depress",
)
FLAG_ENVS = (
    "VERITAS_ANCHOR_STABLE",
    "VERITAS_CONFLICT_TRACE",
    "VERITAS_CONF_CALIB",
    "VERITAS_TREE15_DEPRESS",
)


def _meta() -> dict[tuple[str, str], dict]:
    if not (C85 / "score_input.json").exists():
        return {}
    return {
        (j["case"], j["qid"]): j
        for j in json.loads((C85 / "score_input.json").read_text(encoding="utf-8"))
    }


def _gold_seg(gold: set) -> set[str]:
    return {
        str(loc) if "#" in str(loc) else f"{doc}#{loc}"
        for doc, loc in gold
    }


def _at7(dossier, selected: set[str], gold: set) -> int:
    pri = [
        str(x) for x in (dossier.accounting or {}).get("kg_priority_segment_ids") or []
    ]
    head = [x for x in pri if x in selected][:7]
    if len(head) < 7:
        head = head + sorted(selected - set(head))[: 7 - len(head)]
    return l2_hits(gold, selected_locs(dossier, set(head)))


def _clear_batch_flags() -> None:
    for e in FLAG_ENVS:
        os.environ.pop(e, None)
        os.environ[e] = "0"


def _run_one(case: str, qid: str) -> dict[str, Any]:
    _clear_batch_flags()
    os.environ["VERITAS_KG_SUBMIT_SURFACE"] = "1"
    os.environ["VERITAS_KG_STAGE1"] = "1"
    os.environ["VERITAS_KG_REHYDRATE_BOX"] = "1"
    meta = _meta().get((case, qid)) or {}
    query = str(meta.get("query") or qid)
    budget = int(meta.get("budget") or 12_000)
    gold, _denom = _gold_keys(DEFAULT_GOLD, case, qid)
    gold_seg = _gold_seg(gold)
    d = load_official_case(CASES / case)
    d.question = query
    bridge = density_submit_surface(
        d, top_n=180, order=None, gold_ids=gold_seg or None, use_stage1=True,
    )
    leaks = audit_forbidden_keys(bridge["surface"])
    d.accounting["kg_submit"] = bridge["surface"]
    d.accounting["kg_cap_segments"] = False
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    for bad in FORBIDDEN_PACK_KEYS:
        assert bad not in (kw or {})
    pack = pack_material(d, budget_chars=budget, **(kw or {}))
    # 默认关：不调用 tree15_depress 重装
    sel = {str(x) for x in (pack.get("selected") or [])}
    return {
        "l2": l2_hits(gold, selected_locs(d, sel)),
        "at7": _at7(d, sel, gold),
        "leaks": len(leaks),
        "n_sel": len(sel),
        "n_excluded": len(pack.get("excluded") or []),
    }


def _smoke_flags() -> dict[str, Any]:
    """逐旗＝1：Settings.from_env 可读；模块可 import。"""
    out: dict[str, Any] = {}
    imports = {
        "anchor_stable": "app.core.anchor_stable",
        "conflict_trace": "app.core.conflict_trace",
        "conf_calib": "app.core.conf_calib",
        "tree15_depress": "app.core.tree15_depress",
    }
    for key, env, mod in zip(FLAG_KEYS, FLAG_ENVS, imports.values()):
        _clear_batch_flags()
        os.environ[env] = "1"
        s = Settings.from_env()
        __import__(mod)
        out[key] = {
            "env": env,
            "settings_on": bool(getattr(s, key)),
            "module": mod,
            "import_ok": True,
        }
    _clear_batch_flags()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", type=Path,
        default=ROOT / "artifacts/C118_batch_merge_114_117.md",
    )
    ap.add_argument("--no-smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    rows = []
    for slug, case, qid, role in PLAN:
        print(f"… {slug}/{qid}", flush=True)
        m = _run_one(case, qid)
        rows.append({"slug": slug, "case": case, "qid": qid, "role": role, **m})
        print(f"   L2 {m['l2']} @7 {m['at7']} leaks {m['leaks']}", flush=True)

    lx = [r for r in rows if r["role"] == "regression"]
    ho = [r for r in rows if r["role"] == "holdout"]
    lx_at7 = sum(r["at7"] for r in lx)
    ho_l2 = sum(r["l2"] for r in ho)
    lx_l2 = sum(r["l2"] for r in lx)
    leaks = sum(r["leaks"] for r in rows)
    wall = time.time() - t0

    s0 = Settings()
    defaults = {k: bool(getattr(s0, k)) for k in FLAG_KEYS}
    smoke = {} if args.no_smoke else _smoke_flags()

    ok = (
        lx_at7 >= 11
        and ho_l2 >= 25  # 不显著掉相对合前 ~29
        and leaks == 0
        and all(v is False for v in defaults.values())
    )
    advice = "YES" if ok else "NO"

    lines = [
        "# C-118 末批合入 C-114～117（合后旁证）",
        "",
        f"> 零 LLM；四旗默认关；墙钟 {wall:.1f}s。",
        "> 禁合 C-113；禁改默认为开；禁 pack 多维系数；未宣称树15 红标已灭。",
        "",
        "## 结论",
        "",
        f"- 刘翔@7：**{lx_at7}**（门槛≥11）",
        f"- holdout L2：**{ho_l2}**（刘翔 L2={lx_l2}；合计 L2={lx_l2 + ho_l2}）",
        f"- 泄漏：**{leaks}**",
        f"- 四旗默认：{defaults}",
        f"- 过线建议：**{advice}**",
        "",
        "## 分题（默认旗关）",
        "",
        "| slug/qid | role | L2 | @7 | leaks |",
        "|---|---|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['slug']}/{r['qid']} | {r['role']} | {r['l2']} | "
            f"{r['at7']} | {r['leaks']} |"
        )
    lines += [
        "",
        "## 一行验收",
        "",
        f"过线建议 **{advice}**＋@7={lx_at7}／holdout={ho_l2}／leak={leaks}"
        f"／四旗默认关={all(v is False for v in defaults.values())}",
        "",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "advice": advice,
        "lx_at7": lx_at7,
        "lx_l2": lx_l2,
        "holdout_l2": ho_l2,
        "total_l2": lx_l2 + ho_l2,
        "leaks": leaks,
        "flag_defaults": defaults,
        "flag_envs": list(FLAG_ENVS),
        "smoke": smoke,
        "rows": rows,
        "wall_s": wall,
        "baseline_ref": {
            "main_before": "7c3d24e",
            "expected_at7": 12,
            "expected_holdout_l2": 29,
            "expected_leak": 0,
        },
    }
    args.out.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {args.out}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
