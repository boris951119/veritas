"""机械核对汇总层：一次扫描，统一 flag 口径，供管线/工作台/报告消费。

flag 不持久化——每次加载即时重算（derived view）：人工修改与文件篡改
天然被覆盖，「改数字即红」与「人工修改引入未溯源内容」都是同一套
机制的自然结果，不存在新旧状态不一致的问题。
"""

from __future__ import annotations

from app.core.causal_claim import audit_causal_claim_missing
from app.core.discourse_check import (
    audit_causation_support,
    audit_discourse,
    audit_hedge,
    audit_level_consistency,
    audit_level_tone,
)
from app.core.evidence import Dossier
from app.core.numeric_check import audit_conservation, audit_counting, audit_numeric
from app.core.premise_check import premise_flags
from app.core.dup_check import near_dup_flags
from app.core.question_check import question_flag
from app.core.scope_check import audit_scope
from app.core.claim_check import (
    audit_bare_percent,
    audit_unit_mismatch,
    audit_unverified_sources,
)
from app.core.temporal_check import audit_temporal
from app.core.untrusted import scan_injections
from app.core.warrant_check import audit_parallel_coverage, audit_warrant_theme

KIND_LABEL: dict[str, str] = {
    "calc": "计算复算不符",
    "provenance": "来源外数字",
    "counting": "计数断言无法复核",
    "merge_conservation": "归并概括漂移",
    "rebut_quote": "质证引文未命中",
    "rebut_ref": "质证引用不存在的编号",
    "arbiter_ref": "仲裁理由引用不存在的编号",
    "hedge": "低可信信源配断言语气",
    "level_tone": "措辞强度超过证据等级",
    "level_consistency": "证据等级与信源类型不符",
    "causation_support": "因果标注缺乏机制词支撑",
    "causal_claim_missing": "因果主张卡不完整已降级",
    "warrant_theme": "理由与主张脱节",
    "parallel_coverage": "并列要点覆盖不全",
    "chair_support_gap": "主席采纳要点未进提交支撑",
    "stale": "引用旧时点资料",
    "as_of": "结论未锚定时点",
    "injection": "疑似指令注入内容",
    "near_dup": "疑似同源转述",
    "question": "议题表述待聚焦",
    "premise": "议题前提未被资料覆盖",
    "percent_no_base": "涨跌百分比未见基数",
    "unit_mismatch": "人民币与美元口径混用",
    "source_unverified": "信源出处未核验",
    "scope": "声称范围却无覆盖声明",
    "external_prior": "外部先验未与案卷核对",
    "precedent_time": "同类事件时点未排序",
    "repeat_report_time": "重复报道型时点",
}


def audit_all(dossier: Dossier) -> list[dict]:
    """全部零 LLM 机械闸一次扫描：前提 + 计算/溯源/计数 + 守恒 + 话语
    + 时序 + 范围诚实 + 输入风险（注入/同源）+ 外部先验。"""
    from app.core.precedent import audit_external_prior, audit_repeat_report

    return [
        *([question_flag(dossier.question)] if question_flag(dossier.question)
          else []),
        *premise_flags(dossier),
        *scan_injections(dossier),
        *near_dup_flags(dossier),
        *audit_numeric(dossier),
        *audit_counting(dossier),
        *audit_conservation(dossier),
        *audit_scope(dossier),
        *audit_discourse(dossier),
        *audit_hedge(dossier),
        *audit_level_tone(dossier),
        *audit_level_consistency(dossier),
        *audit_causation_support(dossier),
        *audit_causal_claim_missing(dossier),
        *audit_warrant_theme(dossier),
        *audit_parallel_coverage(dossier),
        *_chair_support_audit_flags(dossier),
        *audit_temporal(dossier),
        *audit_bare_percent(dossier),
        *audit_unit_mismatch(dossier),
        *audit_unverified_sources(dossier),
        *audit_external_prior(dossier),
        *audit_repeat_report(dossier),
    ]


def _chair_support_audit_flags(dossier: Dossier) -> list[dict]:
    """C-72 件②：读 accounting 或当场重算主席支撑旗（关旗 → []）。"""
    try:
        from app.core.claim_slots import (
            chair_support_flags, claim_slots_enabled,
        )
    except ImportError:
        return []
    if not claim_slots_enabled():
        return []
    acc = (dossier.accounting or {}).get("claim_slots") or {}
    cached = acc.get("chair_support_flags")
    if isinstance(cached, list):
        return list(cached)
    return chair_support_flags(dossier)


def summarize(flags: list[dict], not_evaluated: list[dict] | None = None) -> dict:
    """flag 清单 → 计数摘要（哈希链事件与工作台顶栏用）。

    `not_evaluated` 传进来时，摘要多两栏：`n_not_evaluated` 与 `clean`。
    `clean` 才是「无警示」这件事的诚实说法——**有闸未执行时它必须为假**。
    """
    by_kind: dict[str, int] = {}
    for f in flags:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    ne = not_evaluated or []
    return {
        "n_flags": len(flags),
        "n_high": sum(1 for f in flags if f["severity"] == "high"),
        "n_medium": sum(1 for f in flags if f["severity"] == "medium"),
        "by_kind": by_kind,
        "n_not_evaluated": len(ne),
        "not_evaluated_kinds": sorted(n["kind"] for n in ne),
        # 「查过且干净」与「压根没查」不能共用一个词
        "clean": not flags and not ne,
    }


def audit_scan(dossier: Dossier) -> dict:
    """一次扫描出两件事：亮了哪些灯（flags）+ 哪些闸本次没进场（not_evaluated）。

    以前只有 `audit_all`，于是「零警示」既可能是真干净，也可能是全部免检——
    2026-10-13 实测计数闸在 32/34 份存量产物里一个对象都没碰到。
    """
    from app.core.gate_applicability import not_evaluated as _not_evaluated

    flags = audit_all(dossier)
    ne = _not_evaluated(dossier)
    return {"flags": flags, "not_evaluated": ne, "summary": summarize(flags, ne)}
