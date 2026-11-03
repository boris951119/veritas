"""R10／R12：盒内二次筛选。不读金标 id。主张族词来自 case_lexicon。

先用已有召回得到候选池，再在池内：
1. 拼段；2. 近同文；3. 综述／评论降权；4. 标题党；
5. 问句主张对齐／跨主张偏题；6. 小节蹭分；7. 伪制度说明；8. 同文真引语。
"""

from __future__ import annotations

import re
from typing import Any

from app.kg_lab.case_lexicon import CaseLexicon, lexicon_for_question
from app.kg_lab.channel_tier import TIERS
from app.kg_lab.source_role import _norm, jaccard_containment, longest_shared_span

TIER_RANK: dict[str, int] = {name: i for i, name in enumerate(TIERS)}

DOWNWEIGHT: dict[str, float] = {
    "mixed_roundup": 0.06,
    "mixed_summary": 0.06,
    "pure_opinion": 0.06,
    "commentary": 0.05,
}
TITLE_BAIT_PENALTY = 0.08
ON_TOPIC_BOOST = 0.05
OFF_TOPIC_PENALTY = 0.06
SECTION_BAIT_PENALTY = 0.06
FAKE_GLOSS_PENALTY = 0.06
_BAIT_BODY_CHARS = 48
_HEADING = re.compile(r"^\d{1,2}月\d{1,2}日")

_SWALLOW_RATIO = 0.80
_SWALLOW_CHARS = 30
_LENGTH_RATIO = 1.12
_VERBATIM_JAC = 0.72


def _lex(question: str, lex: CaseLexicon | None) -> CaseLexicon:
    return lex if lex is not None else lexicon_for_question(question)


def _tier(feat: dict[str, Any]) -> str:
    for name, on in feat.items():
        if str(name).startswith("tier_") and on:
            return str(name)[5:]
    return "other"


def _fine_role(feat: dict[str, Any], meta: dict[str, Any]) -> str:
    role = str(meta.get("fine_role") or "")
    if role:
        return role
    for name, on in feat.items():
        if str(name).startswith("role_") and on:
            return str(name)[5:]
    return ""


def _claim_terms(question: str, lex: CaseLexicon | None = None) -> tuple[str, ...]:
    """问句点到的主张词。没给问句时用已激活／目录全表，单测不必带题面。"""
    L = _lex(question, lex)
    if not (question or "").strip():
        return L.all_claim_surfaces() or tuple(
            t for fam in ("leave", "money", "post") for t in L.terms_for_family(fam)
        )
    surfaces = L.all_claim_surfaces()
    if surfaces:
        return surfaces
    return L.terms_for_family(L.family_of_question(question))


def _body_without_title_echo(title: str, text: str) -> str:
    title_n = _norm(title)
    kept: list[str] = []
    for line in (text or "").replace("\r", "").split("\n"):
        raw = line.strip()
        if not raw:
            continue
        if "原标题" in raw:
            continue
        n = _norm(raw)
        if not n:
            continue
        if title_n and (n == title_n or (len(title_n) >= 12 and title_n in n and len(n) <= len(title_n) + 4)):
            continue
        if n in {"阅读原文", "相关内容", "点击查看", "展开全文"} or n.startswith("阅读原文"):
            continue
        kept.append(raw)
    return "\n".join(kept)


def _title_surface(title: str, text: str) -> str:
    lines = [title or ""]
    for line in (text or "").replace("\r", "").split("\n"):
        if "原标题" in line:
            lines.append(line)
    return "\n".join(lines)


def is_title_bait(
    title: str,
    text: str,
    question: str = "",
    lex: CaseLexicon | None = None,
) -> bool:
    terms = _claim_terms(question, lex)
    if not terms:
        return False
    surface = _title_surface(title, text)
    if not any(t in surface for t in terms):
        return False
    body = _body_without_title_echo(title, text)
    if any(t in body for t in terms):
        return False
    return len(_norm(body)) < _BAIT_BODY_CHARS


def _family(question: str, lex: CaseLexicon | None = None) -> str:
    return _lex(question, lex).family_of_question(question)


def _family_terms(family: str, lex: CaseLexicon | None = None, question: str = "") -> tuple[str, ...]:
    """二筛对题／小节蹭分只用主张原词，不含框架证据词。"""
    L = lex or lexicon_for_question(question)
    return L.surfaces_for_family(family)


def _content_lines(text: str) -> list[str]:
    kept: list[str] = []
    for line in (text or "").replace("\r", "").split("\n"):
        raw = line.strip()
        if not raw or "原标题" in raw:
            continue
        n = _norm(raw)
        if not n or n in {"阅读原文", "相关内容", "点击查看", "展开全文"} or n.startswith("相关内容"):
            continue
        kept.append(raw)
    return kept


def _is_heading_line(line: str, prev: str) -> bool:
    """日期后立刻接逗号的是叙述句，不是小节标题。"""
    if re.match(r"^\d{1,2}月\d{1,2}日[，,]", line):
        return False
    if _HEADING.match(line):
        return True
    return "相关内容" in prev


def _split_body_heading(text: str) -> tuple[str, str]:
    body: list[str] = []
    heads: list[str] = []
    prev = ""
    for line in _content_lines(text):
        if _is_heading_line(line, prev):
            heads.append(line)
        else:
            body.append(line)
        prev = line
    return "\n".join(body), "\n".join(heads)


def _hits(text: str, terms: tuple[str, ...]) -> bool:
    return any(t in (text or "") for t in terms)


def is_section_bait(
    text: str,
    question: str,
    lex: CaseLexicon | None = None,
) -> bool:
    fam = _family(question, lex)
    terms = _family_terms(fam, lex, question)
    if not terms:
        return False
    body, heads = _split_body_heading(text)
    return _hits(heads, terms) and not _hits(body, terms)


def is_offtopic_money(
    text: str,
    feat: dict[str, Any],
    meta: dict[str, Any],
    question: str,
    lex: CaseLexicon | None = None,
) -> bool:
    """主主张族为 leave 时，正文没有 leave 词、只剩 money 族 → 偏题转载。"""
    L = _lex(question, lex)
    if L.family_of_question(question) != "leave":
        return False
    body, _heads = _split_body_heading(text)
    leave = L.surfaces_for_family("leave")
    money = L.surfaces_for_family("money")
    if _hits(body, leave) or not _hits(body, money):
        return False
    role = _fine_role(feat, meta)
    relay = str(feat.get("r9_relay") or "")
    if role == "official_primary" or relay == "relay_official_bulletin":
        return False
    return True


def is_fake_gloss(feat: dict[str, Any], meta: dict[str, Any], lex: CaseLexicon | None = None) -> bool:
    if str(feat.get("r9_comment") or "") != "institutional_gloss":
        return False
    if _fine_role(feat, meta) != "commentary":
        return False
    voices = tuple((lex.official_voice if lex else None) or ())
    if not voices:
        from app.kg_lab.case_lexicon import GENERIC_OFFICIAL_VOICE
        voices = GENERIC_OFFICIAL_VOICE
    return not any(m in str(meta.get("text") or "") for m in voices)


def _on_topic_body(text: str, question: str, lex: CaseLexicon | None = None) -> bool:
    fam = _family(question, lex)
    terms = _family_terms(fam, lex, question)
    if not terms:
        return False
    body, _heads = _split_body_heading(text)
    return _hits(body, terms)


def claim_delta(
    feat: dict[str, Any],
    meta: dict[str, Any],
    question: str,
    lex: CaseLexicon | None = None,
) -> float:
    if not (question or "").strip():
        return 0.0
    text = str(meta.get("text") or "")
    delta = 0.0
    if is_section_bait(text, question, lex):
        delta += SECTION_BAIT_PENALTY
    elif _on_topic_body(text, question, lex):
        delta -= ON_TOPIC_BOOST
    if is_offtopic_money(text, feat, meta, question, lex):
        delta += OFF_TOPIC_PENALTY
    if is_fake_gloss(feat, meta, lex):
        delta += FAKE_GLOSS_PENALTY
    return delta


def _same_leave_quote(a: str, b: str, lex: CaseLexicon | None = None) -> bool:
    # 只用主张原词，不含「还在单位」等框架证据，否则制度说明段会被误并进同引语簇
    leave = (lex.surfaces_for_family("leave") if lex else ()) or (
        "不愿走", "不想走", "未放行", "没让我走", "不让走"
    )
    ba, _ha = _split_body_heading(a)
    bb, _hb = _split_body_heading(b)
    if not _hits(ba, leave) or not _hits(bb, leave):
        return False
    na, nb = _norm(ba), _norm(bb)
    span = longest_shared_span(na, nb, min_len=10)
    if span < 12:
        return False
    shorter = min(len(na), len(nb))
    longer = max(len(na), len(nb))
    if shorter <= 0 or longer / shorter > 1.85:
        return False
    return span / shorter >= 0.20


def _penalty(
    feat: dict[str, Any],
    meta: dict[str, Any],
    question: str = "",
    lex: CaseLexicon | None = None,
) -> float:
    cmt = str(feat.get("r9_comment") or "")
    if cmt:
        base = float(DOWNWEIGHT.get(cmt, 0.0))
    else:
        role = _fine_role(feat, meta)
        base = float(DOWNWEIGHT.get(role, 0.0))
    if is_title_bait(str(meta.get("title") or ""), str(meta.get("text") or ""), question, lex):
        base += TITLE_BAIT_PENALTY
    base += claim_delta(feat, meta, question, lex)
    return base


def _swallows(host: str, piece: str) -> bool:
    nh, np_ = _norm(host), _norm(piece)
    if not nh or not np_ or len(nh) < len(np_) * _LENGTH_RATIO:
        return False
    shared = longest_shared_span(nh, np_)
    if shared < _SWALLOW_CHARS:
        return False
    return shared / len(np_) >= _SWALLOW_RATIO


def _span_text(na: str, nb: str, *, min_len: int = 18) -> str:
    if len(na) < min_len or len(nb) < min_len:
        return ""
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    best = ""
    i = 0
    limit = len(short)
    while i <= limit - min_len:
        if short[i:i + min_len] not in long_:
            i += 1
            continue
        j = min_len
        while i + j <= limit and short[i:i + j] in long_:
            j += 1
        chunk = short[i:i + j - 1]
        if len(chunk) > len(best):
            best = chunk
        i += max(1, len(chunk) // 2)
    return best


def _is_stitch(host: str, piece: str, others: list[str], texts: dict[str, str]) -> bool:
    nh = _norm(texts.get(host) or "")
    span = _span_text(nh, _norm(texts.get(piece) or ""))
    if len(span) < _SWALLOW_CHARS:
        return False
    leftover = nh.replace(span, "", 1)
    if len(leftover) < _SWALLOW_CHARS:
        return False
    for other in others:
        if other in {host, piece}:
            continue
        ob = texts.get(other) or ""
        if _verbatim(texts.get(host) or "", ob) or _verbatim(texts.get(piece) or "", ob):
            continue
        if _swallows(texts.get(host) or "", ob) or _swallows(ob, texts.get(host) or ""):
            continue
        shared = longest_shared_span(leftover, _norm(ob))
        if shared < _SWALLOW_CHARS:
            continue
        if shared / max(len(leftover), 1) >= 0.60:
            return True
    return False


def _verbatim(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    jac, cont = jaccard_containment(na, nb)
    if jac >= _VERBATIM_JAC:
        return True
    shorter = min(len(na), len(nb))
    longer = max(len(na), len(nb))
    return shorter > 0 and cont >= 0.92 and longer / shorter <= 1.45


def _rep_key(
    pid: str,
    texts: dict[str, str],
    feats: dict[str, dict],
    metas: dict[str, dict],
    scores: dict[str, float],
    question: str = "",
    lex: CaseLexicon | None = None,
):
    feat = feats.get(pid) or {}
    meta = metas.get(pid) or {}
    role = _fine_role(feat, meta)
    relay = str(feat.get("r9_relay") or "")
    if role == "official_primary":
        role_rank = 0
    elif role == "party_primary" or relay == "relay_party_primary":
        role_rank = 1
    else:
        role_rank = 2
    penalized = 1 if _penalty(feat, meta, question, lex) > 0 else 0
    tier_rank = TIER_RANK.get(_tier(feat), len(TIER_RANK))
    return (role_rank, penalized, tier_rank, -float(scores.get(pid) or 0.0), pid)


def inbox_rerank(
    ranked: list[tuple[str, float]],
    *,
    texts: dict[str, str],
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    pool: int = 15,
    k: int = 7,
    question: str = "",
    refill: bool = True,
    lex: CaseLexicon | None = None,
) -> dict[str, Any]:
    """候选池 → 去拼段／近同文 → 降权。"""
    L = _lex(question, lex) if (question or "").strip() else lex
    pool_rows = list(ranked)[: max(k, int(pool))]
    scores = {pid: float(sc) for pid, sc in pool_rows}
    ids = [pid for pid, _ in pool_rows]
    swallow_pairs: list[tuple[str, str]] = []
    for host in ids:
        for piece in ids:
            if host == piece:
                continue
            if _swallows(texts.get(host) or "", texts.get(piece) or ""):
                swallow_pairs.append((host, piece))
    stitch_of: dict[str, str] = {}
    for host, piece in swallow_pairs:
        if host in stitch_of:
            continue
        if _is_stitch(host, piece, ids, texts):
            stitch_of[host] = piece
    swallowed = set(stitch_of)
    remain = [pid for pid in ids if pid not in swallowed]

    parent = {pid: pid for pid in remain}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(remain):
        for b in remain[i + 1:]:
            if _verbatim(texts.get(a) or "", texts.get(b) or ""):
                union(a, b)
    for host, piece in swallow_pairs:
        if host in remain and piece in remain:
            union(host, piece)
    if question and L and L.family_of_question(question) == "leave":
        for i, a in enumerate(remain):
            for b in remain[i + 1:]:
                if _same_leave_quote(texts.get(a) or "", texts.get(b) or "", L):
                    union(a, b)
    groups: dict[str, list[str]] = {}
    for pid in remain:
        groups.setdefault(find(pid), []).append(pid)
    dropped_dup: list[str] = []
    kept: list[str] = []
    rep_of: dict[str, str] = {}
    for members in groups.values():
        rep = min(members, key=lambda pid: _rep_key(pid, texts, feats, metas, scores, question, L))
        kept.append(rep)
        for pid in members:
            rep_of[pid] = rep
            if pid != rep:
                dropped_dup.append(pid)

    bait = [
        pid for pid in ids
        if is_title_bait(
            str((metas.get(pid) or {}).get("title") or ""),
            str((metas.get(pid) or {}).get("text") or ""),
            question,
            L,
        )
    ]
    adjusted: list[tuple[str, float, float]] = []
    for pid in kept:
        meta = metas.get(pid) or {}
        pen = _penalty(feats.get(pid) or {}, meta, question, L)
        adjusted.append((pid, scores[pid] - pen, pen))
    adjusted.sort(key=lambda x: (-x[1], x[0]))
    ranked_rows = [
        {"id": pid, "rank": i, "score": round(sc, 6), "penalty": pen}
        for i, (pid, sc, pen) in enumerate(adjusted, 1)
    ]
    by_id = {row["id"]: row for row in ranked_rows}
    if refill:
        submission = ranked_rows[:k]
    else:
        slate = ids[:k]
        passed = {
            pid for pid, _, pen in adjusted
            if pid in set(slate) and pen <= 1e-12
        }
        submission = [by_id[pid] for pid in slate if pid in passed and pid in by_id]
    return {
        "pool_ids": ids,
        "top_ids": [row["id"] for row in submission],
        "submission": [
            {"id": row["id"], "rank": row["rank"], "score": row["score"]}
            for row in submission
        ],
        "order": ranked_rows,
        "scores": {row["id"]: row["score"] for row in submission},
        "penalties": {pid: pen for pid, _, pen in adjusted if pen},
        "title_bait": sorted(bait),
        "swallowed": sorted(swallowed),
        "swallow_of": {host: piece for host, piece in stitch_of.items()},
        "near_dup_dropped": sorted(dropped_dup),
        "rep_of": rep_of,
        "pool": len(ids),
        "k": k,
        "refill": refill,
        "n_final": len(submission),
    }
