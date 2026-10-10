#!/usr/bin/env python3
"""把可离线启动的比赛包打到桌面（含 vendor，不含密钥与用户案件）。"""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"
OUT = DESKTOP / "veritas-现场离线包.zip"

SKIP_DIR = {
    ".git", ".venv", "venv", ".runtime", "__pycache__", ".pytest_cache",
    ".mypy_cache", "dist", ".idea", ".vscode",
}
SKIP_PREFIX = (
    "cases/user-",
    "eval/corpus/",
)


def _skip(rel: str) -> bool:
    parts = Path(rel).parts
    if parts and parts[0] in SKIP_DIR:
        return True
    if any(p in SKIP_DIR for p in parts):
        return True
    if rel.startswith(SKIP_PREFIX):
        return True
    name = parts[-1] if parts else ""
    if name in {".env", "config.json", ".workbench_llm.json", "run-server.bat", "launch-log.txt"}:
        return True
    if name.endswith((".pyc", ".pyo")):
        return True
    return False


def main() -> None:
    ready = ROOT / "vendor/READY"
    if not ready.is_file():
        raise SystemExit("还没有离线包。先运行：python scripts/prepare_offline_bundle.py")
    if OUT.exists():
        OUT.unlink()
    n = 0
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if _skip(rel):
                continue
            zf.write(path, rel)
            n += 1
    mb = OUT.stat().st_size / (1024 * 1024)
    print(f"OK {n} files -> {OUT} ({mb:.0f} MB)")


if __name__ == "__main__":
    main()
