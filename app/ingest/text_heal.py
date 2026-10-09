"""PDF/公告文本愈合（零 LLM）：拆字与断行表标签拼回可读句。

巨潮摘要常见两类损伤：
1. 汉字被空格拆开：``归 属 于 上 市 公 司``；
2. 表行在标签中切开，数字夹在两半之间：
   ``归属于上市公司股 31,831,900.82 …`` / 下一行 ``东的净利润``。

在切段之前愈合，引文逐字闸与槽位观察才能命中「归属于上市公司股东的净利润」。
"""

from __future__ import annotations

import re

# 汉字之间的排版空格（含全角）压掉；数字/英文旁空格保留
_CJK_SPACE = re.compile(r"(?<=[\u4e00-\u9fff])[ \t\u3000]+(?=[\u4e00-\u9fff])")
# 行尾：标签头 + 一串财务数字（可含同比%）
_LABEL_THEN_NUMS = re.compile(
    r"^(.*[\u4e00-\u9fff])\s+"
    r"(-?\d[\d,]*(?:\.\d+)?(?:\s+-?\d[\d,]*(?:\.\d+)?)*(?:\s*-?\d+(?:\.\d+)?)?%?)"
    r"\s*$"
)
# 已是完整指标名，不必再拼尾巴
_COMPLETE_TAIL = re.compile(
    r"(净利润|净资产|净额|收益率|营业收入|营业总收入|总资产|现金流量)$"
)


def heal_extracted_text(text: str) -> str:
    """摄取后、切段前：拆字合并 + 断行标签拼接。"""
    if not text:
        return text
    text = collapse_cjk_spaces(text)
    text = stitch_broken_metric_lines(text)
    return text


def collapse_cjk_spaces(text: str) -> str:
    """``归 属 于`` → ``归属于``（只压汉字夹缝空白）。"""
    prev = None
    while prev != text:
        prev = text
        text = _CJK_SPACE.sub("", text)
    return text


def stitch_broken_metric_lines(text: str) -> str:
    """把「标签头 + 数字」与下一行「标签尾」拼成完整一行。

    中间空行忽略（pypdf 常在表行间断一空行）。
    """
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        j, nxt = _next_nonempty(lines, i + 1)
        if nxt is not None and _is_label_continuation(nxt):
            # 模式 A：头与尾都无数字，纯标签被换行切断
            if _is_open_label_head(cur) and not re.search(r"\d", cur):
                out.append(f"{cur.rstrip()}{nxt}")
                i = j + 1
                continue
            # 模式 B：头+数字在同行，尾在下行 → 尾插到数字前
            m = _LABEL_THEN_NUMS.match(cur.rstrip())
            if m and not _COMPLETE_TAIL.search(m.group(1)):
                head, nums = m.group(1), m.group(2)
                out.append(f"{head}{nxt} {nums}".rstrip())
                i = j + 1
                continue
        out.append(cur)
        i += 1
    return "\n".join(out)


def _next_nonempty(lines: list[str], start: int) -> tuple[int, str | None]:
    j = start
    while j < len(lines):
        s = lines[j].strip()
        if s:
            return j, s
        j += 1
    return start, None


def _is_label_continuation(line: str) -> bool:
    s = line.strip()
    if not (2 <= len(s) <= 24):
        return False
    if not ("\u4e00" <= s[0] <= "\u9fff"):
        return False
    if re.search(r"\d{3,}", s):
        return False
    cjk = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    return cjk >= 2


def _is_open_label_head(line: str) -> bool:
    s = line.strip()
    if len(s) < 2 or _COMPLETE_TAIL.search(s):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]$", s))
