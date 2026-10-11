"""文本切段：把整篇文档拆成可下钻、可引用的原文段落。

策略：按空行 / Markdown 标题 / 公文层次标题切自然段，过短相邻段
聚合到目标 500 字、单段超 650 字二次切分（比赛提问颗粒度细——
500 字左右的段落才能让「下钻到原文」落在真正回答该细节的段落上，
900 字的大块往往一段盖三个话题）。

层次切片：识别「一、」「（一）」「第一章/条」等结构标题，标题行
强制起新段，且聚合时禁止跨节合并——通告/年报按章节下钻，不把
「一、」与「二、」粘成一块。

完整性优先于均匀：二次切分遵守三条规则——
1. 句子边界优先（。！？；换行后落刀），从不切断句子中段；
2. 列表按条目行切，条目不与正文混装；
3. Markdown 表格按行组切，**表头随每一块走**——跨块引用仍能对上
   列名，不再出现「数据行离开表头成孤儿」的断头段落。
"""

from __future__ import annotations

import re

_TARGET = 500
_MAX = 650

SEGMENT_TARGET = _TARGET
SEGMENT_MAX = _MAX
# 切段规则变更时递增。语料索引据此废旧段，避免旧 segment_id 与新边界混用。
SEGMENTER_VERSION = "hier-v1"

_LIST_ITEM = re.compile(r"^\s*(?:[-*•·]|\d+[.、)])")

# 公文/年报结构标题（行首）。不含阿拉伯数字「1.」——那与列表条目重合，
# 仍走列表行原子切分；层次断段只认中文序号与「第X章/节/条」。
_CN_NUM = r"[一二三四五六七八九十百千零〇两]+"
_SECTION_HEADING = re.compile(
    rf"^(?:"
    rf"#{1,6}\s+\S"                          # Markdown 标题
    rf"|{_CN_NUM}、\S"                        # 一、概述
    rf"|[（(]{_CN_NUM}[)）]\S?"               # （一）或（一）标题
    rf"|第{_CN_NUM}[章节条款项部分篇]\S*"       # 第一章 / 第十条
    rf"|第\d{{1,3}}[章节条款项部分篇]\S*"      # 第1章 / 第12条
    rf")"
)


def is_section_heading(line: str) -> bool:
    """行首是否为结构标题（层次切片的断点判据）。"""
    s = line.strip()
    return bool(s) and _SECTION_HEADING.match(s) is not None


def split_segments(text: str, target: int = _TARGET, max_len: int = _MAX) -> list[str]:
    """整篇文本 → 段落列表（不编 id，调用方入 Source 时统一编号）。"""
    paras = [p.strip() for p in re_split(text) if p.strip()]
    if not paras:
        return []
    out: list[str] = []
    buf = ""
    for para in paras:
        starts_section = is_section_heading(para.splitlines()[0])
        if len(para) > max_len:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(hard_split(para, max_len))
        elif starts_section and buf:
            # 新节起笔：即使未满 target 也不与上一节聚合
            out.append(buf)
            buf = para
        elif len(buf) + len(para) + 1 <= target:
            buf = f"{buf}\n{para}" if buf else para
        else:
            if buf:
                out.append(buf)
            buf = para
    if buf:
        out.append(buf)
    return out


def re_split(text: str) -> list[str]:
    """按空行、Markdown/公文层次标题切自然段。"""
    lines = text.splitlines()
    paras: list[str] = []
    buf: list[str] = []
    for line in lines:
        if is_section_heading(line) and buf:
            paras.append("\n".join(buf))
            buf = [line]
        elif not line.strip() and buf:
            paras.append("\n".join(buf))
            buf = []
        else:
            buf.append(line)
    if buf:
        paras.append("\n".join(buf))
    return paras


def hard_split(para: str, max_len: int) -> list[str]:
    """超长单段二次切分：表格/列表/普通文本三分处置（见模块 docstring）。"""
    lines = para.splitlines()
    table_lines = [ln for ln in lines if ln.lstrip().startswith("|")]
    if len(table_lines) >= 3:
        return _split_table(lines, max_len)
    if len(lines) > 2 and any(_LIST_ITEM.match(ln) for ln in lines[1:]):
        return _split_lines(lines, max_len)
    return _split_sentences(para, max_len)


def _split_sentences(para: str, max_len: int) -> list[str]:
    """句子边界切分（。！？；换行后落刀），退化为定长切。"""
    pieces: list[str] = []
    cur = ""
    for ch in para:
        cur += ch
        if ch in "。！？；\n" and len(cur) >= max_len // 2:
            pieces.append(cur.strip())
            cur = ""
        elif len(cur) >= max_len:
            pieces.append(cur.strip())
            cur = ""
    if cur.strip():
        pieces.append(cur.strip())
    return pieces


def _split_lines(lines: list[str], max_len: int) -> list[str]:
    """列表/行式文本：行是原子，超长才落刀——条目永不与正文混装。"""
    out: list[str] = []
    buf = ""
    for ln in lines:
        cand = f"{buf}\n{ln}" if buf else ln
        if len(cand) > max_len and buf:
            out.append(buf)
            buf = ln
        else:
            buf = cand
    if buf.strip():
        out.append(buf)
    return out


def _is_table_sep(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and stripped.startswith("|") and \
        set(stripped) <= set("|-: ")


def _split_table(lines: list[str], max_len: int) -> list[str]:
    """表格按行组切：表头与分隔行随每一块走，列名永不孤儿。"""
    header = lines[0] if lines[0].lstrip().startswith("|") else ""
    sep = lines[1] if len(lines) > 1 and header and _is_table_sep(lines[1]) else ""
    start = 2 if (header and sep) else (1 if header else 0)
    rows = lines[start:]
    head_block = "\n".join(x for x in (header, sep) if x)
    budget = max_len - (len(head_block) + 1 if head_block else 0)
    chunks: list[str] = []
    buf = ""
    for row in rows:
        cand = f"{buf}\n{row}" if buf else row
        if len(cand) > budget and buf:
            chunks.append(f"{head_block}\n{buf}" if head_block else buf)
            buf = row
        else:
            buf = cand
    if buf.strip():
        chunks.append(f"{head_block}\n{buf}" if head_block else buf)
    return chunks
