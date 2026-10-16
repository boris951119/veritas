"""目录遍历封顶披露：超 max_files / max_depth 必须进 ingest_notes+triage。

对照 HANDOFF C-1：静默丢材料 → 披露「取前 N、另有 M」；未触发不得假披露。
"""

from __future__ import annotations

from pathlib import Path

from app.ingest.case_loader import (
    CollectResult,
    _collect_files,
    count_case_files,
    load_case,
)


def _case(tmp_path: Path, name: str = "cap") -> Path:
    case_dir = tmp_path / "cases" / name
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text(
        "question: 封顶披露回归？\n", encoding="utf-8")
    return case_dir


def test_max_files_triggers_dir_truncated_disclosure(tmp_path):
    """超 500 文件：取前 500，另有 1 未入卷；count_case_files 与 taken 对齐。"""
    case_dir = _case(tmp_path)
    for i in range(501):
        (case_dir / f"f{i:04d}.md").write_text(f"材料{i}。", encoding="utf-8")
    d = load_case(case_dir)
    notes = [n for n in d.ingest_notes if n.get("kind") == "dir_truncated"]
    assert len(notes) == 1
    note = notes[0]
    assert note["taken"] == 500
    assert note["skipped"] == 1
    assert note["files_capped"] is True
    assert "按文件名排序取前 500" in note["detail"]
    assert "另有 1 个文件" in note["detail"]
    assert any(t["route"] == "dir_truncated" for t in d.triage)
    assert count_case_files(case_dir) == note["taken"] == 500
    assert len(d.sources) == 500


def test_max_depth_triggers_dir_truncated_disclosure(tmp_path):
    """深于 3 层的文件未入卷，必须披露。"""
    case_dir = _case(tmp_path)
    (case_dir / "根.md").write_text("根层材料。", encoding="utf-8")
    deep = case_dir / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "深.md").write_text("第 4 层材料。", encoding="utf-8")
    d = load_case(case_dir)
    notes = [n for n in d.ingest_notes if n.get("kind") == "dir_truncated"]
    assert len(notes) == 1
    note = notes[0]
    assert note["depth_capped"] is True
    assert note["skipped"] >= 1
    assert "按文件名排序取前" in note["detail"]
    assert "另有" in note["detail"] and "未入卷" in note["detail"]
    assert any(t["route"] == "dir_truncated" for t in d.triage)
    assert count_case_files(case_dir) == note["taken"]
    titles = {s.title for s in d.sources}
    assert "根" in titles
    assert "深" not in titles


def test_no_cap_no_dir_truncated_disclosure(tmp_path):
    """未触封顶时不得多写 dir_truncated（防空转假披露）。"""
    case_dir = _case(tmp_path)
    (case_dir / "正常.md").write_text("正常材料。", encoding="utf-8")
    sub = case_dir / "一层"
    sub.mkdir()
    (sub / "子.md").write_text("子目录材料。", encoding="utf-8")
    d = load_case(case_dir)
    assert not any(n.get("kind") == "dir_truncated" for n in d.ingest_notes)
    assert not any(t.get("route") == "dir_truncated" for t in d.triage)
    assert len(d.sources) == 2
    collected = _collect_files(case_dir)
    assert isinstance(collected, CollectResult)
    assert not collected.truncated
    assert collected.skipped == 0
