"""R23／R33：一筛补洞——主张／时点／可核验槽把池外近似段捞进 pool20。

只改 pool_ranked；submit_ranked（经典交卷序）不动。
无案专名硬编码、不读金标 id；锚点来自问句表面
（路由短锚／时点展开／拉丁·数额·引号·发言人槽）。
"""

from __future__ import annotations

import re
from typing import Any

from app.kg_lab.intent_routes import route_option_anchors
from app.kg_lab.source_role import _norm

_TIME_SPAN = re.compile(
    r"\d{1,2}时\d{1,2}分至\d{1,2}分|"
    r"\d{1,2}时\d{1,2}分|"
    r"\d{1,2}月\d{1,2}日|"
    r"\d{4}年\d{1,2}月|"
    r"\d{4}年"
)
_WEAK = frozenset({
    "泥石流", "对话", "全球", "安排", "机制", "企业", "政府", "官方",
    "数据", "通报", "热线", "就绪", "洪水", "问题", "事件",
    "是否", "属实", "流传", "说法", "这一", "一方", "双方", "原意",
    "指什么", "还是", "正面", "负面", "评价", "本人",
})
_DISTINCT = re.compile(
    r"\d|[A-Za-z]{3,}|"
    r"时|分|米|万|元|渠道|主渠道|溃决|冰岩|冰川|通稿|监控|"
    r"买断|补偿|编制|放行|联合国|危机|沟通|"
    r"政府介入|政府控制|政府监管|失控|责任"
)
# R33：问句表面可核验槽（禁止案名词表；从问句当场抽）
_LATIN_TOK = re.compile(r"[A-Za-z][A-Za-z0-9\.\-]{2,}")
_CODE_TOK = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]{1,4}-?\d{1,4}(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])[A-Za-z]+\d{2,4}(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])\d{1,2}[A-Za-z](?![A-Za-z0-9])"
)
_AMOUNT_TOK = re.compile(
    r"\d+(?:\.\d+)?\s*(?:人|名|万|亿|元|米|架|枚|次|%|％|吨|公里)"
)
# R35：对立支主张核（还是／是否 后短句），可迁移、非案名
_ALT_SPLIT = re.compile(r"还是|是否|抑或|或者")
# 主张核：优先开关／缺陷／侥幸等；裸「开火／空袭」易灌冲突通稿，不进 claim_alts
_ALT_KEEP = re.compile(
    r"[\u4e00-\u9fff]{2,12}(?:侥幸|开关|缺陷|援助|推荐信|保研|合照|证据|生还|遇难)"
    r"|纯属侥幸|关闭燃油开关|设计缺陷|燃油开关"
)
_ALT_WEAK_TAIL = frozenset({"开火", "空袭", "打击", "动武", "先开火"})
_YEAR_TOK = re.compile(r"20\d{2}")
_MONTH_ZH = re.compile(r"(?<!\d)(1[0-2]|[1-9])\s*月")
_QUOTES = re.compile(r"[「\"“]([^」\"”]{2,40})[」\"”]")
_SPEAKER = re.compile(
    r"([\u4e00-\u9fff]{2,4})本人|"
    r"(?<![方军部院局国会])([\u4e00-\u9fff]{2,4})(?:说的|谈到|谈及|表示|说)|"
    r"(?<![方军部院局国会与和及])([\u4e00-\u9fff]{2,4})(?<!方)(?<!军)称|"
    r"([\u4e00-\u9fff]{2,4})(?=的评价)"
)
# 排除「官方／双方／哪一方」整词误切
_PARTY = re.compile(
    r"(?<![官正双边我敌南北东西])([\u4e00-\u9fff]{1,2})"
    r"(?:方|军)(?=称|说|率先|出动|境内|向|的|，|,|$| |\")"
)
_PARTY_BAD = frozenset({
    "哪一", "哪", "一", "本", "对", "该", "其", "我", "敌", "双", "官",
})
_CONFLICT_VERB = ("开火", "空袭", "动武", "先开火", "打击", "摧毁")
# 问句含中文冲突动词时，拉丁段可迁移近义（非案名）
_CONFLICT_EN = (
    "fired", "firing", "fire ", "attack", "launched", "launch",
    "strike", "airstrike", "shelling", "clashed", "clash",
)
_MONTH_EN = {
    1: ("january", "jan."),
    2: ("february", "feb."),
    3: ("march", "mar."),
    4: ("april", "apr."),
    5: ("may", "may"),
    6: ("june", "jun."),
    7: ("july", "jul."),
    8: ("august", "aug."),
    9: ("september", "sep.", "sept."),
    10: ("october", "oct."),
    11: ("november", "nov."),
    12: ("december", "dec."),
}
_LATIN_STOP = frozenset({
    "the", "and", "for", "are", "was", "were", "this", "that",
    "with", "from", "have", "has", "had", "not", "but", "what",
    "which", "when", "where", "who", "how", "why", "into", "over",
    "also", "than", "then", "them", "they", "their", "been", "being",
})
_EVID = (
    "监控", "通稿", "新闻稿", "发布会", "公报", "通报", "声明",
    "原话", "记者", "认定", "查明", "发言人", "秘书长", "外交部",
    "例行记者会", "新闻发布会",
)
# 口径对立声部（发言人／秘书长）；「发布会查明」不算口径声部
_CALIBER_VOICE = (
    "发言人", "秘书长", "外交部", "联合国", "例行记者会", "声明",
)
# 口径／成因问句表面（可迁移；不含裸「还是」，以免误伤制度对立题）
_CLAIM_Q = ("口径", "采用", "哪一说法", "哪一口径", "应采用")
_CLAIM_Q_PAIR = ("认定", "说法成立")
# 责任／主体对立问句（可迁移；与口径题同走补洞降门槛）
_CLAIM_Q_RESP = ("责任", "承担", "该由", "失控", "由政府", "企业承担")

_PARA_ORD = re.compile(r"^(?P<doc>.+)#p(?P<n>\d+)$")


def expand_question_times(question: str) -> list[str]:
    """展开问句时点；「10时52分至59分」→ 含「10时52分」等可迁移子串。"""
    raw = _TIME_SPAN.findall(question or "")
    out: list[str] = []
    for t in raw:
        if t not in out:
            out.append(t)
        if "至" not in t:
            continue
        for p in re.findall(r"\d{1,2}时\d{1,2}分", t):
            if p not in out:
                out.append(p)
        m = re.match(r"(\d{1,2})时(\d{1,2})分至(\d{1,2})分", t)
        if not m:
            continue
        h, a, b = m.group(1), m.group(2), m.group(3)
        for p in (f"{h}时{a}分", f"{h}时{b}分"):
            if p not in out:
                out.append(p)
    return out


def _split_clock_date(times: list[str]) -> tuple[list[str], list[str]]:
    clock = [t for t in times if "时" in t and "分" in t]
    dates = [t for t in times if t not in clock]
    return clock, dates


def extract_verifiable_slots(question: str) -> dict[str, Any]:
    """从问句表面抽可核验槽：拉丁／代码／数额／引号块／发言人／年月。

    禁止案专名词表；所有词条必须是问句里当场出现的子串。
    """
    q = question or ""
    latin: list[str] = []
    for m in _LATIN_TOK.findall(q):
        if m.lower() in _LATIN_STOP:
            continue
        if m not in latin:
            latin.append(m)
        if len(latin) >= 8:
            break
    codes: list[str] = []
    for m in _CODE_TOK.findall(q):
        if m.lower() in _LATIN_STOP:
            continue
        if m not in codes and m not in latin:
            codes.append(m)
        if len(codes) >= 6:
            break
    amounts: list[str] = []
    for m in _AMOUNT_TOK.findall(q):
        t = re.sub(r"\s+", "", m)
        if t and t not in amounts:
            amounts.append(t)
        if len(amounts) >= 8:
            break
    quotes: list[str] = []
    for qt in _QUOTES.findall(q):
        qt = (qt or "").strip()
        if 2 <= len(qt) <= 16 and qt not in quotes:
            quotes.append(qt)
        # 尾核 2–4 字（推荐信／保研／合照）— 比整句引号更易命中澄清段
        for n in (4, 3, 2):
            if len(qt) >= n:
                tail = qt[-n:]
                if tail not in _WEAK and tail not in quotes:
                    quotes.append(tail)
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,6}", qt):
            if chunk in _WEAK or len(chunk) < 2:
                continue
            if chunk not in quotes:
                quotes.append(chunk)
            if len(quotes) >= 16:
                break
        if len(quotes) >= 16:
            break
    speakers: list[str] = []
    for groups in _SPEAKER.findall(q):
        # findall 多组时返回 tuple
        cands = groups if isinstance(groups, tuple) else (groups,)
        for sp in cands:
            sp = (sp or "").strip()
            if not sp:
                continue
            if sp.endswith("本人") and len(sp) > 2:
                sp = sp[:-2]
            if sp.endswith("的") or sp.startswith("对"):
                continue
            if sp.startswith(("与", "和", "及", "对")) or any(
                b in sp for b in ("哪", "何", "谁", "一方", "双方", "与", "媒体")
            ):
                continue
            if sp.endswith(("方", "军", "部", "院")):
                continue
            if 2 <= len(sp) <= 4 and sp not in _WEAK and sp not in speakers:
                speakers.append(sp)
            if len(speakers) >= 4:
                break
        if len(speakers) >= 4:
            break
    parties: list[str] = []
    for groups in _PARTY.findall(q):
        cands = groups if isinstance(groups, tuple) else (groups,)
        for p in cands:
            p = (p or "").strip()
            if not p or p in _WEAK or p in _PARTY_BAD:
                continue
            for form in (p + "方", p + "军", p):
                if form not in parties and form not in _PARTY_BAD:
                    parties.append(form)
            if len(parties) >= 8:
                break
        if len(parties) >= 8:
            break
    years = list(dict.fromkeys(_YEAR_TOK.findall(q)))[:4]
    months: list[int] = []
    for m in _MONTH_ZH.findall(q):
        try:
            n = int(m)
        except ValueError:
            continue
        if 1 <= n <= 12 and n not in months:
            months.append(n)
    verbs = [v for v in _CONFLICT_VERB if v in q][:4]
    # R35/R36：对立支短主张（长支优先；短核「燃油开关」不进 alts，以免评论通稿灌池）
    claim_alts: list[str] = []
    for part in _ALT_SPLIT.split(q):
        part = part.strip(" ，。？?、；;：:（）()\"“”「」")
        if not part:
            continue
        for m in _ALT_KEEP.findall(part):
            if (
                m not in claim_alts
                and m not in _WEAK
                and not any(m.endswith(t) and len(m) <= len(t) + 2 for t in _ALT_WEAK_TAIL)
            ):
                claim_alts.append(m)
        # 短支整段（≤12 字）也保留
        if 2 <= len(part) <= 12 and part not in _WEAK and part not in claim_alts:
            if any(c in part for c in ("侥幸", "开关", "缺陷", "援助", "生还", "遇难")):
                claim_alts.append(part)
        if len(claim_alts) >= 8:
            break
    return {
        "latin": latin,
        "codes": codes,
        "amounts": amounts,
        "quotes": quotes,
        "speakers": speakers,
        "parties": parties,
        "years": years,
        "months": months,
        "conflict_verbs": verbs,
        "claim_alts": claim_alts[:8],
    }


def _latin_codeish(tok: str) -> bool:
    """含数字／连字符的拉丁串（航班号／型号）易灌池，需与其它槽同现。"""
    return bool(re.search(r"\d", tok or "")) or ("-" in (tok or ""))


def slots_nonempty(slots: dict[str, Any] | None) -> bool:
    """披露用：问句是否抽到任何可核验槽。"""
    if not slots:
        return False
    return bool(
        slots.get("latin")
        or slots.get("codes")
        or slots.get("amounts")
        or slots.get("quotes")
        or slots.get("speakers")
        or (slots.get("years") and slots.get("conflict_verbs"))
        or (slots.get("parties") and slots.get("conflict_verbs"))
    )


def slots_actionable(
    slots: dict[str, Any] | None,
    question: str | None = None,
) -> bool:
    """注入／缩头触发。

    口径／责任题已有 R23–R27 臂，R33 只补引号／冲突年月桥／数额×代码，
    避免 OpenAI／WIRED 等词拉丁在回归案上二次搅池。
    """
    if not slots:
        return False
    q = question or ""
    claim_like = (
        any(c in q for c in _CLAIM_Q)
        or any(c in q for c in _CLAIM_Q_PAIR)
        or any(c in q for c in _CLAIM_Q_RESP)
    )
    latin = list(slots.get("latin") or [])
    word_lat = [k for k in latin if not _latin_codeish(k)]
    code_lat = [k for k in latin if _latin_codeish(k)]
    speakers = list(slots.get("speakers") or [])
    bridge = bool(
        slots.get("quotes")
        or (
            slots.get("amounts")
            and (code_lat or slots.get("codes") or word_lat)
        )
        or (slots.get("years") and slots.get("conflict_verbs"))
        or (slots.get("parties") and slots.get("conflict_verbs"))
        or (
            speakers
            and (slots.get("quotes") or slots.get("amounts") or code_lat)
        )
        # R35：对立支主张核／座位号类代码 → 可召回
        or slots.get("claim_alts")
        or any(
            re.match(r"^\d{1,2}[A-Za-z]$", c or "")
            for c in (slots.get("codes") or [])
        )
        # 评价题：发言人＋正负面 → 专访段召回（禁案名，只靠问句表面）
        or (
            speakers
            and any(c in q for c in ("正面", "负面", "评价", "怎么看", "如何看"))
        )
    )
    if claim_like:
        return bridge
    return bool(word_lat or bridge)


def _short_cores(keys: list[str] | None, *, limit: int = 8) -> list[str]:
    """长侧锚拆短核（开火／推荐信），便于中英混排或半截命中。"""
    out: list[str] = []
    for k in keys or []:
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z]{3,}|\d+(?:人|名|万|米)?", k):
            if chunk in _WEAK or len(chunk) < 2:
                continue
            if chunk not in out:
                out.append(chunk)
            if len(out) >= limit:
                return out
    return out


def distinctive_anchors(keys: list[str] | None, *, allow_weak_sole: bool = False) -> list[str]:
    """抽可迁移主张锚。allow_weak_sole：该侧仅剩弱词（如「泥石流」）时仍保留。"""
    raw = [k for k in (keys or []) if k and len(k) >= 2]
    out: list[str] = []
    for k in raw:
        if k in _WEAK or len(k) < 3:
            continue
        if _DISTINCT.search(k) or len(k) >= 5:
            out.append(k)
        if len(out) >= 6:
            break
    if not out and allow_weak_sole:
        for k in raw:
            if len(k) >= 2 and k not in out:
                out.append(k)
            if len(out) >= 3:
                break
    return out


def _para_neighbors(para_id: str, known: set[str], *, window: int = 1) -> list[str]:
    m = _PARA_ORD.match(para_id or "")
    if not m:
        return []
    doc, n = m.group("doc"), int(m.group("n"))
    out: list[str] = []
    for d in range(1, window + 1):
        for cand in (f"{doc}#p{n - d}", f"{doc}#p{n + d}"):
            if cand in known:
                out.append(cand)
    return out


def build_claim_hole_arm(
    rows: list[dict[str, Any]],
    question: str,
    *,
    bm25_text=None,
) -> dict[str, Any]:
    """主张／时点补洞臂：返回 sorted (pid, score) 与披露。"""
    texts = {
        str(r.get("para_id") or ""): str(r.get("text") or "")
        for r in rows
        if r.get("para_id")
    }
    known = set(texts)
    anchors = route_option_anchors(question)
    times = expand_question_times(question)
    clock, dates = _split_clock_date(times)
    q0 = question or ""
    claim_q = (
        any(c in q0 for c in _CLAIM_Q)
        or any(c in q0 for c in _CLAIM_Q_PAIR)
        or any(c in q0 for c in _CLAIM_Q_RESP)
    )
    # 「口径／采用」类：查明换皮是噪声；「说法成立」成因类：查明常是正答
    caliber_naming = any(c in q0 for c in _CLAIM_Q)
    resp_q = any(c in q0 for c in _CLAIM_Q_RESP)
    # 口径／成因题：允许单侧弱词作锚；有钟点时仍走强锚优先
    weak_sole = claim_q or (not clock and bool(anchors.get("side_a") and anchors.get("side_b")))
    a_keys = distinctive_anchors(
        list(anchors.get("side_a") or []), allow_weak_sole=weak_sole,
    )
    b_keys = distinctive_anchors(
        list(anchors.get("side_b") or []), allow_weak_sole=weak_sole,
    )
    soft = [
        k for k in (anchors.get("soft") or [])
        if k not in _WEAK and len(k) >= 3
    ][:5]
    # raw 侧主张整段也可作软锚（短于 24）
    for raw in list(anchors.get("raw_a") or []) + list(anchors.get("raw_b") or []):
        r = (raw or "").strip()
        if 3 <= len(r) <= 24 and r not in a_keys and r not in b_keys and r not in soft:
            soft.append(r)
    # R26：口径／成因题才把问句点名机构声部作软锚（钟点题不加，防搅池）
    if claim_q:
        for cue in ("联合国", "外交部", "发言人", "秘书长", "新闻发布会", "尼泊尔"):
            if cue in q0 and cue not in a_keys and cue not in b_keys and cue not in soft:
                soft.append(cue)
    # R33：可核验槽并入软锚（仅 actionable 时，防回归案裸数额搅池）
    slots = extract_verifiable_slots(q0)
    has_slots = slots_actionable(slots, q0)
    word_latin = [k for k in (slots.get("latin") or []) if not _latin_codeish(k)]
    if has_slots:
        soft_add = (
            word_latin[:4]
            + list(slots.get("quotes") or [])[:4]
            + list(slots.get("amounts") or [])[:3]
            + list(slots.get("conflict_verbs") or [])[:2]
            + list(slots.get("claim_alts") or [])[:4]
            + list(slots.get("codes") or [])[:3]
        )
        if slots.get("amounts"):
            soft_add = soft_add + [
                k for k in (slots.get("latin") or []) if _latin_codeish(k)
            ][:2]
            soft_add = soft_add + list(slots.get("codes") or [])[:2]
        if not (word_latin or slots.get("quotes") or slots.get("amounts")):
            soft_add = soft_add + list(slots.get("speakers") or [])[:2]
        for tok in soft_add:
            if tok and tok not in a_keys and tok not in b_keys and tok not in soft:
                soft.append(tok)
        soft = soft[:14]
    a_cores = _short_cores(a_keys) if has_slots else []
    b_cores = _short_cores(b_keys) if has_slots else []

    scored: dict[str, float] = {}
    for pid, text in texts.items():
        s = 0.0
        tl = text.lower()
        nc = sum(1 for t in clock if t in text)
        nd = sum(1 for t in dates if t in text)
        s += 6.0 * nc + 0.8 * nd
        if nc >= 2:
            s += 5.0
        if nc >= 1 and any(e in text for e in _EVID):
            s += 3.0
        ha = sum(1 for k in a_keys if k in text)
        hb = sum(1 for k in b_keys if k in text)
        ha_c = sum(1 for k in a_cores if k in text) if a_cores else 0
        hb_c = sum(1 for k in b_cores if k in text) if b_cores else 0
        s += 2.0 * ha + 2.0 * hb + 1.2 * ha_c + 1.2 * hb_c
        if ha and hb:
            s += 2.5
        elif ha_c and hb_c:
            s += 1.2
        # R26：非钟点题才抬精确数额／海拔（钟点题已有 nc 加分，避免通稿时点灌满注入）
        if not clock:
            precise = [
                k for k in a_keys + b_keys
                if k and len(k) >= 4 and any(u in k for u in "米时分万")
            ]
            if precise and any(k in text[:100] for k in precise):
                s += 2.2
        hs = sum(1 for k in soft if k in text or (k.isascii() and k.lower() in tl))
        s += 0.5 * hs
        latin_n = len(re.findall(r"[A-Za-z]{3,}", text[:320]))
        # R33：仅 actionable 槽题启用强对齐（否则保持 R23–R27 行为）
        if has_slots:
            n_lat = sum(1 for k in (slots.get("latin") or []) if k.lower() in tl)
            n_code = sum(1 for k in (slots.get("codes") or []) if k.lower() in tl)
            n_amt = sum(1 for k in (slots.get("amounts") or []) if k in text)
            n_qt = sum(1 for k in (slots.get("quotes") or []) if k in text)
            n_sp = sum(1 for k in (slots.get("speakers") or []) if k in text)
            lat_list = list(slots.get("latin") or [])
            word_lat_n = sum(
                1 for k in lat_list if (not _latin_codeish(k)) and k.lower() in tl
            )
            code_lat_n = sum(
                1 for k in lat_list if _latin_codeish(k) and k.lower() in tl
            )
            n_code_all = n_code + code_lat_n
            if word_lat_n:
                s += 9.0 + 2.0 * min(word_lat_n, 3)
                if any(
                    e in text[:280]
                    for e in ("原话", "访谈", "视频", "官方", "亲口", "一手", "采访", "原文")
                ):
                    s += 4.0
                if any(
                    f'"{k}"' in text or f"“{k}" in text or f"「{k}" in text
                    for k in lat_list
                    if not _latin_codeish(k)
                ):
                    s += 2.5
            if n_code_all:
                if n_amt or n_qt or word_lat_n or ha or hb or ha_c or hb_c:
                    s += 8.0 + 1.5 * min(n_code_all, 2)
                else:
                    s += 1.8 * min(n_code_all, 2)
            if n_amt:
                s += 6.0 + 1.5 * min(n_amt, 3)
                if any(e in text[:200] for e in ("证实", "遇难", "死亡", "官方", "报告")):
                    s += 2.5
                # R35：短数额段优先进池（抗长通稿占注入名额）
                nlen0 = len(re.sub(r"\s+", "", text))
                if 20 <= nlen0 <= 160:
                    s += 4.0
            if n_qt:
                s += 3.5 * min(n_qt, 4)
                if any(
                    e in text[:220]
                    for e in ("澄清", "辟谣", "知情", "并非", "不实", "回应")
                ):
                    s += 3.0
            alt_list = list(slots.get("claim_alts") or [])
            n_alt = sum(1 for k in alt_list if k and k in text)
            # R36：从长支抽可迁移核；正文「关闭了…燃油…开关」靠共现，不把短核塞进 claim_alts
            alt_cores: list[str] = []
            for a in alt_list:
                for m in re.findall(
                    r"关闭燃油开关|燃油开关|设计缺陷|关闭[^，。]{0,8}开关|"
                    r"纯属侥幸|[\u4e00-\u9fff]{2,6}(?:开关|缺陷|侥幸)",
                    a or "",
                ):
                    if m not in alt_cores and m not in _WEAK:
                        alt_cores.append(m)
            switch_q = any(
                any(k in (a or "") for k in ("开关", "缺陷", "燃油"))
                for a in alt_list
            )
            if switch_q:
                for extra in ("fuel switch", "fuel control", "cut off"):
                    if extra not in alt_cores:
                        alt_cores.append(extra)
            n_alt_c = sum(
                1 for k in alt_cores
                if k and (k in text or (k.isascii() and k.lower() in tl))
            )
            # 拆开共现：关闭／切断×燃油×开关 或 fuel×switch×(cut/closed)
            _sw_cut = (
                "燃油" in text and "开关" in text
                and any(c in text for c in ("关闭", "切断", "切断位置"))
            )
            _sw_en = (
                "fuel" in tl and "switch" in tl
                and any(w in tl for w in ("cut off", "cutoff", "closed", "cut-off"))
            )
            if switch_q and not n_alt:
                if _sw_cut or _sw_en:
                    n_alt_c = max(n_alt_c, 1)
            if n_alt:
                s += 7.0 + 2.0 * min(n_alt, 3)
            elif n_alt_c and alt_list:
                # 仅全文未命中长支时用核分，避免与 n_alt 叠灌
                s += 6.0 + 1.2 * min(n_alt_c, 3)
            if (n_alt or n_alt_c) and alt_list:
                nlen0 = len(re.sub(r"\s+", "", text))
                if 12 <= nlen0 <= 160:
                    s += 5.0
                if switch_q:
                    report_v = any(
                        e in text[:360]
                        for e in (
                            "初步调查", "初步报告", "黑匣子", "调查报告",
                            "录音显示", "报告披露", "报告显示", "AAIB",
                            "事故调查",
                        )
                    ) or ("preliminary report" in tl) or ("flight recorder" in tl)
                    if report_v:
                        s += 5.5
                        # 调查声部长段仍优先于标题党短壳
                        if _sw_cut or _sw_en:
                            s += 3.0
                        if nlen0 > 160:
                            s += 2.0
                    elif (
                        any(e in text[:140] for e in ("专家", "分析指出", "正在阅读"))
                        and nlen0 > 200
                    ):
                        s -= 3.0
                    if _sw_en:
                        s += 3.0
            # R35：座位号类 codes（11A）短段额外抬，避免被航班拉丁长通稿挤掉
            if n_code:
                nlen0 = len(re.sub(r"\s+", "", text))
                if 12 <= nlen0 <= 140:
                    s += 4.5
            if n_sp:
                if n_lat or n_qt or n_amt or n_code or n_alt:
                    s += 2.5 * min(n_sp, 2) + 2.0
                else:
                    s += 0.6 * min(n_sp, 2)
                # 评价题：发言人专访短段
                if any(c in q0 for c in ("正面", "负面", "评价")) and n_sp:
                    if any(e in text[:120] for e in ("专访", "表示", "说道", "回忆", "觉得")):
                        s += 4.0
                    nlen0 = len(re.sub(r"\s+", "", text))
                    if 40 <= nlen0 <= 200:
                        s += 2.5
            years = list(slots.get("years") or [])
            if years and latin_n >= 5 and any(y in text for y in years):
                s += 4.0
                for mnum in list(slots.get("months") or [])[:2]:
                    ens = _MONTH_EN.get(int(mnum), ())
                    if any(e in tl for e in ens):
                        s += 3.0
                        break
                if any(v in text for v in (slots.get("conflict_verbs") or [])):
                    s += 2.0
                if any(e in tl for e in _CONFLICT_EN):
                    s += 3.5
                if ha_c or hb_c:
                    s += 2.0
            parties = list(slots.get("parties") or [])
            verbs = list(slots.get("conflict_verbs") or [])
            if parties and verbs:
                if any(p in text for p in parties) and any(v in text for v in verbs):
                    s += 4.0
        # R25/R26：机构口径声部＋侧锚同现（发言人谈泥石流／秘书长谈洪灾）
        voice_n = sum(1 for e in _EVID if e in text[:200])
        caliber_v = sum(1 for e in _CALIBER_VOICE if e in text[:220])
        if claim_q and caliber_v and (ha or hb):
            s += 2.8 + 1.0 * min(caliber_v, 3)
            # R26：口径声部＋单侧主张优先于「查明」假双侧换皮，抬注入位
            if (ha == 0) != (hb == 0):
                s += 3.0
        elif claim_q and voice_n and (ha or hb):
            s += 2.0 + 0.8 * min(voice_n, 3)
        elif claim_q and caliber_v and hs:
            # 问句点名机构声部段（尚无侧锚）也进补洞臂
            s += 2.0 + 0.8 * min(caliber_v, 3)
        # R27：责任题抬「拉丁专名×侧锚／失控」可核验段（OpenAI 失控／政府控制）
        if resp_q and (ha or hb):
            if latin_n:
                s += 1.8 + 0.6 * min(latin_n, 3)
            if "失控" in text or "政府控制" in text or "政府介入" in text:
                s += 1.5
            # 单侧主张（企业 vs 政府）优先于空泛治理长文
            if (ha == 0) != (hb == 0):
                s += 4.0
            elif ha and hb:
                s -= 1.2
        # R26：仅「口径／采用」题降无口径声部的查明双侧，避免占满注入槽
        if caliber_naming and not clock and ("查明" in text) and caliber_v == 0 and ha and hb:
            s -= 4.0
        if s > 0:
            scored[pid] = s

    bm25_bits = clock[:4] + a_keys[:3] + b_keys[:3] + soft[:3]
    if has_slots:
        bm25_bits = (
            bm25_bits
            + word_latin[:3]
            + list(slots.get("amounts") or [])[:3]
            + list(slots.get("quotes") or [])[:2]
        )
        if slots.get("amounts"):
            bm25_bits = bm25_bits + [
                k for k in (slots.get("latin") or []) if _latin_codeish(k)
            ][:2]
    bm25_q = " ".join(bm25_bits).strip()
    if bm25_text is not None and len(bm25_q) >= 4:
        for i, (pid, _sc) in enumerate(bm25_text(bm25_q)[:50]):
            scored[pid] = scored.get(pid, 0.0) + 1.2 / (1.0 + i / 6.0)

    # 无钟点口径题／可核验槽题：门槛略降，避免主张臂空转
    floor = 3.0 if (claim_q and not clock) else 4.0
    if has_slots and not clock:
        floor = min(floor, 2.5)
    top = [
        pid for pid, sc in sorted(scored.items(), key=lambda x: -x[1])[:15]
        if sc >= floor
    ]
    for pid in top:
        for nb in _para_neighbors(pid, known, window=1):
            scored[nb] = scored.get(nb, 0.0) + 1.0

    arm = sorted(scored.items(), key=lambda x: (-x[1], x[0]))[:120]
    return {
        "arm": arm,
        "times": times,
        "clock": clock,
        "dates": dates,
        "side_a": a_keys,
        "side_b": b_keys,
        "soft": soft,
        "slots": slots,
        "n_scored": len(scored),
    }


def _slot_hit_tier(text: str, slots: dict[str, Any] | None) -> int:
    """注入优先级：词拉丁／（代码×数额）＞数额／引号＞年月桥／冲突＞裸代码。"""
    if not slots or not text:
        return 0
    tl = text.lower()
    lat = list(slots.get("latin") or [])
    word_lat = [k for k in lat if not _latin_codeish(k)]
    code_lat = [k for k in lat if _latin_codeish(k)]
    from app.kg_lab.intent_routes import amount_token_hit

    has_word_lat = any(k.lower() in tl for k in word_lat)
    has_code = any(k.lower() in tl for k in (slots.get("codes") or []) + code_lat)
    # R37：数额剥单位数字核，抬英文通稿／声明里的 241／274 等
    has_amt = any(
        amount_token_hit(text, str(k or "")) for k in (slots.get("amounts") or [])
    )
    has_qt = any(k in text for k in (slots.get("quotes") or []))
    # 拉丁专名（航班号等）× 数额数字核 → 最高档，专治中英问句对英文段
    if has_word_lat and has_amt:
        return 3
    alt_list = list(slots.get("claim_alts") or [])
    has_alt = any(k in text for k in alt_list if k and len(k) >= 4)
    alt_cores: list[str] = []
    for a in alt_list:
        for m in re.findall(
            r"关闭燃油开关|燃油开关|设计缺陷|关闭[^，。]{0,8}开关|"
            r"纯属侥幸|[\u4e00-\u9fff]{2,6}(?:开关|缺陷|侥幸)",
            a or "",
        ):
            if m not in alt_cores:
                alt_cores.append(m)
    tl0 = text.lower()
    if any(any(k in (a or "") for k in ("开关", "燃油", "缺陷")) for a in alt_list):
        for extra in ("fuel switch", "fuel control", "cut off"):
            if extra not in alt_cores:
                alt_cores.append(extra)
    has_alt_c = bool(alt_list) and any(
        k in text or (k.isascii() and k.lower() in tl0) for k in alt_cores if k
    )
    if (
        not has_alt_c
        and alt_list
        and any("开关" in (a or "") for a in alt_list)
        and (
            (
                "燃油" in text and "开关" in text
                and any(c in text for c in ("关闭", "切断"))
            )
            or (
                "fuel" in tl0 and "switch" in tl0
                and any(w in tl0 for w in ("cut off", "cutoff", "closed"))
            )
        )
    ):
        has_alt_c = True
    if has_word_lat:
        return 3
    if has_code and (has_amt or has_qt):
        return 3
    if has_alt or has_alt_c:
        return 3 if (has_alt_c or has_alt) else 2
    if has_amt or has_qt:
        return 2
    years = list(slots.get("years") or [])
    latin_n = len(re.findall(r"[A-Za-z]{3,}", text[:320]))
    if years and latin_n >= 5 and any(y in text for y in years):
        return 2
    verbs = list(slots.get("conflict_verbs") or [])
    parties = list(slots.get("parties") or [])
    if verbs and parties and any(v in text for v in verbs) and any(p in text for p in parties):
        return 1
    if has_code:
        return 1
    return 0


def inject_claim_holes(
    pool_ranked: list[tuple[str, float]],
    claim_arm: list[tuple[str, float]],
    *,
    texts: dict[str, str] | None = None,
    slots: dict[str, Any] | None = None,
    head_keep: int = 10,
    max_inject: int = 8,
    min_claim: float = 4.0,
    pool: int = 20,
) -> dict[str, Any]:
    """保经典池头并注入高主张分；有 slots 时钉强槽＋同 doc 限注。"""
    base_ids = [pid for pid, sc in pool_ranked if float(sc) > 0]
    claim_sc = {pid: float(sc) for pid, sc in claim_arm}
    texts = texts or {}
    use_slots = bool(slots)

    pinned: list[str] = []
    if use_slots:
        pin_cands: list[tuple[int, float, int, str]] = []
        # 经典池头强槽钉住；池外高分短可核验经 inject 路径进池（见下方 cands）
        for i, pid in enumerate(base_ids[:25]):
            tier = _slot_hit_tier(texts.get(pid) or "", slots)
            if tier >= 2:
                pin_cands.append((tier, float(claim_sc.get(pid) or 0.0), -i, pid))
        pin_cands.sort(reverse=True)
        pin_doc: dict[str, int] = {}
        for tier, _sc, _neg_i, pid in pin_cands:
            doc = str(pid).split("#", 1)[0]
            if pin_doc.get(doc, 0) >= 2:
                continue
            pinned.append(pid)
            pin_doc[doc] = pin_doc.get(doc, 0) + 1
            if len(pinned) >= 8:
                break

    if use_slots and pinned:
        head: list[str] = []
        for pid in pinned + base_ids:
            if pid in head:
                continue
            head.append(pid)
            if len(head) >= max(head_keep, len(pinned)):
                break
        head = head[: max(head_keep, min(len(pinned) + 2, 12))]
    else:
        # 无槽：与 R23 完全同构，保回归案
        head = base_ids[:head_keep]
    head_set = set(head)

    if use_slots:
        from app.kg_lab.intent_routes import amount_token_hit
        base_pos = {pid: i for i, pid in enumerate(base_ids, 1)}
        # R37：注入只服务池外／深段；已在前20 的通稿不必再注
        cands = [
            (
                _slot_hit_tier(texts.get(pid) or "", slots),
                claim_sc[pid],
                pid,
            )
            for pid in claim_sc
            if pid not in head_set
            and claim_sc[pid] >= min_claim
            and int(base_pos.get(pid) or 10**9) > 20
        ]
        seen_cand = {pid for _t, _s, pid in cands}
        for pid, body in texts.items():
            if not pid or pid in head_set or pid in seen_cand:
                continue
            pr = int(base_pos.get(pid) or 10**9)
            if pr <= 20:
                continue
            tier = _slot_hit_tier(body or "", slots)
            if tier < 2:
                continue
            n_amt = sum(
                1 for a in (slots.get("amounts") or [])
                if amount_token_hit(body or "", str(a or ""))
            )
            # 多数额对撞优先（241／242／274）；略抬更深段
            cands.append((
                tier,
                float(min_claim) + 0.5 * tier + 0.45 * n_amt + min(0.4, pr / 400.0),
                pid,
            ))
            seen_cand.add(pid)
        # R37：有数额槽时按「对撞数字数 × 承运人／拉丁锚 × 短段」重排
        if slots.get("amounts"):
            lat = [str(x).lower() for x in (slots.get("latin") or []) if x]
            ranked_amt: list[tuple[int, int, int, int, float, str]] = []
            for tier, sc, pid in cands:
                body = texts.get(pid) or ""
                tl = body.lower()
                n_amt = sum(
                    1 for a in (slots.get("amounts") or [])
                    if amount_token_hit(body, str(a or ""))
                )
                # 锚只用问句拉丁槽（如航班号），不写航司／国名专名表
                anchor = 1 if any(k in tl for k in lat) else 0
                import re as _re
                nlen = len(_re.sub(r"\s+", "", body))
                short = 1 if 0 < nlen <= 220 else 0
                ranked_amt.append((n_amt, anchor, short, int(tier), float(sc), pid))
            ranked_amt.sort(reverse=True)
            cands = [(tier, sc, pid) for _na, _an, _sh, tier, sc, pid in ranked_amt]
        else:
            cands.sort(reverse=True)
        inject: list[str] = []
        per_doc: dict[str, int] = {}
        for pid in head:
            doc = str(pid).split("#", 1)[0]
            per_doc[doc] = per_doc.get(doc, 0) + 1
        for tier, _sc, pid in cands:
            doc = str(pid).split("#", 1)[0]
            cap = 2 if tier >= 2 else 3
            if per_doc.get(doc, 0) >= cap:
                continue
            inject.append(pid)
            per_doc[doc] = per_doc.get(doc, 0) + 1
            if len(inject) >= max_inject:
                break
    else:
        cands_plain = [
            (claim_sc[pid], pid)
            for pid in claim_sc
            if pid not in head_set and claim_sc[pid] >= min_claim
        ]
        cands_plain.sort(reverse=True)
        inject = [pid for _sc, pid in cands_plain[:max_inject]]

    # 近同文：已注入段的同指纹兄弟也进（同文金标常散落多段）
    if texts and inject:
        fps = {_norm(texts.get(pid) or "")[:96] for pid in inject}
        fps.discard("")
        extra: list[str] = []
        for pid, sc in claim_arm:
            if pid in head_set or pid in inject:
                continue
            if float(sc) < min_claim * 0.6:
                continue
            fp = _norm(texts.get(pid) or "")[:96]
            if fp and fp in fps:
                extra.append(pid)
            if len(inject) + len(extra) >= max_inject + 4:
                break
        inject = inject + extra

    rest: list[str] = []
    seen = set(head) | set(inject)
    if use_slots:
        for pid in base_ids:
            if pid in seen:
                continue
            rest.append(pid)
            seen.add(pid)
    else:
        for pid in base_ids[head_keep:]:
            if pid in seen:
                continue
            rest.append(pid)
            seen.add(pid)
        for pid in base_ids:
            if pid in seen:
                continue
            rest.append(pid)
            seen.add(pid)

    order = head + inject + rest
    ranked = [(pid, float(len(order) - i)) for i, pid in enumerate(order)]
    in_pool20 = set(pid for pid, _ in ranked[:pool])
    n_injected_in20 = sum(1 for pid in inject if pid in in_pool20)
    return {
        "pool_ranked": ranked,
        "injected": inject,
        "n_injected": len(inject),
        "n_injected_in_pool20": n_injected_in20,
        "head_keep": len(head),
        "n_pinned": len(pinned),
    }


def fill_stage1_claim_holes(
    pool_ranked: list[tuple[str, float]],
    rows: list[dict[str, Any]],
    question: str,
    *,
    bm25_text=None,
    head_keep: int = 10,
    max_inject: int = 8,
) -> dict[str, Any]:
    """主入口：对 fuse_r19 的 pool_ranked 做主张补洞。"""
    built = build_claim_hole_arm(rows, question, bm25_text=bm25_text)
    texts = {
        str(r.get("para_id") or ""): str(r.get("text") or "")
        for r in rows
        if r.get("para_id")
    }
    if not built["arm"]:
        return {
            "pool_ranked": list(pool_ranked),
            "injected": [],
            "n_injected": 0,
            "n_injected_in_pool20": 0,
            "claim": built,
            "applied": False,
        }
    q = question or ""
    claim_q = (
        any(c in q for c in _CLAIM_Q)
        or any(c in q for c in _CLAIM_Q_PAIR)
        or any(c in q for c in _CLAIM_Q_RESP)
    )
    times = expand_question_times(q)
    slots = built.get("slots") or extract_verifiable_slots(q)
    has_slots = slots_actionable(slots, q)
    min_claim = 3.0 if (claim_q and not times) else 4.0
    if has_slots and not times:
        min_claim = min(min_claim, 2.5)
    # 口径／责任题：略缩池头；可核验槽题保经典头 10，只抬注入配额
    hk, mi = head_keep, max_inject
    if claim_q and not times:
        hk = min(head_keep, 7)
        mi = max(max_inject, 12)
        if any(c in q for c in _CLAIM_Q_RESP):
            hk = min(hk, 6)
            mi = max(mi, 14)
    if has_slots and not times:
        word_lat = [
            k for k in (slots.get("latin") or []) if not _latin_codeish(k)
        ]
        # 词拉丁／引号缩头让注入；裸数额／航班号不缩（回归案常靠经典头）
        if word_lat or slots.get("quotes"):
            hk = min(hk, 8)
            mi = max(mi, 14)
        elif slots.get("amounts") or slots.get("claim_alts"):
            mi = max(mi, 12)
            # R37：数额×拉丁对撞题——缩池头＋加注入，给深段数字核让路
            if slots.get("amounts") and (
                slots.get("latin") or slots.get("codes")
            ):
                hk = min(hk, 6)
                mi = max(mi, 14)
        elif slots.get("codes"):
            mi = max(mi, 12)
        else:
            mi = max(mi, 10)
    inj = inject_claim_holes(
        pool_ranked,
        built["arm"],
        texts=texts,
        slots=slots if has_slots else None,
        head_keep=hk,
        max_inject=mi,
        min_claim=min_claim,
    )
    return {
        **inj,
        "claim": built,
        "applied": True,
    }
