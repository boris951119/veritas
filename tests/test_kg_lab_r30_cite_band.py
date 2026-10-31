"""R30：细读带宽对齐盒 k + 越界剪枝／重抽。"""

from __future__ import annotations

from app.kg_lab.tree17_cite import (
    build_analyst_user_prompt,
    filter_payload_to_close_band,
    measure_cite_compliance,
    plan_close_read,
    repair_cites_to_band,
    render_cite_prompt_block,
)


def _plan(align: bool):
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
        "d#p1": {
            "text": "产业评论：协作机制仍在讨论中。",
            "doc_id": "d",
        },
    }
    box = ["a#p1", "b#p1", "c#p1", "d#p1"]
    plan = plan_close_read(
        box, metas=metas, question=q, close_k=2, align_to_box=align,
    )
    return q, metas, plan


def test_align_to_box_makes_close_eq_box():
    _q, _metas, plan = _plan(align=True)
    assert plan["align_to_box"] is True
    assert plan["close_k_effective"] == len(plan["box"])
    assert set(plan["close_read"]) == set(plan["box"])


def test_without_align_close_smaller_than_box():
    _q, _metas, plan = _plan(align=False)
    assert plan["close_k_effective"] <= 2
    assert len(plan["close_read"]) < len(plan["box"])


def test_prompt_forbids_non_close_when_not_aligned():
    _q, metas, plan = _plan(align=False)
    block = render_cite_prompt_block(plan)
    assert "禁止" in block or "只许" in block
    user = build_analyst_user_prompt(
        _q, plan=plan, metas=metas, include_non_close=False,
    )
    # 默认资料清单只有细读
    assert "【细读】" in user
    for pid in plan["close_read"]:
        assert pid in user
    for pid in plan["box"]:
        if pid not in plan["close_read"]:
            # 纪律块可点名禁止，但正文【细读】列表不应含它
            assert f"【细读】[{pid}]" not in user


def test_filter_drops_oob_evidence():
    _q, metas, plan = _plan(align=False)
    close = set(plan["close_read"])
    oob = [p for p in plan["box"] if p not in close]
    assert oob
    payload = {
        "conclusions": [
            {
                "statement": "x",
                "evidence": [
                    {"segment_id": plan["close_read"][0], "quote": "a"},
                    {"segment_id": oob[0], "quote": "b"},
                ],
            }
        ]
    }
    filtered = filter_payload_to_close_band(payload, plan)
    evs = filtered["conclusions"][0]["evidence"]
    assert all(e["segment_id"] in close for e in evs)
    assert filtered["n_dropped_evidence"] >= 1
    comp = measure_cite_compliance(
        plan, [e["segment_id"] for e in evs], metas=metas,
    )
    assert comp["band_ok"] is True


def test_repair_regen_when_pair_broken_after_filter():
    _q, metas, plan = _plan(align=False)
    # 构造：只引了带宽外的两侧 → 剪完可能空，触发重抽
    close = list(plan["close_read"])
    oob = [p for p in plan["box"] if p not in set(close)]
    payload = {
        "conclusions": [
            {
                "statement": "bad",
                "evidence": [{"segment_id": oob[0], "quote": "x"}] if oob else [],
            }
        ]
    }

    calls: list[str] = []

    def fake_gen(prompt: str):
        calls.append(prompt)
        # 重抽返回细读内成对
        evs = [{"segment_id": pid, "quote": "q"} for pid in close[:2]]
        if plan.get("pair_required") and len(close) >= 2:
            # 确保两侧
            sides = {}
            for it in plan["items"]:
                if it["para_id"] in close:
                    sides.setdefault(it["side"], it["para_id"])
            evs = [
                {"segment_id": sides.get("option_a", close[0]), "quote": "a"},
                {"segment_id": sides.get("option_b", close[-1]), "quote": "b"},
            ]
        return {
            "parsed": {"conclusions": [{"statement": "ok", "evidence": evs}]},
            "raw": "{}",
        }

    out = repair_cites_to_band(
        payload, plan, question=_q, metas=metas, generate_fn=fake_gen,
    )
    assert out["oob_before"]
    assert out["compliance"]["band_ok"] is True
    if oob and not filter_payload_to_close_band(payload, plan)["conclusions"]:
        assert out["repaired_by_regen"] is True
        assert calls
