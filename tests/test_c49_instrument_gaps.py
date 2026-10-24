"""C-49：三件仪器可信度缺口——zip 反向腿／MANIFEST 活读数／empty_statements。

只动量尺面＋测试面；app/core／export／agents 零字节。
零模型；不许墙钟绝对秒数断言。
这三件补的是仪器可信度，不改研判质量、不承诺分数。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.confidence import recompute_all
from app.core.evidence import RelationKind
from tests.test_c32_causal_claim import _FULL_CLAIM, _add_ev, _base_dossier

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)%")


def _synth_run(tmp_path: Path, name: str = "run") -> Path:
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
    run = tmp_path / name
    topic = run / "专题甲"
    qdir = topic / "questions" / "q1"
    qdir.mkdir(parents=True)
    data = d.to_dict()
    data["question"] = d.question
    (qdir / "report.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    return run


def _docs() -> list[Path]:
    return [ROOT / "docs" / "deliverables"]


def _poison_staging(root: Path) -> None:
    """往 staging 塞 human 链事件＋非空 relevance_override。"""
    poison = root / "_c49_poison_chain.json"
    poison.write_text(
        json.dumps(
            {
                "events": [{"agent": "human", "kind": "chain"}],
                "relevance_override": "manual-label",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 件① zip 反向腿：forbidden 非空＋main exit=1；_scan_forbidden→[] 必须红
# ---------------------------------------------------------------------------


def test_c49_p1_forbidden_len_and_main_exit_code(tmp_path, monkeypatch):
    """哪个数必须变：len(forbidden) 0⇒≥1；main 退出码 0⇒1。"""
    import scripts.build_submission_zip as zmod

    run = _synth_run(tmp_path)
    out_zip = tmp_path / "ok.zip"
    work = tmp_path / "work_ok"
    clean = zmod.build(run, out_zip, _docs(), work, with_causal=False)
    assert clean["forbidden"] == []
    assert len(clean["forbidden"]) == 0

    real_scan = zmod._scan_forbidden

    def scan_after_poison(root: Path):
        _poison_staging(root)
        return real_scan(root)

    monkeypatch.setattr(zmod, "_scan_forbidden", scan_after_poison)
    poisoned_zip = tmp_path / "poison.zip"
    work_p = tmp_path / "work_poison"
    result = zmod.build(run, poisoned_zip, _docs(), work_p, with_causal=False)
    # 数：0 ⇒ ≥1
    assert len(result["forbidden"]) >= 1, result["forbidden"]
    assert result["forbidden"]  # 非空

    # main() 退出码：经 CLI 真跑，毒化 _scan_forbidden
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_submission_zip.py",
            "--run-dir",
            str(run),
            "--docs-dir",
            str(_docs()[0]),
            "--out",
            str(tmp_path / "main_poison.zip"),
            "--work-dir",
            str(tmp_path / "work_main"),
        ],
    )
    code = zmod.main()
    assert code == 1, code


def test_c49_p1_scan_stub_empty_must_red(tmp_path, monkeypatch):
    """刀：把 _scan_forbidden 换成恒返回 [] ⇒ len(forbidden)≥1 断言必须红。"""
    import scripts.build_submission_zip as zmod

    run = _synth_run(tmp_path)
    real_scan = zmod._scan_forbidden

    def scan_after_poison(root: Path):
        _poison_staging(root)
        return real_scan(root)

    # 先证明毒化路径下 forbidden 非空（对照）
    monkeypatch.setattr(zmod, "_scan_forbidden", scan_after_poison)
    r_ok = zmod.build(
        run,
        tmp_path / "ctrl.zip",
        _docs(),
        tmp_path / "work_ctrl",
        with_causal=False,
    )
    assert len(r_ok["forbidden"]) >= 1

    # 刀：恒返回 []
    monkeypatch.setattr(zmod, "_scan_forbidden", lambda root: [])
    r_stub = zmod.build(
        run,
        tmp_path / "stub.zip",
        _docs(),
        tmp_path / "work_stub",
        with_causal=False,
    )
    with pytest.raises(AssertionError):
        assert len(r_stub["forbidden"]) >= 1


# ---------------------------------------------------------------------------
# 件② MANIFEST 活读数：当场填探针数字；改数字必须红；解析失败不许回落
# ---------------------------------------------------------------------------


def test_c49_p2_manifest_filled_from_live_probe(tmp_path):
    """MANIFEST／返回值原因行＝当场 format_causal_omit_status(run)；含百分数与跑次名。"""
    from scripts.build_submission_zip import (
        assert_causal_omit_status_matches_live,
        build,
        format_causal_omit_status,
    )

    run = _synth_run(tmp_path, name="c49-live-run")
    live = format_causal_omit_status(run)
    assert "四要素非空率" in live
    assert "跑次=c49-live-run" in live
    assert "降级" in live
    assert _PCT_RE.search(live), live
    # 逐要素名在场
    for k in ("intervention", "outcome", "population", "counterfactual"):
        assert f"{k}=" in live

    result = build(
        run,
        tmp_path / "live.zip",
        _docs(),
        tmp_path / "work_live",
        with_causal=False,
    )
    assert result["causal_status"] == live
    man = (tmp_path / "work_live" / "staging" / "MANIFEST.txt").read_text(
        encoding="utf-8"
    )
    assert live in man
    assert_causal_omit_status_matches_live(result["causal_status"], run)


def test_c49_p2_mutated_digits_must_red(tmp_path):
    """刀：同一夹具把填进去的数字改掉 ⇒ assert_causal_omit_status_matches_live 必须红。"""
    from scripts.build_submission_zip import (
        assert_causal_omit_status_matches_live,
        format_causal_omit_status,
    )

    run = _synth_run(tmp_path)
    live = format_causal_omit_status(run)
    # 改第一个百分数里的一个数字
    m = _PCT_RE.search(live)
    assert m, live
    old = m.group(1)
    # 翻一个字符
    flipped = ("9" if not old.startswith("9") else "8") + old[1:]
    mutated = live[: m.start(1)] + flipped + live[m.end(1) :]
    assert mutated != live
    with pytest.raises(AssertionError):
        assert_causal_omit_status_matches_live(mutated, run)


def test_c49_p2_no_fallback_when_unparseable(tmp_path):
    """解析不出数字 ⇒ format_causal_omit_status 直接失败，不许回落默认串。"""
    from scripts.build_submission_zip import format_causal_omit_status

    empty_run = tmp_path / "empty-run"
    empty_run.mkdir()
    # 无 report.json ⇒ n_ev=0
    with pytest.raises(ValueError, match="解析不出|证据条数=0|百分数"):
        format_causal_omit_status(empty_run)


# ---------------------------------------------------------------------------
# 件③ empty_statements：present 只认真在场；退化格；不改 test_c46 逐字格
# ---------------------------------------------------------------------------


def test_c49_p3_empty_statements_not_present():
    """有键、两侧只有 id／statement 全空 ⇒ empty_statements，不是 present。"""
    from scripts.probe_resolution_records import _element_清单, _element_结果

    rec = {
        "冲突清单": [
            {"conclusion_id": "CON-A", "statement": ""},
            {"conclusion_id": "CON-B", "statement": ""},
        ],
        "结果": {"outcome": "", "winner_id": "CON-A", "tie": False},
    }
    q, qn = _element_清单(rec)
    r, rn = _element_结果(rec)
    assert q == "empty_statements", (q, qn)
    assert r == "empty_statements", (r, rn)


def test_c49_p3_present_requires_statement_text():
    """说法文本真在场才 present。"""
    from scripts.probe_resolution_records import _element_清单, _element_结果

    rec = {
        "冲突清单": [
            {"conclusion_id": "CON-A", "statement": "甲说法"},
            {"conclusion_id": "CON-B", "statement": "乙说法"},
        ],
        "结果": {"outcome": "甲胜", "winner_id": "CON-A", "tie": False},
    }
    assert _element_清单(rec)[0] == "present"
    assert _element_结果(rec)[0] == "present"


def test_c49_p3_degraded_submission_face_reads_empty_statements(tmp_path):
    """退化形态守护格：造"有键无文本"提交面 ⇒ 探针读出 empty_statements 而非 present。"""
    from scripts.probe_resolution_records import _element_清单, _element_结果

    face = tmp_path / "conflict_resolution.json"
    payload = {
        "records": [
            {
                "conflict_id": "C-deg",
                "question_id": "q1",
                "冲突清单": [
                    {"conclusion_id": "A", "statement": "", "source_ids": [], "para_ids": []},
                    {"conclusion_id": "B", "statement": "", "source_ids": [], "para_ids": []},
                ],
                "结果": {"outcome": "", "winner_id": "A", "tie": False},
                "resolution_type": "语义可信度",
                "rationale": "x",
                "basis": {"type_applies": True},
                "重启条件": "若新证据出现",
            }
        ]
    }
    face.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    rec = json.loads(face.read_text(encoding="utf-8"))["records"][0]
    assert _element_清单(rec)[0] == "empty_statements"
    assert _element_结果(rec)[0] == "empty_statements"
    assert _element_清单(rec)[0] != "present"
    assert _element_结果(rec)[0] != "present"


def test_c49_p3_zip_selfcheck_label_aligned():
    """自查② 打印标签与 present 口径对齐：不再把键在场叫"非空率"。"""
    src = (ROOT / "scripts" / "build_submission_zip.py").read_text(encoding="utf-8")
    assert "文本在场率" in src
    assert "empty_statements 不算在场" in src
    assert "清单_present=" in src
    assert "结果_present=" in src
    # 旧误导标签从自查② 标题消失（注释里的历史「非空率」字样若仅在因果原因行则允许）
    # 自查② 标题行不得再写「非空率」
    for line in src.splitlines():
        if "自查②" in line and "====" in line:
            assert "非空率" not in line, line


def test_c49_p3_c46_record_shape_untouched():
    """tests/test_c46_record_shape.py 逐字格不许动（相对 HEAD 无 diff）。"""
    r = subprocess.run(
        ["git", "diff", "--", "tests/test_c46_record_shape.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert r.stdout == "", "test_c46_record_shape.py 被本单改动了"


def test_c49_a_production_surfaces_untouched():
    """判据 a：app/core／export/official／agents 零 diff。"""
    r = subprocess.run(
        [
            "git",
            "diff",
            "--stat",
            "--",
            "app/core/",
            "app/export/official.py",
            "app/agents/",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert r.stdout.strip() == "", r.stdout
