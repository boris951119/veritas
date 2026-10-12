"""刀十一：未用关键段二次定向研判。"""

from types import SimpleNamespace

from app.agents.base import Analyst
from app.agents.prompts import render_segments_block
from app.agents.second_pass import pick_focus_segments, run_second_pass
from app.core.coverage_gap import unused_topic_segments
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
)


def _bi_like() -> Dossier:
    d = Dossier(question=(
        "各客户项目是否存在延期、回款/坏账或人员流失风险？"))
    src2 = Source.create("进度", SourceType.REPORT, id="SRC2")
    src2.segments.append(Segment(
        id="SRC2#s5", source_id="SRC2",
        text="风险台账：进度延迟70%，核心开发人员离职20%，回款周期拉长。"))
    src6 = Source.create("计划", SourceType.REPORT, id="SRC6")
    src6.segments.append(Segment(
        id="SRC6#s6", source_id="SRC6",
        text="风险管理计划：进度延迟概率高，核心人员离职影响等级高。"))
    src1 = Source.create("账目", SourceType.REPORT, id="SRC1")
    src1.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="项目账目统计截止日为2025年3月31日。"))
    for s in (src1, src2, src6):
        d.add_source(s)
    return d


def test_pick_focus_prefers_unused_risk_segments():
    d = _bi_like()
    # 先引用账目段，风险段应进焦点
    con = Conclusion.create("账目已截止", author="a0", id="CON1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "项目账目统计截止日为2025年3月31日", ["SRC1#s1"], author="a0"))
    focus = pick_focus_segments(d, limit=3)
    ids = [f["segment_id"] for f in focus]
    assert "SRC2#s5" in ids or "SRC6#s6" in ids
    assert "SRC1#s1" not in ids


def test_render_focus_only_lists_focus_segments():
    d = _bi_like()
    block = render_segments_block(d, focus_segment_ids=["SRC6#s6"])
    assert "二次定向研判" in block
    assert "SRC6#s6" in block
    assert "SRC2#s5" not in block
    assert "SRC1#s1" not in block


def test_second_pass_stub_cites_focus_segment():
    d = _bi_like()
    # 无引用 → 焦点含风险段
    assert any(u["segment_id"] == "SRC6#s6" for u in unused_topic_segments(d))

    class Stub:
        def chat(self, model, messages, **kwargs):
            user = messages[-1]["content"]
            assert "SRC6#s6" in user or "SRC2#s5" in user
            assert "二次定向" in user
            # 引用焦点段
            sid = "SRC6#s6" if "SRC6#s6" in user else "SRC2#s5"
            quote = d.segment(sid).text[:40]
            import json
            return SimpleNamespace(content=json.dumps({
                "conclusions": [{
                    "statement": "存在进度延迟与核心人员离职风险",
                    "evidence": [{
                        "quote": quote,
                        "segment_id": sid,
                        "relation": "correlation",
                        "level": "B",
                        "note": "风险台账",
                    }],
                }],
            }, ensure_ascii=False))

    a = Analyst("mainstream", "主流", Stub(), "m")
    sp = run_second_pass(d, [a], max_segments=2)
    assert sp["status"] == "ok"
    assert sp["n_conclusions"] >= 1
    cited = {sid for ev in d.evidences for sid in ev.segment_ids}
    assert cited & set(sp["focus_ids"])


def test_second_pass_skipped_when_all_cited():
    d = _bi_like()
    for i, sid in enumerate(["SRC1#s1", "SRC2#s5", "SRC6#s6"]):
        con = Conclusion.create(f"c{i}", author="a0", id=f"C{i}")
        d.conclusions.append(con)
        d.add_evidence(EvidenceNode.create(
            f"C{i}", d.segment(sid).text[:20], [sid], author="a0"))
    class Boom:
        def chat(self, *a, **k):
            raise AssertionError("不应再调用")
    sp = run_second_pass(d, [Analyst("mainstream", "x", Boom(), "m")])
    assert sp["status"] == "skipped"
    assert sp["reason"] == "no_focus"
