"""warrant_theme 取词闸复放（零模型）。

正例：官方六案金标自身的支撑／冲突事实，结论文本对同一条 quote+fact_des。
负例：random.seed(7)，从六案金标事实里抽 2 条，同案丢弃，
用 A 的结论文本配 B 的那一条 quote+fact_des，抽满 500 对。

打印四行：正例数、误伤数、负例数、捕获数。
误伤率应 ≤5%，捕获率应 ≥40%（改前词表的捕获必须是 0）。
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

ROOT = Path(os.environ.get(
    "OFFICIAL_CASES",
    str(Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"),
))


def _load_cases(root: Path) -> list[dict]:
    cases = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        path = folder / "conclusions.json"
        if not path.is_file():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        facts = []
        for row in rows:
            for side in ("supporting_facts", "conflicting_facts"):
                for fact in row.get(side) or []:
                    if not isinstance(fact, dict):
                        continue
                    facts.append({
                        "conclusion": str(row.get("conclusion") or ""),
                        "evidence": (
                            str(fact.get("quote") or "")
                            + str(fact.get("fact_des") or "")
                        ),
                    })
        cases.append({"name": folder.name, "facts": facts})
    return cases


def _disjoint(claim: str, evidence: str) -> bool:
    from app.core.evidence import (
        Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
    )
    from app.core.warrant_check import audit_warrant_theme

    dossier = Dossier(question="probe")
    src = Source.create("p", SourceType.OTHER, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text=evidence))
    dossier.add_source(src)
    dossier.conclusions.append(Conclusion.create(claim, author="p", id="CON-1"))
    dossier.add_evidence(EvidenceNode.create(
        "CON-1", evidence[:80], ["SRC1#s1"], id="EV-1"))
    return any(f.get("kind") == "warrant_theme" for f in audit_warrant_theme(dossier))


def measure(root: Path | None = None) -> dict:
    root = root or ROOT
    if not root.is_dir():
        raise SystemExit(f"找不到官方样例集：{root}")
    cases = _load_cases(root)
    positives = [fact for case in cases for fact in case["facts"]]
    false_hits = sum(
        1 for fact in positives if _disjoint(fact["conclusion"], fact["evidence"])
    )
    pool = [
        (case["name"], fact["conclusion"], fact["evidence"])
        for case in cases
        for fact in case["facts"]
    ]
    rng = random.Random(7)
    negatives = []
    guard = 0
    while len(negatives) < 500 and guard < 20000:
        guard += 1
        a, b = rng.sample(pool, 2)
        if a[0] == b[0]:
            continue
        negatives.append((a[1], b[2]))
    if len(negatives) < 500:
        raise SystemExit(f"跨案乱配只抽到 {len(negatives)} 对")
    caught = sum(1 for claim, evidence in negatives if _disjoint(claim, evidence))
    return {
        "n_positive": len(positives),
        "n_false": false_hits,
        "n_negative": len(negatives),
        "n_caught": caught,
    }


def main() -> None:
    stats = measure()
    print(f"正例数 {stats['n_positive']}")
    print(f"误伤数 {stats['n_false']}")
    print(f"负例数 {stats['n_negative']}")
    print(f"捕获数 {stats['n_caught']}")


if __name__ == "__main__":
    main()
