"""磁盘语料库：逐份写入 SQLite，检索时只读命中段的正文。

和内存版 CorpusIndex 同一套选料规则（类型保底、实体入候选、
限额父节扩窗）。差别是段文本留在库文件里，案卷里只 hydrate
选中的段。默认研判不走这里；VERITAS_CORPUS_SELECT_MIN>0 才启用。

仍不是百万段集群索引：元数据与倒排在本机 SQLite，查询按词取
posting，不把全库正文装进研判案卷。
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

from app.core.bm25 import _B, _K1, _tokens, expand_query
from app.core.corpus_index import (
    EXPAND_FRACTION,
    PROTECTED_TYPES,
    SelectResult,
    _HITS_PER_SOURCE,
    _MAX_SOURCES,
)
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.premise_check import extract_entities
from app.ingest.segment import SEGMENTER_VERSION, is_section_heading

from app.core.corpus_index import CorpusIndexError


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    credibility REAL NOT NULL,
    url TEXT NOT NULL,
    classification TEXT NOT NULL,
    path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    published_at TEXT NOT NULL,
    subjects TEXT NOT NULL,
    meta TEXT NOT NULL,
    tombstoned INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    text TEXT NOT NULL,
    locator TEXT NOT NULL,
    idx INTEGER NOT NULL,
    section TEXT NOT NULL,
    dl INTEGER NOT NULL,
    nchars INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seg_src ON segments(source_id);
CREATE TABLE IF NOT EXISTS postings (
    term TEXT NOT NULL,
    seg_id TEXT NOT NULL,
    tf INTEGER NOT NULL,
    PRIMARY KEY (term, seg_id)
);
CREATE TABLE IF NOT EXISTS term_df (
    term TEXT PRIMARY KEY,
    df INTEGER NOT NULL
);
"""


class DiskCorpusIndex:
    """单项目 SQLite 索引。一个文件只服务一个 project_id。"""

    def __init__(self, conn: sqlite3.Connection, project_id: str):
        self._conn = conn
        self.project_id = project_id

    @classmethod
    def create(cls, path: Path, project_id: str = "default") -> "DiskCorpusIndex":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        conn = sqlite3.connect(path)
        conn.executescript(_SCHEMA)
        conn.execute("INSERT INTO meta(key, value) VALUES('project_id', ?)",
                     (project_id,))
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('segmenter_version', ?)",
            (SEGMENTER_VERSION,))
        conn.execute("INSERT INTO meta(key, value) VALUES('n_docs', '0')")
        conn.execute("INSERT INTO meta(key, value) VALUES('dl_sum', '0')")
        conn.commit()
        return cls(conn, project_id)

    @classmethod
    def open(cls, path: Path) -> "DiskCorpusIndex":
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT value FROM meta WHERE key='segmenter_version'").fetchone()
        version = row[0] if row else ""
        if version != SEGMENTER_VERSION:
            conn.close()
            raise CorpusIndexError(
                f"切段版本不符（索引 {version or '空'}，当前 {SEGMENTER_VERSION}），"
                "需重建索引")
        proj = conn.execute(
            "SELECT value FROM meta WHERE key='project_id'").fetchone()
        return cls(conn, proj[0] if proj else "default")

    def close(self) -> None:
        self._conn.close()

    def upsert_source(self, source: Source, *,
                      path: str = "",
                      published_at: str = "",
                      subjects: list[str] | None = None) -> None:
        self._drop_source(source.id)
        subjects = [str(s) for s in (subjects or []) if str(s).strip()]
        body_parts: list[str] = []
        section = ""
        n_docs = self._meta_int("n_docs")
        dl_sum = self._meta_int("dl_sum")
        for seg in source.segments:
            first = (seg.text.splitlines() or [""])[0]
            if is_section_heading(first):
                section = first.strip()[:80]
            toks = _tokens(seg.text)
            tf: dict[str, int] = defaultdict(int)
            for tok in toks:
                tf[tok] += 1
            self._conn.execute(
                "INSERT INTO segments(id, source_id, text, locator, idx, "
                "section, dl, nchars) VALUES(?,?,?,?,?,?,?,?)",
                (seg.id, source.id, seg.text, seg.locator, seg.index,
                 section, len(toks), len(seg.text)),
            )
            for term, freq in tf.items():
                self._conn.execute(
                    "INSERT INTO postings(term, seg_id, tf) VALUES(?,?,?)",
                    (term, seg.id, freq),
                )
                self._conn.execute(
                    "INSERT INTO term_df(term, df) VALUES(?, 1) "
                    "ON CONFLICT(term) DO UPDATE SET df = df + 1",
                    (term,),
                )
            n_docs += 1
            dl_sum += len(toks)
            body_parts.append(seg.text)
        digest = hashlib.sha256("\n".join(body_parts).encode("utf-8")).hexdigest()
        self._conn.execute(
            "INSERT OR REPLACE INTO sources("
            "id, title, source_type, credibility, url, classification, path, "
            "content_hash, published_at, subjects, meta, tombstoned"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
            (source.id, source.title, source.source_type.value,
             source.credibility, source.url, source.classification, path,
             digest, (published_at or "").strip(),
             json.dumps(subjects, ensure_ascii=False),
             json.dumps(source.meta or {}, ensure_ascii=False)),
        )
        self._set_meta("n_docs", n_docs)
        self._set_meta("dl_sum", dl_sum)
        self._conn.commit()

    def tombstone(self, source_id: str) -> None:
        self._drop_source(source_id)
        self._conn.execute(
            "INSERT INTO sources(id, title, source_type, credibility, url, "
            "classification, path, content_hash, published_at, subjects, meta, "
            "tombstoned) VALUES(?,?,?,?,?,?,?,?,?,?,?,1) "
            "ON CONFLICT(id) DO UPDATE SET tombstoned=1, content_hash=''",
            (source_id, "", "other", 0.0, "", "internal", "", "", "", "[]", "{}"),
        )
        self._conn.commit()

    def live_source_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM sources WHERE tombstoned=0 "
            "AND id IN (SELECT DISTINCT source_id FROM segments)").fetchone()
        return int(row[0])

    def search(self, question: str) -> list[tuple[str, float]]:
        n_docs = self._meta_int("n_docs")
        if n_docs <= 0:
            return []
        avgdl = self._meta_int("dl_sum") / n_docs or 1.0
        scores: dict[str, float] = defaultdict(float)
        for term in set(_tokens(expand_query(question))):
            df_row = self._conn.execute(
                "SELECT df FROM term_df WHERE term=?", (term,)).fetchone()
            if not df_row:
                continue
            df = int(df_row[0])
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            for seg_id, freq in self._conn.execute(
                    "SELECT seg_id, tf FROM postings WHERE term=?", (term,)):
                dl_row = self._conn.execute(
                    "SELECT dl FROM segments WHERE id=?", (seg_id,)).fetchone()
                dl = int(dl_row[0]) if dl_row and dl_row[0] else 1
                scores[seg_id] += idf * freq * (_K1 + 1.0) / (
                    freq + _K1 * (1.0 - _B + _B * dl / avgdl))
        ranked = [(sid, round(sc, 6)) for sid, sc in scores.items()]
        ranked.sort(key=lambda x: (-x[1], x[0]))
        return ranked

    def select(self, question: str, *,
               max_sources: int = _MAX_SOURCES,
               material_budget: int = 80_000,
               protected_slots: int = 8) -> SelectResult:
        max_sources = max(1, int(max_sources))
        budget = max(1, int(material_budget))
        hit_budget = max(1, int(budget * (1.0 - EXPAND_FRACTION)))
        expand_budget = max(0, budget - hit_budget)
        scores = dict(self.search(question))
        entities = extract_entities(question)
        live = self._live_sources()
        seg_owner = self._owners(list(scores))

        def src_score(src: dict) -> float:
            best = 0.0
            for seg_id, owner in seg_owner.items():
                if owner == src["id"]:
                    best = max(best, scores.get(seg_id, 0.0))
            return best

        ranked = sorted(live, key=lambda s: (-src_score(s), s["id"]))

        def matches_entity(src: dict) -> bool:
            blob = src["title"] + "\n" + "\n".join(src["subjects"])
            return any(ent and ent in blob for ent in entities)

        chosen: list[dict] = []
        seen: set[str] = set()

        def take(src: dict) -> None:
            if src["id"] in seen or len(chosen) >= max_sources:
                return
            seen.add(src["id"])
            chosen.append(src)

        protected = [
            s for s in ranked
            if s["source_type"] in PROTECTED_TYPES
            and (src_score(s) > 0 or matches_entity(s))
        ]
        for src in protected[:min(protected_slots, max_sources)]:
            take(src)
        forced = [s for s in ranked if matches_entity(s)]
        for src in forced:
            take(src)
        for src in ranked:
            take(src)

        selected_ids: list[str] = []
        selected_set: set[str] = set()
        used_hits = 0
        for src in chosen:
            hits = [
                (seg_id, scores[seg_id])
                for seg_id, owner in seg_owner.items()
                if owner == src["id"] and scores.get(seg_id, 0.0) > 0
            ]
            hits.sort(key=lambda x: (-x[1], x[0]))
            rows = []
            if hits:
                for seg_id, _sc in hits[:_HITS_PER_SOURCE]:
                    rows.append(self._seg_brief(seg_id))
            else:
                brief = self._first_brief(src["id"])
                if brief:
                    rows.append(brief)
            for brief in rows:
                if brief is None or brief["id"] in selected_set:
                    continue
                if used_hits + brief["nchars"] > hit_budget:
                    continue
                selected_ids.append(brief["id"])
                selected_set.add(brief["id"])
                used_hits += brief["nchars"]

        expanded = 0
        used_expand = 0
        for seg_id in list(selected_ids):
            brief = self._seg_brief(seg_id)
            if not brief or not brief["section"]:
                continue
            for sib in self._siblings(brief["source_id"], brief["section"]):
                if sib["id"] in selected_set:
                    continue
                if used_expand + sib["nchars"] > expand_budget:
                    continue
                selected_ids.append(sib["id"])
                selected_set.add(sib["id"])
                used_expand += sib["nchars"]
                expanded += 1

        texts = self._fetch_segments(selected_ids)
        order = {src["id"]: i for i, src in enumerate(chosen)}
        texts.sort(key=lambda g: (order.get(g["source_id"], 10**9), g["idx"], g["id"]))
        present = {g["source_id"] for g in texts}
        out_sources: list[Source] = []
        by_src: dict[str, list] = defaultdict(list)
        for g in texts:
            by_src[g["source_id"]].append(g)
        for src in chosen:
            if src["id"] not in present:
                continue
            meta = dict(src["meta"])
            meta["published_at"] = src["published_at"]
            meta["subjects"] = list(src["subjects"])
            meta["content_hash"] = src["content_hash"]
            meta["time_labeled"] = bool(src["published_at"])
            out_sources.append(Source(
                id=src["id"], title=src["title"],
                source_type=SourceType(src["source_type"]),
                credibility=src["credibility"], url=src["url"],
                meta=meta, classification=src["classification"],
                segments=[Segment(
                    id=g["id"], source_id=g["source_id"], text=g["text"],
                    locator=g["locator"], index=g["idx"],
                ) for g in by_src[src["id"]]],
            ))
        n_lib_seg = self._meta_int("n_docs")
        disclosure = {
            "kind": "corpus_select",
            "store": "sqlite",
            "project_id": self.project_id,
            "segmenter_version": SEGMENTER_VERSION,
            "n_library_sources": len(live),
            "n_library_segments": n_lib_seg,
            "n_selected_sources": len(out_sources),
            "n_selected_segments": len(texts),
            "n_expanded_segments": expanded,
            "max_sources": max_sources,
            "protected_ids": [s["id"] for s in chosen
                              if s["source_type"] in PROTECTED_TYPES
                              and s["id"] in present],
            "entity_forced_ids": [s["id"] for s in forced if s["id"] in present],
            "omitted_sources": max(0, len(live) - len(out_sources)),
            "note": (f"库内 {len(live)} 份 / {n_lib_seg} 段，"
                     f"本次纳入 {len(out_sources)} 份 / {len(texts)} 段。"
                     "未入候选不等于已审完全库。"),
        }
        dossier = Dossier(question=question, sources=out_sources)
        dossier.accounting["corpus_select"] = disclosure
        dossier.ingest_notes.append({
            "file": "", "kind": "corpus_select", "detail": disclosure["note"],
        })
        return SelectResult(dossier=dossier, disclosure=disclosure)

    def _drop_source(self, source_id: str) -> None:
        seg_ids = [row[0] for row in self._conn.execute(
            "SELECT id FROM segments WHERE source_id=?", (source_id,))]
        if not seg_ids:
            return
        n_docs = self._meta_int("n_docs")
        dl_sum = self._meta_int("dl_sum")
        for seg_id in seg_ids:
            dl = self._conn.execute(
                "SELECT dl FROM segments WHERE id=?", (seg_id,)).fetchone()
            dl_sum -= int(dl[0]) if dl else 0
            n_docs -= 1
            for term, in self._conn.execute(
                    "SELECT term FROM postings WHERE seg_id=?", (seg_id,)):
                self._conn.execute(
                    "UPDATE term_df SET df = df - 1 WHERE term=?", (term,))
            self._conn.execute("DELETE FROM postings WHERE seg_id=?", (seg_id,))
        self._conn.execute("DELETE FROM term_df WHERE df<=0")
        self._conn.execute("DELETE FROM segments WHERE source_id=?", (source_id,))
        self._set_meta("n_docs", max(0, n_docs))
        self._set_meta("dl_sum", max(0, dl_sum))

    def _live_sources(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, title, source_type, credibility, url, classification, "
            "path, content_hash, published_at, subjects, meta FROM sources "
            "WHERE tombstoned=0 AND id IN (SELECT DISTINCT source_id FROM segments)"
        ).fetchall()
        out = []
        for row in rows:
            out.append({
                "id": row[0], "title": row[1], "source_type": row[2],
                "credibility": row[3], "url": row[4], "classification": row[5],
                "path": row[6], "content_hash": row[7], "published_at": row[8],
                "subjects": json.loads(row[9] or "[]"),
                "meta": json.loads(row[10] or "{}"),
            })
        return out

    def _owners(self, seg_ids: list[str]) -> dict[str, str]:
        owners: dict[str, str] = {}
        for i in range(0, len(seg_ids), 400):
            chunk = seg_ids[i:i + 400]
            marks = ",".join("?" for _ in chunk)
            for seg_id, source_id in self._conn.execute(
                    f"SELECT id, source_id FROM segments WHERE id IN ({marks})",
                    chunk):
                owners[seg_id] = source_id
        return owners

    def _seg_brief(self, seg_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT id, source_id, idx, section, nchars FROM segments WHERE id=?",
            (seg_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "source_id": row[1], "idx": row[2],
                "section": row[3], "nchars": row[4]}

    def _first_brief(self, source_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT id, source_id, idx, section, nchars FROM segments "
            "WHERE source_id=? ORDER BY idx, id LIMIT 1",
            (source_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "source_id": row[1], "idx": row[2],
                "section": row[3], "nchars": row[4]}

    def _siblings(self, source_id: str, section: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, source_id, idx, section, nchars FROM segments "
            "WHERE source_id=? AND section=? ORDER BY idx, id",
            (source_id, section)).fetchall()
        return [{"id": r[0], "source_id": r[1], "idx": r[2],
                 "section": r[3], "nchars": r[4]} for r in rows]

    def _fetch_segments(self, seg_ids: list[str]) -> list[dict]:
        if not seg_ids:
            return []
        found: dict[str, dict] = {}
        for i in range(0, len(seg_ids), 400):
            chunk = seg_ids[i:i + 400]
            marks = ",".join("?" for _ in chunk)
            for row in self._conn.execute(
                    "SELECT id, source_id, text, locator, idx FROM segments "
                    f"WHERE id IN ({marks})", chunk):
                found[row[0]] = {
                    "id": row[0], "source_id": row[1], "text": row[2],
                    "locator": row[3], "idx": row[4],
                }
        return [found[sid] for sid in seg_ids if sid in found]

    def _meta_int(self, key: str) -> int:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return int(row[0]) if row else 0

    def _set_meta(self, key: str, value: int) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def index_case(case_dir: Path, db_path: Path, *,
               project_id: str = "default",
               fetch_links: bool = False,
               on_file=None) -> tuple[DiskCorpusIndex, Dossier]:
    """逐份入库。返回的 dossier 不含信源正文，只留议题、分诊和披露。"""
    from app.ingest.case_loader import load_case

    index = DiskCorpusIndex.create(db_path, project_id)

    def _sink(source: Source) -> None:
        meta = source.meta or {}
        subjects = [str(s) for s in (meta.get("subjects") or [])]
        index.upsert_source(
            source,
            path=str(meta.get("file") or ""),
            published_at=str(meta.get("published_at") or ""),
            subjects=subjects,
        )

    shell = load_case(case_dir, fetch_links=fetch_links, on_file=on_file,
                      source_sink=_sink)
    return index, shell


def dossier_from_case_index(case_dir: Path, *,
                            project_id: str,
                            min_sources: int,
                            material_budget: int,
                            fetch_links: bool = False,
                            on_file=None) -> Dossier:
    """建磁盘索引后：达到阈值就收窄，否则从库中取回全部段（与全量案卷同口径）。"""
    db_path = Path(case_dir) / ".corpus" / "index.sqlite"
    index, shell = index_case(
        case_dir, db_path, project_id=project_id,
        fetch_links=fetch_links, on_file=on_file,
    )
    try:
        if index.live_source_count() >= min_sources:
            result = index.select(
                shell.question, material_budget=material_budget)
            out = result.dossier
        else:
            out = _hydrate_all(index, shell.question)
        out.title = shell.title
        out.triage = list(shell.triage)
        out.ingest_notes = list(shell.ingest_notes) + [
            n for n in out.ingest_notes if n.get("kind") == "corpus_select"]
        if "corpus_select" in out.accounting:
            note = out.accounting["corpus_select"]
            out.accounting = {"corpus_select": note}
        return out
    finally:
        index.close()


def _hydrate_all(index: DiskCorpusIndex, question: str) -> Dossier:
    """未达收窄阈值：正文仍从库里读出，组成与全量摄取等价的案卷。"""
    sources = []
    for src in index._live_sources():
        rows = index._conn.execute(
            "SELECT id, text, locator, idx FROM segments WHERE source_id=? "
            "ORDER BY idx, id", (src["id"],)).fetchall()
        meta = dict(src["meta"])
        meta["published_at"] = src["published_at"]
        meta["subjects"] = list(src["subjects"])
        sources.append(Source(
            id=src["id"], title=src["title"],
            source_type=SourceType(src["source_type"]),
            credibility=src["credibility"], url=src["url"],
            classification=src["classification"], meta=meta,
            segments=[Segment(
                id=r[0], source_id=src["id"], text=r[1],
                locator=r[2], index=r[3],
            ) for r in rows],
        ))
    return Dossier(question=question, sources=sources)
