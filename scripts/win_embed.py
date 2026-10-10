#!/usr/bin/env python3
"""Windows 便携 Python 启动辅助（只用标准库，不 import app）。

便携解释器的 python312._pth 会丢掉当前目录，导致找不到 app 包。
prepare：把仓库根写进 ._pth，并生成 run-server.bat。
wait：等 127.0.0.1:8765 真正应答再让启动器打开浏览器。
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path


def prepare() -> None:
    root = Path.cwd()
    py = os.environ.get("VERITAS_PY") or sys.executable
    norm = py.replace("/", "\\").lower()
    if norm.endswith("\\.runtime\\python.exe"):
        rel = ".runtime\\python.exe"
    elif norm.endswith("\\.venv\\scripts\\python.exe"):
        rel = ".venv\\Scripts\\python.exe"
    else:
        rel = os.path.relpath(py, root)
    pth = root / ".runtime" / "python312._pth"
    if pth.is_file():
        lines = pth.read_text(encoding="utf-8").splitlines()
        root_s = str(root)
        if root_s not in lines:
            if lines and lines[-1].strip() == "import site":
                lines.insert(-1, root_s)
            else:
                lines.append(root_s)
                lines.append("import site")
            pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 演示默认 HMAC 密钥（与 app.core.hashchain.DEMO_CHAIN_KEY 一致）
    demo_key = os.environ.get("VERITAS_CHAIN_KEY") or "veritas-contest-demo-hmac"
    bat = (
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        f'if not defined VERITAS_CHAIN_KEY set "VERITAS_CHAIN_KEY={demo_key}"\r\n'
        f'"%~dp0{rel}" -m app.server --port 8765\r\n'
        "echo.\r\n"
        "echo Server stopped.\r\n"
        "pause\r\n"
    )
    (root / "run-server.bat").write_bytes(bat.encode("ascii"))


def wait_ready() -> int:
    url = "http://127.0.0.1:8765/"
    for _ in range(40):
        try:
            urllib.request.urlopen(url, timeout=1)
            return 0
        except Exception:
            time.sleep(0.5)
    return 1


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    if cmd == "wait":
        raise SystemExit(wait_ready())
    prepare()


if __name__ == "__main__":
    main()
