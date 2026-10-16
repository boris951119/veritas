"""官方样例集适配：raw_documents.json → 案卷。

不走 case_loader 的纯文本分支（那会把整份 JSON 当一篇信源）。
段 id 逐字等于官方 para_id，段文本等于 content[char_start:char_end]。
不二次切段，不重编号。＜5 字的段不进案卷（因而进不了检索），只记条数。
source_credibility 只挂在信源上，不参与检索排序或过滤。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app.core.evidence import Dossier, Segment, Source, SourceType

MIN_PARA_CHARS = 5
_FULL_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$")


def publish_time_or_blank(raw) -> str:
    """完整 ISO 日期原样保留；空、相对时间、站名、残缺年月一律空串。不推断。"""
    text = str(raw or "").strip()
    if not text or not _FULL_ISO_DATE.match(text):
        return ""
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return text


def load_question_list(path: Path) -> list[dict]:
    """问题清单：只取 question_id 与 question。其余键丢弃。

    评测时官方给的是问题清单；自测若要从结论样例抽题，须在研判之外
    先落成这份清单。本函数不打开样例答案文件。
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("问题清单须为 JSON 数组")
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("问题清单项须为对象")
        qid = str(item.get("question_id") or "").strip()
        question = str(item.get("question") or "").strip()
        if not qid or not question:
            raise ValueError("问题清单项须含 question_id 与 question")
        out.append({"question_id": qid, "question": question})
    if not out:
        raise ValueError("问题清单为空")
    return out


def load_official_case(case_dir: Path) -> Dossier:
    """读 case_dir/raw_documents.json，返回尚未填议题的案卷。"""
    path = Path(case_dir) / "raw_documents.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("raw_documents.json 须为文档数组")

    dossier = Dossier(question="", title=Path(case_dir).name)
    n_short = 0
    n_bad_time = 0
    for doc in data:
        if not isinstance(doc, dict):
            continue
        doc_id = str(doc.get("doc_id") or "").strip()
        if not doc_id:
            dossier.ingest_notes.append({
                "file": "raw_documents.json",
                "kind": "official_doc_skipped",
                "detail": "缺少 doc_id，该篇未入卷",
            })
            continue
        content = str(doc.get("content") or "")
        kept: list[Segment] = []
        for para in doc.get("paragraphs") or []:
            if not isinstance(para, dict) or "para_id" not in para:
                continue
            para_id = str(para["para_id"])
            start = int(para.get("char_start") or 0)
            end = int(para.get("char_end") or 0)
            text = content[start:end]
            if len(text) < MIN_PARA_CHARS:
                n_short += 1
                continue
            kept.append(Segment(
                id=para_id, source_id=doc_id, text=text, index=len(kept),
                locator=para_id,
            ))
        published = publish_time_or_blank(doc.get("publish_time"))
        if not published:
            n_bad_time += 1
        cred = doc.get("source_credibility")
        credibility = cred if isinstance(cred, (int, float)) and not isinstance(cred, bool) else None
        if credibility is None or not 0.0 <= float(credibility) <= 1.0:
            credibility = None
        source = Source.create(
            str(doc.get("title") or doc_id),
            SourceType.WEB,
            credibility=None if credibility is None else float(credibility),
            id=doc_id,
            url=str(doc.get("content_url") or ""),
            meta={
                "doc_id": doc_id,
                "publish_time": published,
                "source_credibility": cred,
                "official": True,
            },
        )
        source.segments = kept
        dossier.add_source(source)

    dossier.ingest_notes.append({
        "file": "raw_documents.json",
        "kind": "official_short_paragraph",
        "detail": f"不足 {MIN_PARA_CHARS} 字的段落未进检索：{n_short} 条（para_id 未重编号）",
        "filtered": n_short,
    })
    dossier.ingest_notes.append({
        "file": "raw_documents.json",
        "kind": "official_publish_time",
        "detail": f"publish_time 无法作为完整日期使用、已留空：{n_bad_time} 篇（未推断日期）",
        "unparsed": n_bad_time,
    })
    return dossier
