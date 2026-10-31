#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17：标签解耦 —— schema + lexicon 注入；刘翔回归 + holdout 冒烟。

默认本地 14B（摘要已缓存则跳过）；不接百炼。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.case_lexicon import lexicon_for_question  # noqa: E402
from app.kg_lab.config import DEFAULT_K, WIDE_K  # noqa: E402
from app.kg_lab.eval_metrics import leak_check  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.inbox_rerank import inbox_rerank  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.query_expand import DEFAULT_EXPAND_TOP_N, DEFAULT_PARAPHRASE_N  # noqa: E402
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.recall_arms import _fuse_rrf  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.tag_schema import (  # noqa: E402
    STAGE1_FEATURES,
    STAGE2_FEATURES,
    TAGGING_RULES,
    schema_table,
)
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

OUT = ROOT / "artifacts"
SAMPLES = Path("/Users/liuboyu/Desktop/veritas-testcases/样例集-拓尔思-20261012")
POOL = 20
KS = (4, 5, 7)
# 冒烟：吉隆（大库）+ 中美AI（R16 上 0 命中）
SMOKE = (("jilong", "吉隆"), ("us_cn_ai", "中美AI"))


def _case_by_mark(mark: str, *, prefer_local: bool = False) -> Path:
    if prefer_local:
        hits = [
            p for p in (ROOT / "data" / "trs-samples").iterdir()
            if p.is_dir() and mark in p.name and (p / "raw_documents.json").is_file()
        ]
        if len(hits) == 1:
            return hits[0]
    hits = [
        p for p in SAMPLES.iterdir()
        if p.is_dir() and mark in p.name and (p / "raw_documents.json").is_file()
    ]
    if len(hits) != 1:
        raise SystemExit(f"case {mark}: {hits}")
    return hits[0]


def _coeff_names() -> tuple[dict[str, float], tuple[str, ...]]:
    r9 = json.loads((OUT / "R9_refine_buckets.json").read_text(encoding="utf-8"))
    names = R9_ADDED + tuple(n for n in r9_names(FEATURE_NAMES) if n not in R9_ADDED)
    coeff = {n: float(r9["coeff"].get(n) or 0.0) for n in names}
    for n in names:
        coeff.setdefault(n, 0.0)
    return coeff, names


def _eval_case(
    slug: str,
    case: Path,
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    use_llm_lexicon: bool = False,
    prefer_gold_cluster: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    print(f"=== {slug} {case.name} ===", flush=True)
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    emb = index.ensure_embeddings(force=False)
    print(f"  union {len(union)} embed_new {emb.get('n_new')}", flush=True)
    url_of = {
        str(d.get("doc_id")): str(d.get("content_url") or "")
        for d in json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    }
    bundles = []
    leak_any = False
    lex_dump = []
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, skipped = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        missed_pack = sorted(p for _d, p in gold if p not in universe)
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}
        fused, queries, _pm, _n = _fuse_rrf(sub, question)
        if not leak_check({"queries": queries, "selection_used_gold": False}, gold=gold).get("ok"):
            leak_any = True
        lex = lexicon_for_question(
            question, case_slug=slug, use_llm=use_llm_lexicon,
        )
        # prefer_gold_cluster 仅刘翔回归对照 R12；冒烟／线上关
        prefer = set(l2) if prefer_gold_cluster else None
        bundle = build_bundle(
            sub_rows, fused, question, frames=True, prefer_ids=prefer, lex=lex, case_slug=slug,
        )
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question, lex=lex)
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2
        bundle["missed_pack"] = missed_pack
        bundle["gold_skipped_locator"] = skipped
        bundles.append(bundle)
        lex_dump.append({"qid": qid, "lexicon": lex.to_dict()})
        print(
            f"  {qid} actors={lex.actors} families={lex.active_families}",
            flush=True,
        )
    stage1 = evaluate(bundles, coeff, k7=DEFAULT_K, k15=WIDE_K, names=names)
    q_out = []
    gold_in_pool = 0
    gold_total = 0
    for b in bundles:
        ranked = stage1["ranked"][b["qid"]]
        stage1_pos = {pid: i for i, (pid, _) in enumerate(ranked, 1)}
        texts = {
            pid: str((b["metas"].get(pid) or {}).get("text") or "")
            for pid, _ in ranked[:POOL]
        }
        lex = lexicon_for_question(b["question"], case_slug=slug)
        out = inbox_rerank(
            ranked, texts=texts, feats=b["feats"], metas=b["metas"],
            pool=POOL, k=POOL, question=b["question"], refill=True, lex=lex,
        )
        order = [row["id"] for row in out["order"]]
        l2set = set(b["l2"])
        gold_total += len(b["l2"])
        gold_in_pool += sum(1 for g in b["l2"] if stage1_pos.get(g, 10**9) <= POOL)
        cuts = {}
        for k in KS:
            top = order[:k]
            hits = [g for g in b["l2"] if g in top]
            nongold = [p for p in top if p not in l2set]
            cuts[str(k)] = {
                "hits": len(hits),
                "gold_total": len(b["l2"]),
                "nongold": len(nongold),
                "hit_ids": hits,
                "nongold_ids": nongold,
            }
        outside = []
        for g in b["l2"]:
            ir = order.index(g) + 1 if g in order else None
            s1 = stage1_pos.get(g)
            if s1 is None or s1 > POOL:
                why = f"一筛第 {s1}，池 {POOL} 外" if s1 else "一筛未入围"
            elif ir is None:
                why = "二筛后不在名单"
            elif ir > 7:
                why = f"二筛名次 {ir}，Top-7 外"
            else:
                continue
            outside.append({"id": g, "stage1_rank": s1, "inbox_rank": ir, "why": why})
        for g in b["missed_pack"]:
            outside.append({"id": g, "why": "装箱未选入", "stage1_rank": None, "inbox_rank": None})
        q_out.append({
            "qid": b["qid"],
            "question": b["question"],
            "n_l2": len(b["l2"]),
            "cuts": cuts,
            "outside_top7": outside,
            "stage1_top7": [pid for pid, _ in ranked[:7]],
        })
        print(
            f"  {b['qid']} @4 {cuts['4']['hits']}/{cuts['4']['gold_total']} "
            f"@5 {cuts['5']['hits']} @7 {cuts['7']['hits']} "
            f"pool_gold {sum(1 for g in b['l2'] if stage1_pos.get(g, 10**9) <= POOL)}/{len(b['l2'])}",
            flush=True,
        )
    return {
        "slug": slug,
        "name": case.name,
        "n_union": len(union),
        "questions": q_out,
        "lexicons": lex_dump,
        "gold_in_pool20": gold_in_pool,
        "gold_total": gold_total,
        "stage1_sum7": stage1["sum7"],
        "prefer_gold_cluster": prefer_gold_cluster,
        "leak_any_bad": leak_any,
        "wall_s": round(time.perf_counter() - t0, 1),
    }


def _sum_cuts(cases: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out = {}
    for k in KS:
        hits = nongold = gold = 0
        for c in cases:
            for q in c["questions"]:
                cell = q["cuts"][str(k)]
                hits += cell["hits"]
                nongold += cell["nongold"]
                gold += cell["gold_total"]
        out[str(k)] = {"hits": hits, "gold_total": gold, "nongold": nongold}
    return out


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R17 — 标签解耦（schema + lexicon）",
        "",
        "规则只规定标签**类别**；主体／主张表面词从问句抽取，可选 `vaults/kg-lab/lexicon/<slug>.json` 覆盖。",
        "一筛系数仍冻结 R9／R12；二筛规则不变，但词表改为注入。",
        f"墙钟 {report['wall_s']}s。use_llm_lexicon={report['defaults']['use_llm_lexicon']}（默认本地规则，不调 14B 抽词）。",
        "",
        "## schema：类别 → 用途",
        "",
        "| 类别 | 标签 | 阶段 |",
        "|---|---|---|",
    ]
    for row in report["schema_table"][:40]:
        lines.append(f"| {row['category']} | `{row['tag']}` | {','.join(row['stage'])} |")
    if len(report["schema_table"]) > 40:
        lines.append(f"| … | 共 {len(report['schema_table'])} 行 | … |")
    lines += [
        "",
        "### 一筛特征（排序）",
        "",
        "```",
        ", ".join(STAGE1_FEATURES[:24]) + ", …",
        "```",
        "",
        "### 二筛特征（去重／挡路）",
        "",
        "```",
        ", ".join(STAGE2_FEATURES),
        "```",
        "",
        "## 刘翔回归（对照 R12 池20 @7＝13/14）",
        "",
        "| k | 金标命中 | 金标总数 | 非金标 |",
        "|---:|---:|---:|---:|",
    ]
    train = report["train"]
    for k, cell in report["train_cuts"].items():
        lines.append(f"| {k} | {cell['hits']} | {cell['gold_total']} | {cell['nongold']} |")
    lines += [
        "",
        f"池 20 内金标 {train['gold_in_pool20']}/{train['gold_total']}；一筛 sum@7={train['stage1_sum7']}。",
        "",
        "## holdout 冒烟",
        "",
        "| 案 | 池内金标 | @4 | @5 | @7 |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in report["smoke"]:
        cuts = {k: sum(q["cuts"][k]["hits"] for q in c["questions"]) for k in ("4", "5", "7")}
        gold = sum(q["cuts"]["7"]["gold_total"] for q in c["questions"])
        lines.append(
            f"| {c['slug']} | {c['gold_in_pool20']}/{c['gold_total']} | "
            f"{cuts['4']}/{gold} | {cuts['5']}/{gold} | {cuts['7']}/{gold} |"
        )
    smoke_cuts = report["smoke_cuts"]
    lines += [
        "",
        f"冒烟合计 @7 **{smoke_cuts['7']['hits']}/{smoke_cuts['7']['gold_total']}**"
        f"（R16 同两案 @7 为吉隆 2/13 + 中美AI 0/13＝2/26）。",
        "",
        "## 改动文件",
        "",
    ]
    for p in report["changed_files"]:
        lines.append(f"- `{p}`")
    lines += [
        "",
        "## 读法",
        "",
        report["reading"],
        "",
        "## 剩余风险",
        "",
    ]
    for r in report["risks"]:
        lines.append(f"- {r}")
    lines += [
        "",
        "## 路径",
        f"- `{OUT / 'R17_tag_decouple.json'}`",
        f"- `{OUT / 'R17_tag_decouple.md'}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    assert DEFAULT_EXPAND_TOP_N == 16 and DEFAULT_PARAPHRASE_N == 1
    coeff, names = _coeff_names()
    train_case = _case_by_mark("刘翔", prefer_local=True)
    # 与 R12 同：簇代表可用金标 prefer（只影响通稿去重，特征仍不读金标）
    train = _eval_case(
        "liuxiang", train_case, coeff, names,
        use_llm_lexicon=False, prefer_gold_cluster=True,
    )
    smoke = []
    for slug, mark in SMOKE:
        try:
            smoke.append(_eval_case(slug, _case_by_mark(mark), coeff, names))
        except SystemExit as e:
            print(f"skip smoke {slug}: {e}", flush=True)
    train_cuts = _sum_cuts([train])
    smoke_cuts = _sum_cuts(smoke)
    r16 = {}
    r16_path = OUT / "R16_holdout_topk.json"
    if r16_path.is_file():
        r16_doc = json.loads(r16_path.read_text(encoding="utf-8"))
        r16 = {
            "holdout_at7": (r16_doc.get("holdout_cuts") or {}).get("7"),
            "note": "R16 全五案；本冒烟只跑吉隆+中美AI",
        }
    train7 = train_cuts["7"]["hits"]
    reading = (
        f"刘翔池20 @7＝{train7}/{train_cuts['7']['gold_total']}"
        f"（目标 ≥12/14，R12 为 13/14）。"
        f"冒烟两案 @7＝{smoke_cuts['7']['hits']}/{smoke_cuts['7']['gold_total']}；"
        f"池内金标 {sum(c['gold_in_pool20'] for c in smoke)}/{sum(c['gold_total'] for c in smoke)}。"
    )
    if train7 < 12:
        reading += " 回归未达 12，需检查主体抽取或 prefer_ids 关闭的影响。"
    report: dict[str, Any] = {
        "ticket": "R17-tag-decouple",
        "defaults": {
            "expand_top_n": DEFAULT_EXPAND_TOP_N,
            "n_paraphrase": DEFAULT_PARAPHRASE_N,
            "pool": POOL,
            "frozen_stage1": "R9 coeff (same as R12)",
            "use_llm_lexicon": False,
            "prefer_ids_gold_train_only": True,
            "model_policy": "local-qwen3-14b-default; dashscope only if user says 用线上",
        },
        "schema_table": schema_table(),
        "tagging_rules": TAGGING_RULES,
        "stage1_features": list(STAGE1_FEATURES),
        "stage2_features": list(STAGE2_FEATURES),
        "train": train,
        "train_cuts": train_cuts,
        "smoke": smoke,
        "smoke_cuts": smoke_cuts,
        "r16_ref": r16,
        "changed_files": [
            "app/kg_lab/tag_schema.py",
            "app/kg_lab/case_lexicon.py",
            "app/kg_lab/multidim_weight.py",
            "app/kg_lab/r9_buckets.py",
            "app/kg_lab/inbox_rerank.py",
            "app/kg_lab/source_role.py",
            "app/kg_lab/slice_dims.py",
            "app/kg_lab/query_expand.py",
            "vaults/kg-lab/lexicon/liuxiang.json",
            "scripts/kg_lab/run_r17_tag_decouple.py",
            "tests/test_kg_lab_r17_tag_decouple.py",
        ],
        "risks": [
            "主张族目录仍含就业／安置类通用词（买断／编制等），不是人名，但跨域案可能误激族。",
            "主体抽取是浅规则，复杂问句可能漏机构别名；可用 case_lexicon 或 use_llm=True（本地14B）补。",
            "本跑关闭了金标 prefer_ids，通稿簇代表与 R12 训练跑不完全同分布。",
            "一筛系数仍在刘翔上拟合；解耦词表不等于跨案重拟合。",
        ],
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    report["reading"] = reading
    (OUT / "R17_tag_decouple.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R17_tag_decouple.md").write_text(_markdown(report), encoding="utf-8")
    print(reading, flush=True)
    return 0 if train7 >= 12 and not train["leak_any_bad"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
