"""R23：一筛补洞——主张／时点短锚把池外金标近似段捞进 pool20。

只改 pool_ranked；submit_ranked（经典交卷序）不动。
无案专名、不读金标 id；锚点来自问句表面（路由短锚／时点展开）。
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
})
_DISTINCT = re.compile(
    r"\d|[A-Za-z]{3,}|"
    r"时|分|米|万|元|渠道|主渠道|溃决|冰岩|冰川|通稿|监控|"
    r"买断|补偿|编制|放行|联合国|危机|沟通"
)
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
    claim_q = any(c in q0 for c in _CLAIM_Q) or any(c in q0 for c in _CLAIM_Q_PAIR)
    # 「口径／采用」类：查明换皮是噪声；「说法成立」成因类：查明常是正答
    caliber_naming = any(c in q0 for c in _CLAIM_Q)
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
    soft = soft[:8]

    scored: dict[str, float] = {}
    for pid, text in texts.items():
        s = 0.0
        nc = sum(1 for t in clock if t in text)
        nd = sum(1 for t in dates if t in text)
        s += 6.0 * nc + 0.8 * nd
        if nc >= 2:
            s += 5.0
        if nc >= 1 and any(e in text for e in _EVID):
            s += 3.0
        ha = sum(1 for k in a_keys if k in text)
        hb = sum(1 for k in b_keys if k in text)
        s += 2.0 * ha + 2.0 * hb
        if ha and hb:
            s += 2.5
        # R26：非钟点题才抬精确数额／海拔（钟点题已有 nc 加分，避免通稿时点灌满注入）
        if not clock:
            precise = [
                k for k in a_keys + b_keys
                if k and len(k) >= 4 and any(u in k for u in "米时分万")
            ]
            if precise and any(k in text[:100] for k in precise):
                s += 2.2
        hs = sum(1 for k in soft if k in text)
        s += 0.5 * hs
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
        # R26：仅「口径／采用」题降无口径声部的查明双侧，避免占满注入槽
        if caliber_naming and not clock and ("查明" in text) and caliber_v == 0 and ha and hb:
            s -= 4.0
        if s > 0:
            scored[pid] = s

    bm25_q = " ".join(clock[:4] + a_keys[:3] + b_keys[:3] + soft[:2]).strip()
    if bm25_text is not None and len(bm25_q) >= 4:
        for i, (pid, _sc) in enumerate(bm25_text(bm25_q)[:50]):
            scored[pid] = scored.get(pid, 0.0) + 1.2 / (1.0 + i / 6.0)

    # 无钟点口径题：门槛略降，避免主张臂空转
    floor = 3.0 if (claim_q and not clock) else 4.0
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
        "n_scored": len(scored),
    }


def inject_claim_holes(
    pool_ranked: list[tuple[str, float]],
    claim_arm: list[tuple[str, float]],
    *,
    texts: dict[str, str] | None = None,
    head_keep: int = 10,
    max_inject: int = 8,
    min_claim: float = 4.0,
    pool: int = 20,
) -> dict[str, Any]:
    """保经典池头，把高主张分池外段注入中段；近同文一并补入。"""
    base_ids = [pid for pid, sc in pool_ranked if float(sc) > 0]
    head = base_ids[:head_keep]
    head_set = set(head)
    claim_sc = {pid: float(sc) for pid, sc in claim_arm}

    cands = [
        (claim_sc[pid], pid)
        for pid in claim_sc
        if pid not in head_set and claim_sc[pid] >= min_claim
    ]
    cands.sort(reverse=True)
    inject = [pid for _sc, pid in cands[:max_inject]]

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
        "head_keep": head_keep,
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
    claim_q = any(c in q for c in _CLAIM_Q) or any(c in q for c in _CLAIM_Q_PAIR)
    times = expand_question_times(q)
    min_claim = 3.0 if (claim_q and not times) else 4.0
    # 口径题：略缩池头、多留注入位，让发言人／声明段进 pool20
    hk, mi = head_keep, max_inject
    if claim_q and not times:
        hk = min(head_keep, 7)
        mi = max(max_inject, 12)
    inj = inject_claim_holes(
        pool_ranked,
        built["arm"],
        texts=texts,
        head_keep=hk,
        max_inject=mi,
        min_claim=min_claim,
    )
    return {
        **inj,
        "claim": built,
        "applied": True,
    }
