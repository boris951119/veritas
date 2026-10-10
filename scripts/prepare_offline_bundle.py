#!/usr/bin/env python3
"""在有网的电脑上提前下载比赛离线包（现场不再访问外网）。

产出（不入库，随 U 盘/zip 带走）：
  vendor/python/          Windows 便携 Python + macOS 安装包 + get-pip
  vendor/wheels/          工作台依赖（win_amd64 与当前 Mac）
  vendor/wheels-docling/  可选增强版式（体积大，失败不影响主包）

用法：
  .venv/bin/python scripts/prepare_offline_bundle.py
  .venv/bin/python scripts/prepare_offline_bundle.py --no-docling
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_VER = "3.12.10"
EMBED_NAME = f"python-{PY_VER}-embed-amd64.zip"
PKG_NAME = f"python-{PY_VER}-macos11.pkg"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VER}/{EMBED_NAME}"
PKG_URL = f"https://www.python.org/ftp/python/{PY_VER}/{PKG_NAME}"
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"

WIN_SPEC = [
    "--python-version", "312",
    "--platform", "win_amd64",
    "--implementation", "cp",
    "--abi", "cp312",
    "--only-binary=:all:",
]


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        print("已有", dest.name, dest.stat().st_size // 1024, "KB")
        return
    print("下载", url)
    urllib.request.urlretrieve(url, dest)
    print("  ->", dest, dest.stat().st_size // 1024, "KB")


def _pip_download(req: Path, dest: Path, extra: list[str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "pip", "download", "-r", str(req), "-d", str(dest), *extra])


def _fill_win_markers(dest: Path) -> None:
    """把 wheel METADATA 里 Windows 条件依赖再 download 一遍。"""
    import zipfile
    from packaging.markers import default_environment
    from packaging.requirements import Requirement

    env = default_environment()
    env.update({
        "python_version": "3.12",
        "python_full_version": "3.12.10",
        "sys_platform": "win32",
        "platform_system": "Windows",
        "platform_machine": "AMD64",
        "os_name": "nt",
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
    })
    names: set[str] = set()
    for whl in dest.glob("*.whl"):
        with zipfile.ZipFile(whl) as zf:
            meta = next((n for n in zf.namelist() if n.endswith(".dist-info/METADATA")), None)
            if not meta:
                continue
            for line in zf.read(meta).decode("utf-8", errors="replace").splitlines():
                if not line.startswith("Requires-Dist: "):
                    continue
                raw = line.split(": ", 1)[1].strip()
                try:
                    req = Requirement(raw)
                except Exception:
                    continue
                if req.marker and not req.marker.evaluate(env):
                    continue
                # 已有同名 wheel 就跳过
                key = req.name.lower().replace("_", "-")
                if any(p.name.lower().startswith(key + "-") for p in dest.glob("*.whl")):
                    continue
                names.add(req.name)
    if not names:
        print("Windows 条件依赖已齐")
        return
    print("补齐 Windows 条件依赖:", ", ".join(sorted(names)))
    _run([
        sys.executable, "-m", "pip", "download",
        *sorted(names),
        "-d", str(dest),
        *WIN_SPEC,
    ])


def _pth_template() -> None:
    """便携 Python 解压后要替换的 ._pth，否则没有 site-packages。"""
    text = "python312.zip\n.\nLib\\site-packages\nimport site\n"
    path = ROOT / "vendor/python/python312._pth"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-docling", action="store_true")
    args = ap.parse_args()
    py_dir = ROOT / "vendor/python"
    py_dir.mkdir(parents=True, exist_ok=True)

    print("== 1/4 便携 Python / 安装包 ==")
    _download(EMBED_URL, py_dir / EMBED_NAME)
    _download(GET_PIP, py_dir / "get-pip.py")
    if platform.system() == "Darwin":
        _download(PKG_URL, py_dir / PKG_NAME)
    _pth_template()

    core = ROOT / "requirements-offline.txt"
    print("== 2/4 Windows 依赖 wheel ==")
    _pip_download(core, ROOT / "vendor/wheels/win_amd64", WIN_SPEC)
    # Mac 上 cross-download 会漏掉仅 Windows marker 才启用的依赖
    _run([
        sys.executable, "-m", "pip", "download",
        "pip", "setuptools", "wheel", "colorama", "distro",
        "-d", str(ROOT / "vendor/wheels/win_amd64"),
        *WIN_SPEC,
    ])
    # 再扫一遍已下载 wheel 的 Requires-Dist，补齐 Windows 条件依赖
    _fill_win_markers(ROOT / "vendor/wheels/win_amd64")

    print("== 3/4 当前系统依赖 wheel（便于本机离线自测）==")
    tag = "macosx" if platform.system() == "Darwin" else (
        "win_amd64" if platform.system() == "Windows" else "linux_x86_64")
    native = ROOT / "vendor/wheels" / tag
    if tag == "win_amd64":
        print("当前已是 Windows，跳过重复下载")
    else:
        _pip_download(core, native, [])
        _run([
            sys.executable, "-m", "pip", "download",
            "pip", "setuptools", "wheel", "-d", str(native),
        ])

    print("== 4/4 可选 Docling（增强版式，体积大）==")
    if args.no_docling:
        print("已跳过 Docling")
    else:
        doc = ROOT / "requirements-docling.txt"
        try:
            _pip_download(doc, ROOT / "vendor/wheels-docling/win_amd64", WIN_SPEC)
            if tag != "win_amd64":
                _pip_download(doc, ROOT / "vendor/wheels-docling" / tag, [])
        except subprocess.CalledProcessError as e:
            print("Docling 离线包未下完（主包仍可用）：", e)
            print("可稍后重跑本脚本；现场不装增强版式也能演示。")

    (ROOT / "vendor/READY").write_text(
        f"prepared by python {PY_VER} on {platform.platform()}\n",
        encoding="utf-8",
    )
    print("完成。下一步：python scripts/pack_offline_bundle.py")


if __name__ == "__main__":
    main()
