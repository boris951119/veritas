"""机械核对汇总层：一次扫描，统一 flag 口径，供管线/工作台/报告消费。

flag 不持久化——每次加载即时重算（derived view）：人工修改与文件篡改
天然被覆盖，「改数字即红」与「人工修改引入未溯源内容」都是同一套
机制的自然结果，不存在新旧状态不一致的问题。
"""

from __future__ import annotations

from app.core.discourse_check import audit_discourse
from app.core.evidence import Dossier
from app.core.numeric_check import audit_conservation, audit_numeric
from app.core.premise_check import premise_flags

KIND_LABEL: dict[str, str] = {
    "calc": "计算复算不符",
    "provenance": "来源外数字",
    "merge_conservation": "归并概括漂移",
    "rebut_quote": "质证引文未命中",
    "rebut_ref": "质证引用不存在的编号",
    "arbiter_ref": "仲裁理由引用不存在的编号",
    "premise": "议题前提未被资料覆盖",
}


def audit_all(dossier: Dossier) -> list[dict]:
    """全部零 LLM 机械闸一次扫描：前提 + 计算/溯源 + 守恒 + 话语。"""
    return [
        *premise_flags(dossier),
        *audit_numeric(dossier),
        *audit_conservation(dossier),
        *audit_discourse(dossier),
    ]


def summarize(flags: list[dict]) -> dict:
    """flag 清单 → 计数摘要（哈希链事件与工作台顶栏用）。"""
    by_kind: dict[str, int] = {}
    for f in flags:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    return {
        "n_flags": len(flags),
        "n_high": sum(1 for f in flags if f["severity"] == "high"),
        "n_medium": sum(1 for f in flags if f["severity"] == "medium"),
        "by_kind": by_kind,
    }
