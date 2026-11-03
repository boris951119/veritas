#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""箱内段批量摘要建库（C-127 自实验仓端口；workers=1 稳；可 nohup）。

主仓端口版与实验版两处差异：
- universe（议题进箱并集）逻辑自含在本脚本——读 ``case_dir/conclusions.json``
  取议题＋``pack_material`` 收并集。金标隔离闸只约束 ``app/``，scripts 评测
  侧读取沿用 ``scripts/probe_c125_six_case_gate`` 同法；不 import 已摘除的
  ``app.kg_lab.slices.union_pack_ids``。
- 新增 ``--dry-run``：零 LLM，只报 pending 段数与前几个段 id（CI 可跑）。

摘要缓存落 ``.kg_lab_vault/summaries/<slug>/``（gitignore，不入库）；
已有 ok 摘要的段自动跳过（``force=False``）。默认热路径（开旗）
**不会**自动调用本逻辑——摘要建库只走本脚本。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.kg_test_tree_line import CASE_MARK_PAIRS  # noqa: E402 — C-128 同表
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from app.kg_lab.summarize import summarize_paras, summary_path  # noqa: E402


def _slug(name: str) -> str:
    # C-128：标记映射与生产 ``resolve_case_slug`` 同源（加案只改 kg_test_tree_line）
    for a, b in CASE_MARK_PAIRS:
        if a in name:
            return b
    return "case"


def _questions_from_conclusions(case_dir: Path) -> list[dict[str, str]]:
    conc = json.loads(
        (case_dir / "conclusions.json").read_text(encoding="utf-8"))
    seen: dict[str, str] = {}
    for row in conc:
        qid = str(row.get("question_id") or "").strip()
        q = str(row.get("question") or "").strip()
        if qid and q and qid not in seen:
            seen[qid] = q
    return [{"question_id": k, "question": v}
            for k, v in sorted(seen.items())]


def _union_pack_ids(case_dir: Path) -> tuple[object, set[str]]:
    """该案所有议题的进箱并集（评测侧 universe，同 R44 口径）。"""
    dossier = load_official_case(case_dir)
    union: set[str] = set()
    for row in _questions_from_conclusions(case_dir):
        dossier.question = row["question"]
        pack = pack_material(dossier)
        union |= {str(x) for x in (pack.get("selected") or [])}
    return dossier, union


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-filter", default="刘翔")
    ap.add_argument("--samples", type=Path,
                    default=ROOT / "data" / "trs-samples")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true",
                    help="零 LLM：只报 pending 段数与前几个段 id")
    args = ap.parse_args()
    if not args.samples.is_dir():
        print(f"samples dir not found: {args.samples}", file=sys.stderr)
        return 2
    cases = sorted(
        p for p in args.samples.iterdir()
        if p.is_dir() and (p / "raw_documents.json").is_file()
        and args.case_filter in p.name
    )
    if not cases:
        print("no case", file=sys.stderr)
        return 2
    case = cases[0]
    slug = _slug(case.name)
    dossier, union = _union_pack_ids(case)
    doc_of: dict[str, str] = {}
    for src in dossier.sources:
        for seg in src.segments:
            doc_of[str(seg.id)] = str(src.id)

    def pending() -> list[str]:
        out: list[str] = []
        for pid in sorted(union):
            p = summary_path(slug, doc_of[pid], pid)
            if not p.is_file():
                out.append(pid)
                continue
            try:
                if not json.loads(p.read_text(encoding="utf-8")).get("ok"):
                    out.append(pid)
            except json.JSONDecodeError:
                out.append(pid)
        return out

    if args.dry_run:
        left = pending()
        print(
            f"DRY_RUN slug={slug} universe={len(union)} "
            f"pending={len(left)} sample={left[:5]}",
            flush=True,
        )
        return 0

    round_i = 0
    while True:
        left = pending()
        print(f"round={round_i} pending={len(left)} slug={slug}", flush=True)
        if not left:
            break
        chunk = set(left[: max(1, args.batch)])
        t0 = time.perf_counter()
        meta = summarize_paras(
            dossier, case_slug=slug, para_ids=chunk,
            workers=args.workers, force=False,
        )
        print(
            f"  meta={meta} wall={time.perf_counter() - t0:.1f}s",
            flush=True,
        )
        round_i += 1
    print("ALL_SUMMARIES_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
