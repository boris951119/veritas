"""模型画像探测：用一次真实调用给任意接入模型打「纪律遵从」分。

用户接什么模型是未知的（评审可能自带网关）——系统不能把提示词纪律
押在「模型会听话」上。本模块用**一次**低成本探测调用，让待测模型对
一个微型案卷做一次研判，再用现成的零 LLM 机械闸给回复打分：

- 引文是否逐字命中（citation 闸复用）；
- 推导数字是否写了显式算式（calc 纪律）；
- 低可信信源下是否用了转述语气（hedge 纪律）。

≥2 项通过 → compliant 档（建议性纪律有效，照常注入）；
<2 项 → noncompliant 档（改注入强化版规则 + 结构化 derived 字段 +
打回修复环）。探测失败/关闭 → standard 档（维持现状）。
全程机械判分，与具体模型解耦——换任何模型，分档自动重来。
"""

from __future__ import annotations

import re

from app.agents.base import extract_json
from app.core.citation_check import check_quote
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.llm.model_client import ModelClient

_PROBE_SYSTEM = """你是情报分析师。基于下方唯一资料，输出恰好 1 条结论的 JSON。

要求：
1. quote 必须是对资料原文的逐字摘录，一个字都不能改；
2. 若结论含推导数字（如占比、差额），必须在对应 evidence 的 note 里写显式算式，格式「计算:a/b=c%」；
3. 该资料来自网友帖子（低可信），结论措辞必须用转述语气（如「有网友称」「疑似」）。

输出 JSON（不要输出任何其他文字）：
{"conclusions": [{"statement": "…", "evidence": [{"quote": "…", "segment_id": "SRC-P#s1", "relation": "correlation", "level": "D", "note": "…"}]}]}

资料：
[SRC-P#s1] 网友帖子称：该厂去年营收1200万元，其中海外收入300万元，产能利用率约65%，较前年下滑两成。"""

_HEDGE_RE = re.compile(r"报道称|据报道|据悉|疑似|传闻|网友称|未经官方证实|尚待|或涉")


def _probe_dossier() -> Dossier:
    d = Dossier(question="该厂经营状况如何？")
    src = Source.create("网友帖子", SourceType.WEB, id="SRC-P")
    src.segments.append(Segment(
        id="SRC-P#s1", source_id="SRC-P",
        text="网友帖子称：该厂去年营收1200万元，其中海外收入300万元，"
             "产能利用率约65%，较前年下滑两成。"))
    d.add_source(src)
    return d


def probe_model(client: ModelClient, model: str) -> dict:
    """探测一次 → {tier, scores, model}；任何异常向上抛（调用方降级）。"""
    response = client.chat(model, [
        {"role": "system", "content": _PROBE_SYSTEM},
        {"role": "user", "content": "请输出 JSON。"},
    ], json_mode=True)
    data = extract_json(response.content)
    items = [x for x in (data.get("conclusions") or []) if isinstance(x, dict)]
    if not items:
        return {"tier": "noncompliant", "scores": {"citation": False,
                                                   "calc": False, "hedge": False},
                "model": model}
    item = items[0]
    evs = [e for e in (item.get("evidence") or []) if isinstance(e, dict)]

    # 引文闸（复用 citation_check 归一化口径）
    citation_ok = bool(evs) and any(
        check_quote(str(e.get("quote") or ""), _probe_dossier().sources[0].segments[0].text).ok
        for e in evs)
    # calc 纪律：结论含数字时 note 是否写了算式
    statement = str(item.get("statement") or "")
    calc_ok = (not re.search(r"\d", statement)) or any(
        re.search(r"计算\s*[:：]", str(e.get("note") or "")) for e in evs)
    # hedge 纪律：低可信信源下是否转述
    hedge_ok = bool(_HEDGE_RE.search(statement))

    scores = {"citation": citation_ok, "calc": calc_ok, "hedge": hedge_ok}
    tier = "compliant" if sum(scores.values()) >= 2 else "noncompliant"
    return {"tier": tier, "scores": scores, "model": model}
