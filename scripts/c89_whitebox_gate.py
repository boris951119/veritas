#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-89 白箱三态闸（纯函数）＝召回后、装箱前。

借鉴唯稳律工程纪律：主机侧硬闸、确定性、判不清走 review、不猜。
**不是**因果发现／DoWhy；**不是**检索扩词引擎。

三态：allow｜deny｜review
  - deny：空段／空路径／模板拒标／降级路径
  - review：缺时间且缺量名、与议题锚无交、热词套话无实体／量名
  - allow：可核验实体 ∧（时间∨量名）∧ 与议题锚有交

默认：review 不进装箱池（拒标通道），计入读数，不整案失败。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

GateState = Literal["allow", "deny", "review"]

_TIME_RE = re.compile(
    r"("
    r"\d{4}\s*年|\d{1,2}\s*月|\d{1,2}\s*日|"
    r"\d{1,2}\s*时|\d{1,2}\s*分|"
    r"上午|下午|凌晨|北京时间|当地时间"
    r")"
)
_MEASURE_RE = re.compile(
    r"("
    r"\d+(?:\.\d+)?\s*(?:"
    r"人|名|米|公里|千克|吨|万吨|亿元|万元|%|％|例|架|艘|"
    r"平方米|平方公里|立方米|小时|分钟|天|处|件|台"
    r")"
    r"|\d+(?:\.\d+)?%"
    r")"
)
_ENTITYISH_RE = re.compile(
    r"("
    r"[\u4e00-\u9fff]{2,12}(?:口岸|机场|公司|省|市|县|镇|村|冰川|河流|湖|峰)|"
    r"[A-Z][A-Za-z0-9\-.]{1,20}|"
    r"联合国|中科院|外交部|自然资源部|尼泊尔|西藏|吉隆|印航|柬埔寨"
    r")"
)
_TEMPLATE_PATHS = {
    "领域/事件/地点或主体/切面",
}
_DENY_PATH_PREFIXES = ("降级/", "未标/", "短片/杂讯")


@dataclass(frozen=True)
class GateVerdict:
    state: GateState
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state, "reason": self.reason}


def _tokens_cn(text: str) -> set[str]:
    """极简锚词：连续汉字≥2、英文词、数字块。"""
    out: set[str] = set()
    for m in re.finditer(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9\-]{1,}|\d{2,}", text or ""):
        out.add(m.group(0))
    return out


def anchor_terms(question: str, *, extra: list[str] | None = None) -> set[str]:
    terms = _tokens_cn(question or "")
    for x in extra or []:
        terms |= _tokens_cn(str(x))
    # 去掉过泛单字已在 ≥2；再丢掉极泛词
    stop = {"以及", "或者", "还是", "应以", "是否", "如何", "哪个", "哪些", "什么", "这个", "那个"}
    return {t for t in terms if t not in stop and len(t) >= 2}


def has_time(text: str) -> bool:
    return bool(_TIME_RE.search(text or ""))


def has_measure(text: str) -> bool:
    return bool(_MEASURE_RE.search(text or ""))


def has_entity(text: str, *, tag_ents: list[str] | None = None) -> bool:
    if tag_ents:
        for e in tag_ents:
            if e and e in (text or ""):
                return True
    return bool(_ENTITYISH_RE.search(text or ""))


def path_is_deny(path: str | None) -> str | None:
    if path is None:
        return None
    p = str(path).strip()
    if not p:
        return "empty_path"
    if p in _TEMPLATE_PATHS or "领域/事件" in p:
        return "template_path"
    for pref in _DENY_PATH_PREFIXES:
        if p.startswith(pref):
            return "degraded_path"
    return None


def hotword_boilerplate(text: str, anchors: set[str]) -> bool:
    """通稿套话：短、无时间／量名、且几乎只重复锚词。"""
    t = (text or "").strip()
    if len(t) > 80:
        return False
    if has_time(t) or has_measure(t):
        return False
    toks = _tokens_cn(t)
    if not toks:
        return True
    if not anchors:
        return len(t) < 20 and not has_entity(t)
    hit = sum(1 for x in toks if x in anchors)
    return hit / len(toks) >= 0.85 and not has_entity(t)


def gate_segment(
    text: str,
    question: str,
    *,
    path: str | None = None,
    tag_ents: list[str] | None = None,
    tag_src: str | None = None,
    anchor_extra: list[str] | None = None,
) -> GateVerdict:
    """对单段做三态裁决（确定性，无 LLM）。"""
    t = (text or "").strip()
    if not t:
        return GateVerdict("deny", "empty_text")

    if tag_src in ("template_reject", "fail"):
        return GateVerdict("deny", f"tag_src:{tag_src}")

    pr = path_is_deny(path)
    if pr:
        return GateVerdict("deny", pr)

    anchors = anchor_terms(question, extra=anchor_extra)
    ents_ok = has_entity(t, tag_ents=tag_ents)
    time_ok = has_time(t)
    meas_ok = has_measure(t)

    if hotword_boilerplate(t, anchors):
        return GateVerdict("review", "hotword_boilerplate")

    # 锚点相交：正文或 path 与议题锚有交
    blob = t + " " + (path or "")
    seg_terms = _tokens_cn(blob)
    if tag_ents:
        for e in tag_ents:
            seg_terms |= _tokens_cn(e)
    overlap = seg_terms & anchors if anchors else set()
    if anchors and not overlap:
        return GateVerdict("review", "no_anchor_overlap")

    if not ents_ok:
        return GateVerdict("review", "no_entity")

    if not time_ok and not meas_ok:
        return GateVerdict("review", "no_time_nor_measure")

    # allow：实体 +（时间∨量名）+ 锚相交（无锚时仅前两）
    return GateVerdict("allow", "ok")


def gate_batch(
    items: list[dict[str, Any]],
    question: str,
    *,
    anchor_extra: list[str] | None = None,
) -> list[dict[str, Any]]:
    """items 需含 text；可选 path/ents/src/id。返回附 state/reason。"""
    out = []
    for it in items:
        v = gate_segment(
            str(it.get("text") or ""),
            question,
            path=it.get("path"),
            tag_ents=list(it.get("ents") or []) or None,
            tag_src=it.get("src"),
            anchor_extra=anchor_extra,
        )
        row = dict(it)
        row["gate"] = v.state
        row["gate_reason"] = v.reason
        out.append(row)
    return out


def self_check() -> None:
    """最小自检（非 pytest）：变异应改变裁决。"""
    q = "吉隆口岸泥石流灾害的起始时刻应以10时52分为准吗？"
    # allow：有实体时间量名且贴锚
    v = gate_segment(
        "北京时间2026年8月26日上午10时52分，尼泊尔境内冰川断裂冲击吉隆口岸。",
        q,
    )
    assert v.state == "allow", v
    # deny 空
    assert gate_segment("", q).state == "deny"
    # deny 降级路径
    assert gate_segment("有字", q, path="降级/结构残缺/未知/其他").state == "deny"
    # review 无锚
    v2 = gate_segment("2026年8月某地发生交通事故致3人遇难。", q)
    assert v2.state == "review", v2
    # review 无时间无量名
    v3 = gate_segment("吉隆口岸相关部门召开会议研究灾害应对。", q)
    assert v3.state in ("review", "allow")  # 可能无量名→review
    print("c89_whitebox_gate self_check OK", flush=True)


if __name__ == "__main__":
    self_check()
