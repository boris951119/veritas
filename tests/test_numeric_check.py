"""数字机械核对器：计算复算、输入溯源、来源外数字、归并守恒。"""

from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
)
from app.core.numeric_check import (
    _eval_expr, audit_conservation, audit_numeric, extract_nums,
)

SEG = "客户B合同金额1,280万元，累计回款512万元，合同签订于2026年3月。"
Q = "合同金额1,280万元，累计回款512万元"


def _dossier(statement: str, note: str = "", quote: str = Q,
             question: str = "客户B的回款情况如何？",
             seg: str = SEG) -> Dossier:
    d = Dossier(question=question)
    src = Source.create("合同台账", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text=seg))
    d.add_source(src)
    con = Conclusion.create(statement, author="a", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create("CON1", quote, ["SRC1#s1"],
                                       note=note, id="EV1"))
    return d


def _kinds(d: Dossier) -> set[str]:
    return {f["kind"] for f in audit_numeric(d)}


# -- 提取器 -----------------------------------------------------------------


def test_extract_nums_value_and_unit():
    nums = extract_nums("回款512万元，占比40.5%，合计1,280.50亿")
    assert [(n.raw, n.value, n.scaled) for n in nums] == [
        ("512万", 512.0, 5_120_000.0),
        ("40.5%", 40.5, 0.405),
        ("1,280.50亿", 1280.50, 128_050_000_000.0),
    ]


def test_eval_left_to_right_with_units():
    assert _eval_expr("512/1280") == 0.4
    assert _eval_expr("1280-512") == 768
    assert _eval_expr("1280万-512万") == 7_680_000.0
    assert _eval_expr("1280×40%") == 512.0


# -- 计算闸（红） --------------------------------------------------------------


def test_correct_formulas_produce_no_flags():
    d = _dossier("客户B回款率为40%，缺口768万元。",
                 note="计算:512/1280=40%；1280-512=768")
    assert _kinds(d) == set()


def test_wrong_arithmetic_flagged_high():
    d = _dossier("客户B回款率为45%。", note="计算:512/1280=45%")
    flags = [f for f in audit_numeric(d) if f["kind"] == "calc"]
    assert len(flags) == 1 and flags[0]["severity"] == "high"
    assert "复算不符" in flags[0]["detail"]


def test_fabricated_input_flagged_even_if_arithmetic_holds():
    """算式本身自洽但输入数不在所引材料——输入是编的，同样红。"""
    d = _dossier("客户B回款率为78%。", note="计算:999/1280=78%",
                 quote="合同金额1,280万元")
    flags = [f for f in audit_numeric(d) if f["kind"] == "calc"]
    assert flags and "999" in flags[0]["detail"]


def test_fabricated_input_result_not_exempt_from_provenance():
    """输入造假的算式，其结果数字不得豁免溯源（78% 须另吃黄牌）。"""
    d = _dossier("客户B回款率为78%。", note="计算:999/1280=78%",
                 quote="合同金额1,280万元")
    assert "provenance" in _kinds(d)


def test_unit_scaled_mismatch_flagged():
    d = _dossier("缺口700万元。", note="计算:1280万-512万=700万")
    flags = [f for f in audit_numeric(d) if f["kind"] == "calc"]
    assert flags and flags[0]["severity"] == "high"


def test_unit_suffix_on_result_only_passes():
    """输入裸写、万单位只挂结果（1647.60-1188.00=459.60万）是诚实写法，
    双解释容忍下不得错杀——真实网关 F' 验证跑抓到的唯一红灯即此误报。"""
    seg = "合同额1,647.60万元，已回款1,188.00万元。"
    d = _dossier("回款缺口459.60万元。", note="计算:1647.60-1188.00=459.60万",
                 seg=seg)
    assert not [f for f in audit_numeric(d) if f["kind"] == "calc"]


def test_percent_input_without_source_flagged():
    """用材料中不存在的百分比推导金额——乘数本身无溯源，红。"""
    d = _dossier("预期回款512万元。", note="计算:1280×40%=512")
    assert any(f["kind"] == "calc" for f in audit_numeric(d))


def test_rounding_tolerances_not_flagged():
    """常规取整（半位容差）不红：真值 39.98% 写 40% 放过；
    输入数取材料原值（512.3/1280.8 在段落里）。"""
    seg = "客户B合同金额1,280.8万元，累计回款512.3万元。"
    d = _dossier("回款率约40%。", note="计算:512.3/1280.8=40%", seg=seg)
    assert not [f for f in audit_numeric(d) if f["kind"] == "calc"]


# -- 溯源闸（黄） --------------------------------------------------------------


def test_outside_number_flagged_medium():
    d = _dossier("客户B回款率40%，另有坏账300万元。")
    flags = [f for f in audit_numeric(d) if f["kind"] == "provenance"]
    assert [f["value"] for f in flags] == ["40%", "300万"]


def test_measure_words_years_ordinals_skipped():
    d = _dossier("2026年验收，涉及3份合同，第2次延期。")
    assert _kinds(d) == set()


def test_number_in_segment_text_counts_as_sourced():
    """数字不必在引文里，出现在所引段落原文中即算溯源。"""
    d = _dossier("客户B回款512万元，占合同额四成。", quote="合同金额1,280万元")
    assert not [f for f in audit_numeric(d)
                if f["kind"] == "provenance" and f["value"] == "512万"]


# -- 守恒闸（黄） --------------------------------------------------------------


def test_merge_conservation_flags_new_numbers():
    d = _dossier("多客户回款普遍恶化，合计坏账9.6亿元。")
    member = Conclusion.create("客户B回款512万元", author="a", id="CON0")
    member.status = "merged"
    member.group_id = "CON1"
    d.conclusions.append(member)
    flags = audit_conservation(d)
    assert len(flags) == 1 and flags[0]["value"] == "9.6亿"
    assert flags[0]["severity"] == "medium"


def test_merge_conservation_quiet_when_within_members():
    d = _dossier("客户B回款512万元。")
    member = Conclusion.create("回款512万元，合同1280万元", author="a", id="CON0")
    member.status = "merged"
    member.group_id = "CON1"
    d.conclusions.append(member)
    assert audit_conservation(d) == []
