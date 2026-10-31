"""议题前提核对器：问题实体在信源零命中 → 前置黄牌。"""

from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.premise_check import (
    _is_residue,
    extract_entities,
    premise_flags,
    premise_record,
)

SEG_TEXT = "客户B的供应商已拖欠回款超过90天，账期从90天延长至150天，回款周期显著拉长。"


def _dossier(question: str, seg: str = SEG_TEXT) -> Dossier:
    d = Dossier(question=question)
    src = Source.create("T", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text=seg))
    d.add_source(src)
    return d


def test_entities_split_by_frame_words():
    ents = extract_entities("客户B的供应商是否拖欠回款？")
    assert "客户" in ents and "供应商" in ents and "拖欠回款" in ents
    assert all("是否" not in e for e in ents)


def test_covered_question_produces_no_flags():
    d = _dossier("客户B的供应商是否拖欠回款？")
    assert premise_flags(d) == []


def test_uncovered_entity_flagged():
    d = _dossier("新荣集团是否存在交付风险？")
    flags = premise_flags(d)
    assert len(flags) == 1
    assert flags[0]["kind"] == "premise" and flags[0]["value"] == "新荣集团"
    assert flags[0]["severity"] == "medium"


def test_latin_entity_zero_hit_flagged():
    d = _dossier("ACME公司是否存在交付风险？")
    flags = premise_flags(d)
    assert [f["value"] for f in flags] == ["ACME"]  # 「公司」「交付风险」属框架词不入查


def test_generic_analysis_words_not_checked():
    d = _dossier("请分析客户B的风险情况并评估影响")
    assert premise_flags(d) == []


def test_shareholder_question_template_not_flagged():
    """「第一大股东是谁」是问句模板，不是要在原文找的专有名。"""
    d = _dossier(
        "截至2024年半年度报告期末，第一大股东是谁？持股数量与持股比例？",
        "宜兴市中港投资有限公司持股97,500,000股，比例46.95%。",
    )
    assert premise_flags(d) == []
    assert "第一大股东是谁" not in extract_entities(d.question)
    rec = premise_record(d)
    assert rec["status"] == "exempt_template"
    assert "免核" in rec["note"]
    assert "未核" not in rec["note"]


def test_hengxing_q9_is_exempt_not_no_candidates():
    """恒兴 Q9：模板免核，不得落成 no_candidates（静默未核假象）。"""
    q = "截至 2024 年半年度报告期末，第一大股东是谁？持股数量与持股比例？"
    d = _dossier(q, "宜兴市中港投资有限公司持股97,500,000股，比例46.95%。")
    assert extract_entities(q) == []
    assert premise_record(d)["status"] == "exempt_template"


def test_flag_cap_at_five():
    d = _dossier("甲集团、乙集团、丙集团、丁集团、戊集团、己集团各有什么风险？")
    assert len(premise_flags(d)) <= 5


def test_delay_synonym_is_covered_literal_miss_is_not():
    """延期字面不在、延迟在 → 不亮；自述指标可信真没有 → 仍亮。"""
    from pathlib import Path
    from app.ingest.case_loader import load_case

    d = load_case(Path("cases/bi-delivery-risk"))
    values = [f["value"] for f in premise_flags(d)]
    assert "延期" not in values
    assert "自述指标可信" in values


def test_parent_net_profit_alias_is_covered():
    d = _dossier(
        "2024年半年度归母净利润是多少？",
        "归属于上市公司股东的净利润 1,234,567.89 元，同比 -12.34%。",
    )
    values = [f["value"] for f in premise_flags(d)]
    assert not any("归母净利润" in v for v in values)


def test_true_zero_hit_is_in_analyst_prompt_softly():
    from app.agents.prompts import render_segments_block

    d = _dossier("新荣集团是否存在交付风险？")
    block = render_segments_block(d)
    assert "资料侧未检索到「新荣集团」" in block
    assert "请仍先尽力依据现有资料作答" in block
    assert "写「资料不足」" not in block
    assert premise_flags(d)[0]["severity"] == "medium"


def test_question_residue_not_flagged_on_dividend_question():
    d = _dossier(
        "公司 2023 年度利润分配预案中，拟向全体股东每 10 股派多少现金红利？"
        "现金分红占归母净利润比例是多少？转增后总股本预计多少？",
        "拟向全体股东每10股派发现金红利2元（含税），占归母净利润比例40.70%，"
        "转增后总股本预计为207,667,617股。",
    )
    values = [f["value"] for f in premise_flags(d)]
    assert "股派多少现金红利" not in values
    assert not any("多少" in v or "几" in v for v in values)


def test_hengxing_scorecard_ten_questions_zero_false_premise():
    """十道题面 + 手写段落：前提已核或免核，且无关文本会亮灯。"""
    questions = [
        "恒兴新材 2023 年度有机酮类产品的销量与销售金额分别是多少？",
        "恒兴新材 2025 年全年归属于上市公司股东的净利润是多少？",
        "公司 2023 年度利润分配预案中，拟向全体股东每 10 股派多少现金红利？"
        "现金分红占归母净利润比例是多少？转增后总股本预计多少？",
        "2024 年 1 月 10–12 日恒兴新材股票为何触及异常波动？"
        "公司核查后是否存在应披露未披露的重大事项？",
        "2024 年恒兴新材营业收入、归母净利润各是多少？归母净利润同比变动多少？",
        "恒兴新材在 2024 年披露过几轮股份回购方案？金额区间与用途有何不同？"
        "请按披露时间区分。",
        "工商变更完成后，恒兴新材的股票代码、注册资本、法定代表人、成立日期分别是什么？",
        "2024 年半年度，公司营业收入与归母净利润是多少？归母净利润同比变动多少？",
        "截至 2024 年半年度报告期末，第一大股东是谁？持股数量与持股比例？",
        "据 2023 年报摘要，公司属于什么行业、主营哪几类产品？"
        "文中引用的 2023 年全球锂离子电池电解液出货量及同比增速是多少？",
    ]
    paragraphs = [
        "恒兴新材2023年度报告：公司主营业务为有机酮类产品与电解液相关材料，有机酮类产品的销量与销售金额见分产品情况表。",
        "恒兴新材2025年度实现归属于上市公司股东的净利润，具体数额见合并利润表，母公司净利润另有披露。",
        "公司2023年度利润分配预案：拟向全体股东每10股派发现金红利，并以资本公积转增股本，转增后总股本相应变化，现金分红占归属于上市公司股东的净利润比例见预案说明。",
        "2024年1月10日至12日，恒兴新材股票连续三个交易日收盘价格涨幅偏离值累计达到异常波动标准；公司于公告中说明，经核查，截至公告披露日不存在应披露未披露的重大事项。",
        "恒兴新材2024年年度报告显示，营业收入与归属于上市公司股东的净利润较上年变动，归属于上市公司股东的净利润同比变动幅度见主要财务数据。",
        "恒兴新材2024年披露过多轮股份回购方案，各轮回购金额区间与用途不同：首轮用于注销减少注册资本，后续用于员工持股计划，披露时间依次列示。",
        "恒兴新材完成工商变更后，股票代码保持不变，注册资本、法定代表人、成立日期以登记机关核准记载为准，变更公告已披露。",
        "恒兴新材2024年半年度报告披露营业收入与归属于上市公司股东的净利润，归属于上市公司股东的净利润同比变动情况见董事会报告。",
        "截至2024年半年度报告期末，恒兴新材第一大股东及其持股数量、持股比例见前十名股东持股情况表。",
        "据2023年年度报告摘要，公司所处行业为新材料行业，主营产品包括有机酮类产品与电解液材料；摘要引用行业协会统计的2023年全球锂离子电池电解液出货量与同比增速。",
    ]
    assert len(questions) == 10
    src = Source.create("手写案卷", SourceType.REPORT, id="SRC1")
    for i, text in enumerate(paragraphs, start=1):
        src.segments.append(Segment(
            id=f"doc_001#p{i}", source_id="SRC1", text=text))
    n_candidates = 0
    for q in questions:
        d = Dossier(question=q)
        d.add_source(src)
        rec = premise_record(d)
        n_candidates += rec["n_candidates"]
        assert rec["status"] in {"checked_ok", "exempt_template"}, (
            q[:24], rec["status"], rec["flags"])
        assert rec["n_flags"] == 0
    assert n_candidates >= 30

    blank = Source.create("无关", SourceType.OTHER, id="SRC9")
    blank.segments.append(Segment(
        id="SRC9#s1", source_id="SRC9", text="完全无关的一段话，只讲天气。"))
    lit = 0
    for q in questions:
        d = Dossier(question=q)
        d.add_source(blank)
        if premise_record(d)["n_flags"] > 0:
            lit += 1
    assert lit >= 8


def test_long_chinese_run_still_yields_candidates():
    q1 = "请说明报告期内前五大客户集中度变化情况及原因"
    q2 = "恒兴新材海外营收占比是多少？"
    assert extract_entities(q1), q1
    ents2 = extract_entities(q2)
    assert ents2, q2
    assert any("恒兴" in e or "营收" in e for e in ents2)


def test_no_candidates_status_is_explicit():
    d = _dossier("？？？")
    rec = premise_record(d)
    assert rec["status"] == "no_candidates"
    assert "未核" in rec["note"]


def test_residue_is_morpheme_level_not_company_idioms():
    assert _is_residue("股派多少现金红利")
    assert _is_residue("文中")
    assert _is_residue("哪几类")
    assert not _is_residue("每10股派息")
    assert not _is_residue("按披露口径")
    assert not _is_residue("披露过会后事项")
    assert not _is_residue("股息派发率")
    assert not _is_residue("主营业务毛利")


def test_alarm_token_strips_edge_particles():
    d = _dossier("年商誉减值损失是多少？", "无关正文")
    values = [f["value"] for f in premise_flags(d)]
    assert values
    assert all(not v.endswith("是") for v in values)
    assert any("商誉减值" in v for v in values)
    assert "年商誉减值损失是" not in values


def test_alarm_token_strips_jiu_tong_company_prefix():
    """残渣尾缀收口：多久 / 同 / 本公司 不进报警串。"""
    assert "多久" not in "".join(extract_entities("多久能回款？"))
    assert all(not e.startswith("同") for e in extract_entities("与同行业对比如何？"))
    ents = extract_entities("本公司商誉减值是多少？")
    assert ents
    assert all(not e.startswith(("公司", "本公")) for e in ents)
    assert any("商誉减值" in e for e in ents)
    assert all(not e.endswith("是") for e in ents)


def test_empty_corpus_is_not_checked_ok():
    """无信源正文 ≠ 已核无缺口（checked_ok 不对称）。"""
    d = Dossier(question="新荣集团是否存在交付风险？")
    rec = premise_record(d)
    assert rec["status"] == "no_corpus"
    assert "未核" in rec["note"]
    assert "无信源正文" in rec["note"]


def test_positive_controls_still_flag():
    cases = [
        ("新荣集团是否存在交付风险？", "新荣集团"),
        ("客户是否拖欠回款？", "拖欠回款"),
        ("公司是否收到环保处罚？", "环保处罚"),
        ("本年是否计提商誉减值？", "商誉减值"),
    ]
    for q, expect in cases:
        d = _dossier(q, "完全无关的一段话。")
        values = [f["value"] for f in premise_flags(d)]
        assert any(expect in v or v in expect for v in values), (q, values)


def test_report_distinguishes_unchecked_premise():
    from app.core.hashchain import HashChain
    from app.pipeline import render_report_md

    d = _dossier("？？？")
    d.accounting["premise"] = premise_record(d)
    md = render_report_md(d, HashChain(), [])
    assert "未核" in md
    assert "议题未抽出可比对实体" in md


def test_report_shows_template_exempt_not_unchecked():
    from app.core.hashchain import HashChain
    from app.pipeline import render_report_md

    d = _dossier(
        "截至2024年半年度报告期末，第一大股东是谁？持股数量与持股比例？",
        "宜兴市中港投资有限公司持股97,500,000股，比例46.95%。",
    )
    d.accounting["premise"] = premise_record(d)
    md = render_report_md(d, HashChain(), [])
    assert "免核" in md
    assert "问句模板" in md
    assert "议题未抽出可比对实体" not in md
