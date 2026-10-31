"""R19：从问句抽对立选项＋事件框架键（时点×主体×定性）。

不依赖 leave/money/post 硬族。词表只含通用功能词／问句表面。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.kg_lab.case_lexicon import extract_actors_from_question

_TIME = re.compile(
    r"\d{4}\s*年|\d{1,2}\s*月\d{1,2}\s*日|\d{1,2}\s*时(?:\d{1,2}\s*分)?|"
    r"上午|下午|凌晨|当天|次日|何时|"
    r"\d+\s*年(?!月)"
)
# 是A还是B
_OR = re.compile(
    r"是(?P<a>[\u4e00-\u9fffA-Za-z0-9「」《》\"“\.·\-]{2,30}?)"
    r"还是(?P<b>[\u4e00-\u9fffA-Za-z0-9「」《》\"“\.·\-]{2,40})"
    r"(?=(?:[，,。？?\s]|哪|以|还是|$))"
)
# 以A为准…还是以B为准
_ZHUN = re.compile(
    r"以(?P<a>.{3,48}?)为准[，,\s]*还是以(?P<b>.{3,48}?)为准"
)
# 认定为A还是B
_RENDING = re.compile(
    r"(?:应)?认定为(?P<a>.{2,24}?)还是(?P<b>.{2,24}?)"
    r"(?=(?:[，,。？?\s]|以|哪|$))"
)
_QUOTES = re.compile(r"[「\"“]([^」\"”]{2,24})[」\"”]")
_QUAL = (
    "认定", "证实", "确认", "是否", "能否", "原因", "为何", "导致", "责任",
    "口径", "官方", "通报", "声明", "宣布", "调查", "结论", "数据", "伤亡",
    "提议", "对话", "沟通", "适用", "范围", "原话", "原文", "采访",
    "编制", "岗位", "在编", "档案",
)
_EVID = (
    "通报", "声明", "证实", "数据显示", "记者", "发布会", "调查报告",
    "全文", "原话", "视频", "访谈", "官方", "新闻稿", "监控", "人事档案",
)
_SCOPE = (
    "适用范围", "本埠", "全国", "当地", "境内", "口岸", "双边", "双方",
    "仅限", "不适用于", "属地",
)

# 选项表面 → 可迁移近义检索词（非案情硬族）
_OPT_PARAPHRASE_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"不愿走|不想走"), ("不愿走", "不想走", "没让我走", "想走")),
    (re.compile(r"未放行|不放行|没放行"), ("未放行", "没让我走", "不放", "放行")),
    (re.compile(r"买断费"), ("买断费", "买断", "自主择业")),
    (re.compile(r"自主择业(?:经济补偿金)?"), ("自主择业经济补偿金", "自主择业", "经济补偿")),
    (re.compile(r"在编不在岗"), ("在编不在岗", "在编", "不在岗", "编制", "岗位")),
    (re.compile(r"泥石流"), ("泥石流", "洪灾", "山崩", "冰岩崩")),
    (re.compile(r"冰湖溃决|冰川断裂"), ("冰湖溃决", "冰川断裂", "冰岩崩")),
)


def _clean_option(s: str) -> str:
    s = (s or "").strip(" ，,。？?、；;：:\"'「」《》")
    for stop in ("，", ",", "？", "?", "哪一", "哪方", "以哪", "能否", "是否"):
        if stop in s:
            s = s.split(stop, 1)[0]
    s = s.strip()
    # 去掉前缀赘语
    for pref in ("应以", "应以官方通稿的", "应", "以官方通稿的", "以"):
        if s.startswith(pref) and len(s) - len(pref) >= 4:
            s = s[len(pref):]
            break
    return s.strip()[:36]


def extract_options(question: str) -> list[str]:
    q = question or ""
    out: list[str] = []

    m = _ZHUN.search(q)
    if m:
        a, b = _clean_option(m.group("a")), _clean_option(m.group("b"))
        if a:
            out.append(a)
        if b and b != a:
            out.append(b)

    if len(out) < 2:
        m = _RENDING.search(q)
        if m:
            a, b = _clean_option(m.group("a")), _clean_option(m.group("b"))
            if a and b and a != b:
                out = [a, b]

    if len(out) < 2:
        m = _OR.search(q)
        if m:
            a, b = _clean_option(m.group("a")), _clean_option(m.group("b"))
            out = []
            if a:
                out.append(a)
            if b and b != a:
                out.append(b)

    if len(out) < 2 and "还是" in q:
        left, right = q.split("还是", 1)
        b = _clean_option(right)
        # 取还是左侧末段（避开整句粘连）
        tail = re.split(r"[，,；;]", left)[-1]
        a = _clean_option(tail)
        # 若左侧太长，截到末 24 字内的主张尾巴
        if len(a) > 24:
            frag = re.findall(r"[\u4e00-\u9fffA-Za-z0-9时分许]{2,24}", a)
            a = ""
            for cand in reversed(frag):
                if any(cand.endswith(s) for s in ("费", "金", "走", "岗", "制", "案", "道", "准", "分")):
                    a = cand
                    break
            if not a and frag:
                a = frag[-1]
        if a and b and a != b:
            out = [_clean_option(a), b]

    # 引号内主张也作选项／检索键
    for qm in _QUOTES.finditer(q):
        frag = _clean_option(qm.group(1))
        if frag and frag not in out and 2 <= len(frag) <= 24:
            out.append(frag)

    # 「称其X」裸主张（截到能否／是否／标点）
    for m in re.finditer(
        r"称其(?P<c>[\u4e00-\u9fff]{2,12}?)(?=能否|是否|，|。|？|\s|$)",
        q,
    ):
        frag = _clean_option(m.group("c"))
        if frag and frag not in out:
            out.append(frag)

    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x not in seen and 2 <= len(x) <= 36:
            seen.add(x)
            uniq.append(x)
    return uniq[:6]


def option_paraphrases(opt: str) -> list[str]:
    """可迁移近义扩展，供检索视图用。"""
    s = (opt or "").strip()
    if not s:
        return []
    out: list[str] = [s]
    for pat, alts in _OPT_PARAPHRASE_RULES:
        if pat.search(s):
            out.extend(alts)
    if "不愿" in s:
        out.append(s.replace("不愿", "不想"))
    if "未" in s:
        out.append(s.replace("未", "没"))
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        x = x.strip()
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq[:8]


@dataclass
class EventFrame:
    actors: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    time_cues: list[str] = field(default_factory=list)
    qual_predicates: list[str] = field(default_factory=list)
    evidence_cues: list[str] = field(default_factory=list)
    scope_cues: list[str] = field(default_factory=list)
    question_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_event_frame(question: str) -> EventFrame:
    q = question or ""
    actors = extract_actors_from_question(q)
    options = extract_options(q)
    times = [m.group(0).replace(" ", "") for m in _TIME.finditer(q)]
    time_cues: list[str] = []
    for t in times:
        if t not in time_cues:
            time_cues.append(t)
    quals = [w for w in _QUAL if w in q]
    evid = [w for w in _EVID if w in q]
    scope = [w for w in _SCOPE if w in q]
    # 较稳的 2～8 字片段作检索词（避开整句粘连）
    terms = re.findall(
        r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{3,}|[\d时分]{2,12}",
        q,
    )
    reserved = set(actors) | set(options) | set(quals)
    q_terms: list[str] = []
    for t in terms:
        if t in reserved:
            continue
        if t in {"哪一方", "是否真", "能不能", "这句话", "还是", "应以"}:
            continue
        if t not in q_terms:
            q_terms.append(t)
        if len(q_terms) >= 12:
            break
    return EventFrame(
        actors=actors,
        options=options,
        time_cues=time_cues[:8],
        qual_predicates=quals,
        evidence_cues=evid,
        scope_cues=scope,
        question_terms=q_terms,
    )


def frame_align_score(text: str, frame: EventFrame, *, title: str = "") -> float:
    blob = (title or "") + "\n" + (text or "")
    if not blob.strip():
        return 0.0
    parts: list[float] = []

    def _hit_rate(keys: list[str]) -> float | None:
        if not keys:
            return None
        return sum(1 for k in keys if k and k in blob) / len(keys)

    # 选项用近义扩展后计命中
    opt_keys: list[str] = []
    for opt in frame.options:
        opt_keys.extend(option_paraphrases(opt)[:3])
    for keys in (frame.actors, opt_keys or frame.options, frame.time_cues, frame.qual_predicates):
        r = _hit_rate(keys)
        if r is not None:
            parts.append(r)
    if frame.question_terms:
        r = _hit_rate(frame.question_terms[:8])
        if r is not None:
            parts.append(0.5 * r)
    if not parts:
        return 0.0
    return round(sum(parts) / len(parts), 4)


def option_side(text: str, frame: EventFrame) -> str:
    if len(frame.options) < 2:
        return ""
    a, b = frame.options[0], frame.options[1]
    body = text or ""
    keys_a = option_paraphrases(a)
    keys_b = option_paraphrases(b)
    ha = any(k in body for k in keys_a)
    hb = any(k in body for k in keys_b)
    if ha and not hb:
        return "option_a"
    if hb and not ha:
        return "option_b"
    if ha and hb:
        return "both"
    return "neither"
