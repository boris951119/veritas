"""权重／可信度 ±20% 扰动探针（C-25 件②）：零模型、只读既有产物。

对 dossier 的 source.credibility 与 evidence.weight 各乘 0.8／1.0／1.2，
recompute_all 后报：band 翻转条数、冲突机械 winner 翻转对数、五项客观分是否变。
读数落 /tmp/s4runs/sens-<ts>/。

n_panel 口径（当场定死）：max(1, len(dossier.panel))——与工作台
app/server.py 重算入口一致；不用默认 1（agreement 恒吃地板，扰动读数失真）。
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from app.core.confidence import band_of, recompute_all
from app.core.evidence import Dossier

MULTIPLIERS = (0.8, 1.0, 1.2)
SCORE_KEYS = (
    "score_2_2_1", "score_2_4_1", "score_2_4_2",
    "score_2_5_1", "score_2_5_2",
)


def n_panel_of(dossier: Dossier) -> int:
    return max(1, len(dossier.panel or []))


def _clone(dossier: Dossier) -> Dossier:
    return Dossier.from_dict(copy.deepcopy(dossier.to_dict()))


def apply_multipliers(dossier: Dossier, *, cred: float, weight: float) -> None:
    for src in dossier.sources:
        src.credibility = min(1.0, max(0.0, float(src.credibility) * cred))
    for ev in dossier.evidences:
        ev.weight = float(ev.weight) * weight


def _bands(dossier: Dossier) -> dict[str, str]:
    out: dict[str, str] = {}
    for con in dossier.conclusions:
        if con.status != "majority":
            continue
        out[con.id] = band_of(float(con.confidence))
    return out


def _mech_winners(dossier: Dossier) -> dict[str, str]:
    """冲突对的机械 winner＝两侧 confidence 较高者；相等记 tie。"""
    by_id = {c.id: c for c in dossier.conclusions}
    out: dict[str, str] = {}
    for i, pair in enumerate(dossier.conflicts or []):
        if not isinstance(pair, dict):
            continue
        a = str(pair.get("a_id") or "")
        b = str(pair.get("b_id") or "")
        key = f"{i}:{a}:{b}"
        ca = by_id.get(a)
        cb = by_id.get(b)
        if ca is None or cb is None:
            out[key] = "missing"
            continue
        if ca.confidence > cb.confidence:
            out[key] = a
        elif cb.confidence > ca.confidence:
            out[key] = b
        else:
            out[key] = "tie"
    return out


def band_flips(before: dict[str, str], after: dict[str, str]) -> int:
    ids = set(before) | set(after)
    return sum(1 for i in ids if before.get(i) != after.get(i))


def winner_flips(before: dict[str, str], after: dict[str, str]) -> int:
    ids = set(before) | set(after)
    return sum(1 for i in ids if before.get(i) != after.get(i))


def run_one(base: Dossier, *, cred: float, weight: float) -> Dossier:
    d = _clone(base)
    apply_multipliers(d, cred=cred, weight=weight)
    recompute_all(d, n_panel=n_panel_of(d))
    return d


def objective_scores(
    evidence: Path | None,
    conclusions: Path | None,
    gold_evidence: Path | None,
    gold_conclusions: Path | None,
) -> dict | None:
    if not (evidence and conclusions and gold_evidence and gold_conclusions):
        return None
    from scripts.score_official import score_submission

    return score_submission(evidence, conclusions, gold_evidence, gold_conclusions)


def probe(
    report: Path,
    *,
    evidence: Path | None = None,
    conclusions: Path | None = None,
    gold_evidence: Path | None = None,
    gold_conclusions: Path | None = None,
) -> dict:
    base = Dossier.from_json(report)
    # 先以乘子 1.0 定基线面（与扰动函数同路径，避免"未扰动 ≠ 乘 1.0"）
    base_run = run_one(base, cred=1.0, weight=1.0)
    base_bands = _bands(base_run)
    base_winners = _mech_winners(base_run)
    base_scores = objective_scores(
        evidence, conclusions, gold_evidence, gold_conclusions)

    rows = []
    for m in MULTIPLIERS:
        # 信源 credibility 与证据 weight 各乘同一档
        d = run_one(base, cred=m, weight=m)
        bands = _bands(d)
        winners = _mech_winners(d)
        scores = objective_scores(
            evidence, conclusions, gold_evidence, gold_conclusions)
        score_changed = None
        if base_scores is not None and scores is not None:
            score_changed = any(
                base_scores.get(k) != scores.get(k) for k in SCORE_KEYS
            )
        rows.append({
            "multiplier": m,
            "band_flips": band_flips(base_bands, bands),
            "winner_flips": winner_flips(base_winners, winners),
            "objective_scores_changed": score_changed,
            "n_panel": n_panel_of(d),
            "bands": bands,
            "winners": winners,
        })
    return {
        "report": str(report),
        "n_panel_rule": "max(1, len(dossier.panel))",
        "n_panel": n_panel_of(base),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="权重／可信度扰动敏感性（零 LLM）")
    parser.add_argument("--report", required=True, help="report.json 路径")
    parser.add_argument("--evidence", default=None)
    parser.add_argument("--conclusions", default=None)
    parser.add_argument("--gold-evidence", default=None)
    parser.add_argument("--gold-conclusions", default=None)
    parser.add_argument(
        "--out-dir", default=None,
        help="默认 /tmp/s4runs/sens-<ts>/",
    )
    args = parser.parse_args(argv)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else Path(f"/tmp/s4runs/sens-{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = probe(
        Path(args.report),
        evidence=Path(args.evidence) if args.evidence else None,
        conclusions=Path(args.conclusions) if args.conclusions else None,
        gold_evidence=Path(args.gold_evidence) if args.gold_evidence else None,
        gold_conclusions=Path(args.gold_conclusions) if args.gold_conclusions else None,
    )
    out_path = out_dir / "sensitivity.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # 人类可读摘要
    lines = [
        f"report={result['report']}",
        f"n_panel={result['n_panel']}（规则={result['n_panel_rule']}）",
    ]
    for row in result["rows"]:
        ch = row["objective_scores_changed"]
        ch_s = "未量" if ch is None else ("变" if ch else "不变")
        lines.append(
            f"×{row['multiplier']}: band_flips={row['band_flips']} "
            f"winner_flips={row['winner_flips']} 五项客观分={ch_s}"
        )
    summary = "\n".join(lines) + "\n"
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")
    print(summary, end="")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
