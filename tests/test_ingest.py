"""摄取层：切段、阅读器、案例装载（全部用临时文件，零外部依赖）。"""

from app.core.evidence import SourceType
from app.ingest.case_loader import ingest_file, infer_source_type, load_case
from app.ingest.readers import read_html
from app.ingest.segment import split_segments


def test_split_paragraphs_and_merge():
    text = "段一的内容足够长不会被聚合。\n\n段二的内容也足够长不会被聚合。\n\n段三同样足够长。"
    segs = split_segments(text, target=10, max_len=90)
    assert len(segs) == 3
    assert segs[0] == "段一的内容足够长不会被聚合。"


def test_split_merges_short_adjacent():
    text = "甲。\n\n乙。\n\n丙。"
    segs = split_segments(text, target=50, max_len=90)
    assert len(segs) == 1 and "甲。" in segs[0] and "丙。" in segs[0]


def test_split_hard_long_paragraph():
    para = "这是一句。" * 400  # 2400 字
    segs = split_segments(para, target=500, max_len=650)
    assert all(len(s) <= 650 for s in segs)
    assert len(segs) >= 3


def test_markdown_heading_starts_new_segment():
    segs = split_segments("# 标题\n内容一的内容足够长。\n\n## 小节\n内容二的内容也足够长。",
                          target=10, max_len=90)
    assert any(s.startswith("# 标题") for s in segs)
    assert any(s.startswith("## 小节") for s in segs)


def test_read_html_extracts_title_and_text(tmp_path):
    p = tmp_path / "a.html"
    p.write_text("<html><head><title>页面标题</title></head><body>"
                 "<script>var x=1;</script><p>正文第一段。</p><p>正文第二段。</p>"
                 "</body></html>", encoding="utf-8")
    title, text = read_html(p)
    assert title == "页面标题"
    assert "正文第一段。" in text and "var x" not in text


def test_ingest_file_segments_with_locator(tmp_path):
    p = tmp_path / "note_x.md"
    p.write_text("# 报告\n\n" + "第一段内容。" * 120 + "\n\n" + "第二段内容。" * 120,
                 encoding="utf-8")
    src = ingest_file(p, "SRC1", SourceType.NOTE)
    assert len(src.segments) >= 2
    assert src.segments[0].id == "SRC1#s1"
    assert src.segments[0].locator


def test_infer_source_type_by_keyword_and_ext(tmp_path):
    assert infer_source_type(tmp_path / "paper_a.pdf") == SourceType.PAPER
    assert infer_source_type(tmp_path / "news_b.html") == SourceType.NEWS
    assert infer_source_type(tmp_path / "c.txt") == SourceType.NOTE


def test_load_case_with_manifest(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "question: 固态电池 2030 能否上车？\n"
        "sources:\n  - file: a.md\n    type: report\n    credibility: 0.75\n",
        encoding="utf-8",
    )
    (tmp_path / "a.md").write_text("第一段。\n\n第二段。", encoding="utf-8")
    (tmp_path / "paper_b.txt").write_text("假装是论文文本", encoding="utf-8")
    d = load_case(tmp_path)
    assert d.question == "固态电池 2030 能否上车？"
    assert len(d.sources) == 2
    a = next(s for s in d.sources if s.meta.get("file", "").endswith("a.md"))
    assert a.source_type == SourceType.REPORT and a.credibility == 0.75
    # 未在 manifest 声明的文件：文件名关键词推断类型
    b = next(s for s in d.sources if s.meta.get("file", "").endswith("paper_b.txt"))
    assert b.source_type == SourceType.PAPER


def test_load_case_manifest_indent_selfheal(tmp_path):
    # 缩进硬伤：sources 项多 4 空格（token-burner 实测的官方题面病灶）
    (tmp_path / "manifest.yaml").write_text(
        "question: Q\n"
        "sources:\n"
        "    - file: a.md\n"
          "      type: report\n",
        encoding="utf-8",
    )
    (tmp_path / "a.md").write_text("内容。", encoding="utf-8")
    d = load_case(tmp_path)
    assert d.question == "Q"
    assert d.sources[0].source_type == SourceType.REPORT


# -- 完整性切分（500/650 + 行感知） -----------------------------------------------


def test_table_header_follows_every_chunk():
    """表格按行组切且表头随块走：数据行永不离开列名成孤儿。"""
    rows = ["| 客户 | 回款 | 状态 |", "|---|---|---|"]
    rows += [f"| 客户{i} | 1,28{i}万元 | 正常 |" for i in range(40)]
    segs = split_segments("\n".join(rows), target=500, max_len=650)
    assert len(segs) >= 2
    for s in segs:
        assert s.splitlines()[0] == rows[0]          # 表头在每块首行
        assert all(ln.startswith("|") for ln in s.splitlines())


def test_list_items_never_mixed_with_prose():
    """列表按条目行切：条目不被正文句子拦腰合并。"""
    body = "前言综述。" + "长" * 300
    items = "\n".join(f"- 条目{i}的内容足够长需要单独成段 Some detail {i}。" * 3
                      for i in range(10))
    para = body + "\n" + items
    segs = split_segments(para, target=500, max_len=650)
    list_chunks = [s for s in segs if "- 条目" in s]
    assert list_chunks
    for s in list_chunks:
        assert all(ln.lstrip().startswith("-") for ln in s.splitlines()[1:] or ["-"]) or \
            all(ln.lstrip().startswith("-") for ln in s.splitlines()
                if not ln.startswith("前言"))


def test_sentences_never_cut_midway():
    """二次切分落在句号后：任一块都不以半个句子结尾。"""
    para = "".join(f"这是第{i}个完整的句子，包含足够的长度信息。" for i in range(60))
    segs = split_segments(para, target=500, max_len=650)
    assert len(segs) >= 2
    for s in segs[:-1]:
        assert s.endswith(("。", "！", "？", "；"))


def test_default_segment_size_is_fine_grained():
    """默认参数即 500/650（比赛细颗粒度提问的对齐）。"""
    from app.ingest.segment import SEGMENT_MAX, SEGMENT_TARGET

    assert (SEGMENT_TARGET, SEGMENT_MAX) == (500, 650)
