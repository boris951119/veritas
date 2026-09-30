"""压缩包安全拆封：zip/tar 展开为文件清单 + 拒绝账单（零新依赖）。

zip 不是信源，是信源的集装箱——本模块只做带边界的拆封，拆出的
文件交回 load_case 走与本地文件完全相同的生命周期。四道边界
（假定输入敌意）：

1. zip-slip：拒绝绝对路径与 .. 穿越（entry 名逐段校验）；
2. 炸弹：entry 声明大小预检 + 流式读取硬上限（防说谎的包头）；
3. 数量：entry 总数封顶（超出部分披露「另有 N 个未展开」）；
4. 嵌套深度 =1：压缩包内的压缩包不再展开（披露）。

加密 zip / 损坏包 → 记账单不炸 run；7z/RAR 按魔数识别 → 披露
「不支持的压缩格式」。每条拒绝都进 notes（kind=archive），成功
展开也有一行总账。上限为模块级常量，测试可 monkeypatch 调小。
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

MAX_ENTRY_BYTES = 20 * 1024 * 1024      # 单文件解压上限
MAX_TOTAL_BYTES = 200 * 1024 * 1024     # 单包解压总量上限
MAX_ENTRIES = 500                        # 单包 entry 数上限

_MAGIC: list[tuple[bytes, str]] = [
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),   # 空包
    (b"\x37\x7a\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
]

_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar"}


def sniff_format(path: Path) -> str:
    """魔数识别压缩格式：zip/tar（可处理）· 7z/rar（明确不支持）· ''。"""
    try:
        head = path.open("rb").read(8)
    except OSError:
        return ""
    for magic, fmt in _MAGIC:
        if head.startswith(magic):
            return fmt
    if tarfile.is_tarfile(path):
        return "tar"
    return ""


def is_archive_file(path: Path) -> bool:
    return path.suffix.lower() in _ARCHIVE_SUFFIXES


def _note(file_label: str, detail: str) -> dict:
    return {"file": file_label, "kind": "archive", "detail": detail}


def _safe_parts(name: str) -> list[str] | None:
    """entry 名 → 安全相对路径段；穿越/绝对路径/盘符返回 None。"""
    normalized = name.replace("\\", "/")
    if normalized.startswith(("/", "~")):
        return None
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if not parts:
        return None
    for p in parts:
        if p == ".." or p.endswith(":"):   # 穿越段 / Windows 盘符
            return None
    return parts


def _stream_copy(src, dest: Path, cap: int) -> bool:
    """流式落盘并强制字节上限；超限即截断返回 False（防说谎的包头）。"""
    buf = io.BytesIO()
    total = 0
    while True:
        chunk = src.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            return False
        buf.write(chunk)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(buf.getvalue())
    return True


def expand_archive(path: Path, dest_dir: Path,
                   label: str = "") -> tuple[list[tuple[Path, str]], list[dict]]:
    """压缩包 → ([(解包文件路径, entry 名)], notes 账单)。

    嵌套压缩包会被解出文件但不返回（caller 不递归），只在账单记
    「嵌套压缩包未展开」。"""
    label = label or path.name
    fmt = sniff_format(path)
    if fmt in ("7z", "rar"):
        return [], [_note(label, f"不支持的压缩格式 {fmt}——请解压后提供")]
    if fmt not in ("zip", "tar"):
        return [], []

    out: list[tuple[Path, str]] = []
    notes: list[dict] = []
    n_rejected = 0
    reject_reasons: list[str] = []
    total_bytes = 0
    n_entries = 0
    truncated = False

    def _reject(reason: str) -> None:
        nonlocal n_rejected
        n_rejected += 1
        if len(reject_reasons) < 3:
            reject_reasons.append(reason)

    def _member_iter_zip():
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                yield info.filename, info.file_size, lambda i=info: zf.open(i)

    def _member_iter_tar():
        tf = tarfile.open(path)
        for m in tf:
            if not m.isfile():
                continue
            yield m.name, m.size, lambda mm=m: tf.extractfile(mm)

    try:
        members = _member_iter_zip() if fmt == "zip" else _member_iter_tar()
        for name, declared_size, opener in members:
            n_entries += 1
            if n_entries > MAX_ENTRIES:
                _reject(f"entry 超过 {MAX_ENTRIES} 上限")
                break
            if declared_size > MAX_ENTRY_BYTES:
                _reject(f"{name} 声明 {declared_size}B 超单文件上限")
                continue
            if total_bytes > MAX_TOTAL_BYTES:
                _reject("总量超上限")
                break
            parts = _safe_parts(name)
            if parts is None:
                _reject(f"{name} 路径穿越/绝对路径")
                continue
            if any(Path(p).suffix.lower() in _ARCHIVE_SUFFIXES for p in parts[-1:]):
                _reject(f"{name} 嵌套压缩包未展开")
                continue
            target = dest_dir.joinpath(*parts)
            try:
                ok = _stream_copy(opener(), target, MAX_ENTRY_BYTES)
            except RuntimeError:
                _reject(f"{name} 加密或损坏")
                continue
            except Exception as exc:
                _reject(f"{name} {type(exc).__name__}")
                continue
            if not ok:
                truncated = True
                _reject(f"{name} 实际大小超上限（截断拒收）")
                continue
            total_bytes += target.stat().st_size
            out.append((target, name))
    except zipfile.BadZipFile:
        return [], [_note(label, "压缩包损坏（BadZipFile）")]
    except tarfile.TarError as exc:
        return [], [_note(label, f"压缩包损坏（{type(exc).__name__}）")]
    except Exception as exc:
        return [], [_note(label, f"解包失败：{type(exc).__name__}: {exc}")]

    summary = f"压缩包 {label}：{n_entries} 个条目，解包 {len(out)} 个"
    if n_rejected:
        summary += f"，拒绝 {n_rejected} 个（{'；'.join(reject_reasons)}"
        if n_rejected > len(reject_reasons):
            summary += f" 等 {n_rejected} 项"
        summary += "）"
    if truncated:
        summary += "；存在超限截断拒收"
    notes.append(_note(label, summary))
    return out, notes
