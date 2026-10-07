# -*- coding: utf-8 -*-
"""B4 评测集 v3:子句级挖空出题 → BM25 召回自测。

题目 = 含数值的子句(逗号级切分,全部数字挖空为「多少」),带主语语境
不带答案;BM25 查询剥离公司名(单公司案卷内无区分度,只放大样板噪声)。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.core.bm25 import rank_segments
from app.core.fact_ledger import extract_facts
from app.ingest.case_loader import load_case

JUNK = re.compile(r"年度报告摘要|拟按总股本|并在通过后|信用账户|期权|激励计划|"
                  r"证券代码|证券简称|第二节|第三节|每股收益|回购股份")
TARGET = 30
PER_COMPANY = 5


def clause_of(seg_text: str, raw: str) -> tuple[str, str] | None:
    """含该数值的子句 → (挖空全数字后的子句, 原子句);次子句拼接±1。"""
    i = seg_text.find(raw)
    if i < 0:
        return None
    start = max([seg_text.rfind(ch, 0, i) for ch in "。！？；\n"] + [-1]) + 1
    end = len(seg_text)
    for ch in "。！？；":
        e = seg_text.find(ch, i)
        if e >= 0:
            end = min(end, e + 1)
    sent = seg_text[start:end].strip()
    if not (10 <= len(sent) <= 160):
        return None
    parts = [p for p in re.split(r"[，,]", sent) if p.strip()]
    idx = next((k for k, p in enumerate(parts) if raw in p), None)
    if idx is None:
        return None
    clause = parts[idx]
    if len(clause) < 8 and 0 < idx < len(parts) - 1:
        clause = parts[idx - 1] + "，" + clause
    if not (6 <= len(clause) <= 80):
        return None
    return clause, sent


def mask_numbers(text: str) -> str:
    return re.sub(r"\d[\d,.]*\s*(?:%|％|万|亿|元)?", "多少", text)


def main() -> int:
    corpus = REPO / "eval" / "corpus"
    questions: list[dict] = []
    for cdir in sorted(p for p in corpus.iterdir() if p.is_dir()):
        company = cdir.name
        d = load_case(cdir)
        year_of_src = {src.id: str(src.meta.get("year") or "")
                       for src in d.sources}
        picked: list[dict] = []
        seen: set[str] = set()
        for f in extract_facts(d):
            if JUNK.search(f.metric):
                continue
            year = f.date or year_of_src.get(f.source_id, "")
            if not re.fullmatch(r"(19|20)\d{2}", year):
                continue
            seg = d.segment(f.seg_id)
            if seg is None:
                continue
            got = clause_of(seg.text, f.raw)
            if not got:
                continue
            clause, sent = got
            bm25_q = mask_numbers(clause).replace(company, "")
            if len(re.sub(r"多少", "", bm25_q)) < 8 or bm25_q in seen:
                continue
            seen.add(bm25_q)
            picked.append({
                "company": company, "year": year,
                "question": f"{company}{year}年：{mask_numbers(clause)}",
                "bm25_query": bm25_q,
                "value": f.raw, "ground_seg": f.seg_id,
                "metric": f.metric[:24],
            })
            if len(picked) >= PER_COMPANY:
                break
        questions.extend(picked)

    questions = questions[:TARGET]

    hit = 0
    for q in questions:
        d = load_case(corpus / q["company"])
        top5 = {sid for sid, _ in rank_segments(d, q["bm25_query"])[:5]}
        q["bm25_top5_hit"] = q["ground_seg"] in top5
        hit += q["bm25_top5_hit"]

    out = REPO / "eval" / "questions.jsonl"
    out.write_text("\n".join(json.dumps(q, ensure_ascii=False)
                             for q in questions), encoding="utf-8")
    miss = [q for q in questions if not q["bm25_top5_hit"]]
    print(f"生成 {len(questions)} 问;BM25 recall@5(子句查询口径,上界) = "
          f"{hit}/{len(questions)} = {hit / max(1, len(questions)):.0%}")
    for q in miss[:4]:
        print("  miss:", q["company"], q["bm25_query"][:50], "→", q["ground_seg"])
    by_c: dict[str, int] = {}
    for q in questions:
        by_c[q["company"]] = by_c.get(q["company"], 0) + 1
    print("分布:", by_c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
