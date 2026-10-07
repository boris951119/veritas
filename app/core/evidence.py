"""证据链三级数据模型。

结论 → 证据 → 来源 三级溯源（榜单硬需求 2）：每条证据的 quote 是
从来源 Segment 逐字摘录的引文（由 citation_check 零 LLM 机械核对），
下钻终点是原文段落。相关/因果区分与证据等级（榜单加分项 1）做进
schema 字段，判定由智能体给出、展示与置信度加权由程序执行。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class SourceType(str, Enum):
    """信源类型（决定可信度先验）。"""

    PAPER = "paper"        # 同行评审文献
    PATENT = "patent"      # 专利
    REPORT = "report"      # 机构/官方报告
    NEWS = "news"          # 新闻报道
    NOTE = "note"          # 专家笔记 / 灰色文献
    WEB = "web"            # 网页 / 自媒体
    OTHER = "other"


# 信源可信度先验（0-1）：后续人工可在 manifest 里覆盖
SOURCE_CREDIBILITY_PRIOR: dict[SourceType, float] = {
    SourceType.PAPER: 0.85,
    SourceType.PATENT: 0.70,
    SourceType.REPORT: 0.70,
    SourceType.NEWS: 0.50,
    SourceType.NOTE: 0.40,
    SourceType.WEB: 0.30,
    SourceType.OTHER: 0.40,
}


class EvidenceLevel(str, Enum):
    """证据等级（榜单加分项：等级标注参与置信度加权）。"""

    A = "A"  # 同行评审 / 一手数据 / 多源一致
    B = "B"  # 单一正式研究或官方文件
    C = "C"  # 预印本 / 灰色文献 / 待核转述
    D = "D"  # 自媒体 / 无出处传闻


LEVEL_WEIGHT: dict[EvidenceLevel, float] = {
    EvidenceLevel.A: 1.0,
    EvidenceLevel.B: 0.8,
    EvidenceLevel.C: 0.55,
    EvidenceLevel.D: 0.3,
}


class RelationKind(str, Enum):
    """相关 vs 因果区分（榜单加分项）：因果证据加权高于单纯相关。"""

    CAUSATION = "causation"          # X 导致 Y（有机制/对照支撑）
    CORRELATION = "correlation"      # X 与 Y 共变（无因果论证）
    EXPERT_JUDGMENT = "expert_judgment"  # 领域专家判断


@dataclass
class Segment:
    """来源的最小可下钻单元（原文段落）。"""

    id: str
    source_id: str
    text: str
    locator: str = ""       # 下钻定位：页码 / 章节 / URL 锚点 / 行号
    index: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source_id": self.source_id, "text": self.text,
            "locator": self.locator, "index": self.index,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(id=str(d["id"]), source_id=str(d["source_id"]),
                   text=str(d.get("text", "")), locator=str(d.get("locator", "")),
                   index=int(d.get("index", 0)))


@dataclass
class Source:
    """信源：一份文献 / 专利 / 网页，含可信度与全部段落。"""

    id: str
    title: str
    source_type: SourceType
    credibility: float          # 0-1，可被人工修改后重算
    url: str = ""
    meta: dict = field(default_factory=dict)
    segments: list[Segment] = field(default_factory=list)
    # 密级（public < internal < confidential）：权限视图按此过滤，
    # 审计链与原始案卷永远全量保真——过滤只发生在展示视图上
    classification: str = "internal"
    # 相关性人工裁决（""=自动 / "include"=强制纳入 / "exclude"=强制排除）：
    # 机械分层可能错杀同义表述，人是最高权限，裁决入链可审计
    relevance_override: str = ""

    @classmethod
    def create(cls, title: str, source_type: SourceType,
               credibility: float | None = None, **kw) -> "Source":
        cred = SOURCE_CREDIBILITY_PRIOR[source_type] if credibility is None else credibility
        if not 0.0 <= cred <= 1.0:
            raise ValueError(f"credibility 必须落在 [0,1]: {cred!r}")
        return cls(id=kw.pop("id", None) or _new_id("SRC"), title=title,
                   source_type=source_type, credibility=cred, **kw)

    def segment_by_id(self, segment_id: str) -> Segment | None:
        return next((s for s in self.segments if s.id == segment_id), None)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title,
            "source_type": self.source_type.value,
            "credibility": self.credibility, "url": self.url,
            "meta": self.meta,
            "classification": self.classification,
            "relevance_override": self.relevance_override,
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        return cls(
            id=str(d["id"]), title=str(d.get("title", "")),
            source_type=SourceType(d.get("source_type", "other")),
            credibility=float(d.get("credibility", 0.4)),
            url=str(d.get("url", "")), meta=dict(d.get("meta") or {}),
            classification=str(d.get("classification", "internal")),
            relevance_override=str(d.get("relevance_override", "")),
            segments=[Segment.from_dict(s) for s in d.get("segments") or []],
        )


@dataclass
class EvidenceNode:
    """证据：一条逐字引文 + 所指出处段落 + 关系/等级标注。"""

    id: str
    conclusion_id: str
    quote: str                    # 逐字引文（须在所指 Segment 中机械命中）
    segment_ids: list[str]
    relation: RelationKind = RelationKind.CORRELATION
    level: EvidenceLevel = EvidenceLevel.C
    note: str = ""
    weight: float = 1.0           # 人工可调权重（修改后触发重算）
    author: str = ""              # 产出该证据的智能体
    verified: bool | None = None  # 引文核对结果（audit 时回填）

    @classmethod
    def create(cls, conclusion_id: str, quote: str, segment_ids: list[str], **kw) -> "EvidenceNode":
        return cls(id=kw.pop("id", None) or _new_id("EV"), conclusion_id=conclusion_id,
                   quote=quote, segment_ids=list(segment_ids), **kw)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "conclusion_id": self.conclusion_id, "quote": self.quote,
            "segment_ids": self.segment_ids, "relation": self.relation.value,
            "level": self.level.value, "note": self.note, "weight": self.weight,
            "author": self.author, "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvidenceNode":
        return cls(
            id=str(d["id"]), conclusion_id=str(d["conclusion_id"]),
            quote=str(d.get("quote", "")),
            segment_ids=[str(x) for x in d.get("segment_ids") or []],
            relation=RelationKind(d.get("relation", "correlation")),
            level=EvidenceLevel(d.get("level", "C")),
            note=str(d.get("note", "")), weight=float(d.get("weight", 1.0)),
            author=str(d.get("author", "")), verified=d.get("verified"),
        )


@dataclass
class Conclusion:
    """结论：由某个研判智能体产出，挂证据链、置信度与少数意见。

    status 状态机：
    - majority 默认态（独立结论或归并/仲裁后的多数结论）；
    - dissent  少数意见：仲裁落败但按榜单要求保留，不参与主表置信度排序；
    - merged   已并入归并组，仅作溯源保留（其证据已转挂到组结论）。
    """

    id: str
    statement: str
    author: str = ""                       # 产出智能体名（单人）
    authors: list[str] = field(default_factory=list)  # 归并组的全体署名
    group_id: str = ""                     # 作为归并组成员时指向组结论（溯源/守恒闸用）
    status: str = "majority"
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0                # 0-1（confidence 融合后回填）
    confidence_parts: dict = field(default_factory=dict)  # 分量解释
    dissent: list[dict] = field(default_factory=list)     # 少数意见记录

    @classmethod
    def create(cls, statement: str, author: str = "", **kw) -> "Conclusion":
        return cls(id=kw.pop("id", None) or _new_id("CON"), statement=statement,
                   author=author, **kw)

    def author_names(self) -> list[str]:
        """该结论的全部署名（归并组看 authors，单人看 author）。"""
        return self.authors or ([self.author] if self.author else [])

    def to_dict(self) -> dict:
        return {
            "id": self.id, "statement": self.statement, "author": self.author,
            "authors": self.authors, "group_id": self.group_id,
            "status": self.status,
            "evidence_ids": self.evidence_ids, "confidence": self.confidence,
            "confidence_parts": self.confidence_parts, "dissent": self.dissent,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Conclusion":
        return cls(
            id=str(d["id"]), statement=str(d.get("statement", "")),
            author=str(d.get("author", "")),
            authors=[str(a) for a in d.get("authors") or []],
            group_id=str(d.get("group_id", "")),
            status=str(d.get("status", "majority")),
            evidence_ids=[str(x) for x in d.get("evidence_ids") or []],
            confidence=float(d.get("confidence", 0.0)),
            confidence_parts=dict(d.get("confidence_parts") or {}),
            dissent=list(d.get("dissent") or []),
        )


@dataclass
class Dossier:
    """研判案卷：一次研判任务的全部来源、证据、结论与冲突记录。"""

    question: str
    sources: list[Source] = field(default_factory=list)
    evidences: list[EvidenceNode] = field(default_factory=list)
    conclusions: list[Conclusion] = field(default_factory=list)
    title: str = ""
    # 冲突对与消解记录（ConflictPair.to_dict，见 core/conflicts.py；
    # 存 dict 避免与 evidence 模块互相 import 成环）
    conflicts: list[dict] = field(default_factory=list)
    panel: list[str] = field(default_factory=list)  # 参与研判的分析师名
    # 被引文核对打回的证据清单（EvidenceRef dict + problems；持久化供工作台展示）
    rejected: list[dict] = field(default_factory=list)
    # 摄取阶段披露：解析失败/空文件/扫描件/含图未解析（输入夹层「标」职能）
    ingest_notes: list[dict] = field(default_factory=list)
    # 输入分诊账本：每个文件（含压缩包条目）一条 {file, route, reason}——
    # 哪些进了研判、各自为什么，一页可审计（零相关/重复为派生视图另行披露）
    triage: list[dict] = field(default_factory=list)
    # 主席综合意见（agents/chair.py）：生产路径 LLM+闸，人工修改后模板重渲染
    synthesis: dict = field(default_factory=dict)
    # 本次研判耗时/token（工作台上屏；桩路径为 0）
    accounting: dict = field(default_factory=dict)

    # -- 索引 --

    def segment(self, segment_id: str) -> Segment | None:
        for src in self.sources:
            seg = src.segment_by_id(segment_id)
            if seg is not None:
                return seg
        return None

    def source_of_segment(self, segment_id: str) -> Source | None:
        for src in self.sources:
            if src.segment_by_id(segment_id) is not None:
                return src
        return None

    def evidence(self, evidence_id: str) -> EvidenceNode | None:
        return next((e for e in self.evidences if e.id == evidence_id), None)

    def conclusion(self, conclusion_id: str) -> Conclusion | None:
        return next((c for c in self.conclusions if c.id == conclusion_id), None)

    def statement_of(self, conclusion_id: str) -> str:
        """结论 id → 陈述文本（报告引用用；不存在返回占位）。"""
        con = self.conclusion(conclusion_id)
        return f"「{con.statement}」" if con else "（结论已不存在）"

    def evidences_of(self, conclusion_id: str) -> list[EvidenceNode]:
        return [e for e in self.evidences if e.conclusion_id == conclusion_id]

    # -- 变更（人工修改后重算的入口）--

    def add_source(self, source: Source) -> None:
        self.sources.append(source)

    def add_evidence(self, ev: EvidenceNode) -> None:
        self.evidences.append(ev)
        con = self.conclusion(ev.conclusion_id)
        if con is not None and ev.id not in con.evidence_ids:
            con.evidence_ids.append(ev.id)

    def remove_evidence(self, evidence_id: str) -> None:
        """删除证据（人工编辑 / 引文打回），并从结论挂载点摘除。"""
        self.evidences = [e for e in self.evidences if e.id != evidence_id]
        for con in self.conclusions:
            con.evidence_ids = [i for i in con.evidence_ids if i != evidence_id]

    # -- 序列化 --

    def to_dict(self) -> dict:
        return {
            "question": self.question, "title": self.title,
            "panel": self.panel,
            "sources": [s.to_dict() for s in self.sources],
            "evidences": [e.to_dict() for e in self.evidences],
            "conclusions": [c.to_dict() for c in self.conclusions],
            "conflicts": self.conflicts,
            "rejected": self.rejected,
            "ingest_notes": self.ingest_notes,
            "triage": self.triage,
            "synthesis": self.synthesis,
            "accounting": self.accounting,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Dossier":
        return cls(
            question=str(d.get("question", "")), title=str(d.get("title", "")),
            panel=[str(p) for p in d.get("panel") or []],
            sources=[Source.from_dict(s) for s in d.get("sources") or []],
            evidences=[EvidenceNode.from_dict(e) for e in d.get("evidences") or []],
            conclusions=[Conclusion.from_dict(c) for c in d.get("conclusions") or []],
            conflicts=list(d.get("conflicts") or []),
            rejected=list(d.get("rejected") or []),
            ingest_notes=list(d.get("ingest_notes") or []),
            triage=list(d.get("triage") or []),
            synthesis=dict(d.get("synthesis") or {}),
            accounting=dict(d.get("accounting") or {}),
        )

    def to_json(self, path: Path) -> Path:
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def from_json(cls, path: Path) -> "Dossier":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
