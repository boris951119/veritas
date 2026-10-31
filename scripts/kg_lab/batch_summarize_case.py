#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""箱内段批量摘要（workers=1 稳；可 nohup）。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.kg_lab.slices import union_pack_ids  # noqa: E402
from app.kg_lab.summarize import summarize_paras, summary_path  # noqa: E402


def _slug(name: str) -> str:
    for a, b in [
        ("刘翔", "liuxiang"),
        ("王虹", "wanghong"),
        ("中美AI", "us_cn_ai"),
        ("印度航空", "ai171"),
        ("柬泰", "kh_th"),
        ("吉隆", "jilong"),
    ]:
        if a in name:
            return b
    return "case"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-filter", default="刘翔")
    ap.add_argument("--samples", type=Path,
                    default=ROOT / "data" / "trs-samples")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
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
    d, union, _qs = union_pack_ids(case)
    doc_of: dict[str, str] = {}
    for src in d.sources:
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

    round_i = 0
    while True:
        left = pending()
        print(f"round={round_i} pending={len(left)} slug={slug}", flush=True)
        if not left:
            break
        chunk = set(left[: max(1, args.batch)])
        t0 = time.perf_counter()
        meta = summarize_paras(
            d, case_slug=slug, para_ids=chunk,
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
