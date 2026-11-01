#!/usr/bin/env python3
"""摘要已缓存时：只建图／索引／召回（跳过 summarize）。"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
cmd = [
    sys.executable, "-u",
    str(ROOT / "scripts/kg_lab/probe_kg_spike_recall.py"),
    "--skip-summarize",
    *sys.argv[1:],
]
raise SystemExit(subprocess.call(cmd, cwd=str(ROOT), env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(ROOT)}))
