"""R36：评价题专访短段装箱＋池外可核验召回加力（无案专名）。"""

from __future__ import annotations

from app.kg_lab.density_submit import pack_core_first
from app.kg_lab.intent_routes import (
    core_rank_score,
    is_core_candidate,
    is_interview_voice_segment,
    stage2_verifiable_slots,
)
from app.kg_lab.stage1_claim_holes import (
    extract_verifiable_slots,
    fill_stage1_claim_holes,
    slots_actionable,
)


def test_eval_attitude_slots_and_interview_voice_no_case_lexicon():
    q = "某人本人对母校的评价是正面还是负面？"
    slots = stage2_verifiable_slots(q)
    assert slots.get("speakers")
    assert slots.get("eval_attitude") is True
    voice = (
        "专访中，某人回忆了求学往事。她表示：在学院接受的训练让我有了扎实的基本功。"
    )
    rumor = "原院长回应「成绩不突出、数学系不给写推荐信」等传闻。"
    assert is_interview_voice_segment(voice, slots)
    assert not is_interview_voice_segment(rumor, slots)
    src = open("app/kg_lab/intent_routes.py", encoding="utf-8").read()
    assert "王虹" not in src and "北大" not in src


def test_interview_voice_beats_rumor_shell_in_eval_pack():
    q = "某人本人对母校的评价是正面还是负面？"
    slots = stage2_verifiable_slots(q)
    voice = (
        "专访中，某人表示：在学院的时候学习氛围特别好，想做科研的人特别多。"
    )
    rumor = (
        "扫码查看 原院长回应「成绩不突出、未参与拍摄毕业照、不给写推荐信」等传闻。"
    )
    feats = {
        "v#p1": {
            "verifiability": 0.3, "authority_unit": 0.3,
            "authority_band": "unknown", "option_side": "",
        },
        "r#p1": {
            "verifiability": 0.2, "authority_unit": 0.6,
            "authority_band": "wire_relay", "option_side": "",
        },
    }
    metas = {
        "v#p1": {"text": voice, "doc_id": "v", "channel": "interview"},
        "r#p1": {"text": rumor, "doc_id": "r", "channel": "wire"},
    }
    # 注入 speakers 到文本
    metas["v#p1"]["text"] = voice.replace("某人", slots["speakers"][0])
    metas["r#p1"]["text"] = rumor.replace("某人", slots["speakers"][0])
    pool_pos = {"v#p1": 5, "r#p1": 2}
    assert is_core_candidate(
        "v#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, slots=slots,
    )
    v_sc = core_rank_score(
        "v#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, slots=slots,
    )
    r_sc = core_rank_score(
        "r#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, slots=slots,
    )
    assert v_sc > r_sc
    packed, cores, _ = pack_core_first(
        ["r#p1", "v#p1"],
        feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, slots=slots,
    )
    assert packed[0] == "v#p1"
    assert "v#p1" in cores


def test_fuel_switch_alt_core_injects_without_flight_code_in_para():
    q = "官方调查是否已认定坠机系机组关闭燃油开关所致，而非波音燃油开关设计缺陷？"
    slots = extract_verifiable_slots(q)
    # 长支进 alts；短核「燃油开关」不单独进，防评论通稿灌池
    assert any("关闭燃油开关" in a or "开关" in a for a in (slots.get("claim_alts") or []))
    assert "燃油开关" not in (slots.get("claim_alts") or [])
    assert slots_actionable(slots, q)
    rows = [
        {"para_id": f"pad#p{i}", "text": f"填充通稿{i}无关内容" + "叙述" * 30}
        for i in range(1, 18)
    ]
    # 评论通稿也提「燃油开关」——不应挤掉调查声部金标
    rows.append({
        "para_id": "noise#p1",
        "text": "专家分析指出，燃油开关理论上不可能被意外触动，需要明确的物理操作才能改变状态。" + "分析" * 40,
    })
    rows.append({
        "para_id": "gold#p1",
        "text": (
            "初步调查报告披露，黑匣子录音显示机长关闭了控制两台引擎燃油供应的开关，"
            "这可能是导致坠机的直接原因。"
        ),
    })
    pool = [(f"pad#p{i}", float(20 - i)) for i in range(1, 18)]
    pool.append(("noise#p1", 0.08))
    pool.append(("gold#p1", 0.05))
    out = fill_stage1_claim_holes(pool, rows, q)
    top20 = [pid for pid, _ in out["pool_ranked"][:20]]
    assert "gold#p1" in top20


def test_amount_short_para_still_pins_into_pool20():
    q = "截至2026年5月，空难死亡人数应以机上241人还是含地面共274人为准？AI171"
    rows = [
        {"para_id": f"pad#p{i}", "text": f"长通稿填充{i}" + "叙述" * 40}
        for i in range(1, 22)
    ]
    rows.append({
        "para_id": "amt#p1",
        "text": "航空公司证实空难造成客机上241人遇难，仅1人生还。",
    })
    pool = [(f"pad#p{i}", float(25 - i)) for i in range(1, 22)]
    pool.append(("amt#p1", 0.01))
    out = fill_stage1_claim_holes(pool, rows, q)
    top20 = [pid for pid, _ in out["pool_ranked"][:20]]
    assert "amt#p1" in top20
