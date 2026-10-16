"""C-12：官方案卷进得来、四份 JSON 出得去、精确匹配下界评分器。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.agents.base import Analyst
from app.core.material import pack_material
from app.export.official import export_official
from app.ingest.official_case import load_official_case
from app.pipeline import RunDeps, run_official_case
from scripts.score_official import DISCLAIMER, format_report, score_submission


def _write_docs(tmp_path: Path, docs: list[dict]) -> Path:
    (tmp_path / "raw_documents.json").write_text(
        json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _para(para_id: str, start: int, end: int) -> dict:
    return {"para_id": para_id, "char_start": start, "char_end": end}


def test_para_id_preserved_and_slice_exact(tmp_path):
    """a) 段 id 与切片逐字等于官方 para_id / content 偏移。"""
    docs = []
    for i in (1, 2):
        content = f"文档{i}甲段正文。" + f"文档{i}乙段正文。" + f"文档{i}丙段正文。"
        cuts = []
        cursor = 0
        for name in ("甲", "乙", "丙"):
            piece = f"文档{i}{name}段正文。"
            cuts.append(_para(f"d{i}{name}", cursor, cursor + len(piece)))
            cursor += len(piece)
        docs.append({
            "doc_id": f"doc_{i}",
            "title": f"t{i}",
            "publish_time": "2024-01-02",
            "content": content,
            "source_credibility": 0.4,
            "content_url": "https://example.invalid/a",
            "paragraphs": cuts,
        })
    dossier = load_official_case(_write_docs(tmp_path, docs))
    assert len(dossier.sources) == 2
    for src in dossier.sources:
        raw = next(d for d in docs if d["doc_id"] == src.id)
        assert len(src.segments) == 3
        for seg, para in zip(src.segments, raw["paragraphs"]):
            assert seg.id == para["para_id"]
            assert seg.text == raw["content"][para["char_start"]:para["char_end"]]


def test_long_paragraph_not_resplit(tmp_path):
    """b) 超过 650 字的官方段仍是 1 段。"""
    text = "段" * 1200
    dossier = load_official_case(_write_docs(tmp_path, [{
        "doc_id": "doc_long",
        "title": "长",
        "publish_time": "2024-01-02",
        "content": text,
        "source_credibility": 0.4,
        "content_url": "",
        "paragraphs": [_para("p_long", 0, 1200)],
    }]))
    segs = dossier.sources[0].segments
    assert len(segs) == 1
    assert segs[0].id == "p_long"
    assert len(segs[0].text) == 1200
    assert segs[0].text == text


def test_short_paragraph_filtered_ids_unchanged(tmp_path):
    """c) 2 字段不进检索，其余 para_id 不重编号，披露有条数。"""
    content = "甲乙丙丁戊" + "短" + "后续段落正文足够长"
    # 5 + 1 + rest. Use explicit slices: p1=5 chars, p2=2 chars, p3=the rest.
    content = "甲乙丙丁戊" + "长短" + "后续段落足够长"
    p1, p2, p3 = content[:5], content[5:7], content[7:]
    assert len(p2) == 2 and len(p1) >= 5 and len(p3) >= 5
    dossier = load_official_case(_write_docs(tmp_path, [{
        "doc_id": "doc_x",
        "title": "x",
        "publish_time": "2024-01-02",
        "content": content,
        "source_credibility": 0.2,
        "content_url": "",
        "paragraphs": [
            _para("p1", 0, 5),
            _para("p2", 5, 7),
            _para("p3", 7, len(content)),
        ],
    }]))
    ids = [s.id for s in dossier.sources[0].segments]
    assert ids == ["p1", "p3"]
    selected = set(pack_material(dossier)["selected"])
    assert "p2" not in selected
    assert "p1" in selected and "p3" in selected
    notes = [n for n in dossier.ingest_notes if n.get("kind") == "official_short_paragraph"]
    assert notes and notes[0]["filtered"] == 1


def test_answer_files_not_read_by_judgment_path(tmp_path, monkeypatch):
    """d) 研判＋三题＋导出不打开答案文件；app/ 不读这两个文件名。"""
    quote = "能量密度显著高于液态锂离子电池"
    content = f"测评显示固态电池的{quote}，成本仍高。"
    _write_docs(tmp_path, [{
        "doc_id": "doc_1",
        "title": "电池",
        "publish_time": "2024-05-06",
        "content": content,
        "source_credibility": 0.5,
        "content_url": "",
        "paragraphs": [_para("para_1", 0, len(content))],
    }])
    (tmp_path / "evidence_samples.json").write_text("[]", encoding="utf-8")
    (tmp_path / "conclusions.json").write_text("[]", encoding="utf-8")

    real_read = Path.read_text
    real_open = open

    def _guard_read(self, *args, **kwargs):
        if self.name in {"evidence_samples.json", "conclusions.json"}:
            raise RuntimeError(f"forbidden read {self.name}")
        return real_read(self, *args, **kwargs)

    def _guard_open(file, mode="r", *args, **kwargs):
        name = Path(file).name
        mode_s = str(mode)
        reading = "r" in mode_s and "w" not in mode_s and "a" not in mode_s
        if name in {"evidence_samples.json", "conclusions.json"} and reading:
            raise RuntimeError(f"forbidden read {name}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _guard_read)
    monkeypatch.setattr("builtins.open", _guard_open)

    class Stub:
        def chat(self, model, messages, json_mode=False):
            return SimpleNamespace(content=json.dumps({
                "conclusions": [{
                    "statement": "能量密度占优",
                    "evidence": [{
                        "quote": quote,
                        "segment_id": "para_1",
                        "relation": "correlation",
                        "level": "A",
                        "note": "引",
                    }],
                }],
            }, ensure_ascii=False))

    stub = Stub()
    questions = [
        {"question_id": "q1", "question": "固态电池能量密度是否占优？"},
        {"question_id": "q2", "question": "固态电池能量密度是否占优？"},
        {"question_id": "q3", "question": "固态电池能量密度是否占优？"},
    ]
    from app.config import Settings
    settings = Settings()
    settings.query_rewrite_enabled = False
    settings.ocr_enabled = False
    run_official_case(
        tmp_path, questions, tmp_path / "out", settings=settings,
        deps=RunDeps(client=stub, analysts=[
            Analyst("mainstream", "测", stub, "m"),
        ]),
    )
    assert (tmp_path / "out" / "evidence.json").is_file()
    assert (tmp_path / "out" / "conclusions.json").is_file()

    app_root = Path(__file__).resolve().parents[1] / "app"
    blob = "\n".join(p.read_text(encoding="utf-8") for p in app_root.rglob("*.py"))
    assert "evidence_samples" not in blob
    for path in app_root.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            assert "evidence_samples" not in line
            if "conclusions.json" in line:
                assert "write_text" in line or "out_dir" in line


def test_export_keys_match_appendix_a(tmp_path):
    """e) 证据/结论键名与附录 A 一致；未实现字段为空；说明含「未实现」。"""
    content = "能量密度显著高于液态锂离子电池，用于导出键名核对。"
    case = _write_docs(tmp_path, [{
        "doc_id": "doc_1",
        "title": "t",
        "publish_time": "2024-01-02",
        "content": content,
        "source_credibility": 0.5,
        "content_url": "",
        "paragraphs": [_para("para_9", 0, len(content))],
    }])
    dossier = load_official_case(case)
    from app.core.evidence import Conclusion, EvidenceNode
    con = Conclusion.create("能量密度占优", author="m", id="CON-1")
    dossier.conclusions.append(con)
    dossier.add_evidence(EvidenceNode.create(
        "CON-1", "能量密度显著高于液态锂离子电池", ["para_9"], id="EV-1"))
    out = tmp_path / "export"
    paths = export_official(
        [({"question_id": "q1", "question": "能量密度是否占优？"}, dossier)],
        out,
    )
    evidence = json.loads(paths["evidence"].read_text(encoding="utf-8"))
    conclusions = json.loads(paths["conclusions"].read_text(encoding="utf-8"))
    assert evidence
    assert set(evidence[0]) == {
        "doc_id", "para_id", "quote", "fact_des", "argument", "entities",
    }
    assert set(evidence[0]["argument"]) == {
        "时间", "主体", "地点", "内容", "影响", "数值口径",
    }
    assert evidence[0]["fact_des"] is None
    assert evidence[0]["entities"] is None
    assert all(v == "" for v in evidence[0]["argument"].values())
    assert set(conclusions[0]) == {
        "question_id", "question", "conclusion",
        "supporting_facts", "conflicting_facts",
    }
    assert set(conclusions[0]["supporting_facts"][0]) == {"doc_id", "para_id"}
    assert conclusions[0]["conflicting_facts"] == []
    notes = paths["notes"].read_text(encoding="utf-8")
    assert "未实现" in notes
    confidence = json.loads(paths["confidence"].read_text(encoding="utf-8"))
    assert confidence == [] or {
        "信源可信度", "证据数量与一致性", "推理链完整性", "formula", "substitution",
    } <= set(confidence[0])


def _dump(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _gold_fact(fact_id: str, *, conflict: bool = False) -> dict:
    """金标真实键集：没有 para_id。换形只靠同案 evidence_samples。"""
    row = {
        "fact_id": fact_id,
        "doc_id": "doc_001",
        "quote": "引用原文",
        "fact_des": "事实描述",
        "verdict_label": "conflict" if conflict else "support",
    }
    if conflict:
        row["resolution_type"] = "来源优先级"
    return row


def test_gold_fact_id_resolves_before_exact_match(tmp_path):
    """保真：金标 fact 无 para_id，经 evidence_samples 换形后召回非 0。"""
    samples = [
        {"fact_id": "fact_001", "doc_id": "doc_001", "para_id": "doc_001#p2", "quote": "甲"},
        {"fact_id": "fact_002", "doc_id": "doc_001", "para_id": "doc_001#p3", "quote": "乙"},
    ]
    gold_c = [{
        "question_id": "q_001",
        "question": "问",
        "conclusion": "结",
        "supporting_facts": [_gold_fact("fact_001")],
        "conflicting_facts": [_gold_fact("fact_002", conflict=True)],
    }]
    assert "para_id" not in gold_c[0]["supporting_facts"][0]
    assert "para_id" not in gold_c[0]["conflicting_facts"][0]
    submitted_c = [{
        "question_id": "q_001",
        "question": "问",
        "conclusion": "结",
        "supporting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p2"}],
        "conflicting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p3"}],
    }]
    samples_path = _dump(tmp_path / "evidence_samples.json", samples)
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", samples),
        _dump(tmp_path / "conclusions.json", submitted_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=samples_path,
    )
    assert metrics["Recall_sup"] != 0
    assert metrics["Recall_conf"] != 0
    assert metrics["Recall_sup"] == 1.0
    assert metrics["Recall_conf"] == 1.0
    assert metrics["unresolved_fact_ids"] == 0
    report = format_report(metrics)
    lines = report.splitlines()
    assert lines[0] == DISCLAIMER
    assert lines[1] == "未含语义匹配，且双方为空的侧已剔除"
    assert metrics["recall_src_ceiling"] == (
        "本案金标 2 条，Recall_src 上限未核（未提供 --raw-documents）"
    )
    assert "183/184" not in report
    assert "0 条金标 fact_id 无法解析" in report


def test_blank_submission_scores_all_zero(tmp_path):
    """白卷：四份里评分器能看见的证据与结论都空，五项分数必须全是 0。"""
    samples = [
        {"fact_id": "fact_001", "doc_id": "doc_001", "para_id": "doc_001#p2", "quote": "甲"},
    ]
    gold_c = [{
        "question_id": "q_001",
        "question": "问",
        "conclusion": "结",
        "supporting_facts": [_gold_fact("fact_001")],
        "conflicting_facts": [_gold_fact("fact_001", conflict=True)],
    }]
    blank_c = [{
        "question_id": "q_001",
        "question": "问",
        "conclusion": "",
        "supporting_facts": [],
        "conflicting_facts": [],
    }]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", []),
        _dump(tmp_path / "conclusions.json", blank_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
    )
    for key in ("score_2_2_1", "score_2_4_1", "score_2_4_2", "score_2_5_1", "score_2_5_2"):
        assert metrics[key] == 0, key
    assert metrics["Precision_src"] == 0.0
    assert metrics["Precision_sup"] == 0.0
    assert metrics["Precision_conf"] == 0.0

    # 金标与提交都空：不得再把 precision 记成 1 后加权出满分。
    empty_q = [{
        "question_id": "q_001",
        "supporting_facts": [],
        "conflicting_facts": [],
    }]
    both = score_submission(
        _dump(tmp_path / "evidence_both.json", []),
        _dump(tmp_path / "conclusions_both.json", empty_q),
        _dump(tmp_path / "gold_evidence_both.json", []),
        _dump(tmp_path / "gold_conclusions_both.json", empty_q),
        samples_path=_dump(tmp_path / "samples_both.json", []),
    )
    assert both["score_2_4_2"] == 0
    assert both["score_2_5_2"] == 0
    assert both["Precision_sup"] == 0.0
    assert both["empty_both_excluded"] == 2
    assert "2 侧双方为空，未计入" in format_report(both)


def test_recall_src_ceiling_counted_on_this_case(tmp_path):
    """上限按本案语料算：2 条金标里 1 条段落不在语料，打印 1/2，不印跨案合计。"""
    samples = [
        {"fact_id": "fact_001", "doc_id": "doc_001", "para_id": "doc_001#p1", "quote": "甲"},
        {"fact_id": "fact_002", "doc_id": "doc_009", "para_id": "doc_009#p1", "quote": "乙"},
    ]
    raw = [{
        "doc_id": "doc_001",
        "content": "甲段正文足够长",
        "paragraphs": [{"para_id": "doc_001#p1", "char_start": 0, "char_end": 6}],
    }]
    gold_c = [{
        "question_id": "q_001",
        "supporting_facts": [_gold_fact("fact_001")],
        "conflicting_facts": [_gold_fact("fact_002", conflict=True)],
    }]
    submitted_c = [{
        "question_id": "q_001",
        "supporting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p1"}],
        "conflicting_facts": [{"doc_id": "doc_009", "para_id": "doc_009#p1"}],
    }]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", samples),
        _dump(tmp_path / "conclusions.json", submitted_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
        raw_documents_path=_dump(tmp_path / "raw_documents.json", raw),
    )
    assert metrics["recall_src_ceiling"] == "Recall_src 上限 1/2＝50.0%"
    assert "183/184" not in format_report(metrics)


def test_gold_empty_side_with_fake_evidence_scores_zero(tmp_path):
    """金标该侧为空、提交 1 条假证据：召回不计入，2.4.1 与 2.5.1 都是 0。"""
    samples = [
        {"fact_id": "fact_001", "doc_id": "doc_001", "para_id": "doc_001#p2", "quote": "甲"},
    ]
    gold_c = [{
        "question_id": "q_001",
        "question": "问",
        "conclusion": "结",
        "supporting_facts": [],
        "conflicting_facts": [],
    }]
    submitted_c = [{
        "question_id": "q_001",
        "supporting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p9"}],
        "conflicting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p9"}],
    }]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", []),
        _dump(tmp_path / "conclusions.json", submitted_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
    )
    assert metrics["score_2_4_1"] == 0
    assert metrics["score_2_5_1"] == 0
    assert metrics["Recall_sup"] == 0.0
    assert metrics["Recall_conf"] == 0.0
    assert metrics["Precision_sup"] == 0.0
    assert metrics["Precision_conf"] == 0.0
    assert metrics["gold_empty_submitted"] == 2
    assert "2 侧金标为空但提交了证据（官方 2.4 按金标规模加权，此侧不进平均）" in format_report(metrics)


def test_mixed_questions_fake_evidence_cuts_precision(tmp_path):
    """撒垃圾：q2 金标为空，按金标规模加权不进平均，精确率保持 1.0。"""
    samples = [
        {"fact_id": "fact_001", "doc_id": "doc_001", "para_id": "doc_001#p1", "quote": "甲"},
        {"fact_id": "fact_002", "doc_id": "doc_001", "para_id": "doc_001#p2", "quote": "乙"},
    ]
    gold_c = [
        {
            "question_id": "q1",
            "supporting_facts": [_gold_fact("fact_001"), _gold_fact("fact_002")],
            "conflicting_facts": [],
        },
        {
            "question_id": "q2",
            "supporting_facts": [],
            "conflicting_facts": [],
        },
    ]
    submitted_c = [
        {
            "question_id": "q1",
            "supporting_facts": [
                {"doc_id": "doc_001", "para_id": "doc_001#p1"},
                {"doc_id": "doc_001", "para_id": "doc_001#p2"},
            ],
            "conflicting_facts": [],
        },
        {
            "question_id": "q2",
            "supporting_facts": [
                {"doc_id": "doc_001", "para_id": f"doc_001#fake{i}"} for i in range(10)
            ],
            "conflicting_facts": [],
        },
    ]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", samples),
        _dump(tmp_path / "conclusions.json", submitted_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
    )
    assert metrics["Precision_sup"] == 1.0
    assert metrics["score_2_4_2"] == 6
    assert metrics["Recall_sup"] == 1.0
    report = format_report(metrics)
    assert "1 侧金标为空但提交了证据（官方 2.4 按金标规模加权，此侧不进平均）" in report
    assert "题金标为空" not in report


def test_missing_question_enters_gold_denominator(tmp_path):
    """漏交：q2 整题不在提交里，按金标 3 条记 0，精确率与召回都是 0.4。"""
    samples = [
        {"fact_id": f"fact_{i:03d}", "doc_id": "doc_001", "para_id": f"doc_001#p{i}", "quote": "甲"}
        for i in range(1, 6)
    ]
    gold_c = [
        {
            "question_id": "q1",
            "supporting_facts": [_gold_fact("fact_001"), _gold_fact("fact_002")],
            "conflicting_facts": [],
        },
        {
            "question_id": "q2",
            "supporting_facts": [
                _gold_fact("fact_003"), _gold_fact("fact_004"), _gold_fact("fact_005"),
            ],
            "conflicting_facts": [],
        },
    ]
    submitted_c = [{
        "question_id": "q1",
        "supporting_facts": [
            {"doc_id": "doc_001", "para_id": "doc_001#p1"},
            {"doc_id": "doc_001", "para_id": "doc_001#p2"},
        ],
        "conflicting_facts": [],
    }]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", samples),
        _dump(tmp_path / "conclusions.json", submitted_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
    )
    assert abs(metrics["Precision_sup"] - 0.4) < 1e-9
    assert abs(metrics["Recall_sup"] - 0.4) < 1e-9
    assert metrics["score_2_4_2"] == 0
    assert metrics["score_2_4_1"] == 0
    report = format_report(metrics)
    assert "提交缺 1 道题（按金标遍历，这些题记 0 分）" in report
    assert "无支撑证据" not in report


def test_bare_conclusion_zeros_recall_tier(tmp_path):
    """q2 交了结论但支撑为空：召回 10/11 仍过优档，硬档把 score_2_4_1 打成 0。"""
    samples = [
        {"fact_id": f"fact_{i:03d}", "doc_id": "doc_001", "para_id": f"doc_001#p{i}", "quote": "甲"}
        for i in range(1, 12)
    ]
    gold_c = [
        {
            "question_id": "q1",
            "supporting_facts": [_gold_fact(f"fact_{i:03d}") for i in range(1, 11)],
            "conflicting_facts": [],
        },
        {
            "question_id": "q2",
            "supporting_facts": [_gold_fact("fact_011")],
            "conflicting_facts": [],
        },
    ]
    submitted_c = [
        {
            "question_id": "q1",
            "supporting_facts": [
                {"doc_id": "doc_001", "para_id": f"doc_001#p{i}"} for i in range(1, 11)
            ],
            "conflicting_facts": [],
        },
        {
            "question_id": "q2",
            "conclusion": "裸结论",
            "supporting_facts": [],
            "conflicting_facts": [],
        },
    ]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", samples),
        _dump(tmp_path / "conclusions.json", submitted_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
    )
    assert abs(metrics["Recall_sup"] - (10 / 11)) < 1e-4
    assert metrics["score_2_4_1"] == 0
    assert "1 条结论提交了但无支撑证据（官方 2.4.1 硬档）" in format_report(metrics)


def test_supported_conclusions_keep_recall_tier(tmp_path):
    """反例：提交的结论都有支撑时，不出现硬档行，score_2_4_1 仍按召回分档。"""
    samples = [
        {"fact_id": "fact_001", "doc_id": "doc_001", "para_id": "doc_001#p1", "quote": "甲"},
        {"fact_id": "fact_002", "doc_id": "doc_001", "para_id": "doc_001#p2", "quote": "乙"},
    ]
    gold_c = [{
        "question_id": "q1",
        "supporting_facts": [_gold_fact("fact_001"), _gold_fact("fact_002")],
        "conflicting_facts": [],
    }]
    submitted_c = [{
        "question_id": "q1",
        "supporting_facts": [
            {"doc_id": "doc_001", "para_id": "doc_001#p1"},
            {"doc_id": "doc_001", "para_id": "doc_001#p2"},
        ],
        "conflicting_facts": [],
    }]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", samples),
        _dump(tmp_path / "conclusions.json", submitted_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
    )
    assert metrics["Recall_sup"] == 1.0
    assert metrics["score_2_4_1"] == 6
    assert "无支撑证据" not in format_report(metrics)


def test_extra_question_id_is_disclosed(tmp_path):
    """金标没有的 question_id 不进分母，但必须披露，不许静默丢掉。"""
    samples = [
        {"fact_id": "fact_001", "doc_id": "doc_001", "para_id": "doc_001#p1", "quote": "甲"},
    ]
    gold_c = [{
        "question_id": "q1",
        "supporting_facts": [_gold_fact("fact_001")],
        "conflicting_facts": [],
    }]
    submitted_c = [
        {
            "question_id": "q1",
            "supporting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p1"}],
            "conflicting_facts": [],
        },
        {
            "question_id": "q_extra",
            "supporting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p9"}],
            "conflicting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p9"}],
        },
    ]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", samples),
        _dump(tmp_path / "conclusions.json", submitted_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
    )
    assert metrics["extra_questions"] == 1
    assert metrics["Precision_sup"] == 1.0
    assert "提交含 1 道金标里没有的题" in format_report(metrics)


def test_unresolvable_fact_id_scores_zero(tmp_path):
    """反向：fact_id 查不到则该项为 0，进程不崩，并披露条数。"""
    samples = [
        {"fact_id": "fact_001", "doc_id": "doc_001", "para_id": "doc_001#p2", "quote": "甲"},
    ]
    gold_c = [{
        "question_id": "q_001",
        "question": "问",
        "conclusion": "结",
        "supporting_facts": [_gold_fact("fact_missing")],
        "conflicting_facts": [_gold_fact("fact_also_missing", conflict=True)],
    }]
    submitted_c = [{
        "question_id": "q_001",
        "supporting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p2"}],
        "conflicting_facts": [{"doc_id": "doc_001", "para_id": "doc_001#p2"}],
    }]
    metrics = score_submission(
        _dump(tmp_path / "evidence.json", samples),
        _dump(tmp_path / "conclusions.json", submitted_c),
        _dump(tmp_path / "gold_evidence.json", samples),
        _dump(tmp_path / "gold_conclusions.json", gold_c),
        samples_path=_dump(tmp_path / "evidence_samples.json", samples),
    )
    assert metrics["Recall_sup"] == 0.0
    assert metrics["Recall_conf"] == 0.0
    for key in ("score_2_4_1", "score_2_4_2", "score_2_5_1", "score_2_5_2"):
        assert metrics[key] == 0, key
    assert metrics["unresolved_fact_ids"] == 2
    assert "2 条金标 fact_id 无法解析" in format_report(metrics)


def test_unparseable_publish_time_left_blank(tmp_path):
    """g) 空、相对时间、站名不推断日期，披露计数为 3。"""
    docs = []
    for i, raw in enumerate(("", "8天前", "央视网"), start=1):
        text = f"正文段落{i}足够长"
        docs.append({
            "doc_id": f"d{i}",
            "title": f"t{i}",
            "publish_time": raw,
            "content": text,
            "source_credibility": 0.3,
            "content_url": "",
            "paragraphs": [_para(f"p{i}", 0, len(text))],
        })
    dossier = load_official_case(_write_docs(tmp_path, docs))
    for src in dossier.sources:
        assert src.meta["publish_time"] == ""
    blob = json.dumps(dossier.to_dict(), ensure_ascii=False)
    assert "2026-" not in blob and "2024-" not in blob and "2020-" not in blob
    notes = [n for n in dossier.ingest_notes if n.get("kind") == "official_publish_time"]
    assert notes and notes[0]["unparsed"] == 3
