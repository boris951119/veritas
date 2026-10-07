"""多源阅读器：txt / markdown / html / pdf → (title, 全文)。

PDF 走 pypdf 懒加载（未安装时明确报错，不影响其余格式与全量测试）；
HTML 用标准库 HTMLParser 抽 title 与正文，零第三方依赖。
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


def read_txt(path: Path) -> tuple[str, str]:
    """纯文本：文件名作标题。"""
    return path.stem, path.read_text(encoding="utf-8", errors="replace")


def read_markdown(path: Path) -> tuple[str, str]:
    """Markdown：首行一级标题作标题（无则用文件名），全文原样返回。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    for line in text.splitlines():
        if line.strip().startswith("#"):
            title = line.lstrip("#").strip() or title
            break
    return title, text


class _TextExtractor(HTMLParser):
    """抽 <title> 与正文文本（script/style 剔除）。"""

    _SKIP = {"script", "style"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.chunks: list[str] = []
        self._in_skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._in_skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._in_skip:
            self._in_skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self._in_skip:
            return
        if getattr(self, "_in_title", False):
            self.title += data.strip()
        else:
            self.chunks.append(data)


def parse_html(raw: str, fallback_title: str) -> tuple[str, str]:
    """HTML 原文 → (title, 正文)：网页抓取与本地 .html 共用同一解析。"""
    parser = _TextExtractor()
    parser.feed(raw)
    title = parser.title or fallback_title
    text = "".join(parser.chunks)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return title, text


def read_html(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return parse_html(raw, path.stem)


def read_pdf(path: Path) -> tuple[str, str]:
    """PDF 轻量抽取（pypdf）：逐页文本，页间空行分隔。

    版式增强请走 ``pdf_backend.extract_pdf`` / ``VERITAS_PDF_BACKEND``；
    本函数保持为确定性默认后端，供回退与测试直接调用。
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ImportError(
            "PDF 摄取需要 pypdf：pip install pypdf"
        ) from exc
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    title = path.stem
    # 元信息里常带标题
    try:
        meta_title = (reader.metadata or {}).get("/Title")
        if meta_title and str(meta_title).strip():
            title = str(meta_title).strip()
    except Exception:
        pass
    return title, "\n\n".join(pages)


def read_pdf_routed(path: Path) -> tuple[str, str]:
    """经可插拔后端抽 PDF（默认 pypdf；可选 Docling）。"""
    from app.ingest.pdf_backend import extract_pdf

    result = extract_pdf(path)
    return result.title, result.text


def _zip_xml_text(path: Path, inner_prefix: str) -> str:
    """Office Open XML（docx/xlsx/pptx 本质是 zip）抽标签间文字。"""
    import re
    import zipfile
    from html import unescape

    tag = re.compile(r"<[^>]+>")
    chunks: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.startswith(inner_prefix) or not name.endswith(".xml"):
                continue
            raw = zf.read(name).decode("utf-8", errors="replace")
            text = unescape(tag.sub(" ", raw))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def read_docx(path: Path) -> tuple[str, str]:
    return path.stem, _zip_xml_text(path, "word/")


def read_xlsx(path: Path) -> tuple[str, str]:
    return path.stem, _zip_xml_text(path, "xl/")


def read_pptx(path: Path) -> tuple[str, str]:
    return path.stem, _zip_xml_text(path, "ppt/slides/")


READERS = {
    ".txt": read_txt,
    ".md": read_markdown,
    ".markdown": read_markdown,
    ".html": read_html,
    ".htm": read_html,
    ".pdf": read_pdf_routed,
    ".docx": read_docx,
    ".xlsx": read_xlsx,
    ".xlsm": read_xlsx,
    ".pptx": read_pptx,
}

# 老二进制办公格式：不能当纯文本读，由装载层记「不支持」
UNSUPPORTED_EXTS = {".doc", ".xls", ".ppt", ".rtf", ".pages", ".numbers"}


def read_any(path: Path) -> tuple[str, str]:
    """按扩展名分发；未知扩展名按纯文本兜底。"""
    reader = READERS.get(path.suffix.lower(), read_txt)
    return reader(path)
