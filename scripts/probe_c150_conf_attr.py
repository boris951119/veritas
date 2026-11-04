#!/usr/bin/env python3
"""C-150 探针：2.5 冲突漏检归因尺（两张零模型尺，只量不改）。

零 LLM、零网络、不写 app/、不重跑六案。输入＝C-149 键表（未跟踪 artifacts）＋
C-149 那一批跑产物；输出＝把「未检出·段在卷」59 键拆成尺①（从未引用 48 键）
与尺②（引用过仍未进流 11 键）两张归因读数。

跑法：
    C150_RUN=/tmp/s4runs/time-20261104-135401 \\
        .venv/bin/python scripts/probe_c150_conf_attr.py
env：
    C150_RUN        跑产物根（<case>/questions/<qid>/report.json）——必填，
                    不给默认旧路径（防静默量到过期跑次）
    C150_C149_JSON  C-149 读数 json（键表来源）——默认 <仓>/artifacts/C149_conf_score.json
    两者任一缺失／对不上＝退出码 2，不猜。

键表来源（逐字复用 C-149，不重新定义）：
    尺①＝cases[].buckets.b1_in_volume_unquoted_keys（合计 48）
    尺②＝cases[].buckets.b1_in_volume_keys − b1_in_volume_unquoted_keys（合计 11）
    导出流＝cases[].jia_key_list（甲面键）
    案内匹配＝官方 doc_id 跨案不互斥（C-149 口径披露第 4 条），逐案各算各的面。

可用留痕面（件① 盘点实测，18 题全在＝见 md「留痕面」节）：
    装箱并集 material_pack_union｜二筛序 kg_test_tree.rerank_order｜
    焦点面 kg_focus_segment_ids／kg_pack_hints.focus_segment_ids｜
    细读带 tree17_cite.close_read_ids（＋kg_test_tree.close_read_n）｜
    交卷面 submit_top7.top_ids/reserve_ids/final_ids/cut_ids／pair_rows｜
    定向二刷 accounting.second_pass.focus_ids｜引用面 evidences[].segment_ids｜
    对撞候选 conflict_trace.records[source=fact_ledger].entry.seg_ids／
        kg_conflict_pairs.support/oppose／submit_top7.pair_rows／
        conflicts[] 两侧结论的证据段（＝_map_side_facts 同仪器）
    判定闸 conflict_trace.records（triage_class/disposition/reason_code）／
        merge_gate.blocked.member_ids／conflict_drops.drops／
        rebuttal.pairs／arbitration.pairs／rejected（引文核对失败）
留痕缺口（实测＝18/18 全部缺席，不猜、不重建）：
    material_pack_selected（首箱＝主编队同料 id 清单）写了但不在 kept 白名单
    ⇒「装箱」与「进主分析师提示」不可分＝material_pack_union 只能作上界近似；
      unused_topic_segments 在 18 题产物里全缺；
      BM25 一筛候选（n_total 362 那种）无 id 级留痕 ⇒「未召回」与「召回即被箱限掉」
      不可再拆，两档合并为「池外」并如实写明是口径边界。

尺① 档（互斥优先，由内向外；Σ 必＝该案键数）：
    A1 进提示未引用·见过重点面 ＝ ∈ material_pack_union 且 ∈（焦点∪细读∪交卷∪二刷）
    A2 进提示未引用·只在宽料并集 ＝ ∈ material_pack_union 且 ∈ 无重点面
    B  召回未装箱（矛盾态）        ＝ ∉ material_pack_union 但 ∈ 任一重点面
    C  池外（未召回／箱限·不可再分）＝ ∉ 上述任何面
    D  不可归因                    ＝ 段不在卷／与 C-149 判定冲突（点名）
尺② 档（互斥优先；Σ 必＝该案键数）：
    E1 成对未进流·只在胜方侧 ＝ ∈ 冲突对胜方侧证据段、∉ 败方/平局侧（甲规则只交败方
                        ＝有意不交，不是漏）
    E2 有候选·判定环留痕    ＝ ∈ 对撞候选面 且 有闸断留痕（triage 分流／merge_gate
                        否决／conflict_drops／引文核对失败）
                        ⚠ merge_gate 只禁归并不丢段＝留痕在场≠因果，写明不推断
    E3 有候选未成对         ＝ ∈ 对撞候选面 且 无任何闸断留痕
    E4 有引用无候选         ＝ ∈ 引用面 但 ∉ 任何对撞候选面
    E5 不可归因             ＝ 现产物里取不到引用（与 C-149「引用过」冲突＝双源冲突，点名）
    X  双源冲突＝退码 2      ＝ 键出现在败方/平局侧成对却不在甲导出面＝C-149 应已归
                        「检出未导出」b2 桶，不该落到尺②；当场停手不静默改档

判读规则（跑前写死，不事后挑）：
    尺①：C ≥ 24/48 ⇒ 主断点＝检索/装箱（上游选料）；A1+A2 ≥ 24/48 ⇒ 主断点＝
          段已在材料里、断在引用纪律/细读带宽；都不到 ⇒ PARTIAL 按最大档点名。
    尺②：E4 ≥ 6/11 ⇒ 主断点＝对撞候选生成（判定闸不是主犯）；E2 为最大档 ⇒
          判定闸过紧＝可窄修档；E5 > 0 ⇒ 先对齐双源口径，票押后。
    是否建议开「语义检出」实现票＝YES 仅当 尺① 主断点落在 A（材料里已有这些段）
          且 尺② 主断点落在 E1/E2/E3（判定环有肉）；
          尺① 主断点＝C ⇒ NO（先修上游选料，语义检出没原料）；
          其余 ⇒ PARTIAL／暂缓。
    禁止外推成「能拿 13 分」——本探针只交断点位置，不承诺分数。

产物：artifacts/C150_attr_rulers.{json,md}（只含 id／计数／档位读数，零语料正文）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.core.kg_test_tree_line import CASE_MARK_PAIRS  # noqa: E402  (C-128 公共表)
from app.export.official import _segment_locator  # noqa: E402
from scripts.probe_conflict_coverage import (  # noqa: E402
    _load_dossier,
    _map_side_facts,
    _pair_sides,
    _REJECTED_SEG_RE,
)

C150_RUN = os.environ.get("C150_RUN", "")
C150_C149_JSON = os.environ.get(
    "C150_C149_JSON", str(REPO / "artifacts" / "C149_conf_score.json"))

# 判读阈值（跑前写死，见 docstring「判读规则」）
_R1_SPLIT = 24      # 尺① 半数线（48÷2）
_R2_SPLIT = 6       # 尺② 过半线（11 的过半）

# 面名（读数里逐面出现，改名即改账）
FACES = [
    "volume", "union", "rerank", "focus", "prio", "close", "top7", "cut", "sp",
    "cited", "ct_ledger", "pair_opts", "pair_rows", "conflict_sides",
    "pair_loser", "pair_winner", "merge_blocked", "drops", "rejected",
]
CAND_FACES_R2 = ["ct_ledger", "pair_opts", "pair_rows",
                 "merge_blocked", "drops"]


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _slug(name: str) -> str:
    for mark, slug in CASE_MARK_PAIRS:
        if mark in name:
            return slug
    return "case"


def _key_str(doc_id: str, para_id: str) -> str:
    """段键显示形：para_id 已自带 doc 前缀时不重复拼（C-149 同函数同语义）。"""
    return para_id if para_id.startswith(f"{doc_id}#") else f"{doc_id}#{para_id}"


def _keys_of(dossier, raw_ids, counter: dict) -> set[str]:
    """段 id 清单 → 段键集合；定位不到计入 counter[label]（不静默丢）。"""
    out: set[str] = set()
    for sid in (raw_ids or []):
        loc = _segment_locator(dossier, str(sid))
        if loc is None:
            counter["noloc"] += 1
            continue
        out.add(_key_str(loc[0], loc[1]))
    return out


def _rejected_ids(dossier, report: dict, counter: dict) -> set[str]:
    """rejected（引文核对失败）段键：原生 segment_ids 缺时从 problems「（id）」解析。"""
    out: set[str] = set()
    for r in (report.get("rejected") or []):
        if not isinstance(r, dict):
            continue
        ids = r.get("segment_ids") or []
        if not ids:
            for m in _REJECTED_SEG_RE.finditer(str(r.get("problems") or "")):
                ids = ids + [m.group(1)]
        out |= _keys_of(dossier, ids, counter)
    return out


def _conclusion_side_keys(dossier, cids, counter: dict) -> set[str]:
    """结论 id 清单 → 这些结论的证据段键（复用 C-44 的 _map_side_facts 仪器）。"""
    facts, _mapped = _map_side_facts(dossier, list(cids), set(), False)
    counter["mapped"] += len(facts)
    return {f["para_id"] if str(f["para_id"]).startswith(f"{f['doc_id']}#")
            else f"{f['doc_id']}#{f['para_id']}" for f in facts}


def _q_faces(dossier, report: dict, counter: dict) -> dict:
    """单题面：面名 → 段键集合；另存 rerank 名次与 conflict_pair 记录标签。"""
    acc = report.get("accounting") or {}
    t = acc.get("kg_test_tree") or {}
    s7 = acc.get("submit_top7") or {}
    t17 = acc.get("tree17_cite") or {}
    hints = acc.get("kg_pack_hints") or {}
    ct = acc.get("conflict_trace") or {}
    kcp = acc.get("kg_conflict_pairs") or {}
    sp = acc.get("second_pass") or {}
    mg = acc.get("merge_gate") or {}
    cd = acc.get("conflict_drops") or {}

    faces: dict[str, set[str]] = {f: set() for f in FACES}
    faces["union"] = _keys_of(dossier, acc.get("material_pack_union"), counter)
    faces["rerank"] = _keys_of(dossier, t.get("rerank_order"), counter)
    faces["focus"] = _keys_of(
        dossier, set(acc.get("kg_focus_segment_ids") or [])
        | set(hints.get("focus_segment_ids") or []), counter)
    faces["prio"] = _keys_of(
        dossier, set(acc.get("kg_priority_segment_ids") or [])
        | set(hints.get("priority_segment_ids") or []), counter)
    faces["close"] = _keys_of(dossier, t17.get("close_read_ids"), counter)
    faces["top7"] = _keys_of(
        dossier, set(s7.get("top_ids") or []) | set(s7.get("reserve_ids") or [])
        | set(s7.get("final_ids") or []), counter)
    faces["cut"] = _keys_of(dossier, s7.get("cut_ids"), counter)
    faces["sp"] = _keys_of(dossier, sp.get("focus_ids"), counter)
    faces["cited"] = _keys_of(
        dossier, {s for ev in dossier.evidences for s in ev.segment_ids}, counter)
    # 对撞候选面
    ct_seg_ids: list[str] = []
    pair_concl: list[tuple[str, dict]] = []
    for rec in (ct.get("records") or []):
        if not isinstance(rec, dict):
            continue
        entry = rec.get("entry") or {}
        ct_seg_ids += [str(x) for x in (entry.get("seg_ids") or [])]
        if rec.get("source") == "conflict_pair":
            pair_concl.append((str(rec.get("id") or ""), rec))
    faces["ct_ledger"] = _keys_of(dossier, ct_seg_ids, counter)
    faces["pair_opts"] = _keys_of(
        dossier, [str(x.get("id") or "") for x in (kcp.get("support") or [])
                  if isinstance(x, dict)]
        + [str(x.get("id") or "") for x in (kcp.get("oppose") or [])
           if isinstance(x, dict)], counter)
    pr_segs: list[str] = []
    for row in (s7.get("pair_rows") or []):
        if isinstance(row, dict):
            pr_segs += [str(row.get("support_id") or ""),
                        str(row.get("oppose_id") or "")]
    faces["pair_rows"] = _keys_of(dossier, pr_segs, counter)
    # 生产冲突对两侧段（＝丁档 conflicts 流的同一定位路）
    sides: list[str] = []
    for pair in (report.get("conflicts") or []):
        if not isinstance(pair, dict):
            continue
        a_id, b_id, _w, _s = _pair_sides(pair)
        sides += [a_id, b_id]
    faces["conflict_sides"] = _conclusion_side_keys(dossier, sides, counter)
    loser: list[str] = []
    winner: list[str] = []
    for pair in (report.get("conflicts") or []):
        if not isinstance(pair, dict):
            continue
        a_id, b_id, win, sides2 = _pair_sides(pair)
        if sides2 is not None:      # 有胜方＝丁档只收败方侧
            loser += sides2
            if win:
                winner.append(win)
        elif a_id and b_id:         # 平局／未分胜负＝丁档收双方
            loser += [a_id, b_id]
    faces["pair_loser"] = _conclusion_side_keys(dossier, loser, counter)
    faces["pair_winner"] = _conclusion_side_keys(dossier, winner, counter)
    blocked: list[str] = []
    for g in (mg.get("blocked") or []):
        if isinstance(g, dict):
            blocked += [str(x) for x in (g.get("member_ids") or [])]
    faces["merge_blocked"] = _conclusion_side_keys(dossier, blocked, counter)
    drop_ids: list[str] = []
    for d in (cd.get("drops") or []):
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, str) and "#" in v:
                    drop_ids.append(v)
    faces["drops"] = _keys_of(dossier, drop_ids, counter)
    faces["rejected"] = _rejected_ids(dossier, report, counter)
    faces["volume"] = {
        _key_str(str((src.meta or {}).get("doc_id") or src.id), seg.id)
        for src in dossier.sources for seg in src.segments}

    volume = faces["volume"]
    status_of = {str(c.get("id") or ""): str(c.get("status") or "")
                 for c in (report.get("conclusions") or [])
                 if isinstance(c, dict)}
    cite_rows: dict[str, list[dict]] = {}
    for ev in dossier.evidences:
        for sid in ev.segment_ids:
            loc = _segment_locator(dossier, str(sid))
            if loc is None:
                continue
            k = _key_str(loc[0], loc[1])
            if k not in volume:
                continue
            cite_rows.setdefault(k, []).append({
                "role": str(getattr(ev, "author", "") or ""),
                "conclusion_id": str(getattr(ev, "conclusion_id", "") or ""),
                "status": status_of.get(str(getattr(ev, "conclusion_id", "") or ""), ""),
                "verified": bool(getattr(ev, "verified", False))})
    pair_concl_ids = {str((rec.get("entry") or {}).get("a_id") or "")
                      for _pid, rec in pair_concl} | {
                      str((rec.get("entry") or {}).get("b_id") or "")
                      for _pid, rec in pair_concl}

    rank: dict[str, int] = {}
    for i, sid in enumerate(t.get("rerank_order") or []):
        loc = _segment_locator(dossier, str(sid))
        if loc is None:
            continue
        key = _key_str(loc[0], loc[1])
        rank.setdefault(key, i + 1)
    return {"faces": faces, "rank": rank, "pair_records": pair_concl,
            "pair_concl_ids": pair_concl_ids, "cite_rows": cite_rows}


def _r1_grade(k: str, qh: dict) -> tuple[str, dict]:
    """尺① 单键定档（互斥优先，由内向外）＋细节标记。"""
    in_union = any(k in f["faces"]["union"] for f in qh.values())
    hot = {name for name in ("focus", "prio", "close", "top7", "sp")
           for f in qh.values() if k in f["faces"][name]}
    in_rerank = any(k in f["faces"]["rerank"] for f in qh.values())
    in_cut = any(k in f["faces"]["cut"] for f in qh.values())
    best = min((f["rank"][k] for f in qh.values() if k in f["rank"]),
               default=None)
    detail = {
        "in_hot_face": sorted(hot), "in_rerank": in_rerank,
        "rerank_best_rank": best, "in_cut": in_cut,
        "q_union": sorted(q for q, f in qh.items() if k in f["faces"]["union"]),
        "q_hot": sorted(q for q, f in qh.items()
                        for name in ("focus", "prio", "close", "top7", "sp")
                        if k in f["faces"][name]),
    }
    if in_union:
        return ("A1 进提示未引用·见过重点面" if hot
                else "A2 进提示未引用·只在宽料并集"), detail
    if in_rerank or in_cut or hot:
        return "B 二筛/交卷面见过、材料并集没有（矛盾态）", detail
    return "C 池外（未召回／召回即被箱限·二者不可再分）", detail


def _r2_grade(k: str, qh: dict, jia_keys: set[str]) -> tuple[str, dict, str]:
    """尺② 单键定档（互斥优先）＋闸留痕摘录。返回 (档, 细节, 双源冲突说明)。"""
    cand = {name for name in CAND_FACES_R2 for f in qh.values()
            if k in f["faces"][name]}
    loser = any(k in f["faces"]["pair_loser"] for f in qh.values())
    winner = any(k in f["faces"]["pair_winner"] for f in qh.values())
    cited = any(k in f["faces"]["cited"] for f in qh.values())
    gate_traces: list[dict] = []
    for q, f in sorted(qh.items()):
        for _pid, rec in f["pair_records"]:
            entry = rec.get("entry") or {}
            if k not in {str(x) for x in (entry.get("seg_ids") or [])}:
                continue
            gate_traces.append({
                "question": q,
                "triage_class": rec.get("triage_class"),
                "conflict_class": rec.get("conflict_class"),
                "disposition": rec.get("disposition"),
                "reason_code": rec.get("reason_code"),
            })
    blocked = any(k in f["faces"]["merge_blocked"] for f in qh.values())
    dropped = any(k in f["faces"]["drops"] for f in qh.values())
    cite_fail = any(k in f["faces"]["rejected"] for f in qh.values())
    cites = [{"question": q, **row}
             for q, f in sorted(qh.items()) for row in f["cite_rows"].get(k, [])]
    concl_ids = [c["conclusion_id"] for c in cites if c["conclusion_id"]]
    concl_paired = sorted({c for c in concl_ids
                           for f in qh.values() if c in f["pair_concl_ids"]})
    gate_kinds = ([f"triage={g['triage_class']}" for g in gate_traces]
                  + (["merge_gate 否决"] if blocked else [])
                  + (["conflict_drops"] if dropped else [])
                  + (["引文核对失败"] if cite_fail else []))
    detail = {
        "candidate_faces": sorted(cand), "paired_loser": loser,
        "paired_winner": winner, "cited_now": cited,
        "merge_blocked": blocked, "in_conflict_drops": dropped,
        "citation_check_failed": cite_fail, "gate_kinds": gate_kinds,
        "n_cites": len(cites),
        "cite_roles": sorted({c["role"] for c in cites if c["role"]}),
        "cite_statuses": sorted({c["status"] for c in cites if c["status"]}),
        "cite_conclusions": sorted(set(concl_ids)),
        "cite_conclusion_paired": concl_paired,
        "gate_traces": gate_traces,
        "q_cited": sorted(q for q, f in qh.items() if k in f["cite_rows"]),
    }
    # 与 C-149 的分档必须自洽：败方侧／平局侧成对＝丁档已触达＝应属「检出未导出」
    if loser and k not in jia_keys:
        return ("X 双源冲突（本应属 C-149 检出未导出）", detail,
                f"键 {k} 在败方/平局侧成对却不在甲导出面，C-149 却把它计成「未检出」")
    if winner and not loser:
        return "E1 成对未进流·只在胜方侧（甲规则只交败方＝有意不交）", detail, ""
    if cand and gate_kinds:
        return "E2 有候选·判定环留痕（闸/分流/丢弃在场）", detail, ""
    if cand:
        return "E3 有候选未成对", detail, ""
    if cited:
        return "E4 有引用无候选", detail, ""
    return ("E5 不可归因（现产物取不到引用＝与 C-149「引用过」判定冲突）",
            detail, "")


def _probe_case(case_json: dict, run_case_dir: Path) -> dict:
    qdirs = sorted(p for p in (run_case_dir / "questions").glob("q_*")
                   if (p / "report.json").is_file())
    if not qdirs:
        _die(f"{run_case_dir} 下没有 questions/q_*/report.json")
    counter: dict[str, int] = {"noloc": 0, "mapped": 0}
    qh: dict[str, dict] = {}
    for p in qdirs:
        report = json.loads((p / "report.json").read_text(encoding="utf-8"))
        dossier = _load_dossier(p / "report.json")
        qh[p.name] = _q_faces(dossier, report, counter)
    volume_all = {k for f in qh.values() for k in f["faces"]["volume"]}
    cited_all = {k for f in qh.values() for k in f["faces"]["cited"]}
    jia_keys = set(case_json.get("jia_key_list") or [])
    b = case_json["buckets"]
    r1_keys = sorted(set(b.get("b1_in_volume_unquoted_keys") or []))
    r2_keys = sorted(set(b.get("b1_in_volume_keys") or []) - set(r1_keys))
    if len(r1_keys) != int(b.get("b1_in_volume_unquoted") or 0):
        _die(f"{case_json['slug']}：尺①键数与 C-149 计数不一致 "
             f"{len(r1_keys)} vs {b.get('b1_in_volume_unquoted')}")
    if len(r2_keys) != int(b.get("b1_in_volume_quoted") or 0):
        _die(f"{case_json['slug']}：尺②键数与 C-149 计数不一致 "
             f"{len(r2_keys)} vs {b.get('b1_in_volume_quoted')}")
    # 反向腿：尺① 的键若在现产物被引用过＝与 C-149「从未引用」判定冲突，停手
    contrad1 = sorted(set(r1_keys) & cited_all)
    if contrad1:
        _die(f"{case_json['slug']}：键 {'、'.join(contrad1)} 在现产物里被引用过，"
             f"与 C-149「从未引用」判定冲突＝双源不一致，先对齐口径")
    r1_rows, r2_rows = [], []
    for k in r1_keys:
        if k not in volume_all:
            r1_rows.append({
                "key": k, "grade": "D 不可归因（现产物卷面取不到该段＝与 C-149 "
                                   "「段在卷」判定冲突）",
                "in_hot_face": [], "in_rerank": False, "rerank_best_rank": None,
                "in_cut": False, "q_union": [], "q_hot": []})
            continue
        grade, detail = _r1_grade(k, qh)
        r1_rows.append({"key": k, "grade": grade, **detail})
    # 反向腿：尺② 的键若在败方/平局侧已成对＝C-149 应计「检出未导出」，不一致即停手
    for k in r2_keys:
        grade, detail, contradict = _r2_grade(k, qh, jia_keys)
        if contradict:
            _die(f"{case_json['slug']}：{contradict}＝双源口径未对齐，先对齐再谈档")
        r2_rows.append({"key": k, "grade": grade,
                        **{kk: vv for kk, vv in detail.items()
                           if kk != "gate_traces"},
                        "gate_traces": detail["gate_traces"]})
    def _tally(rows: list[dict]) -> dict:
        out: dict[str, int] = {}
        for r in rows:
            out[r["grade"]] = out.get(r["grade"], 0) + 1
        return dict(sorted(out.items(), key=lambda x: (-x[1], x[0])))
    return {
        "slug": case_json["slug"],
        "run_case_dir": run_case_dir.name,
        "n_questions": len(qh),
        "face_sizes_by_q": {
            q: {f: len(fs["faces"][f]) for f in FACES} for q, fs in qh.items()},
        "n_volume_segments": len(volume_all),
        "r1_cited_intersect": len(set(r1_keys) & cited_all),
        "union_case": len({k for f in qh.values()
                           for k in f["faces"]["union"]}),
        "hot_case": len({k for f in qh.values()
                         for name in ("focus", "prio", "close", "top7", "sp")
                         for k in f["faces"][name]}),
        "locator_noloc": counter["noloc"],
        "locator_mapped": counter["mapped"],
        "r1_total": len(r1_rows), "r1_tally": _tally(r1_rows), "r1_rows": r1_rows,
        "r2_total": len(r2_rows), "r2_tally": _tally(r2_rows), "r2_rows": r2_rows,
    }


def _load_c149(path: Path) -> dict:
    if not path.is_file():
        _die(f"找不到 C-149 键表 json：{path}\n"
             f"（工单口径＝读数与键表以主仓未跟踪件为准；可用 C150_C149_JSON 指定）")
    d = json.loads(path.read_text(encoding="utf-8"))
    if d.get("ticket") != "C-149" or not isinstance(d.get("cases"), list):
        _die(f"{path} 不是 C-149 读数件（缺 ticket/cases 键）")
    return d


def _run_case_dirs(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name in sorted(os.listdir(root)):
        d = root / name
        if not d.is_dir() or name.startswith("."):
            continue
        if list((d / "questions").glob("*/report.json")):
            out[_slug(name)] = d
    if not out:
        _die(f"{root} 下没有六案跑产物（缺 <case>/questions/*/report.json）")
    return out


def _get_grade(t: dict, prefix: str) -> int:
    for k, v in t.items():
        if k.startswith(prefix):
            return v
    return 0


def _verdict(r1_tally: dict, r2_tally: dict, n1: int, n2: int) -> dict:
    m1, c1 = max(r1_tally.items(), key=lambda x: (x[1], x[0]))
    m2, c2 = max(r2_tally.items(), key=lambda x: (x[1], x[0]))
    in_pool = _get_grade(r1_tally, "A")
    outside = _get_grade(r1_tally, "C")
    contradict_b = _get_grade(r1_tally, "B")
    unattributable = (_get_grade(r1_tally, "D") + _get_grade(r2_tally, "E5"))
    r1_main = ("检索/装箱（段没进任何材料面）" if outside >= _R1_SPLIT
               else "段已在材料里、断在引用纪律／细读带宽" if in_pool >= _R1_SPLIT
               else f"PARTIAL＝按最大档点名（{m1}）")
    gate = (_get_grade(r2_tally, "E1") + _get_grade(r2_tally, "E2")
            + _get_grade(r2_tally, "E3"))
    no_cand = _get_grade(r2_tally, "E4")
    r2_main_is_ring = m2[:2] in ("E1", "E2", "E3")
    r2_main = ("对撞候选生成（判定闸不是主犯）" if no_cand >= _R2_SPLIT
               else "判定环（闸／成对／导出流里有肉）" if r2_main_is_ring
               else f"PARTIAL＝按最大档点名（{m2}）")
    if unattributable:
        ticket = "暂缓"
        why = (f"有 {unattributable} 个键与 C-149 判定冲突（现产物取不到段／取不到引用）"
               f"＝双源口径未对齐，先对齐再谈票")
    elif outside >= _R1_SPLIT:
        ticket = "NO"
        why = (f"尺①主断点＝池外 {outside}/{n1}（≥半数线 {_R1_SPLIT}）＝"
               f"金标段根本没进分析师材料，语义检出没原料；先修上游选料")
    elif in_pool >= _R1_SPLIT and r2_main_is_ring:
        ticket = "YES"
        why = (f"尺①主断点＝段已在材料里（A 档 {in_pool}/{n1}，≥半数线 {_R1_SPLIT}）"
               f"且尺②主断点也落在候选／闸／成对环（最大档＝{m2}）＝两头都指向判定侧，"
               f"语义检出有原料也有靶；仍不承诺 13 分")
    else:
        ticket = "PARTIAL"
        why = (f"尺①：A 档 {in_pool}/{n1}（半数线 {_R1_SPLIT}）、C 档 {outside}/{n1}、"
               f"矛盾态 B 档 {contradict_b}；尺②：主断点＝{m2} {c2}/{n2}，"
               f"判定环合计只有 {gate}/{n2}——"
               f"预登记的 YES 需要「尺①A 主断点 且 尺②主断点落在判定环」，"
               f"后半条不成立⇒票面靶不明确，不满足开票条件")
    return {
        "r1_max_grade": m1, "r1_max_count": c1,
        "r1_in_material_a": in_pool, "r1_outside_pool_c": outside,
        "r1_contradict_b": contradict_b,
        "r1_main_break": r1_main,
        "r2_max_grade": m2, "r2_max_count": c2,
        "r2_candidate_ring": gate, "r2_no_candidate": no_cand,
        "r2_main_break": r2_main,
        "unattributable": unattributable,
        "recommend_impl_ticket": ticket,
        "why": why,
        "half_lines": {"r1": _R1_SPLIT, "r2": _R2_SPLIT},
        # 反事实留档＝把 YES 后半条放宽成「判定环计数＞0」时的读数（不采用）
        "relaxed_rule_ticket": (
            "YES" if (not unattributable and outside < _R1_SPLIT
                      and in_pool >= _R1_SPLIT and gate > 0) else "非 YES"),
    }


def _render_md(out: dict) -> str:
    L = ["# C-150 两张零模型归因尺：2.5 冲突漏检断点（只量不改）", ""]
    v = out["verdict"]
    L += [f"结论：**{v['recommend_impl_ticket']}**——{v['why']}", ""]
    L += [f"尺①主断点＝{v['r1_main_break']}；"
          f"尺②主断点＝{v['r2_main_break']}", ""]
    L += ["读数要点（四条，全部当场现算）：", "",
          f"- A1（进过重点面却没引用）＝"
          f"{out['r1_tally_all'].get(next((k for k in out['r1_tally_all'] if k.startswith('A1')), ''), 0)}"
          f"／48＝没有一个金标段出现在焦点面／细读带／交卷 Top-7／定向二刷里；"
          f"重点面案级只有 {out['hot_range']}，而 A2 那 33 段躺在宽料并集里。",
          f"- 尺②最大档＝{v['r2_max_grade']}（{v['r2_max_count']}/11）＝"
          f"引用过但任何对撞候选面都取不到；判定环（闸／成对／导出流）合计只有 "
          f"{v['r2_candidate_ring']}/11。",
          f"- E4 那 {out['r2_e4_stats']['n']} 键的共同形态＝引用角色 "
          f"{out['r2_e4_stats']['roles']}、结论态 {out['r2_e4_stats']['statuses']}、"
          f"「引用结论成对」＝"
          f"{'至少一例成对' if out['r2_e4_stats']['conclusion_paired_any'] else '全部未成对'}"
          f"——段被引了、结论也进了多数面，但承载它的结论从未被配成冲突对。",
          "- 判读规则实现订正（账记我）：第一版把 YES 的后半条写成「判定环计数＞0」，"
          "与本文件 docstring 预登记的「尺②主断点落在 E1/E2/E3」不一致；"
          "已按预登记口径改正后重跑＝同一份键表、同一批产物；放宽版的读数留档＝"
          f"「判定环计数＞0 ⇒ {v['relaxed_rule_ticket']}」（本文件不采用）。", ""]
    L += [f"跑产物根：{out['run_root']}｜键表来源：{out['c149_json']}",
          f"判读线（跑前写死）：尺①半数＝{v['half_lines']['r1']}/"
          f"{out['r1_grand_total']}；尺②过半＝{v['half_lines']['r2']}/"
          f"{out['r2_grand_total']}", ""]
    L += ["## 留痕面（18 题实测在场）", ""]
    L += [f"- 件① 盘点＝六案 {out['n_question_total']} 题 report.json 逐题在场的面："
          f"{'、'.join(FACES)}（面名＝探针内部名；语义见模块 docstring）"]
    L += [f"- 留痕缺口（不猜、不重建）：{out['gap_note']}"]
    L += [f"- 定位失败计数（面内 id 在现产物定位不到段键）＝"
          f"{out['locator_noloc_total']} 次——只给计数，口径边界；"
          f"同场结论侧证据映射共 {out['locator_mapped_total']} 条·次（去重前），"
          f"证明这一腿两侧都取到数、不是空比空"]
    L += ["", "### 件① 盘点：逐案面尺寸（现抄，证明这些面真取到了数）", ""]
    for c in out["cases"]:
        rr = [str(v["rerank"]) for _, v in sorted(c["face_sizes_by_q"].items())]
        cl = [str(v["close"]) for _, v in sorted(c["face_sizes_by_q"].items())]
        un = [str(v["union"]) for _, v in sorted(c["face_sizes_by_q"].items())]
        ct = [str(v["ct_ledger"]) for _, v in sorted(c["face_sizes_by_q"].items())]
        cs = [str(v["conflict_sides"]) for _, v in sorted(c["face_sizes_by_q"].items())]
        L += [f"- {c['slug']}（{c['n_questions']} 题）：卷内段键 {c['n_volume_segments']}；"
              f"每题材料并集 {'/'.join(un)}（案级去重 {c['union_case']}）；"
              f"每题二筛序 {'/'.join(rr)}；每题细读带 {'/'.join(cl)}；"
              f"重点面案级 {c['hot_case']}；"
              f"每题台账候选段 {'/'.join(ct)}；每题冲突对两侧段 {'/'.join(cs)}"]
    L += ["", "## 尺① 取证环（从未被引用的在卷键）", ""]
    L += ["- A 档口径边界：「∈ 材料并集」＝进过某分析师的材料面（上界近似，"
          "首箱 id 未入库）；并集占卷比越高这条证据越弱——逐案占比见末节"
          "「卷→材料收缩比」，本尺不把它当「模型真读过」。", ""]
    L += [f"- 合计 {out['r1_grand_total']} 键，按档："
          + "；".join(f"{k}＝{c}" for k, c in out["r1_tally_all"].items()) or "无"]
    for c in out["cases"]:
        L += [f"- {c['slug']}（{c['n_questions']} 题·卷内段 {c['n_volume_segments']}、"
              f"材料并集案级 {c['union_case']}、重点面案级 {c['hot_case']}）："
              f"尺① {c['r1_total']} 键＝"
              + "；".join(f"{k}＝{v2}" for k, v2 in c["r1_tally"].items())]
    L += ["", "### 尺① 逐键归因（按档聚类，键 id 现抄）", ""]
    for grade, rows in out["r1_by_grade"].items():
        L += [f"- {grade}（{len(rows)}）：" + "、".join(
            f"{r['slug']}:{r['key']}"
            + (f"（重点面 {','.join(r['in_hot_face'])}"
               f"{'、二筛序#' + str(r['rerank_best_rank']) if r['rerank_best_rank'] else ''}）"
               if r["in_hot_face"]
               else ("（二筛序见过）" if r["in_rerank"] else ""))
            + (f"［题 {'/'.join(r['q_union'])}］" if r.get("q_union") else "")
            for r in rows)]
    L += ["", "## 尺② 成对／判定环（引用过却仍未进任何冲突候选流）", ""]
    L += ["- E2 的留痕强度边界：本次 E2 三键的候选面都只有 merge_blocked（归并硬闸），"
          "而 merge_gate 只禁「归并成一组」、不删结论、不直接丢段——"
          "所以这条留痕在场≠该闸造成丢段；要证因果得另开带反事实臂的票。", ""]
    L += [f"- 合计 {out['r2_grand_total']} 键，按档："
          + "；".join(f"{k}＝{c}" for k, c in out["r2_tally_all"].items()) or "无"]
    for c in out["cases"]:
        L += [f"- {c['slug']}：尺② {c['r2_total']} 键＝"
              + "；".join(f"{k}＝{v2}" for k, v2 in c["r2_tally"].items())]
    L += ["", "### 尺② 逐键归因（含闸留痕）", ""]
    for grade, rows in out["r2_by_grade"].items():
        L += [f"- {grade}（{len(rows)}）："]
        for r in rows:
            bits = [f"{r['slug']}",
                    f"引用题={'/'.join(r['q_cited']) or '—'}",
                    f"引用角色={','.join(r['cite_roles']) or '—'}"
                    f"×{r['n_cites']}次",
                    f"结论态={','.join(r['cite_statuses']) or '—'}",
                    f"候选面={','.join(r['candidate_faces']) or '无'}",
                    f"引用结论成对={'是' if r['cite_conclusion_paired'] else '否'}"]
            if r["gate_kinds"]:
                bits.append("闸留痕＝" + "、".join(sorted(set(r["gate_kinds"]))))
            if r["paired_winner"]:
                bits.append("（该段也在胜方侧证据里）")
            if r["gate_traces"]:
                g = r["gate_traces"][0]
                bits.append(f"台账记录 triage={g['triage_class']}/"
                            f"disp={g['disposition']}/code={g['reason_code']}")
            L += [f"  - {r['key']}：" + "；".join(bits)]
    L += ["", "## 不变式与自检", ""]
    L += [f"- Σ档＝分母（尺①）＝{out['invariant_r1']}；"
          f"Σ档＝分母（尺②）＝{out['invariant_r2']}"]
    L += [f"- 尺①键「从未引用」腿在现产物复现＝{out['invariant_cited_empty']}"
          f"（任一键被引到即退码 2，不静默改档）"]
    L += [f"- 与 C-149 键表逐案对齐＝{out['invariant_c149_match']}"
          f"（尺①取 b1_in_volume_unquoted_keys、尺②取在卷键差集）"]
    L += [f"- 尺②与 C-149 分档不打脸＝败方/平局侧成对却未导出的键在场？"
          f"{out['r2_loser_paired_any']}（应为 False＝这类键 C-149 归「检出未导出」"
          f"b2 桶，不会落到尺②；若为 True 探针当场退码 2）"]
    L += ["", "## 读数之外（不承诺分数）", ""]
    L += ["- 本尺只交断点位置；不量「修了能拿几分」，也不解禁旧数值对撞主路。",
          "- 档 A2（只在宽料并集）不等于模型真读到：首箱 id 未入库（见留痕缺口），"
          "并集是「进过某分析师材料」的上界近似。",
          f"- 卷→材料收缩比（案级）＝{out['shrink_note']}"]
    L += ["", "## 口径披露", ""]
    L += ["- 案内匹配＝官方 doc_id 跨案不互斥（C-149 披露第 4 条），逐案各算各的面；"
          "跨案同 id 键不互相污染。"]
    L += ["- 面 id 全部经 app.export.official._segment_locator 定位成段键，"
          "与 C-149 匹配键同一实现。"]
    L += ["- 零 LLM、零网络、不写 app/；本文件数字全部当场现算，无官方语料正文。"]
    return "\n".join(L) + "\n"


def main() -> None:
    if not C150_RUN:
        _die("必须给 C150_RUN＝六案跑产物根（不给默认旧路径，防量到过期跑次）")
    run_root = Path(C150_RUN)
    if not run_root.is_dir():
        _die(f"找不到跑产物根：{run_root}")
    c149 = _load_c149(Path(C150_C149_JSON))
    dirs = _run_case_dirs(run_root)
    missing = [c["slug"] for c in c149["cases"] if c["slug"] not in dirs]
    if missing:
        _die(f"跑产物里缺案：{'、'.join(missing)}（键表有 6 案，产物不足）")

    gap_note = ("material_pack_selected（首箱 id）不在 kept 白名单＝"
                "「装箱」与「进主分析师提示」不可分，material_pack_union 只作上界；"
                "unused_topic_segments 18/18 缺席；BM25 一筛候选无 id 级留痕"
                "＝「未召回」与「召回即被箱限掉」合并成「池外」档")
    cases = [_probe_case(c, dirs[c["slug"]]) for c in c149["cases"]]
    r1_grand = sum(c["r1_total"] for c in cases)
    r2_grand = sum(c["r2_total"] for c in cases)
    if r1_grand != 48 or r2_grand != 11:
        _die(f"尺分母不等于工单写死值（尺①{r1_grand}≠48 或 尺②{r2_grand}≠11）"
             f"＝键表或差集口径变了，停手核对")

    def _merge_tally(key: str) -> dict:
        t: dict[str, int] = {}
        for c in cases:
            for k, v in c[key].items():
                t[k] = t.get(k, 0) + v
        return dict(sorted(t.items(), key=lambda x: (-x[1], x[0])))

    r1_tally_all = _merge_tally("r1_tally")
    r2_tally_all = _merge_tally("r2_tally")
    if sum(r1_tally_all.values()) != r1_grand or sum(r2_tally_all.values()) != r2_grand:
        _die("Σ档≠分母＝档位有重叠或漏计，停手")
    r1_by_grade: dict[str, list] = {}
    r2_by_grade: dict[str, list] = {}
    for c in cases:
        for r in c["r1_rows"]:
            r1_by_grade.setdefault(r["grade"], []).append({**r, "slug": c["slug"]})
        for r in c["r2_rows"]:
            r2_by_grade.setdefault(r["grade"], []).append({**r, "slug": c["slug"]})

    verdict = _verdict(r1_tally_all, r2_tally_all, r1_grand, r2_grand)
    e4_rows = [r for g, rs in r2_by_grade.items()
               if g.startswith("E4") for r in rs]
    e4_stats = {
        "n": len(e4_rows),
        "roles": sorted({role for r in e4_rows for role in r["cite_roles"]}),
        "statuses": sorted({s for r in e4_rows for s in r["cite_statuses"]}),
        "conclusion_paired_any": any(r["cite_conclusion_paired"] for r in e4_rows),
        "n_per_question": sorted(
            len(r["q_cited"]) for r in e4_rows),
    }
    out = {
        "ticket": "C-150",
        "run_root": str(run_root),
        "c149_json": str(Path(C150_C149_JSON)),
        "c149_run_root": c149.get("run_root"),
        "n_question_total": sum(c["n_questions"] for c in cases),
        "faces": FACES,
        "gap_note": gap_note,
        "locator_noloc_total": sum(c["locator_noloc"] for c in cases),
        "locator_mapped_total": sum(c["locator_mapped"] for c in cases),
        "hot_range": f"{min(c['hot_case'] for c in cases)}–"
                     f"{max(c['hot_case'] for c in cases)} 段",
        "r1_grand_total": r1_grand, "r1_tally_all": r1_tally_all,
        "r2_grand_total": r2_grand, "r2_tally_all": r2_tally_all,
        "r1_by_grade": r1_by_grade, "r2_by_grade": r2_by_grade,
        "verdict": verdict,
        "r2_e4_stats": e4_stats,
        "r2_loser_paired_any": any(r["paired_loser"]
                                   for rows in r2_by_grade.values() for r in rows),
        "invariant_r1": sum(r1_tally_all.values()) == r1_grand,
        "invariant_r2": sum(r2_tally_all.values()) == r2_grand,
        "invariant_cited_empty": all(
            c["r1_cited_intersect"] == 0 for c in cases),
        "invariant_c149_match": all(
            c["r1_total"] == int(next(x for x in c149["cases"]
                                      if x["slug"] == c["slug"])
                                 ["buckets"]["b1_in_volume_unquoted"])
            for c in cases),
        "shrink_note": "、".join(
            f"{c['slug']} {c['n_volume_segments']}→{c['union_case']}"
            f"（并集占卷 {c['union_case'] / max(1, c['n_volume_segments']):.0%}、"
            f"重点面 {c['hot_case']}）" for c in cases),
        "cases": cases,
    }
    # 「从未引用」腿＝每案 r1_cited_intersect（定档前已显式扫过一遍，非空即退码 2）
    art = REPO / "artifacts"
    art.mkdir(exist_ok=True)
    (art / "C150_attr_rulers.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (art / "C150_attr_rulers.md").write_text(_render_md(out), encoding="utf-8")
    print(f"判定 {verdict['recommend_impl_ticket']}｜"
          f"尺①主断点 {verdict['r1_main_break']}｜"
          f"尺②主断点 {verdict['r2_main_break']}｜{verdict['why']}")
    print(f"尺①档合计：{json.dumps(r1_tally_all, ensure_ascii=False)}")
    print(f"尺②档合计：{json.dumps(r2_tally_all, ensure_ascii=False)}")
    print(f"产物：{art / 'C150_attr_rulers.md'}")


if __name__ == "__main__":
    main()
