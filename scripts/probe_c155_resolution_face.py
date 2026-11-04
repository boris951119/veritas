#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-155：主观 3.3 消解面判尺（零 LLM、零网络、零现金；只记 id／计数／比率）。

对着官方 3.3 三个锚点量同一张面：
  3.3.1 三要素（冲突清单／消解结果／消解理由）逐条在场
  3.3.2 消解类型落官方五类（多数投票／来源优先级／时效性／语义可信度／其他）＋「其他」占比
  3.3.3 少数意见独立记录＋重启条件非空

两条腿：
- ``current``（默认）＝照产物里已落的 ``resolution_type`` 读数＝改前基线；
- ``rule``         ＝在 resolution 副本上调**仓内实现**
  按预登记的优先序回填类型，量「能诚实改掉多少条其他」——只算映射，不改胜负、
  不改公式、不动提示词；每步落点与判据逐条留痕。

跑法：
    .venv/bin/python -X utf8 scripts/probe_c155_resolution_face.py compose \\
        --root /tmp/s4runs/time-20261104-135401 --out /tmp/c155/compose.json
    .venv/bin/python -X utf8 scripts/probe_c155_resolution_face.py after \\
        --root <改后产物根> --out /tmp/c155/after.json
    .venv/bin/python -X utf8 scripts/probe_c155_resolution_face.py assemble
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OFFICIAL_FIVE = ("多数投票", "来源优先级", "时效性", "语义可信度", "其他")
ART_JSON = REPO / "artifacts" / "C155_resolution_face.json"
ART_MD = REPO / "artifacts" / "C155_resolution_face.md"
BASE_MD = REPO / "artifacts" / "C155_baseline.md"
# 跑前写死的门槛（相对旧批 HANDOFF 记录「其他 15/17＝0.882」）
OTHER_SHARE_GATE = 0.40        # 「其他」占比目标线
HALF_OF_OLD = 0.882 / 2        # 相对旧批降一半＝0.441
OLD_BATCH = {"n_records": 17, "other": 15, "share": 0.882,
             "source": "docs/HANDOFF.md:777（同探针旧批读数）"}
# 基 tip（3227200）真 export 的 records 数组指纹——在 /private/tmp/w155base
# （detach 于 3227200）上对同一 18 题跑同一 export_official 现抄，用于关旗同形：
# 关旗臂 records 必须与它逐字节同（`detail` 披露句变化不在 records 数组里）。
BASE_TIP_RECORDS_SHA8 = "9a3b90a5"

# 判尺腿＝直接调仓内实现 app.core.resolution_time_type.apply_tie_time_rule，
# 不在探针里另写一份平行判据（尺子与代码同源，才不会出现「尺子过、实现不过」）。


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dossier(rep: dict):
    from app.core.evidence import Dossier
    return Dossier.from_dict(rep)


def _side_source_ids(d, con_id: str) -> list[str]:
    out: list[str] = []
    for e in d.evidences_of(con_id) or []:
        for sid in (e.segment_ids or []):
            seg = d.segment(str(sid))
            src = getattr(seg, "source_id", None)
            if src:
                out.append(str(src))
    return out


def _side_dates(d, con_id: str) -> list[str]:
    """两侧信源时点＝走仓内唯一实现 temporal_check.source_date（键位兼容
    published_at／publish_time／year，月粒度不回退成年）——自己挑键会漏掉
    产物里实际用的 publish_time，把「时效性」这条判尺腿判成零。
    """
    from app.core.temporal_check import source_date
    keys: list[str] = []
    by_id = {str(getattr(s, "id", "")): s for s in d.sources or []}
    for src_id in _side_source_ids(d, con_id):
        src = by_id.get(src_id)
        if src is None:
            continue
        day = str(source_date(src) or "").strip()
        if day:
            keys.append(day)
    return keys


def _side_cred(d, con_id: str) -> float | None:
    vals = []
    by_id = {str(getattr(s, "id", "")): s for s in d.sources or []}
    for src_id in _side_source_ids(d, con_id):
        src = by_id.get(src_id)
        if src is None:
            continue
        try:
            vals.append(float(getattr(src, "credibility", 0.0)))
        except (TypeError, ValueError):
            continue
    return round(sum(vals) / len(vals), 4) if vals else None


def _side_n_sources(d, con_id: str) -> int | None:
    ids = _side_source_ids(d, con_id)
    return len(set(ids)) if ids else None


def _rule_leg(pair: dict, res: dict, d) -> dict:
    """在 resolution dict 副本上跑**仓内实现**，读它落成的类型。

    不另写一份平行判据＝尺子与代码同源；跑不通就报错、不当「没改」。
    """
    import copy

    from app.core.resolution_time_type import apply_tie_time_rule

    res_c = copy.deepcopy(res)
    try:
        moved = bool(apply_tie_time_rule(res_c, pair, d))
    except Exception as exc:  # noqa: BLE001
        return {"rule_error": type(exc).__name__}
    return {
        "type_after_rule": str(res_c.get("resolution_type") or ""),
        "rule_applied": moved,
        "rule_sides_dates": (res_c.get("basis") or {}).get("sides_dates"),
    }


def collect(root: str) -> list[dict]:
    """逐题逐对拆出消解记录的结构化事实（不重算判定、不读金标）。"""
    rows: list[dict] = []
    paths = sorted(glob.glob(os.path.join(root, "*", "questions", "*",
                                          "report.json")))
    if not paths:
        raise SystemExit(f"{root} 下没有 */questions/*/report.json＝跑不到，"
                         f"不许静默印 0")
    for p in paths:
        rep = _load(Path(p))
        d = _dossier(rep)
        case = Path(p).parts[-4]
        qid = Path(p).parts[-2]
        for pair in rep.get("conflicts") or []:
            if not isinstance(pair, dict):
                continue
            res = pair.get("resolution")
            if not isinstance(res, dict) or not res:
                rows.append({"case": case, "qid": qid,
                             "conflict_id": str(pair.get("id") or ""),
                             "no_resolution": True})
                continue
            basis = res.get("basis") if isinstance(res.get("basis"), dict) else {}
            a_id = str(pair.get("a_id") or "")
            b_id = str(pair.get("b_id") or "")
            winner = str(res.get("winner_id") or "")
            strength = basis.get("strength") if isinstance(basis.get("strength"),
                                                           dict) else {}
            srcs = basis.get("independent_sources") if isinstance(
                basis.get("independent_sources"), dict) else {}
            try:
                margin = float(basis.get("margin"))
            except (TypeError, ValueError):
                margin = None
            try:
                gap = float(basis.get("strength_gap"))
            except (TypeError, ValueError):
                gap = None
            da, db = _side_dates(d, a_id), _side_dates(d, b_id)
            ca, cb = _side_cred(d, a_id), _side_cred(d, b_id)
            na = srcs.get(a_id, srcs.get("a"))
            nb = srcs.get(b_id, srcs.get("b"))
            if na is None:
                na = _side_n_sources(d, a_id)
            if nb is None:
                nb = _side_n_sources(d, b_id)
            sa_v = strength.get(a_id) if isinstance(strength, dict) else None
            sb_v = strength.get(b_id) if isinstance(strength, dict) else None
            rows.append({
                "case": case, "qid": qid,
                "conflict_id": str(pair.get("id") or ""),
                "sides": (a_id, b_id),
                "method": str(res.get("method") or ""),
                "decision_path": str(basis.get("decision_path") or
                                     res.get("decision_path") or ""),
                "route": str(basis.get("route") or ""),
                "triage_class": str(basis.get("triage_class") or ""),
                "resolution_type": str(res.get("resolution_type") or ""),
                "winner_id": winner,
                "strength_pair": (_f(sa_v), _f(sb_v)),
                "has_listing": bool(pair.get("a_id") and pair.get("b_id")),
                "has_result": bool(winner),
                "has_rationale": bool(str(res.get("rationale") or "").strip()),
                "has_restart": bool(str(res.get("restart_condition") or
                                        res.get("重启条件") or "").strip()),
                "restart_missing_key": ("restart_condition" not in res and
                                       "重启条件" not in res),
                "margin": margin, "strength_gap": gap,
                "n_sources": (na, nb),
                "cred": (ca, cb),
                "dates": (sorted(set(da)), sorted(set(db))),
                "both_kept": winner == "tie" or not winner,
                #  shipped 规则腿＝直接调仓内实现（不另写一份平行判据，避免
                # 「尺子和代码各说各话」）：在 resolution dict 的副本上跑
                # app.core.resolution_time_type.apply_tie_time_rule。
                **_rule_leg(pair, res, d),
                "winner_later": bool(da and db and
                                     max(da) > max(db)) if winner == a_id else (
                                     bool(da and db and max(db) > max(da))
                                     if winner == b_id else False),
            })
    return rows


def _f(v: Any) -> float | None:
    try:
        return None if v is None else round(float(v), 4)
    except (TypeError, ValueError):
        return None


def summarize(rows: list[dict], mode: str) -> dict:
    ok = [r for r in rows if not r.get("no_resolution")]
    n = len(ok)
    cur = Counter(r.get("resolution_type") or "(空)" for r in ok)
    out: dict[str, Any] = {"n_pairs_total": len(rows),
                           "n_no_resolution": sum(1 for r in rows
                                                  if r.get("no_resolution")),
                           "n": n,
                           "type_current": {k: cur.get(k, 0)
                                            for k in OFFICIAL_FIVE},
                           "out_of_five_current": {k: v for k, v in cur.items()
                                                   if k not in OFFICIAL_FIVE},
                           "other_share_current": (round(cur.get("其他", 0) / n, 4)
                                                   if n else None),
                           "elements_current": {
                               "清单": sum(1 for r in ok if r["has_listing"]),
                               "结果": sum(1 for r in ok if r["has_result"]),
                               "理由": sum(1 for r in ok if r["has_rationale"]),
                               "三要素齐": sum(1 for r in ok if r["has_listing"]
                                              and r["has_result"]
                                              and r["has_rationale"]),
                               "重启条件非空": sum(1 for r in ok if r["has_restart"]),
                               "重启条件缺键": sum(1 for r in ok
                                                 if r["restart_missing_key"])},
                           "other_composition": {}}
    others = [r for r in ok if (r.get("resolution_type") or "") == "其他"]
    comp = Counter((r.get("method") or "-", r.get("decision_path") or "-",
                    r.get("route") or "-", r.get("triage_class") or "-")
                   for r in others)
    out["other_composition"] = {repr(k): v for k, v in comp.most_common()}
    if mode == "rule":
        lab = Counter()
        moves = Counter()
        errs = Counter()
        for r in ok:
            if r.get("rule_error"):
                errs[r["rule_error"]] += 1
            t = r.get("type_after_rule") or r.get("resolution_type") or ""
            lab[t] += 1
            if t != (r.get("resolution_type") or ""):
                moves[f"{r.get('resolution_type') or '(空)'}→{t}"] += 1
        out["type_after_rule"] = {k: lab.get(k, 0) for k in OFFICIAL_FIVE}
        out["other_share_after_rule"] = (round(lab.get("其他", 0) / n, 4)
                                         if n else None)
        out["rule_moves"] = dict(moves.most_common())
        out["rule_errors"] = dict(errs)
        out["n_rule_applied"] = sum(1 for r in ok if r.get("rule_applied"))
        out["invariant_applied_plus_untouched_eq_n"] = (
            out["n_rule_applied"] + sum(1 for r in ok if not r.get("rule_applied"))
            == n)
        # 剩下仍在「其他」的：为什么诚实判不到类型（逐条 tell 落点现抄）
        rest = [r for r in ok
                if (r.get("type_after_rule") or r.get("resolution_type") or "")
                == "其他"]
        def _both_dates(r):
            da, db = (r.get("dates") or ((), ()))[:2]
            return bool(da) and bool(db)
        out["remaining_other"] = {
            "n": len(rest),
            "一侧或两侧信源无时点": sum(1 for r in rest if not _both_dates(r)),
            "两侧有时刻但集合相同": sum(1 for r in rest
                                    if _both_dates(r)
                                    and set(r["dates"][0]) == set(r["dates"][1])),
            "两侧时点可解且不同（不该出现＝规则漏）": sum(
                1 for r in rest if _both_dates(r)
                and set(r["dates"][0]) != set(r["dates"][1])),
            "其中双方均保留": sum(1 for r in rest if r.get("both_kept")),
            "其中有明确胜方": sum(1 for r in rest if not r.get("both_kept")),
        }
    return out


def gate_block(summ: dict) -> dict:
    share = summ.get("other_share_after_rule")
    if share is None:
        share = summ.get("other_share_current")
    return {"gate_other_share_target": OTHER_SHARE_GATE,
            "gate_half_of_old": round(HALF_OF_OLD, 4),
            "measured_share": share,
            "meets_target": (share is not None and share <= OTHER_SHARE_GATE),
            "meets_half_of_old": (share is not None and share <= HALF_OF_OLD),
            "old_batch": OLD_BATCH}


def source_date_coverage(root: str) -> dict:
    """缺口披露用：这批产物的信源里有多少带可解时点——时效性覆盖率的上界就在这里。"""
    from app.core.evidence import Source
    from app.core.temporal_check import source_date

    n_src = n_day = 0
    for p in glob.glob(os.path.join(root, "*", "questions", "*", "report.json")):
        rep = _load(Path(p))
        for raw_src in rep.get("sources") or []:
            n_src += 1
            try:
                s = Source.from_dict(raw_src)
            except Exception:  # noqa: BLE001 — 结构异常按「无时点」计，不谎报有
                continue
            if str(source_date(s) or "").strip():
                n_day += 1
    return {"n_sources": n_src, "n_with_resolvable_date": n_day,
            "coverage": (round(n_day / n_src, 4) if n_src else None)}


def stage_after(root: str, out: str) -> dict:
    """提交面（真 export）两臂对照：同 18 题、同一实现、只差旗位。

    关旗臂 records 与开旗臂逐条比：差异只允许落在 resolution_type／basis；
    其余键（冲突清单／结果／理由／重启条件／method／conflict_id）必须逐字同。
    """
    import shutil
    import tempfile

    from app.core.resolution_time_type import apply_tie_time_rule, set_enabled
    from app.export.official import export_official

    paths = sorted(glob.glob(os.path.join(root, "*", "questions", "*",
                                          "report.json")))
    if not paths:
        raise SystemExit(f"跑不到：{root} 下没有 */questions/*/report.json")

    def export_arm(flag_on: bool, tag: str) -> list[dict]:
        tmp = Path(tempfile.mkdtemp(prefix=f"c155_{tag}_"))
        runs: list[tuple[dict, Any]] = []
        for p in paths:
            rep = _load(Path(p))
            d = _dossier(rep)
            if flag_on:
                for pair in d.conflicts or []:
                    if isinstance(pair, dict):
                        res = pair.get("resolution")
                        if isinstance(res, dict):
                            apply_tie_time_rule(res, pair, d)
            qid = Path(p).parts[-2]
            question = {"question_id": qid, "question": str(rep.get("question")
                                                           or rep.get("title")
                                                           or "")}
            runs.append((question, d))
        export_official(runs, tmp)
        f = tmp / "conflict_resolution.json"
        recs = _load(f).get("records") or [] if f.is_file() else []
        shutil.rmtree(tmp, ignore_errors=True)
        if not recs:
            raise SystemExit(f"跑不到：{tag} 臂导出里没有 records")
        return recs

    arms = {"off": export_arm(False, "off"), "on": export_arm(True, "on")}
    dist = {k: dict(Counter(str(r.get("resolution_type") or "(空)")
                           for r in v)) for k, v in arms.items()}
    import hashlib
    recs_sha8 = {
        k: hashlib.sha256(json.dumps(v, ensure_ascii=False, sort_keys=True)
                          .encode("utf-8")).hexdigest()[:8]
        for k, v in arms.items()}
    other = {k: (round(sum(1 for r in v if r.get("resolution_type") == "其他")
                      / len(v), 4) if v else None) for k, v in arms.items()}
    n_by = {k: len(v) for k, v in arms.items()}
    # 逐条差异分三类：①只动 type／basis＝目标改动；②两臂都已被尺寸闸截断、
    # 只是裁得更深（omissions 集合相同）＝已披露的代价；③新增 omission 或
    # 掉了别的字段＝真回归（必须为 0）。
    clean = deeper = regressed = 0
    regressed_detail: list[dict] = []
    for r_off, r_on in zip(arms["off"], arms["on"]):
        if r_off == r_on:
            continue
        om_off = set(r_off.get("omissions") or [])
        om_on = set(r_on.get("omissions") or [])
        changed_other = [k for k in (set(r_off) | set(r_on))
                         if k not in ("resolution_type", "basis")
                         and r_off.get(k) != r_on.get(k)]
        if om_on - om_off or set(r_off) != set(r_on):
            regressed += 1
            if len(regressed_detail) < 5:
                regressed_detail.append({
                    "conflict_id": r_on.get("conflict_id"),
                    "new_omissions": sorted(om_on - om_off),
                    "dropped_omissions": sorted(om_off - om_on),
                    "keys_only_one_arm": sorted(
                        set(r_off) ^ set(r_on))[:6]})
        elif not changed_other:
            clean += 1
        else:
            deeper += 1
    out_doc = {
        "stage": "after", "root": root, "n_records_by_arm": n_by,
        "records_sha8_by_arm": recs_sha8,
        "base_tip_records_sha8": BASE_TIP_RECORDS_SHA8,
        "flag_off_equals_base_tip_records": (
            recs_sha8.get("off") == BASE_TIP_RECORDS_SHA8),
        "type_by_arm": dist, "other_share_by_arm": other,
        "changed_records": sum(1 for a, b in zip(arms["off"], arms["on"])
                               if a != b),
        "changed_only_type_or_basis": clean,
        "already_truncated_trimmed_deeper": deeper,
        "new_field_loss_or_new_omission": regressed,
        "regression_detail": regressed_detail,
        "no_regression": regressed == 0,
        "three_elements_on": {
            "清单": sum(1 for r in arms["on"] if r.get("冲突清单")),
            "结果": sum(1 for r in arms["on"] if r.get("结果")),
            "理由": sum(1 for r in arms["on"]
                      if str(r.get("rationale") or "").strip()),
            "重启条件": sum(1 for r in arms["on"] if r.get("重启条件")),
        },
    }
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(out_doc, ensure_ascii=False, indent=1)
                             + "\n", encoding="utf-8")
    set_enabled(True)
    print(json.dumps(out_doc, ensure_ascii=False, indent=1))
    return out_doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["compose", "after", "assemble"])
    ap.add_argument("--root", default="")
    ap.add_argument("--mode", default="both", choices=["current", "rule",
                                                       "both"])
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if args.stage == "assemble":
        return _assemble()
    root = args.root
    if not root or not Path(root).is_dir():
        print(f"跑不到：--root 缺或不存在（{root!r}）")
        return 2
    if args.stage == "after":
        stage_after(root, args.out)
        return 0
    rows = collect(root)
    mode = "rule" if args.mode in ("rule", "both") else "current"
    summ = summarize(rows, mode)
    doc = {"stage": args.stage, "root": root, "summary": summ,
           "gate": gate_block(summ),
           "source_date_coverage": source_date_coverage(root),
           "rows": rows}
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1)
                                  + "\n", encoding="utf-8")
    print(json.dumps({"summary": summ, "gate": doc["gate"]},
                     ensure_ascii=False, indent=1))
    return 0


def _assemble() -> int:
    """把 compose（改前基线＋规则腿）与 after（真导出两臂对照）拼成交账件。"""
    before = Path("/tmp/c155/compose.json")
    after = Path("/tmp/c155/after_export.json")
    if not before.is_file():
        print("跑不到：缺 /tmp/c155/compose.json（先跑 compose）")
        return 2
    b = _load(before)
    a = _load(after) if after.is_file() else None
    doc = {"ticket": "C-155", "official_anchor": "3.3.1／3.3.2／3.3.3",
           "gates_pre_written": {"other_share_target": OTHER_SHARE_GATE,
                                 "half_of_old": round(HALF_OF_OLD, 4),
                                 "old_batch": OLD_BATCH},
           "rule_source": "app.core.resolution_time_type.apply_tie_time_rule",
           "root": b.get("root"),
           "source_date_coverage": b.get("source_date_coverage"),
           "before": b["summary"], "before_gate": b["gate"],
           "after_export": a,
           "verdict": _verdict(b, a)}
    ART_JSON.parent.mkdir(exist_ok=True)
    ART_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    _render(doc)
    return 0


def _verdict(before: dict, after: dict | None) -> dict:
    """按跑前写死的两条线裁：目标线 40%／相对旧批降一半 44.1%。

    主判据用**同批配对**（同一 18 题、同一实现、只差旗位），跨批只作参照——
    旧批 17 条与现批 176 条分母不同，拿它当主判据就是把批次差异当成分数。
    """
    s = before.get("summary") or before
    share = (after or {}).get("other_share_by_arm", {}).get("on")
    if share is None:
        share = s.get("other_share_after_rule")
    if share is None:
        return {"verdict": "NO", "why": ["跑不到：没有「其他」占比读数"],
                "measured_share": None}
    same_batch = {"off": (after or {}).get("other_share_by_arm", {}).get("off"),
                  "on": share}
    hit_target = share <= OTHER_SHARE_GATE
    hit_half_old = share <= HALF_OF_OLD
    no_reg = bool((after or {}).get("no_regression", True))
    why = [f"同批配对：关旗 {same_batch['off']} → 开旗 {share}"
           f"（Δ{round((share or 0) - (same_batch['off'] or 0), 4):+}）",
           f"目标线≤{OTHER_SHARE_GATE}＝{'过' if hit_target else '不过'}；"
           f"跨批参照线≤{round(HALF_OF_OLD, 4)}＝"
           f"{'过' if hit_half_old else '不过'}（旧批 17 条≠现批 "
           f"{(after or {}).get('n_records_by_arm', {}).get('on')} 条，"
           "只作参照）",
           "无字段丢失／无新增 omission" if no_reg
           else "出现真回归（新掉字段或新 omission），不许开"]
    if not no_reg:
        return {"verdict": "NO", "why": why, "measured_share": share,
                "same_batch": same_batch}
    if hit_target:
        return {"verdict": "YES", "why": why, "measured_share": share,
                "same_batch": same_batch}
    return {"verdict": "PARTIAL", "why": why, "measured_share": share,
            "same_batch": same_batch}


def _render(doc: dict) -> None:
    b = doc["before"]
    a = doc.get("after_export") or {}
    cov = doc.get("source_date_coverage") or {}
    lines = [
        "# C-155 消解面读数（脚本现抄，非手打）",
        "",
        f"- 跑产物根＝`{doc.get('root')}`｜判尺实现＝`{doc.get('rule_source')}`",
        f"- 3.3.2 改前分布＝{b.get('type_current')}｜「其他」占比＝"
        f"{b.get('other_share_current')}",
        f"- 五类之外／缺／空＝{b.get('out_of_five_current')}",
        f"- 3.3.1 三要素（改前）＝{b.get('elements_current')}"
        f"（逐对合计 {b.get('n')}，无裁决 {b.get('n_no_resolution')}）",
        f"- 3.3.3 重启条件非空＝{b['elements_current'].get('重启条件非空')}"
        f"／{b.get('n')}",
        f"- 「其他」桶组成（method／decision_path／route／triage）＝"
        f"{b.get('other_composition')}",
        f"- 信源时点覆盖率（时效性能长多大的天花板）＝{cov}",
        "",
        "## 判尺腿（调仓内实现 apply_tie_time_rule，只补标签、不改胜负）",
        f"- 改前腿回填后分布＝{b.get('type_after_rule')}｜「其他」占比＝"
        f"{b.get('other_share_after_rule')}",
        f"- 命中规则条数＝{b.get('n_rule_applied')}"
        f"｜不变式（命中＋未命中＝分母）＝"
        f"{b.get('invariant_applied_plus_untouched_eq_n')}",
        f"- 报错（不许静默当「没改」）＝{b.get('rule_errors')}",
        f"- 改档明细＝{b.get('rule_moves')}",
        f"- 剩下仍「其他」的诚实原因＝{b.get('remaining_other')}",
        f"- 门槛（跑前写死）：目标≤{doc['gates_pre_written']['other_share_target']}"
        f"／相对旧批降一半≤{doc['gates_pre_written']['half_of_old']}"
        f"（旧批＝{doc['gates_pre_written']['old_batch']}）",
    ]
    if a:
        lines += [
            "",
            "## 改后＝真 export_official 两臂对照（同 18 题，只差旗位）",
            f"- 记录条数＝{a.get('n_records_by_arm')}",
            f"- 类型分布＝{a.get('type_by_arm')}",
            f"- 「其他」占比＝{a.get('other_share_by_arm')}",
            f"- 改动条数＝{a.get('changed_records')}"
            f"｜只动 type／basis＝{a.get('changed_only_type_or_basis')}"
            f"｜两臂本就截断、这次裁深＝"
            f"{a.get('already_truncated_trimmed_deeper')}"
            f"｜新掉字段或新 omission＝{a.get('new_field_loss_or_new_omission')}",
            f"- 回归明细＝{a.get('regression_detail')}",
            f"- 三要素与重启条件（开旗臂导出面）＝{a.get('three_elements_on')}",
            "- 关旗同形（三点取数，不是空比空）：关旗臂 records sha8＝"
            f"{(a.get('records_sha8_by_arm') or {}).get('off')}"
            f"／基 tip 3227200 同 18 题导出 sha8＝"
            f"{a.get('base_tip_records_sha8')}"
            f"⇒ 逐字节同改前？{a.get('flag_off_equals_base_tip_records')}"
            f"；开旗臂 sha8＝{(a.get('records_sha8_by_arm') or {}).get('on')}"
            "（与关旗不同＝旗真在动面）",
        ]
    else:
        lines += ["", "## 改后：未跑＝没有改后读数（不当 0 处理）"]
    v = doc.get("verdict") or {}
    lines += [
        "",
        f"**裁决＝{v.get('verdict')}**",
    ]
    for w in v.get("why") or []:
        lines.append(f"- {w}")
    lines += ["", "产物卫生：本件只含 id／计数／比率，零案卷原文、零模型输出原文。"]
    ART_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    head = [x for x in lines if not x.startswith("## 改后")]
    BASE_MD.write_text("\n".join(head[:16]) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
