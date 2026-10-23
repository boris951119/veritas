#!/usr/bin/env python3
"""C-37：行数账一次抄全（入库脚本）。

输出 HANDOFF 行数与字节、AGENTS 行数、architecture-map 行数、
app/ tests/ scripts/ web/ calibration/ 各自总行数、
pytest --collect-only 条数、grep -c '^def test_' 合计。

写行数账只许抄本脚本输出，不许往上传播估数（见 docs/dev-protocol.md §5）。

用法：
    .venv/bin/python scripts/ledger_counts.py
    .venv/bin/python scripts/ledger_counts.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return path.stat().st_size


def _dir_py_lines(rel: str) -> int:
    root = ROOT / rel
    if not root.is_dir():
        return 0
    total = 0
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            total += len(p.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
    return total


def _collect_only() -> int:
    py = ROOT / ".venv" / "bin" / "python"
    cmd = [str(py) if py.exists() else sys.executable, "-m", "pytest", "--collect-only", "-q"]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"(\d+)\s+tests?\s+collected", r.stdout + r.stderr)
    if m:
        return int(m.group(1))
    # fallback: count lines like "tests/..."
    return sum(1 for line in r.stdout.splitlines() if "::" in line)


def _def_test_count() -> int:
    n = 0
    tests = ROOT / "tests"
    for p in tests.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("def test_"):
                n += 1
    return n


def collect() -> dict:
    handoff = ROOT / "docs" / "HANDOFF.md"
    agents = ROOT / "AGENTS.md"
    # architecture-map: prefer dated file if present
    maps = sorted((ROOT / "docs").glob("architecture-map-*.html"))
    amap = maps[-1] if maps else ROOT / "docs" / "architecture-map.html"
    return {
        "HANDOFF_lines": _lines(handoff),
        "HANDOFF_bytes": _bytes(handoff),
        "AGENTS_lines": _lines(agents),
        "architecture_map_path": str(amap.relative_to(ROOT)) if amap.exists() else "",
        "architecture_map_lines": _lines(amap),
        "app_lines": _dir_py_lines("app"),
        "tests_lines": _dir_py_lines("tests"),
        "scripts_lines": _dir_py_lines("scripts"),
        "web_lines": _lines_sum_web(),
        "calibration_lines": _dir_any_lines("calibration"),
        "pytest_collect_only": _collect_only(),
        "def_test_count": _def_test_count(),
    }


def _lines_sum_web() -> int:
    root = ROOT / "web"
    if not root.is_dir():
        return 0
    total = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".html", ".js", ".css", ".mjs", ".ts"}:
            continue
        try:
            total += len(p.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
    return total


def _dir_any_lines(rel: str) -> int:
    root = ROOT / rel
    if not root.is_dir():
        return 0
    total = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".py", ".json", ".md", ".txt", ".csv"}:
            continue
        if "__pycache__" in p.parts:
            continue
        try:
            total += len(p.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    data = collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"HANDOFF_lines={data['HANDOFF_lines']}")
        print(f"HANDOFF_bytes={data['HANDOFF_bytes']}")
        print(f"AGENTS_lines={data['AGENTS_lines']}")
        print(f"architecture_map_lines={data['architecture_map_lines']} ({data['architecture_map_path']})")
        print(f"app_lines={data['app_lines']}")
        print(f"tests_lines={data['tests_lines']}")
        print(f"scripts_lines={data['scripts_lines']}")
        print(f"web_lines={data['web_lines']}")
        print(f"calibration_lines={data['calibration_lines']}")
        print(f"pytest_collect_only={data['pytest_collect_only']}")
        print(f"def_test_count={data['def_test_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
