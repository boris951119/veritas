"""C-7 容量实测探针（架构师用，非生产路径、不进 tests）。

问题：单专题 ≤2000 篇时，输入层那三道天花板各自的代价与收益是多少——
① 摄取封顶 500 文件（`case_loader._collect_files`）
② 大库选料预算 `material_char_budget`（默认 8 万字）与 `corpus_index._MAX_SOURCES`（50 份）
③ 装箱进提示词

跑法（本机全程 21.9s，零 LLM、零网络，产物只落 /tmp/c7_bench，不碰仓库）：
    PYTHONPATH=. .venv/bin/python scripts/measure_capacity.py
    N_FILES=500 CHARS=3000 PYTHONPATH=. .venv/bin/python scripts/measure_capacity.py

读法：[2]/[3] 比的是「抬不抬 500」的摄取代价；[5-*] 的份数才是召回的真实上界；
最后那段预算扫描告诉你预算抬到多少才会撞上第二道墙（50 份）。
"""
from __future__ import annotations

import os
import random
import resource
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path("/tmp/c7_bench")
N_FILES = int(os.environ.get("N_FILES", "2000"))
CHARS = int(os.environ.get("CHARS", "3000"))
QUESTION = os.environ.get("QUESTION", "华东集团1的停工与欠薪风险有多大？")

TOPICS = ["回款", "停工", "伤亡", "融资", "投诉", "产能", "减持", "召回", "停产", "欠薪"]
ENTS = [f"华{c}集团{i}" for c in "东南西北" for i in range(50)]


def build() -> Path:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    case = ROOT / "case"
    case.mkdir(parents=True)
    (case / "manifest.yaml").write_text(f"question: {QUESTION}\n", encoding="utf-8")
    rnd = random.Random(7)
    for i in range(N_FILES):
        d = case / f"batch{i // 500}"
        d.mkdir(exist_ok=True)
        ent = rnd.choice(ENTS)
        body: list[str] = []
        while sum(len(x) for x in body) < CHARS:
            t = rnd.choice(TOPICS)
            body.append(f"{ent}于本月涉及{t}事项，据内部通报第{rnd.randint(1, 20)}条，"
                        f"涉及金额{rnd.randint(1, 9999)}万元，影响人数{rnd.randint(0, 800)}人。"
                        f"另有{t}相关的补充说明若干条，以官方口径为准。")
        text = "\n\n".join(body)[:CHARS]
        (d / f"news{i:05d}.md").write_text(
            f"# {ent}{rnd.choice(TOPICS)}通报\n\n{text}\n", encoding="utf-8")
    return case


def nseg(dossier) -> int:
    return sum(len(src.segments) for src in dossier.sources)


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


def main() -> None:
    from app.ingest import case_loader
    from app.ingest.case_loader import _collect_files, load_case

    case = build()
    total_bytes = sum(f.stat().st_size for f in case.rglob("*.md"))
    print(f"材料：{N_FILES} 份 × ~{CHARS} 字，磁盘合计 {total_bytes / 1024 / 1024:.1f} MB，"
          f"目录层级 2（batchNNN/）")

    t0 = time.perf_counter()
    c = _collect_files(case)
    print(f"[1] 现口径遍历（封顶 500）：{time.perf_counter() - t0:.2f}s "
          f"→ taken={c.taken} skipped={c.skipped} truncated={c.truncated}")

    t0 = time.perf_counter()
    # d500＝默认封顶 500 下的 load_case 结果（C-7 后仍可读 Settings，默认不变）
    d500 = load_case(case)
    print(f"[2] 现口径摄取 {len(d500.sources)} 份 → load_case："
          f"{time.perf_counter() - t0:.2f}s segments={nseg(d500)} 峰值RSS≈{rss_mb():.0f}MB")

    orig = case_loader._collect_files

    def uncapped(d: Path, max_files: int = N_FILES + 10,
                 max_depth: int = 3):
        return orig(d, max_files=max_files, max_depth=max_depth)

    case_loader._collect_files = uncapped
    try:
        t0 = time.perf_counter()
        dall = load_case(case)
        el_all = time.perf_counter() - t0
    finally:
        case_loader._collect_files = orig
    print(f"[3] 抬上限后摄取 {len(dall.sources)} 份 → load_case：{el_all:.2f}s "
          f"segments={nseg(dall)} 峰值RSS≈{rss_mb():.0f}MB "
          f"（每份均摊 {el_all / max(1, len(dall.sources)) * 1000:.1f}ms）")

    from app.core.corpus_store import DiskCorpusIndex, index_case

    def run_index(tag: str, raise_cap: bool) -> Path:
        db = ROOT / f"corpus_{tag}.sqlite"
        if db.exists():
            db.unlink()
        if raise_cap:
            case_loader._collect_files = uncapped
        t0 = time.perf_counter()
        try:
            index, shell = index_case(case, db)
        finally:
            case_loader._collect_files = orig
        size = db.stat().st_size / 1024 / 1024 if db.exists() else 0
        print(f"[4-{tag}] .corpus 建库：{time.perf_counter() - t0:.2f}s → 库体积 {size:.1f}MB "
              f"live_sources={index.live_source_count()} 峰值RSS≈{rss_mb():.0f}MB"
              "（注意 create() 每次先删旧库＝无缓存）")
        return db

    db_now = run_index("现口径", False)
    db_up = run_index("抬上限", True)

    def budget_sweep(path: Path, label: str) -> None:
        idx = DiskCorpusIndex.open(path)
        total = idx.live_source_count()
        segs = sqlite3.connect(path).execute("select count(*) from segments").fetchone()[0]
        print(f"  [{label}] 库内 {total} 份 / {segs} 段")
        for budget in (80_000, 160_000, 320_000, 640_000):
            t0 = time.perf_counter()
            d = idx.select(QUESTION, material_budget=budget).dossier
            n = len(d.sources)
            chars = sum(len(x.text) for s in d.sources for x in s.segments)
            print(f"    预算 {budget // 1000:>5}k → {n:>3} 份 / {nseg(d):>4} 段 / "
                  f"实装 {chars / 10000:5.1f} 万字 ＝库内份数的 "
                  f"{n / max(1, total) * 100:.1f}%  {time.perf_counter() - t0:.2f}s")

    budget_sweep(db_now, "现口径＝索引只到 500 份")
    budget_sweep(db_up, f"抬上限＝索引全量 {N_FILES} 份")


if __name__ == "__main__":
    main()
