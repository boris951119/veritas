"""添加文件夹：落盘消毒 + 分诊切片 + 办公格式，不另造「整理包」。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.ingest.case_loader import load_case
from app.ingest.import_case import CaseImportError, safe_relpath, write_imported_case
from app.ingest.readers import read_docx
from app.ingest.triage import ROUTE_LABEL
from app.server import create_app


def _docx(text: str) -> bytes:
    buf = io.BytesIO()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
        zf.writestr("[Content_Types].xml", "<Types></Types>")
    return buf.getvalue()


def test_safe_relpath_rejects_traversal():
    assert safe_relpath("../secret.md") is None
    assert safe_relpath("/etc/passwd") is None
    assert safe_relpath("dump/sub/a.md") == "dump/sub/a.md"
    assert safe_relpath("dump/.DS_Store") is None


def test_write_nested_and_skip_junk(tmp_path):
    root = tmp_path / "cases"
    root.mkdir()
    meta = write_imported_case(root, [
        ("现场卷宗/笔记.md", "# 题\n正文入卷。".encode()),
        ("现场卷宗/子/图.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8),
        ("现场卷宗/.DS_Store", b"junk"),
        ("现场卷宗/子/孙/深处.txt", "最底层一段话。".encode()),
    ], question="这家公司是否停工？")
    case_dir = root / meta["case"]
    assert meta["n_written"] == 3
    assert (case_dir / "现场卷宗/笔记.md").is_file()
    d = load_case(case_dir)
    routes = {r["route"] for r in d.triage}
    assert "native" in routes and "image_disclosed" in routes
    assert d.question == "这家公司是否停工？"


def test_docx_ingests_and_old_doc_disclosed(tmp_path):
    case_dir = tmp_path / "c"
    case_dir.mkdir()
    (case_dir / "manifest.yaml").write_text("question: q\n", encoding="utf-8")
    (case_dir / "说明.docx").write_bytes(_docx("合同金额1280万元。"))
    (case_dir / "老文件.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 20)
    d = load_case(case_dir)
    routes = {r["route"] for r in d.triage}
    assert "native" in routes
    assert "unsupported_format" in routes
    assert "1280" in read_docx(case_dir / "说明.docx")[1]
    assert all(r["route"] in ROUTE_LABEL for r in d.triage)


def test_history_dir_not_reingested(tmp_path):
    case_dir = tmp_path / "c"
    case_dir.mkdir()
    (case_dir / "manifest.yaml").write_text("question: q\n", encoding="utf-8")
    (case_dir / "a.md").write_text("正文。", encoding="utf-8")
    hist = case_dir / "history" / "20260101T000000"
    hist.mkdir(parents=True)
    (hist / "report.json").write_text('{"question":"不该入卷"}', encoding="utf-8")
    d = load_case(case_dir)
    assert len(d.sources) == 1
    assert all("history" not in r["file"] for r in d.triage)


def test_import_api_returns_triage(tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    client = TestClient(create_app(cases_root=cases))
    r = client.post(
        "/api/case/import",
        data={"question": "用户亲手问的吗？"},
        files=[
            ("files", ("dump/a.md", "# x\n可入卷的一段。".encode(), "text/markdown")),
            ("files", ("dump/pic.png", b"\x89PNG\r\n\x1a\nxxxx", "image/png")),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_written"] == 2
    assert body["n_sources"] == 1
    assert any(t["route"] == "image_disclosed" for t in body["triage"])
    preview = client.get("/api/ingest", params={"case": body["case"]})
    assert preview.status_code == 200
    assert preview.json()["n_sources"] == 1


def test_traversal_filename_skipped(tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    client = TestClient(create_app(cases_root=cases))
    r = client.post(
        "/api/case/import",
        files=[("files", ("../escape.md", b"nope", "text/plain"))],
    )
    assert r.status_code == 422


def test_write_rejects_empty(tmp_path):
    try:
        write_imported_case(tmp_path / "cases", [])
        assert False
    except CaseImportError:
        pass


def test_rename_case_updates_title(tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    client = TestClient(create_app(cases_root=cases))
    r = client.post(
        "/api/case/import",
        data={"question": "议题"},
        files=[("files", ("a.md", "# t\n正文。".encode(), "text/markdown"))],
    )
    assert r.status_code == 200
    name = r.json()["case"]
    ren = client.post("/api/case/rename", json={"case": name, "title": "现场卷宗甲"})
    assert ren.status_code == 200 and ren.json()["title"] == "现场卷宗甲"
    listed = client.get("/api/cases").json()["cases"]
    hit = next(c for c in listed if c["name"] == name)
    assert hit["title"] == "现场卷宗甲"


def test_remove_and_append_imported_files(tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    client = TestClient(create_app(cases_root=cases))
    r = client.post(
        "/api/case/import",
        data={"question": "议题"},
        files=[
            ("files", ("dump/keep.md", "# k\n留下这段。".encode(), "text/markdown")),
            ("files", ("dump/wrong.md", "# w\n导错了。".encode(), "text/markdown")),
        ],
    )
    assert r.status_code == 200
    name = r.json()["case"]
    assert r.json()["n_sources"] == 2
    gone = client.post("/api/case/files/remove",
                       json={"case": name, "files": ["dump/wrong.md"]})
    assert gone.status_code == 200, gone.text
    body = gone.json()
    assert body["n_removed"] == 1
    assert body["n_sources"] == 1
    assert not (cases / name / "dump/wrong.md").exists()
    assert (cases / name / "dump/keep.md").is_file()
    # 追加到本案，不另开 user-*
    add = client.post(
        "/api/case/import",
        data={"question": "议题", "case": name},
        files=[("files", ("dump/extra.md", "# e\n补一份。".encode(),
                          "text/markdown"))],
    )
    assert add.status_code == 200
    assert add.json()["case"] == name
    assert add.json()["appended"] is True
    assert add.json()["n_sources"] == 2
    assert (cases / name / "dump/extra.md").is_file()


def test_remove_refuses_demo_case(tmp_path):
    cases = tmp_path / "cases"
    demo = cases / "demo"
    demo.mkdir(parents=True)
    (demo / "manifest.yaml").write_text("question: q\n", encoding="utf-8")
    (demo / "a.md").write_text("正文。", encoding="utf-8")
    client = TestClient(create_app(cases_root=cases))
    r = client.post("/api/case/files/remove",
                    json={"case": "demo", "files": ["a.md"]})
    assert r.status_code == 422
    assert (demo / "a.md").is_file()
