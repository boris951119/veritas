#!/usr/bin/env python3
"""C-37：文档全限定 file:line 锚点体检（入库脚本）。

口径：
- 作用域＝docs/*.md ＋ 仓库根 *.md（软链 resolve 去重）
- 默认跳过围栏代码块；`--include-fenced` 把围栏内锚点也计入（两版总数都附报）
- 锚点＝带目录前缀的本地路径 + 行号：
  (app|tests|scripts|web|calibration|eval|docs)/….<ext>:<line>
  ext ∈ py|md|html|json|toml|yml|yaml|txt|css|js|sh|command|bat
- 目标文件不存在（含 docs/）⇒ 计 missing；唯一例外＝`docs/rea-study.md` 内对仓外 REA 文档的引用（否则现树永红）
- 同名歧义＝仅文件名（无目录）且 git ls-files 命中 >1 的 `name.ext:line`

不变式：missing==0 且 oob==0 时退出 0；否则非零。
四数都是当场读数，随文档树漂移。

用法：
    .venv/bin/python scripts/check_doc_anchors.py
    .venv/bin/python scripts/check_doc_anchors.py --json
    .venv/bin/python scripts/check_doc_anchors.py --include-fenced --json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_FENCE = re.compile(r"^(`{3,})")
_EXT = r"py|md|html|json|toml|yml|yaml|txt|css|js|sh|command|bat"
_FQ = re.compile(
    rf"(?<![A-Za-z0-9_/])((?:app|tests|scripts|web|calibration|eval|docs)/"
    rf"[A-Za-z0-9_./\-]+\.(?:{_EXT})):(\d+)\b"
)
_BASE = re.compile(rf"(?<![A-Za-z0-9_./])([A-Za-z0-9_\-]+\.(?:{_EXT})):(\d+)\b")
_PRODUCT_PREFIXES = ("app/", "tests/", "scripts/", "web/", "calibration/", "eval/")


def iter_md_files() -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for p in list((ROOT / "docs").glob("*.md")) + list(ROOT.glob("*.md")):
        try:
            r = p.resolve()
        except OSError:
            continue
        if r in seen:
            continue
        seen.add(r)
        files.append(p)
    return files


def _basename_index() -> dict[str, list[str]]:
    by: dict[str, list[str]] = defaultdict(list)
    try:
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=ROOT, text=True
        ).splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        tracked = []
    for f in tracked:
        by[Path(f).name].append(f)
    return by


def scan(*, include_fenced: bool = False) -> dict:
    total = missing = oob = ambig = 0
    problems: list[dict] = []
    by_base = _basename_index()

    for fp in iter_md_files():
        rel = str(fp.relative_to(ROOT)) if fp.is_relative_to(ROOT) else str(fp)
        try:
            lines = fp.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            problems.append({"file": rel, "error": str(e)})
            continue
        in_fence = False
        marker = ""
        for lineno, line in enumerate(lines, 1):
            if not in_fence:
                fm = _FENCE.match(line.lstrip())
                if fm:
                    in_fence = True
                    marker = fm.group(1)
                    if not include_fenced:
                        continue
                    # include-fenced: fall through and also scan fence-open line? skip opener
                    continue
            else:
                if line.lstrip().startswith(marker):
                    in_fence = False
                    marker = ""
                    continue
                if not include_fenced:
                    continue

            for path, ln_s in _FQ.findall(line):
                if "..." in path:
                    continue
                ln = int(ln_s)
                target = ROOT / path
                exists = target.is_file()
                # docs/ 不存在：一律计 missing（R-C37-4）。
                # 例外＝docs/rea-study.md 里对外部 REA 文档的引用
                # （该文件是竞品研读，目标不在本仓；若也计 missing 则现树永红）。
                if (
                    not exists
                    and path.startswith("docs/")
                    and rel == "docs/rea-study.md"
                ):
                    continue
                total += 1
                if not exists:
                    missing += 1
                    problems.append({
                        "kind": "missing",
                        "source": f"{rel}:{lineno}",
                        "anchor": f"{path}:{ln}",
                    })
                    continue
                nlines = len(target.read_text(encoding="utf-8").splitlines())
                if ln < 1 or ln > nlines:
                    oob += 1
                    problems.append({
                        "kind": "oob",
                        "source": f"{rel}:{lineno}",
                        "anchor": f"{path}:{ln}",
                        "nlines": nlines,
                    })

            for name, ln_s in _BASE.findall(line):
                hits = by_base.get(name, [])
                if len(hits) > 1:
                    total += 1
                    ambig += 1
                    problems.append({
                        "kind": "ambig",
                        "source": f"{rel}:{lineno}",
                        "anchor": f"{name}:{ln_s}",
                        "hits": hits[:5],
                    })

    return {
        "total": total,
        "missing": missing,
        "oob": oob,
        "ambig": ambig,
        "include_fenced": include_fenced,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--include-fenced",
        action="store_true",
        help="also count anchors inside markdown fences (default: skip fences)",
    )
    args = ap.parse_args(argv)
    result = scan(include_fenced=args.include_fenced)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"anchors total={result['total']} missing={result['missing']} "
            f"oob={result['oob']} ambig={result['ambig']}"
        )
        for p in result["problems"][:20]:
            print(f"  ! {p}")
    if result["missing"] > 0 or result["oob"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
