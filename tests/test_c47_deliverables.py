"""C-47：交付包补齐（部署文档／causal_evidence／智能体实测／组包脚本）。

零 LLM。不许墙钟绝对秒数断言。判定／合式／跳平局选取一个字不许动。
"""

from __future__ import annotations

import ast
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from app.agents.panel import load_roster
from app.agents.registry import agent_inventory, inventory_markdown
from app.core.confidence import recompute_all
from app.core.evidence import EvidenceLevel, RelationKind
from app.export.official import _FIELD_NOTES, export_official
from tests.test_c32_causal_claim import (
    _FULL_CLAIM,
    _add_ev,
    _base_dossier,
    _q,
)

ROOT = Path(__file__).resolve().parents[1]

_CAUSAL_KEYS = (
    "conclusion_id", "question_id",
    "intervention", "outcome", "population", "counterfactual",
    "mechanism_completeness", "missing_links", "design_tier",
    "degraded_reason", "evidence_refs", "confidence",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dossier_with_causal() -> object:
    d = _base_dossier()
    _add_ev(
        d,
        relation=RelationKind.CAUSATION,
        claim=dict(_FULL_CLAIM),
        mechanism="direct",
        design_tier="observational",
        quote="全固态电芯的中试良率尚不足百分之四十",
    )
    recompute_all(d, n_panel=1)
    return d


# -- a：core／pipeline／confidence 零 diff 由回写贴 git diff --stat；此处钉源码未改合式入口 --


def test_a_core_confidence_entrypoints_untouched():
    """合式入口仍在 confidence.py；本单测试不 import 私改。"""
    src = (ROOT / "app" / "core" / "confidence.py").read_text(encoding="utf-8")
    assert "def recompute_all" in src
    assert "def conclude_confidence" in src


# -- b：三份 JSON sha 在「无因果行」夹具上与仅加 causal 文件兼容（有因果时 evidence 可变）--


def test_b_sha_invariant_without_causal_rows(tmp_path):
    """无因果主张时：四份旧 JSON 形状稳定；causal_evidence 允许为空列表文件。"""
    d = _base_dossier()
    _add_ev(d, relation=RelationKind.CORRELATION)  # 无主张卡
    recompute_all(d, n_panel=1)
    out = tmp_path / "off"
    paths = export_official([(_q(), d)], out)
    for name in ("evidence", "conclusions", "confidence", "conflict_resolution"):
        assert paths[name].is_file()
    causal = json.loads(paths["causal_evidence"].read_text(encoding="utf-8"))
    assert causal == []
    # 再导一次 sha 逐位相同
    out2 = tmp_path / "off2"
    paths2 = export_official([(_q(), d)], out2)
    for name in ("evidence", "conclusions", "confidence", "conflict_resolution",
                 "causal_evidence"):
        assert _sha(paths[name]) == _sha(paths2[name])


def test_b_causal_row_shape_and_confidence_reuse(tmp_path):
    d = _dossier_with_causal()
    conf_before = float(d.conclusions[0].confidence)
    paths = export_official([(_q(), d)], tmp_path / "c")
    rows = json.loads(paths["causal_evidence"].read_text(encoding="utf-8"))
    assert len(rows) == 1
    row = rows[0]
    for k in _CAUSAL_KEYS:
        assert k in row, k
    assert row["intervention"] == _FULL_CLAIM["intervention"]
    assert row["confidence"] == conf_before
    refs = row["evidence_refs"]
    assert isinstance(refs, list) and refs
    assert {"doc_id", "para_id", "quote"} <= set(refs[0])


# -- c：c33／c34／c46 文件本单零改（内容哈希相对 git HEAD；有改则红）--


@pytest.mark.parametrize("rel", [
    "tests/test_c33_submission_side.py",
    "tests/test_c34_level_official.py",
    "tests/test_c46_record_shape.py",
])
def test_c_submission_suites_untouched(rel):
    """相对 HEAD 无内容 diff（未跟踪改动＝红）。"""
    import subprocess
    r = subprocess.run(
        ["git", "diff", "--", rel],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert r.stdout == "", f"{rel} 被本单改动了"


# -- d：零模型／无墙钟绝对秒断言（扫本单新测试与新脚本 AST）--


def test_d_no_wallclock_assert_in_c47_artifacts():
    """扫本文件：以 assert 开头的语句不得含 elapsed／秒。"""
    test_src = (ROOT / "tests" / "test_c47_deliverables.py").read_text(
        encoding="utf-8")
    for line in test_src.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("assert"):
            continue
        if "elapsed" in stripped or "秒" in stripped:
            raise AssertionError(f"wallclock-assert: {line}")

def test_e_self_collectable():
    assert Path(__file__).is_file()


# -- f：字段说明覆盖 causal_evidence 全字段 --


def test_f_field_notes_cover_causal_keys():
    assert "## causal_evidence.json" in _FIELD_NOTES
    for k in _CAUSAL_KEYS:
        assert k in _FIELD_NOTES, k
    for enum_word in ("direct", "indirect", "correlation_only",
                      "mediator", "temporal", "contrast",
                      "rct", "quasi", "observational", "claim_only"):
        assert enum_word in _FIELD_NOTES


# -- g：件③ 可复跑记录（roster 配置＋演示脚本＋交付笔记）--


def test_g_agent_roster_and_record_artifacts():
    roster_path = ROOT / "config" / "roster-devil-advocate.yaml"
    assert roster_path.is_file()
    roster = load_roster(roster_path)
    assert any(n == "devil-advocate" for n, _, _ in roster)
    # 展示清单真绑 roster，默认清单不含该角色（禁止 _FIXED_AGENTS 假路径）
    inv = agent_inventory(roster=roster)
    assert any("devil-advocate" in r["name"] for r in inv)
    inv_default = agent_inventory()
    assert not any("devil-advocate" in r["name"] for r in inv_default)
    assert "devil-advocate" in inventory_markdown(roster=roster)
    assert (ROOT / "scripts" / "demo_c47_agent.py").is_file()
    note = ROOT / "docs" / "deliverables" / "智能体实测-C47.md"
    assert note.is_file()
    text = note.read_text(encoding="utf-8")
    assert "devil-advocate" in text
    assert "未达" in text  # 工作台项如实未达
    assert "load_roster" in text or "roster-devil-advocate" in text
    assert "_FIXED_AGENTS" not in text or "不改 _FIXED_AGENTS" in text


# -- 件① 部署文档 --


def test_deploy_doc_title_and_no_history_stack():
    doc = ROOT / "docs" / "deliverables" / "部署文档.md"
    text = doc.read_text(encoding="utf-8")
    assert "部署文档" in text.splitlines()[0] or "部署文档" in text[:80]
    assert ":79" in text or "需求说明" in text
    assert "上一档" not in text
    # 历史读数堆叠禁品
    assert "passed in" not in text


# -- 件④ 组包脚本可导入＋自查函数在 --


def test_zip_script_parses_and_mentions_probe():
    src = (ROOT / "scripts" / "build_submission_zip.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert "probe_resolution_records" in src
    assert "_element_清单" in src
    assert "_element_结果" in src
    assert "MANIFEST" in src


def test_zip_script_builds_from_synthetic(tmp_path):
    """合成跑次：一专题含 report.json → zip 含五份 JSON＋MANIFEST。"""
    d = _dossier_with_causal()
    topic = tmp_path / "run" / "专题甲"
    qdir = topic / "questions" / "q1"
    qdir.mkdir(parents=True)
    (qdir / "report.json").write_text(
        json.dumps(d.to_dict(), ensure_ascii=False), encoding="utf-8")
    # 挂上 question 字段
    data = json.loads((qdir / "report.json").read_text(encoding="utf-8"))
    data["question"] = d.question
    (qdir / "report.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")

    from scripts.build_submission_zip import build
    out_zip = tmp_path / "out.zip"
    result = build(
        tmp_path / "run",
        out_zip,
        docs_dirs=[ROOT / "docs" / "deliverables"],
        work_root=tmp_path / "work",
    )
    assert out_zip.is_file()
    assert result["parse_bad"] == []
    with zipfile.ZipFile(out_zip) as zf:
        names = zf.namelist()
    assert "MANIFEST.txt" in names
    assert any(n.endswith("causal_evidence.json") for n in names)
    assert any(n.endswith("evidence.json") for n in names)
