"""R29：树17注入分析师提示词 + 引用合规三轴。"""

from __future__ import annotations

from app.core.evidence import Dossier
from app.agents.prompts import render_segments_block
from app.kg_lab.tree17_cite import (
    ACCOUNTING_KEY,
    attach_tree17_plan,
    build_analyst_user_prompt,
    extract_cited_segment_ids,
    measure_cite_compliance,
    plan_close_read,
    render_cite_prompt_block,
    tree17_prompt_from_dossier,
)


def _conflict_plan():
    q = (
        "AI失控责任该由OpenAI管理层等企业承担，"
        "还是如Anthropic所主张由政府介入承担？"
    )
    metas = {
        "a#p1": {
            "text": "2024年7月通报：OpenAI失控智能体入侵，企业管理层承担责任。",
            "doc_id": "a",
        },
        "b#p1": {
            "text": "Anthropic主张由政府介入控制自动化AI开发速度。",
            "doc_id": "b",
        },
        "c#p1": {
            "text": "有分析认为全球治理需要长期沟通。",
            "doc_id": "c",
        },
    }
    plan = plan_close_read(
        ["c#p1", "a#p1", "b#p1"], metas=metas, question=q, close_k=2,
    )
    return q, metas, plan


def test_render_cite_block_lists_close_and_pair():
    _q, _metas, plan = _conflict_plan()
    block = render_cite_prompt_block(plan)
    assert "【树17 引用纪律】" in block
    assert "成对必读" in block
    assert "a#p1" in block
    assert "b#p1" in block


def test_attach_injects_into_segments_block():
    """accounting 有 tree17_cite → render_segments_block 含纪律；缺席则无。"""
    d = Dossier(question="测试议题：责任该由企业还是政府承担？")
    # 空案卷：无树17时不应出现纪律标题
    text0 = render_segments_block(d)
    assert "【树17 引用纪律】" not in text0

    _q, metas, plan = _conflict_plan()
    attach_tree17_plan(d, plan)
    assert ACCOUNTING_KEY in d.accounting
    # tree17_prompt_from_dossier 直出
    assert "细读集" in tree17_prompt_from_dossier(d)
    # 即使用空 sources，注入块仍应进入（claim 槽路径同级）
    text1 = render_segments_block(d)
    assert "【树17 引用纪律】" in text1


def test_compliance_pair_and_band():
    _q, metas, plan = _conflict_plan()
    # 成对 + 带宽内
    ok = measure_cite_compliance(plan, ["a#p1", "b#p1"], metas=metas)
    assert ok["pair_ok"] is True
    assert ok["band_ok"] is True
    assert ok["ok"] is True
    # 只引一侧
    bad_pair = measure_cite_compliance(plan, ["a#p1"], metas=metas)
    assert bad_pair["pair_ok"] is False
    # 越出带宽（c 通常非细读）
    close = set(plan["close_read"])
    oob = [p for p in plan["box"] if p not in close]
    if oob:
        bad_band = measure_cite_compliance(
            plan, list(close)[:1] + oob[:1], metas=metas,
        )
        # 若成对未满足可能 pair 也红；带宽必红
        assert bad_band["band_ok"] is False


def test_verifiable_priority_axis():
    _q, metas, plan = _conflict_plan()
    close = list(plan["close_read"])
    oob = [p for p in plan["box"] if p not in set(close)]
    if not oob:
        return
    # 只引带宽外 → ver_ok False
    only_oob = measure_cite_compliance(plan, oob[:1], metas=metas)
    assert only_oob["ver_ok"] is False


def test_extract_cited_ids_and_user_prompt():
    q, metas, plan = _conflict_plan()
    payload = {
        "conclusions": [
            {
                "statement": "企业应承担责任",
                "evidence": [
                    {"segment_id": "a#p1", "quote": "OpenAI"},
                    {"segment_id": "b#p1", "quote": "政府介入"},
                ],
            }
        ]
    }
    assert extract_cited_segment_ids(payload) == ["a#p1", "b#p1"]
    user = build_analyst_user_prompt(q, plan=plan, metas=metas)
    assert "【树17 引用纪律】" in user
    assert "【细读】" in user
    assert "a#p1" in user
