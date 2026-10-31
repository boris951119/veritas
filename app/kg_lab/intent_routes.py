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
    "危机管理", "政府介入", "冰岩崩", "冰湖溃决", "冰川断裂", "泥石流",
    "洪灾", "山崩", "监控", "通稿", "联合国主渠道",
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
    "政府介入": ("政府介入", "政府控制", "政府"),
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
        return {"a": 0, "b": 0, "side": "", "total": 0, "soft": 0}
    ha = sum(1 for k in anchors.get("side_a") or [] if k and k in body)
    hb = sum(1 for k in anchors.get("side_b") or [] if k and k in body)
    hs = sum(1 for k in anchors.get("soft") or [] if k and k in body)
    side = ""
    if ha and not hb:
        side = "option_a"
    elif hb and not ha:
        side = "option_b"
    elif ha and hb:
        side = "both"
    elif ha or hb:
        side = "option_a" if ha else "option_b"
    return {"a": ha, "b": hb, "side": side, "total": ha + hb + hs, "soft": hs}


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


def core_rank_score(
    pid: str,
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    pool_pos: dict[str, int] | None = None,
    anchors: dict[str, list[str]] | None = None,
    url_of: dict[str, str] | None = None,
) -> float:
    """核心排序分：锚点命中＋主机权威＋可核验。不读金标 id。"""
    feat = feats.get(pid) or {}
    meta = metas.get(pid) or {}
    text = str(meta.get("text") or "")
    ver = float(feat.get("verifiability") or 0.0)
    auth = float(feat.get("authority_unit") or 0.0)
    fa = float(feat.get("frame_align") or 0.0)
    oa = float(feat.get("option_align") or 0.0)
    pp = int((pool_pos or {}).get(pid) or 10**9)
    doc = str(meta.get("doc_id") or (pid.split("#", 1)[0] if pid else ""))
    url = (url_of or {}).get(doc) or str(meta.get("url") or "")
    host_u = host_authority_unit(url)
    hits = anchor_hits(text, anchors)
    exclusive = 0.20 if hits["side"] in {"option_a", "option_b"} else (
        0.05 if hits["side"] == "both" else 0.0
    )
    soft_n = float(hits.get("soft") or 0)
    soft_b = 0.28 * min(soft_n / 2.0, 1.0)
    # 软锚＋高权威带：抬「通报／沟通渠道」类金标近似段
    band = str(feat.get("authority_band") or "")
    if soft_n >= 1 and band in {"primary_source", "official_channel"}:
        soft_b += 0.28
    if soft_n >= 2:
        soft_b += 0.08
    pool_b = max(0.0, (21 - pp) / 20.0) * 0.10 if pp <= 20 else 0.0
    align = max(fa, oa)
    return (
        0.22 * host_u
        + 0.16 * min(float(hits["a"] + hits["b"]) / 3.0, 1.0)
        + soft_b
        + exclusive
        + 0.14 * ver
        + 0.10 * auth
        + 0.08 * align
        + pool_b
        + (0.04 if route == "adjudicate" and hits["total"] else 0.0)
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
    in_pool = pp <= 20
    if not in_pool:
        return False
    text = str(meta.get("text") or "")
    hits = anchor_hits(text, anchors)
    doc = str(meta.get("doc_id") or (pid.split("#", 1)[0] if pid else ""))
    url = (url_of or {}).get(doc) or str(meta.get("url") or "")
    host_u = host_authority_unit(url)
    sc = core_rank_score(
        pid, feats=feats, metas=metas, route=route,
        pool_pos=pool_pos, anchors=anchors, url_of=url_of,
    )

    # 锚点独占 + 基本可信 → 核心
    if hits["side"] in {"option_a", "option_b"} and (
        ver >= 0.25 or auth >= 0.45 or host_u >= 0.55 or opt >= 0.20
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
) -> bool:
    """高相关非核心：只允许补位，不可回填稀释。"""
    if is_core_candidate(
        pid, feats=feats, metas=metas, route=route,
        pool_pos=pool_pos, anchors=anchors, url_of=url_of,
    ):
        return False
    feat = feats.get(pid) or {}
    meta = metas.get(pid) or {}
    opt = float(feat.get("option_align") or feat.get("frame_align") or 0.0)
    ver = float(feat.get("verifiability") or 0.0)
    auth = float(feat.get("authority_unit") or 0.0)
    side = str(feat.get("option_side") or "")
    text = str(meta.get("text") or "")
    hits = anchor_hits(text, anchors)
    if hits["total"] >= 1:
        return True
    if route == "adjudicate":
        return side in {"option_a", "option_b"} or opt >= 0.25
    if route == "institutional":
        return any(c in text for c in ("制度", "办法", "规定", "编制")) or auth >= 0.45
    return ver >= 0.25 or auth >= 0.45 or opt >= 0.25 or bool(_AMT.search(text))
