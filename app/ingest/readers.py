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


def read_html(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    parser = _TextExtractor()
    parser.feed(raw)
    title = parser.title or path.stem
    text = "".join(parser.chunks)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return title, text


def read_pdf(path: Path) -> tuple[str, str]:
    """PDF：逐页抽取（页间以空行分隔，切段后 locator 记页码——
    页码级 locator 在 case_loader 侧由 page_hint 承载）。"""
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


READERS = {
    ".txt": read_txt,
    ".md": read_markdown,
    ".markdown": read_markdown,
    ".html": read_html,
    ".htm": read_html,
    ".pdf": read_pdf,
}


def read_any(path: Path) -> tuple[str, str]:
    """按扩展名分发；未知扩展名按纯文本兜底。"""
    reader = READERS.get(path.suffix.lower(), read_txt)
    return reader(path)
