# -*- coding: utf-8 -*-
"""B4 跑批：真实模型研判 → ground truth 对账 → 指标报告。

指标:
- M1 证据链命中：ground 段被引用，或标注数值出现在任一证据引文中
  （段落 ID 漂移时仍可对账）；
- M2 数字覆盖：标注数值出现在结论文案或证据引文中；
- 默认按公司一跑（议题合并该公司全部问法）；--per-question 逐问重跑。

用法:
  .venv/bin/python scripts/run_eval_batch.py
  .venv/bin/python scripts/run_eval_batch.py --company 南山铝业
  .venv/bin/python scripts/run_eval_batch.py --per-question --company 南山铝业
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.pipeline import RunDeps, RunSpec, run_case

QUESTIONS = REPO / "eval" / "questions.jsonl"
# B4 标注的 ground_seg（SRC1#s2…）对齐仓库启动包摘要，不是桌面全量公告
DEFAULT_CORPUS = REPO / "eval" / "corpus"
FULL_CORPUS = Path("/Users/liuboyu/Desktop/veritas-testcases/eval-corpus")
REPORT = REPO / "eval" / "report.md"


def _corpus_root(explicit: str = "") -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_dir():
            raise SystemExit(f"语料目录不存在: {p}")
        return p
    if DEFAULT_CORPUS.is_dir() and any(DEFAULT_CORPUS.iterdir()):
        return DEFAULT_CORPUS
    if FULL_CORPUS.is_dir():
        return FULL_CORPUS
    raise SystemExit("找不到评测语料目录（eval/corpus 或桌面 eval-corpus）")


def _score_question(d, q: dict) -> tuple[bool, bool]:
    cited = {sid for ev in d.evidences for sid in ev.segment_ids}
    quotes = " ".join(ev.quote or "" for ev in d.evidences)
    statements = " ".join(c.statement or "" for c in d.conclusions)
    val = str(q.get("value") or "")
    m1 = q.get("ground_seg") in cited or (bool(val) and val in quotes)
    m2 = (bool(val) and val in statements) or (bool(val) and val in quotes)
    return m1, m2


def _write_manifest(case_dir: Path, question: str, pdfs: list[Path],
                    htmls: list[Path]) -> None:
    src_lines: list[str] = []
    for p in pdfs:
        rel = p.relative_to(case_dir).as_posix() if p.is_relative_to(case_dir) else p.name
        src_lines.append(f"  - file: {rel}\n    type: report\n")
    for p in htmls:
        rel = p.relative_to(case_dir).as_posix() if p.is_relative_to(case_dir) else p.name
        src_lines.append(f"  - file: {rel}\n    type: report\n")
    (case_dir / "manifest.yaml").write_text(
        f"question: {question}\nsources:\n" + "".join(src_lines),
        encoding="utf-8",
    )


def _company_question(company: str, qs: list[dict]) -> str:
    """合并议题：用该公司标注问法拼成总问（评测脚本已开 FORCE_JUDGMENT）。"""
    parts = []
    for q in qs:
        text = str(q.get("question") or "").strip().replace("\n", "")
        if text:
            parts.append(text)
    if not parts:
        return f"{company}2024年与2025年营业收入和归母净利润同比变化如何？"
    # 控制长度，避免提示词爆炸
    joined = "；".join(parts[:5])
    return joined[:400]


def _is_real_pdf(path: Path) -> bool:
    try:
        return path.read_bytes()[:5] == b"%PDF-"
    except OSError:
        return False


def _list_sources(case_dir: Path) -> tuple[list[Path], list[Path]]:
    pdf_dir = case_dir / "pdf"
    if pdf_dir.is_dir():
        pdfs = sorted(pdf_dir.glob("*.pdf"))
    else:
        pdfs = sorted(case_dir.glob("*.pdf"))
    # 跳过下载失败落成的 HTML 伪 PDF（头为 <!DOC…）
    pdfs = [p for p in pdfs if _is_real_pdf(p)]
    htmls = sorted(case_dir.glob("*.htm*"))
    return pdfs, htmls


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", default="", help="只跑一家公司")
    ap.add_argument("--per-question", action="store_true",
                    help="逐问重跑（更准、更耗额度）")
    ap.add_argument("--corpus", default="",
                    help="语料根目录（默认 eval/corpus 启动包；全量用桌面路径）")
    args = ap.parse_args()

    corpus = _corpus_root(args.corpus)
    # 评测挖空问法常触发表述澄清闸；强制走完研判，否则 M1/M2 恒为 0
    os.environ["VERITAS_FORCE_JUDGMENT"] = "1"
    questions = [json.loads(l) for l in
                 QUESTIONS.read_text(encoding="utf-8").splitlines()]
    by_c: dict[str, list[dict]] = {}
    for q in questions:
        by_c.setdefault(q["company"], []).append(q)
    if args.company:
        if args.company not in by_c:
            raise SystemExit(f"未知公司: {args.company}")
        by_c = {args.company: by_c[args.company]}

    report: list[str] = [
        "# B4 评测报告（真实模型跑批）", "",
        f"生成时间: {time.strftime('%Y-%m-%d %H:%M')}",
        f"问题数: {sum(len(v) for v in by_c.values())}",
        f"模式: {'逐问' if args.per_question else '按公司合并议题'}",
        f"语料: {corpus}",
        "",
    ]
    totals = {"m1": 0, "m2": 0, "n": 0, "conflicts": 0, "rejected": 0}

    for company, qs in by_c.items():
        case_dir = corpus / company
        if not case_dir.is_dir():
            report += [f"## {company}", "", "语料目录缺失", ""]
            continue
        pdfs, htmls = _list_sources(case_dir)
        print(f"== {company} 开始 {time.strftime('%H:%M')}", flush=True)

        if args.per_question:
            m1 = m2 = 0
            n_con = n_ev = n_cfl = n_rej = 0
            for i, q in enumerate(qs, 1):
                out_dir = case_dir / f"out_eval_q{i}"
                _write_manifest(case_dir, q["question"], pdfs, htmls)
                try:
                    result = run_case(RunSpec(case_dir=case_dir, out_dir=out_dir))
                except Exception as exc:
                    print(f"  Q{i} FAIL {exc}")
                    continue
                d = result.dossier
                hit1, hit2 = _score_question(d, q)
                m1 += int(hit1)
                m2 += int(hit2)
                n_con += len(d.conclusions)
                n_ev += len(d.evidences)
                n_cfl += len(d.conflicts)
                n_rej += len(d.rejected)
                print(f"  Q{i} M1={hit1} M2={hit2}")
            totals["m1"] += m1
            totals["m2"] += m2
            totals["n"] += len(qs)
            totals["conflicts"] += n_cfl
            totals["rejected"] += n_rej
            report += [
                f"## {company}", "",
                f"- 问题 {len(qs)}；结论 {n_con}；证据 {n_ev}；"
                f"冲突 {n_cfl}；打回 {n_rej}",
                f"- M1 证据链命中率: {m1}/{len(qs)}",
                f"- M2 数字覆盖率: {m2}/{len(qs)}",
                "",
            ]
            continue

        out_dir = case_dir / "out_eval"
        _write_manifest(case_dir, _company_question(company, qs), pdfs, htmls)
        try:
            result = run_case(RunSpec(case_dir=case_dir, out_dir=out_dir))
        except Exception as exc:
            report += [f"## {company}", "",
                       f"跑批失败: {type(exc).__name__}: {exc}", ""]
            print(f"  FAIL {exc}")
            continue
        d = result.dossier
        m1 = m2 = 0
        for q in qs:
            hit1, hit2 = _score_question(d, q)
            m1 += int(hit1)
            m2 += int(hit2)
        totals["m1"] += m1
        totals["m2"] += m2
        totals["n"] += len(qs)
        totals["conflicts"] += len(d.conflicts)
        totals["rejected"] += len(d.rejected)
        report += [
            f"## {company}", "",
            f"- 问题 {len(qs)}；结论 {len(d.conclusions)}；证据 {len(d.evidences)}；"
            f"冲突 {len(d.conflicts)}；打回 {len(d.rejected)}",
            f"- M1 证据链命中率: {m1}/{len(qs)}",
            f"- M2 数字覆盖率: {m2}/{len(qs)}",
            "",
        ]
        print(f"  done M1={m1}/{len(qs)} M2={m2}/{len(qs)}")

    hit1 = totals["m1"] / max(1, totals["n"])
    hit2 = totals["m2"] / max(1, totals["n"])
    report += [
        "## 总计", "",
        f"- M1 证据链命中率（ground 段被引用或数值进引文）: **{hit1:.0%}**"
        f"（{totals['m1']}/{totals['n']}）",
        f"- M2 数字覆盖率（数值进结论或引文）: **{hit2:.0%}**"
        f"（{totals['m2']}/{totals['n']}）",
        f"- 冲突对检出: {totals['conflicts']}；引文打回: {totals['rejected']}",
        "",
        "## 口径说明",
        "",
        "- M1/M2 相对标注集对账；段落 ID 漂移时可用「数值∈引文」兜底。",
        "- 合并议题模式省额度；要贴近单问表现请加 `--per-question`。",
    ]
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n报告:", REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
