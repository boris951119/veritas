"""MCP 澄清协议端到端（零 LLM）：调用方智能体 ≤2 轮回环。

协议（app/mcp_server._attach_preflight / question_check）：
1. 首次 run_* 附 preflight.needs_clarification；
2. 调用方把清单问终端用户，携更明确议题重调（计 1 轮）；
3. 至多 2 轮；仍不清则以当前议题继续，报告靠 kind=question 披露。
"""

from __future__ import annotations

from app.core.question_check import question_preflight
from app.mcp_server import _attach_preflight


def _rounds(start: str, replies: list[str], *, max_rounds: int = 2) -> dict:
    """模拟 MCP 调用方：按澄清清单改写议题，≤max_rounds 后停下。"""
    q = start
    history = []
    for i in range(max_rounds + 1):
        pf = question_preflight(q)
        tips = list(pf.get("clarify") or [])
        history.append({"q": q, "tier": pf["tier"], "tips": tips})
        if not tips or pf["tier"] == "clear":
            return {"final": q, "rounds_used": i, "stopped": "clear",
                    "history": history, "preflight": pf}
        if i >= max_rounds:
            return {"final": q, "rounds_used": i, "stopped": "max_rounds",
                    "history": history, "preflight": pf}
        # 调用方「问用户」后拿到的下一版议题
        q = replies[i] if i < len(replies) else q
    return {"final": q, "rounds_used": max_rounds, "stopped": "max_rounds",
            "history": history, "preflight": question_preflight(q)}


def test_vague_question_emits_clarification_tips():
    pf = question_preflight("分析一下这个行业整体情况")
    assert pf["tier"] in ("vague", "ambiguous", "empty")
    assert pf["clarify"]


def test_attach_preflight_exposes_two_round_protocol():
    result = _attach_preflight("他怎么样？", {"conclusions": []})
    pf = result["preflight"]
    assert pf["needs_clarification"]
    assert "2" in pf["protocol"]
    assert pf["tier"] != "clear"
    assert "readback" in pf


def test_clarify_loop_reaches_clear_within_two_rounds():
    out = _rounds(
        "分析一下这个行业",
        replies=[
            "该项目回款怎么样？",                 # 仍含指代 → 第 1 轮
            "客户B 2024 年回款率是多少？",        # 清晰 → 第 2 轮内收口
        ],
    )
    assert out["stopped"] == "clear"
    assert 1 <= out["rounds_used"] <= 2
    assert out["preflight"]["tier"] == "clear"
    assert not out["preflight"]["clarify"]


def test_clarify_loop_stops_at_max_rounds_and_continues():
    """2 轮仍不清 → 以当前最佳解读继续（调用方责任，不无限反问）。"""
    out = _rounds(
        "他怎么样？",
        replies=["这个项目呢？", "那个情况如何？"],
        max_rounds=2,
    )
    assert out["stopped"] == "max_rounds"
    assert out["rounds_used"] == 2
    assert out["preflight"]["tier"] != "clear"
    # 协议仍要求披露，不吞掉歧义
    assert out["preflight"]["clarify"] or out["preflight"]["tier"] in (
        "ambiguous", "vague", "compound", "empty")


def test_judgment_summary_path_keeps_preflight_contract():
    """研判摘要再经 _attach_preflight 后，调用方总能读到协议字段。"""
    from app.mcp_server import _judgment_summary, build_dossier_from_sources

    d = build_dossier_from_sources(
        "分析一下这个行业",
        [{"title": "A", "text": "客户B回款率40%。", "type": "note"}],
    )
    summary = _judgment_summary(d, 1)
    out = _attach_preflight("分析一下这个行业", summary)
    assert "conclusions" in out
    assert out["preflight"]["needs_clarification"]
    assert "至多 2 轮" in out["preflight"]["protocol"]
    assert out["preflight"]["readback"]