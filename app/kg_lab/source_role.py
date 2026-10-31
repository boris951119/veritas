"""通稿近义去重 + 信源角色 prior（R4）。

在 RRF 融合之后、Top-k／装箱截断之前：
1. 同一通报的近义复读簇内只留一个代表（官方原文载体优先）；
2. 按角色加权，不用 source_credibility 浮点当排序键。

不读金标。因果扩圈不在这里。
"""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from app.core.citation_check import normalize
from app.kg_lab.case_lexicon import (
    GENERIC_INSTITUTION,
    GENERIC_PARTY_VOICE,
    CaseLexicon,
)

if TYPE_CHECKING:
    pass

# 融合分乘子。档距故意收窄：只让角色越过「通稿／评论略高于官方」的 RRF 胶着，
# 不足以单靠可信度浮点翻盘（可信度只在同角色代表并列时作 <1 的辅分）。
ROLE_WEIGHT: dict[str, float] = {
    "official_primary": 1.12,
    "institution_def": 1.08,
    "party_claim": 1.05,
    "media_relay": 0.98,
    "commentary": 0.90,
}

ROLE_ORDER: tuple[str, ...] = (
    "official_primary",
    "institution_def",
    "party_claim",
    "media_relay",
    "commentary",
)

_CARRIERS = frozenset({"official_primary", "institution_def"})

# 当事人原话（强标记，无人名）。人名称谓由 lexicon.party_cues() 注入。
_PARTY_STRONG = tuple(GENERIC_PARTY_VOICE) + (
    "再发文",
    "深夜发文",
    "微博发问",
    "他最后说",
    "我一直没有离开",
)

_INSTITUTION = tuple(GENERIC_INSTITUTION)

# 通报里真正定性的句子，不是「持续优化政策」之类尾巴（无人名专名）
_OPERATIVE = (
    "按规定给予了",
    "自主择业经济补偿金",
    "自愿选择自主择业申请",
    "我们予以充分尊重",
    "我们深表敬意",
)


def _party_strong(lex: CaseLexicon | None) -> tuple[str, ...]:
    if lex is None:
        return _PARTY_STRONG
    return tuple(dict.fromkeys(list(_PARTY_STRONG) + list(lex.party_cues())))


def _operative(lex: CaseLexicon | None) -> tuple[str, ...]:
    """只扩当事人敬称模板。不把通报套话整表灌进来，否则短安置句会被抬成 official_primary。"""
    base = list(_OPERATIVE)
    if lex is not None:
        for a in lex.actors:
            if a and not a.endswith(("局", "部", "中心", "委")) and a not in {"官方"}:
                base.append(f"{a}同志是我国优秀")
    return tuple(dict.fromkeys(base))


def _institution(lex: CaseLexicon | None) -> tuple[str, ...]:
    if lex is None:
        return _INSTITUTION
    return tuple(dict.fromkeys(list(_INSTITUTION) + list(lex.institution)))


# R21：可迁移可核验事实槽（禁止案专名）
_TIME_NAIL = re.compile(
    r"\d{4}\s*年\d{1,2}\s*月\d{1,2}\s*日|"
    r"\d{1,2}\s*月\d{1,2}\s*日|"
    r"\d{1,2}\s*时\d{1,2}\s*分|"
    r"北京时间|当地时间"
)
_AMOUNT_NAIL = re.compile(r"\d+(?:\.\d+)?\s*万|\d{2,}\s*元|\$[\d,]+")
_BULLETIN_ATTR = (
    "情况通报", "新闻发布会", "发布会", "联合声明", "新闻稿",
    "通报称", "通报显示", "据通报", "据介绍", "据了解",
    "全文如下", "正式回应", "声明称", "官方称", "官方说",
    "双方同意", "两国元首", "中方称", "外交部", "新闻办公室",
    "调查显示", "监测显示", "记录显示", "数据显示", "按规定",
)
_FACT_ASSERT = (
    "发生", "造成", "宣布", "启动", "建立", "签署", "确认", "证实",
    "认定", "同意建立", "交流", "沟通渠道", "断裂", "查明",
    "established", "agreed to", "signed", "announced", "confirmed",
)
_PURE_OPINION = (
    "热评", "快评", "网友", "舆论", "笔者认为", "或许",
    "值得玩味", "观点文章", "评论区",
)


def verifiable_fact_signals(title: str, text: str, lex: CaseLexicon | None = None) -> dict:
    """可核验事实槽。复合门槛；强可核验才抬 commentary。"""
    blob = (title or "") + "\n" + (text or "")
    body = text or ""
    time_hit = bool(_TIME_NAIL.search(blob))
    amount_hit = bool(_AMOUNT_NAIL.search(blob))
    bulletin = [s for s in _BULLETIN_ATTR if s and s in blob]
    if lex is not None:
        for s in list(lex.bulletin or []) + list(lex.official_voice or []):
            if s and s in blob and s not in bulletin:
                bulletin.append(s)
    operative = [s for s in _operative(lex) if s and s in body]
    fact = [s for s in _FACT_ASSERT if s in body]
    opinion = [s for s in _PURE_OPINION if s in blob]
    score = (
        (0.45 if time_hit else 0.0)
        + (1.0 if amount_hit else 0.0)
        + min(1.6, 0.8 * len(bulletin))
        + min(1.0, 0.5 * len(operative))
        + min(1.0, 0.4 * len(fact))
    )
    compound = (
        (time_hit and amount_hit)
        or (time_hit and bool(bulletin))
        or (time_hit and bool(operative))
        or (amount_hit and bool(bulletin))
        or (bool(bulletin) and bool(fact))
        or (bool(operative) and (time_hit or amount_hit or bool(bulletin)))
        or (time_hit and len(fact) >= 2)
        or (amount_hit and bool(fact))
        or (len(bulletin) >= 2)
    )
    is_verifiable = bool(compound) and score >= 0.9 and not (opinion and score < 1.4)
    headerish = (
        "情况通报" in blob or "新闻发布会" in blob or "联合声明" in blob
        or "发布会介绍" in blob
    )
    strong = bool(operative or amount_hit or headerish or (time_hit and amount_hit))
    return {
        "time_nail": time_hit,
        "amount_nail": amount_hit,
        "bulletin_hits": bulletin,
        "operative_hits": operative,
        "fact_hits": fact,
        "opinion_hits": opinion,
        "score": round(score, 3),
        "is_verifiable": is_verifiable,
        "is_strong_verifiable": bool(strong) and not (opinion and score < 1.0),
        "is_pure_opinion": bool(opinion) and not is_verifiable and score < 1.0,
    }


_MEDIA_FRAME = (
    "回应称",
    "据通报",
    "据了解",
    "据介绍",
    "今天正式回应",
    "全文如下",
    "表示，",
    "表示,",
    "发布该声明",
    "评论员",
    "据《",
    "估算",
)

_COMMENTARY_CUE = (
    "热评",
    "评论",
    "网友",
    "舆论",
    "解读",
    "时间线",
    "尘埃落定",
    "快评",
    "观点",
    "估算",
)

_OUTLET = re.compile(
    r"新华网|看看新闻|人民日报|南方网|央视|网易|凤凰|腾讯|联合早报|"
    r"上观|大众新闻|虎嗅|财新|澎湃|新浪|搜狐|环球|观察者"
)
_TITLE_BUREAU = re.compile(r"体育局.{0,12}(回应|通报|发布)")


def portable_role_from(
    title: str,
    text: str,
    fine_role: str,
    lex: CaseLexicon | None = None,
) -> str:
    """披露／二筛用可迁移角色：强可核验的 commentary 视为 media_relay。

    不改 fine_role（一筛系数仍吃 R20 角色分布）。
    """
    role = fine_role or "commentary"
    vf = verifiable_fact_signals(title, text, lex=lex)
    if role in {"commentary", "mixed_summary"} and vf.get("is_strong_verifiable"):
        return "media_relay"
    if role in {"commentary", "mixed_summary"} and vf.get("is_verifiable") and not vf.get("is_pure_opinion"):
        return "media_relay"
    return role


def infer_source_role(
    title: str,
    text: str,
    credibility: float | None = None,
    lex: CaseLexicon | None = None,
) -> dict[str, Any]:
    """段级粗角色。credibility 只回传，不参与归类。"""
    title = title or ""
    text = text or ""
    blob = title + "\n" + text
    signals: list[str] = []

    party_cues = _party_strong(lex)
    party = [s for s in party_cues if s in text]
    inst = [s for s in _institution(lex) if s in text]
    operative = [s for s in _operative(lex) if s in text]
    media = [s for s in _MEDIA_FRAME if s in text]
    commentary = [s for s in _COMMENTARY_CUE if s in blob]

    # 当事人原话优先于制度句，除非整段是在解释办法而不是引语
    party_keep = ("不是我不想走", "没让我走", "再发文") + tuple(
        c for c in party_cues if c.endswith(("表示", "直言", "称"))
    )
    if party and not (inst and not any(s in text for s in party_keep)):
        signals.append("party_speech")
        role = "party_claim"
    elif inst and not operative:
        signals.append("statute")
        role = "institution_def"
    elif operative and not media:
        signals.append("bulletin_operative")
        role = "official_primary"
    elif operative and media:
        signals.append("relay_frame")
        role = "media_relay"
    elif commentary or (media and not operative):
        signals.append("commentary_cue" if commentary else "media_frame")
        role = "commentary" if commentary and not operative else (
            "media_relay" if media else "commentary"
        )
    else:
        role = "commentary"
        signals.append("default")

    if _TITLE_BUREAU.search(title):
        signals.append("title_bureau")
    if "情况通报" in title or "情况通报" in text:
        signals.append("bulletin_header")
    return {
        "role": role,
        "signals": signals,
        "credibility": credibility,
        "weight": ROLE_WEIGHT[role],
    }


# 细角色。R4 粗角色仍是去重／默认乘子的键；细角色只在传入权重表时改乘子。
# 平台可信度不参与归类：微博本人说即使 cred 很低也是 party_primary。
FINE_ROLES: tuple[str, ...] = (
    "official_primary",
    "official_reprint",
    "institution_def",
    "party_primary",
    "party_relay",
    "opposition_framing",
    "mixed_summary",
    "media_relay",
    "commentary",
)

# 与 R4 粗乘子对齐的起点：转载仍按原文 1.12，混口径仍按评论 0.90。
# 扫参从这个表出发改轴，默认臂不读它。
# R5 扫参推荐（hold_reprint_press_mixed）：转载不降，本人渠道抬，对立／混口径／评论下压。
R5_RECOMMENDED: dict[str, float] = {
    "official_primary": 1.12,
    "official_reprint": 1.12,
    "institution_def": 1.08,
    "party_primary": 1.14,
    "party_relay": 1.05,
    "opposition_framing": 0.92,
    "mixed_summary": 0.76,
    "media_relay": 0.98,
    "commentary": 0.84,
}

R4_FINE_EQUIV: dict[str, float] = {
    "official_primary": 1.12,
    "official_reprint": 1.12,
    "institution_def": 1.08,
    "party_primary": 1.05,
    "party_relay": 1.05,
    "opposition_framing": 1.05,
    "mixed_summary": 0.90,
    "media_relay": 0.98,
    "commentary": 0.90,
}

_FIRST_PERSON = (
    "我已经",
    "由我来说",
    "我一直没有离开",
    "我于",
    "今后与",
)
_WEIBO = ("微博", "发微博")
_WIRE = re.compile(r"新华社|记者|电（|评论员")


def infer_fine_role(
    title: str,
    text: str,
    credibility: float | None = None,
    lex: CaseLexicon | None = None,
) -> dict[str, Any]:
    """在 R4 粗角色上再拆：原文/转载、本人/转述、对立包装、混口径。

    credibility 只回传。问句主体的本人渠道（主体名由 lexicon 注入＋微博／第一人称）
    标 party_primary，不看平台分。
    """
    coarse = infer_source_role(title, text, credibility, lex=lex)
    role = str(coarse["role"])
    signals = list(coarse["signals"])
    blob = (title or "") + "\n" + (text or "")
    head = (text or "")[:80]
    wire = bool(_WIRE.search((title or "") + "\n" + head))
    weibo = any(s in blob for s in _WEIBO)
    first = any(s in (text or "") for s in _FIRST_PERSON) or (
        "不是我不想走" in (text or "") and "全文如下" in (text or "")
    )
    channel = "other"
    if weibo and first and not wire:
        channel = "weibo_self"
    elif weibo:
        channel = "weibo_cited"
    elif wire:
        channel = "wire"
    elif role == "official_primary" and not _OUTLET.search(title or ""):
        channel = "bureau"

    actors = list(lex.actors) if lex is not None else []
    actor_headline = any(
        f"{a}：" in (title or "") or f"{a}称" in (title or "") for a in actors
    )
    bureau_page = (
        role == "official_primary"
        and not _OUTLET.search(title or "")
        and not actor_headline
    )
    if role == "official_primary" and not bureau_page:
        role = "official_reprint"
        signals.append("reprint_outlet_or_headline")
    elif role == "official_primary" and bureau_page:
        signals.append("bureau_primary")

    # 本人渠道压过对立包装：微博上的「我」不是通讯社转述。
    if first and not wire and (
        "全文如下" in (text or "") or weibo or "我已经" in (text or "") or "由我来说" in (text or "")
    ):
        role = "party_primary"
        signals.append("subject_own_channel")
    elif coarse["role"] == "party_claim":
        # 对立包装：金钱族词与评论标题线索（词表可注入）
        money_hit = False
        if lex is not None:
            money_hit = any(t in blob for t in lex.terms_for_family("money"))
        else:
            money_hit = any(t in blob for t in ("买断", "补偿", "自主择业", "二选一"))
        conflict = (
            money_hit
            or "热评" in (title or "")
            or "评论" in (title or "")
        )
        if conflict:
            role = "opposition_framing"
            signals.append("opposition_frame")
        else:
            role = "party_relay"
            signals.append("party_attributed")

    if role == "commentary":
        money_or_speech = any(t in (text or "") for t in ("他发", "他说"))
        if lex is not None:
            money_or_speech = money_or_speech or any(
                t in (text or "") for t in lex.terms_for_family("money")
            )
        else:
            money_or_speech = money_or_speech or ("买断" in (text or ""))
        procedure = any(t in (text or "") for t in ("补偿", "手续", "自主择业"))
        mixes = money_or_speech and procedure
        timeline = any(s in blob for s in ("尘埃落定", "时间线", "大结局"))
        if mixes and (timeline or (text or "").count("月") >= 2):
            role = "mixed_summary"
            signals.append("mixed_caliber")

    # R21：强可核验不得停在 commentary／mixed_summary
    if role == "official_primary":
        channel = "bureau"
    elif role == "official_reprint":
        channel = "reprint"
    elif role == "party_primary":
        channel = "weibo_self" if weibo else "self_post"
    elif role in {"party_relay", "opposition_framing"} and weibo:
        channel = "weibo_cited"
    elif wire and role in {"party_relay", "opposition_framing", "media_relay"}:
        channel = "wire"

    return {
        "role": role,
        "coarse": coarse["role"],
        "signals": signals,
        "channel": channel,
        "credibility": credibility,
        "coarse_weight": coarse["weight"],
    }


def _norm(text: str) -> str:
    return normalize(text or "")


def _bigrams(normed: str) -> set[str]:
    if len(normed) < 2:
        return set()
    return {normed[i:i + 2] for i in range(len(normed) - 1)}


def jaccard_containment(na: str, nb: str) -> tuple[float, float]:
    a, b = _bigrams(na), _bigrams(nb)
    if not a or not b:
        return 0.0, 0.0
    inter = len(a & b)
    jac = inter / len(a | b)
    shorter = a if len(a) <= len(b) else b
    cont = inter / len(shorter) if shorter else 0.0
    return jac, cont


def longest_shared_span(na: str, nb: str, *, min_len: int = 18) -> int:
    """两段归一化正文的最长公共子串（用于「同一句通报被转述」）。"""
    if len(na) < min_len or len(nb) < min_len:
        return 0
    if len(na) > len(nb):
        na, nb = nb, na
    grams = {nb[i:i + min_len] for i in range(0, len(nb) - min_len + 1)}
    best = 0
    i = 0
    n = len(na)
    while i <= n - min_len:
        if na[i:i + min_len] not in grams:
            i += 1
            continue
        j = min_len + 1
        while i + j <= n and na[i:i + j] in nb:
            j += 1
        best = max(best, j - 1)
        i += max(1, (j - 1) // 2)
    return best


def _verbatim(na: str, nb: str) -> bool:
    """几乎同一段（转载），不是「短切片被长拼接包含」。"""
    jac, cont = jaccard_containment(na, nb)
    if jac >= 0.72:
        return True
    shorter = min(len(na), len(nb))
    longer = max(len(na), len(nb))
    if shorter <= 0:
        return False
    return jac >= 0.50 and cont >= 0.92 and (longer / shorter) <= 1.45


def carrier_points(meta: dict[str, Any]) -> float:
    """同簇选代表：角色档 >> 通报载体线索 >> 可信度辅分（跨不过角色）。"""
    role = str(meta.get("role") or "commentary")
    try:
        role_pts = (len(ROLE_ORDER) - ROLE_ORDER.index(role)) * 100
    except ValueError:
        role_pts = 0
    title = str(meta.get("title") or "")
    text = str(meta.get("text") or "")
    bonus = 0.0
    if role == "official_primary":
        if "情况通报" in text:
            bonus += 4
        elif "情况通报" in title:
            bonus += 3
        # 标题本身就是《情况通报》的载体，优先于「发布情况通报：将持续优化…_人民日报」这类改写题
        head = title.split("_")[0].split("-")[0].strip()
        if title.startswith("情况通报") or head == "情况通报":
            bonus += 3
        if _TITLE_BUREAU.search(title):
            bonus += 2
        # 回应争议点的通报句（金额／安置类通用线索，无人名）
        if re.search(r"回应.{0,8}(买断|补偿|安置)|(?:买断|补偿|安置).{0,6}问题", text):
            bonus += 2
        markers = sum(1 for s in _OPERATIVE if s in text)
        bonus += min(3, markers)
        if _OUTLET.search(title):
            bonus -= 1
        else:
            bonus += 2
    cred = meta.get("credibility")
    cred_pts = float(cred) * 0.2 if isinstance(cred, (int, float)) else 0.0
    return float(role_pts) + bonus + cred_pts


def _meta_from_row(row: dict[str, Any], lex: CaseLexicon | None = None) -> dict[str, Any]:
    title = str(row.get("title") or "")
    text = str(row.get("text") or "")
    cred = row.get("source_credibility")
    if cred is not None and not isinstance(cred, (int, float)):
        cred = None
    cred_f = cred if cred is None else float(cred)
    info = infer_source_role(title, text, cred_f, lex=lex)
    fine = infer_fine_role(title, text, cred_f, lex=lex)
    na = _norm(text)
    return {
        "para_id": str(row.get("para_id") or ""),
        "doc_id": str(row.get("doc_id") or ""),
        "title": title,
        "text": text,
        "publish_time": str(row.get("publish_time") or ""),
        "norm": na,
        "role": info["role"],
        "fine_role": fine["role"],
        "portable_role": portable_role_from(title, text, str(fine["role"]), lex=lex),
        "channel": fine["channel"],
        "signals": fine["signals"],
        "credibility": info["credibility"],
        "weight": info["weight"],
    }


def cluster_representatives(
    metas: dict[str, dict[str, Any]],
    *,
    prefer_ids: set[str] | None = None,
    scores: dict[str, float] | None = None,
) -> dict[str, str]:
    """para_id → 簇代表。

    官方／制度段之间只按近重复并（避免把通报的相邻切片并成一段）。
    转述／评论最多挂到一个载体上，按最长共享句，不把两个载体串起来。
    """
    ids = [pid for pid, m in metas.items() if m.get("norm")]
    carriers = [pid for pid in ids if metas[pid]["role"] in _CARRIERS]
    parent = {pid: pid for pid in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(carriers):
        na = metas[a]["norm"]
        for b in carriers[i + 1:]:
            if _verbatim(na, metas[b]["norm"]):
                union(a, b)

    attached: dict[str, str] = {}
    attach_shared: dict[str, int] = {}
    for pid in ids:
        if metas[pid]["role"] in _CARRIERS:
            continue
        if metas[pid]["role"] == "party_claim":
            continue
        na = metas[pid]["norm"]
        best_root = ""
        best_key = (-1, -1.0)
        for c in carriers:
            nb = metas[c]["norm"]
            jac, _cont = jaccard_containment(na, nb)
            if jac < 0.15:
                continue
            shared = longest_shared_span(na, nb)
            if shared < 22:
                continue
            shorter = min(len(na), len(nb))
            if shorter <= 0 or shared / shorter < 0.20:
                continue
            root = find(c)
            key = (shared, carrier_points(metas[c]))
            if key > best_key:
                best_key = key
                best_root = root
        if best_root:
            attached[pid] = best_root
            attach_shared[pid] = best_key[0]

    orphans = [
        pid for pid in ids
        if pid not in attached and metas[pid]["role"] not in _CARRIERS
    ]
    for i, a in enumerate(orphans):
        na = metas[a]["norm"]
        for b in orphans[i + 1:]:
            if _verbatim(na, metas[b]["norm"]):
                union(a, b)

    groups: dict[str, list[str]] = {}
    for pid in ids:
        if pid in attached:
            root = attached[pid]
        else:
            root = find(pid)
        groups.setdefault(root, []).append(pid)
        if pid in attached:
            # 被挂上的转述不在载体 union 里，补进组成员
            pass
    # 载体 find 的成员 + attached
    # 上面的循环已把 attached 放进 root 组；载体成员走 find。避免重复。
    for root, members in list(groups.items()):
        groups[root] = list(dict.fromkeys(members))

    kept = set(prefer_ids or ())

    def _rep_key(pid: str) -> tuple:
        pts = carrier_points(metas[pid])
        # 有检索分时，可信度浮点不再决定同角色代表（0.85 不应压过 0.7 的同文）
        if scores is not None:
            cred = metas[pid].get("credibility")
            if isinstance(cred, (int, float)):
                pts -= float(cred) * 0.2
            sc = float(scores.get(pid) or 0.0)
        else:
            sc = 0.0
        # prefer_ids 只决定簇里留下哪一个 id，不加分
        return (0 if pid in kept else 1, -pts, -sc, pid)

    rep_of: dict[str, str] = {}
    for members in groups.values():
        # 默认同分取更早的 para_id（doc_024 先于 doc_039）
        rep = min(members, key=_rep_key)
        for pid in members:
            rep_of[pid] = rep
    for pid in metas:
        rep_of.setdefault(pid, pid)
    return rep_of


def rerank_source_role(
    rows: list[dict[str, Any]],
    fused: list[tuple[str, float]],
    *,
    dedupe: bool = True,
    role_prior: bool = True,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """RRF 名单 → 角色加权 → 通稿簇替换代表 → 仍按分数降序。

    代表占「簇内最高分」那个名次：转述排在官方前面时，名次留给官方原文。
    weights 按细角色覆盖乘子；缺省＝R4 粗角色乘子。去重仍用粗角色。
    """
    metas = {str(r["para_id"]): _meta_from_row(r) for r in rows if r.get("para_id")}
    if weights:
        for meta in metas.values():
            fine = str(meta.get("fine_role") or "")
            if fine in weights:
                meta["weight"] = float(weights[fine])
    score_raw = {pid: float(sc) for pid, sc in fused}
    weighted: list[tuple[str, float]] = []
    for pid, sc in fused:
        meta = metas.get(pid)
        w = meta["weight"] if (meta and role_prior) else 1.0
        weighted.append((pid, float(sc) * float(w)))
    weighted.sort(key=lambda x: (-x[1], x[0]))

    rep_of = cluster_representatives(metas) if dedupe else {pid: pid for pid in metas}
    # 簇内最高加权分，用来把代表放到簇的最佳名次
    cluster_best: dict[str, float] = {}
    for pid, sc in weighted:
        rep = rep_of.get(pid, pid)
        prev = cluster_best.get(rep)
        if prev is None or sc > prev:
            cluster_best[rep] = sc

    emitted: set[str] = set()
    ranked: list[tuple[str, float]] = []
    substitutions: list[dict[str, Any]] = []
    for pid, sc in weighted:
        rep = rep_of.get(pid, pid)
        if rep in emitted:
            continue
        emitted.add(rep)
        out_sc = cluster_best.get(rep, sc) if dedupe else sc
        ranked.append((rep, round(out_sc, 6)))
        if rep != pid:
            substitutions.append({
                "trigger": pid,
                "representative": rep,
                "trigger_role": (metas.get(pid) or {}).get("role"),
                "rep_role": (metas.get(rep) or {}).get("role"),
                "trigger_score": round(sc, 6),
                "rep_raw_rrf": score_raw.get(rep),
            })

    # 代表自己的原始名次更靠前时，上面的首次出现已经用了簇最高分；
    # 若代表不在 fused 里（分数 0），仍允许替换进名单——只发生在近义规则命中时。
    ranked.sort(key=lambda x: (-x[1], x[0]))
    # 去掉排序后可能的重复（理论上 emitted 已保证唯一）
    seen: set[str] = set()
    uniq: list[tuple[str, float]] = []
    for pid, sc in ranked:
        if pid in seen:
            continue
        seen.add(pid)
        uniq.append((pid, sc))

    roles = {pid: metas[pid]["role"] for pid in metas}
    fine_roles = {pid: metas[pid].get("fine_role") for pid in metas}
    table = dict(weights) if weights else dict(ROLE_WEIGHT)
    return {
        "ranked": uniq,
        "roles": roles,
        "fine_roles": fine_roles,
        "substitutions": substitutions,
        "role_weight": table if role_prior else {k: 1.0 for k in table},
        "dedupe": dedupe,
        "role_prior": role_prior,
        "n_clusters_touched": len({rep_of.get(p, p) for p, _ in fused if rep_of.get(p, p) != p}),
    }
