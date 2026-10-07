#!/usr/bin/env python3
"""赛题评测集出数：BM25 Recall@K · 冲突召回 · 编造检出率。

用法：
  .venv/bin/python scripts/run_eval.py
  .venv/bin/python scripts/run_eval.py --json dist/eval-report.json

设计（诚实边界）：
- 检索 / 编造：走生产路径（BM25、引文核对），零 LLM，可复现；
- 冲突：生产环境开放域冲突由 LLM 检出；本脚本对标注对立对做
  **机械对立词典召回**（可复现），并可选核对证据加权是否偏向金标胜方。
  不把 LLM 冲突检出计入本报告，避免网关波动污染数字。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.bm25 import rank_segments
from app.core.citation_check import check_quote
from app.core.conflicts import ConflictPair, compute_evidence_weight, validate_conflict
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    RelationKind,
)
from app.ingest.case_loader import load_case

_BENCH = _ROOT / "eval" / "benchmark.jsonl"

# 对立信号：一侧命中 left、另一侧命中 right（或反过来）即视为机械检出冲突
_OPPOSITIONS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("停工", "遣散", "资金链断裂"), ("不实", "仍按计划", "运转", "核查")),
    (("量产", "中试", "装车", "路测"), ("看不到", "融资叙事", "不可复现", "无根本解法")),
    (("健康", "可控", "按时"), ("风险", "逾期", "坏账", "纠纷", "偏差", "高风险")),
    (("不能替代", "官方核查"), ("全面停工", "未提供可核验")),
]


def _load_items() -> list[dict]:
    rows = []
    for line in _BENCH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def _with_question(dossier: Dossier, question: str) -> Dossier:
    return replace(dossier, question=question)


def _hits_opposition(a: str, b: str) -> bool:
    for left, right in _OPPOSITIONS:
        a_l = any(k in a for k in left)
        a_r = any(k in a for k in right)
        b_l = any(k in b for k in left)
        b_r = any(k in b for k in right)
        if (a_l and b_r) or (a_r and b_l):
            return True
    return False


def _attach_pair(dossier: Dossier, side: dict, author: str, cid: str) -> None:
    con = Conclusion.create(side["statement"], author=author, id=cid)
    dossier.conclusions.append(con)
    quote = side["quote"]
    seg_id = side["seg"]
    seg = dossier.segment(seg_id)
    if seg is None:
        raise AssertionError(f"段落不存在: {seg_id}")
    ok = check_quote(quote, seg.text).ok
    if not ok:
        raise AssertionError(f"金标引文未命中段落 {seg_id}: {quote!r}")
    dossier.add_evidence(EvidenceNode.create(
        cid, quote, [seg_id],
        level=EvidenceLevel.B,
        relation=RelationKind.CORRELATION,
        note="eval-gold",
    ))


def eval_retrieval(item: dict, get_case) -> dict:
    d = _with_question(get_case(item["case"]), item["question"])
    ranked = [sid for sid, _ in rank_segments(d)]
    k = int(item.get("top_k") or 5)
    top = set(ranked[:k])
    gold = set(item["gold_segments"])
    hit = bool(gold & top)
    return {
        "id": item["id"], "ok": hit,
        "top": ranked[:k], "gold": sorted(gold),
        "hit_segments": sorted(gold & top),
        "note": item.get("note") or "",
    }


def eval_conflict(item: dict, get_case) -> dict:
    base = get_case(item["case"])
    d = Dossier(question=base.question, sources=list(base.sources),
                conclusions=[], evidences=[], conflicts=[])
    _attach_pair(d, item["a"], "analyst_a", "CON-A")
    _attach_pair(d, item["b"], "analyst_b", "CON-B")
    pair = ConflictPair(a_id="CON-A", b_id="CON-B", topic="eval",
                        description="benchmark")
    problems = validate_conflict(pair, d)
    detected = _hits_opposition(item["a"]["statement"], item["b"]["statement"])
    should = bool(item["should_conflict"])
    # 召回视角：应冲突且检出 = TP；应冲突未检出 = FN
    tp = should and detected
    fn = should and not detected
    fp = (not should) and detected
    tn = (not should) and not detected
    prefer = item.get("prefer_winner")
    winner_ok = None
    if prefer and not problems:
        weights = compute_evidence_weight(pair, d)
        wa, wb = weights.get("CON-A", 0.0), weights.get("CON-B", 0.0)
        predicted = "a" if wa >= wb else "b"
        winner_ok = predicted == prefer
    return {
        "id": item["id"], "should": should, "detected": detected,
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "validate_ok": not problems, "problems": problems,
        "winner_ok": winner_ok, "prefer_winner": prefer,
        "note": item.get("note") or "",
    }


def eval_fabrication(item: dict, get_case) -> dict:
    d = get_case(item["case"])
    seg = d.segment(item["seg"])
    if seg is None:
        raise AssertionError(f"段落不存在: {item['seg']}")
    rejected = not check_quote(item["quote"], seg.text).ok
    expect = bool(item["expect_reject"])
    # 检出率：期望拒绝且确实拒绝
    correct = rejected == expect
    return {
        "id": item["id"], "rejected": rejected, "expect_reject": expect,
        "correct": correct,
        "tp": expect and rejected,
        "fn": expect and not rejected,
        "fp": (not expect) and rejected,
        "tn": (not expect) and not rejected,
    }


def summarize(items: list[dict], get_case) -> dict:
    ret, cfl, fab = [], [], []
    for it in items:
        kind = it["kind"]
        if kind == "retrieval":
            ret.append(eval_retrieval(it, get_case))
        elif kind == "conflict":
            cfl.append(eval_conflict(it, get_case))
        elif kind == "fabrication":
            fab.append(eval_fabrication(it, get_case))
        else:
            raise ValueError(f"unknown kind: {kind}")

    def _rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    ret_hits = sum(1 for r in ret if r["ok"])
    cfl_tp = sum(1 for r in cfl if r["tp"])
    cfl_fn = sum(1 for r in cfl if r["fn"])
    cfl_fp = sum(1 for r in cfl if r["fp"])
    fab_tp = sum(1 for r in fab if r["tp"])
    fab_fn = sum(1 for r in fab if r["fn"])
    fab_fp = sum(1 for r in fab if r["fp"])
    fab_tn = sum(1 for r in fab if r["tn"])
    prefer_rows = [r for r in cfl if r["winner_ok"] is not None]
    prefer_ok = sum(1 for r in prefer_rows if r["winner_ok"])

    metrics = {
        "n_items": len(items),
        "bm25_recall_at_k": _rate(ret_hits, len(ret)),
        "bm25_hits": ret_hits,
        "bm25_n": len(ret),
        "conflict_recall": _rate(cfl_tp, cfl_tp + cfl_fn),
        "conflict_precision": _rate(cfl_tp, cfl_tp + cfl_fp),
        "conflict_tp_fn_fp": {"tp": cfl_tp, "fn": cfl_fn, "fp": cfl_fp},
        "evidence_prefer_gold_rate": _rate(prefer_ok, len(prefer_rows)),
        "fabrication_detection_rate": _rate(fab_tp, fab_tp + fab_fn),
        "fabrication_false_positive_rate": _rate(fab_fp, fab_fp + fab_tn),
        "fabrication_accuracy": _rate(
            sum(1 for r in fab if r["correct"]), len(fab)),
    }
    return {
        "metrics": metrics,
        "retrieval": ret,
        "conflict": cfl,
        "fabrication": fab,
        "method_notes": {
            "retrieval": "生产 BM25 rank_segments；命中=金标段落入 Top-K",
            "conflict": "机械对立词典召回（非 LLM）；另报证据加权偏向金标胜方比例",
            "fabrication": "生产 check_quote；期望拒绝且拒绝=检出",
        },
    }


def _print_human(report: dict) -> None:
    m = report["metrics"]
    print("=== veritas 评测集（零 LLM）===")
    print(f"条目数: {m['n_items']}")
    print(f"BM25 Recall@K     : {m['bm25_recall_at_k']}  "
          f"({m['bm25_hits']}/{m['bm25_n']})")
    print(f"冲突召回率         : {m['conflict_recall']}  "
          f"tp/fn/fp={m['conflict_tp_fn_fp']}")
    print(f"冲突精确率         : {m['conflict_precision']}")
    print(f"证据偏向金标胜方   : {m['evidence_prefer_gold_rate']}")
    print(f"编造检出率         : {m['fabrication_detection_rate']}")
    print(f"编造误杀率(FPR)    : {m['fabrication_false_positive_rate']}")
    print(f"编造总体准确率     : {m['fabrication_accuracy']}")
    misses = [r for r in report["retrieval"] if not r["ok"]]
    if misses:
        print("\n检索未命中:")
        for r in misses:
            print(f"  - {r['id']}: gold={r['gold']} top={r['top']}"
                  + (f"  # {r['note']}" if r["note"] else ""))
    cfl_miss = [r for r in report["conflict"] if r["fn"] or r["fp"]]
    if cfl_miss:
        print("\n冲突误判:")
        for r in cfl_miss:
            print(f"  - {r['id']}: should={r['should']} detected={r['detected']}"
                  + (f"  # {r['note']}" if r["note"] else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None,
                    help="写入 JSON 报告路径")
    args = ap.parse_args()
    # case_cache 返回 getter
    cache: dict[str, Dossier] = {}

    def get_case(name: str) -> Dossier:
        if name not in cache:
            cache[name] = load_case(_ROOT / "cases" / name)
        return cache[name]

    report = summarize(_load_items(), get_case)
    _print_human(report)
    out = args.json or (_ROOT / "dist" / "eval-report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nJSON → {out}")
    # 桌面副本方便交件
    desk = Path.home() / "Desktop" / "veritas-eval-report.json"
    desk.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"桌面 → {desk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
