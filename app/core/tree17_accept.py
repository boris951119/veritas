"""C-139：树17 引用验收打回循环（机器验收闸；旗 ``VERITAS_CITE_ACCEPT`` 默认关）。

挂在分析师出答案之后、物化之前：对模型 payload 按五码机械验收
（全部零 LLM、纯字符串/集合运算，同输入逐位可回放）：

  empty_cite          交白卷：零结论、零引用，或存在零证据结论
  out_of_box          引用了交卷盒（kg_submit.rank_order）以外的 segment_id
  anchor_miss         证据未指明来源段落或所指段落不存在（胡编／无锚）
  unverifiable        引文未在所指段落逐字命中（原文对不上）
  conflict_one_sided  交卷盒 conflict_pairs 成对（support＋oppose）只引一侧

失败 → 把「失败原因＋原约束」追加进重写提示重抽：资料清单不变、
仍只喂盒内段、禁金标 id（本模块不读金标、不读量尺）。上限
``attempts``（默认 3；env ``VERITAS_CITE_ACCEPT_ATTEMPTS``／config
``cite_accept_attempts``；硬顶 5）。到顶仍不过 → 机械剪枝（复用
``filter_payload_to_close_band`` 丢盒外 evidence）后物化，accounting
``cite_accept[<analyst>]`` 披露 ``maxed_out``＋逐次失败码——不静默脏过、
不死循环。

启用条件（三者同时）：旗开 ＋ 首轮形状（analyze 无显式 focus——
second_pass／multi_box 定向轮不在本闸范围）＋ 交卷盒在场
（``kg_submit_active``，即测试树主线已跑）。
"""

from __future__ import annotations

import os
from typing import Any

ENV_FLAG = "VERITAS_CITE_ACCEPT"
ENV_ATTEMPTS = "VERITAS_CITE_ACCEPT_ATTEMPTS"
ACCOUNTING_KEY = "cite_accept"
HARD_MAX_ATTEMPTS = 5
DEFAULT_ATTEMPTS = 3

# 失败码（对外稳定、逐位可回放；canonical 序）
CODE_EMPTY = "empty_cite"
CODE_OUT = "out_of_box"
CODE_ANCHOR = "anchor_miss"
CODE_VERBATIM = "unverifiable"
CODE_ONE_SIDED = "conflict_one_sided"
CODE_UNPARSABLE = "unparsable"
CODE_ORDER = (CODE_EMPTY, CODE_OUT, CODE_ANCHOR, CODE_VERBATIM,
              CODE_ONE_SIDED, CODE_UNPARSABLE)


def cite_accept_enabled(settings: Any | None = None) -> bool:
    """旗：settings 优先；env 兜底。默认关（关＝生产行为与改前逐字相同）。"""
    if settings is not None and hasattr(settings, "cite_accept"):
        return bool(getattr(settings, "cite_accept"))
    v = (os.environ.get(ENV_FLAG) or "").strip().lower()
    return v in ("1", "true", "on", "yes")


def cite_accept_attempts(settings: Any | None = None) -> int:
    """打回上限：settings 优先，env 兜底；<1 回默认；硬顶 HARD_MAX_ATTEMPTS。"""
    n: int | None = None
    if settings is not None and hasattr(settings, "cite_accept_attempts"):
        try:
            n = int(getattr(settings, "cite_accept_attempts"))
        except (TypeError, ValueError):
            n = None
    if n is None:
        raw = (os.environ.get(ENV_ATTEMPTS) or "").strip()
        if raw.isdigit() and int(raw) >= 1:
            n = int(raw)
    if n is None or n < 1:
        n = DEFAULT_ATTEMPTS
    return max(1, min(n, HARD_MAX_ATTEMPTS))


def gate_context(dossier: Any) -> dict[str, Any] | None:
    """从 accounting 取验收参照（盒＋成对）。交卷盒缺席 → None＝闸不启用。"""
    acc = getattr(dossier, "accounting", None) or {}
    if not acc.get("kg_submit_active"):
        return None
    surf = acc.get("kg_submit")
    if not isinstance(surf, dict):
        return None
    box = [str(x) for x in (surf.get("rank_order") or []) if str(x).strip()]
    if not box:
        return None
    raw_pairs = surf.get("conflict_pairs")
    pairs = raw_pairs if isinstance(raw_pairs, dict) else {}
    return {"box": box, "box_set": set(box), "pairs": pairs}


def unparsable_verdict() -> dict[str, Any]:
    """回复不是合法 JSON 时的失败判定（可回放；counts 全 0）。"""
    return _verdict(codes=[CODE_UNPARSABLE])


def _verdict(
    *,
    codes: list[str],
    n_conclusions: int = 0,
    n_cons_without_ev: int = 0,
    cited_ids: list[str] | None = None,
    out_of_box_ids: list[str] | None = None,
    anchor_miss_ids: list[str] | None = None,
    unverifiable_ids: list[str] | None = None,
    one_sided_pairs: list[dict[str, Any]] | None = None,
    unenforceable_pairs_n: int = 0,
) -> dict[str, Any]:
    codes = sorted(set(codes), key=CODE_ORDER.index)
    return {
        "ok": not codes,
        "codes": codes,
        "n_conclusions": n_conclusions,
        "n_cons_without_evidence": n_cons_without_ev,
        "n_cited": len(cited_ids or []),
        "cited_ids": list(cited_ids or []),
        "out_of_box_ids": list(out_of_box_ids or []),
        "anchor_miss_ids": list(anchor_miss_ids or []),
        "unverifiable_ids": list(unverifiable_ids or []),
        "one_sided_pairs": list(one_sided_pairs or []),
        "unenforceable_pairs_n": int(unenforceable_pairs_n),
    }


def accept_payload(
    data: dict[str, Any] | None,
    *,
    dossier: Any,
    box: list[str],
    box_set: set[str],
    pairs: dict[str, Any],
) -> dict[str, Any]:
    """五码机械验收（零 LLM；同输入逐位同输出）。

    在物化「之前」跑——打回轮次不在案卷留痕（无 parse drops／无
    empty_runs 噪音），只有通过的 payload 才进案卷。
    """
    from app.core.citation_check import check_quote
    from app.kg_lab.tree17_cite import extract_cited_segment_ids

    cons: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("conclusions"), list):
        cons = data["conclusions"]
    cited = extract_cited_segment_ids(data if isinstance(data, dict) else None)
    cited_set = set(cited)

    codes: list[str] = []
    n_cons_without_ev = 0
    dict_cons = [c for c in cons if isinstance(c, dict)]
    for con in dict_cons:
        evs = con.get("evidence")
        if not isinstance(evs, list) or not evs:
            n_cons_without_ev += 1
    if not cons or not cited or n_cons_without_ev:
        codes.append(CODE_EMPTY)

    out_of_box = [c for c in cited if c not in box_set]
    if out_of_box:
        codes.append(CODE_OUT)

    anchor_miss: list[str] = []
    unverifiable: list[str] = []
    for con in dict_cons:
        evs = con.get("evidence")
        if not isinstance(evs, list):
            continue
        for ev in evs:
            if not isinstance(ev, dict):
                continue
            sid = str(ev.get("segment_id") or "").strip()
            quote = str(ev.get("quote") or "")
            if not sid:
                anchor_miss.append("(no_id)")
                continue
            seg = dossier.segment(sid)
            if seg is None:
                anchor_miss.append(sid)
                continue
            if not check_quote(quote, seg.text).ok:
                unverifiable.append(sid)
    if anchor_miss:
        codes.append(CODE_ANCHOR)
    if unverifiable:
        codes.append(CODE_VERBATIM)

    one_sided: list[dict[str, Any]] = []
    unenforceable_pairs = 0
    conflicts = pairs.get("conflicts") if isinstance(pairs, dict) else None
    for p in conflicts if isinstance(conflicts, list) else []:
        if not isinstance(p, dict):
            continue
        s_id = str(p.get("support_id") or "").strip()
        o_id = str(p.get("oppose_id") or "").strip()
        if not s_id or not o_id:
            continue
        # 只执行「两侧都在交卷盒内」的成对（与树17 计划层 pair_required
        # 同口径）：一侧不在盒＝引用面不可达， analysts 物理引不到——
        # 硬执行会造成必败打回循环；只计数披露，不进失败码。
        if s_id not in box_set or o_id not in box_set:
            unenforceable_pairs += 1
            continue
        s_c = s_id in cited_set
        o_c = o_id in cited_set
        if s_c != o_c:
            one_sided.append({
                "support_id": s_id, "oppose_id": o_id,
                "support_cited": s_c, "oppose_cited": o_c,
            })
    if one_sided:
        codes.append(CODE_ONE_SIDED)

    return _verdict(
        codes=codes,
        n_conclusions=len(cons),
        n_cons_without_ev=n_cons_without_ev,
        cited_ids=cited,
        out_of_box_ids=out_of_box,
        anchor_miss_ids=sorted(set(anchor_miss)),
        unverifiable_ids=sorted(set(unverifiable)),
        one_sided_pairs=one_sided,
        unenforceable_pairs_n=unenforceable_pairs,
    )


def verdict_summary(verdict: dict[str, Any] | None) -> dict[str, Any]:
    """accounting 逐次记录面：码＋计数（不记 quote 原文／模型输出原文）。"""
    v = verdict or {}
    return {
        "codes": list(v.get("codes") or []),
        "n_cited": int(v.get("n_cited") or 0),
        "n_conclusions": int(v.get("n_conclusions") or 0),
        "n_cons_without_evidence": int(v.get("n_cons_without_evidence") or 0),
        "out_of_box_n": len(v.get("out_of_box_ids") or []),
        "anchor_miss_n": len(v.get("anchor_miss_ids") or []),
        "unverifiable_n": len(v.get("unverifiable_ids") or []),
        "one_sided_n": len(v.get("one_sided_pairs") or []),
        "unenforceable_pairs_n": int(v.get("unenforceable_pairs_n") or 0),
    }


def render_failure_block(
    verdict: dict[str, Any] | None,
    *,
    attempt: int,
    box: list[str],
) -> str:
    """打回提示块：只含失败原因＋被违约束的原样复述＋盒内允许编号。

    禁金标 id：块内出现的 id 只有模型自己引错的编号与盒内编号。
    """
    v = verdict or {}
    codes = list(v.get("codes") or [])
    lines = [
        "", f"【引用验收·打回第 {attempt} 次】上一轮输出未过机器验收，"
            "原因与对应要求（必须全部修复）：",
    ]
    n = 0
    if CODE_EMPTY in codes:
        n += 1
        lines.append(
            f"{n}. 存在零结论／零引用／零证据结论：每条结论必须挂至少 1 条"
            "证据，证据必须给所指段落的逐字引文。")
    if CODE_OUT in codes:
        n += 1
        ids = "、".join(str(x) for x in (v.get("out_of_box_ids") or [])[:8])
        lines.append(
            f"{n}. 引用了资料清单以外的编号：{ids}——segment_id 只许取自"
            "下方资料清单中列出的编号，不得编造。")
    if CODE_ANCHOR in codes:
        n += 1
        ids = "、".join(str(x) for x in (v.get("anchor_miss_ids") or [])[:8])
        lines.append(
            f"{n}. {len(v.get('anchor_miss_ids') or [])} 条证据未指明来源段落"
            f"或所指段落不存在：{ids}——segment_id 必须是资料清单中的编号。")
    if CODE_VERBATIM in codes:
        n += 1
        ids = "、".join(str(x) for x in (v.get("unverifiable_ids") or [])[:8])
        lines.append(
            f"{n}. {len(v.get('unverifiable_ids') or [])} 条引文未在所指段落"
            f"中逐字命中（涉及：{ids}）——quote 必须是对原文的逐字摘录，"
            "一个字都不能改写；如需省略用「……」，省略两端仍须逐字一致。")
    if CODE_ONE_SIDED in codes:
        n += 1
        pr = "；".join(
            f"{p.get('support_id')} vs {p.get('oppose_id')}"
            f"（已引 {'support' if p.get('support_cited') else 'oppose'} 侧）"
            for p in (v.get("one_sided_pairs") or [])[:4])
        lines.append(
            f"{n}. 冲突成对只引用了一侧：{pr}——support 与 oppose 两侧"
            "都须至少各引 1 条。")
    if CODE_UNPARSABLE in codes:
        n += 1
        lines.append(f"{n}. 上一轮回复不是合法 JSON——只输出 JSON 本身。")
    lines.append(
        "segment_id 只许使用下列资料清单中的编号：" + "、".join(box) + "。")
    lines.append("其余要求与系统提示词一致；资料清单不变。只输出 JSON。")
    return "\n" + "\n".join(lines)


def finalize_gate(
    analyst: Any,
    dossier: Any,
    *,
    gate_ctx: dict[str, Any],
    data: dict[str, Any] | None,
    verdict: dict[str, Any] | None,
    attempts_log: list[dict[str, Any]],
    attempts_cap: int,
    raw: str,
) -> list[Any]:
    """闸路径收尾：写 accounting；到顶未过 → 机械剪枝后物化＋披露。

    - 过（verdict.ok）＝原样物化最后（通过）payload；
    - 到顶未过＝复用 ``filter_payload_to_close_band`` 丢盒外 evidence 后
      物化（带外不进案卷＝带外 0 不靠自觉），``maxed_out``＋逐次失败码
      进 accounting——披露失败，不静默脏过，不死循环。
    """
    name = str(getattr(analyst, "name", "") or "analyst")
    final_ok = bool(verdict and verdict.get("ok"))
    rec: dict[str, Any] = {
        "analyst": name,
        "enabled": True,
        "attempts": max(1, len(attempts_log)),
        "attempts_cap": int(attempts_cap),
        "attempts_log": list(attempts_log),
        "final_ok": final_ok,
        "maxed_out": not final_ok,
        "codes_final": list((verdict or {}).get("codes") or []),
    }
    payload: dict[str, Any] | None = None
    if final_ok and isinstance(data, dict):
        payload = data
    else:
        from app.kg_lab.tree17_cite import filter_payload_to_close_band

        pruned = filter_payload_to_close_band(
            data if isinstance(data, dict) else None,
            {"close_read": list(gate_ctx["box"])},
        )
        rec["pruned"] = {
            "n_dropped_evidence": int(pruned.get("n_dropped_evidence") or 0),
            "n_dropped_conclusions": int(pruned.get("n_dropped_conclusions") or 0),
        }
        payload = {"conclusions": pruned.get("conclusions") or []}
    if getattr(dossier, "accounting", None) is None:
        dossier.accounting = {}
    slot = dossier.accounting.setdefault(ACCOUNTING_KEY, {})
    if not isinstance(slot, dict):
        slot = {}
        dossier.accounting[ACCOUNTING_KEY] = slot
    slot[name] = rec
    return analyst._materialize(payload, dossier, raw=raw)
