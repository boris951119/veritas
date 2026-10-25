#!/usr/bin/env python3
"""C-24／#79：markdown 表格列数机械核（入库脚本）。

口径（与 docs/dev-protocol.md §5 纪律一致）：
- 按 (?<!\\\\)\\| 切列（转义 \\| 当内容，不算分隔符）
- 跳过围栏代码块（``` … ```）里的假表
- 连续以 | 开头（允许前导空白）的行合成一张表；表内列数不等 ⇒ 报错

读数口径：唯一不变式是 mismatched==0；files／with_tables／tables 都是当场读数、随文档树漂移。
当场附报（随文档树漂移，非不变式；默认作用域 docs/＋仓库根层 *.md）：files=25／with_tables=21／tables=107／mismatched=0。

用法：
    .venv/bin/python scripts/check_markdown_tables.py
    .venv/bin/python scripts/check_markdown_tables.py docs/ README.md
    .venv/bin/python scripts/check_markdown_tables.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_COL_SPLIT = re.compile(r"(?<!\\)\|")
_FENCE = re.compile(r"^(`{3,})")


def _n_cols(line: str) -> int:
    parts = _COL_SPLIT.split(line.rstrip("\n"))
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return len(parts)


def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def iter_md_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".md":
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.rglob("*.md")))
    out: list[Path] = []
    seen: set[Path] = set()
    for f in files:
        try:
            r = f.resolve()
        except OSError:
            continue
        if r in seen:
            continue
        seen.add(r)
        out.append(f)
    return out


def scan_file(path: Path) -> tuple[list[dict], int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    problems: list[dict] = []
    in_fence = False
    fence_marker = ""
    i = 0
    n_tables = 0
    while i < len(lines):
        line = lines[i]
        if not in_fence:
            fm = _FENCE.match(line.lstrip())
            if fm:
                in_fence = True
                fence_marker = fm.group(1)
                i += 1
                continue
        else:
            if fence_marker and line.lstrip().startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            i += 1
            continue
        if not _is_table_row(line):
            i += 1
            continue
        start = i
        rows: list[tuple[int, int]] = []
        while i < len(lines) and _is_table_row(lines[i]):
            if _FENCE.match(lines[i].lstrip()):
                break
            rows.append((i + 1, _n_cols(lines[i])))
            i += 1
        if len(rows) < 2:
            continue
        n_tables += 1
        counts = {c for _, c in rows}
        if len(counts) > 1:
            problems.append({
                "file": str(path),
                "start_line": start + 1,
                "end_line": rows[-1][0],
                "col_counts": sorted(counts),
                "row_summaries": [
                    {"line": ln, "n_cols": nc} for ln, nc in rows
                ],
            })
    return problems, n_tables


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="markdown 表格列数机械核（转义 \\| 当内容；跳过围栏假表）"
    )
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="文件或目录（默认＝docs/＋仓库根层 *.md）",
    )
    ap.add_argument("--json", action="store_true", help="机器可读摘要")
    args = ap.parse_args(argv)

    if args.paths:
        targets = list(args.paths)
    else:
        targets = [ROOT / "docs", *sorted(ROOT.glob("*.md"))]

    files = iter_md_files(targets)
    all_problems: list[dict] = []
    n_tables = 0
    n_with_tables = 0
    for f in files:
        probs, nt = scan_file(f)
        n_tables += nt
        if nt:
            n_with_tables += 1
        all_problems.extend(probs)

    summary = {
        "files": len(files),
        "files_with_tables": n_with_tables,
        "tables": n_tables,
        "mismatched": len(all_problems),
        "problems": all_problems,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"files={summary['files']} with_tables={summary['files_with_tables']} "
            f"tables={summary['tables']} mismatched={summary['mismatched']}"
        )
        for p in all_problems:
            print(
                f"  MISMATCH {p['file']}:{p['start_line']}-{p['end_line']} "
                f"col_counts={p['col_counts']}"
            )
    return 1 if all_problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
