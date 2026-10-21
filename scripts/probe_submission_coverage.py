# -*- coding: utf-8 -*-
"""C-33：提交面覆盖探针——支撑／冲突行数、0 行题、冲突跳过数。零 LLM、只读。

读一份 export_official 产物目录（须含 conclusions.json；字段说明.md 可选，
有则解析冲突侧跳过数）。不带目录参数必须非零退出并提示显式传参（#68）。

用法：
    .venv/bin/python scripts/probe_submission_coverage.py --dir /path/to/export
    .venv/bin/python scripts/probe_submission_coverage.py --help
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SKIP_RE = re.compile(
    r"冲突侧跳过：tie／未分胜负\s+(\d+)\s+对；段落取不到\s+(\d+)\s+对"
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="提交面覆盖探针：逐题支撑／冲突行数与跳过统计（零 LLM、只读）",
    )
    p.add_argument(
        "--dir",
        dest="out_dir",
        metavar="DIR",
        required=True,
        help="export_official 产物目录（须含 conclusions.json）",
    )
    return p.parse_args(argv)


def _load_conclusions(out_dir: Path) -> list[dict]:
    path = out_dir / "conclusions.json"
    if not path.is_file():
        sys.exit(f"找不到 conclusions.json：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        sys.exit(f"conclusions.json 不是数组：{path}")
    return data


def _parse_skips(out_dir: Path) -> tuple[int | None, int | None]:
    notes = out_dir / "字段说明.md"
    if not notes.is_file():
        return None, None
    text = notes.read_text(encoding="utf-8")
    m = _SKIP_RE.search(text)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    out_dir = Path(args.out_dir)
    if not out_dir.is_dir():
        print(f"目录不存在：{out_dir}", file=sys.stderr)
        return 2
    rows = _load_conclusions(out_dir)
    zero_support = 0
    zero_conflict = 0
    zero_both = 0
    print(f"{'question_id':<24}{'支撑':>6}{'冲突':>6}")
    for row in rows:
        qid = str(row.get("question_id") or "")
        n_sup = len(row.get("supporting_facts") or [])
        n_conf = len(row.get("conflicting_facts") or [])
        if n_sup == 0:
            zero_support += 1
        if n_conf == 0:
            zero_conflict += 1
        if n_sup == 0 and n_conf == 0:
            zero_both += 1
        print(f"{qid:<24}{n_sup:>6}{n_conf:>6}")
    print("---")
    print(f"题数={len(rows)}  支撑 0 行题={zero_support}  "
          f"冲突 0 行题={zero_conflict}  两侧皆 0={zero_both}")
    skip_tie, skip_noloc = _parse_skips(out_dir)
    if skip_tie is None:
        print("冲突侧跳过：字段说明.md 无跳过行（未导出或旧产物）")
    else:
        print(f"冲突侧跳过：tie／未分胜负 {skip_tie} 对；"
              f"段落取不到 {skip_noloc} 对")
    return 0


if __name__ == "__main__":
    # 不带 --dir 时 argparse 会以非零退出并提示；显式拦一下更清楚
    if len(sys.argv) == 1:
        print("必须显式传 --dir <export 产物目录>（#68：禁止默认扫盘）",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main())
