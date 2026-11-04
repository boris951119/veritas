"""五份官方提交 JSON＋字段说明。

fact_des／argument／entities 本版本留空，不编造。
conflict 记录只读 Resolution.to_dict() 已有键；basis、重启条件读不到就留空。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.core.confidence import (
    BAND_RULE,
    aggregate_constants,
    band_count_dict,
    band_of,
    band_rel_of,
    band_rel_rule_of,
    row_score_detail,
)
from app.core.conflicts import METHOD_TO_RESOLUTION_TYPE
from app.core.evidence import (
    Dossier,
    conclusion_face_pooled,
    format_conclusion_face_line,
)

_ARGUMENT_KEYS = ("时间", "主体", "地点", "内容", "影响", "数值口径")
_EMPTY_ARGUMENT = {key: "" for key in _ARGUMENT_KEYS}

_FIELD_NOTES = """\
# 官方提交物字段说明

## evidence.json
键与附录 A.2 一致：doc_id、para_id、quote、fact_des、argument、entities。
argument 六槽为：时间、主体、地点、内容、影响、数值口径。
fact_des、argument 各槽、entities：本版本未实现，值为 null 或空串。填它要做抽取、抽取即可能编造 ⇒ 留空并在路演说明。不编造。

本版本另附证据等级字段（加分 4.1.2；rubric:352）：
- level：我方 A/B/C/D（与 EvidenceLevel 一致，键名与取值逐字不变）。
- level_official：官方六级名之一（官方程序记录／官方表态／权威媒体／主流媒体／匿名信源／自媒体转述），
  由全仓唯一映射表 OFFICIAL_LEVEL_TO_OURS（官方六级→A/B/C/D）逆查代表词得到。
  映射依据＝官方程序记录→A；官方表态／权威媒体→B；主流媒体／匿名信源→C；自媒体转述→D
  （与我方 EvidenceLevel 注释及信源优先级序对齐）。
  **加权仍用我方 A/B/C/D、数值未改**（LEVEL_WEIGHT 与 confidence.py 应用点一字未动）。

本版本另附结构化因果主张字段（证据级；系统校验声称结构完整性与措辞纪律，
不做效应估计、不做完整因果引擎）：
- causal_claim：主张卡四要素（intervention＝干预 X／outcome＝结果 Y／
  population＝适用对象／counterfactual＝反事实一句话）。缺任一项则该证据
  降级为 correlation，取消因果加成，并写 degraded_reason。
- mechanism_completeness：机制完整度。direct＝直接机制；indirect＝间接机制
  （须填 missing_links）；correlation_only＝仅相关（默认）。
- missing_links：间接机制缺环枚举。mediator＝缺中介；temporal＝缺时序；
  contrast＝缺对照。
- design_tier：识别强度（只展示／进提交物，**不乘进任何分数**）。
  rct＝随机对照；quasi＝准实验；observational＝观察性；claim_only＝仅声称（默认）。
- declared_relation：降级前的关系标注（降级时保留 causation）。
- degraded_reason：降级原因（缺哪些要素／缺环）；未降级为空串。
  降级后该结论仍把因果机制核对计入链分母并按断链计，故降级不会让置信度变高。

## conclusions.json
键与附录 A.3 一致：question_id、question、conclusion、supporting_facts、conflicting_facts。
supporting_facts / conflicting_facts 的元素只有 doc_id、para_id。
supporting_facts 与 conclusion 文本同源：优先消解后 majority 且带证据的那条结论的 evidence_ids 映射段落；
该题没有任何带证据的结论时才用 headline 兜底，此时支撑沿用全案卷证据并披露「文本与支撑不同源」。
conflicting_facts 映射规则（只一条）：对该题 dossier.conflicts 每一对，当 resolution.winner_id ∈ {a_id, b_id} 时，
取与被交结论对立的另一侧结论的 evidence_ids，经 _segment_locator 换成 (doc_id, para_id) 去重并入；
winner_id 为 tie／human_override 未分胜负、或段落取不到 ⇒ 一律不并入（宁缺毋编），计入跳过数（tie 与取不到段落分开计）。

## confidence.json
schema 自定（附录 A 未规定）。每条结论含：
信源可信度、证据数量与一致性、推理链完整性，
以及公式（v2 加权和＋硬门）`clip01(b + s·strength + c·coverage + a·agreement_factor + h·chain_score)`再经 G1/G2/G3 硬门、
各分项数值与代入演算。
terms.gates 披露三道硬门状态：G1 引文命中（hit_rate＜0.6 ⇒ 封顶 0.40）／G2 无证据（n_evidence≤0 ⇒ 归零）／G3 前提破坏（premise_broken 非空 ⇒ 封顶 0.45）；substitution 尾巴 `+ gates[…]` 列出已触发门名（无触发＝none）。
另有两套呈现档（不许合并、不许互替）：
- band：绝对档。高阈值 0.8＝官方达标行原文「高置信（≥0.8）」；中阈值 0.5＝我方设定（官方未写中/低分界）。
  一律从本行 score（parts 重算）来，不从 dossier_confidence 来（二者实测可差 1e-4）。
- band_rel：同跑次分位档。切点＝statistics.quantiles(scores, n=100, method=inclusive) 的第 34／67 个；
  样本面＝整份 confidence.json pooled（跨题合并）；样本 <2 整档记「低」。方法名与当次切点写在 band_rel_rule。
  退化规则（我方设定）：score≤0 ⇒ 恒记「低」（0 分不参与分位）；切点重合（hi−lo < 1e-9）时并列在切点上的记「不可分」。
  「不可分」＝我方设定，出现在本次分布退化（切点重合）时，表示这一档说不出高低，不是缺数据、也不是低。
v1 连乘下高档（≥0.8）结构性为空；v2 起改为人定权重加权和＋硬门后高档可非空，
但自标定 226 行上高档准确率仍低于整体基准（见 proposal／score_face_v2_report），
达标行「≥0.8 正确率 ≥85%」仍无法回答（等官方第 4 问）。无样本可判／未达标两句须同现。
首屏「本案卷 N 条」是单案卷面；提交物分位面是 pooled 全跑次——两面不要混读。
本文件（confidence.json）仅含消解后 majority 态；逐态真数见下方「本次导出」里当场数出来的样本面披露。
配色（工作台）＝绝对档同一对阈值；提交行多数落在绝对档低／中时卡片偏红/黄是实测结果，不是渲染坏了。

## conflict_resolution.json
schema 自定。resolution_type 取官方五级之一，由 method 经模块级映射表得到
（映射表在 conflicts.py）。
basis、重启条件：由 Resolution.to_dict() 输出；缺失时留空并在 omissions 里披露。
omissions 取值含：人工改判、假不等式已拦截，以及导出层对缺失字段的标注。
导出层不另算证据强度，也不另数独立信源。
冲突清单（C-46）：两侧各一项 {conclusion_id, statement, source_ids, para_ids}；
甲＝pair.a_id、乙＝pair.b_id。statement 逐字取自该结论 statement，超 120 字截断并在串内标 …（截断）；
source_ids／para_ids 由该结论证据的 segment→(doc_id, para_id) 去重列出。
结果（C-46）：{outcome, winner_id, tie}。outcome ∈ 甲胜／乙胜／并存不裁决；
平局或未分胜负一律 outcome＝并存不裁决 且 winner_id＝""（不许伪造胜方）。
单条记录按 JSON 串（ensure_ascii=False）计 ≤800 字；超限先压 statement、再压 rationale，并在 omissions 标注「单条记录超800字已截断」。

## causal_evidence.json
schema 自定（附录 A 将「因果证据 JSON」列为非必须加分项；rubric 1.3）。
每条＝一条**含因果主张的结论**一行（不是每条证据一行；相关-only、无主张卡的结论不出现）。
字段（全部复用既有证据级结构，**不新造判定、不调模型、不改数值**）：
- conclusion_id／question_id：结论与议题标识。
- intervention／outcome／population／counterfactual：主张卡四要素
  （取值来自该结论下首条带非空 causal_claim 的证据；键名与
  app/core/causal_claim.py 的 CLAIM_KEYS 一致）。
- mechanism_completeness：direct｜indirect｜correlation_only
  （与证据字段同名同枚举）。
- missing_links：mediator／temporal／contrast 列表（indirect 时有意义）。
- design_tier：rct｜quasi｜observational｜claim_only（只展示，不进分）。
- degraded_reason：降级成因；未降级为空串。
- evidence_refs：该结论下所有「带因果主张」证据的
  {doc_id, para_id, quote} 列表（quote 为证据原引文摘要，不新造）。
- confidence：复用该结论当前 confidence 数值（与 confidence.json 同源字段
  dossier_confidence／Conclusion.confidence），**本文件不改写、不重算**。

边界句与 evidence.json 相同：系统校验因果声称的结构完整性与措辞纪律，
不做效应估计、不做完整因果引擎。

## 窗口装箱
本次按假定窗口装箱（accounting.pack_window.window_tokens＝数值；
rule＝align_to_window｜align_to_window_未检查｜disabled｜unchecked）。
取值顺序＝探到的生效 num_ctx ＞ model_context_tokens_by_model 声明值 ＞
env 显式 VERITAS_MODEL_CTX_TOKENS 当声明 ＞ 端点可探但无 num_ctx 时落
VERITAS_MODEL_CTX_FALLBACK（默认 4096，未检查，不是安全保证；〔150〕见过
运行时回退 2048）＞ 端点不可探时沿用全局 model_context_tokens（source＝
unchecked_global，披露「窗口未检查（端点不可探，沿用全局 N）＝假定值，
不是实测」——不许叫实测窗）。编队取所用模型窗的最小值。若现场更大请调
VERITAS_MODEL_CTX_TOKENS 或 model_context_tokens_by_model；关闭＝
VERITAS_PACK_TO_WINDOW=0。
"""


def _empty_argument() -> dict:
    return dict(_EMPTY_ARGUMENT)


def _segment_locator(dossier: Dossier, segment_id: str) -> tuple[str, str] | None:
    seg = dossier.segment(segment_id)
    if seg is None:
        return None
    src = dossier.source_of_segment(segment_id)
    doc_id = str((src.meta or {}).get("doc_id") or (src.id if src else ""))
    return doc_id, seg.id


# 全仓唯一一张：官方六级证据等级 → 我方 A/B/C/D（rubric:352）。
# 展示用逆查见 level_official_of；加权仍用 app.core.evidence.LEVEL_WEIGHT，数值未改。
OFFICIAL_LEVEL_TO_OURS: dict[str, str] = {
    "官方程序记录": "A",
    "官方表态": "B",
    "权威媒体": "B",
    "主流媒体": "C",
    "匿名信源": "C",
    "自媒体转述": "D",
}


def level_official_of(level: str) -> str:
    """我方 A/B/C/D → 官方六级展示名（每档取映射表中首次出现的代表词）。"""
    key = str(level or "")
    for official, ours in OFFICIAL_LEVEL_TO_OURS.items():
        if ours == key:
            return official
    raise KeyError(f"unknown evidence level: {level!r}")


def _evidence_rows(dossier: Dossier,
                   seen: set[tuple[str, str, str]]) -> tuple[list[dict], int]:
    """seen 由 export_official 持有，跨题共用。返回 (新行, 被去重掉的行数)。"""
    rows: list[dict] = []
    dropped = 0
    for ev in dossier.evidences:
        for sid in ev.segment_ids:
            loc = _segment_locator(dossier, sid)
            if loc is None:
                continue
            doc_id, para_id = loc
            key = (doc_id, para_id, ev.quote)
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            level_val = ev.level.value
            row = {
                "doc_id": doc_id,
                "para_id": para_id,
                "quote": ev.quote,
                "fact_des": None,
                "argument": _empty_argument(),
                "entities": None,
                "level": level_val,
                "level_official": level_official_of(level_val),
            }
            # C-32：因果相关条目附主张卡键（相关-only 条目不塞空卡噪音）
            declared = (getattr(ev, "declared_relation", "") or
                        ev.relation.value)
            if (ev.relation.value == "causation"
                    or declared == "causation"
                    or getattr(ev, "degraded_reason", "")):
                row["causal_claim"] = (
                    dict(ev.causal_claim) if ev.causal_claim else None)
                row["mechanism_completeness"] = (
                    ev.mechanism_completeness or "correlation_only")
                row["missing_links"] = list(ev.missing_links or [])
                row["design_tier"] = ev.design_tier or "claim_only"
                row["declared_relation"] = declared
                row["degraded_reason"] = ev.degraded_reason or ""
                row["relation"] = ev.relation.value
            rows.append(row)
    return rows, dropped


def _bare_gate_line(n_questions: int, dropped_ids: list[str],
                    kept_bare_ids: list[str] | None = None) -> str:
    ids = "、".join(dropped_ids) if dropped_ids else "（无）"
    if n_questions >= 3:
        return (
            f"裸结论闸：本次题数 {n_questions} ≥3，"
            f"未写入结论提交的 question_id：{ids}。"
        )
    kept = "、".join(kept_bare_ids) if kept_bare_ids else "（无）"
    return (
        f"裸结论闸：本次题数 {n_questions} ≤2，"
        f"裸结论照旧提交，保留的 question_id：{kept}。"
    )


def _facts_from_evidences(dossier: Dossier, evidences) -> list[dict]:
    """把证据列表映射成去重后的 (doc_id, para_id) 行；locator 取不到的跳过。

    C-114：旗开时把取不到的 segment_id 记入 accounting["anchor_stable"]["missing_anchor"]，
    不静默吞（行仍不交——契约禁止无 doc_id#para_id 的模糊锚）。
    """
    facts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    missing: list[dict] = []
    from app.core.anchor_stable import anchor_stable_enabled
    harden = anchor_stable_enabled()
    for ev in evidences:
        for sid in ev.segment_ids:
            loc = _segment_locator(dossier, sid)
            if loc is None:
                if harden:
                    missing.append({
                        "segment_id": str(sid),
                        "reason": "missing_anchor",
                    })
                continue
            if loc in seen:
                continue
            seen.add(loc)
            facts.append({"doc_id": loc[0], "para_id": loc[1]})
    if harden and missing:
        acc = getattr(dossier, "accounting", None)
        if acc is None:
            dossier.accounting = {}
            acc = dossier.accounting
        bucket = acc.setdefault("anchor_stable", {})
        if not isinstance(bucket, dict):
            bucket = {}
            acc["anchor_stable"] = bucket
        prev = list(bucket.get("missing_anchor") or [])
        bucket["missing_anchor"] = prev + missing
        bucket["n_export_missing_anchor"] = len(bucket["missing_anchor"])
    return facts


def _supporting_facts_all(dossier: Dossier) -> list[dict]:
    """全案卷证据 → 段落（仅 headline 兜底时沿用；同源路径不用它）。"""
    return _facts_from_evidences(dossier, dossier.evidences)


def _majority_with_evidence(dossier: Dossier):
    """confidence.json 交的那类：status=majority 且 evidence_ids 非空的第一条。"""
    for con in dossier.conclusions:
        if con.status == "majority" and con.evidence_ids:
            return con
    return None


def _supporting_facts(dossier: Dossier) -> list[dict]:
    """与被交结论文本同源的支撑段落。

    有带证据的 majority 结论 → 只映射该结论的 evidence_ids；
    否则（headline 兜底）→ 沿用全案卷口径。
    """
    con = _majority_with_evidence(dossier)
    if con is not None:
        return _facts_from_evidences(dossier, dossier.evidences_of(con.id))
    return _supporting_facts_all(dossier)


def _conclusion_text(dossier: Dossier) -> str:
    """与 supporting_facts 同源：有带证据 majority 用其 statement；否则 headline 兜底。"""
    con = _majority_with_evidence(dossier)
    if con is not None:
        return con.statement.strip()
    return str((dossier.synthesis or {}).get("headline") or "").strip()


def _conclusion_support_diverged(dossier: Dossier) -> bool:
    """headline 兜底且本题没有任何带证据结论 → 文本与支撑不同源。"""
    return _majority_with_evidence(dossier) is None


def _claim_slots_disclosure(dossier: Dossier) -> dict | None:
    """C-72：开旗时把要点槽覆盖＋主席支撑旗写入 conclusions 行；关旗返回 None。

    不改 conclusion 文本、不拼宽 supporting_facts。
    """
    try:
        from app.core.claim_slots import claim_slots_enabled
    except ImportError:
        return None
    if not claim_slots_enabled():
        return None
    acc = (dossier.accounting or {}).get("claim_slots") or {}
    if not acc:
        # 导出侧兜底：未走管线钩子时当场算一次
        from app.core.claim_slots import apply_claim_slots
        acc = apply_claim_slots(dossier) or {}
    cov = acc.get("coverage") or {}
    flags = acc.get("chair_support_flags") or []
    return {
        "coverage_rate": cov.get("rate"),
        "n_slots": cov.get("n_slots"),
        "n_covered": cov.get("n_covered"),
        "rows": [
            {"id": r.get("id"), "label": r.get("label"),
             "status": r.get("status"), "detail": r.get("detail") or ""}
            for r in (acc.get("rows") or [])
            if isinstance(r, dict)
        ],
        "chair_support_flags": [
            {"value": f.get("value"), "detail": f.get("detail")}
            for f in flags if isinstance(f, dict)
        ],
    }


def _conflicting_facts(dossier: Dossier) -> tuple[list[dict], int, int]:
    """冲突侧：与被交结论对立一侧的段落。

    规则只一条——winner_id ∈ {a_id, b_id} 时取败方 evidence_ids 映射；
    tie／未分胜负／段落全取不到 ⇒ 不并入并计跳过。
    返回 (facts, skipped_tie, skipped_no_locator)。
    """
    facts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    skipped_tie = 0
    skipped_no_locator = 0
    for pair in dossier.conflicts or []:
        if not isinstance(pair, dict):
            continue
        a_id = str(pair.get("a_id") or "")
        b_id = str(pair.get("b_id") or "")
        res = pair.get("resolution") if isinstance(pair.get("resolution"), dict) else {}
        winner = str((res or {}).get("winner_id") or "")
        # tie／human_override 未分胜负／非法 winner → 跳过（计 tie 桶）
        if not a_id or not b_id or winner not in (a_id, b_id):
            skipped_tie += 1
            continue
        loser_id = b_id if winner == a_id else a_id
        mapped_any = False
        for ev in dossier.evidences_of(loser_id):
            for sid in ev.segment_ids:
                loc = _segment_locator(dossier, sid)
                if loc is None:
                    continue
                mapped_any = True
                if loc in seen:
                    continue
                seen.add(loc)
                facts.append({"doc_id": loc[0], "para_id": loc[1]})
        if not mapped_any:
            skipped_no_locator += 1
    return facts, skipped_tie, skipped_no_locator



def _gates_fired_note(gates: dict | None) -> str:
    """substitution 尾巴用：列出已触发硬门名；无 gates／全未触发写 none。"""
    if not isinstance(gates, dict) or not gates:
        return "none"
    fired = [
        name for name, g in gates.items()
        if isinstance(g, dict) and g.get("fired")
    ]
    return ",".join(fired) if fired else "none"


_CONF_FACE_DETAIL_ENV = "VERITAS_CONF_FACE_DETAIL"


def conf_face_detail_enabled(settings: Any | None = None) -> bool:
    """C-156：置信面披露旗。出厂默认开；显式 ``VERITAS_CONF_FACE_DETAIL=0``＝关。

    关＝confidence.json 与字段说明逐字节回到改前形态（本票「换分＝0」那条腿走这里）；
    开＝只往 confidence.json 加两类披露键（component_basis／recompute）＋字段说明两段
    现量文字；score、band、band_rel、公式、合式常量一个都不动。
    settings 为 None 时走 ``Settings.from_env()``（出厂默认＋env 叠加），
    不在无参路径里绕开出厂默认。
    """
    if settings is None:
        from app.config import Settings
        settings = Settings.from_env()
    if hasattr(settings, "conf_face_detail"):
        return bool(getattr(settings, "conf_face_detail"))
    v = (os.environ.get(_CONF_FACE_DETAIL_ENV) or "").strip().lower()
    if v in ("0", "false", "off", "no"):
        return False
    if v in ("1", "true", "on", "yes"):
        return True
    return True


def _printed_recompute(terms: dict, score: float) -> dict:
    """评委只拿「印在这行上的四位数」复算这条 score——与程序内部同一式子，不另发明算法。

    容差＝1e-4（第四位取整边界），这是取整误差的物理上限，不是拍的：
    每个分量先 round4，四位小数乘权重相加后与未取整值最多差若干 1e-4，
    再取四位，落点只可能在 ±1e-4 内。超出＝复现失败，本函数会把它如实标出来。
    """
    consts = aggregate_constants()
    w = consts["weights"]
    hg = consts["hard_gates"]
    raw = (
        w["b"]
        + w["s"] * float(terms.get("strength") or 0.0)
        + w["c"] * float(terms.get("coverage") or 0.0)
        + w["a"] * float(terms.get("agreement_factor") or 0.0)
        + w["h"] * float(terms.get("chain_for_aggregate") or 0.0)
    )
    raw = min(1.0, max(0.0, raw))
    g = terms.get("gates") if isinstance(terms.get("gates"), dict) else {}
    fired: list[str] = []
    capped = raw
    if isinstance(g.get("G2_no_evidence"), dict) and g["G2_no_evidence"].get("fired"):
        fired.append("G2_no_evidence")
        capped = 0.0
    if isinstance(g.get("G1_citation"), dict) and g["G1_citation"].get("fired"):
        fired.append("G1_citation")
        capped = min(capped, float(hg["G1_citation"]["cap"]))
    if isinstance(g.get("G3_premise_broken"), dict) and g["G3_premise_broken"].get("fired"):
        fired.append("G3_premise_broken")
        capped = min(capped, float(hg["G3_premise_broken"]["cap"]))
    expected = round(capped, 4)
    delta = round(abs(expected - float(score)), 4)
    return {
        "printed_weighted_sum": round(raw, 4),
        "gates_fired": fired or ["none"],
        "expected_score": expected,
        "reported_score": round(float(score), 4),
        "delta": delta,
        "tolerance": 0.0001,
        "reproducible": delta <= 0.0001,
        "rule": consts["recompute_rule"],
    }


def _conf_face_lines(rows: list[dict]) -> list[str]:
    """本次置信面现量三行（档分布／硬门触发／分量区分度）——数字当场数，不抄旧账。"""
    scores = [float(r.get("score") or 0.0) for r in rows]
    abs_c = band_count_dict(scores, absolute=True)
    rel_c = band_count_dict(scores, absolute=False)
    n = len(rows)
    fired: dict[str, int] = {"G1_citation": 0, "G2_no_evidence": 0, "G3_premise_broken": 0}
    for r in rows:
        g = (r.get("terms") or {}).get("gates")
        if not isinstance(g, dict):
            continue
        for k in fired:
            if isinstance(g.get(k), dict) and g[k].get("fired"):
                fired[k] += 1
    # 分量区分度：该分量在各行里出现过几个不同取值（1 个＝本次不提供区分度，如实说）
    distinct = {}
    for k in ("strength", "coverage", "agreement", "chain"):
        distinct[k] = len({json.dumps((r.get("terms") or {}).get(k), sort_keys=True) for r in rows})
    multi_author = sum(
        1 for r in rows
        if int(((r.get("component_basis") or {}).get("n_authors")) or 0) >= 2
    )
    bad = sum(1 for r in rows if (r.get("recompute") or {}).get("reproducible") is False)
    return [
        (
            f"置信面本次现量（confidence.json {n} 行）：绝对档 高 {abs_c['高']}／中 {abs_c['中']}／低 {abs_c['低']}；"
            f"分位档 高 {rel_c['高']}／中 {rel_c['中']}／低 {rel_c['低']}／不可分 {rel_c.get('不可分', 0)}。"
        ),
        (
            f"三道硬门本次触发行数＝G1 引文命中 {fired['G1_citation']}／G2 无证据 {fired['G2_no_evidence']}／"
            f"G3 前提破坏 {fired['G3_premise_broken']}（交卷面只收逐字命中的证据，G1 长期不触发＝实测结果，"
            "不是门被摘掉；阈值与封顶值在上方常量表里）。"
        ),
        (
            f"分量区分度本次取值数＝信源可信度 {distinct['strength']}／覆盖 {distinct['coverage']}／"
            f"一致性 {distinct['agreement']}／链完整性 {distinct['chain']}；"
            f"署名≥2 的结论 {multi_author} 条；按印出数复算失败（±1e-4 外）的行 {bad} 条。"
            "（一致性取值数＝1 表示本次没有跨分析师同组结论，该分量不贡献区分度——如实披露，不假装拉开）"
        ),
    ]


def _conf_constants_block() -> str:
    """把生产在用的合式常量表原样打到字段说明里（评委照这张表能算出同一个分）。"""
    consts = aggregate_constants()
    w = consts["weights"]
    return (
        "## 置信合式常量表（confidence.json 复算用；与程序内 `_AGG`／模块常量同一份，非手抄）\n"
        f"raw = clip01(b {w['b']} + s {w['s']}·strength + c {w['c']}·coverage "
        f"+ a {w['a']}·agreement_factor + h {w['h']}·chain_score)\n"
        "分量算法：strength＝等级权×信源可信度×因果加成×人工权重 的均值；"
        f"coverage＝{consts['component_constants']['coverage_floor']} + "
        f"{round(1 - consts['component_constants']['coverage_floor'], 4)}·(1 − exp(−(n−1)/"
        f"{consts['component_constants']['coverage_saturation'] - 1}))（n＝该结论证据条数，饱和于 "
        f"{consts['component_constants']['coverage_saturation']} 条）；"
        f"agreement_factor＝{consts['component_constants']['agreement_floor']} + "
        f"{round(1 - consts['component_constants']['agreement_floor'], 4)}·(署名数/编队人数)；"
        f"chain_score＝六环按适用项通过率（无从判定填 "
        f"{consts['component_constants']['chain_unknown']}）。\n"
        "硬门：" + json.dumps(consts["hard_gates"], ensure_ascii=False) + "\n"
        f"呈现档阈值：" + json.dumps(consts["band_thresholds"], ensure_ascii=False) + "\n"
        f"温度默认：" + json.dumps(consts["temperature_default"]) + "（＝不缩放；非 1.0 须显式启用，本次未启用）\n"
        "复算规则：" + consts["recompute_rule"] + "\n"
        "行内 `component_basis` 给的是该行的真数来源（证据条数／署名数／编队人数／证据等级／"
        "最弱一条强度／六环 applicable 与 broken），`recompute` 是「只拿本行印出的数复算」的结果与差值。\n"
    )


def _confidence_rows(question_id: str, dossier: Dossier) -> list[dict]:
    detail = conf_face_detail_enabled()  # 每案卷读一次，不在行循环里读配置
    n_panel = len(list(dossier.panel or []))
    rows = []
    for con in dossier.conclusions:
        if con.status != "majority":
            continue
        parts = dict(con.confidence_parts or {})
        score, terms = row_score_detail(parts)
        strength = terms["strength"]
        coverage = terms["coverage"]
        agreement = terms["agreement"]
        chain_num = terms["chain"]
        agreement_factor = terms["agreement_factor"]
        chain_factor = terms["chain_factor"]
        rows.append({
            "question_id": question_id,
            "conclusion_id": con.id,
            "信源可信度": strength,
            "证据数量与一致性": {
                "coverage": coverage,
                "agreement": agreement,
                "agreement_factor": agreement_factor,
            },
            "推理链完整性": chain_num,
            "formula": "clip01(b + s*strength + c*coverage + a*agreement_factor + h*chain_score) + hard gates",
            "terms": dict(terms),
            "substitution": (
                f"clip01(0.10 + 0.25*{strength} + 0.20*{coverage} + "
                f"0.15*{agreement_factor} + 0.30*{terms.get('chain_for_aggregate', chain_num)})"
                f" + gates[{_gates_fired_note(terms.get('gates'))}] = {score}"
            ),
            "score": score,
            "dossier_confidence": con.confidence,
            "band": band_of(score),
            "band_rule": BAND_RULE,
        })
        # C-116：旗开后置降档（不改 score）；披露 predicted_band／demote
        from app.core.conf_calib import conf_calib_enabled, gated_band
        if conf_calib_enabled():
            gated = gated_band(
                score, dossier=dossier, conclusion=con, enabled=True,
            )
            rows[-1]["predicted_band"] = gated["predicted_band"]
            rows[-1]["band"] = gated["band"]
            if gated["demoted"]:
                rows[-1]["demote_reasons"] = list(gated["demote_reasons"])
        # C-156：披露两类键（分数面零改动）——分量真数来源＋按印出数复算
        if detail:
            cd = parts.get("chain_detail") if isinstance(parts.get("chain_detail"), dict) else {}
            rows[-1]["component_basis"] = {
                "n_evidence": int(parts.get("n_evidence") or 0),
                "n_authors": int(parts.get("n_authors") or 0),
                "n_panel": n_panel,
                "n_panel_source": "dossier.panel" if n_panel else "案卷未记编队名单（不猜）",
                "levels": sorted(parts.get("levels") or []),
                "min_evidence_score": parts.get("min_evidence_score"),
                "chain_rings_applicable": list(cd.get("applicable") or []),
                "chain_rings_broken": list(cd.get("broken") or []),
                "chain_unknown": bool(cd.get("unknown")),
            }
            rows[-1]["recompute"] = _printed_recompute(terms, score)
    return rows


# C-46：冲突清单 statement 上限／单条记录字数上限（按 Unicode 码点计）
_C46_STMT_MAX = 120
_C46_RECORD_MAX = 800
_C46_TRUNC_MARK = "…（截断）"
_C46_SIZE_OMISSION = "单条记录超800字已截断"


def _c46_truncate_statement(text: str, limit: int = _C46_STMT_MAX) -> str:
    """逐字取自结论 statement；超 limit 截断，并在串内标 …（截断）。"""
    s = str(text or "")
    mark = _C46_TRUNC_MARK
    if len(s) <= limit:
        return s
    keep = max(0, limit - len(mark))
    return s[:keep] + mark


def _c46_side_entry(dossier: Dossier, conclusion_id: str, stmt_limit: int = _C46_STMT_MAX) -> dict:
    """一侧：{conclusion_id, statement, source_ids, para_ids}。statement 逐字取自结论。"""
    cid = str(conclusion_id or "")
    con = next((c for c in dossier.conclusions if c.id == cid), None)
    statement = ""
    source_ids: list[str] = []
    para_ids: list[str] = []
    if con is not None:
        statement = _c46_truncate_statement(con.statement, stmt_limit)
        seen_src: set[str] = set()
        seen_para: set[str] = set()
        for ev in dossier.evidences_of(cid):
            for sid in ev.segment_ids:
                loc = _segment_locator(dossier, sid)
                if loc is None:
                    continue
                doc_id, para_id = loc
                if doc_id not in seen_src:
                    seen_src.add(doc_id)
                    source_ids.append(doc_id)
                if para_id not in seen_para:
                    seen_para.add(para_id)
                    para_ids.append(para_id)
    return {
        "conclusion_id": cid,
        "statement": statement,
        "source_ids": source_ids,
        "para_ids": para_ids,
    }


def _c46_result_of(pair: dict, res: dict) -> dict:
    """结果：甲=a_id／乙=b_id；平局／未分胜负 → 并存不裁决 + winner_id=""。不许伪造胜方。"""
    a_id = str(pair.get("a_id") or "")
    b_id = str(pair.get("b_id") or "")
    winner = str((res or {}).get("winner_id") or "")
    if winner and winner == a_id:
        return {"outcome": "甲胜", "winner_id": winner, "tie": False}
    if winner and winner == b_id:
        return {"outcome": "乙胜", "winner_id": winner, "tie": False}
    return {"outcome": "并存不裁决", "winner_id": "", "tie": True}


def _c46_record_char_len(row: dict) -> int:
    return len(json.dumps(row, ensure_ascii=False))


def _c46_enforce_record_size(row: dict, omissions: list[str]) -> dict:
    """单条 ≤800 字。优先保留 statement 与 basis.type_applies／loser_excluded；
    顺序：basis 压扁 → ids 截短 → rationale → basis 文案压短 → 清空 basis → statement。"""
    if _c46_record_char_len(row) <= _C46_RECORD_MAX:
        return row
    mark = _C46_TRUNC_MARK
    if _C46_SIZE_OMISSION not in omissions:
        omissions.append(_C46_SIZE_OMISSION)
    row["omissions"] = list(omissions)

    def _ok() -> bool:
        return _c46_record_char_len(row) <= _C46_RECORD_MAX

    def _listing() -> list:
        v = row.get("冲突清单")
        return v if isinstance(v, list) else []

    def _shrink_ids(keep: int) -> None:
        for side in _listing():
            if not isinstance(side, dict):
                continue
            if isinstance(side.get("source_ids"), list):
                side["source_ids"] = list(side["source_ids"][:keep])
            if isinstance(side.get("para_ids"), list):
                side["para_ids"] = list(side["para_ids"][:keep])

    # 1) basis 压成 type_applies／loser_excluded（丢掉 strength 等大块）
    basis = row.get("basis")
    compact = None
    if isinstance(basis, dict) and basis:
        compact = {}
        for k in ("type_applies", "loser_excluded"):
            if k in basis:
                compact[k] = basis[k]
        if compact:
            row["basis"] = compact
            if _ok():
                return row

    # 2) ids 截短（此时仍尽量留着 compact basis）
    for keep in (3, 2, 1, 0):
        _shrink_ids(keep)
        if _ok():
            return row

    # 3) 二分压 rationale
    rat = str(row.get("rationale") or "")
    if rat:
        lo, hi = 0, len(rat)
        best = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            trial = (rat[:mid] + mark) if mid < len(rat) else rat
            row["rationale"] = trial
            if _ok():
                best = trial
                lo = mid + 1
            else:
                hi = mid - 1
        row["rationale"] = best
        if _ok():
            return row
        row["rationale"] = ""
        if _ok():
            return row

    # 4) 压短 type_applies／loser_excluded 文案（仍留键）
    if isinstance(row.get("basis"), dict) and row["basis"]:
        b = dict(row["basis"])
        for key in ("type_applies", "loser_excluded"):
            if key not in b:
                continue
            raw = str(b[key] or "")
            lo, hi = 0, len(raw)
            best = mark if raw else ""
            while lo <= hi:
                mid = (lo + hi) // 2
                trial = (raw[:mid] + mark) if mid < len(raw) else raw
                b[key] = trial
                row["basis"] = b
                if _ok():
                    best = trial
                    lo = mid + 1
                else:
                    hi = mid - 1
            b[key] = best
            row["basis"] = b
            if _ok():
                return row
        row["basis"] = ""
        if "basis" not in omissions:
            omissions.append("basis")
            row["omissions"] = list(omissions)
        if _ok():
            return row

    # 5) 最后才压 statement
    for lim in (90, 60, 40, 20, 0):
        for side in _listing():
            if isinstance(side, dict) and "statement" in side:
                raw = str(side.get("statement") or "")
                if raw.endswith(mark):
                    raw = raw[: -len(mark)]
                side["statement"] = _c46_truncate_statement(raw, lim)
        if _ok():
            return row

    row["omissions"] = [_C46_SIZE_OMISSION]
    return row


def _conflict_rows(question_id: str, dossier: Dossier) -> tuple[list[dict], list[str]]:
    rows = []
    omitted_any: list[str] = []
    for pair in dossier.conflicts or []:
        if not isinstance(pair, dict):
            continue
        res = pair.get("resolution") if isinstance(pair.get("resolution"), dict) else {}
        method = str(res.get("method") or "")
        basis = res.get("basis")
        rtype = res.get("resolution_type")
        restart = res.get("restart_condition")
        if restart is None:
            restart = res.get("重启条件")
        omissions = []
        for note in list(res.get("omissions") or []):
            text = str(note or "").strip()
            if text and text not in omissions:
                omissions.append(text)
        if basis is None or basis == "" or basis == {}:
            omissions.append("basis")
            basis = ""
        if rtype in (None, ""):
            omissions.append("resolution_type")
            rtype = METHOD_TO_RESOLUTION_TYPE.get(method, "其他")
        if restart in (None, ""):
            omissions.append("重启条件")
            restart = ""
        a_id = str(pair.get("a_id") or "")
        b_id = str(pair.get("b_id") or "")
        listing = [
            _c46_side_entry(dossier, a_id),
            _c46_side_entry(dossier, b_id),
        ]
        result = _c46_result_of(pair, res)
        row = {
            "question_id": question_id,
            "conflict_id": str(pair.get("id") or ""),
            "resolution_type": rtype,
            "basis": basis if basis is not None else "",
            "重启条件": restart if restart is not None else "",
            "method": method,
            "rationale": str(res.get("rationale") or ""),
            "冲突清单": listing,
            "结果": result,
            "omissions": omissions,
        }
        row = _c46_enforce_record_size(row, omissions)
        omitted_any.extend(omissions)
        rows.append(row)
    return rows, sorted(set(omitted_any))



def _evidence_has_causal_claim(ev) -> bool:
    """该证据是否携带因果主张（与 evidence 行附卡条件对齐）。"""
    declared = (getattr(ev, "declared_relation", "") or ev.relation.value)
    if ev.relation.value == "causation" or declared == "causation":
        return True
    if getattr(ev, "degraded_reason", ""):
        return True
    claim = getattr(ev, "causal_claim", None)
    if isinstance(claim, dict) and any(
            str(claim.get(k) or "").strip() for k in (
                "intervention", "outcome", "population", "counterfactual")):
        return True
    return False


def _causal_evidence_rows(question_id: str, dossier: Dossier) -> list[dict]:
    """每条含因果主张的结论一行；字段复用既有真名，confidence 复用现值。"""
    rows: list[dict] = []
    by_con: dict[str, list] = {}
    for ev in dossier.evidences:
        if not _evidence_has_causal_claim(ev):
            continue
        by_con.setdefault(ev.conclusion_id, []).append(ev)
    con_by_id = {c.id: c for c in dossier.conclusions}
    for cid, evs in by_con.items():
        con = con_by_id.get(cid)
        # 主张卡：首条非空 causal_claim；并列字段取同一条证据
        primary = None
        for ev in evs:
            claim = ev.causal_claim if isinstance(ev.causal_claim, dict) else None
            if claim and any(str(claim.get(k) or "").strip()
                             for k in ("intervention", "outcome",
                                       "population", "counterfactual")):
                primary = ev
                break
        if primary is None:
            primary = evs[0]
        claim = dict(primary.causal_claim) if isinstance(
            primary.causal_claim, dict) else {}
        refs: list[dict] = []
        seen_ref: set[tuple[str, str, str]] = set()
        for ev in evs:
            for sid in ev.segment_ids:
                loc = _segment_locator(dossier, sid)
                if loc is None:
                    continue
                doc_id, para_id = loc
                quote = str(ev.quote or "")
                key = (doc_id, para_id, quote)
                if key in seen_ref:
                    continue
                seen_ref.add(key)
                refs.append({
                    "doc_id": doc_id,
                    "para_id": para_id,
                    "quote": quote,
                })
        # confidence 复用现值：不调用 row_score_detail、不改合式
        conf_val = float(con.confidence) if con is not None else 0.0
        rows.append({
            "conclusion_id": cid,
            "question_id": question_id,
            "intervention": str(claim.get("intervention") or ""),
            "outcome": str(claim.get("outcome") or ""),
            "population": str(claim.get("population") or ""),
            "counterfactual": str(claim.get("counterfactual") or ""),
            "mechanism_completeness": (
                primary.mechanism_completeness or "correlation_only"),
            "missing_links": list(primary.missing_links or []),
            "design_tier": primary.design_tier or "claim_only",
            "degraded_reason": primary.degraded_reason or "",
            "evidence_refs": refs,
            "confidence": conf_val,
        })
    return rows


def export_official(runs: list[tuple[dict, Dossier]], out_dir: Path) -> dict[str, Path]:
    """按 question_id 汇总五份 JSON 与字段说明。runs 元素是 (问题, 案卷)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence: list[dict] = []
    conclusions: list[dict] = []
    confidence: list[dict] = []
    conflicts: list[dict] = []
    causal_evidence: list[dict] = []
    omission_notes: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    deduped = 0
    dropped_ids: list[str] = []
    kept_bare_ids: list[str] = []
    diverged_ids: list[str] = []
    total_skip_tie = 0
    total_skip_noloc = 0
    n_questions = len(runs)
    for question, dossier in runs:
        qid = str(question["question_id"])
        rows, dropped = _evidence_rows(dossier, seen)
        evidence.extend(rows)
        deduped += dropped
        supporting = _supporting_facts(dossier)
        conflicting, skip_tie, skip_noloc = _conflicting_facts(dossier)
        total_skip_tie += skip_tie
        total_skip_noloc += skip_noloc
        diverged = _conclusion_support_diverged(dossier)
        # 题数 ≥3 才丢裸结论：2.3 是 15/N，N=2 时丢一题比 2.4.1 归零更亏。
        if n_questions >= 3 and not supporting:
            dropped_ids.append(qid)
        else:
            if not supporting:
                kept_bare_ids.append(qid)
            if diverged:
                diverged_ids.append(qid)
            row = {
                "question_id": qid,
                "question": str(question["question"]),
                "conclusion": _conclusion_text(dossier),
                "supporting_facts": supporting,
                "conflicting_facts": conflicting,
            }
            # C-72：仅开 VERITAS_CLAIM_SLOTS 时写入披露键；关旗键缺席＝与改前 sha 相同
            disc = _claim_slots_disclosure(dossier)
            if disc is not None:
                row["claim_slots_disclosure"] = disc
            conclusions.append(row)
        confidence.extend(_confidence_rows(qid, dossier))
        conflict_rows, omitted = _conflict_rows(qid, dossier)
        conflicts.extend(conflict_rows)
        omission_notes.extend(omitted)
        causal_evidence.extend(_causal_evidence_rows(qid, dossier))
    gate_line = _bare_gate_line(n_questions, dropped_ids, kept_bare_ids)
    # 早退只在 pipeline 写这一句 confidence_note；此处只读，不改早退条件。
    n_slot = sum(
        1 for _, dossier in runs
        if (dossier.accounting or {}).get("confidence_note")
        == "议题槽位未齐，未发起模型研判")
    slot_line = f"本次 {n_slot} 题因槽位未齐未调用分析师。"
    dedup_line = f"evidence.json 去重 {deduped} 行（键 doc_id, para_id, quote）。"
    face = conclusion_face_pooled([d for _, d in runs])
    face_line = format_conclusion_face_line(face, surface="本次提交物 pooled")
    if diverged_ids:
        div_ids = "、".join(diverged_ids)
        diverge_line = (
            f"文本与支撑不同源（headline 兜底）的 question_id：{div_ids}。"
        )
    else:
        diverge_line = "文本与支撑不同源（headline 兜底）的 question_id：（无）。"
    conflict_skip_line = (
        f"冲突侧跳过：tie／未分胜负 {total_skip_tie} 对；"
        f"段落取不到 {total_skip_noloc} 对。"
    )
    print(gate_line)
    print(slot_line)
    print(dedup_line)
    print(face_line)
    print(diverge_line)
    print(conflict_skip_line)

    # C-20：band_rel 必须看整份提交物 pooled，不能在 _confidence_rows（单案卷）里算
    pooled = [float(r["score"]) for r in confidence]
    rel_rule = band_rel_rule_of(pooled)
    for row in confidence:
        row["band_rel"] = band_rel_of(pooled, float(row["score"]))
        row["band_rel_rule"] = rel_rule

    paths = {
        "evidence": out_dir / "evidence.json",
        "conclusions": out_dir / "conclusions.json",
        "confidence": out_dir / "confidence.json",
        "conflict_resolution": out_dir / "conflict_resolution.json",
        "causal_evidence": out_dir / "causal_evidence.json",
        "notes": out_dir / "字段说明.md",
    }
    paths["evidence"].write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["conclusions"].write_text(
        json.dumps(conclusions, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["confidence"].write_text(
        json.dumps(confidence, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["conflict_resolution"].write_text(
        json.dumps({
            "records": conflicts,
            "omissions": (
                (sorted(set(omission_notes)) or ["basis", "重启条件"])
                + [slot_line]
            ),
            "detail": "basis 与重启条件在 Resolution.to_dict() 中不存在，已留空；"
                      "resolution_type 仅由 method 映射表得到，未另算证据强度",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8")
    paths["causal_evidence"].write_text(
        json.dumps(causal_evidence, ensure_ascii=False, indent=2),
        encoding="utf-8")
    # C-115：旗开且案卷有 conflict_trace → 导出回放面（旗关不写文件）
    from app.core.conflict_trace import conflict_trace_enabled, summarize_trace
    if conflict_trace_enabled():
        merged: list[dict] = []
        gate_sections: list[dict] = []
        rebuttal_sections: list[dict] = []
        arbitration_sections: list[dict] = []
        for question, dossier in runs:
            bucket = (getattr(dossier, "accounting", None) or {}).get(
                "conflict_trace")
            if isinstance(bucket, dict):
                for row in bucket.get("records") or []:
                    if isinstance(row, dict):
                        item = dict(row)
                        item["question_id"] = str(
                            (question or {}).get("question_id") or "")
                        merged.append(item)
            # C-145：归并硬约束闸否决事件随面走（每题一节）
            mg = (getattr(dossier, "accounting", None) or {}).get("merge_gate")
            if isinstance(mg, dict):
                item = dict(mg)
                item["question_id"] = str(
                    (question or {}).get("question_id") or "")
                gate_sections.append(item)
            # C-147：多轮质证留痕随面走（每题一节）
            rb = (getattr(dossier, "accounting", None) or {}).get("rebuttal")
            if isinstance(rb, dict):
                item = dict(rb)
                item["question_id"] = str(
                    (question or {}).get("question_id") or "")
                rebuttal_sections.append(item)
            # C-148：仲裁路由／轻裁留痕随面走（每题一节）
            arb = (getattr(dossier, "accounting", None) or {}).get(
                "arbitration")
            if isinstance(arb, dict):
                item = dict(arb)
                item["question_id"] = str(
                    (question or {}).get("question_id") or "")
                arbitration_sections.append(item)
        # C-143：借 C-123 窄修②——旗开必写回放面（空态也写＋原因句）。
        # 「本次未检出」不等于「资料无冲突」；零对撞静默＝两态在产物面上同形。
        from app.core.conflict_trace import TRIAGE_CLASSES
        detail = ("C-115 三类冲突＋处置留痕回放面；"
                  "conflict_class∈{same_window,cross_day,unknown_time,"
                  "unclassified}；disposition∈{keep,dissent,undecided}；"
                  "C-146 分流轴 triage_class∈{"
                  + ",".join(sorted(TRIAGE_CLASSES))
                  + "}（与 conflict_class 正交，只贴标签不改判）")
        paths["conflict_trace"] = out_dir / "conflict_trace.json"
        n_gate_blocked = sum(int(g.get("n_blocked") or 0)
                             for g in gate_sections)
        if n_gate_blocked:
            detail = detail + "；merge_gate＝C-145 归并硬约束闸否决事件" \
                              "（缺主体／缺指标／不可核验／极性对立不放行为「已一致」）"

        def _fold_rebuttal(target: dict) -> None:
            # C-147：多轮质证留痕随面走（顶层独立节；多题聚合求和）
            if not rebuttal_sections:
                return
            if len(rebuttal_sections) == 1:
                target["rebuttal"] = rebuttal_sections[0]
                return
            esc_rows = [
                dict(p, question_id=s.get("question_id", ""))
                for s in rebuttal_sections
                for p in (s.get("pairs") or [])]
            target["rebuttal"] = {
                "n_questions": len(rebuttal_sections),
                "rounds_requested": max(
                    int(s.get("rounds_requested") or 0)
                    for s in rebuttal_sections),
                "n_pairs": sum(int(s.get("n_pairs") or 0)
                               for s in rebuttal_sections),
                "n_escalated": sum(int(s.get("n_escalated") or 0)
                                   for s in rebuttal_sections),
                "pairs": esc_rows,
                "empty_state": all(bool(s.get("empty_state"))
                                   for s in rebuttal_sections),
            }

        def _fold_arbitration(target: dict) -> None:
            # C-148：仲裁路由／轻裁留痕随面走（顶层独立节；多题聚合求和）
            if not arbitration_sections:
                return
            if len(arbitration_sections) == 1:
                target["arbitration"] = arbitration_sections[0]
                return
            arb_rows = [
                dict(p, question_id=s.get("question_id", ""))
                for s in arbitration_sections
                for p in (s.get("pairs") or [])]
            target["arbitration"] = {
                "n_questions": len(arbitration_sections),
                "n_pairs": sum(int(s.get("n_pairs") or 0)
                               for s in arbitration_sections),
                "n_light": sum(int(s.get("n_light") or 0)
                               for s in arbitration_sections),
                "n_llm": sum(int(s.get("n_llm") or 0)
                             for s in arbitration_sections),
                "pairs": arb_rows,
                "empty_state": all(bool(s.get("empty_state"))
                                   for s in arbitration_sections),
            }

        if merged:
            payload: dict = {
                "records": merged,
                "summary": summarize_trace(merged),
                "detail": detail,
            }
            if gate_sections:
                payload["merge_gate"] = (
                    gate_sections[0] if len(gate_sections) == 1
                    else {"n_questions": len(gate_sections),
                          "n_groups_checked": sum(
                              int(g.get("n_groups_checked") or 0)
                              for g in gate_sections),
                          "n_blocked": sum(
                              int(g.get("n_blocked") or 0)
                              for g in gate_sections),
                          "blocked": [
                              dict(b, question_id=g.get("question_id", ""))
                              for g in gate_sections
                              for b in (g.get("blocked") or [])]})
            _fold_rebuttal(payload)
            _fold_arbitration(payload)
            paths["conflict_trace"].write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            n_q = len(runs)
            empty_payload: dict = {
                "records": [],
                "summary": summarize_trace([]),
                "empty_state": True,
                "detail": detail + f" 本次 {n_q} 题均未检出冲突对或事实对撞"
                          "（未检出＝本次研判没有碰到，不等于资料无冲突）。",
            }
            if gate_sections:
                empty_payload["merge_gate"] = (
                    gate_sections[0] if len(gate_sections) == 1
                    else {"n_questions": len(gate_sections),
                          "n_groups_checked": sum(
                              int(g.get("n_groups_checked") or 0)
                              for g in gate_sections),
                          "n_blocked": sum(
                              int(g.get("n_blocked") or 0)
                              for g in gate_sections),
                          "blocked": [
                              dict(b, question_id=g.get("question_id", ""))
                              for g in gate_sections
                              for b in (g.get("blocked") or [])]})
            _fold_rebuttal(empty_payload)
            _fold_arbitration(empty_payload)
            paths["conflict_trace"].write_text(
                json.dumps(empty_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    detail_block = ""
    conf_lines: list[str] = []
    if conf_face_detail_enabled():
        detail_block = "\n" + _conf_constants_block()
        conf_lines = _conf_face_lines(confidence)
    notes_tail = "".join(line + "\n" for line in conf_lines)
    paths["notes"].write_text(
        _FIELD_NOTES + detail_block + "\n## 本次导出\n" + gate_line + "\n"
        + slot_line + "\n" + dedup_line + "\n" + face_line + "\n"
        + diverge_line + "\n" + conflict_skip_line + "\n" + notes_tail,
        encoding="utf-8")
    return paths
