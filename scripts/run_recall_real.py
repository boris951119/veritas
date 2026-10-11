#!/usr/bin/env python3
"""真实语料选料召回抽检。

默认读桌面全量库 ~/Desktop/veritas-testcases/eval-corpus；
可用 VERITAS_EVAL_CORPUS 或 --corpus 覆盖。仓库 B4 摘要包信源太少，
选料阈值下几乎不会收窄，只适合冒烟。

用法：
  .venv/bin/python scripts/run_recall_real.py
  .venv/bin/python scripts/run_recall_real.py --company 南山铝业
  .venv/bin/python scripts/run_recall_real.py --force-reindex
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.recall_real import default_corpus_root, render_report, run_real_recall


def main() -> int:
    ap = argparse.ArgumentParser(description="真实语料选料召回抽检")
    ap.add_argument("--corpus", type=Path, default=None,
                    help="语料根目录（默认桌面全量库或 VERITAS_EVAL_CORPUS）")
    ap.add_argument("--company", action="append", default=None,
                    help="只跑指定公司，可重复")
    ap.add_argument("--force-reindex", action="store_true")
    ap.add_argument("--max-sources", type=int, default=50)
    ap.add_argument("--out", type=Path,
                    default=_ROOT / "eval" / "recall_real_report.md")
    ap.add_argument("--json", type=Path,
                    default=_ROOT / "eval" / "recall_real_report.json")
    args = ap.parse_args()

    corpus = args.corpus or default_corpus_root()
    if not corpus.is_dir():
        print(f"语料目录不存在: {corpus}", file=sys.stderr)
        return 2

    print(f"语料: {corpus}")
    summary = run_real_recall(
        corpus,
        force_reindex=args.force_reindex,
        companies=args.company,
        max_sources=args.max_sources,
    )
    md = render_report(summary)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    # JSON 去掉超长 selected 也可；完整保留便于复盘
    args.json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)
    print(f"\n已写入 {args.out} 与 {args.json}")
    # 有可打分题且通过率 < 80% 时非零退出，方便 CI/手跑警觉
    if summary["n_scored"] and summary["pass_rate"] < 0.8:
        return 1
    if summary["n_scored"] == 0:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
