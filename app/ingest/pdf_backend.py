"""可插拔 PDF 抽取后端：默认 pypdf，可选 Docling（版式/表格增强）。

设计（与研判智能体解耦）：
- 解析是摄取插件，不是分析师人格；
- Docling 未安装或失败时回退 pypdf / 披露，永不炸管线；
- Docling 产物由装载层标成派生低可信（见 case_loader）。

环境变量：VERITAS_PDF_BACKEND=pypdf|docling（默认 pypdf）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractResult:
    title: str
    text: str
    meta: dict = field(default_factory=dict)
    backend: str = "pypdf"
    fallback_from: str = ""  # 若发生回退，记原后端名
    error: str = ""          # 非空表示该后端失败（可能仍有 text=回退结果）


_BACKEND_OVERRIDE: str | None = None


def set_pdf_backend(name: str | None) -> None:
    """管线/测试注入当前后端（优先于环境变量）。"""
    global _BACKEND_OVERRIDE
    if name is None:
        _BACKEND_OVERRIDE = None
        return
    v = str(name).strip().lower()
    _BACKEND_OVERRIDE = v if v in ("pypdf", "docling") else "pypdf"


def resolved_backend() -> str:
    if _BACKEND_OVERRIDE in ("pypdf", "docling"):
        return _BACKEND_OVERRIDE
    v = (os.environ.get("VERITAS_PDF_BACKEND") or "pypdf").strip().lower()
    return v if v in ("pypdf", "docling") else "pypdf"


def extract_pdf(path: Path, backend: str | None = None) -> ExtractResult:
    """按后端抽 PDF → ExtractResult；docling 失败则回退 pypdf。"""
    path = Path(path)
    want = (backend or resolved_backend()).strip().lower()
    if want == "docling":
        try:
            return _extract_docling(path)
        except Exception as exc:
            fb = _extract_pypdf(path)
            fb.fallback_from = "docling"
            fb.error = f"{type(exc).__name__}: {exc}"
            fb.meta = {
                **fb.meta,
                "parser": fb.backend,
                "parser_requested": "docling",
                "parser_fallback": True,
                "parser_error": fb.error,
            }
            return fb
    return _extract_pypdf(path)


def _extract_pypdf(path: Path) -> ExtractResult:
    from app.ingest.readers import read_pdf

    title, text = read_pdf(path)
    meta: dict = {"parser": "pypdf", "file": str(path)}
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        meta["pdf_pages"] = len(reader.pages)
    except Exception:
        pass
    return ExtractResult(title=title, text=text, meta=meta, backend="pypdf")


def _extract_docling(path: Path) -> ExtractResult:
    """Docling → Markdown（表格尽量保留为 MD 表）。未安装则 ImportError。"""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise ImportError(
            "Docling 未安装。可选：pip install -r requirements-docling.txt"
        ) from exc

    converter = DocumentConverter()
    result = converter.convert(str(path))
    doc = result.document
    title = path.stem
    try:
        if getattr(doc, "name", None) and str(doc.name).strip():
            title = str(doc.name).strip()
    except Exception:
        pass
    text = ""
    if hasattr(doc, "export_to_markdown"):
        text = doc.export_to_markdown() or ""
    elif hasattr(doc, "export_to_text"):
        text = doc.export_to_text() or ""
    else:
        text = str(doc)
    n_tables = 0
    try:
        tables = getattr(doc, "tables", None) or []
        n_tables = len(tables)
    except Exception:
        pass
    meta = {
        "parser": "docling",
        "file": str(path),
        "layout_engine": "docling",
        "n_tables": n_tables,
        "derived": True,
    }
    if not (text or "").strip():
        raise ValueError("Docling 未解析出任何文本")
    return ExtractResult(
        title=title, text=text, meta=meta, backend="docling")


def docling_available() -> bool:
    try:
        import docling  # noqa: F401
        return True
    except ImportError:
        return False
