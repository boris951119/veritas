"""C-69：时间轴键名／对撞三档量尺（默认 --dry-run＝零 HTTP 零模型）。

跑法::

    PYTHONPATH=. .venv/bin/python scripts/probe_c69_time_ledger.py --dry-run
    PYTHONPATH=. .venv/bin/python scripts/probe_c69_time_ledger.py \\
        --from /tmp/six2 \\
        --cases /path/to/样例集-拓尔思-20261012

纯函数 classify_time_class／day_norm 供 tests 真引用（§5 第 26 条）。
文档面点名本探针只写 stem＝probe_c69_time_ledger（§5 第 29 条）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from app.core.evidence import Dossier  # noqa: E402
from app.core.fact_ledger import (  # noqa: E402
    extract_facts, facts_block, find_collisions, set_ledger_time_class,
)
from app.core.skills import detect_skills  # noqa: E402
from app.core.temporal_check import (  # noqa: E402
    audit_temporal, set_source_time_unified, source_date,
)
from app.ingest.official_case import (  # noqa: E402
    load_official_case, publish_time_or_blank,
)

__all__ = [
    "day_norm",
    "classify_time_class",
    "raw_time_class",
    "measure_raw_docs",
    "measure_collisions",
    "main",
]


def day_norm(raw: str) -> str:
    """归一日 YYYYMMDD；不足 8 位回空。"""
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits[:8] if len(digits) >= 8 else ""


def classify_time_class(dates: list[str]) -> str:
    """归一日判据：任一空→unknown_time；全等→same_window；否则 cross_day。"""
    days = [day_norm(d) for d in dates]
    if any(not d for d in days):
        return "unknown_time"
    if len(set(days)) == 1:
        return "same_window"
    return "cross_day"


def raw_time_class(dates: list[str]) -> str:
    """原始串判据（对照臂；归一牙＝同日不同时戳在这里会变 cross_day）。"""
    raws = [str(d or "") for d in dates]
    if any(not r for r in raws):
        return "unknown_time"
    if len(set(raws)) == 1:
        return "same_window"
    return "cross_day"


def measure_raw_docs(cases_root: Path) -> dict:
    """原料三态：完整 ISO／在场非完整／键缺失。"""
    n_full = n_present = n_missing = n_docs = 0
    for rd in sorted(Path(cases_root).glob("*/raw_documents.json")):
        docs = json.loads(rd.read_text(encoding="utf-8"))
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            n_docs += 1
            raw = doc.get("publish_time")
            text = str(raw or "").strip()
            if not text:
                n_missing += 1
            elif publish_time_or_blank(raw):
                n_full += 1
            else:
                n_present += 1
    return {
        "n_docs": n_docs,
        "n_full_iso": n_full,
        "n_present_non_iso": n_present,
        "n_key_missing": n_missing,
    }


def measure_collisions(cases_root: Path) -> dict:
    """两臂 Fact.date 非空率＋三档（归一日／原始串）＋同窗跨信源。"""
    set_source_time_unified(False)
    set_ledger_time_class(False)
    off_facts = 0
    off_dated = 0
    set_source_time_unified(True)
    on_facts = 0
    on_dated = 0
    day_c: Counter = Counter()
    raw_c: Counter = Counter()
    same_cross = 0
    n_cand = 0
    for case_dir in sorted(Path(cases_root).iterdir()):
        if not (case_dir / "raw_documents.json").is_file():
            continue
        set_source_time_unified(False)
        d_off = load_official_case(case_dir)
        facts_off = extract_facts(d_off)
        off_facts += len(facts_off)
        off_dated += sum(1 for f in facts_off if f.date)

        set_source_time_unified(True)
        d_on = load_official_case(case_dir)
        facts_on = extract_facts(d_on)
        on_facts += len(facts_on)
        on_dated += sum(1 for f in facts_on if f.date)
        cols = find_collisions(d_on, facts=facts_on)
        src_by_id = {s.id: s for s in d_on.sources}
        seen: set[tuple[str, str]] = set()
        for c in cols:
            key = (c.entity.lower(), c.metric)
            if key in seen:
                continue
            seen.add(key)
            n_cand += 1
            # 归一日臂＝Fact.date（统一读点已是 YYYYMMDD）
            dates = [f.date for f in c.facts]
            td = classify_time_class(dates)
            # 原始串臂＝信源 meta 原 ISO（publish_time／published_at），
            # 否则归一后 raw≡day，对照臂失去牙
            raw_dates = []
            for f in c.facts:
                src = src_by_id.get(f.source_id)
                if src is None:
                    raw_dates.append("")
                    continue
                raw = (str(src.meta.get("published_at") or "")
                       or str(src.meta.get("publish_time") or "")
                       or str(src.meta.get("year") or ""))
                raw_dates.append(raw.strip())
            tr = raw_time_class(raw_dates)
            day_c[td] += 1
            raw_c[tr] += 1
            if td == "same_window" and c.cross_source:
                same_cross += 1
    set_source_time_unified(False)
    return {
        "n_candidates": n_cand,
        "fact_date_rate_off": (off_dated, off_facts),
        "fact_date_rate_on": (on_dated, on_facts),
        "day_norm": dict(day_c),
        "raw_str": dict(raw_c),
        "same_window_cross_source": same_cross,
    }


def _block_stats(reports: list[Path]) -> tuple[int, int]:
    """当前旗下 facts_block 总字数／总条数（\\n- 计数，18 题相加）。"""
    n_chars = 0
    n_rows = 0
    for rp in reports:
        d = Dossier.from_dict(json.loads(rp.read_text(encoding="utf-8")))
        block = facts_block(d)
        n_chars += len(block)
        n_rows += block.count("\n- ")
    return n_chars, n_rows


def measure_injection(run_root: Path) -> dict:
    """注入面条数／跨信源／时点标记；as_of 触发与黄牌（开关开）；三态字数。"""
    reports = sorted(Path(run_root).rglob("report.json"))

    # 三态字数／条数（R-C69-1 件⑥）：关/关｜开/关｜开/开
    set_source_time_unified(False)
    set_ledger_time_class(False)
    chars_off_off, rows_off_off = _block_stats(reports)
    set_source_time_unified(True)
    set_ledger_time_class(False)
    chars_on_off, rows_on_off = _block_stats(reports)
    set_source_time_unified(True)
    set_ledger_time_class(True)
    chars_on_on, rows_on_on = _block_stats(reports)

    set_source_time_unified(False)
    set_ledger_time_class(False)
    n_inj = n_cross = n_time_mark = 0
    for rp in reports:
        d = Dossier.from_dict(json.loads(rp.read_text(encoding="utf-8")))
        cols = find_collisions(d)[:8]
        n_inj += len(cols)
        n_cross += sum(1 for c in cols if c.cross_source)
        n_time_mark += facts_block(d).count("（时点")

    # 叫醒三项：开关打开后 as_of trigger／黄牌／时点标记
    set_source_time_unified(True)
    n_asof_trig = 0
    n_asof_flag = 0
    n_time_on = 0
    for rp in reports:
        raw = json.loads(rp.read_text(encoding="utf-8"))
        d = Dossier.from_dict(raw)
        skills = detect_skills(d)
        if any(s.name == "as_of_discipline" for s in skills):
            n_asof_trig += 1
        flags = audit_temporal(d)
        n_asof_flag += sum(1 for f in flags if f.get("kind") == "as_of")
        set_ledger_time_class(True)
        n_time_on += facts_block(d).count("（时点")
        set_ledger_time_class(False)
    set_source_time_unified(False)
    return {
        "n_reports": len(reports),
        "inject_n": n_inj,
        "inject_cross": n_cross,
        "time_mark_off": n_time_mark,
        "as_of_trigger_on": n_asof_trig,
        "as_of_flags_on": n_asof_flag,
        "time_mark_on": n_time_on,
        "chars_off_off": chars_off_off,
        "rows_off_off": rows_off_off,
        "chars_on_off": chars_on_off,
        "rows_on_off": rows_on_off,
        "chars_on_on": chars_on_on,
        "rows_on_on": rows_on_on,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="C-69 时间轴量尺")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印将要量的路径（默认）")
    p.add_argument("--from", dest="run_root", type=Path, default=None,
                   help="跑次目录（含 report.json）")
    p.add_argument("--cases", type=Path, default=None,
                   help="官方案卷根（含各案 raw_documents.json）")
    args = p.parse_args(argv)

    run_root = args.run_root
    cases = args.cases
    if args.dry_run or (run_root is None and cases is None):
        print("mode=dry-run（零 HTTP 零模型；加 --from／--cases 才量）")
        print(f"  would --from {run_root or '/tmp/six2'}")
        print(f"  would --cases {cases or '<official-cases-root>'}")
        return 0

    if cases is not None:
        raw = measure_raw_docs(cases)
        print("=== 原料三态 ===")
        print(f"n_docs={raw['n_docs']} full_iso={raw['n_full_iso']} "
              f"present_non_iso={raw['n_present_non_iso']} "
              f"key_missing={raw['n_key_missing']}")
        col = measure_collisions(cases)
        print("=== 两臂 Fact.date 非空 ===")
        print(f"off {col['fact_date_rate_off'][0]}/{col['fact_date_rate_off'][1]}")
        print(f"on  {col['fact_date_rate_on'][0]}/{col['fact_date_rate_on'][1]}")
        print("=== 三档（按案去重）===")
        print(f"n_candidates={col['n_candidates']}")
        print(f"day_norm={col['day_norm']}")
        print(f"raw_str={col['raw_str']}")
        print(f"same_window_cross_source={col['same_window_cross_source']}")

    if run_root is not None:
        inj = measure_injection(run_root)
        print("=== 注入面（开关关）===")
        print(f"n_reports={inj['n_reports']} inject={inj['inject_n']} "
              f"cross={inj['inject_cross']} time_mark={inj['time_mark_off']}")
        print("=== 叫醒（开关开）===")
        print(f"as_of_trigger={inj['as_of_trigger_on']}/{inj['n_reports']} "
              f"as_of_flags={inj['as_of_flags_on']} "
              f"time_mark_on={inj['time_mark_on']}")
        # R-C69-1 件⑥：三态字数／条数（条数恒＝件② 地板）
        print("=== 三态字数（关/关｜开/关｜开/开）===")
        print(f"off/off chars={inj['chars_off_off']} rows={inj['rows_off_off']}")
        print(f"on/off  chars={inj['chars_on_off']} rows={inj['rows_on_off']}")
        print(f"on/on   chars={inj['chars_on_on']} rows={inj['rows_on_on']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
