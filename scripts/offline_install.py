#!/usr/bin/env python3
"""从包内 wheel 离线安装（无外网）。由启动器调用。"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def wheel_tag() -> str:
    if sys.platform == "win32":
        return "win_amd64"
    if sys.platform == "darwin":
        return "macosx"
    return "linux_x86_64"


def wheels_dir(kind: str) -> Path:
    base = ROOT / ("vendor/wheels-docling" if kind == "docling" else "vendor/wheels")
    return base / wheel_tag()


def _pip(py: str, args: list[str]) -> None:
    cmd = [py, "-m", "pip", *args]
    print(" ", " ".join(cmd))
    subprocess.check_call(cmd)


def install(py: str, kind: str) -> None:
    wheels = wheels_dir(kind)
    if not wheels.is_dir() or not any(wheels.iterdir()):
        raise SystemExit(
            f"缺少离线包：{wheels}\n"
            "请在有网的电脑上先运行：python scripts/prepare_offline_bundle.py\n"
            "再把整个文件夹（含 vendor/）拷到比赛电脑。"
        )
    req = ROOT / ("requirements-docling.txt" if kind == "docling" else "requirements-offline.txt")
    _pip(py, ["install", "--upgrade", "pip", "--no-index", "--find-links", str(wheels)])
    # Windows 先钉 colorama，避免 click/pytest 一类条件依赖漏包时整批失败
    if sys.platform == "win32" and kind == "core":
        try:
            _pip(py, ["install", "--no-index", "--find-links", str(wheels), "colorama"])
        except subprocess.CalledProcessError:
            print("警告：colorama 未装上，继续安装主依赖…")
    _pip(py, ["install", "--no-index", "--find-links", str(wheels), "-r", str(req)])


def enable_docling() -> None:
    env = ROOT / ".env"
    line = "VERITAS_PDF_BACKEND=docling"
    text = env.read_text(encoding="utf-8") if env.is_file() else ""
    if "VERITAS_PDF_BACKEND=" in text:
        lines = []
        for raw in text.splitlines():
            if raw.strip().startswith("VERITAS_PDF_BACKEND="):
                lines.append(line)
            else:
                lines.append(raw)
        env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        extra = ("\n" if text and not text.endswith("\n") else "") + line + "\n"
        env.write_text(text + extra, encoding="utf-8")
    print("已写入 .env ：", line)
    print("下次点「启动工作台」会优先走增强版式；失败自动回退轻量抽取。")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--docling", action="store_true")
    args = p.parse_args()
    print("平台", platform.platform(), "wheel", wheel_tag())
    if args.docling:
        install(args.python, "docling")
        enable_docling()
    else:
        install(args.python, "core")
    print("离线安装完成。")


if __name__ == "__main__":
    main()
