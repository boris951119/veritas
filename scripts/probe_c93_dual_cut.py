#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-93：双切召回只量（自切 hier-v1 ↔ 拓尔思官方 para_id）。

Boyu 方案：同一原文两路切——
  ① 官方 raw_documents.paragraphs（para_id＋char_start/end）＝赛道真源；
  ② 我们 split_segments（hier-v1，目标~500／上限~650）。
两路各自 BM25 召回；自切命中经**字符重叠**映射回官方 para_id 后，
与官方召回合并进候选分表，再在**官方段案卷**上走现产 pack_material 打 L2。

一对多归并规则（硬约束，写死）：
  1. 自切段 [s,e) 与官方段 [os,oe) 交叠长度 ov=max(0,min(e,oe)-max(s,os))；
  2. ov>0 ⇒ 该官方 para_id 获得该自切段的 BM25 分（一对多展开，**不**把分摊薄）；
  3. 同一官方段被多条自切命中 ⇒ 取 **max** 分；
  4. ov==0 或自切段在原文中定位失败 ⇒ 计 mapping_fail，不进池；
  5. 交卷／金标／L2 **只认**官方 para_id；自切 id 永不进装箱选中集。

对照臂：
  A0          现产：官方案卷 + pack_material（BM25＋密度键）
  off_only    官方 BM25 分表 → _pack_with_scores（保真刀）
  self_map    仅映射后的自切分 → 装箱
  union_max   max(官方分, 映射自切分) → 装箱
  union_rrf   两路名次 RRF → 装箱
  union_avg   0.5·norm(官方)+0.5·norm(映射) → 装箱

判据 b：L2≥54/105 且相对 A0 lost=0。只量、默认关、不改生产、不 commit。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c93_dual_cut.py \\
      --run-dir /tmp/six2 --smoke --out-dir /tmp/c93_dual
  PYTHONPATH=. .venv/bin/python scripts/probe_c93_dual_cut.py \\
      --run-dir /tmp/six2 --out-dir /tmp/c93_dual
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import fuse_rankings, rank_segments  # noqa: E402
from app.core.evidence import Dossier, Segment, Source, SourceType  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import MIN_PARA_CHARS, load_official_case  # noqa: E402
from app.ingest.segment import SEGMENTER_VERSION, split_segments  # noqa: E402
from scripts.probe_c62_rerank_arms import _pack_with_scores  # noqa: E402
from scripts.probe_c66_multi_box import (  # noqa: E402
    _budget_from_report,
    l2_hits,
    selected_locs,
)
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD, discover_reports  # noqa: E402

TARGET_L2 = 54
TARGET_A0 = 48
TARGET_DENOM = 105
RRF_K = 60


def _load_raw_docs(case_dir: Path) -> list[dict]:
    data = json.loads((case_dir / "raw_documents.json").read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"raw_documents 非数组：{case_dir}")
    return data


def _official_spans(doc: dict) -> list[dict]:
    """[{para_id, char_start, char_end, text}]，跳过过短段（与 load_official_case 同阈）。"""
    content = str(doc.get("content") or "")
    out = []
    for para in doc.get("paragraphs") or []:
        if not isinstance(para, dict) or "para_id" not in para:
            continue
        start = int(para.get("char_start") or 0)
        end = int(para.get("char_end") or 0)
        text = content[start:end]
        if len(text) < MIN_PARA_CHARS:
            continue
        out.append({
            "para_id": str(para["para_id"]),
            "char_start": start,
            "char_end": end,
            "text": text,
        })
    return out


def _locate_self_cuts(content: str, pieces: list[str]) -> tuple[list[dict], int]:
    """顺序定位自切段在原文中的 [start,end)。失败条数单独计。"""
    pos = 0
    located: list[dict] = []
    fail = 0
    for i, piece in enumerate(pieces):
        p = piece
        idx = content.find(p, pos)
        if idx < 0:
            idx = content.find(p.strip(), pos)
        if idx < 0:
            # 全文再找一次（允许非单调）
            idx = content.find(p)
        if idx < 0:
            fail += 1
            continue
        end = idx + len(p if content[idx:idx + len(p)] == p else p.strip())
        # 若用了 strip 匹配，校正长度
        if content[idx:idx + len(p)] != p:
            end = idx + len(p.strip())
            p = content[idx:end]
        located.append({
            "self_id": f"self_{i}",
            "char_start": idx,
            "char_end": end,
            "text": p,
        })
        pos = max(pos, end)
    return located, fail


def _map_self_to_official(
    self_seg: dict,
    official: list[dict],
) -> list[tuple[str, int]]:
    """返回 [(para_id, overlap_chars), ...]，仅 ov>0。一对多全保留。"""
    s, e = self_seg["char_start"], self_seg["char_end"]
    hits: list[tuple[str, int]] = []
    for op in official:
        ov = max(0, min(e, op["char_end"]) - max(s, op["char_start"]))
        if ov > 0:
            hits.append((op["para_id"], ov))
    return hits


def build_self_cut_dossier(raw_docs: list[dict]) -> tuple[Dossier, dict[str, Any]]:
    """自切案卷＋映射表 meta。"""
    dossier = Dossier(question="", title="self_cut_probe")
    meta: dict[str, Any] = {
        "segmenter": SEGMENTER_VERSION,
        "n_self": 0,
        "n_locate_fail": 0,
        "n_map_empty": 0,  # 定位成功但与任何官方段无交叠
        "self_to_official": {},  # self_id -> [para_id,...]
        "official_paras": {},  # para_id -> {doc_id, start, end}
    }
    for doc in raw_docs:
        doc_id = str(doc.get("doc_id") or "").strip()
        if not doc_id:
            continue
        content = str(doc.get("content") or "")
        official = _official_spans(doc)
        for op in official:
            meta["official_paras"][op["para_id"]] = {
                "doc_id": doc_id,
                "char_start": op["char_start"],
                "char_end": op["char_end"],
            }
        pieces = split_segments(content)
        located, fail = _locate_self_cuts(content, pieces)
        meta["n_locate_fail"] += fail
        segs: list[Segment] = []
        for sc in located:
            sid = f"{doc_id}::{sc['self_id']}"
            mapped = _map_self_to_official(sc, official)
            if not mapped:
                meta["n_map_empty"] += 1
            meta["self_to_official"][sid] = [pid for pid, _ in mapped]
            segs.append(Segment(
                id=sid, source_id=doc_id, text=sc["text"],
                index=len(segs), locator=sid,
            ))
            meta["n_self"] += 1
        src = Source.create(
            str(doc.get("title") or doc_id), SourceType.WEB,
            id=doc_id, meta={"doc_id": doc_id},
        )
        src.segments = segs
        dossier.sources.append(src)
    return dossier, meta


def _scores_dict(ranked: list[tuple[str, float]]) -> dict[str, float]:
    return {sid: float(sc) for sid, sc in ranked}


def map_self_scores_to_official(
    self_scores: dict[str, float],
    self_to_official: dict[str, list[str]],
) -> tuple[dict[str, float], int, int]:
    """自切分 → 官方 para_id 分（max 归并）。返回 (scores, n_mapped_hits, n_unmapped_hits)。"""
    out: dict[str, float] = defaultdict(float)
    n_ok = n_fail = 0
    for sid, sc in self_scores.items():
        if sc <= 0:
            continue
        targets = self_to_official.get(sid) or []
        if not targets:
            n_fail += 1
            continue
        n_ok += 1
        for pid in targets:
            out[pid] = max(float(out.get(pid, 0.0)), float(sc))
    return dict(out), n_ok, n_fail


def _norm(scores: dict[str, float]) -> dict[str, float]:
    m = max(scores.values()) if scores else 0.0
    if m <= 0:
        return {k: 0.0 for k in scores}
    return {k: float(v) / m for k, v in scores.items()}


def _rrf_fuse(
    off: dict[str, float],
    mapped: dict[str, float],
) -> dict[str, float]:
    r_off = sorted(off.items(), key=lambda x: (-x[1], x[0]))
    r_map = sorted(mapped.items(), key=lambda x: (-x[1], x[0]))
    fused = fuse_rankings([r_off, r_map], k=RRF_K)
    return _scores_dict(fused)


def _avg_fuse(off: dict[str, float], mapped: dict[str, float]) -> dict[str, float]:
    no, nm = _norm(off), _norm(mapped)
    keys = set(no) | set(nm)
    return {k: 0.5 * no.get(k, 0.0) + 0.5 * nm.get(k, 0.0) for k in keys}


def _max_fuse(off: dict[str, float], mapped: dict[str, float]) -> dict[str, float]:
    keys = set(off) | set(mapped)
    return {k: max(float(off.get(k, 0.0)), float(mapped.get(k, 0.0))) for k in keys}


def _ensure_all_official_keys(
    scores: dict[str, float], official_dossier: Dossier,
) -> dict[str, float]:
    out = dict(scores)
    for src in official_dossier.sources:
        for seg in src.segments:
            out.setdefault(seg.id, 0.0)
    return out


def run_question(
    *,
    case: str,
    qid: str,
    query: str,
    budget: int,
    gold_dir: Path,
    case_dir: Path,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    raw_docs = _load_raw_docs(case_dir)
    off_d = load_official_case(case_dir)
    off_d.question = query
    self_d, cut_meta = build_self_cut_dossier(raw_docs)
    self_d.question = query

    gold, denom = _gold_keys(gold_dir, case, qid)
    if denom == 0:
        return {"case": case, "qid": qid, "skip": True, "reason": "no_gold"}

    # A0
    p0 = pack_material(off_d, budget_chars=budget)
    sel_a0 = {str(x) for x in (p0.get("selected") or [])}
    loc_a0 = selected_locs(off_d, sel_a0)
    hits_a0 = l2_hits(gold, loc_a0)

    off_ranked = rank_segments(off_d)
    off_scores = _scores_dict(off_ranked)
    self_ranked = rank_segments(self_d)
    self_scores = _scores_dict(self_ranked)
    mapped, n_map_ok, n_map_fail = map_self_scores_to_official(
        self_scores, cut_meta["self_to_official"])

    arms_scores = {
        "off_only": off_scores,
        "self_map": mapped,
        "union_max": _max_fuse(off_scores, mapped),
        "union_rrf": _rrf_fuse(off_scores, mapped),
        "union_avg": _avg_fuse(off_scores, mapped),
    }

    row: dict[str, Any] = {
        "case": case, "qid": qid, "denom": denom, "budget": budget,
        "a0_hits": hits_a0, "a0_n": len(sel_a0),
        "n_official_segs": sum(len(s.segments) for s in off_d.sources),
        "n_self_segs": cut_meta["n_self"],
        "n_locate_fail": cut_meta["n_locate_fail"],
        "n_map_empty_segs": cut_meta["n_map_empty"],
        "n_self_score_mapped": n_map_ok,
        "n_self_score_unmapped": n_map_fail,
        "elapsed_s": 0.0,
    }

    gold_in_off_top = set()
    # 池内金标：官方 BM25>0 的段 ∩ 金标
    off_pos = {sid for sid, sc in off_scores.items() if sc > 0}
    loc_off_pos = selected_locs(off_d, off_pos)
    gold_in_off_pool = gold & loc_off_pos
    mapped_pos = {sid for sid, sc in mapped.items() if sc > 0}
    loc_map_pos = selected_locs(off_d, mapped_pos)
    gold_in_map_pool = gold & loc_map_pos
    row["gold_in_off_pool"] = len(gold_in_off_pool)
    row["gold_in_map_pool"] = len(gold_in_map_pool)
    row["gold_only_in_map"] = len(gold_in_map_pool - gold_in_off_pool)
    row["gold_only_in_off"] = len(gold_in_off_pool - gold_in_map_pool)

    for name, sc in arms_scores.items():
        full = _ensure_all_official_keys(sc, off_d)
        sel = _pack_with_scores(off_d, budget, full)
        loc = selected_locs(off_d, sel)
        hits = l2_hits(gold, loc)
        lost = len((gold & loc_a0) - loc)
        gained = len((gold & loc) - loc_a0)
        row[f"{name}_hits"] = hits
        row[f"{name}_lost"] = lost
        row[f"{name}_gained"] = gained
        row[f"{name}_n"] = len(sel)

    row["elapsed_s"] = round(time.perf_counter() - t0, 3)
    row["skip"] = False
    return row


def collect_jobs(
    run_dir: Path,
    gold_dir: Path,
    *,
    only_cases: set[str] | None,
    smoke: bool,
) -> list[dict]:
    jobs = []
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        if only_cases and case not in only_cases:
            continue
        rep = json.loads(rp.read_text(encoding="utf-8"))
        jobs.append({
            "case": case,
            "qid": qid,
            "query": str(rep.get("question") or ""),
            "budget": _budget_from_report(rep),
            "report": str(rp),
        })
    jobs.sort(key=lambda j: (j["case"], j["qid"]))
    if smoke:
        # 碎 vs 粗：吉隆 q_001 + 刘翔 q_001
        want = []
        for pref in ("吉隆", "刘翔"):
            for j in jobs:
                if pref in j["case"] and j["qid"] == "q_001":
                    want.append(j)
                    break
        if len(want) < 2:
            want = jobs[:2]
        return want
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default="/tmp/six2")
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--out-dir", default="/tmp/c93_dual")
    ap.add_argument("--smoke", action="store_true", help="只跑吉隆+刘翔各 q_001")
    ap.add_argument(
        "--cases", default="",
        help="逗号分隔案名子串过滤；空＝六案",
    )
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gold_dir = Path(args.gold_dir)
    run_dir = Path(args.run_dir)

    only = None
    if args.cases.strip():
        only = set()
        # match by substring against discovered cases
        all_cases = {rp.parts[-4] for rp in discover_reports(run_dir)}
        for tok in args.cases.split(","):
            tok = tok.strip()
            if not tok:
                continue
            for c in all_cases:
                if tok in c:
                    only.add(c)

    jobs = collect_jobs(run_dir, gold_dir, only_cases=only, smoke=args.smoke)
    print(
        f"======== C-93 双切召回只量{'（烟雾）' if args.smoke else ''} ========",
        flush=True,
    )
    print(f"jobs={len(jobs)} segmenter={SEGMENTER_VERSION}", flush=True)

    rows = []
    tot = Counter()
    t_all = time.perf_counter()
    for job in jobs:
        case_dir = gold_dir / job["case"]
        if not (case_dir / "raw_documents.json").is_file():
            print(f"跳过缺 raw：{job['case']}", flush=True)
            continue
        row = run_question(
            case=job["case"], qid=job["qid"], query=job["query"],
            budget=job["budget"], gold_dir=gold_dir, case_dir=case_dir,
        )
        if row.get("skip"):
            continue
        rows.append(row)
        tot["denom"] += row["denom"]
        tot["a0"] += row["a0_hits"]
        for arm in ("off_only", "self_map", "union_max", "union_rrf", "union_avg"):
            tot[f"{arm}_hits"] += row[f"{arm}_hits"]
            tot[f"{arm}_lost"] += row[f"{arm}_lost"]
            tot[f"{arm}_gained"] += row[f"{arm}_gained"]
        tot["locate_fail"] += row["n_locate_fail"]
        tot["map_empty"] += row["n_map_empty_segs"]
        tot["self_unmapped_hits"] += row["n_self_score_unmapped"]
        tot["self_mapped_hits"] += row["n_self_score_mapped"]
        tot["gold_map_only"] += row["gold_only_in_map"]
        print(
            f"  {row['case'][:14]} {row['qid']}: "
            f"A0={row['a0_hits']}/{row['denom']} "
            f"union_max={row['union_max_hits']}(L{row['union_max_lost']}G{row['union_max_gained']}) "
            f"self_map={row['self_map_hits']} "
            f"map_fail_segs={row['n_map_empty_segs']}+loc={row['n_locate_fail']} "
            f"{row['elapsed_s']}s",
            flush=True,
        )

    denom = int(tot["denom"])
    a0 = int(tot["a0"])
    arms = {}
    for arm in ("off_only", "self_map", "union_max", "union_rrf", "union_avg"):
        h = int(tot[f"{arm}_hits"])
        lo = int(tot[f"{arm}_lost"])
        g = int(tot[f"{arm}_gained"])
        arms[arm] = {
            "l2_hits": h,
            "lost_n": lo,
            "gained_n": g,
            "vs_a0_delta": h - a0,
            "gate_b": (
                (not args.smoke)
                and denom == TARGET_DENOM
                and h >= TARGET_L2
                and lo == 0
            ),
            "gate_b_note": (
                "smoke／非整六案＝不判门槛 b"
                if args.smoke or denom != TARGET_DENOM
                else ("过" if h >= TARGET_L2 and lo == 0 else "逃逸")
            ),
        }

    summary = {
        "smoke": bool(args.smoke),
        "n_questions": len(rows),
        "denom": denom,
        "a0": a0,
        "reproduce_a0_ok": (not args.smoke) and a0 == TARGET_A0 and denom == TARGET_DENOM,
        "arms": arms,
        "mapping": {
            "n_locate_fail": int(tot["locate_fail"]),
            "n_map_empty_segs": int(tot["map_empty"]),
            "n_self_score_mapped": int(tot["self_mapped_hits"]),
            "n_self_score_unmapped": int(tot["self_unmapped_hits"]),
            "map_fail_rate_among_scored": round(
                tot["self_unmapped_hits"]
                / max(tot["self_mapped_hits"] + tot["self_unmapped_hits"], 1),
                4,
            ),
            "gold_only_in_map_pool_sum": int(tot["gold_map_only"]),
        },
        "elapsed_s": round(time.perf_counter() - t_all, 3),
        "segmenter": SEGMENTER_VERSION,
        "rows": rows,
        "gate_rule": "L2>=54/105 and lost=0 vs A0 (full six only)",
    }

    print("-------- 合计 --------", flush=True)
    print(
        f"A0={a0}/{denom} "
        f"{'OK' if summary.get('reproduce_a0_ok') or args.smoke else '（非整六或不符 48）'}",
        flush=True,
    )
    for k, lab in [
        ("off_only", "仅官方BM25装箱"),
        ("self_map", "仅映射自切"),
        ("union_max", "官方∪映射 max"),
        ("union_rrf", "官方∪映射 RRF"),
        ("union_avg", "官方∪映射 0.5/0.5"),
    ]:
        a = arms[k]
        print(
            f"  {lab}: L2={a['l2_hits']}/{denom} "
            f"lost={a['lost_n']} gained={a['gained_n']} "
            f"ΔA0={a['vs_a0_delta']:+d} [{a['gate_b_note']}]",
            flush=True,
        )
    print("映射:", json.dumps(summary["mapping"], ensure_ascii=False), flush=True)
    print(f"耗时合计 {summary['elapsed_s']}s", flush=True)

    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"落盘 {out / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
