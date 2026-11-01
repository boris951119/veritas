"""R35：裁决短主张保位＋池外可核验召回（无案专名硬编码）。"""

from __future__ import annotations

from app.kg_lab.density_submit import pack_core_first
from app.kg_lab.intent_routes import (
    core_rank_score,
    is_core_candidate,
    is_short_claim_segment,
    stage2_verifiable_slots,
)
from app.kg_lab.stage1_claim_holes import (
    extract_verifiable_slots,
    fill_stage1_claim_holes,
    slots_actionable,
)


def test_seat_code_and_claim_alt_extract_no_case_lexicon():
    q = "11A座位靠近紧急出口是否真的提高了生还概率，还是纯属侥幸？"
    slots = extract_verifiable_slots(q)
    assert "11A" in (slots.get("codes") or [])
    assert any("侥幸" in a for a in (slots.get("claim_alts") or []))
    assert slots_actionable(slots, q)
    src = open("app/kg_lab/stage1_claim_holes.py", encoding="utf-8").read()
    assert "王虹" not in src and "柬泰" not in src
    assert "AI171" not in src  # 禁案／航班专名常量


def test_eval_question_with_speaker_actionable():
    q = "某人本人对母校的评价是正面还是负面？"
    slots = extract_verifiable_slots(q)
    assert slots.get("speakers")
    assert slots_actionable(slots, q)


def test_short_claim_beats_long_wire_on_adjudicate_pack():
    q = "11A座位是否提高生还概率，还是纯属侥幸？"
    slots = stage2_verifiable_slots(q)
    short = "这名旅客幸存与座位号11A有关？专家予以否认，认为纯属侥幸。"
    long = (
        "据澎湃新闻报道：" + "印度航空空难事件中唯一幸存者的采访见诸报端。" * 40
        + " AI171 航班相关长通稿。"
    )
    assert is_short_claim_segment(short, slots, route="adjudicate")
    assert not is_short_claim_segment(long, slots, route="adjudicate")
    feats = {
        "short#p1": {
            "verifiability": 0.3, "authority_unit": 0.3,
            "authority_band": "unknown", "option_side": "option_a",
        },
        "long#p1": {
            "verifiability": 0.4, "authority_unit": 0.7,
            "authority_band": "official_channel", "option_side": "",
        },
    }
    metas = {
        "short#p1": {"text": short, "doc_id": "short", "channel": "news"},
        "long#p1": {"text": long, "doc_id": "long", "channel": "wire"},
    }
    pool_pos = {"short#p1": 2, "long#p1": 1}
    assert is_core_candidate(
        "short#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, slots=slots,
    )
    s_sc = core_rank_score(
        "short#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, slots=slots,
    )
    l_sc = core_rank_score(
        "long#p1", feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, slots=slots,
    )
    assert s_sc > l_sc
    packed, cores, _ = pack_core_first(
        ["long#p1", "short#p1"],
        feats=feats, metas=metas, route="adjudicate",
        pool_pos=pool_pos, slots=slots,
    )
    assert packed[0] == "short#p1"
    assert "short#p1" in cores


def test_amount_short_para_injected_into_pool20():
    q = "截至2026年5月，空难死亡人数应以机上241人还是含地面共274人为准？AI171"
    rows = [
        {"para_id": f"pad#p{i}", "text": f"填充通稿段落{i}没有目标数额"}
        for i in range(1, 18)
    ]
    rows.append({
        "para_id": "gold#p1",
        "text": "航空公司证实空难造成客机上241人遇难，仅1人生还。",
    })
    pool = [(f"pad#p{i}", float(20 - i)) for i in range(1, 18)]
    pool.append(("gold#p1", 0.05))
    out = fill_stage1_claim_holes(pool, rows, q)
    top20 = [pid for pid, _ in out["pool_ranked"][:20]]
    assert "gold#p1" in top20
    assert out["applied"] is True
