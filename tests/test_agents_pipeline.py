"""分析师结构化输出契约 + 管线端到端（FakeClient 桩，零 key 全绿）。"""

from types import SimpleNamespace

from app.agents.base import Analyst, extract_json
from app.core.hashchain import HashChain
from app.pipeline import PipelineResult, run_case


GOOD_BAD_JSON = """```json
{"conclusions": [
  {"statement": "固态电池能量密度占优",
   "evidence": [{"quote": "能量密度显著高于液态锂离子电池",
                 "segment_id": "SRC1#s1",
                 "relation": "correlation", "level": "A", "note": "直接引证"}]},
  {"statement": "成本已经低于液态电池",
   "evidence": [{"quote": "成本已降至液态电池一半以下",
                 "segment_id": "SRC1#s1",
                 "relation": "causation", "level": "A", "note": "编造"}]}
]}
```"""


class FakeClient:
    """鸭子类型桩：只实现 Analyst 用到的 chat。"""

    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "messages": messages, "json_mode": json_mode})
        return SimpleNamespace(content=self.content)


def _make_case(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "question: 固态电池 2030 能否规模上车？\n"
        "sources:\n  - file: a.md\n    type: paper\n",
        encoding="utf-8",
    )
    (tmp_path / "a.md").write_text(
        "# 摘要\n\n本次测评显示固态电池的能量密度显著高于液态锂离子电池，但成本仍高于预期。\n",
        encoding="utf-8",
    )


def test_extract_json_tolerates_fence_and_noise():
    data = extract_json('前言垃圾\n```json\n{"a": 1}\n```\n后缀')
    assert data == {"a": 1}
    assert extract_json('x {"b": [1,2]} y') == {"b": [1, 2]}


def test_analyst_materializes_conclusions_and_evidence(tmp_path):
    _make_case(tmp_path)
    from app.ingest.case_loader import load_case

    dossier = load_case(tmp_path)
    analyst = Analyst("m", "测试角色", FakeClient(GOOD_BAD_JSON), "test-model")
    conclusions = analyst.analyze(dossier)
    assert len(conclusions) == 2
    assert len(dossier.evidences) == 2
    # 独立研判隔离：提示词里带隔离声明
    assert "独立研判" in analyst.client.calls[0]["messages"][0]["content"]


def test_run_case_end_to_end_with_rejection(tmp_path):
    _make_case(tmp_path)
    fake = FakeClient(GOOD_BAD_JSON)
    # 注入单分析师：周 1 最小闭环口径（协同段仅 ≥2 分析师才走）
    single = [Analyst("mainstream", "测试角色", fake, "test-model")]
    result = run_case(tmp_path, out_dir=tmp_path / "out", client=fake,
                      analysts=single)
    assert isinstance(result, PipelineResult)

    # 好证据存活、编造引文被打回
    assert len(result.dossier.evidences) == 1
    assert len(result.rejected) == 1
    assert "未命中" in result.rejected[0]["problems"][0]

    # 置信度已回填且落在 (0,1]
    con = result.dossier.conclusions[0]
    assert 0.0 < con.confidence <= 1.0

    # 三件出口文件齐
    assert (tmp_path / "out" / "report.json").is_file()
    assert (tmp_path / "out" / "report.md").is_file()
    assert (tmp_path / "out" / "chain.jsonl").is_file()

    # 哈希链全程可验证
    assert result.chain.verify_chain().ok
    events = [r.event for r in result.chain.records]
    assert events[0] == "case_loaded" and "citation_audit" in events

    # 报告 Markdown 含防篡改校验段与被打回段
    md = result.report_md
    assert "防篡改校验" in md and "✅" in md and "被打回的证据" in md


def test_run_case_without_analyst_output_still_writes_report(tmp_path):
    _make_case(tmp_path)
    fake = FakeClient('{"conclusions": []}')
    single = [Analyst("mainstream", "测试角色", fake, "test-model")]
    result = run_case(tmp_path, out_dir=tmp_path / "out", client=fake,
                      analysts=single)
    assert result.dossier.conclusions == []
    assert result.chain.verify_chain().ok
    assert "无结论" in result.report_md


def test_conclusions_with_all_evidence_rejected_are_dropped(tmp_path):
    """结论的全部引文被机械核对打回 → 结论不进报告，链上留痕。"""
    _make_case(tmp_path)
    fake = FakeClient('{"conclusions": [{"statement": "成本已经低于液态电池", '
                      '"evidence": [{"quote": "成本已降至液态电池一半以下", '
                      '"segment_id": "SRC1#s1", "relation": "causation", '
                      '"level": "A", "note": "编造"}]}]}')
    single = [Analyst("mainstream", "测试角色", fake, "test-model")]
    result = run_case(tmp_path, out_dir=tmp_path / "out", client=fake,
                      analysts=single)
    assert result.dossier.conclusions == []
    assert result.rejected and "未命中" in result.rejected[0]["problems"][0]
    audit = next(r for r in result.chain.records if r.event == "citation_audit")
    assert audit.payload["n_conclusions_dropped"] == 1
    assert "无结论" in result.report_md
