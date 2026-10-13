"""存量研判产物的质量基线测量：范围越权、闸命中情况、计数闸免检率、子问台账形态。

为什么需要它：讲"某个改动能提升多少"必须先有改前的数。2026-10-13 那次是靠一次性
内联脚本量出来的，**没存盘就不可复放**——本脚本把同一套口径钉成一条命令，
零 LLM、零网络、零写入。

它测四件事：

1. **越权/缺失断言**：结论里出现全称量词（全部/所有/无一/均…）或"不存在类"表述
   （未发现/未检索到/无相关…）的条数——这两类正是「没找到 ≠ 不存在」的幻觉高危区。
2. **现有闸的拦截情况**：上述断言里，有多少已被 `audit_all` 的某道闸亮过灯，
   有多少**全绿静默放行**（后者才是新增闸的真实显影量，别拿前者吹提升）。
3. **计数闸免检率**：`audit_counting` 只核显式「计数:M/N」格式，不写该格式的结论
   压根不进场。免检率高 ⇒ 它报的"零违规"信息含量低。
4. **完整性判据台账形态**：`split_subquestions` 按问号/分号机械切；切不出多条时由
   `obligations()` 走主题组展开或整题兜底（2026-10-13 修复——此前直接返回空 ⇒
   该产物没有任何完整性判据，开放题早退隐形）。来源偏弱时 `ledger_limitation()`
   必须留下声明，本脚本把它计入「弱判据产物数」。

用法：
    .venv/bin/python scripts/measure_baseline.py                # 全部产物
    .venv/bin/python scripts/measure_baseline.py --json         # 机器可读，供 diff
    .venv/bin/python scripts/measure_baseline.py cases/bi-delivery-risk/out
    .venv/bin/python scripts/measure_baseline.py --show-passed 5 # 列全绿放行样本

口径说明（重要，别让数字被误读）：
- 「结论」= `status != "merged"` 的结论，与 `audit_counting` 的遍历口径一致。
- 「引用覆盖」= 该结论全部证据所引段落数 / 案卷段落总数（含未纳入研判的段落）。
- 一条结论可能同时命中全称与缺失两类，合计数按去重后的并集算。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.audit import audit_all  # noqa: E402
from app.core.coverage_gap import (  # noqa: E402
    ledger_limitation, split_subquestions, subquestion_status)
from app.core.evidence import Dossier  # noqa: E402
from app.core.numeric_check import _COUNT_RE  # noqa: E402

# 全称量词：结论声称覆盖了某个集合的全部成员
_UNIVERSAL_RE = re.compile(r"全部|所有|无一|每个|每一|没有任何|均(?:显示|表明|存在|为|未)")
# 「不存在类」断言：把「没找到」说成「不存在」
_ABSENCE_RE = re.compile(
    r"未检索到|没有找到|未发现|无相关|不存在|未见|未提及|没有.{0,3}(证据|信源|记载)")
# 欠覆盖判定阈值：全称断言的引用覆盖低于此值即视为可疑
_LOW_COVERAGE = 0.25


def _artifacts(items: list[str]) -> list[Path]:
    """默认扫 cases/<案例>/out*/report.json；给了路径就按路径来（不静默跳过）。"""
    if items:
        out: list[Path] = []
        for raw in items:
            p = Path(raw)
            if not p.is_absolute():
                p = ROOT / p
            if p.is_dir():
                f = p / "report.json"
                if f.is_file():
                    out.append(f)
                else:
                    out.extend(sorted(p.glob("*/report.json")))
            elif p.is_file():
                out.append(p)
            else:
                raise SystemExit(f"产物路径不存在：{raw}")
        return out
    out = []
    for case_dir in sorted((ROOT / "cases").glob("*")):
        if not case_dir.is_dir():
            continue
        for out_dir in sorted(case_dir.glob("out*")):
            f = out_dir / "report.json"
            if f.is_file():
                out.append(f)
    return out


def measure(path: Path) -> dict:
    """一份 report.json → 一行基线指标。解析失败向上抛，由调用方显式记失败。"""
    dossier = Dossier.from_json(path)
    cons = [c for c in dossier.conclusions if c.status != "merged"]
    n_segments = sum(len(src.segments) for src in dossier.sources)
    flagged_ids = {f.get("conclusion_id") for f in audit_all(dossier)
                   if f.get("conclusion_id")}
    ledger = subquestion_status(dossier)

    label = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    rows = {"artifact": label, "n_conclusions": len(cons),
            "n_segments": n_segments}
    universal = absence = counted = 0
    over_claim_low_cov = 0
    overclaim_ids: set[str] = set()
    passed: list[dict] = []
    for c in cons:
        st = c.statement or ""
        texts = [st] + [(ev.note or "") for ev in dossier.evidences_of(c.id)]
        is_univ = bool(_UNIVERSAL_RE.search(st))
        is_abs = bool(_ABSENCE_RE.search(st))
        if is_univ:
            universal += 1
        if is_abs:
            absence += 1
        if any(_COUNT_RE.search(t or "") for t in texts):
            counted += 1
        share = 0.0
        if n_segments:
            cited = {sid for ev in dossier.evidences_of(c.id) for sid in ev.segment_ids}
            share = len([s for s in cited if dossier.segment(s) is not None]) / n_segments
        if is_univ and share < _LOW_COVERAGE:
            over_claim_low_cov += 1
        if is_univ or is_abs:
            overclaim_ids.add(c.id)
            if c.id not in flagged_ids:
                passed.append({"id": c.id, "share": round(share, 4),
                               "statement": st[:60]})
    rows.update({
        "n_universal": universal,
        "n_absence": absence,
        "n_overclaim": len(overclaim_ids),
        "n_overclaim_flagged": len(overclaim_ids & flagged_ids),
        "n_overclaim_passed": len(passed),
        "n_counting_in_scope": counted,
        "counting_exempt_rate": (1 - counted / len(cons)) if cons else 0.0,
        "n_universal_low_coverage": over_claim_low_cov,
        "n_subquestions_split": len(split_subquestions(dossier.question or "")),
        "n_obligations": len(ledger),
        "ledger_sources": sorted({str(s.get("source") or "") for s in ledger}),
        "ledger_weak": bool(ledger_limitation(ledger)),
        "passed_samples": passed,
    })
    return rows


def _print(rows: list[dict], failed: list[tuple[str, str]], show_passed: int) -> None:
    ok = [r for r in rows if r.get("n_conclusions")]
    tot = {k: sum(r[k] for r in ok) for k in
           ("n_conclusions", "n_universal", "n_absence", "n_overclaim",
            "n_overclaim_flagged", "n_overclaim_passed", "n_counting_in_scope",
            "n_universal_low_coverage", "n_obligations")}
    n_cons = tot["n_conclusions"] or 1
    print(f"产物：{len(rows)} 份（有结论的 {len(ok)} 份）")
    if failed:
        print(f"解析失败：{len(failed)} 份 —— " +
              "；".join(f"{p}: {e[:40]}" for p, e in failed[:3]))
    print(f"\n结论合计                     {tot['n_conclusions']:5d}")
    print(f"  全称量词断言               {tot['n_universal']:5d}  "
          f"({tot['n_universal']/n_cons:.1%})")
    print(f"    其中引用覆盖 <{_LOW_COVERAGE:.0%}   {tot['n_universal_low_coverage']:5d}  "
          f"← 声称范围却几乎没引材料")
    print(f"  「不存在」类断言           {tot['n_absence']:5d}  ({tot['n_absence']/n_cons:.1%})")
    print(f"  越权/缺失合计（按结论去重）  {tot['n_overclaim']:5d}")
    print(f"    已被现有闸亮灯           {tot['n_overclaim_flagged']:5d}")
    print(f"    现有闸全绿放行           {tot['n_overclaim_passed']:5d}  "
          f"← 新增范围闸的真实显影量")
    print(f"\n计数闸：进场 {tot['n_counting_in_scope']} 条 / 免检 "
          f"{tot['n_conclusions'] - tot['n_counting_in_scope']} 条"
          f" ⇒ 免检率 {(1 - tot['n_counting_in_scope']/n_cons):.1%}")
    no_ledger = [r for r in ok if r["n_obligations"] == 0]
    weak = [r for r in ok if r.get("ledger_weak")]
    print(f"\n完整性判据台账：{len(ok)} 份产物中 {len(ok) - len(no_ledger)} 份有判据 / "
          f"{len(no_ledger)} 份仍为空")
    print(f"  其中来源偏弱（主题组展开或整题兜底，须带局限声明）：{len(weak)} 份")
    for r in no_ledger[:6]:
        print(f"   空台账 {r['artifact'][:52]:52s} 切出 {r['n_subquestions_split']} 项")
    for r in weak[:6]:
        print(f"   弱判据 {r['artifact'][:52]:52s} "
              f"判据 {r['n_obligations']} 条·来源 {'/'.join(r['ledger_sources'])}")
    if show_passed:
        print(f"\n全绿放行样本（前 {show_passed} 条）：")
        for r in ok:
            for s in r["passed_samples"][:2]:
                parts = Path(r["artifact"]).parts
                tag = parts[1] if len(parts) > 2 else parts[0]
                print(f"   [{tag[:22]}] {s['id']} "
                      f"覆盖{s['share']:6.1%}「{s['statement']}」")
                show_passed -= 1
                if show_passed <= 0:
                    return


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("items", nargs="*", help="产物目录或 report.json（缺省扫全部）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--show-passed", type=int, default=0,
                    help="列出 N 条全绿放行的越权断言样本")
    args = ap.parse_args()

    rows: list[dict] = []
    failed: list[tuple[str, str]] = []
    for p in _artifacts(args.items):
        try:
            rows.append(measure(p))
        except Exception as exc:  # 不静默跳过：失败也是基线的一部分
            failed.append((str(p.relative_to(ROOT)), type(exc).__name__))
    if args.json:
        print(json.dumps({"artifacts": rows, "failed": failed},
                         ensure_ascii=False, indent=2))
    else:
        _print(rows, failed, args.show_passed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
