"""把用户丢来的文件夹/散文件写成一个案件目录（有界、可审计）。

浏览器选文件夹时带相对路径；本模块只做落盘与 manifest，分诊/切片
仍走 load_case——不另做一套「语义分类后再让用户挑整理包」。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

MAX_FILES = 500
MAX_BYTES_EACH = 20 * 1024 * 1024
MAX_BYTES_TOTAL = 200 * 1024 * 1024
MAX_DEPTH = 3

_SKIP_NAMES = {
    ".ds_store", "thumbs.db", "desktop.ini", ".gitkeep",
}
_SKIP_DIR = {"__macosx", "__pycache__", ".git", "out", "history", ".fetched"}


class CaseImportError(ValueError):
    """用户可见的导入失败（422）。"""


def safe_relpath(name: str) -> str | None:
    """相对路径消毒：拒穿越/绝对路径，跳过系统垃圾目录，深度封顶。"""
    raw = str(name or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or raw.startswith("~"):
        return None
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or p.endswith(":") for p in parts):
        return None
    if parts[-1].lower() in _SKIP_NAMES:
        return None
    if any(p.lower() in _SKIP_DIR or p.startswith(".") for p in parts[:-1]):
        return None
    if parts[-1].startswith("."):
        return None
    if len(parts) > MAX_DEPTH + 1:  # 顶层文件夹名 + 至多 3 层
        parts = parts[: MAX_DEPTH + 1]
    return "/".join(parts)


def _shared_root(rels: list[str]) -> str:
    tops = {r.split("/", 1)[0] for r in rels if "/" in r}
    if len(tops) == 1 and all("/" in r for r in rels):
        return next(iter(tops))
    return ""


def write_imported_case(
    cases_root: Path,
    items: list[tuple[str, bytes]],
    question: str = "",
) -> dict:
    """items: (relative_name, bytes)。返回 {case, title, n_written, skipped}。"""
    if not items:
        raise CaseImportError("没有收到文件")
    kept: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    total = 0
    for name, blob in items:
        rel = safe_relpath(name)
        if not rel:
            skipped.append(name or "（无名）")
            continue
        data = blob if isinstance(blob, (bytes, bytearray)) else bytes(blob)
        if len(data) > MAX_BYTES_EACH:
            skipped.append(f"{rel}（单文件过大）")
            continue
        total += len(data)
        if total > MAX_BYTES_TOTAL:
            raise CaseImportError("资料总体积超过上限，请先筛一批再添加")
        kept.append((rel, bytes(data)))
        if len(kept) > MAX_FILES:
            raise CaseImportError(f"文件数超过 {MAX_FILES}，请先拆开再添加")
    if not kept:
        raise CaseImportError("没有可落盘的文件（路径不合法或全是系统垃圾文件）")

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    case_name = f"user-{stamp}"
    dest = cases_root / case_name
    n = 2
    while dest.exists():
        dest = cases_root / f"{case_name}-{n}"
        n += 1
    dest.mkdir(parents=True, exist_ok=False)

    import json as _json

    root = _shared_root([r for r, _ in kept])
    title = root or dest.name
    q = (question or "").strip() or f"请根据已入卷资料研判：{title}"
    (dest / "manifest.yaml").write_text(
        "question: " + _json.dumps(q, ensure_ascii=False) + "\n"
        "title: " + _json.dumps(title, ensure_ascii=False) + "\n"
        "imported: true\n",
        encoding="utf-8",
    )

    for rel, data in kept:
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.relative_to(dest)
        except ValueError as exc:
            raise CaseImportError("非法路径") from exc
        path.write_bytes(data)

    return {
        "case": dest.name,
        "title": title,
        "n_written": len(kept),
        "skipped": skipped[:20],
        "n_skipped": len(skipped),
        "question": q,
    }
