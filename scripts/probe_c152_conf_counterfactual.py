#!/usr/bin/env python3
"""C-152 探针：冲突漏检反事实尺（两张零模型尺，只量不改）。

把 C-150 的两处断点各量一把「假如只改这一环，能买到多少」的反事实尺，
用来判定要不要开实现票——本探针不调模型、不联网、不改 app/、不重跑六案。

跑法：
    C152_RUN=/tmp/s4runs/time-20261104-135401 \\
        .venv/bin/python scripts/probe_c152_conf_counterfactual.py
env（三者都要在场，缺＝退码 2，不猜）：
    C152_RUN        六案跑产物根（<case>/questions/<qid>/report.json）——必填
    C152_C149_JSON  C-149 键表（默认 <仓>/artifacts/C149_conf_score.json）
    C152_C150_JSON  C-150 逐键归因（默认 <仓>/artifacts/C150_attr_rulers.json）

尺① 重点面反事实（答「取证环是不是带宽饥饿」）
    现有可用序＝`accounting.kg_test_tree.rerank_order`（C-140 起的二筛显式全序；
    现行交卷面 submit_top7 的候选池就是它，见 app/core/submit_top7.py，候选池注释）。
    反事实面＝该序的前 N 段，N∈{7,15,30}（对照值＝产物里现抄的案级重点面尺寸，
    逐题区间都写进 artifacts，不在本 docstring 里预填数字）。
    三面各自对照（现值，不反事实，因产物里没有它们各自的独立候选序）：
        focus＝kg_focus_segment_ids∪kg_pack_hints.focus_segment_ids
        细读＝tree17_cite.close_read_ids
        交卷＝submit_top7.top_ids/reserve_ids/final_ids
    量：C-150 尺①那 48 键（按档 A2／C 分列）进入前 N 面的键数；给覆盖曲线。
    ⚠ 留痕缺口（记缺口、不重建）：细读面没有独立候选序留痕（产物里只有 close_read
      本身 1–3 段），故细读臂的"扩面"只能用 rerank 前 N 代理；续盒并集
      material_pack_union 无序⇒不可反事实；首箱 id 未入库（C-150 已记）。

尺② 结论级配对反事实（答「E4 那 7 键是没规则、缺腿，还是输入面里就没有对侧」）
    两把口径分别量、都写进产物，不许互相冒充：
    口径甲＝现行成对规则原样复放（生产函数，零 LLM）：
        活动集＝status=="majority" 且有证据（＝arbiter._is_active 同判据）
        候选对＝app.core.conflict_pairing.build_candidate_pairs（同主体×议题维重叠
                或同主体极性对立 forced_polarity）
        主体闸＝subject_mismatch_reason；合法性＝validate_conflict
    口径乙＝案无关的机械对侧尺（工单点名的 conflict_trace／fact_ledger 口径）：
        段级对侧＝find_collisions(dossier) 同（实体×指标）多值、且跨信源；
        留痕对侧＝accounting.conflict_trace.records[source=fact_ledger].entry.seg_ids
                 （附 triage_class／disposition 现抄）；
        其余机械面＝kg_conflict_pairs.support/oppose、submit_top7.pair_rows、
                 merge_gate.blocked、conflict_drops、rejected、dissent、生产导出冲突对两侧；
        结论级反事实＝把对撞组里「跨信源＋异值」的两段抬到结论级（两端都要挂到同题
                 活动集里的结论），再过现行两道闸（主体闸＋合法性闸）。
    档（互斥优先，取该键所有题里的最强一档；C>B>D>A>E）：
        C 有对侧腿·现行规则可配却未配 ＝ 反事实对里至少一条两道闸全过
        B 有对侧腿·被现行闸挡         ＝ 反事实对存在但闸不过（缺腿名现抄）
        F 承载结论都不在活动集         ＝ 非 majority／无证据（现行配对的输入面没有它）
        D 段级有对侧·抬不到结论级     ＝ 该键在对撞组里有对侧键，或其他机械面有痕迹，
                                        但抬不到结论级（对侧段没挂到同题活动结论）
        A 输入面无机械可检对侧        ＝ 上述机械面（对撞／台账留痕／kg 候选／pair_rows／
                                        归并闸／丢弃／rejected／dissent）全无对侧 → 按工单
                                        第 3 条记「输入面无对侧」，不假装规则能造出来
        E 不可归因                    ＝ 现产物里取不到承载结论（与 C-150 判定冲突＝点名）
    ⚠ 口径甲的 0 候选不是本尺的故障，是规则的覆盖洞：本尺现抄并披露
      extract_subject／extract_topics／polarity_of 在六案终局结论面上的命中数
      （主体命中为 0 时 build_candidate_pairs 按构造产不出候选——词表是「客户甲/A」
       那套企业口径；此时生产走的是「无程序候选→模型自由检出＋事后主体闸」那条
       兜底路，本尺禁用 LLM，故口径甲只能读到 0，不许把 0 说成「输入面干净」）。
    ⚠ 留痕缺口：产物面只留终局结论集（被归并吸收的结论不在场）⇒ 本尺重跑的输入面
      ＝「改前 detect 当时活动集」的近似，不是同一份；对账腿＝当场比
      len(find_collisions) vs 产物 conflict_trace 里 source=fact_ledger 的记录数，
      不相等就点名（近似程度可量，不靠嘴说）。
    卫生：本尺不写结论原文，只写 id／计数／档位枚举（metric 名只取长度不取文本）。

开票判据（工单预登记，跑前写死，逐字执行）
    开「重点面／带宽」实现票 ⇔ cov(N=15) ≥ 24 或 cov(N=30) ≥ 24，
                              且该 N 新增覆盖里的键主要来自现 A2 档（A2 数 ≥ C 档数）。
    开「候选生成／成对规则」实现票 ⇔ 尺②档 C 的键数 ≥ 4／7。
    两条都不成立 ⇒ 仍否，只交读数＋下一缺口。禁止外推「能拿 13 分」。
    判据口径的补充说明（跑前写清，不是事后改线）：档 C 用口径乙（案无关机械对侧
    ＋现行两道闸）判，因为口径甲在主体命中为 0 的案上按构造必为 0 候选，
    拿 0 去比 4 是把「规则没词表」读成「输入面没对侧」——两件事都要单独成立。
    尺①另记一条上界对照：并集面（material_pack_union，无序）覆盖＝「这些键进过材料」
    的上界近似，与「有序可扩」不是一回事；两者都写进产物，不许互相冒充。

产物：artifacts/C152_counterfactual.{json,md}（只含 id／计数／档位读数）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.core.conflict_pairing import (  # noqa: E402
    build_candidate_pairs,
    extract_subject,
    extract_topics,
    polarity_of,
    subject_mismatch_reason,
)
from app.core.conflicts import (  # noqa: E402
    ConflictPair, dissent_conclusions, validate_conflict)
from app.core.fact_ledger import find_collisions  # noqa: E402
from app.core.kg_test_tree_line import CASE_MARK_PAIRS  # noqa: E402
from app.export.official import _segment_locator  # noqa: E402
from scripts.probe_conflict_coverage import (  # noqa: E402
    _REJECTED_SEG_RE,
    _load_dossier,
    _map_side_facts,
    _pair_sides,
)

C152_RUN = os.environ.get("C152_RUN", "")
C152_C149_JSON = os.environ.get(
    "C152_C149_JSON", str(REPO / "artifacts" / "C149_conf_score.json"))
C152_C150_JSON = os.environ.get(
    "C152_C150_JSON", str(REPO / "artifacts" / "C150_attr_rulers.json"))

N_LEVELS = (7, 15, 30)
GATE_COVER = 24          # 工单原文：48 键覆盖 ≥24（半数）
GATE_PAIRED = 4          # 工单原文：E4 中 ≥4/7 判为「可配却未配」
EXPECT_R1, EXPECT_R2 = 48, 7   # C-150 交账写死的两把尺分母


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _slug(name: str) -> str:
    for mark, slug in CASE_MARK_PAIRS:
        if mark in name:
            return slug
    return "case"


def _key_str(doc_id: str, para_id: str) -> str:
    return para_id if para_id.startswith(f"{doc_id}#") else f"{doc_id}#{para_id}"


def _keys(dossier, raw_ids, counter: dict) -> list[str]:
    """段 id 序→段键序（保序、就地定位；定位不到计数并进 counter）。"""
    out: list[str] = []
    for sid in (raw_ids or []):
        loc = _segment_locator(dossier, str(sid))
        if loc is None:
            counter["noloc"] += 1
            continue
        out.append(_key_str(loc[0], loc[1]))
    return out


def _concl_side_keys(dossier, cids, counter: dict) -> set[str]:
    """结论 id → 证据段键（与 C-44/C-150 同一仪器 _map_side_facts）。"""
    facts, _mapped = _map_side_facts(dossier, list(cids), set(), False)
    counter["mapped"] += len(facts)
    return {_key_str(f["doc_id"], f["para_id"]) for f in facts}


def _cf_pair_legs(dossier, a: str, b: str) -> dict:
    """反事实对过现行两道机械闸；返回闸结果＋缺腿名。"""
    pair = ConflictPair(a_id=a, b_id=b, topic="cf", description="C-152 反事实（不落产物）")
    mismatch = subject_mismatch_reason(dossier, a, b)
    problems = [] if mismatch else validate_conflict(pair, dossier)
    fail_legs = []
    if mismatch:
        fail_legs.append("主体闸")
    for p in problems:
        if "无存活证据" in p:
            fail_legs.append("可核验")
        elif "不存在" in p or "相同" in p:
            fail_legs.append("合法性")
        else:
            fail_legs.append("合法性")
    return {"ok": not mismatch and not problems, "fail_legs": fail_legs}


def _collision_face(dossier, counter: dict) -> tuple[dict, dict, int, int]:
    """口径乙·段级：find_collisions → 键→对撞组摘要＋键→跨源异值对侧键清单。

    返回 (groups_by_key, opp_by_key, n_collisions, n_seg_pairs)：
      groups_by_key[key] ＝ [{metric_len, n_facts, cross_source, time_class,
                             n_other_keys}]（不落 metric 文本，只落长度）
      opp_by_key[key]    ＝ [(对侧键, 对侧条数)]，供结论级抬升用
      n_seg_pairs        ＝ 跨源或异值的「段×段」配对数（无序，一组内逐对计一次）
    """
    by_key: dict[str, list[dict]] = {}
    opp: dict[str, list[tuple[str, int]]] = {}
    collisions = find_collisions(dossier)
    n_seg_pairs = 0
    for col in collisions:
        located: dict[str, list] = {}
        for f in col.facts:
            loc = _segment_locator(dossier, str(f.seg_id))
            if loc is None or not loc[0] or not loc[1]:
                counter["noloc"] += 1
                continue
            located.setdefault(_key_str(loc[0], loc[1]), []).append(f)
        if not located:
            continue
        items = sorted(located.items())
        for i, (key, fs) in enumerate(items):
            vals = {f.value for f in fs}
            srcs = {f.source_id for f in fs}
            others: list[tuple[str, int]] = []
            for k2, g2 in items:
                if k2 == key:
                    continue
                v2 = {f.value for f in g2}
                s2 = {f.source_id for f in g2}
                if not (v2 - vals) or not (s2 - srcs):
                    continue          # 对侧＝既异值又异源（与台账 cross_source 同语义）
                others.append((k2, len(g2)))
                if key < k2:
                    n_seg_pairs += 1
            by_key.setdefault(key, []).append({
                "metric_len": len(str(col.metric or "")),
                "n_facts": len(col.facts),
                "cross_source": bool(col.cross_source),
                "time_class": str(col.time_class),
                "n_other_keys": len(others),
            })
            if others:
                opp.setdefault(key, []).extend(others)
    return by_key, opp, len(collisions), n_seg_pairs


def _q_read(dossier, report: dict, counter: dict) -> dict:
    """单题读数：二筛全序＋三面现值 id＋活动集＋逐键承载结论＋两把尺②口径。"""
    acc = report.get("accounting") or {}
    t = acc.get("kg_test_tree") or {}
    s7 = acc.get("submit_top7") or {}
    t17 = acc.get("tree17_cite") or {}
    hints = acc.get("kg_pack_hints") or {}
    sp = acc.get("second_pass") or {}
    ct = acc.get("conflict_trace") or {}
    kcp = acc.get("kg_conflict_pairs") or {}
    mg = acc.get("merge_gate") or {}
    cd = acc.get("conflict_drops") or {}

    rerank = _keys(dossier, t.get("rerank_order"), counter)
    focus = set(_keys(dossier, set(acc.get("kg_focus_segment_ids") or [])
                      | set(hints.get("focus_segment_ids") or []), counter))
    close = set(_keys(dossier, t17.get("close_read_ids"), counter))
    prio = set(_keys(dossier, acc.get("kg_priority_segment_ids") or [], counter))
    submit = set(_keys(
        dossier, set(s7.get("top_ids") or []) | set(s7.get("reserve_ids") or [])
        | set(s7.get("final_ids") or []), counter))
    sp_ids = set(_keys(dossier, sp.get("focus_ids"), counter))
    union = set(_keys(dossier, acc.get("material_pack_union"), counter))

    active: list[str] = []
    status_of: dict[str, str] = {}
    statements: list[str] = []
    for con in (report.get("conclusions") or []):
        if not isinstance(con, dict):
            continue
        cid = str(con.get("id") or "")
        if not cid:
            continue
        st = str(con.get("statement") or "")
        status_of[cid] = str(con.get("status") or "")
        statements.append(st)
        if status_of[cid] == "majority" and dossier.evidences_of(cid):
            active.append(cid)
    active_set = set(active)

    # 口径甲的输入面覆盖（现抄，证明 0 候选不是仪器坏了）
    rule_cover = {
        "n_concl": len(status_of),
        "n_subject": sum(1 for s in statements if extract_subject(s)),
        "n_topics": sum(1 for s in statements if extract_topics(s)),
        "n_polarity": sum(1 for s in statements if polarity_of(s)),
    }

    carriers: dict[str, list[str]] = {}
    for ev in dossier.evidences:
        for sid in ev.segment_ids:
            loc = _segment_locator(dossier, str(sid))
            if loc is None:
                counter["noloc"] += 1
                continue
            carriers.setdefault(_key_str(loc[0], loc[1]), []).append(
                str(getattr(ev, "conclusion_id", "") or ""))

    pairs = build_candidate_pairs(dossier, active) if len(active) >= 2 else []

    # 口径乙·机械面对侧
    coll_by_key, coll_opp, n_coll, n_seg_pairs = _collision_face(dossier, counter)
    ct_keys: dict[str, list[dict]] = {}
    ledger_recs = 0
    for rec in (ct.get("records") or []):
        if not isinstance(rec, dict) or rec.get("source") != "fact_ledger":
            continue
        ledger_recs += 1
        for sid in ((rec.get("entry") or {}).get("seg_ids") or []):
            k = _keys(dossier, [sid], counter)
            for kk in k:
                ct_keys.setdefault(kk, []).append({
                    "triage_class": str(rec.get("triage_class") or ""),
                    "disposition": str(rec.get("disposition") or ""),
                    "conflict_class": str(rec.get("conflict_class") or ""),
                })

    # 其余机械面（键名与 C-150 同一套取法：段 id 走 _keys，结论 id 走证据侧映射）
    segish = {
        "pair_opts": [str(x.get("id") or "") for x in (kcp.get("support") or [])
                      if isinstance(x, dict)]
        + [str(x.get("id") or "") for x in (kcp.get("oppose") or [])
           if isinstance(x, dict)],
        "pair_rows": [v for row in (s7.get("pair_rows") or []) if isinstance(row, dict)
                      for v in (str(row.get("support_id") or ""),
                                str(row.get("oppose_id") or ""))],
        "drops": [v for d in (cd.get("drops") or []) if isinstance(d, dict)
                  for v in d.values() if isinstance(v, str) and "#" in v],
    }
    faces_r2: dict[str, set[str]] = {
        name: set(_keys(dossier, [i for i in ids if i], counter))
        for name, ids in segish.items()}
    faces_r2["merge_blocked"] = _concl_side_keys(
        dossier, [str(x) for g in (mg.get("blocked") or []) if isinstance(g, dict)
                  for x in (g.get("member_ids") or [])], counter)
    rej_ids: list[str] = []
    for r in (report.get("rejected") or []):
        if not isinstance(r, dict):
            continue
        ids = list(r.get("segment_ids") or [])
        for m in _REJECTED_SEG_RE.finditer(str(r.get("problems") or "")):
            ids.append(m.group(1))
        rej_ids += [str(i) for i in ids]
    faces_r2["rejected"] = set(_keys(dossier, rej_ids, counter))
    faces_r2["dissent"] = _concl_side_keys(
        dossier, [str(c.id) for c in dissent_conclusions(dossier)], counter)
    sides: list[str] = []
    for pair in (report.get("conflicts") or []):
        if not isinstance(pair, dict):
            continue
        a_id, b_id, _w, _s = _pair_sides(pair)
        sides += [x for x in (a_id, b_id) if x]
    faces_r2["conflict_sides"] = _concl_side_keys(dossier, sides, counter)

    # 口径乙·结论级反事实：对侧段两端都挂到同题活动结论，再过现行两道闸
    cf_pairs: list[dict] = []
    seen_cf: set[tuple[str, str]] = set()
    for key, others in coll_opp.items():
        cids_a = sorted({c for c in carriers.get(key, []) if c in active_set})
        if not cids_a:
            continue
        for k2, _n in others:
            cids_b = sorted({c for c in carriers.get(k2, []) if c in active_set})
            for a in cids_a:
                for b in cids_b:
                    if a == b:
                        continue
                    sig = tuple(sorted((a, b)))
                    if sig in seen_cf:
                        continue
                    seen_cf.add(sig)
                    legs = _cf_pair_legs(dossier, a, b)
                    cf_pairs.append({
                        "a": a, "b": b, "keys": tuple(sorted((key, k2))),
                        "ok": legs["ok"], "fail_legs": legs["fail_legs"],
                    })

    return {
        "rerank": rerank,
        "face_focus": focus, "face_close": close, "face_prio": prio,
        "face_submit": submit, "face_sp": sp_ids, "face_union": union,
        "n_active": len(active), "n_conclusions": len(status_of),
        "active": active, "status_of": status_of, "carriers": carriers,
        "pairs": pairs, "rule_cover": rule_cover,
        "coll_by_key": coll_by_key, "coll_opp": coll_opp,
        "ct_keys": ct_keys, "faces_r2": faces_r2, "cf_pairs": cf_pairs,
        "n_collisions": n_coll, "n_ledger_recs": ledger_recs,
        "n_seg_pairs": n_seg_pairs,
    }


def _grade_r1(k: str, qh: dict, grade_from_c150: str) -> dict:
    """尺①：该键在各 N 档反事实面里的最早出现位置。"""
    ranks = [f["rerank"].index(k) + 1 for f in qh.values() if k in f["rerank"]]
    best = min(ranks, default=None)
    hot_now = sorted({name for name in ("face_focus", "face_close", "face_prio",
                                        "face_submit", "face_sp")
                      for f in qh.values() if k in f[name]})
    return {"key": k, "grade_c150": grade_from_c150,
            "rerank_best_pos": best, "faces_now": hot_now,
            "in_rerank": best is not None,
            "in_union": any(k in f["face_union"] for f in qh.values())}


def _grade_r2(k: str, qh: dict) -> tuple[str, dict]:
    """尺②：该键的两把机械口径读数；取最强一档（C>B>D>A>E）。"""
    detail = {"conclusions": [], "statuses": [], "questions": [],
              "in_active": False, "n_cand_pairs": 0,
              "n_coll_groups": 0, "n_coll_other_keys": 0, "n_ct_recs": 0,
              "triage_classes": [], "cross_source": False,
              "n_cf_pairs": 0, "cf_ok": False, "fail_legs": [],
              "other_mech_faces": []}
    for q, f in sorted(qh.items()):
        cids = sorted({c for c in f["carriers"].get(k, []) if c})
        if not cids:
            continue
        detail["questions"].append(q)
        detail["conclusions"] += cids
        detail["statuses"] += [f["status_of"].get(c, "") for c in cids]
        detail["in_active"] = detail["in_active"] or bool(set(cids) & set(f["active"]))
        cidset = set(cids)
        mine = [p for p in f["pairs"] if p["a"] in cidset or p["b"] in cidset]
        detail["n_cand_pairs"] += len(mine)
        for g in (f["coll_by_key"].get(k) or []):
            detail["n_coll_groups"] += 1
            detail["n_coll_other_keys"] += int(g["n_other_keys"])
            detail["cross_source"] = detail["cross_source"] or bool(g["cross_source"])
        for r in (f["ct_keys"].get(k) or []):
            detail["n_ct_recs"] += 1
            detail["triage_classes"].append(r["triage_class"])
        for name, ks in f["faces_r2"].items():
            if k in ks and name not in detail["other_mech_faces"]:
                detail["other_mech_faces"].append(name)
        cf = [p for p in f["cf_pairs"] if cidset & set(p["keys"])]
        detail["n_cf_pairs"] += len(cf)
        if any(p["ok"] for p in cf):
            detail["cf_ok"] = True
        for p in cf:
            for leg in p["fail_legs"]:
                if leg not in detail["fail_legs"]:
                    detail["fail_legs"].append(leg)
    detail["conclusions"] = sorted(set(detail["conclusions"]))
    detail["statuses"] = sorted({s for s in detail["statuses"] if s})
    detail["triage_classes"] = sorted(set(detail["triage_classes"]))
    detail["other_mech_faces"].sort()
    if not detail["conclusions"]:
        return ("E 不可归因（现产物取不到承载该段的结论＝与 C-150 判定冲突）", detail)
    if detail["cf_ok"]:
        grade = "C 有对侧腿·现行两道闸全过＝可配却未配（缺的是候选生成那一腿）"
    elif detail["n_cf_pairs"]:
        grade = ("B 有对侧腿·被现行闸挡（缺腿＝"
                 + "／".join(detail["fail_legs"]) + "）")
    elif not detail["in_active"]:
        grade = "F 承载结论都不在活动集（非 majority／无证据）＝现行配对的输入面没有它"
    elif detail["n_coll_other_keys"] or detail["other_mech_faces"]:
        grade = ("D 段级／留痕面有对侧痕迹·抬不到结论级"
                 f"（对侧键 {detail['n_coll_other_keys']}、其他机械面 "
                 f"{'／'.join(detail['other_mech_faces']) or '无'}）")
    else:
        grade = ("A 输入面无机械可检对侧（对撞组／台账留痕／kg 候选／交卷成对行／"
                 "归并闸／丢弃／rejected／dissent 八面皆无对侧＝按工单第 3 条记账，"
                 "不假装规则能造出来）"
                 + (f"［注：该键在 {detail['n_coll_groups']} 组对撞里但对侧键 0＝"
                    f"同值或同源重复报道］" if detail["n_coll_groups"] else ""))
    return grade, detail


def _probe_case(c149_case: dict, c150_case: dict, run_case_dir: Path) -> dict:
    qdirs = sorted(p for p in (run_case_dir / "questions").glob("q_*")
                   if (p / "report.json").is_file())
    if not qdirs:
        _die(f"{run_case_dir} 下没有 questions/q_*/report.json")
    counter: dict[str, int] = {"noloc": 0, "mapped": 0}
    qh: dict[str, dict] = {}
    dossiers: dict[str, object] = {}
    for p in qdirs:
        report = json.loads((p / "report.json").read_text(encoding="utf-8"))
        dossiers[p.name] = _load_dossier(p / "report.json")
        qh[p.name] = _q_read(dossiers[p.name], report, counter)

    r1_keys = list(c150_case["r1_rows"])
    if len(r1_keys) != c149_case["buckets"]["b1_in_volume_unquoted"]:
        _die(f"{c149_case['slug']}：C-150 尺①行数与 C-149 键数不一致")
    rows_r1 = [_grade_r1(r["key"], qh, r["grade"]) for r in r1_keys]

    e4_keys = [r["key"] for r in c150_case["r2_rows"]
               if r["grade"].startswith("E4")]
    rows_r2, r2_tally = [], {}
    for k in e4_keys:
        grade, detail = _grade_r2(k, qh)
        head = grade[0]
        r2_tally[head] = r2_tally.get(head, 0) + 1
        rows_r2.append({
            "key": k, "grade": grade,
            "n_conclusions": len(detail["conclusions"]),
            "conclusions": detail["conclusions"],
            "conclusion_statuses": detail["statuses"],
            "carriers_in_active": detail["in_active"],
            "questions": sorted(set(detail["questions"])),
            "n_cand_pairs_甲": detail["n_cand_pairs"],
            "n_coll_groups_乙": detail["n_coll_groups"],
            "n_coll_other_keys_乙": detail["n_coll_other_keys"],
            "cross_source_乙": detail["cross_source"],
            "n_ledger_recs_乙": detail["n_ct_recs"],
            "triage_classes_乙": detail["triage_classes"],
            "other_mech_faces_乙": detail["other_mech_faces"],
            "n_cf_pairs_乙": detail["n_cf_pairs"],
            "cf_passes_gates_乙": detail["cf_ok"],
            "cf_fail_legs_乙": detail["fail_legs"],
        })

    cov = {}
    for n in N_LEVELS:
        face = {k for f in qh.values() for k in f["rerank"][:n]}
        cov[n] = {
            "total": sum(1 for r in rows_r1 if r["key"] in face),
            "A2": sum(1 for r in rows_r1
                      if r["key"] in face and r["grade_c150"].startswith("A2")),
            "C": sum(1 for r in rows_r1
                     if r["key"] in face and r["grade_c150"].startswith("C")),
            "face_n": len(face),
        }
    all_rerank = {k for f in qh.values() for k in f["rerank"]}
    union_all = {k for f in qh.values() for k in f["face_union"]}
    now_hot = {k for f in qh.values() for name in
               ("face_focus", "face_close", "face_prio", "face_submit", "face_sp")
               for k in f[name]}
    rule_cover_total: dict[str, int] = {}
    for f in qh.values():
        for kk, vv in f["rule_cover"].items():
            rule_cover_total[kk] = rule_cover_total.get(kk, 0) + vv
    return {
        "slug": c149_case["slug"], "run_case_dir": run_case_dir.name,
        "n_questions": len(qh),
        "rerank_sizes": {q: len(f["rerank"]) for q, f in sorted(qh.items())},
        "face_now_sizes": {
            q: {name: len(f[name]) for name in
                ("face_focus", "face_close", "face_prio", "face_submit", "face_sp")}
            for q, f in sorted(qh.items())},
        "n_active_by_q": {q: f["n_active"] for q, f in sorted(qh.items())},
        "n_conclusions_by_q": {q: f["n_conclusions"]
                               for q, f in sorted(qh.items())},
        "n_candidate_pairs_by_q": {q: len(f["pairs"]) for q, f in sorted(qh.items())},
        # 口径甲输入面覆盖：证明 0 候选来自词表案不通用，不是本尺读空
        "rule_cover_totals": rule_cover_total,
        "n_collisions_by_q": {q: f["n_collisions"] for q, f in sorted(qh.items())},
        "n_ledger_recs_by_q": {q: f["n_ledger_recs"] for q, f in sorted(qh.items())},
        "n_seg_pairs_by_q": {q: f["n_seg_pairs"] for q, f in sorted(qh.items())},
        "n_cf_pairs_by_q": {q: len(f["cf_pairs"]) for q, f in sorted(qh.items())},
        "n_cf_ok_by_q": {q: sum(1 for p in f["cf_pairs"] if p["ok"])
                         for q, f in sorted(qh.items())},
        "n_exported_conflicts_by_q": {
            q: len([p for p in (getattr(dossiers[q], "conflicts", []) or [])
                   if isinstance(p, dict)]) for q in sorted(qh)},
        "locator_noloc": counter["noloc"], "side_mapped": counter["mapped"],
        "r1_n": len(rows_r1), "r1_rows": rows_r1,
        "r1_cover_by_n": {str(n): cov[n] for n in N_LEVELS},
        "r1_cover_full_order": {
            "total": sum(1 for r in rows_r1 if r["key"] in all_rerank),
            "A2": sum(1 for r in rows_r1
                      if r["key"] in all_rerank and r["grade_c150"].startswith("A2")),
            "C": sum(1 for r in rows_r1
                     if r["key"] in all_rerank and r["grade_c150"].startswith("C")),
            "face_n": len(all_rerank)},
        "r1_cover_union": {
            "total": sum(1 for r in rows_r1 if r["key"] in union_all),
            "A2": sum(1 for r in rows_r1
                      if r["key"] in union_all and r["grade_c150"].startswith("A2")),
            "face_n": len(union_all)},
        "r1_cover_now_hot": {
            "total": sum(1 for r in rows_r1 if r["key"] in now_hot),
            "face_n": len(now_hot)},
        "r2_n": len(rows_r2), "r2_rows": rows_r2,
        "r2_tally": dict(sorted(r2_tally.items(), key=lambda x: (-x[1], x[0]))),
    }


def _load_json(path: str, want_ticket: str) -> dict:
    p = Path(path)
    if not p.is_file():
        _die(f"找不到 {want_ticket} 读数件：{p}\n（用对应 env 指定；缺＝退码 2）")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("ticket") != want_ticket:
        _die(f"{p} 不是 {want_ticket} 读数件（ticket 键＝{d.get('ticket')!r}）")
    return d


def _merge_cases(cases: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for c in cases:
        for k, v in c[key].items():
            out[k] = out.get(k, 0) + v
    return dict(sorted(out.items(), key=lambda x: (-x[1], x[0])))


def _verdict(cases: list[dict]) -> dict:
    tot = {str(n): {"total": 0, "A2": 0, "C": 0, "face_n": 0} for n in N_LEVELS}
    full = {"total": 0, "A2": 0, "C": 0, "face_n": 0}
    union = {"total": 0, "A2": 0, "face_n": 0}
    rc: dict[str, int] = {}
    n_coll = n_recs = n_seg_pairs = n_cf = n_exported = n_cf_ok = 0
    for c in cases:
        for n, v in c["r1_cover_by_n"].items():
            for k2 in ("total", "A2", "C", "face_n"):
                tot[n][k2] += v[k2]
        for k2 in ("total", "A2", "C", "face_n"):
            full[k2] += c["r1_cover_full_order"][k2]
        for k2 in ("total", "A2", "face_n"):
            union[k2] += c["r1_cover_union"][k2]
        for k2, v in c["rule_cover_totals"].items():
            rc[k2] = rc.get(k2, 0) + v
        n_coll += sum(c["n_collisions_by_q"].values())
        n_recs += sum(c["n_ledger_recs_by_q"].values())
        n_seg_pairs += sum(c["n_seg_pairs_by_q"].values())
        n_cf += sum(c["n_cf_pairs_by_q"].values())
        n_cf_ok += sum(c["n_cf_ok_by_q"].values())
        n_exported += sum(c["n_exported_conflicts_by_q"].values())
    r2_tally = _merge_cases(cases, "r2_tally")
    n_c = _get(r2_tally, "C")
    n_b = _get(r2_tally, "B")
    n_d = _get(r2_tally, "D")
    n_a = _get(r2_tally, "A")
    n_f = _get(r2_tally, "F")
    n_e = _get(r2_tally, "E")

    hot_gate_pass = any(tot[str(n)]["total"] >= GATE_COVER for n in N_LEVELS)
    hot_gate_detail = "、".join(
        f"N={n} 覆盖 {tot[str(n)]['total']}（A2 {tot[str(n)]['A2']}／C {tot[str(n)]['C']}）"
        for n in N_LEVELS)
    a2_majority = any(tot[str(n)]["total"] >= GATE_COVER
                      and tot[str(n)]["A2"] >= tot[str(n)]["C"] for n in N_LEVELS)
    ticket_hot = "YES" if (hot_gate_pass and a2_majority) else "NO"
    ticket_pair = "YES" if n_c >= GATE_PAIRED else "NO"
    if ticket_hot == "YES" and ticket_pair == "YES":
        overall, why = "YES", "两把反事实尺各自过线（重点面覆盖≥24 且增量来自 A2；可配却未配≥4/7）"
    elif ticket_hot == "YES":
        overall, why = "PARTIAL", (f"只过重点面线（{hot_gate_detail}）；"
                                  f"尺②可配却未配只有 {n_c}/7＜{GATE_PAIRED}")
    elif ticket_pair == "YES":
        overall, why = "PARTIAL", (f"只过成对线（可配却未配 {n_c}/7）；"
                                  f"重点面覆盖未过线＝{hot_gate_detail}＜{GATE_COVER}")
    else:
        overall, why = "NO", (f"两条预登记线都没过＝重点面覆盖 {hot_gate_detail}"
                             f"（线 {GATE_COVER}）；尺②有对侧腿且可配 {n_c}/7"
                             f"（线 {GATE_PAIRED}；被闸挡 {n_b}／段级有痕迹抬不到结论级 {n_d}"
                             f"／输入面无机械可检对侧 {n_a}／不在活动集 {n_f}／不可归因 {n_e}）")
    return {
        "overall": overall, "why": why,
        "r1_cover_by_n": tot, "r1_cover_full_order": full,
        "r1_cover_union": union,
        "r1_gate_cover": GATE_COVER, "r1_gate_detail": hot_gate_detail,
        "r1_a2_majority_at_gate": a2_majority,
        "ticket_bandwidth": ticket_hot, "ticket_pairing": ticket_pair,
        "r2_tally": r2_tally, "r2_c": n_c, "r2_gate": GATE_PAIRED,
        "rule_cover_totals": rc,
        "n_collisions": n_coll, "n_ledger_recs": n_recs,
        "rehydrate_agrees": n_coll == n_recs,
        "n_seg_pairs": n_seg_pairs, "n_cf_pairs": n_cf, "n_cf_ok": n_cf_ok,
        "n_cf_fail": n_cf - n_cf_ok,
        "n_exported_conflicts": n_exported,
        "r2_c_grade_names": [r["grade"] for cs in cases for r in cs["r2_rows"]
                             if r["grade"].startswith("C")],
    }


def _get(t: dict, prefix: str) -> int:
    for k, v in t.items():
        if k.startswith(prefix):
            return v
    return 0


def _close_range(cases: list[dict]) -> str:
    """逐题细读面尺寸的现抄区间（不给产物里的数字编故事）。"""
    vals = [sz["face_close"] for c in cases for sz in c["face_now_sizes"].values()]
    if not vals:
        return "无读数"
    lo, hi = min(vals), max(vals)
    return f"{lo} 段" if lo == hi else f"{lo}–{hi} 段"


def _render_md(out: dict) -> str:
    v = out["verdict"]
    L = ["# C-152 冲突漏检反事实尺（两张零模型尺，只量不改）", ""]
    L += [f"结论：**{v['overall']}**——{v['why']}", ""]
    L += [f"- 重点面／带宽实现票＝**{v['ticket_bandwidth']}**"
          f"（预登记线：cov(N=15 或 30)≥{v['r1_gate_cover']} 且增量主要来自 A2）",
          f"- 候选生成／成对规则实现票＝**{v['ticket_pairing']}**"
          f"（预登记线：「有对侧腿且现行规则可配却未配」＝档 C ≥{v['r2_gate']}／7，"
          f"按口径乙判；本次档 C＝{v['r2_c']}）", ""]
    L += [f"跑产物根：{out['run_root']}｜键表：C-149＋C-150 未跟踪件（{out['c149_json']}、"
          f"{out['c150_json']}）｜反事实序＝kg_test_tree.rerank_order（二筛显式全序）", ""]
    L += ["## 尺① 重点面反事实（取证环是不是带宽饥饿）", ""]
    L += [f"- 48 键在各 N 档前缀面里的覆盖（合计；面尺寸＝案级相加，"
          f"案内不相交、跨案同 id 不合并＝与量尺同一口径）："
          + "、".join(f"N={n}＝{v['r1_cover_by_n'][str(n)]['total']}"
                      f"（A2 {v['r1_cover_by_n'][str(n)]['A2']}／"
                      f"C {v['r1_cover_by_n'][str(n)]['C']}，面 {v['r1_cover_by_n'][str(n)]['face_n']} 段）"
                      for n in N_LEVELS)]
    L += [f"- 用尽全序（N＝∞，案级二筛序并集 {v['r1_cover_full_order']['face_n']} 段）"
          f"也只覆盖 {v['r1_cover_full_order']['total']}/48"
          f"（A2 {v['r1_cover_full_order']['A2']}／C {v['r1_cover_full_order']['C']}）"
          f"＝余 {48 - v['r1_cover_full_order']['total']} 键不在任何可用的序里，"
          f"加带宽买不到它们（序里没有的键，扩到多大都扩不出）"]
    L += [f"- 并集面上界（material_pack_union，无序、不可反事实）：案级 "
          f"{v['r1_cover_union']['face_n']} 段里含这 48 键中的 "
          f"{v['r1_cover_union']['total']} 个（A2 {v['r1_cover_union']['A2']}）"
          f"＝「进过材料」是真，「有序可选」是假——带宽票要的不是并集而是序"]
    n_a1 = sum(1 for r in out["r1_all_rows"] if r["grade_c150"].startswith("A1"))
    L += [f"- 对照现面（不做反事实）：案级重点面并集 {out['now_hot_face_total']} 段，"
          f"覆盖 {out['now_hot_cover']}／48；C-150 的 A1 档（进提示未引用）＝"
          f"{n_a1} 键（两把尺同一事实才继续用）"]
    L += ["", "### 尺① 按案（现抄面尺寸，证明两侧都取到数）", ""]
    for c in out["cases"]:
        L += [f"- {c['slug']}：二筛序 {'/'.join(str(x) for x in c['rerank_sizes'].values())} 段；"
              + "；".join(
                  f"N={n} 覆盖 {c['r1_cover_by_n'][str(n)]['total']}/{c['r1_n']}"
                  for n in N_LEVELS)
              + f"；用尽全序 {c['r1_cover_full_order']['total']}/{c['r1_n']}"
              f"；并集面 {c['r1_cover_union']['total']}/{c['r1_n']}"
              f"（并集 {c['r1_cover_union']['face_n']} 段）"]
    L += ["", "### 尺① 逐键（键→二筛序最早位置；不在序里的记「序外」）", ""]
    in_order = [r for r in out["r1_all_rows"] if r["in_rerank"]]
    L += [f"- 在序里（{len(in_order)}）：" + "、".join(
        f"{r['slug']}:{r['key']}＝第{r['rerank_best_pos']}位（{r['grade_c150'][:2]}）"
        for r in in_order) or "无"]
    L += [f"- 序外（{len(out['r1_all_rows']) - len(in_order)}）："
          + "、".join(f"{r['slug']}:{r['key']}（{r['grade_c150'][:2]}）"
                      for r in out["r1_all_rows"] if not r["in_rerank"])]
    L += ["", "## 尺② 结论级配对反事实（E4 那 7 键，两把口径分开量）", ""]
    rc = v["rule_cover_totals"]
    L += [f"- 口径甲＝现行成对规则原样复放：build_candidate_pairs＋"
          f"subject_mismatch_reason＋validate_conflict，零 LLM；活动集＝majority 且有证据。"]
    L += [f"- 口径甲输入面覆盖（六案终局结论面现抄，逐题相加）：结论 {rc['n_concl']} 条·次、"
          f"extract_subject 命中 **{rc['n_subject']}** 条、extract_topics 命中 "
          f"{rc['n_topics']} 条、polarity_of 命中 {rc['n_polarity']} 条；"
          f"逐题候选对合计 {sum(sum(c['n_candidate_pairs_by_q'].values()) for c in out['cases'])} 条"
          + (f"＝主体命中 0 ⇒ 同主体×议题那条候选路按构造出不来（词表是「客户甲/A」"
             f"那套企业口径，本批语料不适用）；生产在这些案实际走"
             f"「无程序候选→模型自由检出＋事后主体闸」那条兜底路，本尺禁用 LLM，"
             f"所以口径甲只读到 0，不许把 0 说成「输入面干净」。"
             if rc["n_subject"] == 0 else
             "＝主体命中非 0，候选路部分可用，逐题数见下节。")]
    L += [f"- 同期生产导出冲突对 {v['n_exported_conflicts']} 对（逐题现抄）＝证明"
          f"「配得上」这件事在现行系统里靠的是模型自由检出，不是机械候选。"]
    L += [f"- 口径乙＝案无关机械对侧尺（下列计数一律逐题相加：对撞与台账留痕都是案级口径，"
          f"每题各重跑一遍，故一案的三个题各记一次）：当场 find_collisions 得对撞组 "
          f"{v['n_collisions']} 组·次，产物 conflict_trace 里 source=fact_ledger 记录 "
          f"{v['n_ledger_recs']} 条·次＝{'两侧都取到数且相等（复现一致＝重放输入面可信）' if v['rehydrate_agrees'] and v['n_collisions'] else '两侧不一致或有一侧为 0＝点名，不据此判绿'}；"
          f"跨源异值「段×段」对侧配对 {v['n_seg_pairs']} 对·次"
          f"（对侧料在卷面上{'不缺位' if v['n_seg_pairs'] else '本次没量到'}）；"
          f"把这些对侧抬到结论级（两端都挂同题活动结论）＝{v['n_cf_pairs']} 对，"
          f"再过现行两道闸＝全过 {v['r2_c']} 键（档 C）。"]
    L += [f"- 档合计：{json.dumps(v['r2_tally'], ensure_ascii=False)}"
          f"（C 可配却未配／B 有对侧被闸挡／D 段级有痕迹抬不到结论级／"
          f"A 输入面无机械可检对侧／F 承载结论不在活动集／E 不可归因）"]
    L += ["", "### 尺② 逐键（两把口径各自的读数）", ""]
    for r in out["r2_all_rows"]:
        L += [f"- {r['slug']}:{r['key']}＝{r['grade']}；"
              f"承载结论 {r['n_conclusions']} 条（态 {'／'.join(r['conclusion_statuses']) or '—'}、"
              f"在活动集＝{r['carriers_in_active']}）、题 {'/'.join(r['questions']) or '—'}；"
              f"甲候选对 {r['n_cand_pairs_甲']}｜乙对撞组 {r['n_coll_groups_乙']}"
              f"（跨源＝{r['cross_source_乙']}、对侧键 {r['n_coll_other_keys_乙']}）、"
              f"台账留痕 {r['n_ledger_recs_乙']} 条（triage "
              f"{'／'.join(r['triage_classes_乙']) or '—'}）、其他机械面 "
              f"{'／'.join(r['other_mech_faces_乙']) or '无'}、"
              f"结论级反事实对 {r['n_cf_pairs_乙']} 条（过闸＝{r['cf_passes_gates_乙']}、"
              f"缺腿 {'／'.join(r['cf_fail_legs_乙']) or '—'}）"]
    L += ["", "### 尺② 输入面尺寸（现抄，逐题）", ""]
    for c in out["cases"]:
        L += [f"- {c['slug']}：结论 {'/'.join(str(x) for x in c['n_conclusions_by_q'].values())}"
              f"／活动集 {'/'.join(str(x) for x in c['n_active_by_q'].values())}"
              f"／甲候选对 {'/'.join(str(x) for x in c['n_candidate_pairs_by_q'].values())}"
              f"／对撞组 {'/'.join(str(x) for x in c['n_collisions_by_q'].values())}"
              f"／台账留痕 {'/'.join(str(x) for x in c['n_ledger_recs_by_q'].values())}"
              f"／段级对侧配 {'/'.join(str(x) for x in c['n_seg_pairs_by_q'].values())}"
              f"／结论级反事实 {'/'.join(str(x) for x in c['n_cf_pairs_by_q'].values())}"
              f"／导出冲突对 {'/'.join(str(x) for x in c['n_exported_conflicts_by_q'].values())}"]
    L += ["", "## 不变式与自检", ""]
    L += [f"- 尺①行数＝48＝C-149/C-150 键数（逐案核）＝{out['inv_r1']}；"
          f"尺②行数＝7＝C-150 E4 键数＝{out['inv_r2']}"]
    L += [f"- 尺①档互斥（每键只一档）＝{out['inv_r1_unique']}；"
          f"尺②档互斥（每键取最强一档，Σ＝7）＝{out['inv_r2_unique']}"]
    L += [f"- 复现一致：当场 find_collisions 组数＝产物台账留痕条数"
          f"（{v['n_collisions']} vs {v['n_ledger_recs']}，均逐题相加）＝{v['rehydrate_agrees']}"]
    L += [f"- 两侧都取到数（不是空比空）：甲面读数＝结论 {rc['n_concl']} 条·次／"
          f"活动集合计 {sum(sum(c['n_active_by_q'].values()) for c in out['cases'])} 条·次；"
          f"乙面读数＝对撞组 {v['n_collisions']} 组·次／段级对侧配 {v['n_seg_pairs']} 对·次／"
          f"结论侧映射 {out['side_mapped_total']} 条·次"]
    L += [f"- 定位失败（反事实序与面里的 id 在现产物定位不到段键）＝"
          f"{out['locator_noloc_total']} 次"]
    L += ["", "## 留痕缺口（记缺口，不猜、不重建）", ""]
    L += [f"- {out['gap_1']}"]
    L += [f"- {out['gap_2']}"]
    L += [f"- {out['gap_3']}"]
    L += ["", "## 下一缺口（只写读数指向的那一处，不开票、不许愿）", ""]
    L += [f"- 尺①：二筛全序只装得下 {v['r1_cover_full_order']['face_n']} 段·次，"
          f"其中含 48 键 {v['r1_cover_full_order']['total']} 个；并集面 "
          f"{v['r1_cover_union']['face_n']} 段·次含 {v['r1_cover_union']['total']} 个"
          f"＝缺口在「宽料没有可用的序」，不在「窗口太小」。"]
    L += [f"- 尺②：段级对侧配 {v['n_seg_pairs']} 对（对撞组里跨源异值），"
          f"抬到结论级只剩 {v['n_cf_pairs']} 对（两端都得是同题活动结论），"
          f"这 {v['n_cf_pairs']} 对里过现行两道闸 {v['n_cf_ok']} 对、被闸挡 "
          f"{v['n_cf_fail']} 对＝档 C 键数 {v['r2_c']}/7"
          f"⇒ 缺口在「对侧段没进同一题的活动结论面」，与尺① 那一处同源；"
          f"闸在这一路拦掉 {v['n_cf_fail']} 对——这只说明本批语料上闸不是挡箭牌，"
          f"不外推到其他案。"]
    L += [f"- 现行成对规则的口径要能承接任何冲突票，先得有案无关的主体×指标口径"
          f"（本批 18 题抽到主体的结论 {rc['n_subject']}/{rc['n_concl']} 条·次）；"
          f"但这句话只说明「现在配不出来」，不说明「配出来能拿几分」。"]
    L += ["", "## 读数之外", ""]
    L += ["- 本尺只答「只改这一环买多少」，不外推分数，没说能拿 13；"
          "也没解禁旧数值对撞主路、没改仲裁公式、没开 cite_accept。",
          "- 零 LLM、零网络、不写 app/；本文件数字全部当场现算，无官方语料正文、"
          "无结论原文（只 id／计数／档位枚举；对撞 metric 名只记字符数）。"]
    return "\n".join(L) + "\n"


def main() -> None:
    if not C152_RUN:
        _die("必须给 C152_RUN＝六案跑产物根（不给默认旧路径，防量到过期跑次）")
    run_root = Path(C152_RUN)
    if not run_root.is_dir():
        _die(f"找不到跑产物根：{run_root}")
    c149 = _load_json(C152_C149_JSON, "C-149")
    c150 = _load_json(C152_C150_JSON, "C-150")
    if c149.get("run_root") != c150.get("run_root") and c150.get("run_root"):
        _die(f"C-149 与 C-150 的跑次根不一致（{c149.get('run_root')} vs "
             f"{c150.get('run_root')}）＝两份键表不是同一批，停手")
    if c150.get("run_root") and c150["run_root"] != str(run_root):
        _die(f"C152_RUN 与键表跑次根不一致（{run_root} vs {c150['run_root']}）")

    dirs: dict[str, Path] = {}
    for name in sorted(os.listdir(run_root)):
        d = run_root / name
        if d.is_dir() and not name.startswith(".") \
                and list((d / "questions").glob("*/report.json")):
            dirs[_slug(name)] = d
    missing = [c["slug"] for c in c149["cases"] if c["slug"] not in dirs]
    if missing:
        _die(f"跑产物里缺案：{'、'.join(missing)}")
    c150_by_slug = {c["slug"]: c for c in c150["cases"]}

    cases = []
    for c in c149["cases"]:
        if c["slug"] not in c150_by_slug:
            _die(f"C-150 读数缺案 {c['slug']}＝两份键表不齐")
        cases.append(_probe_case(c, c150_by_slug[c["slug"]], dirs[c["slug"]]))

    r1_rows_all, r2_rows_all = [], []
    for c in cases:
        r1_rows_all += [{"slug": c["slug"], **r} for r in c["r1_rows"]]
        r2_rows_all += [{"slug": c["slug"], **r} for r in c["r2_rows"]]
    n_r1, n_r2 = len(r1_rows_all), len(r2_rows_all)
    if n_r1 != EXPECT_R1 or n_r2 != EXPECT_R2:
        _die(f"尺分母不等于写死值（尺①{n_r1}≠{EXPECT_R1} 或 尺②{n_r2}≠{EXPECT_R2}）"
             f"＝键表变了，停手核对")
    if len({r["key"] + r["slug"] for r in r1_rows_all}) != n_r1:
        _die("尺①键有重复＝一案内同键出现两次")

    verdict = _verdict(cases)
    out = {
        "ticket": "C-152",
        "run_root": str(run_root),
        "c149_json": str(Path(C152_C149_JSON)),
        "c150_json": str(Path(C152_C150_JSON)),
        "counterfactual_order": "accounting.kg_test_tree.rerank_order",
        "n_levels": list(N_LEVELS),
        "cases": cases,
        "r1_all_rows": r1_rows_all,
        "r2_all_rows": r2_rows_all,
        "verdict": verdict,
        "inv_r1": n_r1 == EXPECT_R1,
        "inv_r2": n_r2 == EXPECT_R2,
        "inv_r1_unique": len({(r["slug"], r["key"]) for r in r1_rows_all}) == n_r1,
        "inv_r2_unique": sum(verdict["r2_tally"].values()) == n_r2,
        "locator_noloc_total": sum(c["locator_noloc"] for c in cases),
        "side_mapped_total": sum(c["side_mapped"] for c in cases),
        "gap_1": (f"细读面无独立候选序留痕（本批逐题 close_read 面 "
                  f"{_close_range(cases)}）⇒ 细读臂「扩到 N」只能用 rerank 前 N 代理；"
                  f"material_pack_union 无序⇒不可反事实；首箱 id 未入库（C-150 已记）"),
        "gap_2": ("尺②输入面＝产物里的终局结论集（被归并吸收的结论不在场），"
                  "与 detect 当时的活动集不完全同一；逐题活动集数／候选对数／对撞组数"
                  "已现抄，复现一致腿＝当场 find_collisions 组数＝产物台账留痕条数"),
        "gap_3": (f"口径甲（现行成对规则）在这批产物产 0 候选：逐题候选对合计 "
                  f"{sum(sum(c['n_candidate_pairs_by_q'].values()) for c in cases)} 条，"
                  f"同面上 extract_subject 命中 {verdict['rule_cover_totals']['n_subject']}"
                  f"/{verdict['rule_cover_totals']['n_concl']} 条·次（议题 "
                  f"{verdict['rule_cover_totals']['n_topics']}、极性 "
                  f"{verdict['rule_cover_totals']['n_polarity']}）"
                  f"⇒ 本尺不能把「甲＝0」读成「输入面无对侧」，只能读成"
                  f"「规则的词表在这批语料上抽不到主体」；对侧与否以口径乙读数为准"),
    }
    out["now_hot_face_total"] = sum(
        c["r1_cover_now_hot"]["face_n"] for c in cases)
    out["now_hot_cover"] = sum(c["r1_cover_now_hot"]["total"] for c in cases)
    art = REPO / "artifacts"
    art.mkdir(exist_ok=True)
    (art / "C152_counterfactual.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (art / "C152_counterfactual.md").write_text(_render_md(out), encoding="utf-8")
    print(f"总判定 {verdict['overall']}｜重点面票 {verdict['ticket_bandwidth']}"
          f"｜成对票 {verdict['ticket_pairing']}｜{verdict['why']}")
    print(f"尺①覆盖：{json.dumps(verdict['r1_cover_by_n'], ensure_ascii=False)}"
          f"｜用尽全序 {json.dumps(verdict['r1_cover_full_order'], ensure_ascii=False)}"
          f"｜并集面 {json.dumps(verdict['r1_cover_union'], ensure_ascii=False)}")
    print(f"尺②档合计：{json.dumps(verdict['r2_tally'], ensure_ascii=False)}"
          f"｜甲覆盖 {json.dumps(verdict['rule_cover_totals'], ensure_ascii=False)}"
          f"｜乙对撞组 {verdict['n_collisions']}＝台账留痕 {verdict['n_ledger_recs']}"
          f"（复现一致 {verdict['rehydrate_agrees']}）"
          f"｜段级对侧配 {verdict['n_seg_pairs']}｜结论级反事实 {verdict['n_cf_pairs']}"
          f"｜导出冲突对 {verdict['n_exported_conflicts']}")
    print(f"产物：{art / 'C152_counterfactual.md'}")


if __name__ == "__main__":
    main()
