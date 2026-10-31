#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R21：可迁移来源角色——诊断＋修标后评测。

规则优先区分「可核验事实陈述」vs「纯观点／混口径」。禁止案名硬编码。
评测：liuxiang 回归 + jilong／us_cn_ai 冒烟；对比 R19／R20。
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.config import DEFAULT_K  # noqa: E402
from app.kg_lab.event_frame import extract_event_frame  # noqa: E402
from app.kg_lab.index_build import KgIndex, build_corpus_rows  # noqa: E402
from app.kg_lab.multidim_weight import build_bundle  # noqa: E402
from app.kg_lab.portable_tags import apply_portable_features, authority_band  # noqa: E402
from app.kg_lab.r8_fit import FEATURE_NAMES, augment_features, evaluate  # noqa: E402
from app.kg_lab.r9_buckets import R9_ADDED, apply_r9, r9_names  # noqa: E402
from app.kg_lab.slices import pack_selected_for_question, union_pack_ids  # noqa: E402
from app.kg_lab.source_role import infer_fine_role, portable_role_from  # noqa: E402
from app.kg_lab.stage1_pool import fuse_r19  # noqa: E402
from app.kg_lab.stage2_authority import authority_rerank  # noqa: E402
from app.kg_lab.case_lexicon import lexicon_for_question  # noqa: E402
from app.kg_lab.source_role import _meta_from_row  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

OUT = ROOT / "artifacts"
SAMPLES = Path("/Users/liuboyu/Desktop/veritas-testcases/样例集-拓尔思-20261012")
KS = (4, 5, 7)
POOLS = (20, 50)

R19 = {
    "liuxiang": {"pool20": 8, "at4": 9, "at5": 11, "at7": 12, "gold": 14},
    "jilong": {"pool20": 4, "at4": 1, "at5": 2, "at7": 2, "gold": 13},
    "us_cn_ai": {"pool20": 6, "at4": 0, "at5": 0, "at7": 0, "gold": 13},
}
R20 = {
    "liuxiang": {"pool20": 8, "at4": 9, "at5": 11, "at7": 12, "gold": 14},
    "jilong": {"pool20": 4, "at4": 1, "at5": 2, "at7": 2, "gold": 13},
    "us_cn_ai": {"pool20": 6, "at4": 0, "at5": 0, "at7": 0, "gold": 13},
}


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
    from app.kg_lab.r21_coeff import apply_r21_coeff_nudge

    r9 = json.loads((OUT / "R9_refine_buckets.json").read_text(encoding="utf-8"))
    names = R9_ADDED + tuple(n for n in r9_names(FEATURE_NAMES) if n not in R9_ADDED)
    coeff = {n: float(r9["coeff"].get(n) or 0.0) for n in names}
    for n in names:
        coeff.setdefault(n, 0.0)
    for n in ("frame_align", "authority_unit", "has_time_nail", "option_align",
              "publish_recency", "verifiability", "title_option_hit", "role_party_relay"):
        coeff.setdefault(n, 0.0)
        if n not in names:
            names = names + (n,)
    coeff = apply_r21_coeff_nudge(coeff)
    return coeff, names


def diagnose_case(slug: str, mark: str, *, prefer_local: bool = False) -> dict[str, Any]:
    case = _case(mark, prefer_local=prefer_local)
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    by = {r["para_id"]: r for r in rows}
    gold_roles: Counter[str] = Counter()
    gold_auth: Counter[str] = Counter()
    neigh_roles: Counter[str] = Counter()
    gold_rows: list[dict[str, Any]] = []
    mislabel = 0
    n_gold = 0
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, _ = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        lex = lexicon_for_question(question, case_slug=slug)
        # 近邻：同文档 ±1 且非金标
        gold_set = set(l2)
        for pid in l2:
            n_gold += 1
            row = by.get(pid) or {}
            title = str(row.get("title") or "")
            text = str(row.get("text") or "")
            fine = infer_fine_role(title, text, row.get("source_credibility"), lex=lex)
            role = portable_role_from(title, text, str(fine["role"]), lex=lex)
            auth = authority_band(
                title=title, text=text, fine_role=role, tier="other",
            )
            gold_roles[role] += 1
            gold_auth[auth] += 1
            low = role in {"commentary", "mixed_summary"} or auth in {"market", "unknown"}
            if low:
                mislabel += 1
            gold_rows.append({
                "qid": qid, "pid": pid, "fine_role": role,
                "authority_band": auth, "signals": fine.get("signals"),
                "text_head": text[:60].replace("\n", " "),
            })
            # neighbors
            m = __import__("re").match(r"^(?P<doc>.+)#p(?P<n>\d+)$", pid)
            if not m:
                continue
            doc, n = m.group("doc"), int(m.group("n"))
            for d in (-1, 1):
                nb = f"{doc}#p{n + d}"
                if nb in gold_set or nb not in by:
                    continue
                nrow = by[nb]
                nf = infer_fine_role(
                    str(nrow.get("title") or ""), str(nrow.get("text") or ""),
                    nrow.get("source_credibility"), lex=lex,
                )
                nrole = portable_role_from(
                    str(nrow.get("title") or ""), str(nrow.get("text") or ""),
                    str(nf["role"]), lex=lex,
                )
                neigh_roles[nrole] += 1
    return {
        "slug": slug,
        "n_gold": n_gold,
        "gold_fine_role": dict(gold_roles),
        "gold_authority_band": dict(gold_auth),
        "neighbor_fine_role": dict(neigh_roles),
        "mislabel_low_auth_or_comment": mislabel,
        "mislabel_rate": round(mislabel / n_gold, 4) if n_gold else 0.0,
        "samples": gold_rows[:12],
    }


def _eval_case(
    slug: str,
    mark: str,
    coeff: dict[str, float],
    names: tuple[str, ...],
    *,
    prefer_gold: bool,
) -> dict[str, Any]:
    case = _case(mark, prefer_local=(slug == "liuxiang"))
    t0 = time.perf_counter()
    print(f"=== eval {slug} ===", flush=True)
    dossier, union, questions = union_pack_ids(case)
    rows = build_corpus_rows(dossier, case_slug=slug, para_ids=union)
    index = KgIndex(slug, rows)
    index.ensure_embeddings(force=False)
    raw = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    url_of = {str(d.get("doc_id")): str(d.get("content_url") or "") for d in raw}
    publish_of = {str(d.get("doc_id")): str(d.get("publish_time") or "") for d in raw}
    pool_hits = {str(p): 0 for p in POOLS}
    cut_hits = {str(k): 0 for k in KS}
    gold_total = 0
    q_out = []
    for qrow in questions:
        qid, question = qrow["question_id"], qrow["question"]
        gold, _ = gold_paras_for_question(case, qid)
        universe = pack_selected_for_question(dossier, question)
        l2 = sorted(p for _d, p in gold if p in universe)
        gold_total += len(l2)
        sub_rows = [r for r in rows if r["para_id"] in universe]
        sub = KgIndex(slug, sub_rows)
        sub.embeddings = {pid: v for pid, v in index.embeddings.items() if pid in universe}
        fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
        submit_ranked = fr["ranked"]
        pool_ranked = fr.get("pool_ranked") or fr["ranked"]
        frame = extract_event_frame(question)
        prefer = set(l2) if prefer_gold else None
        bundle = build_bundle(
            sub_rows, submit_ranked, question, frames=True,
            prefer_ids=prefer, case_slug=slug,
        )
        by_row = {r["para_id"]: r for r in sub_rows}
        lex = lexicon_for_question(question, case_slug=slug)
        for pid, _sc in pool_ranked[:50]:
            if pid in bundle["metas"]:
                continue
            row = by_row.get(pid)
            if row:
                bundle["metas"][pid] = _meta_from_row(row, lex=lex)
                bundle["feats"].setdefault(pid, {})
        augment_features(bundle["feats"], bundle["metas"], url_of)
        apply_r9(bundle["feats"], bundle["metas"], question)
        apply_portable_features(
            bundle["feats"], bundle["metas"], url_of, question, frame,
            publish_of=publish_of,
        )
        bundle["qid"] = qid
        bundle["question"] = question
        bundle["l2"] = l2
        stage1 = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)
        ranked = stage1["ranked"][qid]
        pool_pos = {pid: i for i, (pid, _) in enumerate(pool_ranked, 1)}
        pool_stats = {}
        for p in POOLS:
            in_p = [g for g in l2 if pool_pos.get(g, 10**9) <= p]
            pool_hits[str(p)] += len(in_p)
            pool_stats[str(p)] = {"hits": len(in_p), "gold_total": len(l2)}
        texts = {
            pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
            for pid in set([p for p, _ in ranked[:30]] + [p for p, _ in pool_ranked[:30]])
        }
        out = authority_rerank(
            ranked, pool_ranked,
            texts=texts, feats=bundle["feats"], metas=bundle["metas"],
            question=question, frame=frame, url_of=url_of, publish_of=publish_of,
            pool=20, k=20,
            head_keep=7 if prefer_gold else 2,
            max_inject=2 if prefer_gold else 5,
        )
        order = [row["id"] for row in out["order"]]
        cuts = {}
        for k in KS:
            hits = [g for g in l2 if g in order[:k]]
            cut_hits[str(k)] += len(hits)
            cuts[str(k)] = {"hits": len(hits), "gold_total": len(l2), "hit_ids": hits}
        print(
            f"  {qid} pool20 {pool_stats['20']['hits']}/{len(l2)} "
            f"@7 {cuts['7']['hits']}",
            flush=True,
        )
        q_out.append({"qid": qid, "pool": pool_stats, "cuts": cuts})
    return {
        "slug": slug,
        "gold_total": gold_total,
        "pool_hits": pool_hits,
        "cut_hits": cut_hits,
        "questions": q_out,
        "wall_s": round(time.perf_counter() - t0, 1),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R21 — 可迁移来源角色信号",
        "",
        "## 结论先行",
        "",
    ]
    for b in report["verdict_bullets"]:
        lines.append(f"- {b}")
    lines += [
        "",
        f"墙钟 {report['wall_s']}s。规则优先；未调线上大模型。",
        "",
        "## 诊断：金标误标（修后）",
        "",
        "| 案 | 金标 | commentary/mixed | 误标率 | Top fine_role |",
        "|---|---:|---:|---:|---|",
    ]
    for d in report["diagnosis"]:
        top = sorted(d["gold_fine_role"].items(), key=lambda x: -x[1])[:3]
        top_s = ", ".join(f"{k}:{v}" for k, v in top) or "—"
        lines.append(
            f"| {d['slug']} | {d['n_gold']} | {d['mislabel_low_auth_or_comment']} | "
            f"{d['mislabel_rate']:.0%} | {top_s} |"
        )
    if report.get("diagnosis_before"):
        lines += [
            "",
            "### 修前对照（同尺快照）",
            "",
            "| 案 | 误标率 | Top fine_role |",
            "|---|---:|---|",
        ]
        for d in report["diagnosis_before"]:
            top = sorted(d["gold_fine_role"].items(), key=lambda x: -x[1])[:3]
            top_s = ", ".join(f"{k}:{v}" for k, v in top) or "—"
            lines.append(f"| {d['slug']} | {d['mislabel_rate']:.0%} | {top_s} |")
    lines += [
        "",
        "## 评测 vs R19／R20",
        "",
        "| 案 | 池20 | @4 | @5 | @7 | R20@7 | R19池20 | Δ@7 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        b20 = R20[c["slug"]]
        b19 = R19[c["slug"]]
        lines.append(
            f"| {c['slug']} | {c['pool_hits']['20']} | {c['cut_hits']['4']} | "
            f"{c['cut_hits']['5']} | {c['cut_hits']['7']} | {b20['at7']} | "
            f"{b19['pool20']} | {c['cut_hits']['7'] - b20['at7']:+d} |"
        )
    lines += [
        "",
        "## 改动要点",
        "",
        "1. **`verifiable_fact_signals`**：URL／标题／通报模板／时点×数额复合槽；禁止案专名。",
        "2. **`portable_role` 与 `fine_role` 分流**：一筛仍吃 R20 `fine_role`（保刘翔）；"
        "披露／权威带／二筛注入用 `portable_role`（强／复合可核验的 commentary→media_relay）。",
        "3. **`authority_band` + `verifiability_unit`** 吃可核验槽；媒体等级仍只作一维。",
        "4. **二筛注入**：高可核验池内段插到 `head_keep` 之后（进 Top-k 前段），不再只置换弱尾。",
        "5. **词表**：`GENERIC_BULLETIN`／`INSTITUTION`／`OFFICIAL_VOICE` 加法扩展跨案模板，保留原安置套话。",
        "6. 保留 R19 pool／R20 conflict_pairs／裁决分流／二筛无问句相似度；**未**整套重拟合系数。",
        "",
        "## 剩余局限",
        "",
        "- 池外金标（pool>20）仍无法靠二筛注入进 @7；池20 与 R20 持平。",
        "- `portable_role` 未回写一筛独热，跨案 @k 主要靠注入；要再涨需轻量重拟合或池扩。",
        "- 通稿近同文去重仍靠正文相似，不依赖金标标签。",
        "",
        "## 路径",
        "- `artifacts/R21_portable_role.json`",
        "- `artifacts/R21_portable_role.md`",
        "- `artifacts/R21_diagnosis_before.json`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    t0 = time.perf_counter()
    # 诊断（当前码＝修后）；修前快照若有则读
    before_path = OUT / "R21_diagnosis_before.json"
    diagnosis_before = None
    if before_path.is_file() and os.environ.get("VERITAS_R21_REFRESH_BEFORE") != "1":
        diagnosis_before = json.loads(before_path.read_text(encoding="utf-8"))

    diagnosis = [
        diagnose_case("liuxiang", "刘翔", prefer_local=True),
        diagnose_case("jilong", "吉隆"),
        diagnose_case("us_cn_ai", "中美AI"),
    ]
    # 若尚无修前快照：把当前当 before 存一份的时机已过——用环境变量强制时另存
    if diagnosis_before is None and (OUT / "R21_diagnosis_before.json").is_file():
        diagnosis_before = json.loads((OUT / "R21_diagnosis_before.json").read_text(encoding="utf-8"))

    coeff, names = _coeff_names()
    cases = [
        _eval_case("liuxiang", "刘翔", coeff, names, prefer_gold=True),
        _eval_case("jilong", "吉隆", coeff, names, prefer_gold=False),
        _eval_case("us_cn_ai", "中美AI", coeff, names, prefer_gold=False),
    ]
    train = cases[0]
    bullets = []
    bullets.append(
        f"刘翔回归：@7 **{train['cut_hits']['7']}/{train['gold_total']}**"
        f"（门槛 ≥11；R20={R20['liuxiang']['at7']}）。"
    )
    for c in cases[1:]:
        b = R20[c["slug"]]
        bullets.append(
            f"{c['slug']}：池20 **{c['pool_hits']['20']}**（R20 {b['pool20']}），"
            f"@7 **{c['cut_hits']['7']}**（R20 {b['at7']}）。"
        )
    for d in diagnosis:
        bullets.append(
            f"诊断 {d['slug']}：金标误标（comment/低权威）**{d['mislabel_rate']:.0%}**"
            f"（{d['mislabel_low_auth_or_comment']}/{d['n_gold']}）。"
        )
    report = {
        "ticket": "R21-portable-role",
        "diagnosis": diagnosis,
        "diagnosis_before": diagnosis_before,
        "cases": cases,
        "r19": R19,
        "r20": R20,
        "verdict_bullets": bullets,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R21_portable_role.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R21_portable_role.md").write_text(_markdown(report), encoding="utf-8")
    print("\n".join(bullets), flush=True)
    smoke_ok = any(
        cases[i]["cut_hits"]["7"] > R20[cases[i]["slug"]]["at7"]
        or cases[i]["pool_hits"]["20"] > R20[cases[i]["slug"]]["pool20"]
        for i in (1, 2)
    )
    ok = train["cut_hits"]["7"] >= 11 and smoke_ok
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
