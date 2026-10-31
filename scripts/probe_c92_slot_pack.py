#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-92：事实槽选段只量（零模型；接「相关≠支撑」改轴方案）。

方案（Boyu 拍可按此做）：
  - 用现行 fact_ledger._scan 把段挂上 (实体, 指标, 数值)
  - 议题抽出槽线索（数字／出现在台账里的实体与指标词）
  - 段分＝槽匹配（含同主体 1 跳）＋轻度 BM25；装箱用分主序（不除长度）
  - 对照生产 A0（BM25＋密度键）

判据 b（探索）：L2≥54 且相对 A0 lost=0。生产默认不动。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c92_slot_pack.py \\
      --c85-dir /tmp/c85_k180 --out-dir /tmp/c92_slot
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.fact_ledger import Fact, _scan  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.core.numeric_check import extract_nums  # noqa: E402
from scripts.probe_c62_rerank_arms import _pack_with_scores  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_c91_mono_pack import _pack_score_primary  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

TARGET_L2 = 54
TARGET_A0 = 48
TARGET_DENOM = 105

_CN_RUN = re.compile(r"[\u4e00-\u9fff]{2,12}")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9\-.]{1,40}")
_DIGITISH = re.compile(r"^[\d年月日时分秒点．.%％\-—~～/\s]+$")
# 议题虚词，不作槽
_QUERY_STOP = {
    "是否", "还是", "应以", "为准", "关于", "什么", "如何", "怎样", "多少",
    "可以", "能够", "因为", "所以", "以及", "或者", "如果", "那么", "这个",
    "那个", "一个", "我们", "他们", "你们", "什么时候", "为什么",
}


def _ok_entity(e: str) -> bool:
    e = (e or "").strip()
    if len(e) < 2 or len(e) > 16:
        return False
    if _DIGITISH.match(e):
        return False
    if e.isdigit():
        return False
    if e in _QUERY_STOP:
        return False
    # 纯短数字片
    if re.fullmatch(r"\d{1,4}", e):
        return False
    return True


def _ok_metric(m: str) -> bool:
    m = (m or "").strip()
    if len(m) < 2 or len(m) > 16:
        return False
    if _DIGITISH.match(m):
        return False
    if m in _QUERY_STOP:
        return False
    return True


def _query_numbers(query: str) -> set[str]:
    out: set[str] = set()
    for num in extract_nums(query or ""):
        raw = (num.raw or "").strip()
        if raw:
            out.add(raw)
        # 只要「有辨识度」的数，避免把年份碎片当槽
        if abs(num.scaled) >= 10 or raw.endswith("%") or "万" in raw or "亿" in raw:
            out.add(f"{num.scaled:g}")
    return out


def _build_indexes(facts: list[Fact]) -> tuple[dict[str, list[Fact]], set[str], set[str]]:
    by_seg: dict[str, list[Fact]] = defaultdict(list)
    entities: set[str] = set()
    metrics: set[str] = set()
    for f in facts:
        by_seg[f.seg_id].append(f)
        if _ok_entity(f.entity):
            entities.add(f.entity.strip())
        for m in (f.metric, f.metric_canon):
            if _ok_metric(m or ""):
                metrics.add(m.strip())
    return by_seg, entities, metrics


def _query_phrases(query: str) -> list[str]:
    """议题自身抽槽：较长中文片＋拉丁专名；去停用。"""
    q = query or ""
    phrases: list[str] = []
    seen: set[str] = set()
    for m in _LATIN.findall(q):
        if m.lower() not in seen and len(m) >= 2:
            seen.add(m.lower())
            phrases.append(m)
    # 中文：取长度≥3 的 run，再切出长度 3..8 的子串会爆炸；只保留整段 run
    for run in _CN_RUN.findall(q):
        if run in _QUERY_STOP or len(run) < 3:
            continue
        if run not in seen:
            seen.add(run)
            phrases.append(run)
    # 长者优先（匹配时）
    phrases.sort(key=len, reverse=True)
    return phrases


def _query_slots(query: str, entities: set[str], metrics: set[str]) -> dict[str, Any]:
    q = query or ""
    hit_ent = sorted(
        {e for e in entities if e and e in q and _ok_entity(e)},
        key=len, reverse=True,
    )
    hit_met = sorted(
        {m for m in metrics if m and m in q and _ok_metric(m)},
        key=len, reverse=True,
    )
    phrases = _query_phrases(q)
    return {
        "entities": hit_ent,
        "metrics": hit_met,
        "numbers": sorted(_query_numbers(q)),
        "phrases": phrases,
    }


def _text_of(dossier: Dossier) -> dict[str, str]:
    return {
        seg.id: (seg.text or "")
        for src in dossier.sources for seg in src.segments
    }


def _slot_scores(
    facts: list[Fact],
    slots: dict[str, Any],
    text_of: dict[str, str],
    *,
    hop: bool,
    use_text: bool,
) -> dict[str, float]:
    """段级槽分：台账匹配（可选）＋议题短语落在段文（补非数字金标）。"""
    by_seg, _, _ = _build_indexes(facts)
    ent_q = set(slots["entities"])
    met_q = set(slots["metrics"])
    num_q = set(slots["numbers"])
    phrases = list(slots.get("phrases") or [])
    scores: dict[str, float] = defaultdict(float)

    for seg_id, flist in by_seg.items():
        sc = 0.0
        for f in flist:
            if f.entity and f.entity in ent_q:
                sc += 3.0
            if (f.metric and f.metric in met_q) or (
                f.metric_canon and f.metric_canon in met_q
            ):
                sc += 2.0
            if f.raw and f.raw in num_q:
                sc += 4.0
        scores[seg_id] = sc

    if use_text:
        for sid, text in text_of.items():
            if not text:
                continue
            sc = 0.0
            for ph in phrases:
                if ph and ph in text:
                    # 长短语权重更高
                    sc += 1.0 + min(len(ph), 12) / 6.0
            for n in num_q:
                if n and n in text:
                    sc += 2.0
            if sc:
                scores[sid] = float(scores.get(sid, 0.0)) + sc

    if hop and ent_q:
        for f in facts:
            if f.entity and f.entity in ent_q:
                scores[f.seg_id] = float(scores.get(f.seg_id, 0.0)) + 1.5

    return dict(scores)


def _fuse(
    bm25: dict[str, float],
    slot: dict[str, float],
    *,
    mode: str,
    w_slot: float = 1.0,
) -> dict[str, float]:
    all_ids = set(bm25) | set(slot)
    max_b = max((bm25.get(i, 0.0) for i in all_ids), default=0.0) or 1.0
    max_s = max((slot.get(i, 0.0) for i in all_ids), default=0.0) or 1.0
    out: dict[str, float] = {}
    for sid in all_ids:
        b = float(bm25.get(sid, 0.0)) / max_b
        s = float(slot.get(sid, 0.0)) / max_s if max_s else 0.0
        if mode == "slot_only":
            out[sid] = float(slot.get(sid, 0.0))
        elif mode == "bm25_only":
            out[sid] = float(bm25.get(sid, 0.0))
        elif mode == "add":
            out[sid] = w_slot * s + b
        elif mode == "slot_gate":
            # 有槽分的段：槽主导；无槽：仅靠弱 BM25
            if slot.get(sid, 0.0) > 0:
                out[sid] = 1000.0 * s + b
            else:
                out[sid] = b
        else:
            raise ValueError(mode)
    return out


def analyze(c85_dir: Path, gold_dir: Path) -> dict[str, Any]:
    jobs = json.loads((c85_dir / "score_input.json").read_text(encoding="utf-8"))

    # use_text：议题短语落段文（补 63% 无台账金标）；ledger_only＝仅台账
    arm_specs = [
        {"name": "a0", "kind": "a0"},
        {"name": "bm25_pri", "mode": "bm25_only", "w": 0.0, "hop": False, "pack": "pri", "text": False, "ledger": False},
        {"name": "ledger_only", "mode": "slot_only", "w": 0.0, "hop": True, "pack": "pri", "text": False, "ledger": True},
        {"name": "text_only", "mode": "slot_only", "w": 0.0, "hop": False, "pack": "pri", "text": True, "ledger": False},
        {"name": "text_ledger", "mode": "slot_only", "w": 0.0, "hop": True, "pack": "pri", "text": True, "ledger": True},
        {"name": "add_text_w1", "mode": "add", "w": 1.0, "hop": True, "pack": "pri", "text": True, "ledger": True},
        {"name": "add_text_w2", "mode": "add", "w": 2.0, "hop": True, "pack": "pri", "text": True, "ledger": True},
        {"name": "add_text_w3", "mode": "add", "w": 3.0, "hop": True, "pack": "pri", "text": True, "ledger": True},
        {"name": "gate_text", "mode": "slot_gate", "w": 1.0, "hop": True, "pack": "pri", "text": True, "ledger": True},
        {"name": "gate_text_den", "mode": "slot_gate", "w": 1.0, "hop": True, "pack": "den", "text": True, "ledger": True},
    ]

    tot = {a["name"]: Counter() for a in arm_specs}
    rows = []
    slot_stats = Counter()

    for job in jobs:
        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        budget = int(job["budget"])
        query = str(job.get("query") or dossier.question or "")
        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        if denom == 0:
            continue

        facts, st = _scan(dossier)
        _, entities, metrics = _build_indexes(facts)
        slots = _query_slots(query, entities, metrics)
        text_of = _text_of(dossier)
        slot_stats["n_q_ent"] += len(slots["entities"])
        slot_stats["n_q_met"] += len(slots["metrics"])
        slot_stats["n_q_num"] += len(slots["numbers"])
        slot_stats["n_q_phrase"] += len(slots["phrases"])
        slot_stats["n_facts"] += len(facts)
        if slots["entities"] or slots["metrics"] or slots["numbers"] or slots["phrases"]:
            slot_stats["q_with_any_slot"] += 1
        else:
            slot_stats["q_with_no_slot"] += 1

        bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        for src in dossier.sources:
            for seg in src.segments:
                bm25.setdefault(seg.id, 0.0)

        # 缓存两种槽分
        cache_slot: dict[tuple[bool, bool], dict[str, float]] = {}

        def get_slot(hop: bool, use_text: bool, use_ledger: bool) -> dict[str, float]:
            key = (hop, use_text, use_ledger)
            if key not in cache_slot:
                if not use_ledger and not use_text:
                    cache_slot[key] = {}
                else:
                    # 无 ledger 时传空 facts 列表给台账支路
                    fl = facts if use_ledger else []
                    cache_slot[key] = _slot_scores(
                        fl, slots, text_of, hop=hop and use_ledger, use_text=use_text)
            return cache_slot[key]

        p0 = pack_material(dossier, budget_chars=budget)
        sel_a0 = {str(x) for x in (p0.get("selected") or [])}
        loc_a0 = selected_locs(dossier, sel_a0)

        packs: dict[str, set[str]] = {"a0": sel_a0}
        for spec in arm_specs:
            if spec["name"] == "a0":
                continue
            slot = get_slot(bool(spec["hop"]), bool(spec["text"]), bool(spec.get("ledger", True)))
            fused = _fuse(bm25, slot, mode=spec["mode"], w_slot=float(spec["w"]))
            if spec["pack"] == "den":
                packs[spec["name"]] = _pack_with_scores(dossier, budget, fused)
            else:
                packs[spec["name"]] = _pack_score_primary(dossier, budget, fused)

        row: dict[str, Any] = {
            "case": job["case"], "qid": job["qid"], "denom": denom,
            "n_slot_ent": len(slots["entities"]),
            "n_slot_met": len(slots["metrics"]),
            "n_slot_num": len(slots["numbers"]),
            "n_slot_phrase": len(slots["phrases"]),
            "n_facts": len(facts),
            "slot_entities": slots["entities"][:8],
            "slot_metrics": slots["metrics"][:8],
            "slot_phrases": slots["phrases"][:8],
        }
        for name, sel in packs.items():
            loc = selected_locs(dossier, sel)
            hits = l2_hits(gold, loc)
            lost = len((gold & loc_a0) - loc)
            gained = len((gold & loc) - loc_a0)
            row[f"{name}_hits"] = hits
            row[f"{name}_lost"] = lost
            row[f"{name}_gained"] = gained
            row[f"{name}_n"] = len(sel)
            tot[name]["hits"] += hits
            tot[name]["lost"] += lost
            tot[name]["gained"] += gained
            tot[name]["n"] += len(sel)
        tot["a0"]["denom"] += denom
        rows.append(row)

    denom = int(tot["a0"]["denom"])
    a0_hits = int(tot["a0"]["hits"])
    arms_out = {}
    for spec in arm_specs:
        name = spec["name"]
        h = int(tot[name]["hits"])
        lo = int(tot[name]["lost"])
        g = int(tot[name]["gained"])
        arms_out[name] = {
            "l2_hits": h,
            "lost_n": lo,
            "gained_n": g,
            "vs_a0_delta": h - a0_hits,
            "gate_b": h >= TARGET_L2 and lo == 0,
            "mean_n_seg": round(tot[name]["n"] / max(len(rows), 1), 1),
        }

    return {
        "n_questions": len(rows),
        "denom": denom,
        "reproduce_a0_ok": a0_hits == TARGET_A0 and denom == TARGET_DENOM,
        "slot_stats": dict(slot_stats),
        "arms": arms_out,
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--c85-dir", default="/tmp/c85_k180")
    ap.add_argument("--out-dir", default="/tmp/c92_slot")
    ap.add_argument("--gold-dir", default="")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gold = Path(args.gold_dir) if args.gold_dir else DEFAULT_GOLD

    print("======== C-92 事实槽选段只量（零模型）========", flush=True)
    summary = analyze(Path(args.c85_dir), gold)
    print(
        f"复现 A0={summary['arms']['a0']['l2_hits']}/{summary['denom']} "
        f"{'OK' if summary['reproduce_a0_ok'] else 'FAIL'}",
        flush=True,
    )
    print("槽统计:", json.dumps(summary["slot_stats"], ensure_ascii=False), flush=True)
    labels = {
        "a0": "A0 生产密度",
        "bm25_pri": "BM25 分主序",
        "ledger_only": "仅台账槽+1跳",
        "text_only": "仅议题短语落段文",
        "text_ledger": "短语+台账",
        "add_text_w1": "槽文+BM25 w=1",
        "add_text_w2": "槽文+BM25 w=2",
        "add_text_w3": "槽文+BM25 w=3",
        "gate_text": "槽文门控+BM25",
        "gate_text_den": "槽文门控+密度装箱",
    }
    for k, lab in labels.items():
        a = summary["arms"][k]
        g = "过" if a["gate_b"] else "逃逸"
        print(
            f"  {lab}: L2={a['l2_hits']}/{summary['denom']} "
            f"lost={a['lost_n']} gained={a['gained_n']} "
            f"ΔA0={a['vs_a0_delta']:+d} 门槛b={g}",
            flush=True,
        )
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"落盘 {out / 'summary.json'}", flush=True)
    return 0 if summary["reproduce_a0_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
