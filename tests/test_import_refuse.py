"""C-6：导入侧深度拒收（不截文件名）＋可摄取计数口径对齐。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.ingest.case_loader import load_case
from app.ingest.import_case import (
    append_imported_files,
    resolve_case_file,
    safe_relpath,
    write_imported_case,
)
from app.server import create_app


def test_deep_path_two_files_refused_no_orphan_on_disk(tmp_path):
    """a) 5 段两份 → n_written=0、n_refused=2、reason=deep_path；无无扩展名残留。"""
    root = tmp_path / "cases"
    root.mkdir()
    meta = write_imported_case(root, [
        ("top/a/b/c/一月.txt", "一月回款20万".encode()),
        ("top/a/b/c/二月.txt", "二月回款25万".encode()),
    ])
    assert meta["n_written"] == 0
    assert meta["n_refused"] == 2
    assert all(r["reason"] == "deep_path" for r in meta["refused"])
    case_dir = root / meta["case"]
    assert case_dir.is_dir()
    # 专防覆盖回归：不得出现无扩展名的 top/a/b/c 文件
    assert not (case_dir / "top/a/b/c").exists()
    assert not (case_dir / "top/a/b/c").is_file()
    assert list(case_dir.rglob("*.txt")) == []
    d = load_case(case_dir)
    notes = [n for n in d.ingest_notes if n.get("kind") == "import_refused"]
    assert len(notes) == 2
    assert any(t["route"] == "import_refused" for t in d.triage)


def test_four_segment_path_accepted(tmp_path):
    """b) 4 段 top/a/b/c.md → 正常入卷、零拒收（与遍历侧边界对齐）。"""
    root = tmp_path / "cases"
    root.mkdir()
    meta = write_imported_case(root, [
        ("top/a/b/c.md", "客户B回款率40%。".encode()),
    ])
    assert meta["n_written"] == 1
    assert meta["n_refused"] == 0
    assert safe_relpath("top/a/b/c.md") == "top/a/b/c.md"
    assert (root / meta["case"] / "top/a/b/c.md").is_file()


def test_hidden_path_refused_with_original_name(tmp_path):
    """c) .DS_Store、.git/config → reason=hidden_path，披露出原路径。"""
    root = tmp_path / "cases"
    root.mkdir()
    meta = write_imported_case(root, [
        (".DS_Store", b"\x00\x00"),
        (".git/config", b"[core]\n"),
        ("ok.md", "正文入卷。".encode()),
    ])
    assert meta["n_written"] == 1
    reasons = {r["name"]: r["reason"] for r in meta["refused"]}
    assert reasons[".DS_Store"] == "hidden_path"
    assert reasons[".git/config"] == "hidden_path"
    d = load_case(root / meta["case"])
    details = " ".join(n["detail"] for n in d.ingest_notes
                       if n.get("kind") == "import_refused")
    assert ".DS_Store" in details and ".git/config" in details


def test_oversize_refused(tmp_path):
    """d) 单文件 >20MB → reason=oversize。"""
    root = tmp_path / "cases"
    root.mkdir()
    big = b"x" * (20 * 1024 * 1024 + 1)
    meta = write_imported_case(root, [
        ("big.md", big),
        ("small.md", "小文件。".encode()),
    ])
    assert meta["n_written"] == 1
    assert meta["n_refused"] == 1
    assert meta["refused"][0]["reason"] == "oversize"
    assert "big.md" in meta["refused"][0]["name"]


def test_hidden_dir_count_uses_readers_suffix(tmp_path):
    """e) .materials 里 png 不计可摄取；.md 仍计 3。"""
    case_dir = tmp_path / "cases" / "h"
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text("question: q\n", encoding="utf-8")
    (case_dir / "正常.md").write_text("正文。", encoding="utf-8")

    png_dir = case_dir / ".materials_png"
    png_dir.mkdir()
    for i in range(3):
        (png_dir / f"p{i}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    d1 = load_case(case_dir)
    notes1 = [n for n in d1.ingest_notes if n.get("kind") == "hidden_dir_skipped"
              and ".materials_png" in (n.get("file") or "")]
    assert len(notes1) == 1
    assert notes1[0]["n_files"] == 0
    assert notes1[0].get("n_unsupported", 0) == 0
    assert notes1[0].get("n_images", 0) == 3
    assert "另有 3 个图片文件（未 OCR）" in notes1[0]["detail"]
    assert "含 0 个可摄取文件未入卷" not in notes1[0]["detail"]

    md_dir = case_dir / ".materials_md"
    md_dir.mkdir()
    for i in range(3):
        (md_dir / f"m{i}.md").write_text("材料。", encoding="utf-8")
    d2 = load_case(case_dir)
    notes2 = [n for n in d2.ingest_notes if n.get("kind") == "hidden_dir_skipped"
              and ".materials_md" in (n.get("file") or "")]
    assert len(notes2) == 1
    assert notes2[0]["n_files"] == 3

    # 老办公格式：可摄取 0，另有 N 个格式暂不支持
    doc_dir = case_dir / ".materials_doc"
    doc_dir.mkdir()
    for i in range(2):
        (doc_dir / f"old{i}.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 8)
    d3 = load_case(case_dir)
    notes3 = [n for n in d3.ingest_notes if n.get("kind") == "hidden_dir_skipped"
              and ".materials_doc" in (n.get("file") or "")]
    assert len(notes3) == 1
    assert notes3[0]["n_files"] == 0
    assert notes3[0]["n_unsupported"] == 2
    assert "另有 2 个格式暂不支持" in notes3[0]["detail"]
    assert "含 0 个可摄取文件未入卷" not in notes3[0]["detail"]


def test_refused_deep_path_not_resolvable_for_delete(tmp_path):
    """f) 被拒深层路径不得被 resolve_case_file 认可。"""
    root = tmp_path / "cases"
    root.mkdir()
    deep = "top/a/b/c/一月.txt"
    meta = write_imported_case(root, [(deep, "一月".encode())])
    assert meta["n_refused"] == 1
    case_dir = root / meta["case"]
    assert resolve_case_file(case_dir, deep) is None
    assert safe_relpath(deep) is None
    # 工作台删除清单同源：resolve 失败 → remove 记入 refused
    from app.ingest.import_case import remove_case_files
    out = remove_case_files(case_dir, [deep])
    assert out["n_removed"] == 0
    assert deep in out["refused"] or any(deep in x for x in out["refused"])


def test_import_api_refused_in_body_and_notes(tmp_path):
    """端到端：添加文件夹链路返回 refused，ingest_notes 可读。"""
    cases = tmp_path / "cases"
    cases.mkdir()
    client = TestClient(create_app(cases_root=cases))
    r = client.post(
        "/api/case/import",
        data={"question": "深层目录？"},
        files=[
            ("files", ("top/a/b/c/一月.txt", "一月回款20万".encode(),
                       "text/plain")),
            ("files", ("top/a/b/c/二月.txt", "二月回款25万".encode(),
                       "text/plain")),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_written"] == 0
    assert body["n_refused"] == 2
    assert all(x["reason"] == "deep_path" for x in body["refused"])
    assert any(t["route"] == "import_refused" for t in body["triage"])
    case_dir = cases / body["case"]
    assert not (case_dir / "top/a/b/c").exists()
