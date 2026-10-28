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
import statistics
from dataclasses import dataclass

from app.core.evidence import Dossier
from app.core.numeric_check import _close, extract_nums

# C-69：VERITAS_LEDGER_TIME_CLASS（默认关＝facts_block 文案与改前逐字相同）
_LEDGER_TIME_CLASS = False

# C-78：对撞行派生「组内相对偏差」标签（默认关＝报告渲染与改前逐字相同；
# 只呈现、不改 find_collisions／采信／提示词）。
_LEDGER_OUTLIER_TAG = False

# 对外统一口径＝只用本标签短语（不许改写成均值／σ 口径）。
DISPERSION_LABEL = "组内相对偏差（中位数±k×MAD）"


def set_ledger_time_class(on: bool) -> None:
    global _LEDGER_TIME_CLASS
    _LEDGER_TIME_CLASS = bool(on)


def ledger_time_class_enabled() -> bool:
    return bool(_LEDGER_TIME_CLASS)


def set_ledger_outlier_tag(on: bool) -> None:
    global _LEDGER_OUTLIER_TAG
    _LEDGER_OUTLIER_TAG = bool(on)


def ledger_outlier_tag_enabled() -> bool:
    return bool(_LEDGER_OUTLIER_TAG)

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

    @property
    def time_class(self) -> str:
        """归一日后的时点档：same_window｜cross_day｜unknown_time。

        比较一律用 YYYYMMDD（不足 8 位视空→unknown_time）；不许用原始串。
        开关关时仍可算（件④），只是 facts_block 文案不读这一档。
        """
        days: list[str] = []
        for f in self.facts:
            digits = re.sub(r"\D", "", str(f.date or ""))
            days.append(digits[:8] if len(digits) >= 8 else "")
        if any(not d for d in days):
            return "unknown_time"
        if len(set(days)) == 1:
            return "same_window"
        return "cross_day"


# 未采信数字分类计数的原因枚举（固定六键）。
# 真分母＝「本该对撞的数字对」机械不可知——只能披露「这些数字没进台账、因为……」，
# 不得把不可知包装成比率类指标。
_DROP_REASONS = (
    "year", "clause_ref", "ordinal", "no_metric", "metric_rejected", "entity_stop",
)


def _empty_dropped() -> dict[str, int]:
    return {k: 0 for k in _DROP_REASONS}


def _scan(dossier: Dossier) -> tuple[list[Fact], dict]:
    """一次全卷扫描 → (入台账事实, fact_ledger_stats)。

    判定路径与改前逐字等价：该 continue 的仍不进 facts，只是按原因计数。
    不把裸数塞进台账。stats 键：n_numbers / n_facts / dropped。
    """
    facts: list[Fact] = []
    dropped = _empty_dropped()
    n_numbers = 0
    # C-69／R-C69-1：开关开→统一读点；关→改前内联（published_at／year 原串）
    # 不许 try/except 静默退回——开闸却读方瞎且无人报错＝假绿入口（与 skills 一致）
    from app.core.temporal_check import source_date, source_time_unified
    _unified = bool(source_time_unified())
    for src in dossier.sources:
        if _unified:
            date = source_date(src)
        else:
            date = str(src.meta.get("published_at") or src.meta.get("year") or "")
        for seg in src.segments:
            text = seg.text
            for num in extract_nums(text):
                n_numbers += 1
                if _YEAR_RE.fullmatch(num.raw) or _YEAR_RE.fullmatch(num.raw.rstrip("年")):
                    dropped["year"] += 1
                    continue  # 年份不是经营事实
                after = text[num.end: num.end + 1]
                if after and after in _CLAUSE_TAIL:
                    dropped["clause_ref"] += 1
                    continue  # 条款/页码/期号引用
                if num.start > 0 and text[num.start - 1] == "第":
                    dropped["ordinal"] += 1
                    continue  # 序数（第3次/第2轮）
                head = text[: num.start]
                m = _ENTITY_METRIC.search(head)
                if not m:
                    dropped["no_metric"] += 1
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
                    dropped["metric_rejected"] += 1
                    continue
                if entity and entity in _ENTITY_STOP:
                    dropped["entity_stop"] += 1
                    continue
                facts.append(Fact(
                    entity=entity, metric=metric, value=num.scaled,
                    raw=num.raw, source_id=src.id, seg_id=seg.id, date=date))
    stats = {
        "n_numbers": n_numbers,
        "n_facts": len(facts),
        "dropped": dropped,
    }
    return facts, stats


def extract_facts(dossier: Dossier) -> list[Fact]:
    """全部段落 → 事实清单（顺序稳定：信源序 × 段序 × 数字序）。

    签名不变；内部走 ``_scan`` 取 [0]。要分类计数请用 ``_scan``。
    """
    return _scan(dossier)[0]


def format_dropped_disclosure(stats: dict) -> str:
    """报告/链上一行文案：未采信数字分类计数（字段名与文案禁用比率类指标词）。"""
    dropped = stats.get("dropped") or _empty_dropped()
    bits = "、".join(f"{k} {dropped.get(k, 0)}" for k in _DROP_REASONS)
    return (f"未采信数字分类计数：共 {int(stats.get('n_numbers') or 0)} 个数字，"
            f"入台账 {int(stats.get('n_facts') or 0)} 条；{bits}")

def _collisions_from_facts(facts: list[Fact]) -> list[Collision]:
    """已扫描事实 → 对撞清单（不再二次扫卷）。"""
    groups: dict[tuple[str, str], list[Fact]] = {}
    for f in facts:
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


def find_collisions(dossier: Dossier,
                    facts: list[Fact] | None = None) -> list[Collision]:
    """同 (实体小写, 指标) 下数值不可调和（>1% 容差）→ 对撞清单。

    ``facts`` 若已由 ``_scan`` 取得可传入，避免 pipeline 路径二次全扫。
    """
    if facts is None:
        facts = extract_facts(dossier)
    return _collisions_from_facts(facts)


def facts_block(dossier: Dossier) -> str:
    """对撞台账 → 分析师提示词注入块（无对撞返回空串）。

    C-69：LEDGER_TIME_CLASS 开时按 time_class 换文案；条目一条不删、顺序不变、
    仍截 [:8]。关时文案与改前逐字相同。
    """
    collisions = find_collisions(dossier)
    if not collisions:
        return ""
    if not _LEDGER_TIME_CLASS:
        lines = ["", "资料内已知数字冲突（下列数值互相矛盾；请在 JSON 的 conclusions 里"
                 "正面回应：采信哪一方、依据什么，或声明资料不足。"
                 "禁止另起 Markdown 分析报告）："]
        for c in collisions[:8]:
            detail = "；".join(
                f"{f.source_id}说{f.entity}{f.metric}{f.raw}"
                + (f"（时点 {f.date}）" if f.date else "")
                for f in c.facts)
            lines.append(f"- {c.entity or '（未指明主体）'}·{c.metric}：{detail}")
        return "\n".join(lines) + "\n"

    # 与 app.core.precedent.TIME_UNSORTABLE_REASON 同句（避免循环 import）
    _time_unknown = "时点不明，未据此排序"
    lines = ["", "资料内已知数字冲突（下列数值互相矛盾；请在 JSON 的 conclusions 里"
             "正面回应。禁止另起 Markdown 分析报告）："]
    for c in collisions[:8]:
        tc = c.time_class
        if tc == "same_window":
            guide = "采信哪一方、依据什么，或声明资料不足"
        elif tc == "cross_day":
            guide = ("这是不同日期的变化，写成时序演变（旧值→新值），"
                     "不要判谁错")
        else:
            guide = f"{_time_unknown}；不要求采信某一方"
        detail = "；".join(
            f"{f.source_id}说{f.entity}{f.metric}{f.raw}"
            + (f"（时点 {_display_day(f.date)}）" if _display_day(f.date) else "")
            for f in c.facts)
        lines.append(
            f"- {c.entity or '（未指明主体）'}·{c.metric}：{detail}"
            f"（{guide}）")
    return "\n".join(lines) + "\n"


def _display_day(raw: str) -> str:
    """行内时点只展示归一日（8 位）；不足则空。"""
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits[:8] if len(digits) >= 8 else ""


# ---- C-78：组内相对偏差标签（渲染侧；不改 find_collisions）----------------

def normalize_entity(entity: str) -> str:
    """去数字、去标点、去空白后转小写（分组键用）。"""
    text = str(entity or "")
    text = re.sub(r"\d+", "", text)
    text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return text.lower()


def _fmt_num(v: float) -> str:
    """稳定小数：去掉多余尾零，保证跨进程同字。"""
    if abs(v - round(v)) < 1e-12:
        return str(int(round(v)))
    return f"{v:.6g}"


def format_dispersion_note(*, value: float, med: float, mad: float, k: int) -> str:
    """派生标签文案；数字必须来自入参（删掉数字或改成常量 ⇒ 守护格红）。"""
    return (
        f"{DISPERSION_LABEL}：中位 {_fmt_num(med)}，MAD {_fmt_num(mad)}，"
        f"此值 {_fmt_num(value)} 偏离 {int(k)}×MAD ⇒ 标为可疑"
    )


def _fact_tag_key(f: Fact) -> tuple[str, str, float]:
    return (f.source_id, f.seg_id, float(f.value))


def build_dispersion_tag_map(
    facts: list[Fact] | None,
    *,
    k: int = 3,
) -> dict[tuple[str, str, float], str]:
    """(source_id, seg_id, value) → 标签文案。

    规则（C-78）：同 (归一主体, 指标) 且不同数值 ≥3；med／MAD；
    仅 MAD>0 且 |v−med| > k×MAD 才标。组键与组内均显式排序＝确定性。
    """
    out: dict[tuple[str, str, float], str] = {}
    groups: dict[tuple[str, str], list[Fact]] = {}
    for f in facts or []:
        metric = f.metric or ""
        if not metric:
            continue
        gkey = (normalize_entity(f.entity), metric)
        groups.setdefault(gkey, []).append(f)

    for gkey in sorted(groups.keys()):
        fs = sorted(
            groups[gkey],
            key=lambda x: (x.source_id, x.seg_id, float(x.value), x.raw),
        )
        values = [float(f.value) for f in fs]
        distinct = sorted(set(values))
        if len(distinct) < 3:
            continue
        med = float(statistics.median(values))
        mad = float(statistics.median([abs(v - med) for v in values]))
        if mad <= 0:
            continue
        lo = med - float(k) * mad
        hi = med + float(k) * mad
        for f in fs:
            v = float(f.value)
            if v < lo or v > hi:
                out[_fact_tag_key(f)] = format_dispersion_note(
                    value=v, med=med, mad=mad, k=int(k))
    return out


def dispersion_notes_for_facts(
    facts: list[Fact] | None,
    tag_map: dict[tuple[str, str, float], str] | None,
) -> list[str]:
    """某对撞行涉及的事实 → 去重后的标签列表（稳序）。"""
    if not tag_map:
        return []
    notes: list[str] = []
    seen: set[str] = set()
    for f in sorted(
        facts or [],
        key=lambda x: (x.source_id, x.seg_id, float(x.value), x.raw),
    ):
        note = tag_map.get(_fact_tag_key(f))
        if note and note not in seen:
            seen.add(note)
            notes.append(note)
    return notes


def dispersion_accounting(facts: list[Fact] | None) -> dict:
    """k=3 进报告；k=5 只进 accounting 对照。"""
    t3 = build_dispersion_tag_map(facts, k=3)
    t5 = build_dispersion_tag_map(facts, k=5)
    return {
        "label": DISPERSION_LABEL,
        "k3_n_tagged": len(t3),
        "k5_n_tagged": len(t5),
        "k_report": 3,
    }
