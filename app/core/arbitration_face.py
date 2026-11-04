"""C-148：仲裁上下文接线＋轻裁（树22 仲裁，对标市场优质做法）。

盘点（件①，基 tip bf65d23）：现仲裁＝程序侧证据强度已在场
（``compute_evidence_weight`` 纯程序可复算），但 C-146 分流与仲裁零接线
（oral_misread／date_offset 这类「不是真对立」的对也走全量 LLM 仲裁）；
C-147 质证轮次／闸结果、C-145 归并闸否决史都不进仲裁上下文；裁决理由只
有 rationale 自由文本，无结构化留痕。少数意见保留已由 ``apply_resolution``
（败方 status="dissent"＋胜方挂 dissent 记录）承担——本模块不动它。

对标的市场做法与本模块的落点（交账「对标」段的骨架）：
- 证据强度＝程序侧可复算输入，不是 LLM 口算分 → 现状已在场，本模块原样
  接线（一行不改，冲突数值线 STOP）；
- 新近度最多做并列打破 → 现状＝提示词里「强度打平时纳入考量」的引导语，
  本模块不加码、不写进裁决规则；
- 质证轮次／闸结果／triage 进仲裁上下文 → ``build_context`` 程序侧片段；
- oral_misread／date_offset 默认轻裁、不升仲裁 → ``arbitrate_light``
  （tie 形态：双方保留多数意见，理由写分流依据，不判谁错）；
- 胜方＋败方少数意见都保留 → 现状已在场（dissent），本模块不碰；
- 理由结构化进 accounting／仲裁导出 → ``write_accounting`` ＋
  ``fold_into_trace_payload``（与 C-145／C-147 同一手法：顶层独立节，
  不冒充第四类冲突、不碰 C-115 三类与 C-146 分流计数）。

开关：``Settings.arb_context`` 默认 True（比赛需要）；``VERITAS_ARB_CONTEXT=0``
全关＝逐字节同改前（light 路不开、上下文片段不拼、accounting 无键、
导出无节）。禁：数值冲突加权／打分零改动；不读金标；不往提示词塞系数。
"""
from __future__ import annotations

import os
from typing import Any

ACCOUNTING_KEY = "arbitration"
SECTION_KEY = "arbitration"

# 路由封闭集合（留痕里可见）
ROUTE_LLM = "llm_enriched"     # 真对立／其他 → LLM 仲裁＋程序上下文片段
ROUTE_LIGHT = "light_program"  # 误读／跨日 → 程序轻裁（tie 形态，不叫模型）

# 轻裁档：不是同一事实的对立（误读）或只是时序档位差（跨日）＝不判谁错
LIGHT_CLASSES = ("oral_misread", "date_offset")

_ENV_ARB = "VERITAS_ARB_CONTEXT"


def arb_enabled(settings: Any | None = None) -> bool:
    """默认随出厂（True）。``VERITAS_ARB_CONTEXT=0`` 关＝逐字节同改前。

    settings 为 None 时走 ``Settings.from_env()``（出厂默认＋env 叠加），
    不许在无参路径里绕开出厂默认——否则翻默认后管线挂点静默不走
    （与 rebuttal_rounds.multiround_enabled 同一纪律）。
    """
    if settings is None:
        from app.config import Settings
        settings = Settings.from_env()
    if hasattr(settings, "arb_context"):
        return bool(getattr(settings, "arb_context"))
    v = (os.environ.get(_ENV_ARB) or "").strip().lower()
    if v in ("0", "false", "off", "no"):
        return False
    return True


def arb_route(pair: Any, dossier: Any) -> dict[str, Any]:
    """冲突对 → 仲裁路由（复用 C-146 triage_conflict_pair 同一函数）。

    与质证路由同一输入口径（conflict_class 恒 "unclassified"）——同一对
    在质证面、仲裁面、留痕面判同一档。只路由，不改任何判定。
    """
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
    route = ROUTE_LIGHT if cls in LIGHT_CLASSES else ROUTE_LLM
    return {
        "pair_id": str(getattr(pair, "id", "") or ""),
        "a_id": str(getattr(pair, "a_id", "") or ""),
        "b_id": str(getattr(pair, "b_id", "") or ""),
        "triage_class": cls,
        "triage_reason_code": str(t.get("triage_reason_code") or ""),
        "triage_reason_short": str(t.get("triage_reason_short") or ""),
        "route": route,
    }


def merge_veto_face(dossier: Any, ids: list[str]) -> list[dict[str, Any]]:
    """C-145 归并闸否决史：两成员出现过的被否决组（MERGE-xxxx＋fail_legs）。

    含义：这两条曾被 LLM 提议归并、被硬闸拦下保持独立——仲裁者应当知道
    「差异曾被静默合并」这个风险曾被机械侧确认过。纯读账本，零 LLM。
    """
    acc = getattr(dossier, "accounting", None)
    blocked = (acc or {}).get("merge_gate") or {}
    out: list[dict[str, Any]] = []
    idset = {str(i) for i in ids}
    for row in (blocked.get("blocked") or []):
        members = {str(m) for m in (row.get("member_ids") or [])}
        hit = members & idset
        if hit:
            out.append({
                "group_id": str(row.get("id") or ""),
                "member_ids": sorted(hit),
                "fail_legs": list(row.get("fail_legs") or []),
            })
    return out


def rebuttal_face(pair_id: str, rb_rows: list[dict] | None) -> dict[str, Any]:
    """C-147 质证留痕摘要：本对的轮数／闸旗读数（从当轮 rb_rows 取）。

    rb_rows＝pipeline 循环里已收的 rebuttal pair_row 列表（仲裁发生在
    同一对的质证之后、accounting 落盘之前——所以从行取而不是读账本）。
    """
    for row in (rb_rows or []):
        if str(row.get("pair_id") or "") != str(pair_id):
            continue
        rounds = list(row.get("rounds") or [])
        if not rounds:
            return {"escalation": str(row.get("escalation") or "none"),
                    "rounds_used": 0, "gate_flags": 0, "repaired": 0}
        return {
            "escalation": str(row.get("escalation") or "multi_round"),
            "rounds_used": max((int(r.get("round") or 0) for r in rounds),
                               default=0),
            "gate_flags": sum(int(r.get("quote_flags") or 0)
                              + int(r.get("ref_flags") or 0) for r in rounds),
            "repaired": sum(1 for r in rounds if r.get("repaired")),
        }
    return {}


def build_context(pair: Any, dossier: Any, route_row: dict[str, Any],
                  rb_rows: list[dict] | None = None,
                  veto: list[dict] | None = None) -> str:
    """程序侧仲裁上下文片段（零 LLM、确定性、不读金标、不塞系数）。

    只补事实（分流判定／否决史／质证留痕），不下裁决指令——裁决仍是
    ARBITER_SYSTEM 既有职责；证据强度对比提示词里本来就有，此处不重复。
    veto＝调用方已算好的否决史（省一次重复读账本），缺省现算。
    """
    ids = [str(getattr(pair, "a_id", "") or ""),
           str(getattr(pair, "b_id", "") or "")]
    lines = ["仲裁上下文（程序侧，可复算；只补事实，不改裁决规则）：",
             f"- 分流判定：{route_row.get('triage_class')}"
             f"（{route_row.get('triage_reason_code')}："
             f"{route_row.get('triage_reason_short')}）"]
    if veto is None:
        veto = merge_veto_face(dossier, ids)
    if veto:
        for v in veto:
            lines.append(
                f"- 归并闸否决史：{v['group_id']}"
                f"（fail_legs={'、'.join(v['fail_legs']) or 'unknown'}）"
                f"——{'、'.join(v['member_ids'])} 曾被提议归并、被硬闸拦下"
                "保持独立")
    else:
        lines.append("- 归并闸否决史：无（两成员未同入被否决组）")
    face = rebuttal_face(route_row.get("pair_id") or "", rb_rows)
    if face:
        lines.append(
            f"- 质证留痕：{face.get('escalation') or 'none'}，"
            f"{int(face.get('rounds_used') or 0)} 轮，"
            f"闸旗 {int(face.get('gate_flags') or 0)} 项，"
            f"打回 {int(face.get('repaired') or 0)} 次"
            "（全轮引文与闸结果见 accounting.rebuttal）")
    return "\n".join(lines)


def arbitrate_light(pair: Any, dossier: Any, rebuts: dict | None,
                    route_row: dict[str, Any]) -> Any:
    """轻裁：不叫模型，tie 形态消解（双方保留多数意见），理由写分流依据。

    结构化留痕落在 Resolution.basis（route／triage／机械读数）；tie 的
    重启条件沿用既有表（补充新证据即重启）。不走 ``_stamp`` 的 tie 文案
    分支——那里写死「强度差 ≤ margin」的句子，轻裁对不保证成立（假不等
    式不许进 basis），故 basis 文案在这里按真数重写。
    """
    from app.core.conflicts import (
        METHOD_TO_RESOLUTION_TYPE, Resolution, _stamp, _source_fold,
        compute_evidence_weight,
    )
    from app.core.resolution_time_type import apply_tie_time_rule

    weight = compute_evidence_weight(pair, dossier)
    res = Resolution(
        winner_id="tie", method="tie",
        rationale=(
            f"程序轻裁（未升 LLM 仲裁）：分流判定 {route_row.get('triage_class')}"
            f"（{route_row.get('triage_reason_code')}："
            f"{route_row.get('triage_reason_short')}）＝不是同一事实的对立，"
            "不判谁错，双方保留多数意见；任一方补充新证据即重启。"
        ),
        evidence_weight=weight,
        rebuts=dict(rebuts or {}),
    )
    exact = None
    pairs = None
    try:
        from app.core.dup_check import duplicate_map, near_dup_pairs

        exact = duplicate_map(dossier)
        pairs = near_dup_pairs(dossier)
    except Exception:
        exact, pairs = {}, []
    _stamp(res, pair, dossier, "tie", exact, pairs)
    sa = float(weight.get(str(getattr(pair, "a_id", "")), 0.0))
    sb = float(weight.get(str(getattr(pair, "b_id", "")), 0.0))
    res.basis["route"] = ROUTE_LIGHT
    res.basis["triage_class"] = route_row.get("triage_class") or ""
    res.basis["triage_reason_code"] = route_row.get("triage_reason_code") or ""
    na, _, _ = _source_fold(str(getattr(pair, "a_id", "")), dossier,
                            exact, pairs)
    nb, _, _ = _source_fold(str(getattr(pair, "b_id", "")), dossier,
                            exact, pairs)
    res.basis["type_applies"] = (
        f"程序轻裁（分流 {route_row.get('triage_class')}）＝不判谁错；"
        f"证据强度 {getattr(pair, 'a_id', '')}={sa:.2f}／"
        f"{getattr(pair, 'b_id', '')}={sb:.2f}、"
        f"独立信源 {na} 与 {nb}（程序口径，只对比不裁决）")
    res.basis["loser_excluded"] = "双方均未排除（轻裁＝不判谁错）"
    res.resolution_type = METHOD_TO_RESOLUTION_TYPE["tie"]
    # C-155：轻裁同为「双方均保留」，与 _stamp 共用同一条时效性回填（不另起判据）
    apply_tie_time_rule(res, pair, dossier)
    return res


def pair_row(pair: Any, route_row: dict[str, Any], res: Any, *,
             context_included: bool, llm_called: bool,
             veto: list[dict] | None = None) -> dict[str, Any]:
    """一对冲突的仲裁留痕行（结构化理由面：路由＋是否消解＋终局）。"""
    row: dict[str, Any] = {
        "pair_id": str(getattr(pair, "id", "") or ""),
        "a_id": str(getattr(pair, "a_id", "") or ""),
        "b_id": str(getattr(pair, "b_id", "") or ""),
        "triage_class": route_row.get("triage_class") or "",
        "triage_reason_code": route_row.get("triage_reason_code") or "",
        "route": route_row.get("route") or "",
        "context_included": bool(context_included),
        "llm_called": bool(llm_called),
        "merge_veto_groups": [v.get("group_id") for v in (veto or [])],
    }
    if res is not None:
        row.update({
            "resolved": True,
            "winner_id": str(getattr(res, "winner_id", "") or ""),
            "method": str(getattr(res, "method", "") or ""),
            "decision_path": str(getattr(res, "decision_path", "") or ""),
        })
    else:
        row["resolved"] = False
    return row


def write_accounting(dossier: Any, *, rows: list[dict],
                     n_pairs: int) -> dict[str, Any] | None:
    """旗开才写 accounting[ACCOUNTING_KEY]；零对也写空态（原因句）。"""
    if not arb_enabled():
        return None
    acc = getattr(dossier, "accounting", None)
    if not isinstance(acc, dict):
        return None
    n_light = sum(1 for r in rows if r.get("route") == ROUTE_LIGHT)
    n_llm = sum(1 for r in rows if r.get("route") == ROUTE_LLM)
    if n_pairs <= 0 and not rows:
        payload: dict[str, Any] = {
            "enabled": True,
            "n_pairs": 0,
            "n_light": 0,
            "n_llm": 0,
            "pairs": [],
            "empty_state": True,
            "detail": "本次未检出冲突对＝无仲裁对象"
                      "（未检出＝本次研判没有碰到，不等于资料无冲突）。",
        }
    else:
        payload = {
            "enabled": True,
            "n_pairs": int(n_pairs),
            "n_light": n_light,
            "n_llm": n_llm,
            "pairs": list(rows),
            "detail": (
                f"C-148 仲裁路由：{n_pairs} 对冲突，轻裁 {n_light}"
                f"（oral_misread／date_offset 不升 LLM，tie 形态保留双方），"
                f"LLM 仲裁 {n_llm}（带程序侧上下文片段）"),
        }
    acc[ACCOUNTING_KEY] = payload
    return payload


def fold_into_trace_payload(payload: dict, accounting: Any) -> None:
    """accounting 里的 arbitration 折进 conflict_trace.json 顶层独立节。

    与 merge_gate（C-145）／rebuttal（C-147）同一手法：不进 records
    （不冒充第四类冲突、不污染 C-115 覆盖率与 C-146 分流计数）；
    旗关无键＝零差异。
    """
    if not isinstance(payload, dict):
        return
    acc = accounting if isinstance(accounting, dict) else {}
    bucket = acc.get(ACCOUNTING_KEY)
    if isinstance(bucket, dict):
        payload[SECTION_KEY] = bucket
