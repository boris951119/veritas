"""段 → Obsidian vault slice 笔记（frontmatter 定位字段 + 原文）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core.evidence import Dossier, Segment
from app.core.material import pack_material

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
