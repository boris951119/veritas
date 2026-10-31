#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Obsidian KG 混合召回 spike（只量；实验树；不合入主仓）。

召回宇宙＝已进箱段（对齐 C-104）。对照臂：
  ① q_bm25          纯问句 BM25（原文）
  ② summary_bm25    摘要字段 BM25（+关键词拓展）
  ③ embedding       本机 bge-m3
  ④ rrf_bm25_emb    RRF(①∪②∪③)
  ⑤ rrf_plus_hop    ④ + 实体／因果一跳（返回边路径）
  oracle            点名箱内金标（仅对照）

用法（在 veritas-obsidian-kg-exp 根）：
  PYTHONPATH=. .venv/bin/python scripts/kg_lab/probe_kg_spike_recall.py \\
      --case-filter 刘翔 --out-dir /tmp/kg_spike_recall
  # 跳过摘要／向量重建（用缓存）：
  ... --skip-summarize --skip-embed
  # 冒烟：每案最多摘要 N 段
  ... --summary-limit 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.config import (  # noqa: E402
    DEFAULT_K,
    DEFAULT_SAMPLES,
    SUMMARY_WORKERS,
    WIDE_K,
)
from app.kg_lab.eval_metrics import (  # noqa: E402
    leak_check,
    measure_arm,
    relative_deltas,
)
from app.kg_lab.graph import build_graph_from_summaries  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.recall_arms import run_all_arms  # noqa: E402
from app.kg_lab.slices import (  # noqa: E402
    ingest_case_slices,
    pack_selected_for_question,
    union_pack_ids,
)
from app.kg_lab.summarize import summarize_paras  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402


def _ids_at_k(pick: dict[str, Any], k: int) -> list[str]:
    return [str(x["para_id"]) for x in (pick.get("picked") or [])[:k]]


def hop_vs_rrf_diag(
    hop_pick: dict[str, Any],
    rrf_pick: dict[str, Any],
    *,
    gold_l2: set[str],
    k: int,
) -> dict[str, Any]:
    """R1 报表：n_hop_added／gold_via_hop／与 RRF 的对称差。"""
    rrf_ids = _ids_at_k(rrf_pick, k)
    hop_ids = _ids_at_k(hop_pick, k)
    rrf_set, hop_set = set(rrf_ids), set(hop_ids)
    # 优先用臂内显式 hop_added（相对 RRF Top-k）；再按集合差兜底
    explicit = [str(x) for x in (hop_pick.get("hop_added_ids") or []) if str(x) in hop_set]
    if not explicit:
        explicit = sorted(hop_set - rrf_set)
    # 截到本 k 窗口内实际入选的 hop
    hop_in_topk = [pid for pid in explicit if pid in hop_set][:k]
    gold_via = sorted(set(hop_in_topk) & gold_l2)
    return {
        "k": k,
        "n_hop_added": len(hop_in_topk),
        "hop_added_ids": hop_in_topk,
        "gold_via_hop": gold_via,
        "n_gold_via_hop": len(gold_via),
        "picked_equal_rrf": hop_ids == rrf_ids,
        "symdiff": sorted(rrf_set ^ hop_set),
        "only_in_hop": sorted(hop_set - rrf_set),
        "only_in_rrf": sorted(rrf_set - hop_set),
        "swapped_out_ids": list(hop_pick.get("swapped_out_ids") or [])[:k],
        "hop_quota": hop_pick.get("hop_quota"),
        "n_hop_candidates": hop_pick.get("n_hop_candidates"),
    }


def _case_dirs(samples: Path, case_filter: str | None) -> list[Path]:
    dirs = sorted(
        p for p in samples.iterdir()
        if p.is_dir() and (p / "raw_documents.json").is_file()
    )
    if case_filter:
        dirs = [p for p in dirs if case_filter in p.name]
    return dirs


def _slug(case_dir: Path) -> str:
    # 文件系统友好短名
    name = case_dir.name
    for a, b in [
        ("刘翔编制“二选一”事件", "liuxiang"),
        ("王虹“北大discouraged”事件", "wanghong"),
        ("中美AI事故预警提议（2026.9）", "us_cn_ai"),
        ("印度航空 AI171 空难（2025.6–2026.5）", "ai171"),
        ("柬泰边境争端（2025.12–2026.9）", "kh_th"),
        ("2026·8·26 吉隆口岸泥石流灾害", "jilong"),
    ]:
        if name == a or a in name:
            return b
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40]


def run_case(
    case_dir: Path,
    *,
    out_dir: Path,
    k: int,
    wide_k: int,
    skip_summarize: bool,
    skip_embed: bool,
    summary_limit: int | None,
    workers: int,
    force_summary: bool,
) -> dict[str, Any]:
    slug = _slug(case_dir)
    print(f"\n=== case {case_dir.name} slug={slug} ===", flush=True)
    t_case = time.perf_counter()
    dossier, union_ids, questions = union_pack_ids(case_dir)
    print(f"  union_pack={len(union_ids)} questions={len(questions)}", flush=True)

    # 1) slices
    t0 = time.perf_counter()
    slice_meta = ingest_case_slices(case_dir, only_para_ids=union_ids, case_slug=slug)
    print(f"  slices written={slice_meta['n_written']} wall={time.perf_counter()-t0:.1f}s", flush=True)

    # 2) summaries
    sum_meta: dict[str, Any]
    if skip_summarize:
        sum_meta = {"skipped": True}
        print("  summarize skipped", flush=True)
    else:
        print(f"  summarize workers={workers} limit={summary_limit}", flush=True)
        sum_meta = summarize_paras(
            dossier, case_slug=slug, para_ids=union_ids,
            workers=workers, force=force_summary, limit=summary_limit,
        )
        print(f"  summarize done {sum_meta}", flush=True)

    # 3) graph
    t0 = time.perf_counter()
    graph_meta = build_graph_from_summaries(slug)
    print(
        f"  graph entities={graph_meta.get('n_entities')} "
        f"edges={graph_meta.get('n_edges')} wall={time.perf_counter()-t0:.1f}s",
        flush=True,
    )

    # 4) index + embeddings（宇宙＝并集；评测时再按题裁剪）
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union_ids)
    index = KgIndex(slug, rows)
    index.save_meta()
    if skip_embed:
        emb_meta = {"skipped": True}
        # 仍尝试加载缓存
        try:
            index.ensure_embeddings(force=False)
            emb_meta = {"skipped": True, "n_vectors": len(index.embeddings)}
        except Exception as e:  # noqa: BLE001
            emb_meta = {"skipped": True, "error": str(e)}
        print(f"  embed skipped/load {emb_meta}", flush=True)
    else:
        print("  embedding…", flush=True)
        emb_meta = index.ensure_embeddings(force=False)
        print(f"  embed {emb_meta}", flush=True)

    # 5) per-question arms
    q_rows: list[dict[str, Any]] = []
    for qrow in questions:
        qid = qrow["question_id"]
        question = qrow["question"]
        gold, skipped = gold_paras_for_question(case_dir, qid)
        universe = pack_selected_for_question(dossier, question)
        gold_paras = {p for _d, p in gold}
        l2 = {p for _d, p in gold if p in universe}
        print(
            f"  — {qid} gold={len(gold)} L2={len(l2)} pack={len(universe)} "
            f"skip_locator={skipped}",
            flush=True,
        )
        t0 = time.perf_counter()
        # 索引宇宙裁剪：只在本题箱内排
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub_index = KgIndex(slug, sub_rows)
        sub_index.embeddings = {
            pid: vec for pid, vec in index.embeddings.items() if pid in universe
        }
        # hop 配额随 k 变：@7 与 @15 须各自组名单（不可用 wide 截前 k）
        arms_k = run_all_arms(
            sub_index, question, k=k, universe=universe,
            case_slug=slug, gold_para_ids=l2, include_oracle=True,
        )
        arms_wide = run_all_arms(
            sub_index, question, k=wide_k, universe=universe,
            case_slug=slug, gold_para_ids=l2, include_oracle=True,
        )
        wall = round(time.perf_counter() - t0, 3)
        metrics_k: dict[str, Any] = {}
        metrics_wide: dict[str, Any] = {}
        leaks: dict[str, Any] = {}
        for name, pick in arms_k.items():
            metrics_k[name] = measure_arm(
                pick, gold=gold, universe=universe, miss_ids=None, k=k,
            )
            leaks[name] = leak_check(pick, gold=gold)
        for name, pick in arms_wide.items():
            metrics_wide[name] = measure_arm(
                pick, gold=gold, universe=universe, miss_ids=None, k=wide_k,
            )
            # 泄漏以 @k 查询为准；wide 再验一次
            lk_w = leak_check(pick, gold=gold)
            if not lk_w.get("ok"):
                leaks[f"{name}@wide"] = lk_w
        deltas = relative_deltas(metrics_k)
        hop_diag_k = hop_vs_rrf_diag(
            arms_k["rrf_plus_hop"], arms_k["rrf_bm25_emb"], gold_l2=l2, k=k,
        )
        hop_diag_wide = hop_vs_rrf_diag(
            arms_wide["rrf_plus_hop"], arms_wide["rrf_bm25_emb"],
            gold_l2=l2, k=wide_k,
        )
        arms = arms_k  # arms_raw 主存 @k；wide hop 明细另挂
        leak_fail = [n for n, lk in leaks.items() if not lk.get("ok")]
        q_rows.append({
            "case": case_dir.name,
            "slug": slug,
            "qid": qid,
            "question": question,
            "denom_gold": len(gold),
            "n_l2": len(l2),
            "n_pack": len(universe),
            "wall_s": wall,
            "metrics_at_k": metrics_k,
            "metrics_at_wide_k": metrics_wide,
            "leak_checks": leaks,
            "leak_fail_arms": leak_fail,
            "deltas_vs_baseline": deltas,
            "hop_diag_at_k": hop_diag_k,
            "hop_diag_at_wide_k": hop_diag_wide,
            "arms_raw": {
                name: {
                    "picked": pick.get("picked"),
                    "queries": pick.get("queries"),
                    "paths": pick.get("paths") if name == "rrf_plus_hop" else {},
                    "selection_used_gold": pick.get("selection_used_gold"),
                    "n_hop_added": pick.get("n_hop_added"),
                    "hop_added_ids": pick.get("hop_added_ids"),
                    "swapped_out_ids": pick.get("swapped_out_ids"),
                    "hop_quota": pick.get("hop_quota"),
                }
                for name, pick in arms_k.items()
            },
            "arms_raw_wide": {
                "rrf_bm25_emb": {
                    "picked": arms_wide["rrf_bm25_emb"].get("picked"),
                },
                "rrf_plus_hop": {
                    "picked": arms_wide["rrf_plus_hop"].get("picked"),
                    "n_hop_added": arms_wide["rrf_plus_hop"].get("n_hop_added"),
                    "hop_added_ids": arms_wide["rrf_plus_hop"].get("hop_added_ids"),
                    "swapped_out_ids": arms_wide["rrf_plus_hop"].get("swapped_out_ids"),
                    "hop_quota": arms_wide["rrf_plus_hop"].get("hop_quota"),
                    "paths": arms_wide["rrf_plus_hop"].get("paths"),
                },
            },
        })
        # 行摘要
        for name in ("q_bm25", "summary_bm25", "embedding", "rrf_bm25_emb",
                     "rrf_plus_hop", "oracle"):
            m = metrics_k[name]
            lk = leaks[name]
            print(
                f"    {name:14} hit={m['n_gold_hit']}/{m['n_l2_gold']} "
                f"recall@k={m['recall_at_k']} seen_not={m['n_seen_not']} "
                f"leak_ok={lk['ok']}",
                flush=True,
            )
        print(
            f"    hop@k  n_hop_added={hop_diag_k['n_hop_added']} "
            f"gold_via_hop={hop_diag_k['n_gold_via_hop']} "
            f"equal_rrf={hop_diag_k['picked_equal_rrf']} "
            f"|symdiff|={len(hop_diag_k['symdiff'])}",
            flush=True,
        )
        if leak_fail:
            raise RuntimeError(
                f"leak check failed qid={qid} arms={leak_fail}; stop"
            )

    # 案级汇总
    def _sum_hit(arm: str) -> tuple[int, int]:
        h = sum(r["metrics_at_k"][arm]["n_gold_hit"] for r in q_rows)
        d = sum(r["metrics_at_k"][arm]["n_l2_gold"] for r in q_rows)
        return h, d

    summary_arms = {}
    for arm in ("q_bm25", "summary_bm25", "embedding", "rrf_bm25_emb",
                "rrf_plus_hop", "oracle"):
        h, d = _sum_hit(arm)
        summary_arms[arm] = {
            "n_gold_hit": h,
            "n_l2": d,
            "recall_at_k": round(h / d, 4) if d else None,
        }
    b = summary_arms["q_bm25"]["n_gold_hit"]
    o = summary_arms["oracle"]["n_gold_hit"]
    for arm, block in summary_arms.items():
        block["delta_vs_q_bm25"] = block["n_gold_hit"] - b
        block["delta_vs_oracle"] = block["n_gold_hit"] - o
        block["gap_to_oracle"] = o - block["n_gold_hit"]

    leak_any = any(
        (not lk.get("ok"))
        for r in q_rows
        for lk in r["leak_checks"].values()
    )
    hop_sum_k = {
        "n_hop_added": sum(r["hop_diag_at_k"]["n_hop_added"] for r in q_rows),
        "n_gold_via_hop": sum(r["hop_diag_at_k"]["n_gold_via_hop"] for r in q_rows),
        "n_q_equal_rrf": sum(
            1 for r in q_rows if r["hop_diag_at_k"]["picked_equal_rrf"]
        ),
        "n_q_diff_rrf": sum(
            1 for r in q_rows if not r["hop_diag_at_k"]["picked_equal_rrf"]
        ),
        "gold_via_hop_ids": sorted({
            gid
            for r in q_rows
            for gid in r["hop_diag_at_k"]["gold_via_hop"]
        }),
    }
    hop_sum_wide = {
        "n_hop_added": sum(r["hop_diag_at_wide_k"]["n_hop_added"] for r in q_rows),
        "n_gold_via_hop": sum(
            r["hop_diag_at_wide_k"]["n_gold_via_hop"] for r in q_rows
        ),
        "n_q_equal_rrf": sum(
            1 for r in q_rows if r["hop_diag_at_wide_k"]["picked_equal_rrf"]
        ),
        "n_q_diff_rrf": sum(
            1 for r in q_rows if not r["hop_diag_at_wide_k"]["picked_equal_rrf"]
        ),
        "gold_via_hop_ids": sorted({
            gid
            for r in q_rows
            for gid in r["hop_diag_at_wide_k"]["gold_via_hop"]
        }),
    }
    # @15 hit 汇总（对照用）
    summary_arms_wide = {}
    for arm in ("q_bm25", "summary_bm25", "embedding", "rrf_bm25_emb",
                "rrf_plus_hop", "oracle"):
        h = sum(r["metrics_at_wide_k"][arm]["n_gold_hit"] for r in q_rows)
        d = sum(r["metrics_at_wide_k"][arm]["n_l2_gold"] for r in q_rows)
        summary_arms_wide[arm] = {
            "n_gold_hit": h,
            "n_l2": d,
            "recall_at_k": round(h / d, 4) if d else None,
        }
    case_out = {
        "case": case_dir.name,
        "slug": slug,
        "k": k,
        "wide_k": wide_k,
        "union_pack": len(union_ids),
        "slice_meta": {"n_written": slice_meta["n_written"]},
        "summarize": sum_meta,
        "graph": graph_meta,
        "embed": emb_meta,
        "questions": q_rows,
        "summary_arms_at_k": summary_arms,
        "summary_arms_at_wide_k": summary_arms_wide,
        "hop_summary_at_k": hop_sum_k,
        "hop_summary_at_wide_k": hop_sum_wide,
        "leak_any_bad": leak_any,
        "wall_s": round(time.perf_counter() - t_case, 3),
        "revision": "R1-hop-quota",
    }
    out_path = out_dir / f"case_{slug}.json"
    out_path.write_text(json.dumps(case_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {out_path}", flush=True)
    return case_out


def main() -> int:
    ap = argparse.ArgumentParser(description="KG hybrid recall spike (box-only)")
    ap.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    ap.add_argument("--case-filter", type=str, default="刘翔",
                    help="子串过滤案名；空字符串＝六案全跑")
    ap.add_argument("--out-dir", type=Path, default=Path("/tmp/kg_spike_recall"))
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--wide-k", type=int, default=WIDE_K)
    ap.add_argument("--skip-summarize", action="store_true")
    ap.add_argument("--skip-embed", action="store_true")
    ap.add_argument("--force-summary", action="store_true")
    ap.add_argument("--summary-limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=SUMMARY_WORKERS)
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    filt = args.case_filter if args.case_filter != "" else None
    cases = _case_dirs(args.samples, filt)
    if not cases:
        print(f"no cases under {args.samples} filter={args.case_filter!r}", file=sys.stderr)
        return 2

    t0 = time.perf_counter()
    case_results = []
    for c in cases:
        case_results.append(run_case(
            c,
            out_dir=out_dir,
            k=args.k,
            wide_k=args.wide_k,
            skip_summarize=args.skip_summarize,
            skip_embed=args.skip_embed,
            summary_limit=args.summary_limit,
            workers=args.workers,
            force_summary=args.force_summary,
        ))

    # 总表
    arms = ["q_bm25", "summary_bm25", "embedding", "rrf_bm25_emb", "rrf_plus_hop", "oracle"]
    table = []
    for arm in arms:
        h = sum(r["summary_arms_at_k"][arm]["n_gold_hit"] for r in case_results)
        d = sum(r["summary_arms_at_k"][arm]["n_l2"] for r in case_results)
        table.append({
            "arm": arm,
            "n_gold_hit": h,
            "n_l2": d,
            "recall_at_k": round(h / d, 4) if d else None,
            "delta_vs_q_bm25": h - sum(
                r["summary_arms_at_k"]["q_bm25"]["n_gold_hit"] for r in case_results
            ),
            "gap_to_oracle": sum(
                r["summary_arms_at_k"]["oracle"]["n_gold_hit"] for r in case_results
            ) - h,
        })

    table_wide = []
    for arm in arms:
        h = sum(
            (r.get("summary_arms_at_wide_k") or {}).get(arm, {}).get("n_gold_hit") or 0
            for r in case_results
        )
        d = sum(
            (r.get("summary_arms_at_wide_k") or {}).get(arm, {}).get("n_l2") or 0
            for r in case_results
        )
        table_wide.append({
            "arm": arm,
            "n_gold_hit": h,
            "n_l2": d,
            "recall_at_k": round(h / d, 4) if d else None,
        })

    hop_k = {
        "n_hop_added": sum(
            (r.get("hop_summary_at_k") or {}).get("n_hop_added") or 0
            for r in case_results
        ),
        "n_gold_via_hop": sum(
            (r.get("hop_summary_at_k") or {}).get("n_gold_via_hop") or 0
            for r in case_results
        ),
        "n_q_equal_rrf": sum(
            (r.get("hop_summary_at_k") or {}).get("n_q_equal_rrf") or 0
            for r in case_results
        ),
        "n_q_diff_rrf": sum(
            (r.get("hop_summary_at_k") or {}).get("n_q_diff_rrf") or 0
            for r in case_results
        ),
        "gold_via_hop_ids": sorted({
            gid
            for r in case_results
            for gid in ((r.get("hop_summary_at_k") or {}).get("gold_via_hop_ids") or [])
        }),
    }
    hop_wide = {
        "n_hop_added": sum(
            (r.get("hop_summary_at_wide_k") or {}).get("n_hop_added") or 0
            for r in case_results
        ),
        "n_gold_via_hop": sum(
            (r.get("hop_summary_at_wide_k") or {}).get("n_gold_via_hop") or 0
            for r in case_results
        ),
        "n_q_equal_rrf": sum(
            (r.get("hop_summary_at_wide_k") or {}).get("n_q_equal_rrf") or 0
            for r in case_results
        ),
        "n_q_diff_rrf": sum(
            (r.get("hop_summary_at_wide_k") or {}).get("n_q_diff_rrf") or 0
            for r in case_results
        ),
        "gold_via_hop_ids": sorted({
            gid
            for r in case_results
            for gid in (
                (r.get("hop_summary_at_wide_k") or {}).get("gold_via_hop_ids") or []
            )
        }),
    }

    leak_any = any(r["leak_any_bad"] for r in case_results)
    report = {
        "ticket": "obsidian-kg-hybrid-recall-spike",
        "revision": "R1-hop-quota",
        "align": "C-104 box-only universe; no gold leak into query/features",
        "k": args.k,
        "wide_k": args.wide_k,
        "cases": [r["case"] for r in case_results],
        "n_cases": len(case_results),
        "table_at_k": table,
        "table_at_wide_k": table_wide,
        "hop_at_k": hop_k,
        "hop_at_wide_k": hop_wide,
        "picked_equal_rrf_all_q_at_k": hop_k["n_q_diff_rrf"] == 0,
        "leak_any_bad": leak_any,
        "wall_s": round(time.perf_counter() - t0, 3),
        "paths": {
            "exp_root": str(ROOT),
            "vault": str(ROOT / "vaults" / "kg-lab"),
            "artifacts": str(ROOT / "artifacts" / "kg-index"),
            "baseline_r0": str(
                ROOT / "artifacts" / "kg-index" / "baseline_r0_liuxiang"
            ),
            "out_dir": str(out_dir),
            "samples": str(args.samples),
        },
        "per_case_files": [f"case_{r['slug']}.json" for r in case_results],
    }
    if leak_any:
        (out_dir / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print("LEAK FAIL — stop", flush=True)
        return 3

    for name in ("summary.json", "r1_summary.json"):
        (out_dir / name).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    # markdown 对照表
    lines = [
        "# KG hybrid recall spike — R1",
        "",
        f"- revision=R1-hop-quota（`arm_rrf_hop`：Top-k 预留 hop_quota≈k//3）",
        f"- k={args.k} wide_k={args.wide_k}",
        f"- cases={report['cases']}",
        f"- wall_s={report['wall_s']}",
        f"- leak_any_bad={report['leak_any_bad']}",
        f"- @7：n_hop_added={hop_k['n_hop_added']} gold_via_hop={hop_k['n_gold_via_hop']} "
        f"q_diff_vs_rrf={hop_k['n_q_diff_rrf']}/{len(case_results)} "
        f"（equal_all={report['picked_equal_rrf_all_q_at_k']}）",
        f"- @15：n_hop_added={hop_wide['n_hop_added']} "
        f"gold_via_hop={hop_wide['n_gold_via_hop']} "
        f"q_diff_vs_rrf={hop_wide['n_q_diff_rrf']}",
        "",
        "## @K=7",
        "",
        "| arm | hit/L2 | recall@k | Δ vs ① | gap→oracle |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in table:
        lines.append(
            f"| {row['arm']} | {row['n_gold_hit']}/{row['n_l2']} | "
            f"{row['recall_at_k']} | {row['delta_vs_q_bm25']:+d} | "
            f"{row['gap_to_oracle']} |"
        )
    lines += [
        "",
        "## @K=15",
        "",
        "| arm | hit/L2 | recall@15 |",
        "|---|---:|---:|",
    ]
    for row in table_wide:
        lines.append(
            f"| {row['arm']} | {row['n_gold_hit']}/{row['n_l2']} | "
            f"{row['recall_at_k']} |"
        )
    lines += [
        "",
        "## Hop 上场证据",
        f"- gold_via_hop@7 ids: {hop_k['gold_via_hop_ids']}",
        f"- gold_via_hop@15 ids: {hop_wide['gold_via_hop_ids']}",
        "",
        "## Paths",
        f"- exp: `{report['paths']['exp_root']}`",
        f"- baseline_r0: `{report['paths']['baseline_r0']}`",
        f"- out: `{report['paths']['out_dir']}`",
        "",
    ]
    table_body = "\n".join(lines)
    (out_dir / "TABLE.md").write_text(table_body, encoding="utf-8")
    (out_dir / "r1_TABLE.md").write_text(table_body, encoding="utf-8")
    print("\n" + table_body, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
