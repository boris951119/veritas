"""C-147：多轮质证（真对立＋可吃的 other 进 2..N 轮书面对打）。

盘点（件①，基 tip f9509a2）：现质证＝单轮／两侧不互见（app/agents/
arbiter.py::run_rebuttals，轮数护栏＝1）；闸只有事后 audit_discourse
（引文逐字＋引用存在性＝黄旗披露，无生成时逐轮闸、无打回）；C-146 分流
只在事后留痕里贴标签，与质证零接线；无任何 rebuttal 留痕面。

本模块只管三件事（质证对打循环在 arbiter，仲裁公式一行不动＝冲突数值线
STOP）：
- 开关与轮数：Settings.rebuttal_multiround 默认 True（比赛需要）；
  rebuttal_rounds 默认 2、夹在 [2,6]。env VERITAS_MULTI_REBUTTAL=0 全关
  ＝旧单轮逐字节同形（accounting 无键、仲裁输入不变）。
- 分流路由：复用 C-146 triage_conflict_pair 同一函数、同一输入口径
  （conflict_class 恒 "unclassified"——apply_conflict_trace 现行传
  collisions=None，质证时与留痕时同一对判同一档）：
  true_oppose → 强制进多轮；other 且两侧主体标签都在且相等 → 语义侧吃进
  多轮（同主体跨表述对立：机械极性判不出而判读已判对立，让双方对打；
  禁金标／系数灌箱）；oral_misread／date_offset → 默认不进（轻标留痕）；
  other 无主体 → 不进（轻标）。
- 留痕：accounting["rebuttal"]＝逐对 escalation／逐轮 text＋闸结果＋打回
  ＋采信倾向 lean；空态披露。折进 conflict_trace.json 顶层 rebuttal 节
  （独立节，不冒充第四类冲突、不碰 C-115 三类与 C-146 分流计数）。
"""
from __future__ import annotations

import os
from typing import Any

ACCOUNTING_KEY = "rebuttal"
SECTION_KEY = "rebuttal"
DEFAULT_ROUNDS = 2
MIN_ROUNDS = 2
MAX_ROUNDS = 6

# escalation_reason 封闭集合（留痕里可见的路由原因）
ESC_TRUE = "true_oppose_forced"
ESC_SEMANTIC = "semantics_eat_other_same_subject"
ESC_OTHER_NO_SUBJECT = "other_subject_unknown"
ESC_NONE_PREFIX = "class_not_escalated:"

_ENV_MULTI = "VERITAS_MULTI_REBUTTAL"
_ENV_ROUNDS = "VERITAS_REBUTTAL_ROUNDS"


def multiround_enabled(settings: Any | None = None) -> bool:
    """默认随出厂（True）。``VERITAS_MULTI_REBUTTAL=0`` 关＝旧单轮同形。

    settings 为 None 时走 ``Settings.from_env()``（出厂默认＋env 叠加），
    不许在无参路径里绕开出厂默认——否则翻默认后管线挂点静默不走。
    """
    if settings is None:
        from app.config import Settings
        settings = Settings.from_env()
    if hasattr(settings, "rebuttal_multiround"):
        return bool(getattr(settings, "rebuttal_multiround"))
    v = (os.environ.get(_ENV_MULTI) or "").strip().lower()
    if v in ("0", "false", "off", "no"):
        return False
    return True


def rounds_requested(settings: Any | None = None) -> tuple[int, str]:
    """(轮数, 夹取说明)；夹在 [2,6]，说明非空＝发生过夹取（要披露）。"""
    if settings is None:
        from app.config import Settings
        settings = Settings.from_env()
    val = DEFAULT_ROUNDS
    if hasattr(settings, "rebuttal_rounds"):
        try:
            val = int(getattr(settings, "rebuttal_rounds"))
        except (TypeError, ValueError):
            val = DEFAULT_ROUNDS
    note = ""
    if val < MIN_ROUNDS:
        note = f"rebuttal_rounds={val} 低于下限，按 {MIN_ROUNDS} 执行"
        val = MIN_ROUNDS
    elif val > MAX_ROUNDS:
        note = f"rebuttal_rounds={val} 超上限，按 {MAX_ROUNDS} 执行"
        val = MAX_ROUNDS
    return val, note


def escalation_for(pair: Any, dossier: Any) -> dict[str, Any]:
    """冲突对 → 是否进多轮质证（复用 C-146 同一函数，判得出才路由）。"""
    from app.core.conflict_trace import triage_conflict_pair
    raw = {
        "id": str(getattr(pair, "id", "") or ""),
        "a_id": str(getattr(pair, "a_id", "") or ""),
        "b_id": str(getattr(pair, "b_id", "") or ""),
        "topic": str(getattr(pair, "topic", "") or ""),
        "description": str(getattr(pair, "description", "") or ""),
    }
    t = triage_conflict_pair(raw, "unclassified", dossier=dossier)
    cls = str(t.get("triage_class") or "other")
    ev = t.get("triage_evidence") or {}
    out: dict[str, Any] = {
        "triage_class": cls,
        "triage_reason_code": str(t.get("triage_reason_code") or ""),
        "escalate": False,
        "escalation_reason": "",
        "semantic_upgrade": False,
    }
    if cls == "true_oppose":
        out["escalate"] = True
        out["escalation_reason"] = ESC_TRUE
    elif cls == "other":
        # other 档已保证：两侧原文不同、主体不冲突、议题维不相交不成立、
        # 极性机械判不出对立、数值集合不构成不相交。能吃的＝两侧主体标签
        # 都在且相等（同主体跨表述对立）。
        sa = str(ev.get("subject_a") or "")
        sb = str(ev.get("subject_b") or "")
        if sa and sb and sa == sb:
            out["escalate"] = True
            out["escalation_reason"] = ESC_SEMANTIC
            out["semantic_upgrade"] = True
        else:
            out["escalation_reason"] = ESC_OTHER_NO_SUBJECT
    else:
        # oral_misread／date_offset 默认不进多轮（轻标留痕，单轮旧路照旧）
        out["escalation_reason"] = ESC_NONE_PREFIX + cls
    return out


def pair_row(pair: Any, esc: dict[str, Any], *, rounds: int,
             round_rows: list[dict] | None) -> dict[str, Any]:
    """一对冲突的留痕行（escalated＝带逐轮；none＝轻标）。"""
    escalated = bool(esc.get("escalate"))
    row: dict[str, Any] = {
        "pair_id": str(getattr(pair, "id", "") or ""),
        "a_id": str(getattr(pair, "a_id", "") or ""),
        "b_id": str(getattr(pair, "b_id", "") or ""),
        "triage_class": esc.get("triage_class") or "",
        "triage_reason_code": esc.get("triage_reason_code") or "",
        "escalation": "multi_round" if escalated else "none",
        "escalation_reason": esc.get("escalation_reason") or "",
        "semantic_upgrade": bool(esc.get("semantic_upgrade")),
    }
    if escalated:
        rws = list(round_rows or [])
        row["rounds_requested"] = int(rounds)
        row["rounds_used"] = max(
            (int(r.get("round") or 0) for r in rws), default=0)
        row["rounds"] = rws
    return row


def write_accounting(dossier: Any, *, rows: list[dict], n_pairs: int,
                     rounds: int, rounds_note: str = "") -> dict | None:
    """旗开才写 accounting[ACCOUNTING_KEY]；零对也写空态（原因句）。"""
    if not multiround_enabled():
        return None
    acc = getattr(dossier, "accounting", None)
    if not isinstance(acc, dict):
        return None
    n_esc = sum(1 for r in rows if r.get("escalation") == "multi_round")
    if n_pairs <= 0 and not rows:
        payload: dict[str, Any] = {
            "enabled": True,
            "rounds_requested": int(rounds),
            "n_pairs": 0,
            "n_escalated": 0,
            "pairs": [],
            "empty_state": True,
            "detail": "本次未检出冲突对＝无质证对象"
                      "（未检出＝本次研判没有碰到，不等于资料无冲突）。",
        }
    else:
        detail = (
            f"C-147 多轮质证：{n_pairs} 对冲突，{n_esc} 对进 {MIN_ROUNDS}.."
            f"{int(rounds)} 轮对打（true_oppose 强制；other 同主体跨表述"
            "吃进；oral_misread／date_offset 不进＝单轮旧路照旧）")
        if rounds_note:
            detail += f"；{rounds_note}"
        payload = {
            "enabled": True,
            "rounds_requested": int(rounds),
            "n_pairs": int(n_pairs),
            "n_escalated": n_esc,
            "pairs": list(rows),
            "detail": detail,
        }
    acc[ACCOUNTING_KEY] = payload
    return payload


def fold_into_trace_payload(payload: dict, accounting: Any) -> None:
    """accounting 里的 rebuttal 折进 conflict_trace.json 顶层独立节。

    与 C-145 merge_gate 同一手法：不进 records（不冒充第四类冲突、
    不污染 C-115 覆盖率与 C-146 分流计数）；旗关无键＝零差异。
    """
    if not isinstance(payload, dict):
        return
    acc = accounting if isinstance(accounting, dict) else {}
    bucket = acc.get(ACCOUNTING_KEY)
    if isinstance(bucket, dict):
        payload[SECTION_KEY] = bucket


def joined_rebuts(round_rows: list[dict]) -> dict[str, str]:
    """逐轮行 → Resolution.rebuts 形状（{side: 「第r轮：…」拼接}）。

    旧单轮形状保持 {side: str}——audit_discourse 与报告渲染零改动即可
    扫到全部轮次的引文与引用。
    """
    per: dict[str, list[str]] = {}
    for r in round_rows or []:
        side = str(r.get("side") or "")
        text = str(r.get("text") or "")
        if side and text:
            per.setdefault(side, []).append(
                f"第{r.get('round')}轮：{text}")
    return {side: "；".join(parts) for side, parts in per.items()}
