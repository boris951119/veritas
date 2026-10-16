"""C-5：工具名单外隐藏目录不入卷但必须披露；工具目录静默。"""

from __future__ import annotations

from pathlib import Path

from app.ingest.case_loader import load_case


def _case(tmp_path: Path, name: str = "hidden") -> Path:
    case_dir = tmp_path / "cases" / name
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text(
        "question: 隐藏目录披露？\n", encoding="utf-8")
    (case_dir / "正常.md").write_text("客户B回款率40%。", encoding="utf-8")
    return case_dir


def _hidden_notes(d):
    return [n for n in d.ingest_notes if n.get("kind") == "hidden_dir_skipped"]


def test_materials_hidden_dir_disclosed_without_filenames(tmp_path):
    """a) .materials/ 放 3 个 txt → 一条披露，含目录名、不含文件名。"""
    case_dir = _case(tmp_path)
    hid = case_dir / ".materials"
    hid.mkdir()
    for name in ("a.txt", "b.txt", "secret_payload.txt"):
        (hid / name).write_text("材料正文。", encoding="utf-8")
    d = load_case(case_dir)
    notes = _hidden_notes(d)
    assert len(notes) == 1
    note = notes[0]
    assert ".materials" in note["detail"]
    assert note["n_files"] == 3
    assert "a.txt" not in note["detail"]
    assert "b.txt" not in note["detail"]
    assert "secret_payload" not in note["detail"]
    assert any(t["route"] == "hidden_dir_skipped" for t in d.triage)
    # 仍不入卷
    assert all(".materials" not in (s.meta.get("file") or "") for s in d.sources)
    assert len(d.sources) == 1


def test_git_hidden_dir_no_disclosure(tmp_path):
    """b) .git/ 放大量文件 → 不出披露。"""
    case_dir = _case(tmp_path)
    git = case_dir / ".git"
    git.mkdir()
    for i in range(20):
        (git / f"obj{i}").write_bytes(b"\x00" * 8)
    d = load_case(case_dir)
    assert _hidden_notes(d) == []
    assert not any(t.get("route") == "hidden_dir_skipped" for t in d.triage)


def test_fetched_cache_no_false_alarm(tmp_path):
    """c) .fetched/index.json 存在 → 不出披露（假警报回归保护）。"""
    case_dir = _case(tmp_path)
    fetched = case_dir / ".fetched"
    fetched.mkdir()
    (fetched / "index.json").write_text("{}", encoding="utf-8")
    d = load_case(case_dir)
    assert _hidden_notes(d) == []


def test_no_hidden_dir_no_disclosure(tmp_path):
    """d) 无隐藏目录 → 零披露。"""
    case_dir = _case(tmp_path)
    d = load_case(case_dir)
    assert _hidden_notes(d) == []
    assert not any(t.get("route") == "hidden_dir_skipped" for t in d.triage)
