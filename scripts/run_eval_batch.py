# -*- coding: utf-8 -*-
"""B4 跑批:七家公司真实模型研判 → 30 问 ground truth 对账 → 指标报告。

指标:
- M1 证据链命中率:ground truth 段落是否被某条结论的证据引用;
- M2 数字覆盖率:ground truth 数值是否出现在某条结论 statement 中;
- M3 冲突检出:对撞台账对同公司跨年/更正口径的捕获数;
- 汇总 → eval/report.md。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.pipeline import RunDeps, RunSpec, run_case

QUESTIONS = REPO / "eval" / "questions.jsonl"
CORPUS = Path("/Users/liuboyu/Desktop/veritas-testcases/eval-corpus")
REPORT = REPO / "eval" / "report.md"


def main() -> int:
    questions = [json.loads(l) for l in
                 QUESTIONS.read_text(encoding="utf-8").splitlines()]
    by_c: dict[str, list[dict]] = {}
    for q in questions:
        by_c.setdefault(q["company"], []).append(q)

    report: list[str] = ["# B4 评测报告(真实模型跑批)", "",
                         f"生成时间:{time.strftime('%Y-%m-%d %H:%M')}",
                         f"问题数:{len(questions)}", ""]
    totals = {"m1": 0, "m2": 0, "n": 0, "conflicts": 0, "rejected": 0}

    for company, qs in by_c.items():
        case_dir = CORPUS / company
        out_dir = case_dir / "out_eval"
        (case_dir / "manifest.yaml").write_text(
            f"question: {company}2024-2025年度经营成果与财务状况研判"
            "(营收、盈利、分红、股东回报与风险)\\n"
            + "".join(f'sources:\\n  - file: pdf/{p.name}\\n    type: report\\n'
                      for p in sorted((case_dir / "pdf").glob("*.pdf"))),
            encoding="utf-8")
        print(f"== {company} 开始 {time.strftime('%H:%M')}", flush=True)
        try:
            result = run_case(RunSpec(case_dir=case_dir, out_dir=out_dir))
        except Exception as exc:
            report += [f"## {company}", "", f"跑批失败:{type(exc).__name__}: {exc}", ""]
            print(f"  FAIL {exc}")
            continue
        d = result.dossier
        cited_segs = {sid for ev in d.evidences for sid in ev.segment_ids}
        all_statements = " ".join(c.statement for c in d.conclusions)
        m1 = m2 = 0
        for q in qs:
            if q["ground_seg"] in cited_segs:
                m1 += 1
            if q["value"] in all_statements:
                m2 += 1
        totals["m1"] += m1
        totals["m2"] += m2
        totals["n"] += len(qs)
        totals["conflicts"] += len(d.conflicts)
        totals["rejected"] += len(d.rejected)
        report += [
            f"## {company}", "",
            f"- 问题 {len(qs)};结论 {len(d.conclusions)};证据 {len(d.evidences)};"
            f"冲突 {len(d.conflicts)};打回 {len(d.rejected)};",
            f"- M1 证据链命中率:{m1}/{len(qs)};",
            f"- M2 数字覆盖率:{m2}/{len(qs)};",
            "",
        ]
        print(f"  done M1={m1}/{len(qs)} M2={m2}/{len(qs)}")

    hit1 = totals["m1"] / max(1, totals["n"])
    hit2 = totals["m2"] / max(1, totals["n"])
    report += ["## 总计", "",
               f"- M1 证据链命中率(ground 段被结论引用):**{hit1:.0%}**"
               f"({totals['m1']}/{totals['n']})",
               f"- M2 数字覆盖率(数值进结论):**{hit2:.0%}**"
               f"({totals['m2']}/{totals['n']})",
               f"- 冲突对检出:{totals['conflicts']};引文打回:{totals['rejected']}"]
    REPORT.write_text("\\n".join(report) + "\\n", encoding="utf-8")
    print("\n报告:", REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
