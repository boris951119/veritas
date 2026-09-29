"""A/B 协议指标提取：对 6 份 out_ab_* 产物按预注册口径出表。

用法：.venv/bin/python scripts/ab_metrics.py [case=bi-delivery-risk]
指标定义见 docs/ab-protocol.md 第 3 节；警示为派生视图，直接对
report.json 即时重算（app.core.audit.audit_all）。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.audit import audit_all
from app.core.evidence import Dossier

MAIN_METRIC = {
    # skill -> (配对闸 kind, 主指标口径)
    "calc_discipline": ("calc", "flags"),
    "number_provenance": ("provenance", "flags"),
    "counting_discipline": ("counting", "flags"),
    "hedged_claim": ("hedge", "flags"),
    "level_tone": ("level_tone", "flags"),
    "table_citation": ("rejected", "rate"),  # 引文打回率 = rejected/总证据
}


def run_metrics(case: str) -> dict:
    root = Path("cases") / case
    groups: dict[str, list[dict]] = {"a": [], "b": []}
    for g in ("a", "b"):
        for i in (1, 2, 3):
            out = root / f"out_ab_{g}_{i}"
            report = out / "report.json"
            if not report.is_file():
                groups[g].append({"run": f"{g}{i}", "missing": True})
                continue
            d = Dossier.from_json(report)
            flags = Counter(f["kind"] for f in audit_all(d))
            n_ev = len(d.evidences)
            majors = sum(1 for c in d.conclusions if c.status == "majority")
            groups[g].append({
                "run": f"{g}{i}",
                "n_conclusions": len(d.conclusions),
                "n_majority": majors,
                "n_conflicts": len(d.conflicts),
                "n_evidence": n_ev,
                "n_rejected": len(d.rejected),
                "reject_rate": round(len(d.rejected) / n_ev, 3) if n_ev else 0.0,
                "flags": dict(flags),
                "calc_red": flags.get("calc", 0),
                "injection": _injection_of(out),
            })
    return groups


def _injection_of(out: Path) -> bool | None:
    """从 chain.jsonl 读 skills_triggered.injection（验证开关确实生效）。"""
    chain = out / "chain.jsonl"
    if not chain.is_file():
        return None
    for line in chain.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("event") == "skills_triggered":
            return bool(rec.get("payload", {}).get("injection"))
    return None


def _median(xs: list) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def summarize(groups: dict) -> dict:
    out = {}
    for skill, (kind, metric) in MAIN_METRIC.items():
        per = {}
        for g in ("a", "b"):
            vals = []
            for r in groups[g]:
                if r.get("missing"):
                    continue
                vals.append(r["reject_rate"] if metric == "rate"
                            else r["flags"].get(kind, 0))
            per[g] = vals
        med_a, med_b = _median(per["a"]), _median(per["b"])
        out[skill] = {
            "metric": metric, "A_runs": per["a"], "B_runs": per["b"],
            "median_A": med_a, "median_B": med_b,
            "headroom_zero": med_a == 0,
            "verdict": ("无功效可测(本案例)" if med_a == 0 and med_b <= med_a
                        else "有效" if med_b < med_a else "无效"),
        }
    return out


if __name__ == "__main__":
    case = sys.argv[1] if len(sys.argv) > 1 else "bi-delivery-risk"
    groups = run_metrics(case)
    print(json.dumps({"runs": groups, "verdicts": summarize(groups)},
                     ensure_ascii=False, indent=2))
