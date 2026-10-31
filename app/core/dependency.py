"""结论→结论依赖边：一遍 LLM 抽取 + 机械校验 + 传播／失效亮牌。

依赖边只用于推理树展示与人工介入传播，**不参与** conclude_confidence
四分量。语义正确性未经 A/B；人工可在 /api/conclusion/depends 增删并留痕。
v1 只在既有结论之间连边，不合成新前提节点。
"""

from __future__ import annotations

from app.agents.base import extract_json
from app.core.evidence import Dossier

# 报告／accounting 固定披露（跨面复用时点名工件，见 C-13 判据 l）
NOTE_NARROW = "中间结论层＝被依赖的既有结论，未合成新前提"
NOTE_AB = (
    "依赖边由模型抽取，语义正确性未经 A/B，"
    "人工可在 /api/conclusion/depends 增删并留痕"
)
NOTE_FAILED = "依赖边未生成"

_EXTRACT_SYSTEM = (
    "你是研判依赖抽取器。只输出 JSON："
    '{"edges":[{"from":"CON-x","to":"CON-y","why":"一句话"}]}。'
    "from 以 to 为前提；只连已有结论 id；不要发明新结论。"
)


def _order_index(dossier: Dossier) -> dict[str, int]:
    return {c.id: i for i, c in enumerate(dossier.conclusions)}


def _unique_by_dossier_order(ids: list[str], dossier: Dossier) -> list[str]:
    order = _order_index(dossier)
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i in seen:
            continue
        seen.add(i)
        out.append(i)
    out.sort(key=lambda x: order.get(x, 10**9))
    return out


def find_cycle_path(dossier: Dossier, frm: str, to: str) -> list[str] | None:
    """若新增 frm→depends_on to 会成环，返回环路径（含两端），否则 None。"""
    if frm == to:
        return [frm, to]
    # 从 to 沿已有 depends_on 能否走到 frm
    by_id = {c.id: c for c in dossier.conclusions}
    stack: list[tuple[str, list[str]]] = [(to, [to])]
    visited: set[str] = set()
    while stack:
        node, path = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        con = by_id.get(node)
        if con is None:
            continue
        for nxt in con.depends_on or []:
            if nxt == frm:
                return [frm] + path + [frm]
            if nxt not in visited:
                stack.append((nxt, path + [nxt]))
    return None


def validate_dependency_edge(
        dossier: Dossier, frm: str, to: str) -> str | None:
    """机械校验一条边。合法返回 None；否则返回披露句（拒收理由）。"""
    ids = {c.id for c in dossier.conclusions}
    if frm not in ids or to not in ids:
        missing = [x for x in (frm, to) if x not in ids]
        return f"依赖边拒收：id 不存在（{', '.join(missing)}）"
    if frm == to:
        return f"依赖边拒收：自环（{frm}→{frm}）"
    to_con = dossier.conclusion(to)
    assert to_con is not None
    if to_con.status != "majority":
        return (
            f"依赖边拒收：前提 {to} 的 status={to_con.status!r}，"
            f"须为 majority（不得以 merged/dissent 当前提）"
        )
    cycle = find_cycle_path(dossier, frm, to)
    if cycle is not None:
        path = "→".join(cycle)
        return f"依赖边拒收：成环（{path}）"
    return None


def add_dependency(dossier: Dossier, frm: str, to: str) -> None:
    """写入一条边（调用方须先 validate）。幂等。"""
    con = dossier.conclusion(frm)
    if con is None:
        raise KeyError(f"结论不存在: {frm}")
    if to not in con.depends_on:
        con.depends_on.append(to)


def remove_dependency(dossier: Dossier, frm: str, to: str) -> None:
    con = dossier.conclusion(frm)
    if con is None:
        raise KeyError(f"结论不存在: {frm}")
    con.depends_on = [x for x in con.depends_on if x != to]


def apply_validated_edges(
        dossier: Dossier,
        raw_edges: list,
) -> tuple[list[dict], list[str]]:
    """逐条校验并写入；返回 (accepted, disclosures)。非法边各出一条披露。"""
    accepted: list[dict] = []
    disclosures: list[str] = []
    # 先清空再写——本遍抽取覆盖上一次
    for c in dossier.conclusions:
        c.depends_on = []
    for item in raw_edges or []:
        if not isinstance(item, dict):
            disclosures.append("依赖边拒收：条目非对象")
            continue
        frm = str(item.get("from") or "").strip()
        to = str(item.get("to") or "").strip()
        why = str(item.get("why") or "").strip()
        reason = validate_dependency_edge(dossier, frm, to)
        if reason:
            disclosures.append(reason)
            continue
        add_dependency(dossier, frm, to)
        accepted.append({"from": frm, "to": to, "why": why})
    return accepted, disclosures


def extract_dependencies(
        dossier: Dossier, client, model: str) -> dict:
    """一遍 LLM 抽取依赖边；失败 → 0 条边 + 披露「依赖边未生成」，不炸管线。

    依赖边语义正确性未经 A/B（见模块头注释与 NOTE_AB）。
    """
    base_notes = [NOTE_NARROW, NOTE_AB]
    cons = [c for c in dossier.conclusions if c.status != "merged"]
    if not cons:
        rec = {
            "n_edges": 0,
            "accepted": [],
            "rejected": [],
            "disclosures": base_notes + [NOTE_FAILED],
            "note": NOTE_FAILED,
        }
        dossier.accounting["dependency"] = rec
        return rec

    listing = "\n".join(
        f"- [{c.id}] status={c.status}｜{(c.statement or '')[:80]}"
        for c in cons
    )
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM},
        {"role": "user", "content":
         f"议题：{dossier.question}\n结论清单：\n{listing}\n"
         "请给出结论之间的前提依赖边。"},
    ]
    try:
        raw = client.chat(model, messages, json_mode=True).content
        data = extract_json(raw)
        edges = data.get("edges") if isinstance(data, dict) else None
        if not isinstance(edges, list):
            raise ValueError("缺少 edges 列表")
    except Exception:
        for c in dossier.conclusions:
            c.depends_on = []
        rec = {
            "n_edges": 0,
            "accepted": [],
            "rejected": [],
            "disclosures": base_notes + [NOTE_FAILED],
            "note": NOTE_FAILED,
        }
        dossier.accounting["dependency"] = rec
        return rec

    accepted, rejected = apply_validated_edges(dossier, edges)
    disclosures = base_notes + rejected
    if not accepted and not rejected:
        disclosures = base_notes + [NOTE_FAILED]
        note = NOTE_FAILED
    elif not accepted and rejected:
        note = NOTE_FAILED
        if NOTE_FAILED not in disclosures:
            disclosures.append(NOTE_FAILED)
    else:
        note = NOTE_AB
    rec = {
        "n_edges": len(accepted),
        "accepted": accepted,
        "rejected": rejected,
        "disclosures": disclosures,
        "note": note,
    }
    dossier.accounting["dependency"] = rec
    return rec


def affected_downstream(conclusion_id: str, dossier: Dossier) -> list[str]:
    """沿 depends_on 反向做传递闭包；visited 环保护；按案卷序排序。"""
    reverse: dict[str, list[str]] = {}
    for con in dossier.conclusions:
        for prem in con.depends_on or []:
            reverse.setdefault(prem, []).append(con.id)
    reachable: list[str] = []
    visited: set[str] = {conclusion_id}
    stack = list(reverse.get(conclusion_id, []))
    while stack:
        nid = stack.pop()
        if nid in visited:
            continue
        visited.add(nid)
        reachable.append(nid)
        for child in reverse.get(nid, []):
            if child not in visited:
                stack.append(child)
    return _unique_by_dossier_order(reachable, dossier)


def upstream_failed(conclusion_id: str, dossier: Dossier) -> bool:
    """上游失效：status=dissent／存活证据删空／confidence==0.0。"""
    con = dossier.conclusion(conclusion_id)
    if con is None:
        return True
    if con.status == "dissent":
        return True
    if not dossier.evidences_of(conclusion_id):
        return True
    if float(con.confidence or 0.0) == 0.0:
        return True
    return False


def refresh_premise_broken(dossier: Dossier) -> None:
    """按当前 depends_on 重算 premise_broken（只亮牌，不改写下游结论文案）。"""
    for con in dossier.conclusions:
        broken: list[str] = []
        seen: set[str] = set()
        for up in con.depends_on or []:
            if up in seen:
                continue
            if upstream_failed(up, dossier):
                seen.add(up)
                broken.append(up)
        con.premise_broken = broken


def mutation_seed_ids(dossier: Dossier, payload: dict) -> list[str]:
    """从变更 payload 推断直接触及的结论 id（mutate 前调用，证据尚在）。"""
    seeds: list[str] = []
    cid = payload.get("conclusion_id")
    if cid:
        seeds.append(str(cid))
    eid = payload.get("evidence_id")
    if eid:
        ev = dossier.evidence(str(eid))
        if ev is not None:
            seeds.append(ev.conclusion_id)
    frm = payload.get("from")
    if frm:
        seeds.append(str(frm))
    to = payload.get("to")
    if to:
        seeds.append(str(to))
    cfid = payload.get("conflict_id")
    if cfid:
        for c in dossier.conflicts or []:
            if isinstance(c, dict) and c.get("id") == cfid:
                for k in ("a_id", "b_id"):
                    if c.get(k):
                        seeds.append(str(c[k]))
                w = (c.get("resolution") or {}).get("winner_id")
                if w and w != "tie":
                    seeds.append(str(w))
    return _unique_by_dossier_order(seeds, dossier)


def collect_affected(seeds: list[str], dossier: Dossier) -> list[str]:
    """多种子下游并集，按案卷序、无重复。"""
    acc: list[str] = []
    for s in seeds:
        acc.extend(affected_downstream(s, dossier))
    return _unique_by_dossier_order(acc, dossier)
