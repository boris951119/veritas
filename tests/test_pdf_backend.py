"""可插拔 PDF 后端：默认 pypdf、Docling 回退、派生低可信、分诊路由。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.ingest.case_loader import SourceSpec, ingest_file, load_case
from app.ingest.pdf_backend import (
    ExtractResult,
    extract_pdf,
    resolved_backend,
    set_pdf_backend,
)


@pytest.fixture(autouse=True)
def _reset_backend():
    set_pdf_backend(None)
    old = os.environ.pop("VERITAS_PDF_BACKEND", None)
    yield
    set_pdf_backend(None)
    if old is None:
        os.environ.pop("VERITAS_PDF_BACKEND", None)
    else:
        os.environ["VERITAS_PDF_BACKEND"] = old


def _mini_pdf(path: Path, lines: list[str]) -> Path:
    from scripts.build_layout_fixtures import write_pdf
    write_pdf(path, [lines])
    return path


def test_resolved_backend_default_pypdf():
    assert resolved_backend() == "pypdf"


def test_extract_pypdf_reads_text(tmp_path):
    p = _mini_pdf(tmp_path / "a.pdf", ["HelloTable", "Revenue 1280"])
    set_pdf_backend("pypdf")
    r = extract_pdf(p)
    assert r.backend == "pypdf"
    assert "Revenue" in r.text or "1280" in r.text
    assert r.meta.get("parser") == "pypdf"


def test_docling_missing_falls_back_to_pypdf(tmp_path, monkeypatch):
    p = _mini_pdf(tmp_path / "b.pdf", ["FallbackCell", "MARK_42"])
    set_pdf_backend("docling")

    def _boom(_path):
        raise ImportError("Docling 未安装")

    monkeypatch.setattr(
        "app.ingest.pdf_backend._extract_docling", _boom)
    r = extract_pdf(p)
    assert r.backend == "pypdf"
    assert r.fallback_from == "docling"
    assert r.meta.get("parser_fallback") is True
    assert "MARK_42" in r.text or "FallbackCell" in r.text


def test_docling_success_marks_derived(tmp_path, monkeypatch):
    p = _mini_pdf(tmp_path / "c.pdf", ["ignored by mock"])
    set_pdf_backend("docling")

    def _fake(_path):
        return ExtractResult(
            title="mock-doc",
            text="| Account | Amount |\n|---|---|\n| Cash | 99 |\n",
            meta={"parser": "docling", "derived": True, "n_tables": 1},
            backend="docling",
        )

    monkeypatch.setattr(
        "app.ingest.pdf_backend._extract_docling", _fake)
    r = extract_pdf(p)
    assert r.backend == "docling"
    assert "Cash" in r.text
    src = ingest_file(p, "SRC9", SourceSpec())
    assert src.meta.get("parser") == "docling"
    assert src.credibility == 0.3


def test_load_case_layout_parsed_route(tmp_path, monkeypatch):
    case = tmp_path / "case"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "question: q\nsources:\n  - file: t.pdf\n", encoding="utf-8")
    _mini_pdf(case / "t.pdf", ["X"])
    set_pdf_backend("docling")

    def _fake(_path):
        return ExtractResult(
            title="t", text="cell-A 100\n\ncell-B 200",
            meta={"parser": "docling", "derived": True},
            backend="docling",
        )

    monkeypatch.setattr(
        "app.ingest.pdf_backend._extract_docling", _fake)
    d = load_case(case)
    assert any(t["route"] == "layout_parsed" for t in d.triage)
    assert d.sources[0].credibility == 0.3


def test_layout_fixtures_eval_smoke():
    """难例集在默认 pypdf 下应全员抽到 must_contain。"""
    from scripts.build_layout_fixtures import main as build
    from scripts.run_layout_eval import main as run_eval

    build()
    set_pdf_backend("pypdf")
    assert run_eval() == 0
