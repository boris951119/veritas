"""语料索引与两阶段选料（刀1/刀2/限额扩窗）。

默认阈值 50：信源数达到才收窄；未达则整卷研判。设为 0 强制关闭。
达到阈值时管线才建索引并 hydrate 成小案卷。本模块不声称已能扛十万份：

- 本模块是内存索引，段文本在进程里；
- 磁盘版见 corpus_store：逐份写入 SQLite，研判只读选中段；
- 百万段集群与金标 Recall 仍未做。

选料约束（对应方案复查）：
- 类型保底：report/paper/patent 先占席，避免谣言刷分挤掉官方；
- 议题实体命中标题或主体的信源强制入候选；
- 父节扩窗只发生在有层次标题的节内，且不超过预算的 30%；
- 无标题前言不扩窗；
- 切段版本不符拒绝加载旧索引；删除走墓碑。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.core.bm25 import _B, _K1, _tokens, expand_query, fuse_rankings
from app.core.dup_check import lsh_near_dup_pairs
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.premise_check import extract_entities
from app.ingest.segment import SEGMENTER_VERSION, is_section_heading

PROTECTED_TYPES = frozenset({
    SourceType.REPORT.value,
    SourceType.PAPER.value,
    SourceType.PATENT.value,
})
EXPAND_FRACTION = 0.30
_MAX_SOURCES = 50
_HITS_PER_SOURCE = 6


class CorpusIndexError(ValueError):
    """索引不可用（版本不符、租户不符、快照损坏）。"""


@dataclass
class _Seg:
    id: str
    source_id: str
    text: str
    locator: str
    index: int
    section: str
    dl: int


@dataclass
class _Src:
    id: str
    title: str
    source_type: str
    credibility: float
    url: str
    classification: str
    path: str
    content_hash: str
    published_at: str
    subjects: list[str]
    meta: dict
    tombstoned: bool = False


@dataclass
class SelectResult:
    dossier: Dossier
    disclosure: dict


@dataclass
class CorpusIndex:
    """单项目段级索引。一个实例只服务一个 project_id。"""

    project_id: str = "default"
    segmenter_version: str = SEGMENTER_VERSION
    sources: dict[str, _Src] = field(default_factory=dict)
    segments: dict[str, _Seg] = field(default_factory=dict)
    _postings: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    _df: dict[str, int] = field(default_factory=dict)
    _dl_sum: int = 0

    def upsert_source(self, source: Source, *,
                      path: str = "",
                      published_at: str = "",
                      subjects: list[str] | None = None) -> None:
        """增量写入一份信源。同 id 先摘掉旧段再写入（不重切其他信源）。"""
        self._drop_source(source.id)
        subjects = [str(s) for s in (subjects or []) if str(s).strip()]
        body = "\n".join(seg.text for seg in source.segments)
        section = ""
        for seg in source.segments:
            first = (seg.text.splitlines() or [""])[0]
            if is_section_heading(first):
                section = first.strip()[:80]
            toks = _tokens(seg.text)
            rec = _Seg(
                id=seg.id, source_id=source.id, text=seg.text,
                locator=seg.locator, index=seg.index, section=section,
                dl=len(toks),
            )
            self.segments[seg.id] = rec
            self._add_posting(seg.id, toks)
        self.sources[source.id] = _Src(
            id=source.id, title=source.title,
            source_type=source.source_type.value,
            credibility=source.credibility, url=source.url,
            classification=source.classification, path=path,
            content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            published_at=(published_at or "").strip(),
            subjects=subjects,
            meta=dict(source.meta or {}),
        )

    def tombstone(self, source_id: str) -> None:
        """删除信源：段与倒排摘除，留下墓碑，避免旧 id 复活。"""
        self._drop_source(source_id)
        src = self.sources.get(source_id)
        if src is None:
            self.sources[source_id] = _Src(
                id=source_id, title="", source_type="other", credibility=0.0,
                url="", classification="internal", path="", content_hash="",
                published_at="", subjects=[], meta={}, tombstoned=True,
            )
        else:
            src.tombstoned = True
            src.content_hash = ""

    def _search_terms(self, qtext: str) -> list[tuple[str, float]]:
        n_docs = len(self.segments)
        if n_docs == 0:
            return []
        avgdl = self._dl_sum / n_docs if n_docs else 1.0
        if avgdl <= 0:
            avgdl = 1.0
        q_terms = set(_tokens(qtext))
        scores: dict[str, float] = defaultdict(float)
        for term in q_terms:
            plist = self._postings.get(term)
            if not plist:
                continue
            df = self._df.get(term, 0)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            for seg_id, freq in plist:
                seg = self.segments.get(seg_id)
                if seg is None:
                    continue
                dl = seg.dl or 1
                scores[seg_id] += idf * freq * (_K1 + 1.0) / (
                    freq + _K1 * (1.0 - _B + _B * dl / avgdl))
        ranked = [(sid, round(sc, 6)) for sid, sc in scores.items()]
        ranked.sort(key=lambda x: (-x[1], x[0]))
        return ranked

    def search(self, question: str,
               queries: list[str] | None = None) -> list[tuple[str, float]]:
        """BM25 → [(seg_id, score)]。queries 多路时 RRF 融合。"""
        if queries:
            cleaned = [str(q).strip() for q in queries if str(q).strip()]
            if len(cleaned) > 1:
                return fuse_rankings([self._search_terms(q) for q in cleaned])
            if len(cleaned) == 1:
                return self._search_terms(cleaned[0])
        return self._search_terms(expand_query(question))

    def select(self, question: str, *,
               max_sources: int = _MAX_SOURCES,
               material_budget: int = 80_000,
               protected_slots: int = 8,
               queries: list[str] | None = None) -> SelectResult:
        """两阶段选料 → 只含候选段（含限额父节）的案卷。"""
        max_sources = max(1, int(max_sources))
        budget = max(1, int(material_budget))
        hit_budget = max(1, int(budget * (1.0 - EXPAND_FRACTION)))
        expand_budget = max(0, budget - hit_budget)
        scores = dict(self.search(question, queries=queries))
        entities = extract_entities(question)
        live = [s for s in self.sources.values() if not s.tombstoned
                and any(seg.source_id == s.id for seg in self.segments.values())]

        def src_score(src: _Src) -> float:
            best = 0.0
            for seg in self.segments.values():
                if seg.source_id == src.id:
                    best = max(best, scores.get(seg.id, 0.0))
            return best

        ranked = sorted(live, key=lambda s: (-src_score(s), s.id))

        def matches_entity(src: _Src) -> bool:
            blob = src.title + "\n" + "\n".join(src.subjects)
            return any(ent and ent in blob for ent in entities)

        chosen: list[_Src] = []
        seen: set[str] = set()

        def take(src: _Src) -> None:
            if src.id in seen or len(chosen) >= max_sources:
                return
            seen.add(src.id)
            chosen.append(src)

        protected = [
            s for s in ranked
            if s.source_type in PROTECTED_TYPES
            and (src_score(s) > 0 or matches_entity(s))
        ]
        for src in protected[:min(protected_slots, max_sources)]:
            take(src)
        forced = [s for s in ranked if matches_entity(s)]
        for src in forced:
            take(src)
        for src in ranked:
            take(src)

        by_source_hits: dict[str, list[_Seg]] = defaultdict(list)
        for seg in self.segments.values():
            if seg.source_id in seen and scores.get(seg.id, 0.0) > 0:
                by_source_hits[seg.source_id].append(seg)
        for sid in by_source_hits:
            by_source_hits[sid].sort(
                key=lambda g: (-scores.get(g.id, 0.0), g.index, g.id))

        selected: list[_Seg] = []
        selected_ids: set[str] = set()
        used_hits = 0
        for src in chosen:
            hits = by_source_hits.get(src.id) or []
            if not hits:
                # 保底席即使 BM25 为 0，也钉该源第一段，避免「占席但无正文」
                own = [g for g in self.segments.values() if g.source_id == src.id]
                own.sort(key=lambda g: (g.index, g.id))
                hits = own[:1]
            for seg in hits[:_HITS_PER_SOURCE]:
                if seg.id in selected_ids:
                    continue
                if used_hits + len(seg.text) > hit_budget:
                    continue
                selected.append(seg)
                selected_ids.add(seg.id)
                used_hits += len(seg.text)

        expanded = 0
        used_expand = 0
        # 先钉命中段，再按节扩。无标题（section 空）不扩。
        for seg in list(selected):
            if not seg.section:
                continue
            siblings = [
                g for g in self.segments.values()
                if g.source_id == seg.source_id and g.section == seg.section
                and g.id not in selected_ids
            ]
            siblings.sort(key=lambda g: (g.index, g.id))
            for sib in siblings:
                if used_expand + len(sib.text) > expand_budget:
                    continue
                selected.append(sib)
                selected_ids.add(sib.id)
                used_expand += len(sib.text)
                expanded += 1

        order = {src.id: i for i, src in enumerate(chosen)}
        selected.sort(key=lambda g: (order.get(g.source_id, 10**9), g.index, g.id))
        present = {g.source_id for g in selected}
        out_sources: list[Source] = []
        for src in chosen:
            if src.id not in present:
                continue
            segs = [g for g in selected if g.source_id == src.id]
            meta = dict(src.meta)
            meta["published_at"] = src.published_at
            meta["subjects"] = list(src.subjects)
            meta["content_hash"] = src.content_hash
            meta["time_labeled"] = bool(src.published_at)
            hydrated = Source(
                id=src.id, title=src.title,
                source_type=SourceType(src.source_type),
                credibility=src.credibility, url=src.url, meta=meta,
                classification=src.classification,
                segments=[Segment(
                    id=g.id, source_id=g.source_id, text=g.text,
                    locator=g.locator, index=g.index,
                ) for g in segs],
            )
            out_sources.append(hydrated)

        n_lib_seg = len(self.segments)
        disclosure = {
            "kind": "corpus_select",
            "project_id": self.project_id,
            "segmenter_version": self.segmenter_version,
            "n_library_sources": len(live),
            "n_library_segments": n_lib_seg,
            "n_selected_sources": len(out_sources),
            "n_selected_segments": len(selected),
            "n_expanded_segments": expanded,
            "max_sources": max_sources,
            "protected_ids": [s.id for s in chosen if s.source_type in PROTECTED_TYPES
                              and s.id in present],
            "entity_forced_ids": [s.id for s in forced if s.id in present],
            "omitted_sources": max(0, len(live) - len(out_sources)),
            "note": (f"库内 {len(live)} 份 / {n_lib_seg} 段，"
                     f"本次纳入 {len(out_sources)} 份 / {len(selected)} 段。"
                     "未入候选不等于已审完全库。"),
        }
        dossier = Dossier(question=question, sources=out_sources)
        dossier.accounting["corpus_select"] = disclosure
        dossier.ingest_notes.append({
            "file": "", "kind": "corpus_select", "detail": disclosure["note"],
        })
        return SelectResult(dossier=dossier, disclosure=disclosure)

    def near_duplicate_pairs(self) -> list[tuple[str, str, float]]:
        """库内近似同源（LSH）。无主体时的退路；不声称零漏报。"""
        items = []
        seen_hash: dict[str, str] = {}
        for src in self.sources.values():
            if src.tombstoned:
                continue
            if src.content_hash and src.content_hash in seen_hash:
                continue
            text = "\n".join(
                g.text for g in sorted(
                    (s for s in self.segments.values() if s.source_id == src.id),
                    key=lambda s: (s.index, s.id))
            )
            if src.content_hash:
                seen_hash[src.content_hash] = src.id
            items.append((src.id, text))
        return lsh_near_dup_pairs(items)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False),
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CorpusIndex":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "segmenter_version": self.segmenter_version,
            "sources": [
                {
                    "id": s.id, "title": s.title, "source_type": s.source_type,
                    "credibility": s.credibility, "url": s.url,
                    "classification": s.classification, "path": s.path,
                    "content_hash": s.content_hash,
                    "published_at": s.published_at, "subjects": s.subjects,
                    "meta": s.meta, "tombstoned": s.tombstoned,
                }
                for s in self.sources.values()
            ],
            "segments": [
                {
                    "id": g.id, "source_id": g.source_id, "text": g.text,
                    "locator": g.locator, "index": g.index, "section": g.section,
                }
                for g in self.segments.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CorpusIndex":
        version = str(data.get("segmenter_version") or "")
        if version != SEGMENTER_VERSION:
            raise CorpusIndexError(
                f"切段版本不符（索引 {version or '空'}，当前 {SEGMENTER_VERSION}），"
                "需重建索引")
        idx = cls(project_id=str(data.get("project_id") or "default"))
        src_meta = {str(s["id"]): s for s in data.get("sources") or []}
        grouped: dict[str, list] = defaultdict(list)
        for raw in data.get("segments") or []:
            grouped[str(raw["source_id"])].append(raw)
        for sid, raws in grouped.items():
            meta = src_meta.get(sid) or {}
            if meta.get("tombstoned"):
                continue
            raws.sort(key=lambda r: (int(r.get("index", 0)), str(r["id"])))
            source = Source(
                id=sid, title=str(meta.get("title") or ""),
                source_type=SourceType(str(meta.get("source_type") or "other")),
                credibility=float(meta.get("credibility") or 0.4),
                url=str(meta.get("url") or ""),
                meta=dict(meta.get("meta") or {}),
                classification=str(meta.get("classification") or "internal"),
                segments=[Segment(
                    id=str(r["id"]), source_id=sid, text=str(r.get("text") or ""),
                    locator=str(r.get("locator") or ""),
                    index=int(r.get("index") or 0),
                ) for r in raws],
            )
            idx.upsert_source(
                source, path=str(meta.get("path") or ""),
                published_at=str(meta.get("published_at") or ""),
                subjects=list(meta.get("subjects") or []),
            )
        for sid, meta in src_meta.items():
            if meta.get("tombstoned"):
                idx.tombstone(sid)
        return idx

    def _add_posting(self, seg_id: str, toks: list[str]) -> None:
        tf: dict[str, int] = defaultdict(int)
        for t in toks:
            tf[t] += 1
        self._dl_sum += len(toks)
        for term, freq in tf.items():
            self._postings.setdefault(term, []).append((seg_id, freq))
            self._df[term] = self._df.get(term, 0) + 1

    def _drop_source(self, source_id: str) -> None:
        gone = [sid for sid, seg in self.segments.items()
                if seg.source_id == source_id]
        if not gone:
            return
        drop = set(gone)
        for sid in gone:
            self._dl_sum -= self.segments[sid].dl
            del self.segments[sid]
        for term in list(self._postings):
            kept = [(s, f) for s, f in self._postings[term] if s not in drop]
            if kept:
                self._postings[term] = kept
                self._df[term] = len(kept)
            else:
                self._postings.pop(term, None)
                self._df.pop(term, None)


def narrow_dossier(dossier: Dossier, *,
                   project_id: str = "default",
                   max_sources: int = _MAX_SOURCES,
                   material_budget: int = 80_000,
                   queries: list[str] | None = None) -> Dossier:
    """把已装入的大案卷收成小案卷。摄取笔记与分诊账本保留。"""
    index = CorpusIndex(project_id=project_id)
    for src in dossier.sources:
        subjects = [str(s) for s in (src.meta.get("subjects") or [])]
        published = str(src.meta.get("published_at") or "")
        index.upsert_source(
            src, path=str(src.meta.get("file") or ""),
            published_at=published, subjects=subjects,
        )
    qinfo = (dossier.accounting or {}).get("query_rewrite") or {}
    use_q = queries or qinfo.get("queries")
    result = index.select(
        dossier.question, max_sources=max_sources,
        material_budget=material_budget, queries=use_q,
    )
    out = result.dossier
    out.title = dossier.title
    out.ingest_notes = list(dossier.ingest_notes) + list(out.ingest_notes)
    out.triage = list(dossier.triage)
    out.accounting = dict(dossier.accounting)
    out.accounting["corpus_select"] = result.disclosure
    return out
