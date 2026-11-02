"""C-114：证据定位稳；默认关；禁系数；重构后再解析一致。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.core.anchor_stable import (
    anchor_stable_enabled,
    compare_anchor_maps,
    dossier_anchor_map,
    resolve_paragraph_text,
    text_fingerprint,
    validate_citation_anchor,
)
from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys
from app.ingest.official_case import load_official_case


def _write_case(tmp: Path, docs: list[dict]) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "raw_documents.json").write_text(
        json.dumps(docs, ensure_ascii=False), encoding="utf-8",
    )
    return tmp


def _doc(doc_id: str, content: str, paras: list[dict]) -> dict:
    return {
        "doc_id": doc_id,
        "title": f"标题-{doc_id}",
        "content": content,
        "content_url": "",
        "publish_time": "2024-01-01",
        "source_credibility": 0.8,
        "paragraphs": paras,
    }


def test_c114_flag_default_off(monkeypatch):
    monkeypatch.delenv("VERITAS_ANCHOR_STABLE", raising=False)
    assert Settings().anchor_stable is False
    assert anchor_stable_enabled() is False
    monkeypatch.setenv("VERITAS_ANCHOR_STABLE", "1")
    assert Settings.from_env().anchor_stable is True
    assert anchor_stable_enabled() is True


def test_c114_flag_off_legacy_slice(monkeypatch, tmp_path):
    """旗关＝严格切片；BOM 前置会漂（与改前同）。"""
    monkeypatch.setenv("VERITAS_ANCHOR_STABLE", "0")
    body = "甲乙丙丁戊己庚辛壬癸子丑寅卯"
    span = 8  # ≥ MIN_PARA_CHARS
    docs = [_doc("doc_a", "\ufeff" + body, [
        {"para_id": "doc_a#p1", "char_start": 0, "char_end": span},
    ])]
    case = _write_case(tmp_path / "off", docs)
    d = load_official_case(case)
    # BOM 占 1：旗关切到「\\ufeff＋前 span-1 字」≠ 原「前 span 字」
    assert len(d.sources) == 1
    seg = d.sources[0].segments[0]
    assert seg.text != body[:span]
    assert "anchor_stable" not in (d.accounting or {})


def test_c114_flag_on_strips_bom_and_rebinds(monkeypatch, tmp_path):
    monkeypatch.setenv("VERITAS_ANCHOR_STABLE", "1")
    body = "甲乙丙丁戊己庚辛壬癸子丑寅卯"
    span = 8
    # 转存时带上段落正文指纹；再前置 BOM（偏移相对无 BOM 正文）
    docs = [_doc("doc_a", "\ufeff" + body, [
        {
            "para_id": "doc_a#p1",
            "char_start": 0,
            "char_end": span,
            "text": body[:span],
        },
    ])]
    case = _write_case(tmp_path / "on", docs)
    d = load_official_case(case)
    seg = d.sources[0].segments[0]
    assert seg.text == body[:span]
    assert seg.id == "doc_a#p1"
    acc = d.accounting["anchor_stable"]
    assert acc["n_rebound"] + acc["n_ok"] >= 1
    assert audit_forbidden_keys(acc) == []
    for bad in FORBIDDEN_PACK_KEYS:
        assert bad not in acc


def test_c114_flag_on_unwraps_envelope(monkeypatch, tmp_path):
    monkeypatch.setenv("VERITAS_ANCHOR_STABLE", "1")
    body = "足够长的段落正文用于通过最小字数闸"
    docs = [_doc("doc_b", body, [
        {"para_id": "doc_b#p1", "char_start": 0, "char_end": len(body),
         "text": body},
    ])]
    path = tmp_path / "env" / "raw_documents.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"raw_documents": docs}, ensure_ascii=False),
        encoding="utf-8",
    )
    d = load_official_case(path.parent)
    assert d.sources[0].segments[0].id == "doc_b#p1"


def test_c114_contract_rejects_fuzzy_only():
    ok, _ = validate_citation_anchor({
        "doc_id": "d1", "para_id": "d1#p1", "quote": "x",
    })
    assert ok
    bad, reason = validate_citation_anchor({"title": "只有标题", "quote": "片段"})
    assert not bad
    assert "fuzzy_only" in reason


def test_c114_reload_consistency_gain(monkeypatch, tmp_path):
    """同金标键：旗开在 BOM+嵌入文应力下一致率高于旗关。"""
    body = "刘翔同志自主择业经济补偿金按规定发放完毕。"
    base_docs = [_doc("doc_001", body, [
        {"para_id": "doc_001#p1", "char_start": 0, "char_end": len(body)},
    ])]
    base = _write_case(tmp_path / "base", base_docs)
    monkeypatch.setenv("VERITAS_ANCHOR_STABLE", "0")
    base_map = dossier_anchor_map(load_official_case(base))

    stressed = [_doc("doc_001", "\ufeff" + body, [
        {
            "para_id": "doc_001#p1",
            "char_start": 0,
            "char_end": len(body),
            "text": body,
        },
    ])]
    st = _write_case(tmp_path / "stress", stressed)

    monkeypatch.setenv("VERITAS_ANCHOR_STABLE", "0")
    off = compare_anchor_maps(base_map, dossier_anchor_map(load_official_case(st)))
    monkeypatch.setenv("VERITAS_ANCHOR_STABLE", "1")
    on = compare_anchor_maps(base_map, dossier_anchor_map(load_official_case(st)))
    assert on["consistency_rate"] > off["consistency_rate"]
    assert on["consistency_rate"] == 1.0
    assert not on["missing_anchor"] and not on["drift"]


def test_c114_resolve_off_matches_raw_slice():
    content = "abcdefghij"
    para = {"para_id": "x#p1", "char_start": 2, "char_end": 6}
    out = resolve_paragraph_text(content, para, harden=False)
    assert out["text"] == content[2:6]
    assert out["status"] == "ok"


def test_c114_fingerprint_stable():
    assert text_fingerprint("甲  乙\n丙") == text_fingerprint("甲 乙 丙")
