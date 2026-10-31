"""段 → Obsidian vault slice 笔记（frontmatter 定位字段 + 原文）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.evidence import Dossier, Segment
from app.core.material import pack_material
from app.ingest.official_case import load_official_case
from app.kg_lab.config import SLICES_DIR, VAULT_ROOT

_SAFE = re.compile(r"[^\w.\-]+", re.UNICODE)


def safe_name(doc_id: str, para_id: str) -> str:
    a = _SAFE.sub("_", doc_id.strip()) or "doc"
    b = _SAFE.sub("_", para_id.strip()) or "para"
    return f"{a}__{b}"


def segment_map(dossier: Dossier) -> dict[str, Segment]:
    out: dict[str, Segment] = {}
    for src in dossier.sources:
        for seg in src.segments:
            out[str(seg.id)] = seg
    return out


def pack_selected_for_question(dossier: Dossier, question: str) -> set[str]:
    dossier.question = (question or "").strip()
    pack = pack_material(dossier)
    return {str(x) for x in (pack.get("selected") or [])}


def questions_from_conclusions(case_dir: Path) -> list[dict[str, str]]:
    conc = json.loads((case_dir / "conclusions.json").read_text(encoding="utf-8"))
    seen: dict[str, str] = {}
    for row in conc:
        qid = str(row.get("question_id") or "").strip()
        q = str(row.get("question") or "").strip()
        if qid and q and qid not in seen:
            seen[qid] = q
    return [{"question_id": k, "question": v} for k, v in sorted(seen.items())]


def write_slice(
    *,
    case_slug: str,
    doc_id: str,
    para_id: str,
    text: str,
    title: str = "",
    out_dir: Path | None = None,
) -> Path:
    root = out_dir or (SLICES_DIR / case_slug)
    root.mkdir(parents=True, exist_ok=True)
    name = safe_name(doc_id, para_id)
    path = root / f"{name}.md"
    # YAML frontmatter：定位字段；正文＝原文
    fm = (
        f"---\n"
        f"type: slice\n"
        f"case: {json.dumps(case_slug, ensure_ascii=False)}\n"
        f"doc_id: {json.dumps(doc_id, ensure_ascii=False)}\n"
        f"para_id: {json.dumps(para_id, ensure_ascii=False)}\n"
        f"title: {json.dumps(title or doc_id, ensure_ascii=False)}\n"
        f"---\n\n"
    )
    path.write_text(fm + (text or "") + "\n", encoding="utf-8")
    return path


def ingest_case_slices(
    case_dir: Path,
    *,
    only_para_ids: set[str] | None = None,
    case_slug: str | None = None,
) -> dict[str, Any]:
    """写 slice 笔记；only_para_ids 非空时只写箱内段。"""
    slug = case_slug or case_dir.name
    dossier = load_official_case(case_dir)
    written: list[dict[str, str]] = []
    skipped = 0
    for src in dossier.sources:
        doc_id = str(src.id)
        title = str(src.title or doc_id)
        for seg in src.segments:
            pid = str(seg.id)
            if only_para_ids is not None and pid not in only_para_ids:
                skipped += 1
                continue
            path = write_slice(
                case_slug=slug, doc_id=doc_id, para_id=pid,
                text=seg.text or "", title=title,
            )
            written.append({
                "doc_id": doc_id,
                "para_id": pid,
                "path": str(path.relative_to(VAULT_ROOT)),
                "n_chars": len(seg.text or ""),
            })
    meta = {
        "case": slug,
        "case_dir": str(case_dir),
        "n_written": len(written),
        "n_skipped_outside_box": skipped,
        "slices": written,
    }
    out = SLICES_DIR / slug / "_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def union_pack_ids(case_dir: Path) -> tuple[Dossier, set[str], list[dict[str, str]]]:
    """该案所有议题的进箱并集（召回宇宙上限）。"""
    dossier = load_official_case(case_dir)
    qs = questions_from_conclusions(case_dir)
    union: set[str] = set()
    for row in qs:
        union |= pack_selected_for_question(dossier, row["question"])
    return dossier, union, qs
