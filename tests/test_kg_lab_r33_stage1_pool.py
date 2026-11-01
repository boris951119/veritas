"""R33：可核验槽抽取／actionable 闸／拉丁进池（无案专名硬编码）。"""

from __future__ import annotations

from app.kg_lab.stage1_claim_holes import (
    build_claim_hole_arm,
    extract_verifiable_slots,
    fill_stage1_claim_holes,
    slots_actionable,
)


def test_extract_latin_and_quote_tails_from_question_surface():
    q = (
        '某人说的 discouraged 原意指什么？'
        '流传的「无人肯写推荐信」「因绩点不足未保研」是否属实？'
    )
    slots = extract_verifiable_slots(q)
    assert "discouraged" in slots["latin"]
    assert "推荐信" in slots["quotes"] or any("推荐" in x for x in slots["quotes"])
    assert "保研" in slots["quotes"]
    # 禁止把抽取结果写成案名词表常量依赖
    assert "王虹" not in open(
        "app/kg_lab/stage1_claim_holes.py", encoding="utf-8"
    ).read()


def test_amount_times_code_actionable_but_bare_amount_not():
    bare_q = "这笔49.4万元应认定为买断费还是补偿金？"
    bare = extract_verifiable_slots(bare_q)
    assert bare["amounts"]
    assert not slots_actionable(bare, bare_q)

    mixed_q = "截至2026年5月，AI171空难死亡人数应以机上241人还是274人为准？"
    mixed = extract_verifiable_slots(mixed_q)
    assert "AI171" in mixed["latin"]
    assert any("241" in a for a in mixed["amounts"])
    assert slots_actionable(mixed, mixed_q)

    # 责任对立题：词拉丁不单独 actionable（回归案已有 R27 臂）
    resp_q = (
        "AI失控责任该由OpenAI管理层等企业承担，"
        "还是如Anthropic所主张由政府介入承担？"
    )
    assert not slots_actionable(extract_verifiable_slots(resp_q), resp_q)


def test_latin_hit_scores_primary_over_empty():
    q = "问句里的 discouraged 原意是什么？"
    rows = [
        {
            "para_id": "doc_a#p1",
            "text": "一手访谈视频中亲口说 felt discouraged，是原话出处。",
        },
        {
            "para_id": "doc_b#p1",
            "text": "完全无关的中文通稿，没有拉丁词。",
        },
    ]
    built = build_claim_hole_arm(rows, q)
    sc = dict(built["arm"])
    assert sc.get("doc_a#p1", 0) > sc.get("doc_b#p1", 0)
    assert slots_actionable(built["slots"])


def test_fill_injects_latin_without_case_lexicon():
    q = "原文 discouraged 指什么？"
    rows = [
        {"para_id": f"doc_x#p{i}", "text": f"填充段{i}没有目标词"}
        for i in range(1, 16)
    ]
    rows.append({
        "para_id": "doc_gold#p1",
        "text": "官方访谈原话说 discouraged 的语境。",
    })
    # 经典池头故意不含金标
    pool = [(f"doc_x#p{i}", float(20 - i)) for i in range(1, 16)]
    pool.append(("doc_gold#p1", 0.1))
    out = fill_stage1_claim_holes(pool, rows, q)
    top20 = [pid for pid, _ in out["pool_ranked"][:20]]
    assert "doc_gold#p1" in top20
    assert out["applied"] is True


def test_conflict_year_bridge_marks_english_para():
    q = "泰方称柬方率先开火，2025年12月冲突谁先动武？"
    slots = extract_verifiable_slots(q)
    assert "2025" in slots["years"]
    assert slots["conflict_verbs"]
    assert slots_actionable(slots)
    rows = [
        {
            "para_id": "en#p1",
            "text": (
                "On the morning of December 8, 2025, the forces launched "
                "an attack after clashes along the border."
            ),
        },
        {"para_id": "zh#p1", "text": "无关水利新闻。"},
    ]
    built = build_claim_hole_arm(rows, q)
    sc = dict(built["arm"])
    assert sc.get("en#p1", 0) > sc.get("zh#p1", 0)
