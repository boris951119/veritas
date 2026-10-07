"""复合输入：链接清单（默认披露/显式抓取）+ 压缩包安全拆封 + 目录遍历。

敌意样本全覆盖：zip-slip、炸弹（声明超限/实际超限）、数量上限、
嵌套压缩包、加密 zip、损坏包、不支持的 7z。全部零网络（抓取桩注入）。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.ingest import links as links_mod
from app.ingest.archive import expand_archive, sniff_format
from app.ingest.case_loader import load_case
from app.ingest.links import (
    LinkFetchError, classify_link_list, extract_urls, fetch_link_source,
)


def _case(tmp_path: Path, name: str = "demo") -> Path:
    case_dir = tmp_path / "cases" / name
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text(
        "question: 客户B的交付风险如何？\n", encoding="utf-8")
    return case_dir


LINKS_TXT = "\n".join(f"https://example.com/doc{i}" for i in range(8)) + "\n"


# -- 链接清单检测 ----------------------------------------------------------------


def test_classify_link_list():
    ok, n = classify_link_list(LINKS_TXT)
    assert ok and n == 8
    prose = "客户B回款率40%，详见 https://example.com/report 。" * 3
    assert not classify_link_list(prose)[0]


def test_extract_urls_dedup_and_cap():
    text = "\n".join(["https://a.com/x"] * 5 + [f"https://b.com/{i}" for i in range(40)])
    urls = extract_urls(text, cap=10)
    assert len(urls) == 10 and urls[0] == "https://a.com/x"


def test_link_list_disclosed_not_ingested_by_default(tmp_path):
    case_dir = _case(tmp_path)
    (case_dir / "links.txt").write_text(LINKS_TXT, encoding="utf-8")
    d = load_case(case_dir)
    assert not d.sources                       # URL 文本不入卷
    note = next(n for n in d.ingest_notes if n["kind"] == "links")
    assert "8 条网页链接未抓取" in note["detail"]


def test_link_fetch_creates_web_sources_with_accounting(tmp_path, monkeypatch):
    case_dir = _case(tmp_path)
    (case_dir / "links.txt").write_text(LINKS_TXT, encoding="utf-8")

    calls: list[str] = []

    def fake_fetch(url: str):
        calls.append(url)
        if "doc3" in url:
            raise LinkFetchError("HTTP 404")
        from types import SimpleNamespace
        return ("text/html",
                f"<html><title>报道{url[-1]}</title><body><p>客户B交付风险"
                f"相关正文 {url}，回款率40%。</p></body></html>".encode())

    monkeypatch.setattr(links_mod, "fetch_raw", fake_fetch)
    d = load_case(case_dir, fetch_links=True)
    assert len(d.sources) == 7                 # 8 条中 1 条 404
    assert all(s.source_type.value == "web" and s.credibility == 0.3
               for s in d.sources)
    assert all(s.meta.get("url") and s.meta.get("fetched")
               for s in d.sources)
    note = next(n for n in d.ingest_notes if n["kind"] == "links")
    assert "成功 7 条" in note["detail"] and "404" in note["detail"]


def test_fetched_source_overrides_injected_fetcher(monkeypatch):
    def fake_fetch(url: str):
        return ("text/html",
                "<html><title>页面</title><body><p>正文内容足够长。</p>"
                "</body></html>".encode("utf-8"))

    monkeypatch.setattr(links_mod, "fetch_raw", fake_fetch)
    src = fetch_link_source("https://x.com/a")
    assert src.title == "页面" and src.segments


# -- 压缩包拆封 ------------------------------------------------------------------


def _make_zip(path: Path, entries: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_sniff_formats(tmp_path):
    z = tmp_path / "a.zip"
    _make_zip(z, {"x.txt": "hi"})
    assert sniff_format(z) == "zip"
    seven = tmp_path / "b.7z"
    seven.write_bytes(b"\x37\x7a\xbc\xaf\x27\x1c" + b"\x00" * 32)
    assert sniff_format(seven) == "7z"
    assert sniff_format(tmp_path / "c.txt") == ""


def test_zip_happy_path_mixed_content(tmp_path):
    case_dir = _case(tmp_path)
    (case_dir / "资料.zip").write_bytes(b"")  # 占位后重写
    _make_zip(case_dir / "资料.zip", {
        "审计报告.md": "# 审计\n\n客户B回款率40%，累计回款512万元。",
        "回款凭证.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        "links.txt": LINKS_TXT,
    })
    d = load_case(case_dir)
    # 只有 md 入卷；png 披露 image_file；links 披露未抓取；zip 本身不是信源
    assert [s.source_type.value for s in d.sources] == ["note"]
    assert any(n["kind"] == "image_file" and "资料.zip::回款凭证.png" in n["file"]
               for n in d.ingest_notes)
    assert any(n["kind"] == "links" for n in d.ingest_notes)
    assert any(n["kind"] == "archive" and "解包 3 个" in n["detail"]
               for n in d.ingest_notes)


def test_zip_slip_entries_rejected(tmp_path):
    case_dir = _case(tmp_path)
    _make_zip(case_dir / "evil.zip", {
        "../穿越.txt": "escape",
        "/abs/path.txt": "absolute",
        "正常.md": "客户B正常内容。",
    })
    d = load_case(case_dir)
    note = next(n for n in d.ingest_notes if n["kind"] == "archive")
    assert "拒绝 2" in note["detail"] and ("路径穿越" in note["detail"]
                                           or "绝对路径" in note["detail"])
    assert len(d.sources) == 1                 # 正常条目照常入卷


def test_zip_bomb_declared_size_rejected(tmp_path, monkeypatch):
    import app.ingest.archive as arch
    monkeypatch.setattr(arch, "MAX_ENTRY_BYTES", 100)
    case_dir = _case(tmp_path)
    _make_zip(case_dir / "bomb.zip", {"big.md": "客" * 400})
    d = load_case(case_dir)
    note = next(n for n in d.ingest_notes if n["kind"] == "archive")
    assert "超单文件上限" in note["detail"] and not d.sources


def test_zip_bomb_lying_header_truncated(tmp_path, monkeypatch):
    """包头说谎（声明小、实际大）：流式硬上限拒收（或按损坏包披露，
    两种都是合法的敌意处置，绝不让它入卷）。"""
    import app.ingest.archive as arch
    monkeypatch.setattr(arch, "MAX_ENTRY_BYTES", 100)
    case_dir = _case(tmp_path)
    # 用 zipfile 正常写入（声明=实际 400B），再篡改中央目录声明大小为 1B
    _make_zip(case_dir / "lie.zip", {"x.md": "客户B内容。" * 40})
    import struct
    raw = bytearray((case_dir / "lie.zip").read_bytes())
    sig = raw.find(b"PK\x01\x02")
    struct.pack_into("<I", raw, sig + 24, 1)   # 中央目录未压缩大小
    (case_dir / "lie.zip").write_bytes(bytes(raw))
    entries, notes = expand_archive(case_dir / "lie.zip", tmp_path / "out")
    # 安全性质：零入卷 + 有账（zipfile 自校验抛 BadZipFile 或流式截断，
    # 两条路都是合法的敌意处置）
    assert not entries
    assert any("拒绝" in n["detail"] or "损坏" in n["detail"]
               for n in notes)


def test_nested_archive_not_expanded(tmp_path):
    case_dir = _case(tmp_path)
    inner = case_dir / "inner.zip"
    _make_zip(inner, {"a.md": "客户B内层内容。"})
    _make_zip(case_dir / "outer.zip", {"inner.zip": inner.read_bytes()})
    inner.unlink()
    d = load_case(case_dir)
    note = next(n for n in d.ingest_notes if n["kind"] == "archive")
    assert "嵌套压缩包未展开" in note["detail"]
    assert not d.sources


def test_encrypted_zip_disclosed(tmp_path, monkeypatch):
    """加密条目：标准库写不出真加密 zip，用桩模拟 open 抛 RuntimeError
    （expand_archive 的处置路径与真实加密包一致）。"""
    case_dir = _case(tmp_path)
    _make_zip(case_dir / "enc.zip", {"秘密.md": "客户B内容。"})
    monkeypatch.setattr(
        zipfile.ZipFile, "open",
        lambda self, *a, **kw: (_ for _ in ()).throw(
            RuntimeError("File is encrypted, password required")))
    d = load_case(case_dir)
    assert any(n["kind"] == "archive" and "加密" in n["detail"]
               for n in d.ingest_notes)
    assert not d.sources


def test_corrupt_zip_disclosed(tmp_path):
    case_dir = _case(tmp_path)
    (case_dir / "bad.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    d = load_case(case_dir)
    assert any(n["kind"] == "archive" for n in d.ingest_notes)
    assert not d.sources


def test_unsupported_7z_disclosed(tmp_path):
    case_dir = _case(tmp_path)
    (case_dir / "data.7z").write_bytes(b"\x37\x7a\xbc\xaf\x27\x1c" + b"\x00" * 64)
    d = load_case(case_dir)
    assert any(n["kind"] == "archive" and "不支持" in n["detail"]
               for n in d.ingest_notes)


# -- 目录遍历与混合场景 ------------------------------------------------------------


def test_subdirectories_walked_with_provenance(tmp_path):
    case_dir = _case(tmp_path)
    sub = case_dir / "报告材料"
    sub.mkdir()
    (sub / "审计.md").write_text("客户B回款率40%。", encoding="utf-8")
    (case_dir / "根目录说明.md").write_text("客户B合同金额1280万元。", encoding="utf-8")
    d = load_case(case_dir)
    assert len(d.sources) == 2
    rels = [s.meta["file"] for s in d.sources]
    assert any("报告材料/审计.md" in r for r in rels)


def test_hidden_and_cache_dirs_skipped(tmp_path):
    case_dir = _case(tmp_path)
    (case_dir / ".git").mkdir()
    (case_dir / ".git" / "config").write_text("x", encoding="utf-8")
    (case_dir / "__pycache__").mkdir()
    (case_dir / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"\x00")
    (case_dir / "正常.md").write_text("客户B内容。", encoding="utf-8")
    d = load_case(case_dir)
    assert len(d.sources) == 1


def test_full_mixed_bundle_zip(tmp_path, monkeypatch):
    """主办方形态的完整混合包：报告+图片+链接清单+重复件，一次跑通。"""
    case_dir = _case(tmp_path)
    report = "# 审计\n\n客户B回款率40%，累计回款512万元。"
    _make_zip(case_dir / "资料.zip", {
        "审计报告.md": report,
        "审计报告副本.md": report,       # SHA-256 重复件
        "回款凭证.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        "links.txt": LINKS_TXT,
    })
    from app.ingest import links as links_mod

    def fake_fetch(url: str):
        return ("text/html",
                f"<html><title>报道</title><body>客户B交付进展正文。</body>"
                f"</html>".encode())

    monkeypatch.setattr(links_mod, "fetch_raw", fake_fetch)
    d = load_case(case_dir, fetch_links=True)
    kinds = sorted(n["kind"] for n in d.ingest_notes)
    assert "archive" in kinds and "image_file" in kinds and "links" in kinds
    # md 正本 + 副本（入卷，去重在装箱期排除）+ 抓取的 8 页 = 10 份信源
    assert len(d.sources) == 10
    from app.core.dup_check import duplicate_map
    assert duplicate_map(d)  # 副本被识别为精确重复，不进分析师提示词


def test_artifact_dirs_never_reingested(tmp_path):
    """自产文件环路回归守护：产物目录（out/out_offline/out_ab_*）绝不
    被输入遍历吃回——归一化 diff 验收抓到的真实回归（滚雪球膨胀）。"""
    case_dir = _case(tmp_path)
    (case_dir / "正常.md").write_text("客户B回款率40%。", encoding="utf-8")
    for sub in ("out", "out_offline", "out_ab_a_1"):
        art = case_dir / sub
        art.mkdir()
        (art / "report.json").write_text('{"conclusions": []}', encoding="utf-8")
    d = load_case(case_dir)
    assert [s.title for s in d.sources] == ["正常"]
    assert all("out" not in r["file"] for r in d.triage)


def test_hidden_files_never_ingested(tmp_path):
    """拓尔思语料首战抓出的真 bug:.DS_Store 等隐藏文件不入卷。"""
    case_dir = _case(tmp_path)
    (case_dir / "正常.md").write_text("客户B回款率40%。", encoding="utf-8")
    (case_dir / ".DS_Store").write_bytes(b"\x00" * 8)
    (case_dir / ".expected.json").write_text("{}", encoding="utf-8")
    d = load_case(case_dir)
    assert len(d.sources) == 1
    assert all(not r["file"].startswith(".") for r in d.triage)
