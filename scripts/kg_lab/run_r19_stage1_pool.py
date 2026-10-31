#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R19：一筛进池评测。主尺＝金标进池20／50；次尺＝@4/@5/@7。

刘翔回归＋吉隆／中美AI 冒烟。二筛仍用 inbox_rerank。默认本地规则视图；
VERITAS_R19_LLM_VIEWS=1 时加 14B 改写。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.config import DEFAULT_K  # noqa: E402
from app.kg_lab.event_frame import extract_event_frame  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.inbox_rerank import inbox_rerank  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features  # noqa: E402
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

OUT = ROOT / "artifacts"
SAMPLES = Path("/Users/liuboyu/Desktop/veritas-testcases/样例集-拓尔思-20261012")
POOLS = (20, 50)
KS = (4, 5, 7)
CASES = (
    ("liuxiang", "刘翔", True),   # train / prefer_gold_cluster
    ("jilong", "吉隆", False),
    ("us_cn_ai", "中美AI", False),
)


def _case(mark: str, *, prefer_local: bool = False) -> Path:
    roots = []
    if prefer_local:
        roots.append(ROOT / "data" / "trs-samples")
    roots.append(SAMPLES)
    for root in roots:
        if not root.is_dir():
            continue
        hits = [
            p for p in root.iterdir()
            if p.is_dir() and mark in p.name and (p / "raw_documents.json").is_file()
        ]
        if len(hits) == 1:
            return hits[0]
    raise SystemExit(f"case {mark} not found")


def _coeff_names() -> tuple[dict[str, float], tuple[str, ...]]:
    r9 = json.loads((OUT / "R9_refine_buckets.json").read_text(encoding="utf-8"))
    names = R9_ADDED + tuple(n for n in r9_names(FEATURE_NAMES) if n not in R9_ADDED)
    coeff = {n: float(r9["coeff"].get(n) or 0.0) for n in names}
    for n in names:
        coeff.setdefault(n, 0.0)
    # 新特征写入披露／进池侧；排序系数保持 0，避免搅乱 R9 已拟合序
    coeff.setdefault("frame_align", 0.0)
    coeff.setdefault("authority_unit", 0.0)
    coeff.setdefault("has_time_nail", 0.0)
    names = names + tuple(n for n in ("frame_align", "authority_unit", "has_time_nail") if n not in names)
    return coeff, names


def _rank_map(ranked: list[tuple[str, float]]) -> dict[str, int]:
    return {pid: i for i, (pid, _) in enumerate(ranked, 1)}


def _eval_case(
    slug: str,
    case: Path,
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    prefer_gold: bool,
    use_llm_views: bool,
    baseline_fuse: bool,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    print(f"=== {slug} {case.name} llm_views={use_llm_views} ===", flush=True)
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    url_of = {
        str(d.get("doc_id")): str(d.get("content_url") or "")
        for d in json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    }
    q_out = []
    pool_hits = {str(p): 0 for p in POOLS}
    gold_total = 0
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, skipped = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        missed_pack = sorted(p for _d, p in gold if p not in universe)
        gold_total += len(l2)
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}

        if baseline_fuse:
            fused, queries, _pm, _n = _fuse_rrf(sub, question)
            submit_ranked = fused
            pool_ranked = fused
            fuse_meta = {"mode": "r12_classic", "n_neighbor_added": 0, "n_view_fill": 0, "views": []}
        else:
            fr = fuse_r19(sub, question, use_llm_views=use_llm_views, neighbor_window=1)
            submit_ranked = fr["ranked"]
            pool_ranked = fr.get("pool_ranked") or fr["ranked"]
            fuse_meta = {
                "mode": "r19",
                "n_neighbor_added": fr["n_neighbor_added"],
                "n_view_fill": fr.get("n_view_fill", 0),
                "views": fr["views"],
                "frame": fr["frame"],
            }

        frame = extract_event_frame(question)
        prefer = set(l2) if prefer_gold else None
        bundle = build_bundle(
            sub_rows, submit_ranked, question, frames=True,
            prefer_ids=prefer, case_slug=slug,
        )
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        apply_portable_features(bundle["feats"], bundle["metas"], url_of, question, frame)
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2

        # 交卷排序：经典 RRF + R9（与 R12／R17 同路径）
        stage1 = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)
        ranked = stage1["ranked"][qid]
        # 进池率：看 pool_ranked（经典头＋视图／邻块填尾）
        pool_pos = _rank_map(pool_ranked)

        pool_stats = {}
        for p in POOLS:
            in_p = [g for g in l2 if pool_pos.get(g, 10**9) <= p]
            pool_hits[str(p)] += len(in_p)
            pool_stats[str(p)] = {
                "hits": len(in_p),
                "gold_total": len(l2),
                "hit_ids": in_p,
                "miss_ids": [
                    {"id": g, "stage1_rank": pool_pos.get(g)}
                    for g in l2 if pool_pos.get(g, 10**9) > p
                ],
            }

        texts = {pid: str((bundle["metas"].get(pid) or {}).get("text") or "") for pid, _ in ranked[:20]}
        out = inbox_rerank(
            ranked, texts=texts, feats=bundle["feats"], metas=bundle["metas"],
            pool=20, k=20, question=question, refill=True,
        )
        order = [row["id"] for row in out["order"]]
        cuts = {}
        for k in KS:
            top = order[:k]
            hits = [g for g in l2 if g in top]
            nongold = [p for p in top if p not in set(l2)]
            cuts[str(k)] = {
                "hits": len(hits),
                "gold_total": len(l2),
                "nongold": len(nongold),
                "hit_ids": hits,
            }
        print(
            f"  {qid} pool20 {pool_stats['20']['hits']}/{len(l2)} "
            f"pool50 {pool_stats['50']['hits']}/{len(l2)} "
            f"@7 {cuts['7']['hits']} frame_opts={fuse_meta.get('frame', {}).get('options') if isinstance(fuse_meta.get('frame'), dict) else extract_event_frame(question).options}",
            flush=True,
        )
        q_out.append({
            "qid": qid,
            "question": question,
            "n_l2": len(l2),
            "n_pack_miss": len(missed_pack),
            "pool": pool_stats,
            "cuts": cuts,
            "fuse": {k: fuse_meta[k] for k in ("mode", "n_neighbor_added", "views") if k in fuse_meta},
            "frame": extract_event_frame(question).to_dict(),
        })
    return {
        "slug": slug,
        "name": case.name,
        "n_union": len(union),
        "gold_total": gold_total,
        "pool_hits": pool_hits,
        "pool_rate": {
            p: round(pool_hits[p] / gold_total, 4) if gold_total else 0.0 for p in pool_hits
        },
        "cut_hits": {
            str(k): sum(q["cuts"][str(k)]["hits"] for q in q_out) for k in KS
        },
        "questions": q_out,
        "wall_s": round(time.perf_counter() - t0, 1),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R19 — 一筛进池（混合检索＋事件框架）",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。use_llm_views={report['defaults']['use_llm_views']}。"
        "二筛仍为 inbox_rerank；不指望捞池外金标。未做系数网格重拟合。",
        "",
        "## 数字表",
        "",
        "| 案 | 金标 | 池20 | 池20率 | 池50 | 池50率 | @4 | @5 | @7 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        lines.append(
            f"| {c['slug']} | {c['gold_total']} | "
            f"{c['pool_hits']['20']} | {c['pool_rate']['20']:.0%} | "
            f"{c['pool_hits']['50']} | {c['pool_rate']['50']:.0%} | "
            f"{c['cut_hits']['4']} | {c['cut_hits']['5']} | {c['cut_hits']['7']} |"
        )
    if report.get("baselines"):
        lines += ["", "### 对照基线（历史）", "", "| 来源 | 案 | 池20 | @7 |", "|---|---|---:|---:|"]
        for row in report["baselines"]:
            lines.append(f"| {row['source']} | {row['slug']} | {row['pool20']} | {row['at7']} |")
    lines += [
        "",
        "## 改动要点",
        "",
        "1. **事件框架**：问句抽对立选项＋时点／主体／定性键（`event_frame.py`），去掉一筛对 leave/money/post 硬族依赖；选项近义扩展（不愿→不想等）。",
        "2. **可迁移标签**：authority_band／frame_align／has_time_nail／applicability（`portable_tags.py`）。",
        "3. **多视图检索**：结论／原因／证据改写 + 原文BM25⊕摘要BM25⊕向量 RRF（`query_views` + `stage1_pool`）。",
        "4. **邻块补全＋权威臂**：命中邻块 ±1；另加「回应／通报」权威检索臂（通义：高相似靠角色权威）。",
        "5. **双通道**：`pool_ranked`＝经典⊕视图⊕权威⊕邻块（进池率）；`submit_ranked`＝纯经典（@k／二筛），防填池搅乱刘翔回归。",
        "6. **二筛**：沿用 R12 inbox 规则，只排盒内——不指望捞池外金标。",
        "",
        "## 分题池命中",
        "",
    ]
    for c in report["cases"]:
        lines.append(f"### {c['slug']}")
        lines.append("")
        lines.append("| 题 | 金标 | 池20 | 池50 | @7 | 选项 |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for q in c["questions"]:
            opts = " / ".join((q.get("frame") or {}).get("options") or []) or "—"
            lines.append(
                f"| {q['qid']} | {q['n_l2']} | {q['pool']['20']['hits']} | "
                f"{q['pool']['50']['hits']} | {q['cuts']['7']['hits']} | {opts} |"
            )
        lines.append("")
    lines += [
        "## 路径",
        "- `artifacts/R19_stage1_pool.json`",
        "- `artifacts/R19_stage1_pool.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    use_llm = os.environ.get("VERITAS_R19_LLM_VIEWS", "") in {"1", "true", "TRUE"}
    coeff, names = _coeff_names()
    cases = []
    # 刘翔
    cases.append(_eval_case(
        "liuxiang", _case("刘翔", prefer_local=True), coeff, names,
        prefer_gold=True, use_llm_views=use_llm, baseline_fuse=False,
    ))
    # 冒烟
    for slug, mark, _ in CASES[1:]:
        cases.append(_eval_case(
            slug, _case(mark), coeff, names,
            prefer_gold=False, use_llm_views=use_llm, baseline_fuse=False,
        ))

    baselines = [
        {"source": "R17", "slug": "liuxiang", "pool20": "14/14", "at7": "12/14"},
        {"source": "R17", "slug": "jilong", "pool20": "2/13", "at7": "2/13"},
        {"source": "R17", "slug": "us_cn_ai", "pool20": "3/13", "at7": "0/13"},
        {"source": "R16", "slug": "jilong", "pool20": "~3/13", "at7": "2/13"},
        {"source": "R16", "slug": "us_cn_ai", "pool20": "~3/13", "at7": "0/13"},
    ]
    train = cases[0]
    smoke = cases[1:]
    bullets = []
    bullets.append(
        f"刘翔回归：池20 **{train['pool_hits']['20']}/{train['gold_total']}**，"
        f"@7 **{train['cut_hits']['7']}/{train['gold_total']}**"
        f"（目标池满、@7≥12）。"
    )
    for c in smoke:
        bullets.append(
            f"{c['slug']}：池20 **{c['pool_hits']['20']}/{c['gold_total']}**"
            f"（{c['pool_rate']['20']:.0%}），池50 **{c['pool_hits']['50']}/{c['gold_total']}**，"
            f"@7 {c['cut_hits']['7']}/{c['gold_total']}。"
        )
    r17_j = 2 / 13
    r17_u = 3 / 13
    if smoke:
        j = next(c for c in smoke if c["slug"] == "jilong")
        u = next(c for c in smoke if c["slug"] == "us_cn_ai")
        bullets.append(
            f"相对 R17：吉隆池20 {j['pool_rate']['20']:.0%} vs {r17_j:.0%}；"
            f"中美AI池20 {u['pool_rate']['20']:.0%} vs {r17_u:.0%}。"
        )
    report = {
        "ticket": "R19-stage1-pool",
        "defaults": {
            "use_llm_views": use_llm,
            "pools": list(POOLS),
            "neighbor_window": 1,
            "stage2": "inbox_rerank pool20",
            "no_grid_refit": True,
        },
        "cases": cases,
        "baselines": baselines,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R19_stage1_pool.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R19_stage1_pool.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)
    # 回归闸：@7 不回退；进池以冒烟案相对 R17 为主尺（刘翔池满为愿景非硬闸）
    ok = train["cut_hits"]["7"] >= 12
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
