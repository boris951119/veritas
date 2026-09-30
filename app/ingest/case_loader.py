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


def infer_source_type(path: Path) -> SourceType:
    name = path.name.lower()
    for kw, stype in _KEYWORD_HINTS:
        if kw in name:
            return stype
    return _EXT_HINTS.get(path.suffix.lower(), SourceType.OTHER)


def ingest_file(path: Path, source_id: str, source_type: SourceType,
                credibility: float | None = None, title: str | None = None,
                published_at: str | None = None) -> Source:
    """单文件 → Source（切段并编号，locator 记段序）。"""
    real_title, text = read_any(path)
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


def load_case(case_dir: Path) -> Dossier:
    """案例目录 → Dossier（manifest.yaml 用缩进自愈加载）。

    摄取按文件隔离：单个损坏/加密文件只降级为 ingest_notes 披露，
    绝不炸整条 run——「我们假定输入是敌意的」的第一原则。"""
    case_dir = Path(case_dir)
    manifest = {}
    manifest_path = case_dir / "manifest.yaml"
    if manifest_path.is_file():
        manifest = load_yaml_robust(manifest_path)

    dossier = Dossier(
        question=str(manifest.get("question") or case_dir.name),
        title=str(manifest.get("title") or case_dir.name),
    )

    declared: dict[str, dict] = {}
    for item in manifest.get("sources") or []:
        if isinstance(item, dict) and item.get("file"):
            declared[str(item["file"])] = item

    files = sorted(
        p for p in case_dir.iterdir()
        if p.is_file() and p.name != "manifest.yaml"
    )
    for i, path in enumerate(files):
        spec = declared.get(path.name, {})
        try:
            source_type = SourceType(spec.get("type", infer_source_type(path)))
            cred = spec.get("credibility")
            source = ingest_file(
                path,
                source_id=f"SRC{i + 1}",
                source_type=source_type,
                credibility=float(cred) if cred is not None else None,
                title=str(spec.get("title") or "") or None,
                published_at=(str(spec["published_at"])
                              if spec.get("published_at") else None),
            )
        except Exception as exc:  # 单文件坏，不炸全场
            dossier.ingest_notes.append({
                "file": path.name, "kind": "parse_error",
                "detail": f"解析失败（{type(exc).__name__}: {exc}）——"
                          "该文件内容未进入研判",
            })
            continue
        if not source.segments:
            detail = "未解析出任何文本"
            if source.meta.get("pdf_pages"):
                detail = (f"疑似扫描件/纯图 PDF（{source.meta['pdf_pages']} 页"
                          f"、{source.meta.get('pdf_images', 0)} 张图）——"
                          "文字层为空，图中数字可能缺失")
            dossier.ingest_notes.append(
                {"file": path.name, "kind": "empty", "detail": detail})
            continue  # 零段落信源不入卷（已披露），不进提示词噪声
        elif source.meta.get("pdf_images"):
            dossier.ingest_notes.append({
                "file": path.name, "kind": "images",
                "detail": f"含 {source.meta['pdf_images']} 张内嵌图片未解析"
                          "——图中的数字与结论可能缺失",
            })
        classification = str(spec.get("classification") or "internal").lower()
        if classification in ("public", "internal", "confidential"):
            source.classification = classification
        dossier.add_source(source)
    return dossier
