"""C-16：引用段落不存在／未编号时的静默丢弃必须留痕，insufficient 必有成因。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.agents.base import Analyst
from app.core.evidence import Conclusion, Dossier, Segment, Source, SourceType
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


def test_d_roundtrip_and_demo_offline_invariant(tmp_path):
    """d) 序列化 round-trip；demo_offline 新跑的 insufficient 全部有成因。

    34 份历史 report 没有 parse_drops 键——只作统计对照，不许拿它们断言新键。
    """
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

    # 统计对照（改前历史留档）：34 份／活结论 304／零证据 10／有打回 5／无打回 5。
    # 不许对它们断言 parse_drops 键——那是改前产物，断言必然假红；demo 也会改写 out_offline。
    from collections import defaultdict

    hist = list(Path("cases").glob("*/out*/report.json"))
    assert len(hist) == 34
    n_live = n_zero = n_with_rej = n_without_rej = 0
    for p in hist:
        blob = json.loads(p.read_text(encoding="utf-8"))
        by_cid = defaultdict(list)
        for e in blob.get("evidences") or []:
            by_cid[e.get("conclusion_id")].append(e)
        rej_by = defaultdict(list)
        for r in blob.get("rejected") or []:
            rej_by[r.get("conclusion_id")].append(r)
        for c in blob.get("conclusions") or []:
            if c.get("status") == "merged":
                continue
            n_live += 1
            if by_cid.get(c.get("id")):
                continue
            n_zero += 1
            if rej_by.get(c.get("id")):
                n_with_rej += 1
            else:
                n_without_rej += 1
    assert (n_live, n_zero, n_with_rej, n_without_rej) == (304, 10, 5, 5)

    from scripts.demo_offline import main as demo_main

    demo_main()
    for case in ("demo-solid-state", "bi-delivery-risk"):
        report = Path("cases") / case / "out_offline" / "report.json"
        dossier = Dossier.from_json(report)
        cause_ids = {
            str(r.get("conclusion_id") or "")
            for r in (list(dossier.rejected or []) + list(dossier.parse_drops or []))
            if r.get("conclusion_id")
        }
        insuff = [c for c in dossier.conclusions if c.status == "insufficient"]
        for con in insuff:
            assert con.id in cause_ids, con.id
        # 判定没变：离线演示两案与改前同量级（本就不应出现零证据 insufficient）
        assert len(insuff) == 0


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
    """f) 禁止触碰的文件相对基线 58e8610 零改动；pipeline 只动渲染与链事件。"""
    import subprocess

    base = "58e8610"
    for path in (
        "app/core/conflicts.py",
        "app/core/human_ops.py",
        "app/export/official.py",
        "app/core/citation_check.py",
    ):
        out = subprocess.check_output(
            ["git", "diff", base, "--", path], text=True)
        assert out == "", path

    pipe = subprocess.check_output(
        ["git", "diff", base, "--", "app/pipeline.py"], text=True)
    # 只许出现 citation_audit 的 n_parse_dropped 与渲染区两处相关文案
    assert "n_parse_dropped" in pipe
    assert "引用未落地的证据" in pipe
    assert "成因缺失（异常）" in pipe
    # 不许动 empties 判定
    assert 'and c.status != "merged"' in Path("app/pipeline.py").read_text(encoding="utf-8")
    assert "con.status = \"insufficient\"" in Path("app/pipeline.py").read_text(
        encoding="utf-8")
