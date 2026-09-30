"""案例装载：cases/<case>/ 目录 → Dossier。

目录布局（推荐带 manifest.yaml，亦可在无 manifest 时裸放文件）::

    cases/solid-state-battery/
    ├── manifest.yaml     # 题目、信源类型与可信度覆盖
    ├── overview.md
    ├── paper_x.pdf
    └── news_y.html

manifest.yaml 示例::

    question: 固态电池路线 2030 年前能否规模上车？
    sources:
      - file: overview.md
        type: report
        credibility: 0.7        # 可选覆盖
        published_at: 2026-03   # 可选：信源时点（时效闸/仲裁新近度用）
      - file: paper_x.pdf
        type: paper
    # 也可整目录推断：未列出的文件按扩展名/文件名推断类型

类型推断兜底：文件名含 paper/patent/news/web/note/report 关键词，
否则按扩展名（.pdf→paper、.html→web、.md/.txt→note）。
未声明 published_at 时回退抽取正文首个「20XX年」落入 meta.year。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.evidence import Dossier, Segment, Source, SourceType
from app.ingest.archive import expand_archive, is_archive_file, sniff_format
from app.ingest.links import classify_link_list
from app.ingest.readers import read_any
from app.ingest.segment import split_segments
from app.llm.yaml_robust import load_yaml_robust

_KEYWORD_HINTS: list[tuple[str, SourceType]] = [
    ("paper", SourceType.PAPER),
    ("patent", SourceType.PATENT),
    ("news", SourceType.NEWS),
    ("web", SourceType.WEB),
    ("report", SourceType.REPORT),
    ("note", SourceType.NOTE),
]

_EXT_HINTS = {
    ".pdf": SourceType.PAPER,
    ".html": SourceType.WEB,
    ".htm": SourceType.WEB,
    ".md": SourceType.NOTE,
    ".txt": SourceType.NOTE,
}

_YEAR_RE = re.compile(r"(19|20)\d{2}\s*年")

# 纯图片文件：无可靠文字层信号，按扩展名识别——专用披露，不入卷
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
               ".tiff", ".tif", ".heic", ".heif"}


def infer_source_type(path: Path) -> SourceType:
    name = path.name.lower()
    for kw, stype in _KEYWORD_HINTS:
        if kw in name:
            return stype
    return _EXT_HINTS.get(path.suffix.lower(), SourceType.OTHER)


def ingest_file(path: Path, source_id: str, source_type: SourceType,
                credibility: float | None = None, title: str | None = None,
                published_at: str | None = None,
                preloaded: tuple[str, str] | None = None) -> Source:
    """单文件 → Source（切段并编号，locator 记段序）。

    preloaded：(title, text) 已读内容直用（链接清单检测后复用，免双读）。"""
    real_title, text = preloaded or read_any(path)
    meta: dict = {"file": str(path)}
    if published_at:
        meta["published_at"] = published_at
    else:
        m = _YEAR_RE.search(text)
        if m:
            meta["year"] = re.sub(r"\D", "", m.group(0))
    source = Source.create(
        title=title or real_title,
        source_type=source_type,
        credibility=credibility,
        id=source_id,
        meta=meta,
    )
    for i, seg_text in enumerate(split_segments(text)):
        source.segments.append(Segment(
            id=f"{source_id}#s{i + 1}",
            source_id=source_id,
            text=seg_text,
            locator=f"段 {i + 1}",
            index=i,
        ))
    return source


def _pdf_probe(path: Path) -> dict:
    """PDF 元探测（尽力而为）：页数、内嵌图片数——图片披露用，不炸摄取。"""
    out: dict = {}
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        out["pdf_pages"] = len(reader.pages)
        images = 0
        for page in reader.pages:
            try:
                xo = (page.get("/Resources") or {}).get("/XObject") or {}
                images += sum(
                    1 for k in xo
                    if xo[k].get_object().get("/Subtype") == "/Image")
            except Exception:
                continue
        out["pdf_images"] = images
    except Exception:
        pass
    return out


def _collect_files(case_dir: Path, max_files: int = 500,
                   max_depth: int = 3) -> list[tuple[Path, str]]:
    """有界遍历案例目录 → [(路径, 相对路径)]。

    子目录此前被静默忽略——主办方自己解压成文件夹的场景同样常见；
    隐藏目录与 __pycache__ 跳过，数量/深度封顶（假定输入敌意）。"""
    out: list[tuple[Path, str]] = []

    def walk(d: Path, prefix: str, depth: int) -> None:
        if depth > max_depth or len(out) >= max_files:
            return
        for p in sorted(d.iterdir(), key=lambda x: x.name):
            if len(out) >= max_files:
                break
            if depth == 0 and p.name == "manifest.yaml":
                continue
            if p.is_dir():
                if p.name.startswith(".") or p.name == "__pycache__":
                    continue
                walk(p, f"{prefix}{p.name}/", depth + 1)
            else:
                out.append((p, prefix + p.name))

    walk(case_dir, "", 0)
    return out


def load_case(case_dir: Path, fetch_links: bool = False) -> Dossier:
    """案例目录 → Dossier（manifest.yaml 用缩进自愈加载）。

    摄取按文件隔离：单个损坏/加密文件只降级为 ingest_notes 披露，
    绝不炸整条 run。目录里的压缩包先安全拆封（slip/炸弹/数量/嵌套
    四道边界，见 ingest.archive），拆出的文件与本地文件同权走本流程；
    链接清单文件默认只披露不抓取（fetch_links=True 才逐条抓取并
    披露成败）。"""
    case_dir = Path(case_dir)
    manifest = {}
    manifest_path = case_dir / "manifest.yaml"
    if manifest_path.is_file():
        manifest = load_yaml_robust(manifest_path)

    dossier = Dossier(
        question=str(manifest.get("question") or case_dir.name),
        title=str(manifest.get("title") or case_dir.name),
    )

    declared_rel: dict[str, dict] = {}
    declared_name: dict[str, dict] = {}
    for item in manifest.get("sources") or []:
        if isinstance(item, dict) and item.get("file"):
            name = str(item["file"])
            declared_rel[name] = item
            declared_name.setdefault(name.rsplit("/", 1)[-1], item)

    counter = 0

    def _next_id() -> str:
        nonlocal counter
        counter += 1
        return f"SRC{counter}"

    def _ingest_one(path: Path, spec: dict, rel: str,
                    preloaded: tuple[str, str] | None = None) -> None:
        try:
            source_type = SourceType(spec.get("type", infer_source_type(path)))
            cred = spec.get("credibility")
            source = ingest_file(
                path,
                source_id=_next_id(),
                source_type=source_type,
                credibility=float(cred) if cred is not None else None,
                title=str(spec.get("title") or "") or None,
                published_at=(str(spec["published_at"])
                              if spec.get("published_at") else None),
                preloaded=preloaded,
            )
        except Exception as exc:  # 单文件坏，不炸全场
            dossier.ingest_notes.append({
                "file": rel, "kind": "parse_error",
                "detail": f"解析失败（{type(exc).__name__}: {exc}）——"
                          "该文件内容未进入研判",
            })
            return
        if not source.segments:
            detail = "未解析出任何文本"
            if source.meta.get("pdf_pages"):
                detail = (f"疑似扫描件/纯图 PDF（{source.meta['pdf_pages']} 页"
                          f"、{source.meta.get('pdf_images', 0)} 张图）——"
                          "文字层为空，图中数字可能缺失")
            dossier.ingest_notes.append(
                {"file": rel, "kind": "empty", "detail": detail})
            return  # 零段落信源不入卷（已披露）
        if source.meta.get("pdf_images"):
            dossier.ingest_notes.append({
                "file": rel, "kind": "images",
                "detail": f"含 {source.meta['pdf_images']} 张内嵌图片未解析"
                          "——图中的数字与结论可能缺失",
            })
        classification = str(spec.get("classification") or "internal").lower()
        if classification in ("public", "internal", "confidential"):
            source.classification = classification
        dossier.add_source(source)

    def _handle_links(rel: str, text: str, n_links: int) -> None:
        """链接清单：默认只披露；fetch_links=True 才逐条抓取并披露成败。"""
        if not fetch_links:
            dossier.ingest_notes.append({
                "file": rel, "kind": "links",
                "detail": f"链接清单：含 {n_links} 条网页链接未抓取"
                          "（网络抓取默认关闭，--fetch-links / "
                          "VERITAS_FETCH_LINKS=1 开启）",
            })
            return
        from app.ingest.links import LinkFetchError, extract_urls, fetch_link_source

        n_ok = 0
        failures: list[str] = []
        for url in extract_urls(text):
            try:
                source = fetch_link_source(url)
                source.id = _next_id()
                dossier.add_source(source)
                n_ok += 1
            except LinkFetchError as exc:
                failures.append(f"{url}（{exc}）")
        detail = f"链接清单 {rel}：抓取成功 {n_ok} 条"
        if failures:
            sample = "；".join(failures[:3])
            detail += (f"，失败 {len(failures)} 条：{sample}"
                       + ("…" if len(failures) > 3 else ""))
        dossier.ingest_notes.append(
            {"file": rel, "kind": "links", "detail": detail})

    import tempfile

    def _process_file(path: Path, rel: str, spec: dict | None = None) -> None:
        """单个文件（顶层或压缩包条目）→ 信源或披露，与来源无关同一待遇。"""
        spec = spec or {}
        if path.suffix.lower() in _IMAGE_EXTS:
            dossier.ingest_notes.append({
                "file": rel, "kind": "image_file",
                "detail": "纯图片文件，未做 OCR——图中文字、数字与图表"
                          "信息未进入研判（如有需要请人工整理为文字材料）",
            })
            return
        fmt = sniff_format(path) if is_archive_file(path) else ""
        if fmt in ("7z", "rar"):
            dossier.ingest_notes.append({
                "file": rel, "kind": "archive",
                "detail": f"不支持的压缩格式 {fmt}——请解压后提供",
            })
            return
        if fmt in ("zip", "tar"):
            entries, notes = expand_archive(
                path, Path(tempfile.mkdtemp(prefix="veritas_unpack_")), label=rel)
            dossier.ingest_notes.extend(notes)
            for entry_path, entry_name in entries:
                entry_spec = declared_name.get(entry_name.rsplit("/", 1)[-1])
                # 溯源：信源来自哪个包的哪个条目
                _process_file(entry_path, f"{rel}::{entry_name}", entry_spec)
            return
        try:
            title, text = read_any(path)
        except Exception as exc:
            dossier.ingest_notes.append({
                "file": rel, "kind": "parse_error",
                "detail": f"解析失败（{type(exc).__name__}: {exc}）——"
                          "该文件内容未进入研判",
            })
            return
        is_links, n_links = classify_link_list(text)
        if is_links:
            _handle_links(rel, text, n_links)
            return
        _ingest_one(path, spec, rel, preloaded=(title, text))

    for path, rel in _collect_files(case_dir):
        _process_file(path, rel,
                      declared_rel.get(rel) or declared_name.get(path.name))
    return dossier
