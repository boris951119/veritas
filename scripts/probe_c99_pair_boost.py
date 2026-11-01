#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-99：审阅分＋A0 软保底（B=7000）配对评估。

主尺＝刘翔（冻结 /tmp/c85_k180，零新调用）开／关装箱 L2。
旁证＝恒兴新材 HX-Q1/Q2/Q3：本机构建小案卷 → 抽锚＋审 B（K=60）
→ A0 vs Boost 装箱；尺＝出处文件段是否进箱＋accept 字面是否进箱文。
不作官方涨分声称；默认关；不改生产。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c99_pair_boost.py \\
      --out-dir /tmp/c99_pair
  # 跳过恒兴 LLM 旁证（只跑刘翔）
  ... --skip-hengxing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.ingest.case_loader import load_case  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from scripts.probe_c62_rerank_arms import build_candidates  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import (  # noqa: E402
    _fallback_anchors,
    _fuse,
    _gold_keys,
    _score_batches,
    extract_anchors,
)
from scripts.probe_c84_llm_rerank import _lock_local  # noqa: E402
from scripts.probe_c91_mono_pack import _pack_score_primary  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

CASE_SUB = "刘翔"
DEFAULT_C85 = Path("/tmp/c85_k180")
HX_ROOT = Path.home() / "Desktop/veritas-testcases/eval-corpus/恒兴新材"
HX_QFILE = HX_ROOT / "questions-10.jsonl"
B_FIXED = 7000.0
HX_IDS = ("HX-Q1", "HX-Q2", "HX-Q3")
HX_K = 60
HX_BUDGET = 12_000
HX_NOISE = 8
DEFAULT_MODEL = "veritas-qwen3-14b:latest"


def _id_scores(sc: Any, job: dict) -> dict[str, float]:
    if isinstance(sc, dict):
        return {str(k): float(v) for k, v in sc.items()}
    return {cid: float(s) for cid, s in zip(job["ids"], sc)}


def _boost_pack(
    dossier: Dossier, budget: int, fused: dict[str, float], sel_a0: set[str], B: float,
) -> set[str]:
    boosted = dict(fused)
    for sid in sel_a0:
        boosted[sid] = float(boosted.get(sid, 0.0)) + float(B)
    return _pack_score_primary(dossier, budget, boosted)


def run_liuxiang(
    *, gold_dir: Path, cases_root: Path, c85_dir: Path,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    jobs = [
        j for j in json.loads((c85_dir / "score_input.json").read_text(encoding="utf-8"))
        if CASE_SUB in j["case"]
    ]
    jobs = sorted(jobs, key=lambda j: j["qid"])
    scores_c = json.loads((c85_dir / "llm_scores_c.json").read_text(encoding="utf-8"))
    rows = []
    tot = {"a0": 0, "on_hits": 0, "on_lost": 0, "on_gained": 0, "denom": 0}
    for job in jobs:
        case, qid, query = job["case"], job["qid"], job["query"]
        budget = int(job["budget"])
        dossier = load_official_case(cases_root / case)
        dossier.question = query
        gold, denom = _gold_keys(gold_dir, case, qid)
        key = f"{case}::{qid}"
        id_sc = _id_scores(scores_c[key], job)
        bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        for sid in id_sc:
            bm25.setdefault(sid, 0.0)
        fused = _fuse(bm25, id_sc, use_bm25=True)

        p0 = pack_material(dossier, budget_chars=budget)
        sel_a0 = {str(x) for x in (p0.get("selected") or [])}
        loc_a0 = selected_locs(dossier, sel_a0)
        a0_hits = l2_hits(gold, loc_a0)

        sel_on = _boost_pack(dossier, budget, fused, sel_a0, B_FIXED)
        loc_on = selected_locs(dossier, sel_on)
        on_hits = l2_hits(gold, loc_on)
        lost = len((gold & loc_a0) - loc_on)
        gained = len((gold & loc_on) - loc_a0)

        rows.append({
            "qid": qid, "denom": denom, "budget": budget,
            "off_A0": {"hits": a0_hits, "n": len(sel_a0)},
            "on_boost": {
                "hits": on_hits, "lost": lost, "gained": gained,
                "n": len(sel_on), "B": B_FIXED,
            },
        })
        tot["a0"] += a0_hits
        tot["on_hits"] += on_hits
        tot["on_lost"] += lost
        tot["on_gained"] += gained
        tot["denom"] += denom

    improve = (
        tot["on_lost"] == 0
        and tot["on_hits"] >= tot["a0"]
        and tot["on_gained"] > 0
    )
    return {
        "ruler": "刘翔",
        "B": B_FIXED,
        "A0_hits": tot["a0"],
        "on_hits": tot["on_hits"],
        "lost": tot["on_lost"],
        "gained": tot["on_gained"],
        "denom": tot["denom"],
        "improve_pass": improve,
        "status": (
            "IMPROVE" if improve
            else ("FLAT" if tot["on_lost"] == 0 and tot["on_hits"] >= tot["a0"]
                  else "ESCAPE")
        ),
        "rows": rows,
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "note": "冻结 C-85 分；开＝融合分+A0软保底 B=7000；关＝现产 A0",
    }


def _load_hx_questions() -> list[dict]:
    if not HX_QFILE.is_file():
        raise SystemExit(f"缺恒兴题库 {HX_QFILE}")
    all_q = [
        json.loads(line)
        for line in HX_QFILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {q["id"]: q for q in all_q}
    out = []
    for qid in HX_IDS:
        if qid not in by_id:
            raise SystemExit(f"缺题 {qid}")
        out.append(by_id[qid])
    return out


def _pick_noise(corpus: Path, gold_names: set[str], qid: str, n: int) -> list[Path]:
    pdfs = sorted(
        p for p in corpus.glob("*.pdf")
        if p.name not in gold_names and p.stat().st_size > 1000
    )
    # 确定性洗牌
    scored = []
    for p in pdfs:
        h = hashlib.sha256(f"{qid}:{p.name}".encode()).hexdigest()
        scored.append((h, p))
    scored.sort()
    return [p for _, p in scored[:n]]


def _build_hx_case(
    work: Path, q: dict, corpus: Path,
) -> Path:
    case_dir = work / q["id"]
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)
    material = case_dir / "材料"
    material.mkdir()
    gold_files = []
    for name in q.get("source_files") or []:
        src = corpus / name
        if not src.is_file():
            raise SystemExit(f"{q['id']} 缺出处文件 {name}")
        dst = material / name
        if not dst.exists():
            os.symlink(src.resolve(), dst)
        gold_files.append(name)
    noise = _pick_noise(corpus, set(gold_files), q["id"], HX_NOISE)
    for p in noise:
        dst = material / p.name
        if not dst.exists():
            os.symlink(p.resolve(), dst)
    # manifest
    import yaml
    sources = [{"file": f"材料/{name}", "type": "report"} for name in gold_files]
    sources += [{"file": f"材料/{p.name}", "type": "report"} for p in noise]
    (case_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {"question": q["question"], "sources": sources},
            allow_unicode=True, sort_keys=False, width=10_000,
        ),
        encoding="utf-8",
    )
    meta = {
        "gold_files": gold_files,
        "noise_files": [p.name for p in noise],
        "accept": q.get("accept") or [],
    }
    (case_dir / "c99_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return case_dir


def _source_file_of(dossier: Dossier, seg_id: str) -> str:
    for src in dossier.sources:
        for seg in src.segments:
            if seg.id == seg_id:
                # path / title / id
                meta = src.meta or {}
                for key in ("path", "file", "filename", "title"):
                    v = meta.get(key) if isinstance(meta, dict) else None
                    if v:
                        return str(v)
                return src.id or ""
    return ""


def _pack_metrics(
    dossier: Dossier, selected: set[str], gold_files: list[str], accept: list[str],
) -> dict[str, Any]:
    gold_basenames = {Path(f).name for f in gold_files}
    n_gold_seg = 0
    blob = []
    for sid in selected:
        path = _source_file_of(dossier, sid)
        base = Path(path).name if path else ""
        # 路径里含出处文件名也算
        hit = any(g in path or g == base for g in gold_basenames)
        if hit:
            n_gold_seg += 1
        seg = dossier.segment(sid)
        if seg is not None:
            blob.append(seg.text or "")
    text = "\n".join(blob)
    accept_hits = [a for a in accept if a and a in text]
    return {
        "n_selected": len(selected),
        "n_from_gold_source": n_gold_seg,
        "gold_source_ratio": round(
            n_gold_seg / max(len(selected), 1), 4),
        "accept_hits": accept_hits,
        "n_accept_hit": len(accept_hits),
        "n_accept": len(accept),
    }


def run_hengxing(
    *,
    work: Path,
    model: str,
    batch_size: int,
) -> dict[str, Any]:
    _lock_local()
    qs = _load_hx_questions()
    work.mkdir(parents=True, exist_ok=True)
    score_dir = work / "hx_scores"
    score_dir.mkdir(parents=True, exist_ok=True)

    # prepare jobs
    jobs = []
    dossiers: dict[str, Dossier] = {}
    metas: dict[str, dict] = {}
    t_ingest = time.perf_counter()
    for q in qs:
        case_dir = _build_hx_case(work / "cases", q, HX_ROOT)
        print(f"  摄取 {q['id']} …", flush=True)
        dossier = load_case(case_dir)
        dossier.question = q["question"]
        dossiers[q["id"]] = dossier
        meta = json.loads((case_dir / "c99_meta.json").read_text(encoding="utf-8"))
        metas[q["id"]] = meta
        query, cands, bm25_scores, _ = build_candidates(dossier, n=HX_K)
        text_of = {
            seg.id: (seg.text or "")
            for src in dossier.sources for seg in src.segments
        }
        jobs.append({
            "case": "恒兴新材",
            "qid": q["id"],
            "query": query or q["question"],
            "budget": HX_BUDGET,
            "ids": [c["id"] for c in cands],
            "texts": [text_of.get(c["id"], "") for c in cands],
            "bm25_scores": {str(k): float(v) for k, v in bm25_scores.items()},
        })
    ingest_s = round(time.perf_counter() - t_ingest, 1)
    (score_dir / "score_input.json").write_text(
        json.dumps(jobs, ensure_ascii=False), encoding="utf-8")

    # anchors + score B
    print("  抽锚＋审 B …", flush=True)
    t_score = time.perf_counter()
    anchors = extract_anchors(score_dir, model=model, limit=None)
    cache_path = score_dir / "llm_scores_b.json"
    done: dict[str, list[float]] = {}
    if cache_path.is_file():
        done = json.loads(cache_path.read_text(encoding="utf-8"))
    n_calls = 0
    for ji, job in enumerate(jobs, 1):
        key = f"{job['case']}::{job['qid']}"
        if key in done and len(done[key]) == len(job["ids"]):
            print(f"  审B [{ji}/{len(jobs)}] {key} 缓存", flush=True)
            continue
        anc = anchors.get(key) or _fallback_anchors(job["query"])
        sc, c = _score_batches(
            job["query"], anc, job["texts"],
            model=model, batch_size=batch_size,
        )
        n_calls += c
        done[key] = sc
        cache_path.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        print(f"  审B [{ji}/{len(jobs)}] {key} calls+={c}", flush=True)
    score_s = round(time.perf_counter() - t_score, 1)

    rows = []
    for job in jobs:
        qid = job["qid"]
        dossier = dossiers[qid]
        meta = metas[qid]
        budget = int(job["budget"])
        key = f"{job['case']}::{qid}"
        id_list_scores = done[key]
        id_sc = {
            sid: float(sc) for sid, sc in zip(job["ids"], id_list_scores)
        }
        bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        for sid in id_sc:
            bm25.setdefault(sid, 0.0)
        # 非候选段 bm25 已在全表
        fused = _fuse(bm25, id_sc, use_bm25=True)

        p0 = pack_material(dossier, budget_chars=budget)
        sel_a0 = {str(x) for x in (p0.get("selected") or [])}
        sel_on = _boost_pack(dossier, budget, fused, sel_a0, B_FIXED)

        off_m = _pack_metrics(
            dossier, sel_a0, meta["gold_files"], meta["accept"])
        on_m = _pack_metrics(
            dossier, sel_on, meta["gold_files"], meta["accept"])
        rows.append({
            "qid": qid,
            "question": job["query"][:80],
            "gold_files": meta["gold_files"],
            "off_A0": off_m,
            "on_boost": {**on_m, "B": B_FIXED},
            "delta_gold_segs": (
                on_m["n_from_gold_source"] - off_m["n_from_gold_source"]
            ),
            "delta_accept": on_m["n_accept_hit"] - off_m["n_accept_hit"],
        })

    return {
        "ruler": "恒兴旁证（非官方金标）",
        "ids": list(HX_IDS),
        "B": B_FIXED,
        "k": HX_K,
        "budget": HX_BUDGET,
        "noise_n": HX_NOISE,
        "model": model,
        "ingest_s": ingest_s,
        "score_s": score_s,
        "score_calls_b": n_calls,
        "rows": rows,
        "note": (
            "尺＝出处文件段落进箱数＋accept 字面命中；"
            "案卷＝出处 PDF＋8 份噪声 PDF；与刘翔 L2 不可混比"
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="C-99 pair boost eval")
    ap.add_argument("--out-dir", type=Path, default=Path("/tmp/c99_pair"))
    ap.add_argument("--c85-dir", type=Path, default=DEFAULT_C85)
    ap.add_argument("--gold-dir", type=Path, default=None)
    ap.add_argument("--cases-root", type=Path, default=None)
    ap.add_argument("--skip-hengxing", action="store_true")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--batch-size", type=int, default=12)
    args = ap.parse_args()
    gold = args.gold_dir or DEFAULT_GOLD
    cases = args.cases_root or DEFAULT_GOLD
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("=== C-99 刘翔主尺（开/关）===", flush=True)
    lx = run_liuxiang(gold_dir=gold, cases_root=cases, c85_dir=args.c85_dir)
    print(
        f"A0 {lx['A0_hits']}/{lx['denom']} → on {lx['on_hits']}/{lx['denom']} "
        f"lost={lx['lost']} gained={lx['gained']} [{lx['status']}]",
        flush=True,
    )
    (args.out_dir / "liuxiang.json").write_text(
        json.dumps(lx, ensure_ascii=False, indent=2), encoding="utf-8")

    hx = None
    if not args.skip_hengxing:
        print("=== C-99 恒兴旁证 HX-Q1/2/3 ===", flush=True)
        hx = run_hengxing(
            work=args.out_dir / "hengxing",
            model=args.model,
            batch_size=args.batch_size,
        )
        for r in hx["rows"]:
            print(
                f"{r['qid']}: gold_segs "
                f"{r['off_A0']['n_from_gold_source']}→"
                f"{r['on_boost']['n_from_gold_source']} "
                f"(Δ{r['delta_gold_segs']:+d}); accept "
                f"{r['off_A0']['n_accept_hit']}→"
                f"{r['on_boost']['n_accept_hit']} "
                f"(Δ{r['delta_accept']:+d})",
                flush=True,
            )
        (args.out_dir / "hengxing.json").write_text(
            json.dumps(hx, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "ticket": "C-99",
        "B_fixed": B_FIXED,
        "liuxiang": {
            k: lx[k] for k in (
                "A0_hits", "on_hits", "lost", "gained", "denom",
                "improve_pass", "status", "elapsed_s",
            )
        },
        "hengxing": None if hx is None else {
            "ids": hx["ids"],
            "score_s": hx["score_s"],
            "score_calls_b": hx["score_calls_b"],
            "rows_brief": [
                {
                    "qid": r["qid"],
                    "delta_gold_segs": r["delta_gold_segs"],
                    "delta_accept": r["delta_accept"],
                    "off_accept": r["off_A0"]["n_accept_hit"],
                    "on_accept": r["on_boost"]["n_accept_hit"],
                }
                for r in hx["rows"]
            ],
        },
        "recommendation": {
            "go_nogo": (
                "GO_CANDIDATE" if lx["improve_pass"] else "NO_GO"
            ),
            "reason": (
                "刘翔 IMPROVE（B=7000）；恒兴仅旁证参考；"
                "仍默认关——合入须用户拍 + 可选全链路真跑"
                if lx["improve_pass"]
                else "刘翔未 IMPROVE，不合入"
            ),
            "production_default": "仍关",
        },
        "note": (
            "配对＝同案卷关/开装箱；刘翔用冻结审阅分；"
            "恒兴现场抽锚审 B；非官方涨分"
        ),
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("go_nogo", summary["recommendation"]["go_nogo"])
    print("wrote", args.out_dir)


if __name__ == "__main__":
    main()
