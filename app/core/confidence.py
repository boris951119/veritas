"""置信度量化（榜单硬需求 3：按信源可信度、证据数量与一致性、
推理链完整性给分并说明依据）。

四分量，全部可解释、可增量重算：
- strength   证据强度：等级权 × 信源可信度 × 因果加成 × 人工权重 的均值；
             （对应榜单「信源可信度」）
- coverage   证据覆盖：条数边际递减，饱和于 4 条；单条有基本覆盖下限；
             （对应榜单「数据数量」）
- agreement  跨智能体一致性：结论署名数 / 分析师编队人数（归并组被多个
             分析师独立得出 → 加成；单人结论不打到 0，floor 0.5）。
             （对应榜单「一致性」）
- chain      推理链完整性：引文是否逐字命中、理由是否支撑主张、数字是否可溯源、
             声称范围有无声明、时点有无锚定、因果有无机制——六环按**适用项**
             计通过率（对应榜单「推理链完整性」，此前只有黄灯不进分）。

综合 = 加权和＋硬门（v2；人定权重，非拟合）：
  raw = clip01(b + s·strength + c·coverage + a·agreement_factor + h·chain_score)；
  再经 G1 引文命中／G2 无证据／G3 前提破坏三道硬门封顶。
  权重表见 `_AGG`（先验设定；拟合版只作附报、不进生产）。
  第四维直接用 `chain_score` 原值（0–1 六环通过率）；
  `chain_factor_of`／`_CHAIN_FLOOR`／`_CHAIN_UNKNOWN` 留作面板与 v1 对照。
人工修改（删证据/改权重/改信源可信度）后，工作台经 `_mutate` 调
`recompute_all()` 全量回填置信度；依赖传播只识别并披露受影响集合
（`affected_downstream`／`premise_broken` 黄牌），不改变本模块公式。
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from app.core.evidence import (
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    LEVEL_WEIGHT,
    RelationKind,
)

_CAUSATION_BONUS = 1.15       # 因果证据加成（封顶 1）
_COVERAGE_SATURATION = 4      # 覆盖分饱和所需证据条数
_COVERAGE_FLOOR = 0.5         # 单条证据的覆盖分下限（有证据就有基本覆盖）
_AGREEMENT_FLOOR = 0.5        # 单人结论的一致性因子下限
_CHAIN_FLOOR = 0.55           # 链全断时的因子下限（压分不清零，语义仍归人）
_CHAIN_UNKNOWN = 0.75         # 无从判定时的因子（不给满分也不按断链罚）

# 合式常量表（人定、非拟合）。b/s/c/a/h＝加权和；g*＝三道硬门阈值。
# 先验设定；拟合版只作附报、不进生产。拟合只许发生在温度标量 T 上（见 scripts/fit_temperature.py）。
_AGG: dict[str, float] = {
    "b": 0.10,   # 截距
    "s": 0.25,   # strength
    "c": 0.20,   # coverage
    "a": 0.15,   # agreement_factor
    "h": 0.30,   # chain_score 原值
    "g1_hit_rate_min": 0.6,  # G1：引文命中率下限
    "g1_cap": 0.40,          # G1 触发时 conf 封顶
    "g3_cap": 0.45,          # G3：premise_broken 非空时封顶
}

# 生产默认温度（不缩放）。非 1.0 须经配置／回执显式启用；本模块读取侧见 apply_temperature。
_DEFAULT_TEMPERATURE = 1.0


def aggregate(strength: float, coverage: float, agreement_factor: float,
              chain_score: float) -> float:
    """唯一合式：加权和（人定权重，非拟合）。

    raw = clip01(b + s·strength + c·coverage + a·agreement_factor + h·chain_score)。
    第四维是 `chain_score` 原值，不经 `chain_factor_of` 下限拉伸。
    硬门见 `apply_hard_gates`；温度见 `apply_temperature`。
    """
    a = _AGG
    raw = (
        a["b"]
        + a["s"] * float(strength)
        + a["c"] * float(coverage)
        + a["a"] * float(agreement_factor)
        + a["h"] * float(chain_score)
    )
    return min(1.0, max(0.0, raw))


def apply_hard_gates(
    conf: float,
    *,
    hit_rate: float | None,
    n_evidence: int,
    premise_broken: list | tuple | None,
) -> tuple[float, dict]:
    """三道硬门。返回 (封顶后 conf, gates 披露字典)。阈值只读 `_AGG`。"""
    a = _AGG
    gates: dict = {
        "G1_citation": {
            "fired": False,
            "hit_rate": None if hit_rate is None else round(float(hit_rate), 4),
            "threshold": a["g1_hit_rate_min"],
            "cap": a["g1_cap"],
        },
        "G2_no_evidence": {"fired": False, "n_evidence": int(n_evidence)},
        "G3_premise_broken": {
            "fired": False,
            "ids": list(premise_broken or []),
            "cap": a["g3_cap"],
        },
    }
    out = float(conf)
    if int(n_evidence) <= 0:
        gates["G2_no_evidence"]["fired"] = True
        out = 0.0
    if hit_rate is not None and float(hit_rate) < a["g1_hit_rate_min"]:
        gates["G1_citation"]["fired"] = True
        out = min(out, a["g1_cap"])
    if premise_broken:
        gates["G3_premise_broken"]["fired"] = True
        out = min(out, a["g3_cap"])
    return out, gates


def apply_temperature(raw: float, *, mean: float, temperature: float) -> float:
    """单调温度缩放：score = clip01(mean + T·(raw − mean))。T=1 恒等。"""
    t = float(temperature)
    m = float(mean)
    return min(1.0, max(0.0, m + t * (float(raw) - m)))


def citation_hit_rate(dossier: "Dossier", conclusion_id: str) -> float | None:
    """当场用 citation_check 重算：逐字命中条数 / 证据条数。无证据 → None（交给 G2）。"""
    from app.core.citation_check import check_evidence

    evs = dossier.evidences_of(conclusion_id)
    if not evs:
        return None
    hits = sum(1 for ev in evs if not check_evidence(ev, dossier))
    return hits / len(evs)


def _chain_score_for_aggregate(chain_score: float | None) -> float:
    """aggregate 第四维：有原值用原值；None（无从判定）填 `_CHAIN_UNKNOWN` 数值，不经 floor 拉伸。"""
    if chain_score is None:
        return _CHAIN_UNKNOWN
    return float(chain_score)


def _gated_score_from_parts(parts: dict | None, raw: float) -> float:
    """从 parts 里已披露的 gates／n_evidence 重放硬门（与 conclude_confidence 同源）。"""
    p = dict(parts or {})
    n_evidence = int(p.get("n_evidence") or 0)
    gates_in = p.get("gates") if isinstance(p.get("gates"), dict) else {}
    g1 = gates_in.get("G1_citation") if isinstance(gates_in.get("G1_citation"), dict) else {}
    g3 = gates_in.get("G3_premise_broken") if isinstance(gates_in.get("G3_premise_broken"), dict) else {}
    hit_rate = g1.get("hit_rate")
    premise_broken = g3.get("ids") or []
    # 无 gates 字段的旧 parts：不瞎触发 G1／G3（hit_rate 未知）；G2 仍看 n_evidence
    if not gates_in:
        hit_rate = 1.0  # 未知视作不触发 G1
        premise_broken = []
        if "n_evidence" not in p:
            # 更老的产物：无法判断无证据，只跑加权和
            return round(raw, 4)
    conf, _ = apply_hard_gates(
        raw, hit_rate=hit_rate, n_evidence=n_evidence, premise_broken=premise_broken,
    )
    return round(conf, 4)


# 呈现层分档（C-20）：不进 conclude_confidence；0.8＝官方达标行原文，0.5＝我方设定
_BAND_HIGH = 0.8
_BAND_MID = 0.5
_BAND_REL_EPS = 1e-9  # 切点重合判定容差（我方设定；R-C20-3）
BAND_RULE = (
    "高阈值 0.8＝官方达标行原文；中阈值 0.5＝我方设定；规则分档，不是命中率"
)


def chain_factor_of(chain_score: float | None) -> float:
    """链完整性 → 置信度因子（0-1）。

    `None` = 无从判定：REA 那条「unknown 不许当 pass」的规矩——既不给
    满分（0.75 < 1），也不按断链罚（0.75 > 0.55）。
    注意这是**防御分支**：实际链上只要结论挂了证据，quote_hits 环必进分母，
    所以有证据的结论永远拿得到分数；而「无证据」在进这里之前就已经返回 0。
    留着它是为了让语义口子收紧后不塌——将来分母口径一变，未知档仍走 0.75。
    """
    if chain_score is None:
        return _CHAIN_UNKNOWN
    return _CHAIN_FLOOR + (1 - _CHAIN_FLOOR) * chain_score


def band_of(score: float) -> str:
    """绝对档：>=0.8 高／>=0.5 中／否则低（边界方向钉官方达标行原话）。"""
    if score >= _BAND_HIGH:
        return "高"
    if score >= _BAND_MID:
        return "中"
    return "低"


def band_rel_cuts(scores: Sequence[float]) -> tuple[float, float] | None:
    """34%/67% 切点；样本 <2 返回 None（quantiles 会抛）。"""
    xs = list(scores)
    if len(xs) < 2:
        return None
    q = statistics.quantiles(xs, n=100, method="inclusive")
    return q[33], q[66]


def band_rel_of(scores: Sequence[float], score: float) -> str:
    """同跑次分位档；0 分恒低；切点重合 ⇒ 不可分；样本 <2 整档记「低」。"""
    if score <= 0.0:  # 规则一：0 分＝无支撑，不参与分位
        return "低"
    cuts = band_rel_cuts(scores)
    if cuts is None:  # 样本 <2：原有分支
        return "低"
    lo, hi = cuts
    if hi - lo < _BAND_REL_EPS:  # 规则二：切点重合（含 hi<lo 浮点毛刺）
        if score > hi + _BAND_REL_EPS:
            return "高"
        if score < lo - _BAND_REL_EPS:
            return "低"
        return "不可分"
    if score >= hi:
        return "高"
    if score >= lo:
        return "中"
    return "低"


def band_rel_rule_of(scores: Sequence[float]) -> str:
    """别人能照着复算：方法名＋pooled 样本数＋当次切点（或小样本／退化分支）。"""
    xs = list(scores)
    n = len(xs)
    if n < 2:
        return (
            f"quantiles n=100 method=inclusive；pooled 样本数={n}；"
            "样本<2 整档记为低；来源＝我方本次分布"
        )
    lo, hi = band_rel_cuts(xs)  # type: ignore[misc]
    base = (
        f"quantiles n=100 method=inclusive；pooled 样本数={n}；"
        f"切点 lo={round(lo, 4)} hi={round(hi, 4)}；来源＝我方本次分布"
    )
    if hi - lo < _BAND_REL_EPS:
        n_tied = sum(
            1 for s in xs
            if s > 0.0
            and not (s > hi + _BAND_REL_EPS)
            and not (s < lo - _BAND_REL_EPS)
        )
        return (
            f"{base}；切点重合（lo={lo!r} hi={hi!r}），"
            f"并列在切点上的 {n_tied} 条记『不可分』"
        )
    return base


def row_score_detail(parts: dict | None) -> tuple[float, dict]:
    """提交行 score＋代入项（唯一一份公式；导出层 terms／substitution 共用）。"""
    p = dict(parts or {})
    strength = float(p.get("strength") or 0.0)
    coverage = float(p.get("coverage") or 0.0)
    agreement = float(p.get("agreement") or 0.0)
    chain = p.get("chain")
    chain_num = None if chain is None else float(chain)
    agreement_factor = _AGREEMENT_FLOOR + (1 - _AGREEMENT_FLOOR) * agreement
    chain_factor = chain_factor_of(chain_num)  # 面板／v1 对照；不进 v2 合式
    chain_for_agg = _chain_score_for_aggregate(chain_num)
    # 若 parts 来自 conclude_confidence，复用其 aggregate_raw，避免分量四位四舍五入后 ±1e-4
    if "aggregate_raw" in p and p.get("aggregate_raw") is not None:
        raw = float(p["aggregate_raw"])
    else:
        raw = aggregate(strength, coverage, agreement_factor, chain_for_agg)
    score = _gated_score_from_parts(p, raw)
    gates = p.get("gates") if isinstance(p.get("gates"), dict) else None
    terms = {
        "strength": strength,
        "coverage": coverage,
        "agreement": agreement,
        "agreement_factor": round(agreement_factor, 4),
        "chain": chain_num,
        "chain_factor": round(chain_factor, 4),
        "chain_for_aggregate": round(chain_for_agg, 4),
        "aggregate_raw": round(raw, 4),
        # R-C36-3：substitution 挂「+ gates」须在提交面真披露；无 gates 的旧 parts 写 null
        "gates": gates,
    }
    return score, terms


def row_score_of(parts: dict | None) -> float:
    """提交行 score：与官方导出层同一份公式（唯一实现）。"""
    return row_score_detail(parts)[0]


def aggregate_constants() -> dict:
    """对外披露用的合式常量只读快照＝`aggregate`／`apply_hard_gates` 当场用的同一份数。

    这函数不做任何判定、不改任何分数：导出层把它写进提交 JSON，是为了让评委
    「按式能算出同分」——印出去的权重与程序里乘的权重来自同一个对象，
    不存在第二份抄本可以漂移。温度＝生产默认（不缩放）；非 1.0 须显式启用，
    本快照如实反映当前默认。
    """
    return {
        "weights": {
            "b": _AGG["b"], "s": _AGG["s"], "c": _AGG["c"],
            "a": _AGG["a"], "h": _AGG["h"],
        },
        "hard_gates": {
            "G1_citation": {
                "hit_rate_min": _AGG["g1_hit_rate_min"], "cap": _AGG["g1_cap"],
                "rule": "hit_rate < hit_rate_min => conf = min(conf, cap)",
            },
            "G2_no_evidence": {
                "cap": 0.0, "rule": "n_evidence <= 0 => conf = 0",
            },
            "G3_premise_broken": {
                "cap": _AGG["g3_cap"],
                "rule": "premise_broken 非空 => conf = min(conf, cap)",
            },
        },
        "component_constants": {
            "coverage_floor": _COVERAGE_FLOOR,
            "coverage_saturation": _COVERAGE_SATURATION,
            "agreement_floor": _AGREEMENT_FLOOR,
            "chain_unknown": _CHAIN_UNKNOWN,
            "causation_bonus": _CAUSATION_BONUS,
        },
        "band_thresholds": {"high": _BAND_HIGH, "mid": _BAND_MID},
        "temperature_default": _DEFAULT_TEMPERATURE,
        "recompute_rule": (
            "分量各先 round4 → raw = clip01(b + s*strength + c*coverage "
            "+ a*agreement_factor + h*chain_score) → 依序过 G2/G1/G3 封顶 "
            "→ score = round(conf, 4)；用印出的四位数手算允许落在 ±1e-4 "
            "（第四位取整边界），超出＝复现失败"
        ),
    }


def band_count_dict(scores: Sequence[float], *, absolute: bool) -> dict[str, int]:
    """档条数（含 0）。绝对面 3 键；相对面 4 键（含「不可分」）。"""
    xs = list(scores)
    if absolute:
        out = {"高": 0, "中": 0, "低": 0}
        for s in xs:
            out[band_of(s)] += 1
        return out
    out = {"高": 0, "中": 0, "低": 0, "不可分": 0}
    for s in xs:
        out[band_rel_of(xs, s)] += 1
    return out


def evidence_score(ev: EvidenceNode, dossier: Dossier) -> float:
    """单条证据的强度分（0-1）：等级 × 信源可信度 × 因果加成 × 人工权重。

    因果加成须有机制词支撑（引文/说明含「因为/导致/由此…」）——causation
    有加成即有虚标动机，无机制表述按相关计分（机械侧与 discourse_check
    的 causation_support 闸同口径，闸亮黄牌、此处压分）。"""
    creds = []
    for sid in ev.segment_ids:
        src = dossier.source_of_segment(sid)
        if src is not None:
            creds.append(src.credibility)
    base = (sum(creds) / len(creds)) if creds else 0.3
    score = LEVEL_WEIGHT.get(ev.level, 0.5) * base * ev.weight
    if ev.relation == RelationKind.CAUSATION:
        from app.core.discourse_check import has_mechanism_word

        if has_mechanism_word(ev.quote, ev.note):
            score *= _CAUSATION_BONUS
    return min(1.0, max(0.0, score))


def evidence_strength_of(conclusion_id: str, dossier: Dossier) -> float:
    """结论的证据平均强度（0-1；无证据为 0）——冲突加权的机械口径。"""
    evs = dossier.evidences_of(conclusion_id)
    if not evs:
        return 0.0
    return sum(evidence_score(e, dossier) for e in evs) / len(evs)


def conclude_confidence(conclusion_id: str, dossier: Dossier,
                        n_panel: int = 1,
                        chain_ctx: dict | None = None) -> tuple[float, dict]:
    """结论置信度 = aggregate(…) 加权和＋硬门（见模块 docstring）。"""
    con = dossier.conclusion(conclusion_id)
    evs = dossier.evidences_of(conclusion_id)
    if con is None or not evs:
        # 链上无从下手的结论（典型：证据被人工删空）记 unknown 而不是 0——
        # 「没证据」这件事由 strength/coverage 承担罚分，链分量不许重复计罚，
        # 更不许在渲染层冒出「0.00〔六环全闭合〕」这种自相矛盾。
        _conf0, gates0 = apply_hard_gates(
            0.0, hit_rate=None, n_evidence=len(evs),
            premise_broken=list((con.premise_broken if con else None) or []),
        )
        return _conf0, {"strength": 0.0, "coverage": 0.0, "agreement": 0.0,
                     "chain": None,
                     "chain_detail": {"applicable": [], "broken": [],
                                      "score": None, "unknown": True},
                     "n_evidence": len(evs), "note": "无证据支撑",
                     "gates": gates0}
    scores = [evidence_score(e, dossier) for e in evs]
    strength = sum(scores) / len(scores)
    n = len(evs)
    coverage = _COVERAGE_FLOOR + (1 - _COVERAGE_FLOOR) * (
        1.0 - math.exp(-(n - 1) / (_COVERAGE_SATURATION - 1)))
    n_authors = len({*con.author_names()}) or 1
    panel = max(1, int(n_panel))
    agreement = min(1.0, n_authors / panel)
    agreement_factor = _AGREEMENT_FLOOR + (1 - _AGREEMENT_FLOOR) * agreement
    # 第四分量：推理链完整性（六环按适用项计通过率；无从判定走未知档，
    # 既不白捡满分也不按断链罚——见 chain_integrity 模块文档）
    from app.core.chain_integrity import chain_context, chain_integrity

    ctx = chain_ctx if chain_ctx is not None else chain_context(dossier)
    report = chain_integrity(dossier, conclusion_id, ctx)
    chain_score = report.score
    chain_factor = chain_factor_of(chain_score)  # 面板／v1 对照；不进 v2 合式
    chain_for_agg = _chain_score_for_aggregate(chain_score)
    hit_rate = citation_hit_rate(dossier, conclusion_id)
    premise_broken = list(con.premise_broken or [])
    raw = aggregate(strength, coverage, agreement_factor, chain_for_agg)
    conf, gates = apply_hard_gates(
        raw, hit_rate=hit_rate, n_evidence=n, premise_broken=premise_broken,
    )
    parts = {
        "strength": round(strength, 4),
        "coverage": round(coverage, 4),
        "agreement": round(agreement, 4),
        "chain": (None if chain_score is None else round(chain_score, 4)),
        "chain_detail": report.to_parts(),
        "n_evidence": n,
        "n_authors": n_authors,
        "levels": sorted({e.level.value for e in evs}),
        "min_evidence_score": round(min(scores), 4),
        "gates": gates,
        "aggregate_raw": round(raw, 4),
        "chain_factor": round(chain_factor, 4),
    }
    return round(conf, 4), parts


def recompute_conclusion(conclusion_id: str, dossier: Dossier,
                         n_panel: int = 1,
                         chain_ctx: dict | None = None) -> float:
    """人工修改后的增量重算入口（工作台每改一处只重算受影响结论）。"""
    conf, parts = conclude_confidence(conclusion_id, dossier, n_panel, chain_ctx)
    con = dossier.conclusion(conclusion_id)
    if con is not None:
        con.confidence = conf
        con.confidence_parts = parts
    return conf


def recompute_all(dossier: Dossier, n_panel: int = 1) -> None:
    """全量回填（管线收口与报告前调用）。链上下文只扫一遍闸，避免 O(n²)。"""
    from app.core.chain_integrity import chain_context

    ctx = chain_context(dossier)
    for con in dossier.conclusions:
        recompute_conclusion(con.id, dossier, n_panel, chain_ctx=ctx)
