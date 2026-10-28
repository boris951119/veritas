"""C-72 要点槽（零 LLM）：从问句抽通用切面，每槽绑可定位证据或显式缺口。

开关 VERITAS_CLAIM_SLOTS（默认 False）。关＝本模块全部空操作，导出与改前逐字相同。
三条禁线：不用金标词表、不写六案专用分支、不把槽做成相关性打分。

R-C72-1：覆盖率拆 bound／真 gap／盖章三数；主席旗改「gloss 数字与时点须逐字可定位」；
词表纯净可被测试钉死。
"""

from __future__ import annotations

import re

from app.core.evidence import Dossier

_CLAIM_SLOTS = False

GAP_MARK = "资料未覆盖该要点"
STAMP_PREFIX = "【程序盖章】"

# 通用切面：只看问句形态，不碰金标／案名。
_SLOT_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("cause", "原因或归因", (
        "原因", "为何", "为什么", "归因", "导致", "因为", "所致", "引发",
    )),
    ("status", "当前状态", (
        "现状", "目前", "当前", "现在", "进展", "态势", "是否真有",
    )),
    ("number", "关键数字", (
        "多少", "几人", "几成", "人数", "数量", "万元", "死亡", "伤亡",
        "比例", "几名", "多少人",
    )),
    ("time", "关键时点", (
        "何时", "什么时候", "时刻", "哪年", "时间", "日期", "截止",
        "几月", "就绪", "起始",
    )),
)

# what 档线索（与 _SLOT_SPECS 一并进纯净检查）
_WHAT_CUES: tuple[str, ...] = ("发生", "是否", "哪一", "还是", "什么", "如何", "能否")

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_LATIN = re.compile(r"[A-Za-z]{3,}")
_DIGITS = re.compile(r"\d+")
_HAS_DIGIT = re.compile(r"\d")

# 主席 gloss 里必须逐字落进支撑段的锚：数字串 + 时点串
_GLOSS_TIME = re.compile(
    r"(?:"
    r"\d{4}年\d{1,2}月\d{1,2}日"
    r"|\d{4}年\d{1,2}月"
    r"|\d{1,2}月\d{1,2}日"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}时\d{1,2}分(?:\d{1,2}秒)?"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
    r")"
)


def set_claim_slots(on: bool) -> None:
    global _CLAIM_SLOTS
    _CLAIM_SLOTS = bool(on)


def claim_slots_enabled() -> bool:
    return bool(_CLAIM_SLOTS)


def slot_cue_vocab() -> set[str]:
    """全部槽位线索词（供纯净格钉死；不含案名／金标）。"""
    out: set[str] = set(_WHAT_CUES)
    for _sid, _label, cues in _SLOT_SPECS:
        out.update(cues)
    return out


def case_gold_forbidden_tokens() -> set[str]:
    """六案案名 ∪ 金标侧常见专名／结论锚（只作禁入词表，不进模型输入）。

    宁可多列专名，不可把通用切面词（原因／是否／多少…）放进来。
    """
    return {
        # 案名碎片
        "泥石流", "吉隆", "吉隆口岸",
        "discouraged", "王虹", "北大",
        "AI171", "空难", "印度航空",
        "刘翔", "二选一", "编制",
        "柬泰", "柬埔寨", "F-16",
        "中美AI", "WIRED", "OpenAI", "Anthropic",
        # 架构师 K6 当场塞过的案专用词
        "红机",
        # 金标／通稿高频专名（非通用切面）
        "冰湖溃决", "冰岩崩", "买断费", "自主择业",
    }


def cue_case_gold_intersection() -> set[str]:
    """线索词表 ∩（六案案名∪金标 token）；非空＝禁止项③ 破。"""
    return slot_cue_vocab() & case_gold_forbidden_tokens()


def _tokens(text: str) -> set[str]:
    q = text or ""
    out: set[str] = set()
    for run in _CJK.findall(q):
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    for word in _LATIN.findall(q):
        out.add(word.lower())
    out.update(_DIGITS.findall(q))
    return out


def extract_slots(question: str) -> list[dict]:
    """从问句抽必要切面。空问句 → 空列表；否则至少一档「发生什么」。"""
    q = (question or "").strip()
    if not q:
        return []
    slots: list[dict] = []
    slots.append({
        "id": "what",
        "label": "发生什么",
        "cues": _WHAT_CUES,
    })
    for sid, label, cues in _SLOT_SPECS:
        hit = any(c in q for c in cues)
        if sid == "number" and not hit:
            hit = bool(_HAS_DIGIT.search(q))
        if hit:
            slots.append({"id": sid, "label": label, "cues": cues})
    return slots


def _quote_locatable(dossier: Dossier, ev) -> bool:
    """引文须在所指段落原文里逐字可定位；定位不上＝凑出来的槽。"""
    quote = (ev.quote or "").strip()
    if not quote:
        return False
    for sid in ev.segment_ids or []:
        seg = dossier.segment(sid)
        if seg is not None and quote in (seg.text or ""):
            return True
    return False


def _support_blob(dossier: Dossier, con_id: str) -> str:
    parts: list[str] = []
    for ev in dossier.evidences_of(con_id):
        hit = False
        for sid in ev.segment_ids or []:
            seg = dossier.segment(sid)
            if seg is not None and (seg.text or ""):
                parts.append(seg.text or "")
                hit = True
        if not hit:
            parts.append(ev.quote or "")
        parts.append(ev.note or "")
    return "\n".join(parts)


def _slot_covered_by_text(slot: dict, text: str) -> bool:
    """槽与文本有可辨识交集即视为说到了该切面（非相关性打分）。"""
    blob_tok = _tokens(text)
    if not blob_tok:
        return False
    if any(c in (text or "") for c in slot.get("cues") or ()):
        return True
    label_tok = _tokens(slot.get("label") or "")
    if label_tok & blob_tok:
        return True
    return False


def _model_gap_corpus(dossier: Dossier) -> str:
    """只读模型写过的面（statement／note／open_issues）。

    ⚠ 不许读 accounting['claim_slots']——否则程序盖章会在二次评估里冒充真缺口。
    """
    bits: list[str] = []
    for con in dossier.conclusions:
        bits.append(con.statement or "")
        for ev in dossier.evidences_of(con.id):
            bits.append(ev.note or "")
    synth = dossier.synthesis or {}
    for issue in synth.get("open_issues") or []:
        if not isinstance(issue, dict):
            continue
        text = str(issue.get("text") or "")
        # 程序盖章写进 open_issues 的也不算真缺口
        if text.startswith(STAMP_PREFIX):
            continue
        bits.append(text)
    return "\n".join(bits)


def assess_slot_rows(dossier: Dossier) -> list[dict]:
    """每槽一行：bound／gap／empty／bogus。关旗 → []。

    gap＝模型自己写了「资料未覆盖该要点」；empty＝留空（尚未盖章）。
    """
    if not claim_slots_enabled():
        return []
    slots = extract_slots(dossier.question or "")
    rows: list[dict] = []
    gap_blob = _model_gap_corpus(dossier)
    # 缺口子句本身含槽标签，不可当作「说到了该切面」的绑定证据
    _gap_clause = re.compile(re.escape(GAP_MARK) + r"[：:].{0,40}")
    for slot in slots:
        sid = slot["id"]
        label = slot["label"]
        gap_hit = (
            f"{GAP_MARK}：{label}" in gap_blob
            or f"{GAP_MARK}:{label}" in gap_blob
            or (GAP_MARK in gap_blob and label in gap_blob)
        )
        # 模型已显式写缺口 → 优先记真 gap（不许被缺口文案自己绑成 bound）
        if gap_hit:
            rows.append({
                "id": sid, "label": label, "status": "gap",
                "evidence_id": None,
                "detail": f"{GAP_MARK}：{label}",
                "stamped": False,
            })
            continue
        bound_ev = None
        bogus = False
        for con in dossier.conclusions:
            if con.status not in ("majority", "dissent", "insufficient"):
                continue
            for ev in dossier.evidences_of(con.id):
                locatable = _quote_locatable(dossier, ev)
                raw = f"{ev.note or ''}{con.statement or ''}{ev.quote or ''}"
                note = _gap_clause.sub("", raw)
                talks = _slot_covered_by_text(slot, note) or _slot_covered_by_text(
                    slot, _support_blob(dossier, con.id))
                if talks and locatable:
                    bound_ev = ev.id
                    break
                if talks and not locatable and (ev.quote or "").strip():
                    bogus = True
            if bound_ev:
                break
        if bound_ev:
            rows.append({
                "id": sid, "label": label, "status": "bound",
                "evidence_id": bound_ev, "detail": "", "stamped": False,
            })
        elif bogus:
            rows.append({
                "id": sid, "label": label, "status": "bogus",
                "evidence_id": None, "detail": "引文逐字定位不上",
                "stamped": False,
            })
        else:
            rows.append({
                "id": sid, "label": label, "status": "empty",
                "evidence_id": None, "detail": "留空",
                "stamped": False,
            })
    return rows


def stamp_uncovered_gaps(dossier: Dossier) -> list[dict]:
    """把 empty 槽盖成 stamped_gap（披露用，不算答到要点）。"""
    if not claim_slots_enabled():
        return []
    rows = assess_slot_rows(dossier)
    stamped: list[dict] = []
    for row in rows:
        if row["status"] == "empty":
            detail = f"{STAMP_PREFIX}{GAP_MARK}：{row['label']}"
            stamped.append({
                **row,
                "status": "stamped_gap",
                "detail": detail,
                "stamped": True,
            })
        else:
            stamped.append(dict(row))
    return stamped


def slot_coverage(rows: list[dict]) -> dict:
    """分开报三个数；ok 不许建立在盖章之后。

    - bound_rate＝真绑证据／总槽
    - true_gap_rate＝模型自写缺口／总槽
    - stamped_rate＝程序盖章／总槽
    - ok＝全部为 bound|gap（真缺口），且无 empty／bogus／stamped_gap
    """
    n = len(rows)
    n_bound = sum(1 for r in rows if r.get("status") == "bound")
    n_true_gap = sum(
        1 for r in rows
        if r.get("status") == "gap" and not r.get("stamped")
    )
    n_stamped = sum(
        1 for r in rows
        if r.get("stamped") or r.get("status") == "stamped_gap"
    )
    n_bogus = sum(1 for r in rows if r.get("status") == "bogus")
    n_empty = sum(1 for r in rows if r.get("status") == "empty")
    n_honest = n_bound + n_true_gap
    bound_rate = (n_bound / n) if n else 1.0
    true_gap_rate = (n_true_gap / n) if n else 0.0
    stamped_rate = (n_stamped / n) if n else 0.0
    honest_rate = (n_honest / n) if n else 1.0
    ok = (
        n == 0
        or (n_empty == 0 and n_bogus == 0 and n_stamped == 0 and n_honest == n)
    )
    return {
        "n_slots": n,
        "n_bound": n_bound,
        "n_true_gap": n_true_gap,
        "n_stamped": n_stamped,
        "n_bogus": n_bogus,
        "n_empty": n_empty,
        "bound_rate": bound_rate,
        "true_gap_rate": true_gap_rate,
        "stamped_rate": stamped_rate,
        "n_covered_honest": n_honest,
        "honest_rate": honest_rate,
        # 兼容旧键：rate／n_covered 只反映诚实覆盖（不含盖章）
        "n_covered": n_honest,
        "rate": honest_rate,
        "ok": ok,
    }


def claim_slots_prompt(dossier: Dossier) -> str:
    """注入分析师提示：逐槽交证或显式缺口。关旗／无槽 → 空串。"""
    if not claim_slots_enabled():
        return ""
    slots = extract_slots(dossier.question or "")
    if not slots:
        return ""
    lines = [
        "",
        "要点槽（程序从问句导出的通用切面；禁止留空、禁止硬凑）：",
    ]
    for s in slots:
        lines.append(
            f"- {s['id']}（{s['label']}）：要么挂逐字可定位证据，"
            f"要么在 statement／note 写「{GAP_MARK}：{s['label']}」。"
        )
    lines.append(
        "不许用外部金标词表；不许把槽当成相关性打分；"
        "资料没有就写缺口，不要拼宽引文。"
    )
    return "\n".join(lines)


def gloss_anchor_tokens(gloss: str) -> list[str]:
    """主席 gloss 里必须在支撑段逐字可定位的数字与时点锚。"""
    g = gloss or ""
    anchors: list[str] = []
    for m in _GLOSS_TIME.finditer(g):
        anchors.append(m.group(0))
    # 数字串（长度≥1）；去掉已被时点串覆盖的子串重复
    covered = set(anchors)
    for m in _DIGITS.finditer(g):
        tok = m.group(0)
        if any(tok in a for a in covered):
            continue
        anchors.append(tok)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for a in anchors:
        if a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out


def chair_support_flags(dossier: Dossier) -> list[dict]:
    """主席采纳要点的数字／时点锚落不进提交结论支撑段 → 披露旗。

    R-C72-1：不再用二元组交集（真产物上恒不触发）；改为 gloss 内数字与时点
    必须在支撑段逐字可定位，定位不到才出旗。无数字／时点锚的 gloss 本条不启。
    """
    if not claim_slots_enabled():
        return []
    submitted = None
    for con in dossier.conclusions:
        if con.status == "majority" and con.evidence_ids:
            submitted = con
            break
    if submitted is None:
        return []
    blob = _support_blob(dossier, submitted.id)
    flags: list[dict] = []
    synth = dossier.synthesis or {}
    for pt in synth.get("points") or []:
        if not isinstance(pt, dict):
            continue
        gloss = str(pt.get("gloss") or "").strip()
        if not gloss:
            continue
        con_id = str(pt.get("con_id") or "")
        anchors = gloss_anchor_tokens(gloss)
        if not anchors:
            continue
        missing = [a for a in anchors if a not in blob]
        if not missing:
            continue
        joined = "、".join(missing)
        flags.append({
            "kind": "chair_support_gap",
            "severity": "medium",
            "conclusion_id": submitted.id,
            "value": joined,
            "detail": (
                f"主席采纳要点「{gloss[:40]}」"
                f"（con_id={con_id or '—'}）中的数字／时点锚"
                f"「{joined}」未能在提交结论 {submitted.id} 的支撑段落逐字定位；"
                f"未改提交文本、未拼宽证据"
            ),
        })
    return flags


def chair_support_zero_disclosure(n_flags: int) -> dict:
    """真产物／单案扫描旗数＝0 时必须显式披露（防悄悄变哑）。"""
    if n_flags == 0:
        return {
            "n_flags": 0,
            "zero_trigger_disclosed": True,
            "note": "主席支撑旗扫描＝0（已显式披露，非静默变哑）",
        }
    return {
        "n_flags": n_flags,
        "zero_trigger_disclosed": False,
        "note": f"主席支撑旗扫描＝{n_flags}",
    }


def apply_claim_slots(dossier: Dossier) -> dict:
    """管线钩子：评估＋盖缺口＋主席支撑旗 → accounting['claim_slots']。关旗空操作。"""
    if not claim_slots_enabled():
        return {}
    rows = stamp_uncovered_gaps(dossier)
    cov = slot_coverage(rows)
    flags = chair_support_flags(dossier)
    zero = chair_support_zero_disclosure(len(flags))
    rec = {
        "rows": rows,
        "coverage": cov,
        "chair_support_flags": flags,
        "n_chair_support_flags": len(flags),
        "chair_support_scan": zero,
        # 交账三数快照（与 coverage 同口径，便于披露一眼看见）
        "bound_rate": cov["bound_rate"],
        "true_gap_rate": cov["true_gap_rate"],
        "stamped_rate": cov["stamped_rate"],
        "n_bound": cov["n_bound"],
        "n_true_gap": cov["n_true_gap"],
        "n_stamped": cov["n_stamped"],
    }
    dossier.accounting["claim_slots"] = rec
    if any(r.get("stamped") for r in rows):
        synth = dict(dossier.synthesis or {})
        issues = list(synth.get("open_issues") or [])
        for r in rows:
            if not r.get("stamped"):
                continue
            text = str(r.get("detail") or f"{STAMP_PREFIX}{GAP_MARK}：{r.get('label')}")
            if not any(text[:16] in str(o.get("text") or "") for o in issues):
                issues.append({
                    "kind": "gap", "ref": "要点槽",
                    "text": text[:120],
                })
        synth["open_issues"] = issues
        dossier.synthesis = synth
    return rec
