"""文本切段：把整篇文档拆成可下钻、可引用的原文段落。

策略：按空行切自然段，过短相邻段聚合到目标 500 字、单段超 650 字
二次切分（比赛提问颗粒度细——500 字左右的段落才能让「下钻到原文」
落在真正回答该细节的段落上，900 字的大块往往一段盖三个话题）。

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

_LIST_ITEM = re.compile(r"^\s*(?:[-*•·]|\d+[.、)])")


def split_segments(text: str, target: int = _TARGET, max_len: int = _MAX) -> list[str]:
    """整篇文本 → 段落列表（不编 id，调用方入 Source 时统一编号）。"""
    paras = [p.strip() for p in re_split(text) if p.strip()]
    if not paras:
        return []
    out: list[str] = []
    buf = ""
    for para in paras:
        if len(para) > max_len:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(hard_split(para, max_len))
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
    """按空行（含 Markdown 标题行）切自然段。"""
    lines = text.splitlines()
    paras: list[str] = []
    buf: list[str] = []
    for line in lines:
        if line.strip().startswith("#") and buf:
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
