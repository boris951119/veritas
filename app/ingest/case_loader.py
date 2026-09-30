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


def load_case(case_dir: Path) -> Dossier:
    """案例目录 → Dossier（manifest.yaml 用缩进自愈加载）。"""
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
        dossier.add_source(source)
    return dossier
