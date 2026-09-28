"""文本切段：把整篇文档拆成可下钻、可引用的原文段落。

策略：按空行切自然段，过长相邻段聚合、超长单段二次切分，目标
600 字、上限 900 字（引文下钻的最小单元不宜过大，也不至于碎到
丢上下文）。
"""

from __future__ import annotations

_TARGET = 600
_MAX = 900


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
    """超长单段按句子边界二次切分（。！？；换行），退化为定长切。"""
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
