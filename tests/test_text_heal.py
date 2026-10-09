"""PDF 拆字/断行表标签愈合 + 引文命中回归（Q8 口径）。"""

from app.core.citation_check import check_evidence, check_quote
from app.core.evidence import EvidenceNode, Segment, Source, SourceType, Dossier
from app.ingest.segment import split_segments
from app.ingest.text_heal import (
    collapse_cjk_spaces, heal_extracted_text, stitch_broken_metric_lines,
)


# 自 2024 半年报摘要 pypdf 原文截取（损伤形态）
_RAW_TABLE = """2.2 主要财务数据
单位：元  币种：人民币
营业收入 356,769,612.82 312,580,769.16 14.14
归 属 于 上 市 公 司 股 31,831,900.82 44,243,529.09 -28.05
东的净利润
归 属 于 上 市 公 司 股
东的净资产
1,737,499,779.33 1,758,999,535.59 -1.22
"""


def test_collapse_cjk_spaces():
    assert collapse_cjk_spaces("归 属 于 上 市 公 司") == "归属于上市公司"
    assert "31,831" in collapse_cjk_spaces("股 31,831,900.82")


def test_stitch_puts_tail_before_numbers():
    raw = "归属于上市公司股 31,831,900.82 44,243,529.09 -28.05\n东的净利润"
    out = stitch_broken_metric_lines(raw)
    assert "归属于上市公司股东的净利润 31,831,900.82" in out
    assert out.index("净利润") < out.index("31,831")


def test_stitch_skips_blank_line_between_head_and_tail():
    raw = ("归属于上市公司股 31,831,900.82 44,243,529.09 -28.05\n"
           "\n"
           "东的净利润")
    out = stitch_broken_metric_lines(raw)
    assert "归属于上市公司股东的净利润 31,831,900.82" in out


def test_stitch_joins_label_only_break():
    raw = "归属于上市公司股\n东的净资产\n1,737,499,779.33"
    out = stitch_broken_metric_lines(raw)
    assert "归属于上市公司股东的净资产" in out


def test_heal_then_quote_hits_parent_net_profit():
    healed = heal_extracted_text(_RAW_TABLE)
    assert "归属于上市公司股东的净利润" in healed.replace(" ", "")
    q = "归属于上市公司股东的净利润 31,831,900.82"
    assert check_quote(q, healed).ok
    assert check_quote("营业收入 356,769,612.82", healed).ok


def test_heal_before_split_keeps_metric_with_number():
    healed = heal_extracted_text(_RAW_TABLE)
    segs = split_segments(healed)
    blob = "\n".join(segs)
    assert "归属于上市公司股东的净利润" in blob.replace(" ", "")
    assert any(
        check_quote("归属于上市公司股东的净利润 31,831,900.82", s).ok
        for s in segs
    )


def test_adjacent_segment_citation_fallback():
    """标签与数字分落相邻段：拼接窗口应放过。"""
    d = Dossier(question="Q")
    src = Source.create("T", SourceType.REPORT, id="SRC1")
    src.segments = [
        Segment(id="SRC1#s1", source_id="SRC1",
                text="本报告期归属于上市公司股东的净利润为"),
        Segment(id="SRC1#s2", source_id="SRC1",
                text="31,831,900.82元，同比下降28.05%。"),
    ]
    d.add_source(src)
    ev = EvidenceNode.create(
        "CON1", "归属于上市公司股东的净利润为31,831,900.82元", ["SRC1#s1"])
    assert check_evidence(ev, d) == []
    # 单段仍不命中
    assert not check_quote(
        "归属于上市公司股东的净利润为31,831,900.82元",
        src.segments[0].text).ok
