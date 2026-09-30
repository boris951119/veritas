"""事实对撞台账（零 LLM）：把「信源间数字打架」从运气变成机械检出。

分析师各自引证不同文档时，信源间的数字矛盾才会以结论冲突的形式
浮出来——分析师恰好没引到，矛盾就沉底。本模块把冲突检测下沉到
事实层：从全部段落机械抽取「实体 × 指标 × 数值 × 信源」四元组，
同一 (实体, 指标) 出现不可调和的不同数值 → 记入对撞台账。产物
两个去向：报告「资料内数字冲突」章节（分析师漏看也兜底）+ 分析师
提示词注入（「以下资料冲突必须在结论中回应」，给质证递靶子）。

抽取口径（宁勿错杀）：
- 指标 = 数字前紧邻的中文词串（≤8 字，剥「的/约/近/超/达/至/为」）；
- 实体 = 指标前紧邻的中文/字母数字词串（≤8 字，如「客户B」），可空；
- 跳过年份、序数、计数量词与空指标；
- 数值按万/亿缩放后 1% 容差比对，同值不撞；
- 同信源自相矛盾也记（标注），跨信源对撞是主场景。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.evidence import Dossier
from app.core.numeric_check import _close, extract_nums

_ENTITY_METRIC = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]{2,10}?)([\u4e00-\u9fff]{2,8})$")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
# 指标尾部的连接/模糊词，剥掉后才是干净指标名
_METRIC_FILLER = "的约近超达至为了将已"
# 条款/编号引用（合同第3.1条、第2期）不是经营事实
_CLAUSE_TAIL = "条款章节项期号页行"
# 停用词：伪实体（连接/指代词）与伪指标（动词/范围词）——台账宁缺毋滥
_ENTITY_STOP = {
    "该", "其", "本", "其中", "截至", "目前", "当前", "预计", "另外",
    "对应", "相关", "根据", "按照", "要求", "情况", "此外", "同时",
    "以及", "并且", "但是", "然而", "因此", "由于", "通过", "经过",
    "关于", "对于", "需求", "双方", "各方", "上述", "如下", "以下",
    "以上", "累计已", "合计已",
}
_METRIC_STOP = {
    "涉及", "超过", "不足", "达到", "约为", "以上", "以下", "之间",
    "前后", "左右", "其中", "以及", "出现", "存在", "发生", "进行",
}


@dataclass
class Fact:
    """一条机械抽出的事实：某信源说（实体, 指标）= 数值。"""

    entity: str
    metric: str
    value: float          # 缩放后数值（万/亿已乘级，% 已除百）
    raw: str              # 原文数字切片（含单位）
    source_id: str
    seg_id: str
    date: str             # 信源时点（meta.published_at/year，可空）


@dataclass
class Collision:
    """一次对撞：同 (实体, 指标) 下不可调和的多值。"""

    entity: str
    metric: str
    facts: list[Fact]

    @property
    def cross_source(self) -> bool:
        return len({f.source_id for f in self.facts}) > 1


def extract_facts(dossier: Dossier) -> list[Fact]:
    """全部段落 → 事实清单（顺序稳定：信源序 × 段序 × 数字序）。"""
    facts: list[Fact] = []
    for src in dossier.sources:
        date = str(src.meta.get("published_at") or src.meta.get("year") or "")
        for seg in src.segments:
            text = seg.text
            for num in extract_nums(text):
                if _YEAR_RE.fullmatch(num.raw) or _YEAR_RE.fullmatch(num.raw.rstrip("年")):
                    continue  # 年份不是经营事实
                after = text[num.end: num.end + 1]
                if after and after in _CLAUSE_TAIL:
                    continue  # 条款/页码/期号引用
                if num.start > 0 and text[num.start - 1] == "第":
                    continue  # 序数（第3.1条/第2期）
                head = text[: num.start]
                m = _ENTITY_METRIC.search(head)
                if not m:
                    continue  # 没有指标词的裸数（计数量词等）不进台账
                raw_entity, raw_metric = m.group(1), m.group(2)
                if raw_entity and not any(c.isascii() and c.isalnum()
                                          for c in raw_entity):
                    # 纯中文「实体」与指标的分界本就任意（非结构化数据≠实体
                    # 非结+指标构化数据）：并入指标，避免拦腰截断
                    metric = raw_entity + raw_metric
                    entity = ""
                else:
                    entity, metric = raw_entity, raw_metric
                metric = metric.rstrip(_METRIC_FILLER)
                while entity and entity[-1] in _METRIC_FILLER:
                    entity = entity[:-1]
                if len(metric) < 2 or metric in _METRIC_STOP:
                    continue
                if entity and entity in _ENTITY_STOP:
                    continue
                facts.append(Fact(
                    entity=entity, metric=metric, value=num.scaled,
                    raw=num.raw, source_id=src.id, seg_id=seg.id, date=date))
    return facts


def find_collisions(dossier: Dossier) -> list[Collision]:
    """同 (实体小写, 指标) 下数值不可调和（>1% 容差）→ 对撞清单。"""
    groups: dict[tuple[str, str], list[Fact]] = {}
    for f in extract_facts(dossier):
        groups.setdefault((f.entity.lower(), f.metric), []).append(f)
    out: list[Collision] = []
    for (entity, metric), fs in groups.items():
        distinct: list[Fact] = []
        for f in fs:
            if not any(_close(f.value, kept.value) for kept in distinct):
                distinct.append(f)
        if len(distinct) >= 2:
            out.append(Collision(entity=fs[0].entity, metric=metric,
                                 facts=sorted(fs, key=lambda x: (x.source_id, x.seg_id))))
    out.sort(key=lambda c: (not c.cross_source, c.entity, c.metric))
    return out


def facts_block(dossier: Dossier) -> str:
    """对撞台账 → 分析师提示词注入块（无对撞返回空串）。"""
    collisions = find_collisions(dossier)
    if not collisions:
        return ""
    lines = ["", "资料内已知数字冲突（下列数值互相矛盾，你的结论必须正面回应："
             "采信哪一方、依据什么，或声明资料不足）："]
    for c in collisions[:8]:
        detail = "；".join(
            f"{f.source_id}说{f.entity}{f.metric}{f.raw}"
            + (f"（时点 {f.date}）" if f.date else "")
            for f in c.facts)
        lines.append(f"- {c.entity or '（未指明主体）'}·{c.metric}：{detail}")
    return "\n".join(lines) + "\n"
