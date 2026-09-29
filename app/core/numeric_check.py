"""数字机械核对器：计算复算 + 数字溯源 + 归并守恒（三道零 LLM 闸）。

引文核对器只保证「引文真实存在」；本模块堵引文之外的第二大幻觉源
——模型自己算出来的、或自己带来的数字：

- 计算闸（红，severity=high）：结论/证据说明里的显式算式
  （512/1280=40%、1280-512=768、512万+256万=768万、1280×40%=512）
  由程序代入重算；算式对不上 → 「计算不复现」，算式输入数在所引
  材料中定位不到 → 「计算输入超出所引证据」。
- 溯源闸（黄，severity=medium）：结论中的每个数字要么出自所引证据
  （引文/段落/议题），要么是已验证算式的产物；否则标记「来源外数字」。
- 守恒闸（黄）：归并组结论不得引入成员结论与组证据之外的新数字
  （「普遍恶化」式概括漂移的机械侧；实体守恒交给质证与仲裁）。

判定全程数值与字符串运算，零模型调用、可复现；与引文核对器同一
哲学：模型负责主张，程序负责复算。输出统一为 flag dict（见
core/audit.py），供报告、工作台与哈希链留痕消费。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.evidence import Dossier

# ---------------------------------------------------------------- 提取器

_NUM_TOKEN = r"\d(?:[\d,]*\d)?(?:\.\d+)?"
# 数字 + 可选单位（万/亿/%）；raw 为原文切片，value 为纯数值
_NUM_RE = re.compile(rf"({_NUM_TOKEN})\s*(万|亿|%|％)?")

# 算式：数字(带单位) 与 + - × ÷ 连接，等号右侧为结果（可带 万/亿/%）
_OP = r"[+＋\-−×x÷／/]"
_EXPR_RE = re.compile(
    rf"({_NUM_TOKEN}\s*(?:万|亿|%|％)?(?:\s*{_OP}\s*{_NUM_TOKEN}\s*(?:万|亿|%|％)?){{1,4}})"
    rf"\s*[=＝]\s*({_NUM_TOKEN})\s*(万|亿|%|％)?"
)

# 溯源时跳过的噪声数字：日期/时间/编号 id/序数/计数量词
# （日期必须月份 1-12 合法，避免把 1280-512、1280.50 这类算式/小数当日期剥掉）
_DATE_TIME_RE = re.compile(
    r"\d{4}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])"   # 2026-03-15
    r"|\d{4}[-](?:0?[1-9]|1[0-2])(?!\d)"                            # 2026-3 月
    r"|\d{1,2}:\d{2}")                                              # 12:30
_ID_TOKEN_RE = re.compile(r"\b(?:EV|CON|SRC|CFL|PA)-[0-9a-zA-Z]{4,}")
_MEASURE_WORD = "条份个项家篇轮方名人次类档支批起"

_UNIT_SCALE = {"万": 10_000.0, "亿": 100_000_000.0}


@dataclass
class Num:
    """文本中抽出的一个数字：原文切片 + 数值（含单位缩放前后）。"""

    raw: str
    value: float          # 纯数值（无单位缩放）
    scaled: float         # 万/亿 缩放后；% 记 value/100
    unit: str             # 万 / 亿 / % / ""
    start: int
    end: int


def _strip_noise(text: str) -> str:
    """剥掉日期/时间/编号切片——用等长空格替换，保持下标不失真。"""
    return _DATE_TIME_RE.sub(lambda m: " " * len(m.group(0)),
                             _ID_TOKEN_RE.sub(lambda m: " " * len(m.group(0)), text))


def extract_nums(text: str) -> list[Num]:
    """文本 → 数字清单（先剥掉日期/时间/编号等噪声切片）。"""
    cleaned = _strip_noise(text)
    out: list[Num] = []
    for m in _NUM_RE.finditer(cleaned):
        raw = m.group(0).strip()
        value = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").replace("％", "%")
        scaled = value / 100.0 if unit == "%" else value * _UNIT_SCALE.get(unit, 1.0)
        out.append(Num(raw=raw, value=value, scaled=scaled, unit=unit,
                       start=m.start(), end=m.end()))
    return out


def _parse_expr(text: str) -> list[tuple[str, Num, list[Num], bool]]:
    """文本 → [(算式原文, 结果Num, 输入Num清单, 结果是否为百分数)]。"""
    cleaned = _strip_noise(text)
    out = []
    for m in _EXPR_RE.finditer(cleaned):
        result = _num_of(m.group(2).strip(), (m.group(3) or "").replace("％", "%"))
        inputs = [_num_of(nm.group(1).strip(), (nm.group(2) or "").replace("％", "%"))
                  for nm in _NUM_RE.finditer(m.group(1))]
        out.append((m.group(0), result, inputs, result.unit == "%"))
    return out


def _num_of(raw: str, unit: str) -> Num:
    """raw 数值串 + 单位 → Num（统一缩放规则：% 除百，万/亿乘级）。"""
    value = float(raw.replace(",", ""))
    scaled = value / 100.0 if unit == "%" else value * _UNIT_SCALE.get(unit, 1.0)
    return Num(raw=raw + unit, value=value, scaled=scaled, unit=unit, start=0, end=0)


def _eval_expr(expr_text: str) -> float | None:
    """算式串 → 左侧运算结果（自左向右，含单位缩放；解析失败 None）。"""
    tokens = re.findall(rf"({_NUM_TOKEN})\s*(万|亿|%|％)?|([+＋\-−×x÷／/])", expr_text)
    acc: float | None = None
    op = ""
    for value_s, unit_s, op_s in tokens:
        if op_s:
            op = op_s
            continue
        value = float(value_s.replace(",", ""))
        scaled = (value / 100.0 if unit_s in ("%", "％")
                  else value * _UNIT_SCALE.get(unit_s or "", 1.0))
        if acc is None:
            acc = scaled
            continue
        if op in ("+", "＋"):
            acc += scaled
        elif op in ("-", "−"):
            acc -= scaled
        elif op in ("×", "x"):
            acc *= scaled
        elif op in ("÷", "／", "/"):
            if abs(scaled) < 1e-12:
                return None
            acc /= scaled
        else:
            return None
    return acc


def _close(got: float, want: float, rel: float = 0.01) -> bool:
    """数值近似相等：1% 相对容差 + 小额绝对容差（浮点噪声/常规取整）。"""
    return abs(got - want) <= max(0.0051, abs(want) * rel)


# ---------------------------------------------------------------- 三道闸


def _corpus_of(dossier: Dossier, conclusion_id: str) -> str:
    """结论可引用的全部材料：所引证据引文 + 其来源段落 + 议题原文。"""
    parts: list[str] = [dossier.question]
    for ev in dossier.evidences_of(conclusion_id):
        parts.append(ev.quote)
        for sid in ev.segment_ids:
            seg = dossier.segment(sid)
            if seg is not None:
                parts.append(seg.text)
    return "\n".join(parts)


def _traceable(num: Num, corpus_nums: list[Num]) -> bool:
    """算式输入是否能在所引材料中按数值定位（同值即认，单位无关）。"""
    return any(abs(n.value - num.value) <= 1e-9 for n in corpus_nums)


def check_calc(conclusion, dossier: Dossier) -> tuple[list[dict], str]:
    """计算闸：结论与证据说明中的显式算式，程序重算 + 输入溯源。

    返回 (flags, 已通过验证的算式拼接文本)——后者供溯源闸豁免
    「算式输入与结果数字」。"""
    flags: list[dict] = []
    corpus_nums = extract_nums(_corpus_of(dossier, conclusion.id))
    checked_expressions = ""
    texts = [(conclusion.statement, "结论")] + [
        (ev.note, f"证据 {ev.id} 说明") for ev in dossier.evidences_of(conclusion.id)
    ]
    seen: set[str] = set()
    for text, where in texts:
        if not text:
            continue
        for expr_text, result, inputs, is_pct in _parse_expr(text):
            key = re.sub(r"\s+", "", expr_text)
            if key in seen:
                continue
            seen.add(key)
            lhs = re.split(r"[=＝]", expr_text, maxsplit=1)[0]
            got = _eval_expr(lhs)
            if got is None:
                continue  # 解析不了的不武断（交给溯源闸）
            if not _close(got, result.scaled):
                flags.append({
                    "kind": "calc", "severity": "high",
                    "conclusion_id": conclusion.id,
                    "value": expr_text,
                    "detail": f"{where}算式「{expr_text}」复算不符"
                              f"（程序得 {got:.4g}，声称 {result.raw}）",
                })
            else:
                missing = [n for n in inputs if not _traceable(n, corpus_nums)]
                if missing:
                    flags.append({
                        "kind": "calc", "severity": "high",
                        "conclusion_id": conclusion.id,
                        "value": expr_text,
                        "detail": f"{where}算式「{expr_text}」的输入数 "
                                  f"{'、'.join(n.raw for n in missing)}"
                                  " 在所引证据中定位不到",
                    })
                else:
                    # 只有完全通过的算式才豁免其输入/结果数字的溯源
                    checked_expressions += " " + expr_text
    return flags, checked_expressions


def _provenance_nums(statement: str, checked: str) -> list[Num]:
    """溯源对象数字：剥噪声、跳过计数量词/年份/序数/已验证算式。"""
    checked_zone = extract_nums(checked)
    out = []
    for n in extract_nums(statement):
        if any(abs(n.value - c.value) <= 1e-9 for c in checked_zone):
            continue  # 已验证算式的输入/结果
        tail = statement[n.end: n.end + 1]
        if tail and tail in _MEASURE_WORD:
            continue  # 计数断言（“4份文档”）留给计数 skill
        if statement[max(0, n.start - 1): n.start] == "第":
            continue  # 序数
        if n.unit == "" and re.fullmatch(r"(19|20)\d{2}", n.raw) \
                and statement[n.end: n.end + 1] == "年":
            continue  # 年份
        out.append(n)
    return out


def _value_in_corpus(num: Num, corpus: str) -> bool:
    """数字是否出现在材料中：同值命中（材料侧按其自身精度取整比对）。"""
    m = re.match(rf"({_NUM_TOKEN})", num.raw)
    decimals = (len(m.group(1).split(".")[1]) if "." in m.group(1) else 0)
    tolerance = 0.5 * (10 ** -decimals) + 1e-9
    return any(abs(c.value - num.value) <= tolerance for c in extract_nums(corpus))


def check_provenance(conclusion, dossier: Dossier, checked: str) -> list[dict]:
    """溯源闸：结论里的数字必须出自所引证据/段落/议题或已验证算式。"""
    corpus = _corpus_of(dossier, conclusion.id)
    flags: list[dict] = []
    seen: set[float] = set()
    for n in _provenance_nums(conclusion.statement, checked):
        if n.value in seen:
            continue
        seen.add(n.value)
        if not _value_in_corpus(n, corpus):
            flags.append({
                "kind": "provenance", "severity": "medium",
                "conclusion_id": conclusion.id,
                "value": n.raw,
                "detail": f"结论中的数字 {n.raw} 未出现在所引证据与段落中"
                          "（来源外数字）",
            })
    return flags


def audit_numeric(dossier: Dossier) -> list[dict]:
    """计算闸 + 溯源闸：遍历存活结论（merged 成员已冻结不再审）。"""
    flags: list[dict] = []
    for con in dossier.conclusions:
        if con.status == "merged":
            continue
        calc_flags, checked = check_calc(con, dossier)
        flags.extend(calc_flags)
        flags.extend(check_provenance(con, dossier, checked))
    return flags


# ---------------------------------------------------------------- 守恒闸


def audit_conservation(dossier: Dossier) -> list[dict]:
    """归并守恒闸：组结论的数字 ⊆ 成员结论 ∪ 组证据材料 ∪ 议题。"""
    members_of: dict[str, list] = {}
    for con in dossier.conclusions:
        if con.status == "merged" and con.group_id:
            members_of.setdefault(con.group_id, []).append(con)
    flags: list[dict] = []
    for con in dossier.conclusions:
        members = members_of.get(con.id)
        if not members:
            continue
        allowed = "\n".join(
            [m.statement for m in members]
            + [_corpus_of(dossier, con.id)])
        seen: set[float] = set()
        for n in _provenance_nums(con.statement, ""):
            if n.value in seen:
                continue
            seen.add(n.value)
            if not _value_in_corpus(n, allowed):
                flags.append({
                    "kind": "merge_conservation", "severity": "medium",
                    "conclusion_id": con.id,
                    "value": n.raw,
                    "detail": f"归并概括引入成员结论与证据之外的新数字 {n.raw}"
                              "（概括漂移警示）",
                })
    return flags
