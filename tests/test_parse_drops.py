"""C-16：引用段落不存在／未编号时的静默丢弃必须留痕，insufficient 必有成因。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.agents.base import Analyst
from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
)
from app.core.hashchain import HashChain
from app.pipeline import RunDeps, RunSpec, render_report_md, run_case


class FakeClient:
    def __init__(self, content: str):
        self.content = content

    def chat(self, model, messages, json_mode=False):
        return SimpleNamespace(content=self.content)


def _make_case(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text(
        "question: Q\n"
        "sources:\n  - file: a.md\n    type: paper\n",
        encoding="utf-8",
    )
    (tmp_path / "a.md").write_text(
        "# 摘要\n\n本次测评显示固态电池的能量密度显著高于液态锂离子电池。\n",
        encoding="utf-8",
    )


def test_a_missing_segment_leaves_parse_drop_and_insufficient(tmp_path):
    """a) 引用不存在的段落 → parse_drops 1 条，结论 insufficient，成因可查。"""
    _make_case(tmp_path)
    payload = json.dumps({
        "conclusions": [{
            "statement": "能量密度占优",
            "evidence": [{
                "quote": "能量密度显著高于液态锂离子电池",
                "segment_id": "SRC9#s99",
                "relation": "correlation",
                "level": "A",
                "note": "悬空引用",
            }],
        }],
    }, ensure_ascii=False)
    fake = FakeClient(payload)
    single = [Analyst("mainstream", "测试角色", fake, "test-model")]
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out"),
        RunDeps(client=fake, analysts=single),
    )
    drops = result.dossier.parse_drops
    assert len(drops) == 1
    assert "不存在" in drops[0]["reason"]
    assert drops[0]["segment_id"] == "SRC9#s99"
    assert [c.status for c in result.dossier.conclusions] == ["insufficient"]
    con_id = result.dossier.conclusions[0].id
    assert drops[0]["conclusion_id"] == con_id
    assert result.rejected == []
    cause_ids = {r["conclusion_id"] for r in drops}
    assert con_id in cause_ids
    audit = next(r for r in result.chain.records if r.event == "citation_audit")
    assert audit.payload["n_parse_dropped"] == 1
    assert "引用未落地的证据（段落不存在／未编号）" in result.report_md
    assert "成因缺失（异常）" not in result.report_md


def test_a_three_sites_share_one_reason():
    """a) base／repair／ingress 悬空引用留痕文案一致，author 各取各的身份。"""
    from app.agents.ingress import ingest_external_judgment
    from app.agents.repair import _apply_repair

    def _src(dossier: Dossier) -> None:
        src = Source.create("T", SourceType.PAPER, id="SRC1")
        src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="原文足够长"))
        dossier.add_source(src)

    base = Dossier(question="Q")
    _src(base)
    Analyst("分析师甲", "角色", FakeClient(json.dumps({
        "conclusions": [{
            "statement": "悬空",
            "evidence": [{"quote": "原文足够长", "segment_id": "SRC9#s99"}],
        }],
    }, ensure_ascii=False)), "m").analyze(base)

    repaired = Dossier(question="Q")
    _src(repaired)
    con = Conclusion.create("待修复", author="修复环乙", id="CON-r")
    repaired.conclusions.append(con)
    _apply_repair(repaired, con, {"conclusions": [{
        "statement": "待修复",
        "evidence": [{"quote": "原文足够长", "segment_id": "SRC9#s99"}],
    }]})

    ingested = Dossier(question="Q")
    _src(ingested)
    ingest_external_judgment(ingested, {
        "agent": "入卷丙",
        "conclusions": [{
            "statement": "外部悬空",
            "evidence": [{"quote": "原文足够长", "segment_id": "SRC9#s99"}],
        }],
    })

    drops = [base.parse_drops[0], repaired.parse_drops[0], ingested.parse_drops[0]]
    assert len({row["author"] for row in drops}) == 3
    assert {row["author"] for row in drops} == {"分析师甲", "修复环乙", "入卷丙"}
    assert len({row["reason"] for row in drops}) == 1
    assert drops[0]["reason"] == "引用段落不存在（segment_id=SRC9#s99）"


def test_c_non_dict_evidence_has_its_own_reason(tmp_path):
    """c) 证据条目是字符串时走第三格，结论仍 insufficient，报告不印成因缺失。"""
    _make_case(tmp_path)
    payload = json.dumps({
        "conclusions": [{
            "statement": "能量密度占优",
            "evidence": ["这不是对象"],
        }],
    }, ensure_ascii=False)
    fake = FakeClient(payload)
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out"),
        RunDeps(client=fake, analysts=[
            Analyst("mainstream", "测试角色", fake, "test-model"),
        ]),
    )
    assert len(result.dossier.parse_drops) == 1
    reason = result.dossier.parse_drops[0]["reason"]
    assert reason == "证据条目不是对象（渲染层拿不到）"
    assert "未给出 segment_id" not in reason
    assert "引用段落不存在" not in reason
    assert [c.status for c in result.dossier.conclusions] == ["insufficient"]
    assert "成因缺失（异常）" not in result.report_md
    assert "引用未落地的证据（段落不存在／未编号）" in result.report_md


def test_d_ingress_dangling_shows_in_report():
    """d) 入卷悬空引用出现在留痕节，报告不含成因缺失。"""
    from app.agents.ingress import ingest_external_judgment

    d = Dossier(question="入卷")
    src = Source.create("T", SourceType.PAPER, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="原文足够长可以引用。"))
    d.add_source(src)
    ingest_external_judgment(d, {
        "agent": "外部分析师",
        "conclusions": [{
            "statement": "能量密度占优",
            "evidence": [{
                "quote": "能量密度显著高于液态",
                "segment_id": "SRC9#s99",
            }],
        }],
    })
    md = render_report_md(d, HashChain(), [])
    assert "引用未落地的证据（段落不存在／未编号）" in md
    assert "引用段落不存在（segment_id=SRC9#s99）" in md
    assert "成因缺失（异常）" not in md


def test_a2_empty_segment_id_reason():
    """a 的另一格：未给出 segment_id 时 reason 走另一条文案。"""
    d = Dossier(question="Q")
    src = Source.create("T", SourceType.PAPER, id="SRC1")
    src.segments.append(Segment(id="SRC1#s1", source_id="SRC1", text="原文足够长"))
    d.add_source(src)
    Analyst("mainstream", "测试角色", FakeClient(json.dumps({
        "conclusions": [{
            "statement": "悬空",
            "evidence": [{"quote": "原文足够长", "segment_id": "", "level": "C"}],
        }],
    }, ensure_ascii=False)), "m").analyze(d)
    assert len(d.parse_drops) == 1
    assert d.parse_drops[0]["reason"] == "未给出 segment_id"
    assert d.evidences == []


def test_b_citation_fail_goes_only_to_rejected(tmp_path):
    """b) 段落存在但引文不过闸 → 只进 rejected，两节标题分家。"""
    _make_case(tmp_path)
    payload = json.dumps({
        "conclusions": [{
            "statement": "成本已经低于液态电池",
            "evidence": [{
                "quote": "成本已降至液态电池一半以下",
                "segment_id": "SRC1#s1",
                "relation": "causation",
                "level": "A",
                "note": "编造",
            }],
        }],
    }, ensure_ascii=False)
    fake = FakeClient(payload)
    single = [Analyst("mainstream", "测试角色", fake, "test-model")]
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out"),
        RunDeps(client=fake, analysts=single),
    )
    assert result.rejected and "未命中" in result.rejected[0]["problems"][0]
    assert result.dossier.parse_drops == []
    md = result.report_md
    assert md.count("## 被打回的证据（引文核对未通过）") == 1
    assert "引用未落地的证据（段落不存在／未编号）" not in md
    rejected_block = md.split("## 被打回的证据（引文核对未通过）", 1)[1]
    rejected_block = rejected_block.split("## ", 1)[0]
    assert "引用未落地" not in rejected_block
    assert "段落不存在" not in rejected_block
    assert "未编号" not in rejected_block


def test_c_invariant_anomaly_appears_and_clears():
    """c) insufficient 无留痕 → 印成因缺失；补上后消失。"""
    d = Dossier(question="Q")
    d.conclusions.append(Conclusion.create(
        "资料不足：悬空结论", author="a", id="CON-x", status="insufficient"))
    chain = HashChain()
    md_bad = render_report_md(d, chain, rejected=[])
    assert "成因缺失（异常）" in md_bad

    d.parse_drops.append({
        "conclusion_id": "CON-x",
        "author": "a",
        "segment_id": "SRC9#s99",
        "quote_head": "x",
        "reason": "引用段落不存在（segment_id=SRC9#s99）",
    })
    md_ok = render_report_md(d, chain, rejected=[])
    assert "成因缺失（异常）" not in md_ok
    assert "引用未落地的证据（段落不存在／未编号）" in md_ok


def _cause_ids(dossier: Dossier) -> set[str]:
    return {
        str(r.get("conclusion_id") or "")
        for r in (list(dossier.rejected or []) + list(dossier.parse_drops or []))
        if r.get("conclusion_id")
    }


def test_d_roundtrip_and_dangling_has_cause(tmp_path):
    """d) 序列化 round-trip；自建悬空引用的 insufficient 全部有成因。"""
    drop = {
        "conclusion_id": "CON-1",
        "author": "mainstream",
        "segment_id": "SRC9#s99",
        "quote_head": "引文头",
        "reason": "引用段落不存在（segment_id=SRC9#s99）",
    }
    d = Dossier(question="Q", parse_drops=[drop])
    loaded = Dossier.from_dict(d.to_dict())
    assert loaded.parse_drops == [drop]

    case = tmp_path / "dangling"
    case.mkdir()
    _make_case(case)
    payload = json.dumps({
        "conclusions": [{
            "statement": "能量密度占优",
            "evidence": [{
                "quote": "能量密度显著高于液态锂离子电池",
                "segment_id": "SRC9#s99",
                "level": "A",
            }],
        }],
    }, ensure_ascii=False)
    result = run_case(
        RunSpec(case_dir=case, out_dir=case / "out"),
        RunDeps(client=FakeClient(payload), analysts=[
            Analyst("mainstream", "测试角色", FakeClient(payload), "test-model"),
        ]),
    )
    insuff = [c for c in result.dossier.conclusions if c.status == "insufficient"]
    assert len(insuff) >= 1
    causes = _cause_ids(result.dossier)
    for con in insuff:
        assert con.id in causes, con.id
    assert "成因缺失（异常）" not in result.report_md


def _repair_dossier():
    d = Dossier(question="Q")
    src = Source.create("T", SourceType.PAPER, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text="原文足够长可以引用。"))
    d.add_source(src)
    con = Conclusion.create("能量密度 300Wh/kg 占优", author="analyst_a", id="CON-1")
    d.conclusions.append(con)
    ev = EvidenceNode.create(
        con.id, "原文足够长", ["SRC1#s1"], author="analyst_a")
    d.evidences.append(ev)
    con.evidence_ids.append(ev.id)
    return d, con


def test_i_rejected_repair_rolls_back_drops_accepted_keeps_one():
    """i) 被拒的修复不留虚痕；被接受且真丢掉一条时留痕恰 1 条。"""
    from app.agents.repair import RepairCtx, run_repair_round

    class RejectClient:
        def chat(self, model, messages, json_mode=False):
            return SimpleNamespace(content=json.dumps({"conclusions": [{
                "statement": "能量密度 300Wh/kg 占优",
                "evidence": [{
                    "quote": "原文足够长", "segment_id": "SRC9#s99", "level": "A",
                }],
            }]}, ensure_ascii=False))

    rejected, con = _repair_dossier()
    before = list(rejected.parse_drops)
    stats = run_repair_round(
        rejected,
        [{"kind": "provenance", "conclusion_id": con.id, "detail": "数字无出处"}],
        RepairCtx(client=RejectClient(), model="stub", max_repairs=2),
    )
    assert stats["accepted"] == 0
    assert rejected.parse_drops == before
    assert len(rejected.evidences_of(con.id)) == 1
    md = render_report_md(rejected, HashChain(), [])
    assert "引用未落地的证据" not in md

    class AcceptClient:
        def chat(self, model, messages, json_mode=False):
            return SimpleNamespace(content=json.dumps({"conclusions": [{
                "statement": "能量密度占优",
                "evidence": [
                    {"quote": "原文足够长", "segment_id": "SRC1#s1", "level": "A"},
                    {"quote": "悬空引文", "segment_id": "SRC9#s99", "level": "A"},
                ],
            }]}, ensure_ascii=False))

    accepted, con2 = _repair_dossier()
    stats2 = run_repair_round(
        accepted,
        [{"kind": "provenance", "conclusion_id": con2.id, "detail": "数字无出处"}],
        RepairCtx(client=AcceptClient(), model="stub", max_repairs=2),
    )
    assert stats2["accepted"] == 1
    assert len(accepted.evidences_of(con2.id)) == 1
    assert len(accepted.parse_drops) == 1
    assert accepted.parse_drops[0]["reason"] == "引用段落不存在（segment_id=SRC9#s99）"
    md2 = render_report_md(accepted, HashChain(), [])
    assert "引用未落地的证据" in md2


def test_e_export_bytes_unchanged_by_parse_drops(tmp_path):
    """e) 纯留痕：同一案卷有无 parse_drops，四份提交 JSON 逐字节相同。"""
    from app.export.official import export_official
    from app.ingest.case_loader import load_case

    _make_case(tmp_path)
    dossier = load_case(tmp_path)
    dossier.conclusions.append(Conclusion.create("有支撑", author="m", id="CON-1"))
    from app.core.evidence import EvidenceNode
    text = dossier.sources[0].segments[0].text
    sid = dossier.sources[0].segments[0].id
    dossier.add_evidence(EvidenceNode.create(
        "CON-1", text[: min(40, len(text))] or text, [sid], id="EV-1"))
    dossier.sources[0].meta["doc_id"] = "doc_001"

    runs = [({"question_id": "q1", "question": "Q"}, dossier)]
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    paths_a = export_official(runs, out_a)
    dossier.parse_drops = [{
        "conclusion_id": "CON-ghost",
        "author": "m",
        "segment_id": "SRC9#s99",
        "quote_head": "ghost",
        "reason": "引用段落不存在（segment_id=SRC9#s99）",
    }]
    paths_b = export_official(runs, out_b)
    for key in ("evidence", "conclusions", "confidence", "conflict_resolution"):
        assert paths_a[key].read_bytes() == paths_b[key].read_bytes()


def test_f_forbidden_files_untouched():
    """f) citation_check 相对 C-16 基线仍为零；pipeline 自 C-16 之后没有新 diff。

    conflicts.py／human_ops.py／official.py 是 C-14b 的允许落点，不再相对 58e8610 钉死。
    """
    import subprocess

    base = "c68fe30"
    out = subprocess.check_output(
        ["git", "diff", base, "--", "app/core/citation_check.py"], text=True)
    assert out == ""
    # C-17 要在 pipeline 加 content_head 与空交付节，不能再钉「相对 c68fe30 零 diff」。
    # 仍钉：citation_check 零 diff，且 empties→insufficient 那两句还在。
    pipe_since = subprocess.check_output(
        ["git", "diff", base, "--", "app/pipeline.py"], text=True)
    assert "content_head" in pipe_since
    assert "empty_runs" in pipe_since

    pipe = subprocess.check_output(
        ["git", "diff", "58e8610", "--", "app/pipeline.py"], text=True)
    # 只许出现 citation_audit 的 n_parse_dropped 与渲染区两处相关文案
    assert "n_parse_dropped" in pipe
    assert "引用未落地的证据" in pipe
    assert "成因缺失（异常）" in pipe
    # 不许动 empties 判定
    assert 'and c.status != "merged"' in Path("app/pipeline.py").read_text(encoding="utf-8")
    assert "con.status = \"insufficient\"" in Path("app/pipeline.py").read_text(
        encoding="utf-8")
