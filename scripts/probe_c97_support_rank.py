#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-97：机械「支撑分」排序只量（刘翔主尺）。

接 C-96：关灌满／粗槽买不到 gained。本票改排序目标＝支撑信号，不是相关／槽盖住。

支撑信号（零 LLM、只看问句＋段文、不碰金标）：
  1. 主体锁定：问句实体出现在段内
  2. 议题数字：问句数字／金额片出现在段内
  3. 对立口径：问句「A还是B」两侧说法片出现在段内
分＝ 1000·subj + 100·n_num + 50·n_alt + bm25_norm∈[0,1]
（bm25 只打平手；主体为硬加分，不是唯一闸）

臂：
  A0         现产 pack_material
  SuppPri    支撑分主序 + 关零分灌满
  SuppGate   无主体命中 ⇒ 分清零，再同 SuppPri（资格闸）
  SuppHard   须 主体∧(数字∨对立口径) 才保留分，再同 SuppPri
  C85Pri     （可选）C-85 融合分 + 分主序，作旁证；缺缓存则跳过

门槛：刘翔 lost=0 且 gained>0 才算合入候选；Δ=0＝FLAT；掉分＝ESCAPE。
只量、默认关；不改生产；不 commit。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c97_support_rank.py \\
      --out-dir /tmp/c97_supp
  PYTHONPATH=. .venv/bin/python scripts/probe_c97_support_rank.py --smoke
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.answer_slots import priority_segment_ids  # noqa: E402
from app.core.bm25 import rank_segments  # noqa: E402
from app.core.dup_check import duplicate_map  # noqa: E402
from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material, pack_search_queries  # noqa: E402
from app.core.numeric_check import extract_nums  # noqa: E402
from app.core.relevance import classify_sources  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from app.ingest.segment import SEGMENT_MAX  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _fuse, _gold_keys  # noqa: E402
from scripts.probe_c91_mono_pack import _pack_score_primary  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

CASE_SUB = "刘翔"
DEFAULT_C85 = Path("/tmp/c85_k180")
DEFAULT_CASES = DEFAULT_GOLD

_ALT_SPLIT = re.compile(r"(?:还是|或者|或是|抑或)")
_DIGITISH = re.compile(r"^[\d年月日时分秒点．.%％\-—~～/\s万亿]+$")
_ORG_SUFFIX = re.compile(r"局|部|厅|委|办|院|队|公司|集团|银行")
# 问句虚尾／抽脏片
_STOP_ENT = {
    "是否", "还是", "应以", "为准", "关于", "什么", "如何", "怎样", "多少",
    "可以", "能够", "因为", "所以", "以及", "或者", "如果", "那么", "这个",
    "那个", "一个", "哪方", "哪一", "一方", "说法", "口径", "认定", "至今",
    "官方", "称为", "能否", "真有", "拖了", "才安", "这笔", "哪一方",
    "方口径为准", "一方说法站得住", "以人事档案证实", "官方称",
}
def _billing_len(text: str) -> int:
    return min(len(text or ""), int(SEGMENT_MAX))


def _eligible_lengths(dossier: Dossier) -> dict[str, int]:
    dups = duplicate_map(dossier)
    relevance = {s["source_id"]: s for s in classify_sources(dossier)}
    lengths: dict[str, int] = {}
    for src in dossier.sources:
        if src.id in dups or (relevance.get(src.id) or {}).get("level") == "zero":
            continue
        for seg in src.segments:
            lengths[seg.id] = _billing_len(seg.text)
    if not lengths:
        for src in dossier.sources:
            if src.id in dups:
                continue
            for seg in src.segments:
                lengths[seg.id] = _billing_len(seg.text)
    return lengths


def _texts(dossier: Dossier) -> dict[str, str]:
    return {
        seg.id: (seg.text or "")
        for src in dossier.sources for seg in src.segments
    }


def _bm25_scores(dossier: Dossier) -> dict[str, float]:
    queries = pack_search_queries(dossier)
    ranked = (
        rank_segments(dossier, queries=queries)
        if queries else rank_segments(dossier)
    )
    return {str(k): float(v) for k, v in dict(ranked).items()}


def _ok_phrase(p: str) -> bool:
    p = (p or "").strip()
    if len(p) < 2 or len(p) > 16:
        return False
    if p in _STOP_ENT:
        return False
    if _DIGITISH.fullmatch(p):
        return False
    return True


def _query_subjects(query: str) -> list[str]:
    """问句主体：机构后缀 + 「是X不愿」人名。

    不用 extract_entities（切片太脏）。不写案名表。
    """
    q = query or ""
    ents: list[str] = []
    seen: set[str] = set()

    def _add(e: str) -> None:
        e = (e or "").strip()
        if not _ok_phrase(e) or e in seen:
            return
        if len(e) < 2 or len(e) > 8:
            return
        # 拒「年才／否真有」一类邻域误切
        if any(ch in e for ch in "是否才其称的了"):
            return
        seen.add(e)
        ents.append(e)

    # 自后缀位向前取 2–4 字（避免「还是体育局」被贪成「还是体育+局」）
    for m in _ORG_SUFFIX.finditer(q):
        tail = m.group(0)
        start = m.start()
        picked = None
        for n in (2, 3, 4):
            if start < n:
                continue
            head = q[start - n:start]
            if not re.fullmatch(r"[\u4e00-\u9fff]+", head):
                continue
            if any(ch in head for ch in "是否还或的了其才"):
                continue
            picked = head + tail
            break
        if picked:
            _add(picked)
    for m in re.finditer(r"是([\u4e00-\u9fff]{2,3})不愿", q):
        _add(m.group(1))
    for m in re.finditer(r"([\u4e00-\u9fff]{2,3})退役", q):
        _add(m.group(1))
    ents.sort(key=len, reverse=True)
    return ents


def _query_numbers(query: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for num in extract_nums(query or ""):
        raw = (num.raw or "").strip()
        cands = []
        if raw:
            cands.append(raw)
        scaled = f"{num.scaled:g}"
        if abs(num.scaled) >= 10 or (
            raw and ("%" in raw or "万" in raw or "亿" in raw)
        ):
            cands.append(scaled)
        for c in cands:
            if c and c not in seen:
                seen.add(c)
                out.append(c)
    for m in re.findall(r"\d+(?:\.\d+)?", query or ""):
        if m not in seen and len(m) <= 8:
            seen.add(m)
            out.append(m)
    return out


def _query_alts(query: str) -> list[str]:
    """从「A还是B」抽两侧核心说法；无对立 → []。"""
    q = (query or "").strip()
    if "还是" not in q and "或者" not in q:
        return []
    # 裁掉问句尾巴「以哪方…」「哪一方…」
    q2 = re.sub(
        r"[，,]?(?:以哪方.*|哪一方.*|哪方.*|能否.*)$",
        "",
        q,
    )
    parts = _ALT_SPLIT.split(q2)
    if len(parts) < 2:
        return []
    out: list[str] = []
    seen: set[str] = set()
    scrub = re.compile(
        r"^(?:这笔|应认定为|认定为|是|拖了\d+年才安置，?)|"
        r"(?:以哪方口径为准|哪一方说法站得住)$"
    )
    for part in parts[:2]:
        p = scrub.sub("", part.strip()).strip("，。、 ")
        # 优先整侧；过长再取末 4–12 字有内容片
        cands = [p] if 2 <= len(p) <= 16 else []
        cands += re.findall(r"[\u4e00-\u9fff]{2,12}", p)
        for c in cands:
            c = c.strip()
            if c in seen or c in _STOP_ENT:
                continue
            if not _ok_phrase(c) and not re.search(r"\d", c):
                continue
            # 跳过过宽的整句残片
            if "安置" in c and len(c) > 6:
                continue
            seen.add(c)
            out.append(c)
            break  # 每侧只留一条主说法
    return out


def extract_support_cues(query: str) -> dict[str, Any]:
    return {
        "subjects": _query_subjects(query),
        "numbers": _query_numbers(query),
        "alts": _query_alts(query),
    }


def _hits_in(text: str, needles: list[str]) -> list[str]:
    t = text or ""
    return [n for n in needles if n and n in t]


def support_features(
    text: str, cues: dict[str, Any],
) -> dict[str, Any]:
    subj = _hits_in(text, cues.get("subjects") or [])
    nums = _hits_in(text, cues.get("numbers") or [])
    alts = _hits_in(text, cues.get("alts") or [])
    return {
        "subj": subj,
        "nums": nums,
        "alts": alts,
        "has_subj": bool(subj),
        "has_num": bool(nums),
        "has_alt": bool(alts),
        "hard_ok": bool(subj) and (bool(nums) or bool(alts)),
    }


def support_score(
    feat: dict[str, Any],
    bm25: float,
    max_bm25: float,
    *,
    mode: str,
) -> float:
    """mode: full | gate_subj | hard."""
    if mode == "gate_subj" and not feat["has_subj"]:
        return 0.0
    if mode == "hard" and not feat["hard_ok"]:
        return 0.0
    bn = (float(bm25) / max_bm25) if max_bm25 > 0 else 0.0
    return (
        1000.0 * (1.0 if feat["has_subj"] else 0.0)
        + 100.0 * len(feat["nums"])
        + 50.0 * len(feat["alts"])
        + bn
    )


def _pack_pri_nofill(
    dossier: Dossier, budget: int, scores: dict[str, float],
) -> set[str]:
    """分主序 + 关零分灌满（复用 c91 主序但不跑零分轮转）。"""
    budget = max(1, int(budget))
    lengths = _eligible_lengths(dossier)
    selected: set[str] = set()
    used = 0

    def _take(seg_id: str) -> bool:
        nonlocal used
        if seg_id in selected or seg_id not in lengths:
            return False
        ln = lengths[seg_id]
        if used + ln > budget:
            return False
        selected.add(seg_id)
        used += ln
        return True

    for seg_id in priority_segment_ids(dossier):
        _take(seg_id)
    scored = [
        g for g in lengths
        if scores.get(g, 0.0) > 0.0 and g not in selected
    ]
    for seg_id in sorted(scored, key=lambda g: (-scores.get(g, 0.0), g)):
        if used >= budget:
            break
        _take(seg_id)
    return selected


def _build_score_table(
    dossier: Dossier,
    cues: dict[str, Any],
    bm25: dict[str, float],
    *,
    mode: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    lengths = _eligible_lengths(dossier)
    texts = _texts(dossier)
    max_b = max((bm25.get(g, 0.0) for g in lengths), default=0.0) or 1.0
    scores: dict[str, float] = {}
    n_subj = n_hard = n_pos = 0
    for g in lengths:
        feat = support_features(texts.get(g, ""), cues)
        sc = support_score(feat, bm25.get(g, 0.0), max_b, mode=mode)
        scores[g] = sc
        if feat["has_subj"]:
            n_subj += 1
        if feat["hard_ok"]:
            n_hard += 1
        if sc > 0:
            n_pos += 1
    meta = {
        "n_eligible": len(lengths),
        "n_with_subj": n_subj,
        "n_hard_ok": n_hard,
        "n_score_pos": n_pos,
        "mode": mode,
    }
    return scores, meta


def _load_lx_jobs(c85_dir: Path) -> list[dict]:
    path = c85_dir / "score_input.json"
    if not path.is_file():
        raise SystemExit(f"缺 {path}")
    jobs = json.loads(path.read_text(encoding="utf-8"))
    out = [j for j in jobs if CASE_SUB in j["case"]]
    if len(out) != 3:
        raise SystemExit(f"期望刘翔 3 问，实得 {len(out)}")
    return sorted(out, key=lambda j: j["qid"])


def _eval(gold, loc_a0, dossier, selected):
    loc = selected_locs(dossier, selected)
    hits = l2_hits(gold, loc)
    lost = len((gold & loc_a0) - loc)
    gained = len((gold & loc) - loc_a0)
    return hits, lost, gained


def _arm_status(hits, lost, gained, a0):
    hard = lost == 0 and hits >= a0
    if hard and gained > 0:
        return "IMPROVE"
    if hard:
        return "FLAT"
    return "ESCAPE"


def run_all(
    *,
    gold_dir: Path,
    cases_root: Path,
    c85_dir: Path,
    smoke_qid: str | None,
    with_c85: bool,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    jobs = _load_lx_jobs(c85_dir)
    if smoke_qid:
        jobs = [j for j in jobs if j["qid"] == smoke_qid]
        if not jobs:
            raise SystemExit(f"smoke 无此问 {smoke_qid}")

    scores_c = None
    if with_c85:
        sp = c85_dir / "llm_scores_c.json"
        if sp.is_file():
            scores_c = json.loads(sp.read_text(encoding="utf-8"))
        else:
            with_c85 = False

    rows: list[dict[str, Any]] = []
    tot: Counter = Counter()
    arms = ["SuppPri", "SuppGate", "SuppHard"]
    if with_c85:
        arms.append("C85Pri")

    for job in jobs:
        case, qid, query = job["case"], job["qid"], job["query"]
        budget = int(job["budget"])
        case_dir = cases_root / case
        dossier = load_official_case(case_dir)
        dossier.question = query
        gold, denom = _gold_keys(gold_dir, case, qid)
        cues = extract_support_cues(query)
        bm25 = _bm25_scores(dossier)

        p0 = pack_material(dossier, budget_chars=budget)
        sel_a0 = {str(x) for x in (p0.get("selected") or [])}
        loc_a0 = selected_locs(dossier, sel_a0)
        a0_hits = l2_hits(gold, loc_a0)

        # 金标段上的支撑特征（诊断，不算泄漏训练——只报告）
        texts = _texts(dossier)
        gold_locs = gold
        gold_feat = {"n": 0, "subj": 0, "num": 0, "alt": 0, "hard": 0}
        lengths = _eligible_lengths(dossier)
        for sid in lengths:
            loc = selected_locs(dossier, {sid})
            if not (loc & gold_locs):
                continue
            gold_feat["n"] += 1
            f = support_features(texts.get(sid, ""), cues)
            if f["has_subj"]:
                gold_feat["subj"] += 1
            if f["has_num"]:
                gold_feat["num"] += 1
            if f["has_alt"]:
                gold_feat["alt"] += 1
            if f["hard_ok"]:
                gold_feat["hard"] += 1

        row: dict[str, Any] = {
            "case": case, "qid": qid, "denom": denom, "budget": budget,
            "query": query, "cues": cues,
            "A0": {"hits": a0_hits, "n": len(sel_a0)},
            "gold_support_feat": gold_feat,
        }

        for mode, name in (
            ("full", "SuppPri"),
            ("gate_subj", "SuppGate"),
            ("hard", "SuppHard"),
        ):
            sc, meta = _build_score_table(dossier, cues, bm25, mode=mode)
            sel = _pack_pri_nofill(dossier, budget, sc)
            h, lo, g = _eval(gold, loc_a0, dossier, sel)
            row[name] = {
                "hits": h, "lost": lo, "gained": g, "n": len(sel),
                "status": _arm_status(h, lo, g, a0_hits),
                "meta": meta,
            }
            tot[f"{name}_hits"] += h
            tot[f"{name}_lost"] += lo
            tot[f"{name}_gained"] += g

        if with_c85 and scores_c is not None:
            key = f"{case}::{qid}"
            raw = scores_c.get(key)
            if raw is None:
                row["C85Pri"] = {"skip": True, "reason": f"缺分 {key}"}
            else:
                if isinstance(raw, dict):
                    id_sc = {str(k): float(v) for k, v in raw.items()}
                else:
                    id_sc = {
                        cid: float(s) for cid, s in zip(job["ids"], raw)
                    }
                # 对齐 job 内 bm25（冻结）或现场
                bm25_j = {
                    str(k): float(v)
                    for k, v in (job.get("bm25_scores") or {}).items()
                }
                for sid in id_sc:
                    bm25_j.setdefault(sid, 0.0)
                    bm25.setdefault(sid, bm25_j.get(sid, 0.0))
                fused = _fuse(bm25_j or bm25, id_sc, use_bm25=True)
                # 分主序（c91）；仍可能含零分轮转——旁证用 production-like pri
                sel = _pack_score_primary(dossier, budget, fused)
                h, lo, g = _eval(gold, loc_a0, dossier, sel)
                row["C85Pri"] = {
                    "hits": h, "lost": lo, "gained": g, "n": len(sel),
                    "status": _arm_status(h, lo, g, a0_hits),
                }
                tot["C85Pri_hits"] += h
                tot["C85Pri_lost"] += lo
                tot["C85Pri_gained"] += g

        rows.append(row)
        tot["denom"] += denom
        tot["a0"] += a0_hits

    def _sum_arm(name: str) -> dict[str, Any]:
        hits = int(tot.get(f"{name}_hits", 0))
        lost = int(tot.get(f"{name}_lost", 0))
        gained = int(tot.get(f"{name}_gained", 0))
        a0 = int(tot["a0"])
        st = _arm_status(hits, lost, gained, a0)
        return {
            "hits": hits, "lost": lost, "gained": gained,
            "denom": int(tot["denom"]), "a0": a0,
            "delta_vs_a0": hits - a0,
            "status": st,
            "improve_pass": st == "IMPROVE",
        }

    summary = {
        "ticket": "C-97",
        "ruler": "刘翔",
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "A0_hits": int(tot["a0"]),
        "gate": "IMPROVE＝lost0∧L2≥A0∧gained>0；否则 FLAT／ESCAPE",
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "note": (
            "只量；支撑＝主体+数字+对立口径机械分；零 LLM；"
            "C85Pri 旁证可选；生产默认关"
        ),
    }
    for a in arms:
        if any(a in r for r in rows):
            summary[a] = _sum_arm(a)

    if any(summary.get(a, {}).get("improve_pass") for a in arms if a in summary):
        summary["verdict"] = "PASS_CANDIDATE"
    elif any(
        summary.get(a, {}).get("status") == "FLAT" for a in arms if a in summary
    ):
        summary["verdict"] = "FLAT_no_gain"
    else:
        summary["verdict"] = "ESCAPE"
    return {"summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="C-97 support-rank (LiuXiang)")
    ap.add_argument("--out-dir", type=Path, default=Path("/tmp/c97_supp"))
    ap.add_argument("--gold-dir", type=Path, default=None)
    ap.add_argument("--cases-root", type=Path, default=None)
    ap.add_argument("--c85-dir", type=Path, default=DEFAULT_C85)
    ap.add_argument("--no-c85", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--smoke-qid", default=None)
    args = ap.parse_args()
    gold_dir = args.gold_dir or DEFAULT_GOLD
    cases_root = args.cases_root or DEFAULT_CASES
    smoke_qid = args.smoke_qid or ("q_001" if args.smoke else None)

    result = run_all(
        gold_dir=gold_dir,
        cases_root=cases_root,
        c85_dir=args.c85_dir,
        smoke_qid=smoke_qid,
        with_c85=not args.no_c85,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(result["summary"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out_dir / "rows.json").write_text(
        json.dumps(result["rows"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    s = result["summary"]
    print("=== C-97 刘翔主尺 · 支撑分 ===")
    print(f"A0     {s['A0_hits']}/{s['denom']}")
    for name in ("SuppPri", "SuppGate", "SuppHard", "C85Pri"):
        if name not in s:
            continue
        a = s[name]
        print(
            f"{name:10s} {a['hits']}/{a['denom']} "
            f"lost={a['lost']} gained={a['gained']} "
            f"Δ={a['delta_vs_a0']:+d}  [{a['status']}]"
        )
    print("verdict", s["verdict"], f"elapsed={s['elapsed_s']}s")
    print("wrote", args.out_dir)


if __name__ == "__main__":
    main()
