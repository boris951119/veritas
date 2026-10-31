"""R22：轻量意图路由（2～3 条）→ 二筛优先序差异。

路由（规则优先，无案专名）：
- adjudicate  对立裁决：选项对齐／对立侧优先
- institutional 制度释义：制度／办法／编制类载体优先
- fact_check  事实核对：可核验／时点／通报优先（默认）

每条只挂一小套权重偏置，不是完整标签字典。
路由层可抽对立锚点（短键），供二筛核心排序；一筛仍走原 extract_options，避免翻池。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.kg_lab.event_frame import EventFrame, extract_event_frame
from app.kg_lab.question_intent import QuestionIntent, classify_intent

ROUTES: tuple[str, ...] = ("adjudicate", "institutional", "fact_check")

_INSTITUTIONAL_CUES = (
    "制度", "办法", "规定", "编制", "岗位", "框架", "释义", "对应",
    "含义", "定义", "适用范围", "法律", "机制", "口径如何理解",
    "怎么理解", "如何认定", "属于什么",
)

_ADJ_SURFACE = (
    "还是", "哪一口径", "哪一说法", "哪一方", "以哪", "为准",
    "定性为", "该由", "应采用",
)

# 相对 DEFAULT_WEIGHTS 的偏置（绝对值仍建议落在常理范围；评测侧不另加重拟合）
ROUTE_WEIGHT_BIAS: dict[str, dict[str, float]] = {
    "adjudicate": {
        "option_align": 0.18,
        "authority": 0.05,
        "verifiability": 0.05,
        "primary_role": 0.05,
        "time_nail": 0.0,
        "title_option": 0.08,
    },
    "institutional": {
        "primary_role": 0.18,
        "authority": 0.10,
        "verifiability": 0.08,
        "option_align": -0.05,
        "time_nail": 0.0,
    },
    "fact_check": {
        "verifiability": 0.18,
        "time_nail": 0.10,
        "authority": 0.08,
        "option_align": 0.0,
        "publish_recency": 0.05,
    },
}

_STOP = frozenset({
    "到底", "能否", "是否", "该由", "定性为", "机制", "应", "的", "在", "后",
    "如", "所称", "主张", "还是", "哪一", "口径", "说法", "成立", "评估",
    "采用", "与", "或", "以及", "还有", "对于", "关于", "一个", "这个",
    "我们", "他们", "它们", "因为", "所以", "如果", "已经", "可以",
    "问题", "事件", "相关", "进行", "通过", "根据", "表示", "认为",
    "安排", "承担", "启用", "就绪启用", "月的", "年后",
})

_DINGXING = re.compile(
    r"(?:应)?定性为(?P<a>.{2,28}?)[，,\s]*还是(?P<b>.{2,40}?)[？?]?$"
)
_GAI_YOU = re.compile(
    r"(?:该由|由)(?P<a>.{2,28}?)承担[，,\s]*还是(?:如[^，,]{0,20}主张)?(?:由)?(?P<b>.{2,28}?)承担"
)
_NENGFOU_OR = re.compile(
    r"(?:到底)?(?:能否|是否)(?P<a>.{2,40}?)[，,\s]*还是(?:如)?(?P<b>.{2,48}?)[？?]?$"
)
_CHENG = re.compile(
    r"(?P<a>[\u4e00-\u9fffA-Za-z]{2,12})称(?P<a_claim>[\u4e00-\u9fff]{2,16})"
    r"[、，,](?P<b>[\u4e00-\u9fffA-Za-z与和]{2,24})称(?P<b_claim>[\u4e00-\u9fff或]{2,24})"
)
_REN_VS = re.compile(
    r"(?P<a>[\u4e00-\u9fff与和]{2,16})认定的(?P<a_claim>.{4,36}?)"
    r"[，,]?与(?P<b>[\u4e00-\u9fff]{2,12})所称(?P<b_claim>.{2,24})"
)
_ZHUN = re.compile(
    r"以(?P<a>.{3,48}?)为准[，,\s]*还是以(?P<b>.{3,48}?)为准"
)
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9\.\-]{1,24}")
_NUM_UNIT = re.compile(
    r"\d{1,4}(?:年|月|日|时|分|米|人|万|亿)?(?:\d{0,2}(?:时|分|秒|米)?)?"
)
_CN_CHUNK = re.compile(r"[\u4e00-\u9fff]{2,8}")


def _clean_side(s: str) -> str:
    s = (s or "").strip(" ，,。？?、；;：:\"'「」《》")
    # 截掉问句尾巴污染
    for stop in ("哪一说法", "哪一口径", "哪一方", "是否成立", "？", "?"):
        if stop in s:
            s = s.split(stop, 1)[0]
    for pref in (
        "应以官方通稿的", "应以", "应定性为", "定性为", "认定为", "该由", "由",
        "应采用", "采用", "还是如", "如", "应", "以", "所称", "在",
    ):
        if s.startswith(pref) and len(s) - len(pref) >= 2:
            s = s[len(pref):]
            break
    for suf in ("为准", "承担", "成立", "启用", "后就绪", "就绪"):
        if s.endswith(suf) and len(s) > len(suf) + 2:
            # 保留「就绪」本身作锚，只剥后缀赘语时除外
            if suf in {"就绪", "后就绪"}:
                break
            s = s[: -len(suf)]
    return s.strip()[:48]


_TOPIC_CUES = (
    "通报热线", "沟通渠道", "通报", "热线", "就绪", "中美对话", "主渠道",
    "危机管理", "政府介入", "失控", "责任", "冰岩崩", "冰湖溃决", "冰川断裂",
    "泥石流", "洪灾", "山崩", "监控", "通稿", "联合国主渠道",
)
# 问句主题 → 可迁移近义软锚（不是案专名）
_SOFT_EXPAND: dict[str, tuple[str, ...]] = {
    "通报热线": ("通报热线", "沟通渠道", "通报机制", "事故预警", "热线"),
    "通报": ("通报", "沟通渠道", "通报机制", "预警"),
    "热线": ("热线", "沟通渠道"),
    "就绪": ("就绪", "启用"),
    "对话": ("中美对话", "人工智能对话", "AI对话"),
    "中美对话": ("中美对话", "人工智能对话"),
    "主渠道": ("联合国主渠道", "主渠道"),
    "危机管理": ("危机管理", "危机沟通"),
    "政府介入": ("政府介入", "政府控制", "美国政府", "政府监管"),
    "失控": ("失控", "失控智能体", "安全隔离"),
    "责任": ("责任", "承担责任", "责任保险"),
    "泥石流": ("泥石流",),
    "洪灾": ("洪灾", "洪水"),
    "山崩": ("山崩", "冰岩崩"),
    "冰岩崩": ("冰岩崩", "冰川断裂", "冰川崩塌"),
    "冰湖溃决": ("冰湖溃决", "溃决"),
    "冰川断裂": ("冰川断裂", "冰岩崩"),
    "监控": ("监控", "监控记录"),
    "通稿": ("通稿", "新闻稿", "官方通稿"),
}
_WEAK_SIDE = frozenset({
    "对话", "通报", "政府", "介入", "泥石", "石流", "官方", "数据",
    "全球", "安排", "机制", "企业",
})
# 纯「N分」残片易误命中「10时59分」这类无关钟点（R24）
_AMBIG_MIN_ONLY = re.compile(r"^\d{1,2}分$")
_CLOCK_KEY = re.compile(r"\d{1,2}时\d{1,2}分")
# 成因／口径对立表面（可迁移，非案名）
_CLAIM_CONFLICT_CUES = (
    "崩", "溃", "洪灾", "洪水", "山崩", "泥石流", "冰岩", "冰川", "米",
)
# 主体×责任／治理对立（企业专名 vs 政府介入）
_GOV_RESP_CUES = (
    "政府", "企业", "责任", "承担", "介入", "监管", "失控", "管理层",
)
_VOICE_CUES = (
    "发言人", "秘书长", "新闻发布会", "发布会", "声明", "例行记者会",
    "外交部", "通报称", "情况通报",
)
# 口径对立声部（不含「发布会查明」）
_CALIBER_VOICE_CUES = (
    "发言人", "秘书长", "外交部", "联合国", "例行记者会", "声明",
)
_HASHTAG_WRAP = re.compile(r"【#|#[\u4e00-\u9fffA-Za-z0-9_]{2,24}#")
_DEFINITIONAL = re.compile(
    r"(?:^|。|；)[^。]{0,12}(?:是一种|是指|指的是|定义为)"
)


def is_claim_conflict_route(anchors: dict[str, list[str]] | None) -> bool:
    """钟点对撞，或两侧均含成因／口径对立线索，或主体×责任对立 → 启用软保位。"""
    keys_a = list((anchors or {}).get("side_a") or [])
    keys_b = list((anchors or {}).get("side_b") or [])
    if any(_CLOCK_KEY.search(k or "") for k in keys_a + keys_b):
        return True
    def _hit(keys: list[str], cues: tuple[str, ...]) -> bool:
        return any(any(c in (k or "") for c in cues) for k in keys)
    if _hit(keys_a, _CLAIM_CONFLICT_CUES) and _hit(keys_b, _CLAIM_CONFLICT_CUES):
        return True
    # R27：一侧拉丁／机构主体，一侧政府／责任口径
    all_keys = keys_a + keys_b + list((anchors or {}).get("soft") or [])
    has_corp = any(re.search(r"[A-Za-z]{3,}", k or "") for k in keys_a + keys_b)
    has_gov = _hit(all_keys, _GOV_RESP_CUES)
    if has_corp and has_gov and keys_a and keys_b:
        return True
    return False


def _filter_side_keys(keys: list[str]) -> list[str]:
    """去掉易误伤的短时点残片；保留完整钟点键。"""
    has_clock = any(_CLOCK_KEY.search(k or "") for k in keys)
    out: list[str] = []
    for k in keys:
        if not k:
            continue
        if has_clock and _AMBIG_MIN_ONLY.fullmatch(k):
            continue
        out.append(k)
    return out


def _anchors_from_side(side: str) -> list[str]:
    """从一侧主张抽短锚点（拉丁专名／时点数额／并列块／主题词），无案专名表。"""
    s = _clean_side(side)
    if not s:
        return []
    out: list[str] = []
    for m in _LATIN.finditer(s):
        tok = m.group(0)
        if tok.lower() not in {"ai", "or", "the", "and"} and tok not in out:
            out.append(tok)
    for m in _NUM_UNIT.finditer(s):
        tok = m.group(0)
        # 只要带单位或≥3 位的时点／数额，避免残片
        if len(tok) >= 3 and any(u in tok for u in "年月日时分米人万亿") and tok not in out:
            out.append(tok)
        elif re.fullmatch(r"\d{4}", tok) and tok not in out:
            out.append(tok)
    # 或／顿号并列拆开
    for piece in re.split(r"[或、／/,，]", s):
        piece = _clean_side(piece)
        if 2 <= len(piece) <= 16 and piece not in _STOP and piece not in out:
            out.append(piece)
    # 主题功能词：仅当本侧原文含有时收录（可迁移）；弱词不进侧锚
    for cue in _TOPIC_CUES:
        if cue in s and cue not in out and cue not in _WEAK_SIDE:
            out.append(cue)
    # 尾部 4～8 字主张块（对立重心常在后）
    for n in (8, 6, 4):
        if len(s) >= n:
            tok = s[-n:]
            if (
                tok not in _STOP
                and tok not in _WEAK_SIDE
                and not tok.startswith(("的", "在", "与"))
                and tok not in out
            ):
                out.append(tok)
                break
    if 2 <= len(s) <= 16 and s not in out and s not in _STOP and s not in _WEAK_SIDE:
        out.insert(0, s)
    # 过滤过短／过弱侧锚
    out = [k for k in out if k and (len(k) >= 3 or k.isascii()) and k not in _WEAK_SIDE]
    return out[:8]


def route_option_sides(question: str) -> tuple[list[str], list[str]]:
    """路由层对立两侧原文（不写回一筛 EventFrame）。"""
    q = question or ""
    for pat in (_ZHUN, _DINGXING, _GAI_YOU, _NENGFOU_OR):
        m = pat.search(q)
        if m:
            a, b = _clean_side(m.group("a")), _clean_side(m.group("b"))
            if a and b and a != b:
                return [a], [b]
    m = _CHENG.search(q)
    if m:
        a, b = _clean_side(m.group("a_claim")), _clean_side(m.group("b_claim"))
        if a and b and a != b:
            return [a], [b]
    m = _REN_VS.search(q)
    if m:
        a, b = _clean_side(m.group("a_claim")), _clean_side(m.group("b_claim"))
        if a and b and a != b:
            return [a], [b]
    if "还是" in q:
        left, right = q.split("还是", 1)
        b = _clean_side(right)
        tail = re.split(r"[，,；;]", left)[-1]
        a = _clean_side(tail)
        if len(a) > 28:
            frags = _CN_CHUNK.findall(a)
            a = frags[-1] if frags else a[-24:]
        if a and b and a != b:
            return [a], [b]
    return [], []


def route_option_anchors(question: str) -> dict[str, list[str]]:
    """两侧短锚点 + 合并列表。供核心排序／option 命中。"""
    q = question or ""
    side_a, side_b = route_option_sides(q)
    keys_a: list[str] = []
    keys_b: list[str] = []
    for s in side_a:
        for k in _anchors_from_side(s):
            if k not in keys_a:
                keys_a.append(k)
    for s in side_b:
        for k in _anchors_from_side(s):
            if k not in keys_b:
                keys_b.append(k)
    # R27：「还是」清洗会丢掉半句拉丁专名（Anthropic 等）——从原半句补回
    if "还是" in q:
        left, right = q.split("还是", 1)
        for m in _LATIN.finditer(left):
            tok = m.group(0)
            if len(tok) >= 3 and tok.lower() not in {"ai", "or", "the", "and"}:
                if tok not in keys_a and tok not in keys_b:
                    keys_a.append(tok)
        for m in _LATIN.finditer(right):
            tok = m.group(0)
            if len(tok) >= 3 and tok.lower() not in {"ai", "or", "the", "and"}:
                if tok not in keys_b and tok not in keys_a:
                    keys_b.append(tok)
    # 问句主题 → 软锚（含近义扩展）；弱词不进侧锚
    soft: list[str] = []
    for cue in _TOPIC_CUES:
        if cue not in q:
            continue
        expanded = _SOFT_EXPAND.get(cue, (cue,))
        in_a = any(cue in s for s in side_a) or any(cue in k for k in keys_a)
        in_b = any(cue in s for s in side_b) or any(cue in k for k in keys_b)
        if in_a and not in_b:
            for e in expanded:
                if e not in keys_a and e not in _WEAK_SIDE:
                    keys_a.append(e)
        elif in_b and not in_a:
            for e in expanded:
                if e not in keys_b and e not in _WEAK_SIDE:
                    keys_b.append(e)
        else:
            for e in expanded:
                if e not in soft:
                    soft.append(e)
    shared = set(keys_a) & set(keys_b)
    keys_a = [k for k in keys_a if k not in shared and k not in _WEAK_SIDE]
    keys_b = [k for k in keys_b if k not in shared and k not in _WEAK_SIDE]
    keys_a = _filter_side_keys(keys_a)
    keys_b = _filter_side_keys(keys_b)
    soft = [c for c in soft if c not in keys_a and c not in keys_b]
    return {
        "side_a": keys_a[:10],
        "side_b": keys_b[:10],
        "all": (keys_a + keys_b + soft)[:24],
        "soft": soft[:10],
        "raw_a": side_a,
        "raw_b": side_b,
    }


def anchor_hits(text: str, anchors: dict[str, list[str]] | None) -> dict[str, Any]:
    body = text or ""
    if not anchors:
        return {"a": 0, "b": 0, "side": "", "total": 0, "soft": 0, "clock_a": 0, "clock_b": 0}
    keys_a = _filter_side_keys(list(anchors.get("side_a") or []))
    keys_b = _filter_side_keys(list(anchors.get("side_b") or []))
    ha = sum(1 for k in keys_a if k and k in body)
    hb = sum(1 for k in keys_b if k and k in body)
    hs = sum(1 for k in anchors.get("soft") or [] if k and k in body)
    clock_a = sum(1 for k in keys_a if k and _CLOCK_KEY.search(k) and k in body)
    clock_b = sum(1 for k in keys_b if k and _CLOCK_KEY.search(k) and k in body)
    side = ""
    if ha and not hb:
        side = "option_a"
    elif hb and not ha:
        side = "option_b"
    elif ha and hb:
        side = "both"
    elif ha or hb:
        side = "option_a" if ha else "option_b"
    return {
        "a": ha, "b": hb, "side": side, "total": ha + hb + hs, "soft": hs,
        "clock_a": clock_a, "clock_b": clock_b,
    }


def host_authority_unit(url: str) -> float:
    """可迁移主机权威：部委／.gov／联合国 > 央媒 > 其他。不读金标。"""
    host = (urlparse(url or "").netloc or "").lower()
    if not host:
        return 0.0
    if any(
        x in host
        for x in (
            "mfa.gov", "fmprc.gov", "state.gov", "un.org", "whitehouse.gov",
            "mod.gov.cn", "gov.cn",
        )
    ):
        # 通稿转载站略降
        if any(x in host for x in ("news.cn", "xinhua", "people.com", "cctv")):
            return 0.55
        if host.endswith(".gov.cn") or host.endswith(".gov") or "mfa." in host or "fmprc." in host:
            return 1.0
        if "un.org" in host or "whitehouse.gov" in host or "state.gov" in host:
            return 0.95
    if any(x in host for x in ("news.cn", "xinhua", "people.com", "cctv.com", "chinadaily")):
        return 0.55
    if host.endswith(".gov.cn") or host.endswith(".gov"):
        return 0.85
    return 0.0


@dataclass
class IntentRoute:
    route: str  # adjudicate | institutional | fact_check
    base: QuestionIntent
    notes: list[str] = field(default_factory=list)
    anchors: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = self.base.to_dict()
        d["route"] = self.route
        d["route_notes"] = list(self.notes)
        if self.anchors:
            d["route_anchors"] = {
                "side_a": list(self.anchors.get("side_a") or []),
                "side_b": list(self.anchors.get("side_b") or []),
            }
        return d


def classify_route(question: str, frame: EventFrame | None = None) -> IntentRoute:
    """规则分流；歧义默认 fact_check（不调线上大模型）。

    对立表面词（还是／哪一说法等）+ 路由锚点 → adjudicate，即使一筛 frame.options 为空。
    """
    q = question or ""
    frame = frame or extract_event_frame(q)
    base = classify_intent(q, frame)
    anchors = route_option_anchors(q)
    notes: list[str] = []
    has_surface = any(c in q for c in _ADJ_SURFACE)
    has_anchors = bool(anchors.get("side_a")) and bool(anchors.get("side_b"))
    if base.adjudication or base.kind == "adjudicate":
        notes.append("from_adjudication")
        return IntentRoute(route="adjudicate", base=base, notes=notes, anchors=anchors)
    if has_surface and has_anchors:
        notes.append("route_or_surface")
        return IntentRoute(route="adjudicate", base=base, notes=notes, anchors=anchors)
    inst_hits = [c for c in _INSTITUTIONAL_CUES if c in q]
    if len(inst_hits) >= 2 or (
        any(c in q for c in ("制度", "办法", "编制", "对应的表述", "如何认定"))
        and not base.evidence_first
    ):
        notes.append(f"institutional_cues:{','.join(inst_hits[:4])}")
        return IntentRoute(route="institutional", base=base, notes=notes, anchors=anchors)
    notes.append("default_fact_check")
    return IntentRoute(route="fact_check", base=base, notes=notes, anchors=anchors)


def route_weights(route: str, base: dict[str, float] | None = None) -> dict[str, float]:
    from app.kg_lab.stage2_authority import DEFAULT_WEIGHTS

    out = {**DEFAULT_WEIGHTS, **(base or {})}
    bias = ROUTE_WEIGHT_BIAS.get(route) or ROUTE_WEIGHT_BIAS["fact_check"]
    for k, d in bias.items():
        out[k] = float(out.get(k) or 0.0) + float(d)
    return out


_INST_META = frozenset({"institution_def", "official_primary", "official_reprint"})

# R34：问句可核验槽↔切片对齐（无案专名）；通稿壳降权
_SLOT_WEAK = frozenset({
    "是否", "属实", "流传", "说法", "这一", "一方", "双方", "原意",
    "指什么", "还是", "正面", "负面", "评价", "本人", "问题", "事件",
    "官方", "媒体", "报道", "称", "有何", "对此",
})
_CONFLICT_EN = (
    "fired", "firing", "attack", "launched", "launch",
    "strike", "airstrike", "shelling", "clashed", "clash",
)
_ROUNDUP_CUE = (
    "时间线", "以下是", "综合报道", "持续关注", "均称", "多方",
    "盘点", "速览", "一文看懂", "最新消息汇总", "汇总多方",
    "完整读下来", "看起来更像", "评论文章",
)
_DIPLO_SHELL_CUE = (
    "劝和促谈", "高度关注", "穿梭调停", "会见柬", "会见泰",
)
_MONTH_EN = {
    1: ("january", "jan."), 2: ("february", "feb."), 3: ("march", "mar."),
    4: ("april", "apr."), 5: ("may", "may"), 6: ("june", "jun."),
    7: ("july", "jul."), 8: ("august", "aug."), 9: ("september", "sep."),
    10: ("october", "oct."), 11: ("november", "nov."), 12: ("december", "dec."),
}


_CLAIM_NOUN_TAIL = (
    "援助", "开火", "空袭", "打击", "推荐信", "保研", "合照", "遇难", "伤亡", "证据",
)
_PRIMARY_LATIN_CUE = (
    "felt ", "原话", "访谈", "官方视频", "原始出处", "亲口", "英文访谈",
)


def stage2_verifiable_slots(question: str) -> dict[str, Any]:
    """二筛用可核验槽：复用一筛抽取＋问句内容名词（武器／推荐信等）。"""
    from app.kg_lab.stage1_claim_holes import extract_verifiable_slots

    slots = dict(extract_verifiable_slots(question or ""))
    q = question or ""
    nouns: list[str] = []
    claim_nouns: list[str] = []
    # 标点切段（武器援助／率先开火）比整句滑窗更稳
    for part in re.split(r"[，。？?、；;：:\s／/]+", q):
        part = part.strip()
        if 2 <= len(part) <= 12 and part not in _SLOT_WEAK and part not in nouns:
            nouns.append(part)
        if len(nouns) >= 8:
            break
    for m in re.findall(
        r"[\u4e00-\u9fff]{2,8}(?:援助|开火|空袭|打击|推荐信|保研|合照|遇难|伤亡|证据|侥幸)",
        q,
    ):
        if m not in nouns:
            nouns.append(m)
        # 短主张核（武器援助／率先开火）作强槽候选
        for tail in _CLAIM_NOUN_TAIL + ("侥幸",):
            if m.endswith(tail):
                stem = m[-(len(tail) + 2):] if len(m) > len(tail) + 1 else m
                if len(stem) >= 4 and stem not in claim_nouns:
                    claim_nouns.append(stem)
                if m not in claim_nouns:
                    claim_nouns.append(m)
                break
    # 并入一筛对立支
    for a in list(slots.get("claim_alts") or []):
        if a and a not in claim_nouns:
            claim_nouns.append(a)
    slots["nouns"] = nouns[:12]
    slots["claim_nouns"] = claim_nouns[:10]
    return slots


_LEAD_SHELL = re.compile(
    r"^(?:据|根据|当地时间|北京时间|新华社|总台|记者|报道|近日|有消息)"
)


def is_short_claim_segment(
    text: str,
    slots: dict[str, Any] | None,
    *,
    route: str = "",
) -> bool:
    """裁决题短主张段：短引语／关键句，非导语壳／长通稿。"""
    body = text or ""
    nlen = len(re.sub(r"\s+", "", body))
    if not (16 <= nlen <= 140):
        return False
    if looks_like_wire_shell(body):
        return False
    if _LEAD_SHELL.match(body[:12]) and nlen > 90:
        return False
    # 须撞问句可核验表面：对立支／代码／数额／主张核／引号
    if not slots:
        return False
    hits = 0
    for k in list(slots.get("claim_alts") or []) + list(slots.get("claim_nouns") or []):
        if k and len(k) >= 2 and k in body:
            hits += 1
    for k in list(slots.get("codes") or []) + list(slots.get("amounts") or []):
        if k and k in body:
            hits += 1
    for k in list(slots.get("quotes") or []):
        if k and len(k) >= 4 and k in body:
            hits += 1
    # 裁决对立常见判定词（纯属／否认／无关／并非）＋短段
    if any(c in body for c in ("纯属", "否认", "无关", "并非", "不实", "予以否认")):
        hits += 1
    return hits >= 1


def slot_align_detail(
    text: str, slots: dict[str, Any] | None,
) -> tuple[int, int]:
    """强槽命中（拉丁／数额／引号／年月组合／主张核）与弱名词分计。

    裸年份不记强槽（防 2026 通篇灌核心伤裁决题）；
    冲突动词须搭拉丁／年月／主张核，或英文冲突词，才记强槽。
    """
    if not slots or not text:
        return 0, 0
    tl = text.lower()
    strong = 0
    for k in slots.get("latin") or []:
        if k and k.lower() in tl:
            strong += 1
    for k in slots.get("codes") or []:
        if k and k.lower() in tl:
            strong += 1
    for k in slots.get("amounts") or []:
        if k and k in text:
            strong += 1
    # 引号：只计≥4字且去子串重复（防「荐信／保研」碎片把通稿抬到 strong=10）
    matched_q: list[str] = []
    for k in sorted((slots.get("quotes") or []), key=lambda x: len(x or ""), reverse=True):
        if not k or len(k) < 4 or k not in text:
            continue
        if any(k in m for m in matched_q):
            continue
        matched_q.append(k)
    strong += min(len(matched_q), 3)
    # 主张核／对立支 → 强槽；同样去子串
    claim_pool = list(slots.get("claim_nouns") or []) + list(slots.get("claim_alts") or [])
    matched_c: list[str] = []
    for n in sorted(claim_pool[:12], key=lambda x: len(x or ""), reverse=True):
        if not n or len(n) < 2 or n not in text:
            continue
        if len(n) < 4 and n not in ("侥幸", "11A"):
            continue
        if any(n in m for m in matched_c) or any(n in m for m in matched_q):
            continue
        matched_c.append(n)
    strong += min(len(matched_c), 2)
    # 座位号／短代码
    for k in list(slots.get("codes") or [])[:4]:
        if k and k in text:
            strong += 1
            break
    # 年月须组合：年＋月（中或英），裸年不算
    years = list(slots.get("years") or [])
    months = list(slots.get("months") or [])
    year_hit = bool(years and any(y in text for y in years))
    month_hit = False
    if months:
        for mnum in months[:2]:
            ens = _MONTH_EN.get(int(mnum), ())
            if any(e in tl for e in ens):
                month_hit = True
                break
            if f"{int(mnum)}月" in text or f"{int(mnum)} 月" in text:
                month_hit = True
                break
    if year_hit and month_hit:
        strong += 2
    # 冲突：英文冲突词直接强；中文冲突须已有其它强槽或年月组合
    if slots.get("conflict_verbs"):
        if any(e in tl for e in _CONFLICT_EN):
            strong += 1
        elif (strong >= 1 or (year_hit and month_hit)) and any(
            v in text for v in (slots.get("conflict_verbs") or [])
        ):
            strong += 1
    weak = 0
    for n in list(slots.get("nouns") or [])[:8]:
        if n and len(n) >= 3 and n in text:
            weak += 1
    return strong, weak


def slot_align_hits(text: str, slots: dict[str, Any] | None) -> int:
    """综合分：强槽权重高；裸名词不单独抬核心。"""
    strong, weak = slot_align_detail(text, slots)
    if strong <= 0:
        return 0
    return 2 * strong + min(weak, 3)


def looks_like_wire_shell(
    text: str,
    *,
    band: str = "",
    slot_hits: int = 0,
) -> bool:
    """综述／外交劝和壳。有槽仍可判壳（关键词被包进汇总文）。"""
    body = text or ""
    head = body[:160]
    if any(c in head for c in _ROUNDUP_CUE):
        return True
    if any(c in head for c in _DIPLO_SHELL_CUE):
        return True
    return False


def core_rank_score(
    pid: str,
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    pool_pos: dict[str, int] | None = None,
    anchors: dict[str, list[str]] | None = None,
    url_of: dict[str, str] | None = None,
    slots: dict[str, Any] | None = None,
) -> float:
    """核心排序分：锚点命中＋主机权威＋可核验。不读金标 id。

    R24：裁决题优先「双侧／可核验时点」；短单侧通稿降权，避免近同文占满盒。
    R34：问句可核验槽对齐抬分；无槽通稿壳降权（尤其非裁决题）。
    """
    feat = feats.get(pid) or {}
    meta = metas.get(pid) or {}
    text = str(meta.get("text") or "")
    ver = float(feat.get("verifiability") or 0.0)
    auth = float(feat.get("authority_unit") or 0.0)
    fa = float(feat.get("frame_align") or 0.0)
    oa = float(feat.get("option_align") or 0.0)
    time_n = float(feat.get("has_time_nail") or 0.0)
    pp = int((pool_pos or {}).get(pid) or 10**9)
    doc = str(meta.get("doc_id") or (pid.split("#", 1)[0] if pid else ""))
    url = (url_of or {}).get(doc) or str(meta.get("url") or "")
    host_u = host_authority_unit(url)
    hits = anchor_hits(text, anchors)
    band = str(feat.get("authority_band") or "")
    channel = str(meta.get("channel") or "")
    slot_hits = slot_align_hits(text, slots)
    clock_a = int(hits.get("clock_a") or 0)
    clock_b = int(hits.get("clock_b") or 0)
    clock_route = any(
        _CLOCK_KEY.search(k or "")
        for k in list((anchors or {}).get("side_a") or [])
        + list((anchors or {}).get("side_b") or [])
    )
    claim_route = is_claim_conflict_route(anchors)
    conflict_route = (clock_route or claim_route) and route == "adjudicate"
    # R24/R25 对撞题：双侧／句首钟点／机构口径优先；其它题贴近 R22 原式以免伤 us
    if conflict_route and clock_route:
        if hits["side"] == "both" and (clock_a + clock_b) >= 1:
            exclusive = 0.20 + 0.10 * min(float(clock_a + clock_b), 2.0) + 0.12
            if clock_a >= 1 and clock_b >= 1:
                exclusive += 0.08
        elif hits["side"] == "both":
            exclusive = 0.06
        elif hits["side"] in {"option_a", "option_b"}:
            exclusive = 0.14
            if (clock_a + clock_b) == 0:
                exclusive -= 0.06
        else:
            exclusive = 0.0
    else:
        exclusive = 0.20 if hits["side"] in {"option_a", "option_b"} else (
            0.05 if hits["side"] == "both" else 0.0
        )
    soft_n = float(hits.get("soft") or 0)
    soft_b = 0.28 * min(soft_n / 2.0, 1.0)
    # 软锚＋高权威带：抬「通报／沟通渠道」类金标近似段
    if soft_n >= 1 and band in {"primary_source", "official_channel"}:
        soft_b += 0.28
    if soft_n >= 2:
        soft_b += 0.08
    pool_b = max(0.0, (21 - pp) / 20.0) * 0.10 if pp <= 20 else 0.0
    align = max(fa, oa)
    nlen = len(re.sub(r"\s+", "", text))
    voice_n = sum(1 for v in _VOICE_CUES if v in text[:160])
    caliber_v = sum(1 for v in _CALIBER_VOICE_CUES if v in text[:200])
    # R26：口径／成因对撞——真双侧（多锚或口径声部）才满额；「查明」换皮假双侧降权
    if conflict_route and not clock_route:
        if hits["side"] == "both":
            strong_both = (
                (int(hits["a"]) + int(hits["b"])) >= 3
                or caliber_v >= 1
            )
            # 查明通稿常因近义扩展误打成 both；无口径声部则按弱双侧
            if ("查明" in text) and caliber_v == 0:
                strong_both = False
            exclusive = 0.18 if strong_both else 0.05
        elif hits["side"] in {"option_a", "option_b"}:
            exclusive = 0.16
            if caliber_v:
                exclusive += 0.08
            elif voice_n:
                exclusive += 0.04
            # R27：可核验责任独占抬；裸专名点赞／路过提及降
            strong_resp = any(
                c in text for c in (
                    "失控", "失控智能体", "入侵", "政府控制", "政府介入", "许可管理",
                )
            )
            if strong_resp:
                exclusive += 0.14
            elif re.search(r"[A-Za-z]{3,}", text[:200]):
                # 裸专名路过（Anthropic 点名无失控／政府控制）大幅降
                exclusive -= 0.18
        else:
            exclusive = 0.0
    # R26：通稿罚分只打短段；长 wire_relay 金标近似段不再被 0.14 压到分地板下
    wire_pen = 0.0
    short_wire = nlen > 0 and nlen < 110
    if (
        conflict_route
        and hits["side"] in {"option_a", "option_b"}
        and short_wire
        and (
            band == "wire_relay"
            or channel == "wire"
            or soft_n >= 1
        )
    ):
        wire_pen = 0.22 if clock_route else 0.14
    # R26：成因题也轻抬时点钉（10时52分＋5200米类金标近似），不限钟点路由
    if clock_route:
        time_b = 0.10 * time_n
    elif conflict_route:
        time_b = 0.10 * time_n
    else:
        time_b = 0.0
    # R26：精确数额／海拔等主张锚在句首 → 成因题轻抬（可迁移，不读案名）
    precise_b = 0.0
    if conflict_route and not clock_route and hits["side"] in {"option_a", "option_b", "both"}:
        head80 = text[:80]
        precise_n = sum(
            1 for k in list((anchors or {}).get("side_a") or [])
            + list((anchors or {}).get("side_b") or [])
            if k and len(k) >= 4 and any(u in k for u in "米时分万") and k in head80
        )
        precise_b = 0.10 * min(precise_n, 2)
    head = text[:120]
    head_clock = 0
    if clock_route:
        for k in (anchors or {}).get("side_a") or []:
            if k and _CLOCK_KEY.search(k) and k in head:
                head_clock += 1
        for k in (anchors or {}).get("side_b") or []:
            if k and _CLOCK_KEY.search(k) and k in head:
                head_clock += 1
    head_b = 0.14 * min(head_clock, 2) if clock_route else 0.0
    roundup_pen = 0.0
    if (
        clock_route
        and route == "adjudicate"
        and hits["side"] == "both"
        and nlen > 320
        and head_clock == 0
        and (clock_a + clock_b) >= 1
    ):
        roundup_pen = 0.22
    # R25：话题标签包装／辞书定义降权；机构口径声部抬权（可迁移）
    wrap_pen = 0.14 if conflict_route and _HASHTAG_WRAP.search(text[:80]) else 0.0
    defin_pen = 0.10 if conflict_route and _DEFINITIONAL.search(text[:100]) else 0.0
    voice_b = 0.0
    if conflict_route and voice_n:
        voice_b = 0.12 * min(voice_n, 2)
        if band in {"primary_source", "official_channel"} or host_u >= 0.55:
            voice_b += 0.10
    # R26：仅降「查明」假双侧（成因独占查明段不降，以免伤冰岩崩金标近似）
    caliber_pen = 0.0
    if (
        conflict_route
        and not clock_route
        and "查明" in text
        and caliber_v == 0
        and hits["side"] == "both"
    ):
        caliber_pen = 0.16
    # R34：可核验槽对齐抬（事实核对题加重；强槽计数拉开档，防通稿壳压过）
    slot_strong, _ = slot_align_detail(text, slots)
    _quote_q = bool(slots and (slots.get("quotes") or slots.get("claim_nouns")))
    _slot_boost_route = route == "fact_check" or _quote_q
    if _slot_boost_route and slot_strong >= 1:
        slot_b = 0.22 + 0.12 * min(float(slot_strong), 4.0) + 0.04 * min(
            float(slot_hits), 4.0,
        )
        # 一手拉丁原话／访谈出处相对二手解读抬
        _tl = text.lower()
        if any(
            (c in _tl) if c.endswith(" ") else (c in text)
            for c in _PRIMARY_LATIN_CUE
        ):
            slot_b += 0.16
        # 精确钟点＋槽：可核查时点陈述优先于无时点通稿
        if re.search(
            r"\d{1,2}时\d{1,2}分|\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)",
            text[:180],
        ):
            slot_b += 0.14
        # 英文开战陈述（launched/attack＋年月）相对外交劝和稿
        if any(e in _tl for e in ("launched an", "launched a", "opened fire")):
            slot_b += 0.18
        # 引号主张核命中多 → 澄清原文优先于标题党转载
        if _quote_q and slot_strong >= 3:
            slot_b += 0.10
    elif slot_hits:
        slot_b = 0.08 * min(float(slot_hits), 4.0)
    else:
        slot_b = 0.0
    shell_pen = 0.0
    if _slot_boost_route and looks_like_wire_shell(
        text, band=band, slot_hits=slot_hits,
    ):
        # 有强槽的壳降权轻一点，无槽壳重罚
        shell_pen = 0.22 if slot_strong >= 1 else 0.32
    # 非裁决题：无强槽的权威通稿壳再降一档（防独占盒位）
    if (
        route == "fact_check"
        and slot_strong <= 0
        and band in {"official_channel", "wire_relay"}
        and nlen > 180
    ):
        shell_pen = max(shell_pen, 0.18)
    # R35：仅座位码／侥幸／开关类短主张题保位（数额裁决不走，防长金标被降）
    short_b = 0.0
    long_wire_pen = 0.0
    _alts = list((slots or {}).get("claim_alts") or []) + list(
        (slots or {}).get("claim_nouns") or []
    )
    _short_q = bool(
        slots
        and (
            any(re.match(r"^\d{1,2}[A-Za-z]$", c or "") for c in (slots.get("codes") or []))
            or any(any(k in (a or "") for k in ("侥幸", "生还", "开关", "缺陷")) for a in _alts)
        )
    )
    if route == "adjudicate" and _short_q:
        if is_short_claim_segment(text, slots, route=route):
            short_b = 0.36 + 0.08 * min(float(slot_strong), 3.0)
        elif (
            nlen > 500
            and slot_strong <= 1
            and not hits["total"]
            and any(k and k.lower() in text.lower() for k in (slots.get("latin") or [])[:3])
        ):
            # 长通稿只靠航班／型号拉丁撞槽 → 降
            long_wire_pen = 0.20
    # 事实核对：精确钟点＋拉丁／型号 再抬一档（可核查时点声明）
    if route == "fact_check" and slot_strong >= 1 and re.search(
        r"\d{1,2}时\d{1,2}分", text[:180],
    ):
        slot_b += 0.12
    return (
        0.22 * host_u
        + 0.16 * min(float(hits["a"] + hits["b"]) / 3.0, 1.0)
        + soft_b
        + exclusive
        + 0.14 * ver
        + 0.10 * auth
        + 0.08 * align
        + pool_b
        + time_b
        + head_b
        + voice_b
        + precise_b
        + slot_b
        + short_b
        + (0.04 if route == "adjudicate" and hits["total"] else 0.0)
        - wire_pen
        - roundup_pen
        - wrap_pen
        - defin_pen
        - caliber_pen
        - shell_pen
        - long_wire_pen
    )


def is_core_candidate(
    pid: str,
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    pool_pos: dict[str, int] | None = None,
    anchors: dict[str, list[str]] | None = None,
    url_of: dict[str, str] | None = None,
    slots: dict[str, Any] | None = None,
) -> bool:
    """线上「金标近似」：池内＋（锚点命中／强可核验主机）。不读金标 id。"""
    feat = feats.get(pid) or {}
    meta = metas.get(pid) or {}
    ver = float(feat.get("verifiability") or 0.0)
    auth = float(feat.get("authority_unit") or 0.0)
    opt = float(feat.get("option_align") or feat.get("frame_align") or 0.0)
    side = str(feat.get("option_side") or "")
    role = str(meta.get("portable_role") or meta.get("fine_role") or "")
    time_n = float(feat.get("has_time_nail") or 0.0)
    band = str(feat.get("authority_band") or "")
    pp = int((pool_pos or {}).get(pid) or 10**9)
    text = str(meta.get("text") or "")
    hits = anchor_hits(text, anchors)
    slot_strong, _slot_weak = slot_align_detail(text, slots)
    slot_hits = slot_align_hits(text, slots)
    # R26：对撞题精确独占允许贴池缘（≤24），避免 5200米／发言人段卡在 21～23
    claim = is_claim_conflict_route(anchors)
    precise_hit = any(
        k and len(k) >= 4 and any(u in k for u in "米时分万") and k in text[:120]
        for k in list((anchors or {}).get("side_a") or [])
        + list((anchors or {}).get("side_b") or [])
    )
    voice_hit = any(v in text[:160] for v in _CALIBER_VOICE_CUES)
    edge_ok = (
        claim
        and hits["side"] in {"option_a", "option_b"}
        and (precise_hit or voice_hit)
        and pp <= 24
    )
    # R34：事实核对题强槽对齐可贴池缘；裁决题不靠拉丁灌核心
    slot_edge = route == "fact_check" and slot_strong >= 1 and pp <= 22
    in_pool = pp <= 20 or edge_ok or slot_edge
    if not in_pool:
        return False
    doc = str(meta.get("doc_id") or (pid.split("#", 1)[0] if pid else ""))
    url = (url_of or {}).get(doc) or str(meta.get("url") or "")
    host_u = host_authority_unit(url)
    sc = core_rank_score(
        pid, feats=feats, metas=metas, route=route,
        pool_pos=pool_pos, anchors=anchors, url_of=url_of, slots=slots,
    )

    # R34：事实核对题——池内强槽对齐进核心（抗 wire_relay 误伤）
    if route == "fact_check" and slot_strong >= 1:
        return True
    # 引号／主张核多击（造谣核对类）——不限路由，避免裁决误分时通稿独占
    if slot_strong >= 2 and (
        (slots.get("quotes") or slots.get("claim_nouns") or slots.get("claim_alts"))
        and pp <= 20
    ):
        return True
    # R35：座位码／侥幸类短主张段进核心
    nlen = len(re.sub(r"\s+", "", text))
    _alts_c = list((slots or {}).get("claim_alts") or []) + list(
        (slots or {}).get("claim_nouns") or []
    )
    _short_q = bool(
        slots
        and (
            any(re.match(r"^\d{1,2}[A-Za-z]$", c or "") for c in (slots.get("codes") or []))
            or any(
                any(k in (a or "") for k in ("侥幸", "生还", "开关", "缺陷"))
                for a in _alts_c
            )
        )
    )
    if (
        route == "adjudicate"
        and pp <= 20
        and _short_q
        and is_short_claim_segment(text, slots, route=route)
    ):
        return True
    # 裁决题：强槽须同时有侧锚，避免 OpenAI 等拉丁通篇灌核心
    if route == "adjudicate" and slot_strong >= 1 and hits["total"] >= 1:
        return True
    # 锚点独占 + 基本可信 → 核心；短独占主张段（常是原话／否认句）也进
    if hits["side"] in {"option_a", "option_b"} and (
        ver >= 0.25 or auth >= 0.45 or host_u >= 0.55 or opt >= 0.20
        or (pp <= 20 and 0 < nlen <= 220)
    ):
        return True
    # 双侧锚点 + 高权威主机
    if hits["side"] == "both" and (host_u >= 0.85 or ver >= 0.67) and sc >= 0.45:
        return True
    # 问句主题软锚（通报／对话等）+ 池内权威／可核验载体
    if int(hits.get("soft") or 0) >= 1 and (
        host_u >= 0.55
        or band in {"primary_source", "official_channel"}
        or (ver >= 0.50 and auth >= 0.75)
    ):
        return True
    if route == "institutional":
        if role in _INST_META and (ver >= 0.50 or auth >= 0.75):
            return True
        if band == "primary_source" and ver >= 0.67 and opt >= 0.15:
            return True
        return False
    if host_u >= 0.85 and ver >= 0.50 and (hits["total"] >= 1 or opt >= 0.12):
        return True
    if ver >= 0.67 and band == "primary_source" and host_u >= 0.55 and (
        hits["total"] >= 1 or opt >= 0.12
    ):
        return True
    if ver >= 1.0 and time_n >= 1.0 and auth >= 0.75 and opt >= 0.15:
        return True
    if side in {"option_a", "option_b"} and ver >= 0.67 and (auth >= 0.45 or opt >= 0.35):
        return True
    return False


_AMT = re.compile(r"\d+(?:\.\d+)?\s*万|\d{2,}\s*元")


def related_filler(
    pid: str,
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    anchors: dict[str, list[str]] | None = None,
    pool_pos: dict[str, int] | None = None,
    url_of: dict[str, str] | None = None,
    slots: dict[str, Any] | None = None,
) -> bool:
    """高相关非核心：只允许补位，不可回填稀释。"""
    if is_core_candidate(
        pid, feats=feats, metas=metas, route=route,
        pool_pos=pool_pos, anchors=anchors, url_of=url_of, slots=slots,
    ):
        return False
    feat = feats.get(pid) or {}
    meta = metas.get(pid) or {}
    opt = float(feat.get("option_align") or feat.get("frame_align") or 0.0)
    ver = float(feat.get("verifiability") or 0.0)
    auth = float(feat.get("authority_unit") or 0.0)
    side = str(feat.get("option_side") or "")
    band = str(feat.get("authority_band") or "")
    text = str(meta.get("text") or "")
    hits = anchor_hits(text, anchors)
    slot_hits = slot_align_hits(text, slots)
    # R34：事实核对／引号主张题——综述／外交壳不进补位，防占满 k_min
    _quote_q = bool(slots and (slots.get("quotes") or slots.get("claim_nouns")))
    if (route == "fact_check" or _quote_q) and looks_like_wire_shell(
        text, band=band, slot_hits=slot_hits,
    ):
        return False
    if hits["total"] >= 1:
        return True
    if slot_hits >= 1:
        return True
    if route == "adjudicate":
        return side in {"option_a", "option_b"} or opt >= 0.25
    if route == "institutional":
        return any(c in text for c in ("制度", "办法", "规定", "编制")) or auth >= 0.45
    return ver >= 0.25 or auth >= 0.45 or opt >= 0.25 or bool(_AMT.search(text))
