"""把用户丢来的文件夹/散文件写成一个案件目录（有界、可审计）。

浏览器选文件夹时带相对路径；本模块只做落盘与 manifest，分诊/切片
仍走 load_case——不另做一套「语义分类后再让用户挑整理包」。

深度超限一律拒收（不截文件名、不改名、不压平）——截掉末段会让多文件
塌成同一 rel 静默覆盖（C-6 实测）。拒收分原因进 refused / ingest_notes。
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

# 可软拒收并披露的原因（与路径穿越等硬失败区分）
_SOFT_REFUSE = frozenset({"deep_path", "hidden_path", "oversize"})

_REASON_LABEL = {
    "deep_path": "路径层级超限",
    "hidden_path": "隐藏路径",
    "oversize": "单文件过大",
}


class CaseImportError(ValueError):
    """用户可见的导入失败（422）。"""


def _normalize_parts(name: str) -> list[str] | None:
    """相对路径 → 段列表；绝对/穿越/空 → None。"""
    raw = str(name or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or raw.startswith("~"):
        return None
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or p.endswith(":") for p in parts):
        return None
    return parts


def classify_import_path(name: str) -> tuple[str | None, str | None]:
    """路径消毒 → (rel, refuse_reason)。

    reason 为 None 表示可写；否则为 deep_path／hidden_path（oversize 在落盘前按体积判）。
    深度超限返回 (None, deep_path)，**绝不**截掉文件名后返回残缺路径。
    """
    parts = _normalize_parts(name)
    if parts is None:
        return None, "invalid_path"
    if parts[-1].lower() in _SKIP_NAMES:
        return None, "hidden_path"
    if any(p.lower() in _SKIP_DIR or p.startswith(".") for p in parts[:-1]):
        return None, "hidden_path"
    if parts[-1].startswith("."):
        return None, "hidden_path"
    if len(parts) > MAX_DEPTH + 1:  # 顶层文件夹名 + 至多 3 层
        return None, "deep_path"
    return "/".join(parts), None


def safe_relpath(name: str) -> str | None:
    """相对路径消毒：拒穿越/绝对路径/隐藏/超深；超深不再截断文件名。"""
    rel, reason = classify_import_path(name)
    if reason is not None:
        return None
    return rel


def _shared_root(rels: list[str]) -> str:
    tops = {r.split("/", 1)[0] for r in rels if "/" in r}
    if len(tops) == 1 and all("/" in r for r in rels):
        return next(iter(tops))
    return ""


def resolve_case_file(case_dir: Path, rel: str) -> Path | None:
    """把分诊账本里的相对路径解析到案件目录内；拒穿越/产物目录/manifest。

    深度与 dot 判定与 ``classify_import_path`` 同一套——导入拒收的路径
    不得再被删除清单／resolve 认可（C-6 闭环）。
    """
    parts = _normalize_parts(rel)
    if parts is None:
        return None
    if parts[-1].lower() in _SKIP_NAMES or parts[-1] == "manifest.yaml":
        return None
    if any(p.lower() in _SKIP_DIR or p.startswith(".") or p.startswith("out_")
           for p in parts):
        return None
    if len(parts) > MAX_DEPTH + 1:
        return None
    path = (case_dir / Path(*parts)).resolve()
    try:
        path.relative_to(case_dir.resolve())
    except ValueError:
        return None
    return path


def remove_case_files(case_dir: Path, rels: list[str]) -> dict:
    """按相对路径删除入卷文件；空目录顺带清掉。返回 removed/missing/refused。"""
    case_dir = Path(case_dir)
    if not case_dir.is_dir():
        raise CaseImportError("找不到这套资料")
    removed: list[str] = []
    missing: list[str] = []
    refused: list[str] = []
    for raw in rels:
        path = resolve_case_file(case_dir, raw)
        if path is None:
            refused.append(str(raw or "（无名）"))
            continue
        rel = str(path.relative_to(case_dir.resolve())).replace("\\", "/")
        if not path.is_file():
            missing.append(rel)
            continue
        path.unlink()
        removed.append(rel)
        # 清空父目录（不越过案件根）
        parent = path.parent
        while parent != case_dir and parent.is_dir():
            try:
                next(parent.iterdir())
                break
            except StopIteration:
                parent.rmdir()
                parent = parent.parent
    return {
        "removed": removed,
        "n_removed": len(removed),
        "missing": missing[:20],
        "refused": refused[:20],
    }


def _refuse_entry(name: str, reason: str) -> dict:
    return {"name": str(name or "（无名）"), "reason": reason}


def _refuse_label(reason: str) -> str:
    return _REASON_LABEL.get(reason, reason)


def _merge_import_refused(case_dir: Path, new_items: list[dict]) -> None:
    """把本次拒收写入 manifest.import_refused（追加去重），供 load_case 披露。"""
    if not new_items:
        return
    from app.llm.yaml_robust import load_yaml_robust
    import yaml

    man = case_dir / "manifest.yaml"
    if not man.is_file():
        return
    meta = dict(load_yaml_robust(man) or {})
    existing = list(meta.get("import_refused") or [])
    seen = {(str(x.get("name")), str(x.get("reason"))) for x in existing
            if isinstance(x, dict)}
    for item in new_items:
        key = (str(item.get("name")), str(item.get("reason")))
        if key in seen:
            continue
        existing.append({"name": item["name"], "reason": item["reason"]})
        seen.add(key)
    meta["import_refused"] = existing
    man.write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _filter_items(
    items: list[tuple[str, bytes]],
    *,
    existing: int = 0,
    total: int = 0,
) -> tuple[list[tuple[str, bytes]], list[dict], list[str]]:
    """消毒 + 体积检查 → (kept, refused, skipped_compat)。"""
    kept: list[tuple[str, bytes]] = []
    refused: list[dict] = []
    skipped: list[str] = []
    running = total
    for name, blob in items:
        rel, reason = classify_import_path(name)
        if reason is not None:
            if reason in _SOFT_REFUSE:
                entry = _refuse_entry(name, reason)
                refused.append(entry)
                skipped.append(
                    f"{entry['name']}（{_refuse_label(reason)}）")
            else:
                skipped.append(name or "（无名）")
            continue
        assert rel is not None
        data = blob if isinstance(blob, (bytes, bytearray)) else bytes(blob)
        if len(data) > MAX_BYTES_EACH:
            entry = _refuse_entry(name or rel, "oversize")
            refused.append(entry)
            skipped.append(f"{entry['name']}（{_refuse_label('oversize')}）")
            continue
        running += len(data)
        if running > MAX_BYTES_TOTAL:
            raise CaseImportError("资料总体积超过上限，请先筛一批再添加")
        if existing + len(kept) >= MAX_FILES:
            raise CaseImportError(f"文件数超过 {MAX_FILES}，请先删一批再添加")
        kept.append((rel, bytes(data)))
    return kept, refused, skipped


def _result_payload(
    *,
    case: str,
    n_written: int,
    refused: list[dict],
    skipped: list[str],
    appended: bool = False,
    title: str = "",
    question: str = "",
) -> dict:
    out = {
        "case": case,
        "n_written": n_written,
        "refused": refused[:50],
        "n_refused": len(refused),
        "skipped": skipped[:20],
        "n_skipped": len(skipped),
    }
    if appended:
        out["appended"] = True
    if title:
        out["title"] = title
    if question:
        out["question"] = question
    return out


def append_imported_files(
    case_dir: Path,
    items: list[tuple[str, bytes]],
) -> dict:
    """往已有案件追加文件（导入后删错再补的场景）。"""
    from app.ingest.case_loader import _collect_files

    case_dir = Path(case_dir)
    if not case_dir.is_dir() or not (case_dir / "manifest.yaml").is_file():
        raise CaseImportError("找不到这套资料")
    if not items:
        raise CaseImportError("没有收到文件")
    already = _collect_files(case_dir).files
    existing = len(already)
    total = sum(f.stat().st_size for f, _ in already if f.is_file())
    kept, refused, skipped = _filter_items(
        items, existing=existing, total=total)
    if not kept:
        if refused:
            _merge_import_refused(case_dir, refused)
            return _result_payload(
                case=case_dir.name, n_written=0,
                refused=refused, skipped=skipped, appended=True)
        raise CaseImportError("没有可落盘的文件（路径不合法或全是系统垃圾文件）")
    n_written = 0
    for rel, data in kept:
        path = case_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.relative_to(case_dir)
        except ValueError as exc:
            raise CaseImportError("非法路径") from exc
        path.write_bytes(data)
        n_written += 1
    _merge_import_refused(case_dir, refused)
    return _result_payload(
        case=case_dir.name, n_written=n_written,
        refused=refused, skipped=skipped, appended=True)


def write_imported_case(
    cases_root: Path,
    items: list[tuple[str, bytes]],
    question: str = "",
) -> dict:
    """items: (relative_name, bytes)。返回含 n_written / refused / n_refused。"""
    if not items:
        raise CaseImportError("没有收到文件")
    kept, refused, skipped = _filter_items(items)
    if not kept and not refused:
        raise CaseImportError("没有可落盘的文件（路径不合法或全是系统垃圾文件）")
    if kept and len(kept) > MAX_FILES:
        raise CaseImportError(f"文件数超过 {MAX_FILES}，请先拆开再添加")

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    case_name = f"user-{stamp}"
    dest = cases_root / case_name
    n = 2
    while dest.exists():
        dest = cases_root / f"{case_name}-{n}"
        n += 1
    dest.mkdir(parents=True, exist_ok=False)

    import json as _json

    root = _shared_root([r for r, _ in kept]) if kept else ""
    title = root or dest.name
    q = (question or "").strip() or (
        f"请根据已入卷资料研判：{title}" if kept
        else "（本次导入文件均未入卷，请查看拒收原因后重试）"
    )
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

    _merge_import_refused(dest, refused)
    return _result_payload(
        case=dest.name, n_written=len(kept),
        refused=refused, skipped=skipped,
        title=title, question=q,
    )
