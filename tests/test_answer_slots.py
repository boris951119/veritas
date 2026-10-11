"""议题槽位：全年指标未被同期间覆盖时，主答案必须是资料不足。"""

from app.agents.chair import build_synthesis, render_chair_template
from app.core.answer_slots import assess_slots, parse_slots
from app.core.evidence import (
    Conclusion, Dossier, Segment, Source, SourceType,
)
from app.core.material import pack_material


def _dossier(question: str, texts: list[str]) -> Dossier:
    d = Dossier(question=question)
    for i, text in enumerate(texts, 1):
        src = Source.create(f"S{i}", SourceType.REPORT, id=f"SRC{i}")
        src.segments.append(Segment(
            id=f"SRC{i}#s1", source_id=f"SRC{i}", text=text))
        d.add_source(src)
    return d


_Q = "恒兴新材 2025 年全年归属于上市公司股东的净利润是多少？"


def test_parse_fy_parent_net_profit():
    slots = parse_slots(_Q)
    assert len(slots) == 1
    assert slots[0]["year"] == 2025
    assert slots[0]["grain"] == "fy"
    assert slots[0]["metric_id"] == "net_profit_parent"


def test_parse_multi_metrics_keeps_order():
    q = "2024 年半年度，公司营业收入与归母净利润是多少？"
    ids = [s["metric_id"] for s in parse_slots(q)]
    assert ids == ["revenue", "net_profit_parent"]


def test_colloquial_yingshou_parses_revenue():
    slots = parse_slots("2024年半年度营收是多少？")
    assert len(slots) == 1 and slots[0]["metric_id"] == "revenue"


def test_metric_without_period_clarifies_not_assumes():
    from app.core.answer_slots import slot_intent, slot_prompt

    intent = slot_intent("公司归母净利润是多少？")
    assert intent["metrics"] and intent["period"] is None
    assert intent["slots"] == []
    assert intent["complete"] is False
    assert any("未锁定会计期间" in t for t in intent["clarify"])
    d = _dossier("公司归母净利润是多少？", ["2024年半年度归母净利润 1 亿元"])
    prompt = slot_prompt(d)
    assert "禁止自行假定" in prompt
    from app.core.answer_slots import apply_answer_contract
    synth = apply_answer_contract(d, {
        "mode": "template", "headline": "随便写个数字",
        "points": [], "open_issues": [], "gate_notes": [],
    })
    assert any(i.get("kind") == "question" for i in synth["open_issues"])


def test_missing_period_early_exits_pipeline_without_llm(tmp_path):
    """口语缺期间：管线秒级回读确认，不调分析师。"""
    from app.pipeline import RunDeps, RunSpec, run_case

    case = tmp_path / "nl"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "question: 公司归母净利润是多少？\nsources:\n"
        "  - file: a.txt\n    type: report\n",
        encoding="utf-8")
    (case / "a.txt").write_text(
        "2024年半年度归属于上市公司股东的净利润31,831,900.82元。",
        encoding="utf-8")

    class Boom:
        def chat(self, *a, **k):
            raise AssertionError("缺期间早停不应调用模型")

    out = case / "out"
    result = run_case(
        RunSpec(case_dir=case, out_dir=out, probe=False,
                dossier=None),
        RunDeps(client=Boom()),  # type: ignore[arg-type]
    )
    # load_case via case_dir — need question from manifest
    hl = (result.dossier.synthesis or {}).get("headline", "")
    assert "议题未齐" in hl or "未锁定会计期间" in hl
    assert result.dossier.accounting.get("n_calls") == 0
    events = [r.event for r in result.chain.records]
    assert "slot_clarify_early_exit" in events
    assert "analyst_done" not in events
    import json
    prog = json.loads((out / "progress.json").read_text(encoding="utf-8"))
    clarify_steps = [
        s for s in prog.get("steps") or []
        if (s.get("detail") or {}).get("clarify")]
    assert clarify_steps
    assert any("会计期间" in t for t in clarify_steps[0]["detail"]["clarify"])


def test_ambiguous_profit_clarifies_scope():
    from app.core.answer_slots import slot_intent

    intent = slot_intent("2024年公司净利润是多少？")
    assert intent["complete"] is False
    assert any("利润" in t and "归母" in t for t in intent["clarify"])
    assert parse_slots("2024年公司净利润是多少？") == []


def test_ambiguous_income_and_sales_clarify():
    from app.core.answer_slots import slot_intent

    i1 = slot_intent("2024年半年度收入是多少？")
    assert any("收入" in t for t in i1["clarify"])
    i2 = slot_intent("去年销售怎么样？")
    assert any("销售" in t for t in i2["clarify"])


def test_shareholder_without_as_of_clarifies_time_kind():
    from app.core.answer_slots import slot_intent

    intent = slot_intent("第一大股东是谁？持股多少？")
    assert intent["time_kind"] == "as_of"
    assert any("时点快照" in t or "报告期期末" in t for t in intent["clarify"])


def test_abnormal_move_without_window_clarifies():
    from app.core.answer_slots import slot_intent

    intent = slot_intent("股票交易异常波动是什么原因？")
    assert intent["time_kind"] == "event_window"
    assert any("事件窗" in t for t in intent["clarify"])


def test_buyback_round_clarifies_unless_named():
    from app.core.answer_slots import slot_intent

    vague = slot_intent("公司回购股份花了多少钱？")
    assert any("轮次" in t for t in vague["clarify"])
    clear = slot_intent("两轮回购方案的金额与用途分别是什么？")
    assert not any("轮次" in t for t in clear["clarify"])


def test_clear_parent_net_profit_with_period_is_complete():
    from app.core.answer_slots import slot_intent

    intent = slot_intent("2024年半年度归母净利润是多少？")
    assert intent["complete"] is True
    assert intent["metrics"][0]["id"] == "net_profit_parent"


def test_company_pronoun_on_single_issuer_is_not_a_subject_gap():
    """单一上市公司公告里的「公司」就是这家，不另要主体。"""
    from app.core.answer_slots import slot_intent

    d = _dossier("公司2024年半年度归母净利润是多少？", [
        "江苏恒兴新材料科技股份有限公司2024年半年度报告。"
        "宜兴市中港投资有限公司为第一大股东。",
    ])
    intent = slot_intent(d.question, d)
    assert not any("对象主体" in t for t in intent["clarify"])
    assert intent["complete"] is True


def test_subsidiary_without_legal_name_clarifies():
    from app.core.answer_slots import slot_intent

    intent = slot_intent("子公司2024年半年度营收是多少？")
    assert any("子公司" in t for t in intent["clarify"])
    named = slot_intent("子公司江苏恒兴化学有限公司2024年半年度营收是多少？")
    assert not any("子公司" in t and "未锁定" in t for t in named["clarify"])


def test_two_issuers_require_a_named_subject(tmp_path):
    from app.pipeline import RunDeps, RunSpec, run_case

    d = _dossier("2024年半年度归母净利润是多少？", [
        "甲乙丙丁股份有限公司与戊己庚辛股份有限公司同期披露净利润。",
    ])
    from app.core.answer_slots import slot_intent
    intent = slot_intent(d.question, d)
    assert any("多家股份公司" in t for t in intent["clarify"])
    locked = slot_intent("甲乙丙丁股份有限公司2024年半年度归母净利润是多少？", d)
    assert not any("多家股份公司" in t for t in locked["clarify"])

    case = tmp_path / "two"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "question: 2024年半年度归母净利润是多少？\nsources:\n"
        "  - file: a.txt\n    type: report\n",
        encoding="utf-8")
    (case / "a.txt").write_text(
        "甲乙丙丁股份有限公司与戊己庚辛股份有限公司2024年半年度归母净利润。",
        encoding="utf-8")

    class Boom:
        def chat(self, *a, **k):
            raise AssertionError("主体未锁定不应调用模型")

    result = run_case(
        RunSpec(case_dir=case, out_dir=case / "out", probe=False),
        RunDeps(client=Boom()),  # type: ignore[arg-type]
    )
    hl = (result.dossier.synthesis or {}).get("headline", "")
    assert "多家股份公司" in hl or "对象主体" in hl
    assert result.dossier.accounting.get("n_calls") == 0


def test_distributive_each_customer_does_not_clarify_multi_issuer():
    """各客户 = 分配性提问：多家主体不早退，只披露整卷研判。"""
    from app.core.answer_slots import slot_intent

    d = _dossier(
        "各客户项目是否存在延期、回款或人员流失风险？",
        [
            "某头部券商股份有限公司数据中台来往账目。",
            "某国有大行股份有限公司数据中台来往账目。",
        ],
    )
    intent = slot_intent(d.question, d)
    assert not any("多家股份公司" in t for t in intent["clarify"])
    assert intent["complete"] is True
    assert any("多主体整卷研判" in t for t in intent["disclosures"])


def test_distributive_does_not_mute_subsidiary_clarify():
    """分配性量词不能改哑「子公司未给全称」闸。"""
    from app.core.answer_slots import slot_intent

    intent = slot_intent("各客户子公司的营收分别是多少？")
    assert any("子公司" in t for t in intent["clarify"])


def test_bare_ge_aspect_still_clarifies_multi_issuer():
    """「各方面」不含分配性主体量词，多家仍要澄清。"""
    from app.core.answer_slots import slot_intent

    d = _dossier("各方面风险怎么样？", [
        "甲乙丙丁股份有限公司与戊己庚辛股份有限公司同期披露。",
    ])
    intent = slot_intent(d.question, d)
    assert any("多家股份公司" in t for t in intent["clarify"])


def test_bi_distributive_question_no_early_exit(tmp_path, monkeypatch):
    """bi 议题含各客户：不设 FORCE 也不应 slot 早退。"""
    from app.pipeline import RunDeps, RunSpec, run_case

    monkeypatch.delenv("VERITAS_FORCE_JUDGMENT", raising=False)
    case = tmp_path / "bi-dist"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "question: 各客户项目是否存在延期、回款或人员流失风险？\n"
        "sources:\n"
        "  - file: a.txt\n    type: report\n"
        "  - file: b.txt\n    type: report\n",
        encoding="utf-8")
    (case / "a.txt").write_text(
        "某头部券商股份有限公司项目回款正常。", encoding="utf-8")
    (case / "b.txt").write_text(
        "某国有大行股份有限公司项目进度正常。", encoding="utf-8")

    class Fixed:
        def __init__(self):
            self.call_log = []
            self.total_tokens_used = 0

        def chat(self, *a, **k):
            from types import SimpleNamespace
            self.call_log.append(1)
            self.total_tokens_used += 10
            return SimpleNamespace(content='{"conclusions":[]}')

    result = run_case(
        RunSpec(case_dir=case, out_dir=case / "out", probe=False),
        RunDeps(client=Fixed()),  # type: ignore[arg-type]
    )
    events = [r.event for r in result.chain.records]
    assert "slot_clarify_early_exit" not in events
    assert any("多主体整卷研判" in t
               for t in (result.dossier.accounting.get("slot_disclosures") or []))


def test_two_rounds_phrase_does_not_ask_to_pick_one():
    from app.core.answer_slots import slot_intent

    q = "恒兴新材在 2024 年披露过几轮股份回购方案？金额区间与用途有何不同？请按披露时间区分。"
    assert not any("轮次" in t for t in slot_intent(q)["clarify"])


def test_dividend_plan_is_not_profit_or_shareholder_gap():
    from app.core.answer_slots import slot_intent

    q = ("公司 2023 年度利润分配预案中，拟向全体股东每 10 股派多少现金红利？"
         "现金分红占归母净利润比例是多少？")
    tips = slot_intent(q)["clarify"]
    assert not any("利润" in t and "归母净利润" in t for t in tips)
    assert not any("时点快照" in t for t in tips)
    assert slot_intent(q)["complete"] is True


def test_missing_period_overrides_assumed_year_headline():
    """复现：未指定期间时模型假定 2024 半年度并喊资料不足 → 必须打掉。"""
    from app.core.answer_slots import apply_answer_contract

    d = _dossier("公司归母净利润是多少？", [
        "2024年半年度实现归属于上市公司股东的净利润31,831,900.82元。",
    ])
    d.conclusions.append(Conclusion.create(
        "2024年半年度，公司实现归属于上市公司股东的净利润31,831,900.82元。",
        author="a", id="CON-1"))
    d.conclusions[0].status = "majority"
    d.conclusions[0].confidence = 0.36
    synth = apply_answer_contract(d, {
        "mode": "llm",
        "headline": "资料不足，无法获取2024年半年度归属于上市公司股东的净利润。",
        "points": [], "open_issues": [], "gate_notes": [],
    })
    assert "议题未齐" in synth["headline"] or "未锁定会计期间" in synth["headline"]
    assert "2024" not in synth["headline"]
    assert "31,831" not in synth["headline"]
    assert "资料不足" not in synth["headline"]


def test_covered_slots_rewrite_false_insufficient_headline():
    q = "2024 年半年度，公司营业收入与归母净利润是多少？"
    d = _dossier(q, [
        "2024年半年度报告摘要\n"
        "营业收入 356,769,612.82\n"
        "归属于上市公司股东的净利润 31,831,900.82",
    ])
    d.sources[0].meta["file"] = "2024-08-26_2024年半年度报告摘要.pdf"
    d.conclusions.append(Conclusion.create(
        "2024年半年度实现归属于上市公司股东的净利润31,831,900.82元。",
        author="a", id="CON-1"))
    d.conclusions.append(Conclusion.create(
        "2024年半年度实现营业收入356,769,612.82元。",
        author="b", id="CON-2"))
    for c in d.conclusions:
        c.status = "majority"
        c.confidence = 0.5
    from app.core.answer_slots import apply_answer_contract
    synth = apply_answer_contract(d, {
        "mode": "llm",
        "headline": "资料不足，无法获取2024年半年度归属于上市公司股东的净利润。",
        "points": [],
        "open_issues": [{"kind": "gap", "ref": "议题",
                         "text": "结论涉及归母净利润，但资料缺失，不予采纳。"}],
        "gate_notes": [],
    })
    assert not synth["headline"].startswith("资料不足")
    assert "31,831,900.82" in synth["headline"]
    assert "356,769" in synth["headline"]
    assert all(a["status"] == "covered" for a in synth["slots"])


def test_headline_lifts_absolute_net_profit_over_yoy_only():
    """问「是多少」时，标题必须带净利绝对值，不能只剩同比句。"""
    from app.core.answer_slots import apply_answer_contract

    q = "2024 年半年度，公司营业收入与归母净利润是多少？归母净利润同比变动多少？"
    d = _dossier(q, [
        "2024年半年度报告摘要\n"
        "营业收入 356,769,612.82\n"
        "归属于上市公司股东的净利润 31,831,900.82",
    ])
    d.sources[0].meta["file"] = "2024-08-26_2024年半年度报告摘要.pdf"
    d.conclusions.append(Conclusion.create(
        "2024年半年度，公司实现营业收入356,769,612.82元。",
        author="a", id="CON-1"))
    d.conclusions.append(Conclusion.create(
        "2024年半年度，公司归属于上市公司股东的净利润较上年同期下降28.05%。",
        author="b", id="CON-2"))
    d.conclusions.append(Conclusion.create(
        "2024年半年度，公司实现归属于上市公司股东的净利润31,831,900.82元。",
        author="c", id="CON-3"))
    for c, conf in zip(d.conclusions, (0.51, 0.51, 0.36)):
        c.status = "majority"
        c.confidence = conf
    synth = apply_answer_contract(d, {
        "mode": "llm",
        "headline": ("2024年半年度，公司实现营业收入356,769,612.82元；"
                     "2024年半年度，公司归属于上市公司股东的净利润较上年同期下降28.05%"),
        "points": [], "open_issues": [], "gate_notes": [],
    })
    assert "31,831,900.82" in synth["headline"]
    assert "356,769" in synth["headline"]


def test_publication_date_is_not_the_accounting_period():
    d = _dossier(_Q, [
        "2025年4月28日，公司披露2024年度归属于上市公司股东的净利润为34,853,361.18元。",
    ])
    a = assess_slots(d)[0]
    assert a["status"] == "insufficient"
    assert a["nearest"]["year"] == 2024
    assert a["nearest"]["grain"] == "fy"


def test_half_year_does_not_cover_full_year():
    d = _dossier(_Q, [
        "2025年半年度归属于上市公司股东的净利润为2,911.51万元。",
    ])
    a = assess_slots(d)[0]
    assert a["status"] == "insufficient"
    assert a["nearest"]["grain"] == "h1"


def test_exact_period_is_covered():
    d = _dossier(_Q, [
        "2025年全年归属于上市公司股东的净利润为1,000万元。",
    ])
    assert assess_slots(d)[0]["status"] == "covered"


def test_chair_headline_refuses_other_year_number():
    d = _dossier(_Q, [
        "2024年度归属于上市公司股东的净利润为34,853,361.18元。",
    ])
    d.conclusions.append(Conclusion.create(
        "最新全年净利润为2024年度的34,853,361.18元。",
        author="a", id="CON-1"))
    d.conclusions[0].status = "majority"
    d.conclusions[0].confidence = 0.8
    synth = render_chair_template(d)
    assert synth["headline"].startswith("资料不足")
    assert "34,853,361.18" not in synth["headline"]
    assert "34853361" not in synth["headline"]
    assert any(i["kind"] == "gap" and "未披露" in i["text"]
               for i in synth["open_issues"])


def test_llm_headline_overridden_when_slot_uncovered():
    class Stub:
        def chat(self, model, messages, json_mode=False):
            from types import SimpleNamespace
            import json
            body = json.dumps({
                "headline": "2025年全年归母净利润为3485万元",
                "points": [],
                "open_issues": [],
            }, ensure_ascii=False)
            return SimpleNamespace(content=body)

    d = _dossier(_Q, [
        "2024年度归属于上市公司股东的净利润为100万元。",
    ])
    synth = build_synthesis(d, Stub(), "m")
    assert synth["headline"].startswith("资料不足")
    assert "3485" not in synth["headline"]
    assert any("槽位" in n for n in synth.get("gate_notes") or [])


def test_dividend_ratio_question_does_not_ask_for_net_profit():
    q = ("公司 2023 年度利润分配预案中，拟向全体股东每 10 股派多少现金红利？"
         "现金分红占归母净利润比例是多少？转增后总股本预计多少？")
    slots = parse_slots(q)
    assert all(s["metric_id"] != "net_profit_parent" for s in slots)
    d = _dossier(q, ["2023年度每10股派发现金红利2元（含税），占归母净利润比例40.70%。"])
    d.conclusions.append(Conclusion.create(
        "每10股派发现金红利2元（含税），转增后总股本207,667,617股。",
        author="a", id="CON-1"))
    d.conclusions[0].status = "majority"
    d.conclusions[0].confidence = 0.5
    synth = render_chair_template(d)
    assert not synth["headline"].startswith("资料不足")


def test_report_period_in_filename_covers_table_row():
    """表内只写「本报告期」，期间在文件名：2024 半年报应判覆盖。"""
    q = "2024 年半年度归母净利润是多少？"
    d = _dossier(q, [
        "本报告期主要财务数据\n"
        "归属于上市公司股东的净利润 31,831,900.82 44,243,529.09 -28.05",
    ])
    d.sources[0].meta["file"] = "2024-08-26_2024年半年度报告摘要.pdf"
    a = assess_slots(d)[0]
    assert a["status"] == "covered"
    assert a["grain"] == "h1"
    assert a["metric_id"] == "net_profit_parent"


def test_half_year_filename_does_not_cover_full_year_ask():
    q = "恒兴新材 2024 年全年归属于上市公司股东的净利润是多少？"
    d = _dossier(q, [
        "2024 年半年度报告摘要\n"
        "归属于上市公司股东的净利润 31,831,900.82",
    ])
    d.sources[0].meta["file"] = "2024-08-26_2024年半年度报告摘要.pdf"
    assert assess_slots(d)[0]["status"] == "insufficient"


def test_unrelated_question_is_not_rewritten():
    d = _dossier("客户B的交付风险如何？", ["客户B延期6天。"])
    assert parse_slots(d.question) == []
    assert "资料不足" not in render_chair_template(d)["headline"]


def test_metric_period_segment_is_pinned():
    noise = "天气晴朗适合出行" * 8
    hit = "2024年度归属于上市公司股东的净利润为100万元。"
    d = _dossier(_Q, [noise, hit])
    pack = pack_material(d, budget_chars=len(hit))
    assert "SRC2#s1" in pack["selected"]
    assert "SRC1#s1" not in pack["selected"]
