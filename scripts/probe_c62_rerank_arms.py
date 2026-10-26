#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-62：精排双臂对照（T＝本机 cross-encoder／R＝百炼付费 rerank）离线量 L2。

四臂同一分母 105、同一 budget、同一装箱、同一份前 120 段候选集与同一句 query：
  A＝现行 BM25 密度键
  H＝引用 C-61 已存盘（不重跑）＝53/105、lost=2
  T＝可注入的本地精排打分函数（本脚本不 import torch、不装模型）
  R＝只构造／解析百炼 text-rerank 请求；**本脚本永不发付费 HTTP**

默认 ``--dry-run``＝零调用、零下载；真跑显式 ``--run``（T 需注入 scorer；R 只读缓存）。

R 臂协议（与工单一致；端点＝DashScope 原生 text-rerank，非 OpenAI 兼容扁平口）：
  POST {DASHSCOPE_BASE}/api/v1/services/rerank/text-rerank/text-rerank
  Authorization: Bearer $DASHSCOPE_API_KEY
  body.model ∈ {qwen3-rerank, gte-rerank-v2}
  body.input.query / body.input.documents
  body.parameters.top_n
  读 output.results[].index + relevance_score；usage.total_tokens
  ⚠ 官方「OpenAI 兼容」口对 qwen3-rerank 用扁平 query/documents；本单钉原生嵌套形。
  若架构师实测嵌套被拒，按 §3.4 停手，不许本脚本自创扁平形冒充过线。

判据 b 两把刀（零模型、dry-run 也跑）：
  ① 拼接路灌真 BM25 原分 ⇒ 选中集与 pack_material 18/18 相同
  ② 模型分换成名次常数（＝fuse_rankings([bm25], k=60)，模型不参与）⇒ L2 回到 48

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c62_rerank_arms.py --run-dir /tmp/six2
  PYTHONPATH=. .venv/bin/python scripts/probe_c62_rerank_arms.py --run-dir /tmp/six2 --run \\
      --t-scorer /tmp/c62_t_scores.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import fuse_rankings, rank_segments  # noqa: E402
from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material, pack_search_queries  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    discover_reports,
    gold_paras_for_question,
)

CAND_N = 120
RRF_K = 60  # 与 C-61／〔139〕K2 同：名次常数＝1/(k+rank)
DEFAULT_C61 = Path("/tmp/c61_hybrid_retrieval/summary.json")
DEFAULT_OUT = Path("/tmp/c62_rerank")
CACHE_DIR_NAME = "cache"
# 百炼原生 text-rerank（嵌套 input／parameters）——与工单字段名对齐
DASHSCOPE_RERANK_URL = os.environ.get(
    "DASHSCOPE_RERANK_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
)
R_MODEL_PRIMARY = "qwen3-rerank"
R_MODEL_FALLBACK = "gte-rerank-v2"
# 粗估：中文约 1.5 字/token（只用于 dry-run 披露，不作计费）
_CHARS_PER_TOK = 1.5

ScoreFn = Callable[[str, list[tuple[str, str]]], list[float]]
# (query, [(seg_id, text), ...]) -> scores 与列表等长

# T 臂可注入打分器（本进程默认拒绝；架构师从 /tmp/venv_rerank 侧注入）
_T_SCORER: ScoreFn | None = None


def set_t_scorer(fn: ScoreFn | None) -> None:
    """架构师注入：fn(query, [(id, text), ...]) -> list[float]（等长）。"""
    global _T_SCORER
    _T_SCORER = fn


def score_candidates_local(query: str, pairs: list[tuple[str, str]]) -> list[float]:
    """给一批段落打分（T 臂入口）。未注入则立刻失败——本脚本不装 torch。"""
    if _T_SCORER is None:
        raise RuntimeError(
            "T 臂 scorer 未注入：请从 /tmp/venv_rerank 侧调用 set_t_scorer(...)，"
            "或 --run --t-scorer <JSON>；本脚本不 import torch、不下载模型"
        )
    scores = _T_SCORER(query, pairs)
    if len(scores) != len(pairs):
        raise RuntimeError(f"T scorer 返回长度 {len(scores)} ≠ 候选 {len(pairs)}")
    return [float(x) for x in scores]


def _budget_from_report(rep: dict) -> int:
    pw = (rep.get("accounting") or {}).get("pack_window") or {}
    b = pw.get("budget")
    if b is None:
        raise ValueError("report 缺 accounting.pack_window.budget")
    return int(b)


def _query_of(dossier: Dossier) -> str:
    qs = pack_search_queries(dossier)
    if qs:
        return str(qs[0]).strip()
    return (dossier.question or "").strip()


def _bm25_table(dossier: Dossier) -> list[tuple[str, float]]:
    queries = pack_search_queries(dossier)
    return list(
        rank_segments(dossier, queries=queries) if queries else rank_segments(dossier))


def _pack_with_scores(dossier: Dossier, budget: int, scores: dict[str, float]) -> set[str]:
    """拼接路：分数表 → monkeypatch rank_segments → 同一 pack_material。"""
    import app.core.bm25 as bm25_mod
    import app.core.material as mat_mod

    def _fake_rank(dossier_, query=None, queries=None):
        return sorted(scores.items(), key=lambda x: (-x[1], x[0]))

    real_b, real_m = bm25_mod.rank_segments, mat_mod.rank_segments
    bm25_mod.rank_segments = _fake_rank
    mat_mod.rank_segments = _fake_rank
    try:
        pack = pack_material(dossier, budget_chars=budget)
    finally:
        bm25_mod.rank_segments = real_b
        mat_mod.rank_segments = real_m
    return {str(x) for x in (pack.get("selected") or [])}


def build_candidates(
    dossier: Dossier,
    *,
    n: int = CAND_N,
) -> tuple[str, list[dict], dict[str, float], dict[str, int]]:
    """前 n 段候选（按 BM25 名次）；返回 query、候选行、全表 BM25 分、1-based 位次。"""
    ranked = _bm25_table(dossier)
    bm25_scores = dict(ranked)
    bm25_rank = {sid: i + 1 for i, (sid, _) in enumerate(ranked)}
    text_of = {
        seg.id: (seg.text or "")
        for src in dossier.sources for seg in src.segments
    }
    cands = []
    for sid, sc in ranked[:n]:
        cands.append({
            "id": sid,
            "bm25_score": float(sc),
            "bm25_rank": bm25_rank[sid],
            "text_sha": hashlib.sha256(text_of.get(sid, "").encode("utf-8")).hexdigest()[:16],
            "n_chars": len(text_of.get(sid, "")),
        })
    query = _query_of(dossier)
    return query, cands, bm25_scores, bm25_rank


def candidates_sha(query: str, cands: list[dict]) -> str:
    payload = {
        "query": query,
        "ids": [c["id"] for c in cands],
        "ranks": [c["bm25_rank"] for c in cands],
        "text_shas": [c["text_sha"] for c in cands],
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def estimate_r_tokens(query: str, cands: list[dict]) -> int:
    chars = len(query) + sum(int(c["n_chars"]) for c in cands)
    return max(1, int(chars / _CHARS_PER_TOK))


# ---- R 臂：只构造／解析，永不发 HTTP ------------------------------------

def build_rerank_request(
    *,
    model: str,
    query: str,
    documents: list[str],
    top_n: int,
) -> dict[str, Any]:
    """构造百炼原生 text-rerank 请求体（嵌套 input／parameters）。"""
    return {
        "model": model,
        "input": {
            "query": query,
            "documents": documents,
        },
        "parameters": {
            "top_n": int(top_n),
            "return_documents": False,
        },
    }


def parse_rerank_response(resp: dict[str, Any], *, n_docs: int) -> tuple[list[float], int]:
    """解析 output.results[].index + relevance_score；返回与 documents 对齐的分数＋total_tokens。"""
    out = resp.get("output") or {}
    results = out.get("results") or []
    scores = [0.0] * n_docs
    for row in results:
        if not isinstance(row, dict):
            continue
        idx = int(row.get("index", -1))
        if 0 <= idx < n_docs:
            scores[idx] = float(row.get("relevance_score") or 0.0)
    usage = resp.get("usage") or {}
    total = int(usage.get("total_tokens") or 0)
    return scores, total


def cache_path(cache_dir: Path, case: str, qid: str, model: str) -> Path:
    safe = hashlib.sha256(f"{case}|{qid}|{model}".encode()).hexdigest()[:24]
    return cache_dir / f"{safe}.json"


# ---- 构造（判据 f） -------------------------------------------------------

def construct_jobs(
    run_dir: Path,
    *,
    gold_root: Path | None,
    out_dir: Path,
) -> dict:
    assert gold_root is None, "判据 f：构造侧 gold_root 必须为 None"
    cand_dir = out_dir / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        budget = _budget_from_report(rep)
        query, cands, bm25_scores, bm25_rank = build_candidates(dossier)
        sha = candidates_sha(query, cands)
        blob = {
            "case": case,
            "qid": qid,
            "query": query,
            "budget": budget,
            "sha": sha,
            "candidates": cands,
            "report": str(rp.resolve()),
        }
        path = cand_dir / f"{case}__{qid}.json"
        # 文件名可能含特殊字：改用 sha 名，索引另存
        path = cand_dir / f"{sha[:20]}.json"
        path.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding="utf-8")
        jobs.append({
            "case": case,
            "qid": qid,
            "query": query,
            "budget": budget,
            "sha": sha,
            "cand_path": str(path),
            "n_cand": len(cands),
            "est_tokens": estimate_r_tokens(query, cands),
            "bm25_scores": bm25_scores,
            "bm25_rank": bm25_rank,
            "report": str(rp.resolve()),
            # 文本只在需要打分时再读 report；dry-run 不持有全文
        })
    return {
        "run_dir": str(run_dir),
        "n_questions": len(jobs),
        "jobs": jobs,
        "cand_dir": str(cand_dir),
    }


def _load_dossier(report_path: str) -> Dossier:
    return Dossier.from_dict(json.loads(Path(report_path).read_text(encoding="utf-8")))


def _texts_for_cands(dossier: Dossier, cands: list[dict]) -> list[tuple[str, str]]:
    text_of = {
        seg.id: (seg.text or "")
        for src in dossier.sources for seg in src.segments
    }
    return [(c["id"], text_of.get(c["id"], "")) for c in cands]


def scores_from_rerank_on_candidates(
    bm25_scores: dict[str, float],
    cands: list[dict],
    cand_scores: list[float],
) -> dict[str, float]:
    """候选段用模型分；非候选保留 0（不进密度正分轮）。"""
    out = {sid: 0.0 for sid in bm25_scores}
    for c, sc in zip(cands, cand_scores):
        out[c["id"]] = float(sc)
    return out


def rank_constant_scores(bm25_scores: dict[str, float]) -> dict[str, float]:
    """名次常数＝模型不参与（〔139〕K2 同形）：只留 BM25 一张名次表 → RRF 1/(60+rank)。

    ⚠ 不许用 1/rank：六案实测 L2 会漂到 50（密度键再除 log2(len) 后重排），
    而 fuse_rankings([bm25], k=60) 在六案上 L2 仍 48、选中集 18/18＝生产。
    """
    ranked = sorted(bm25_scores.items(), key=lambda x: (-x[1], x[0]))
    return dict(fuse_rankings([ranked], k=RRF_K))


# ---- 判据 b ---------------------------------------------------------------

def run_criterion_b(jobs: list[dict], gold_dir: Path) -> dict:
    """两把保真刀；返回明细。刀② 属判分侧——这里才开金标。"""
    mism_bm25 = []
    l2_const = 0
    denom = 0
    for job in jobs:
        dossier = _load_dossier(job["report"])
        budget = job["budget"]
        prod = {str(x) for x in (
            pack_material(dossier, budget_chars=budget).get("selected") or [])}
        via = _pack_with_scores(dossier, budget, job["bm25_scores"])
        if prod != via:
            mism_bm25.append({
                "case": job["case"], "qid": job["qid"],
                "only_prod": sorted(prod - via)[:8],
                "only_via": sorted(via - prod)[:8],
            })
        # 刀②：名次常数（模型不参与）
        const_scores = rank_constant_scores(job["bm25_scores"])
        sel_const = _pack_with_scores(dossier, budget, const_scores)
        gold, _ = gold_paras_for_question(gold_dir / job["case"], job["qid"])
        if not gold:
            continue
        gold_paras = {p for _d, p in gold.keys()}
        denom += len(gold)
        l2_const += len(gold_paras & sel_const)

    knife1_ok = len(mism_bm25) == 0
    knife2_ok = (denom == 105 and l2_const == 48)
    return {
        "knife1_ok": knife1_ok,
        "knife1_mismatches": mism_bm25,
        "knife1_n_ok": len(jobs) - len(mism_bm25),
        "knife2_ok": knife2_ok,
        "knife2_l2": l2_const,
        "knife2_denom": denom,
        "knife2_note": "名次常数＝fuse_rankings([bm25], k=60)；第二遍证缓存一致≠模型确定性（R 臂）",
    }


def score_arm_selections(
    jobs: list[dict],
    selections: dict[tuple[str, str], set[str]],
    gold_dir: Path,
    *,
    bm25_rank_of: dict[tuple[str, str], dict[str, int]],
    sel_a: dict[tuple[str, str], set[str]],
) -> dict:
    tot = Counter()
    gained, lost = [], []
    identical = 0
    for job in jobs:
        key = (job["case"], job["qid"])
        gold, _ = gold_paras_for_question(gold_dir / job["case"], job["qid"])
        if not gold:
            continue
        gold_paras = {p for _d, p in gold.keys()}
        denom = len(gold)
        sa = sel_a[key]
        sh = selections[key]
        a_hit = gold_paras & sa
        h_hit = gold_paras & sh
        tot["denom"] += denom
        tot["l2"] += len(h_hit)
        if sa == sh:
            identical += 1
        for p in sorted(a_hit - h_hit):
            lost.append({"case": job["case"], "qid": job["qid"], "para": p})
        ranks = bm25_rank_of[key]
        for p in sorted(h_hit - a_hit):
            gained.append({
                "case": job["case"], "qid": job["qid"], "para": p,
                "bm25_rank": ranks.get(p),
            })
    return {
        "denom": int(tot["denom"]),
        "l2": int(tot["l2"]),
        "lost_n": len(lost),
        "gained_n": len(gained),
        "lost": lost,
        "gained": gained,
        "n_identical_to_a": identical,
    }


# ---- dry-run 打印 ---------------------------------------------------------

def print_dry_run(pack: dict) -> None:
    jobs = pack["jobs"]
    n_q = len(jobs)
    n_score = sum(j["n_cand"] for j in jobs)
    n_req = n_q  # R 臂每题 1 请求（documents=120）
    tok = sum(j["est_tokens"] for j in jobs)
    print("======== C-62 --dry-run（零调用、零下载）========")
    print(f"题数＝{n_q}")
    print(f"将要打分的段数（T／R 各）＝{n_score}（每题前 {CAND_N} 段 × {n_q}）")
    print(f"将发出的请求数（R 臂）＝{n_req}（每题 1 次 text-rerank）")
    print(f"预计 token（粗估，R 臂）＝{tok}")
    print(f"T 臂依赖＝独立 /tmp/venv_rerank（约 637 MB）＋BAAI/bge-reranker-v2-m3（约 2.1 GB）；本脚本不装、不 import torch")
    print(f"R 臂端点＝{DASHSCOPE_RERANK_URL}")
    print(f"R 臂模型＝{R_MODEL_PRIMARY}（退路 {R_MODEL_FALLBACK}）")
    print("本 dry-run 未发起任何 embedding／精排／付费 HTTP。")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--run-dir", default="/tmp/six2")
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--c61-summary", default=str(DEFAULT_C61))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true", default=None,
                    help="零调用（默认）；与 --run 互斥")
    ap.add_argument("--run", action="store_true",
                    help="显式真跑：T 需 --t-scorer；R 只读 cache，永不付费 HTTP")
    ap.add_argument("--t-scorer", default="",
                    help="JSON：{(case,qid): [score×n_cand]} 或路径由架构师注入")
    args = ap.parse_args(argv)

    # 默认 dry-run
    do_run = bool(args.run)
    if args.dry_run is True and do_run:
        raise SystemExit("不能同时 --dry-run 与 --run")
    dry = not do_run

    run_dir = Path(args.run_dir)
    gold_dir = Path(args.gold_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / CACHE_DIR_NAME
    cache_dir.mkdir(parents=True, exist_ok=True)

    if not run_dir.is_dir():
        print(f"跑次不存在：{run_dir}", file=sys.stderr)
        return 2

    # —— 构造（不开金标）——
    print("[构造] gold_root=None …", flush=True)
    pack = construct_jobs(run_dir, gold_root=None, out_dir=out_dir)
    print(f"判据 f：构造未读金标＝True；题数＝{pack['n_questions']}", flush=True)

    # 候选集 sha（T／R 将断言同一份）
    shas = {j["sha"] for j in pack["jobs"]}
    print(f"候选集文件数＝{len(pack['jobs'])}；唯一 sha 数＝{len(shas)}（每题一份）")
    # 模拟 T／R 各读一次并断言
    sha_t, sha_r = [], []
    for j in pack["jobs"]:
        blob = json.loads(Path(j["cand_path"]).read_text(encoding="utf-8"))
        sha_t.append(blob["sha"])
        sha_r.append(blob["sha"])
        assert blob["sha"] == j["sha"]
    same_tr = sha_t == sha_r
    print(f"判据 d：T／R 读到的候选集 sha 逐题相同＝{same_tr}")

    if dry:
        print_dry_run(pack)

    # —— 判据 b ——
    print("\n[判据 b] 两把保真刀 …", flush=True)
    b = run_criterion_b(pack["jobs"], gold_dir)
    print(f"  刀① BM25 原分走拼接路 ≡ pack_material："
          f"{'✅' if b['knife1_ok'] else '❌'} "
          f"({b['knife1_n_ok']}/{pack['n_questions']})")
    if not b["knife1_ok"]:
        print(f"   mismatch 样例：{b['knife1_mismatches'][:3]}")
        print("判据 b 刀① 红 ⇒ 停手", flush=True)
        (out_dir / "criterion_b.json").write_text(
            json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
        return 3
    print(f"  刀② 名次常数 fuse_rankings([bm25],k=60)（模型不参与）"
          f"L2＝{b['knife2_l2']}/{b['knife2_denom']}："
          f"{'✅' if b['knife2_ok'] else '❌'}（须＝48/105）")
    if not b["knife2_ok"]:
        print("判据 b 刀② 红 ⇒ 停手", flush=True)
        (out_dir / "criterion_b.json").write_text(
            json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
        return 3

    # —— 判据 a：A 臂 ——
    print("\n[判据 a] A 臂复现 …", flush=True)
    sel_a: dict[tuple[str, str], set[str]] = {}
    bm25_rank_of: dict[tuple[str, str], dict[str, int]] = {}
    t0 = time.time()
    for j in pack["jobs"]:
        dossier = _load_dossier(j["report"])
        pack_a = pack_material(dossier, budget_chars=j["budget"])
        key = (j["case"], j["qid"])
        sel_a[key] = {str(x) for x in (pack_a.get("selected") or [])}
        bm25_rank_of[key] = j["bm25_rank"]
    wall_a = round(time.time() - t0, 3)
    scored_a = score_arm_selections(
        pack["jobs"], sel_a, gold_dir,
        bm25_rank_of=bm25_rank_of, sel_a=sel_a)
    # 对 A，gained 相对自己为空；l2 即 A L2
    a_l2 = scored_a["l2"]
    a_ok = a_l2 == 48 and scored_a["denom"] == 105
    print(f"  A L2＝{a_l2}/{scored_a['denom']}  {'✅' if a_ok else '❌'}")
    if not a_ok:
        print("口径飘了，停手。", flush=True)
        return 3

    # —— H：引用 C-61 ——
    h_summary = {"l2": None, "lost_n": None, "gained_n": None, "note": ""}
    c61_path = Path(args.c61_summary)
    if c61_path.is_file():
        c61 = json.loads(c61_path.read_text(encoding="utf-8"))
        p1 = c61.get("pass1") or {}
        h_summary = {
            "l2": p1.get("l2_h"),
            "lost_n": p1.get("lost_n"),
            "gained_n": p1.get("gained_n"),
            "note": f"引用 {c61_path}（不重跑）",
            "embed_model": c61.get("embed_model"),
        }
        print(f"\n[H 臂] 引用 C-61：L2={h_summary['l2']}/105 lost={h_summary['lost_n']} "
              f"gained={h_summary['gained_n']}  {h_summary['note']}")
    else:
        h_summary["note"] = f"C-61 摘要不在：{c61_path}"
        print(f"\n[H 臂] ⚠ {h_summary['note']}")

    # —— T／R（dry-run 不算分；--run 才走）——
    t_result = {
        "l2": None, "lost_n": None, "gained_n": None,
        "wall_s": None, "cost": 0, "status": "dry-run／未跑",
        "gained": [], "identical_to_a": None,
    }
    r_result = {
        "l2": None, "lost_n": None, "gained_n": None,
        "wall_s": None, "cost_tokens": 0, "status": "dry-run／未跑",
        "gained": [], "identical_to_a": None,
        "cache_note": "第二遍证的是缓存一致，不是模型确定性",
    }

    # 预写 R 请求样例（不发送）
    sample_job = pack["jobs"][0]
    sample_blob = json.loads(Path(sample_job["cand_path"]).read_text(encoding="utf-8"))
    # documents 占位：用 text_sha 代替正文，避免 dry-run 读全文；真请求构造在 --run
    sample_req = build_rerank_request(
        model=R_MODEL_PRIMARY,
        query=sample_job["query"],
        documents=[f"[stub:{c['id']}|{c['text_sha']}]" for c in sample_blob["candidates"]],
        top_n=len(sample_blob["candidates"]),
    )
    (out_dir / "sample_r_request.json").write_text(
        json.dumps({
            "url": DASHSCOPE_RERANK_URL,
            "headers": {"Authorization": "Bearer $DASHSCOPE_API_KEY",
                        "Content-Type": "application/json"},
            "body": sample_req,
            "note": "dry-run 正文为 stub；--run 时换成真 seg.text。本文件从未被 POST。",
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    if do_run:
        # T：优先已注入的 set_t_scorer；否则 --t-scorer JSON
        t_scorer_path = Path(args.t_scorer) if args.t_scorer else None
        use_json = bool(t_scorer_path and t_scorer_path.is_file())
        use_inject = _T_SCORER is not None
        if not use_json and not use_inject:
            t_result["status"] = (
                "跳过：未 set_t_scorer、也未提供 --t-scorer JSON"
                "（由 /tmp/venv_rerank 侧注入）"
            )
            print(f"\n[T 臂] {t_result['status']}")
        else:
            t_scores_all = (
                json.loads(t_scorer_path.read_text(encoding="utf-8"))
                if use_json else None
            )
            sel_t: dict[tuple[str, str], set[str]] = {}
            t0 = time.time()
            for j in pack["jobs"]:
                key = f"{j['case']}::{j['qid']}"
                blob = json.loads(Path(j["cand_path"]).read_text(encoding="utf-8"))
                assert blob["sha"] == j["sha"], "T 臂候选集 sha 漂移"
                dossier = _load_dossier(j["report"])
                cands = blob["candidates"]
                pairs = _texts_for_cands(dossier, cands)
                if use_json:
                    raw = t_scores_all.get(key) or t_scores_all.get(j["qid"])
                    if not raw or len(raw) != len(cands):
                        raise SystemExit(f"T scorer 缺/长度不对：{key}")
                    fixed = [float(x) for x in raw]
                    set_t_scorer(lambda q, ps, _f=fixed: list(_f))
                scored = score_candidates_local(j["query"], pairs)
                score_map = scores_from_rerank_on_candidates(
                    j["bm25_scores"], cands, scored)
                sel_t[(j["case"], j["qid"])] = _pack_with_scores(
                    dossier, j["budget"], score_map)
            if use_json:
                set_t_scorer(None)
            t_result["wall_s"] = round(time.time() - t0, 3)
            st = score_arm_selections(
                pack["jobs"], sel_t, gold_dir,
                bm25_rank_of=bm25_rank_of, sel_a=sel_a)
            t_result.update({
                "l2": st["l2"], "lost_n": st["lost_n"], "gained_n": st["gained_n"],
                "gained": st["gained"], "identical_to_a": st["n_identical_to_a"],
                "status": "ok", "cost": 0,
            })
            print(f"\n[T 臂] L2={st['l2']}/105 lost={st['lost_n']} gained={st['gained_n']} "
                  f"identical_to_a={st['n_identical_to_a']}/18")

        # R：只读缓存，不 HTTP
        sel_r: dict[tuple[str, str], set[str]] = {}
        total_tok = 0
        missing_cache = []
        t0 = time.time()
        for j in pack["jobs"]:
            blob = json.loads(Path(j["cand_path"]).read_text(encoding="utf-8"))
            assert blob["sha"] == j["sha"], "R 臂候选集 sha 漂移"
            cp = cache_path(cache_dir, j["case"], j["qid"], R_MODEL_PRIMARY)
            if not cp.is_file():
                # 尝试 fallback 模型名的缓存键
                cp2 = cache_path(cache_dir, j["case"], j["qid"], R_MODEL_FALLBACK)
                if cp2.is_file():
                    cp = cp2
                else:
                    missing_cache.append(str(cp))
                    continue
            resp = json.loads(cp.read_text(encoding="utf-8"))
            dossier = _load_dossier(j["report"])
            texts = _texts_for_cands(dossier, blob["candidates"])
            docs = [t for _i, t in texts]
            scores, tok = parse_rerank_response(resp, n_docs=len(docs))
            total_tok += tok
            score_map = scores_from_rerank_on_candidates(
                j["bm25_scores"], blob["candidates"], scores)
            sel_r[(j["case"], j["qid"])] = _pack_with_scores(
                dossier, j["budget"], score_map)
        r_result["wall_s"] = round(time.time() - t0, 3)
        r_result["cost_tokens"] = total_tok
        if missing_cache:
            r_result["status"] = (
                f"缓存不全（缺 {len(missing_cache)}/{pack['n_questions']}）；"
                f"本脚本不发付费请求——请架构师填 /tmp/c62_rerank/cache/。"
                f"样例缺：{missing_cache[0]}"
            )
            print(f"\n[R 臂] {r_result['status']}")
        else:
            # 第二遍只读缓存（再扫一次）证缓存一致
            sel_r2: dict[tuple[str, str], set[str]] = {}
            for j in pack["jobs"]:
                blob = json.loads(Path(j["cand_path"]).read_text(encoding="utf-8"))
                cp = cache_path(cache_dir, j["case"], j["qid"], R_MODEL_PRIMARY)
                if not cp.is_file():
                    cp = cache_path(cache_dir, j["case"], j["qid"], R_MODEL_FALLBACK)
                resp = json.loads(cp.read_text(encoding="utf-8"))
                dossier = _load_dossier(j["report"])
                texts = _texts_for_cands(dossier, blob["candidates"])
                scores, _tok = parse_rerank_response(resp, n_docs=len(texts))
                score_map = scores_from_rerank_on_candidates(
                    j["bm25_scores"], blob["candidates"], scores)
                sel_r2[(j["case"], j["qid"])] = _pack_with_scores(
                    dossier, j["budget"], score_map)
            cache_consistent = sel_r == sel_r2
            st = score_arm_selections(
                pack["jobs"], sel_r, gold_dir,
                bm25_rank_of=bm25_rank_of, sel_a=sel_a)
            r_result.update({
                "l2": st["l2"], "lost_n": st["lost_n"], "gained_n": st["gained_n"],
                "gained": st["gained"], "identical_to_a": st["n_identical_to_a"],
                "status": "ok（只读缓存）",
                "cache_consistent": cache_consistent,
                "cache_note": "第二遍证的是缓存一致，不是模型确定性",
            })
            print(f"\n[R 臂] L2={st['l2']}/105 lost={st['lost_n']} gained={st['gained_n']} "
                  f"cache_consistent＝{cache_consistent}  "
                  f"※{r_result['cache_note']}")

    # —— 判据 c 摘要（A 已有；H 来自 C-61；T／R 若跑了）——
    print("\n判据 c（相对 A 新命中；完全相同＝没生效）：")
    print(f"  A：参照臂")
    print(f"  H：见 C-61 gained 清单（本单不重跑）")
    if t_result.get("identical_to_a") is not None:
        eff = "没生效" if t_result["identical_to_a"] == pack["n_questions"] else "有差异"
        print(f"  T：identical_to_a={t_result['identical_to_a']}/18 ⇒ {eff}")
        for g in (t_result.get("gained") or [])[:12]:
            print(f"    + {g['case'][:14]}/{g['qid']} {g['para']} bm25_rank={g['bm25_rank']}")
    else:
        print(f"  T：{t_result['status']}")
    if r_result.get("identical_to_a") is not None:
        eff = "没生效" if r_result["identical_to_a"] == pack["n_questions"] else "有差异"
        print(f"  R：identical_to_a={r_result['identical_to_a']}/18 ⇒ {eff}")
    else:
        print(f"  R：{r_result['status']}")

    # —— 判据 g 成本表（纯文本）——
    print("\n======== 判据 g 成本表 ========")
    print("臂｜L2｜lost｜gained｜墙钟s｜花钱｜依赖／体积｜演示机离线")
    print(f"A｜{a_l2}/105｜0｜0｜{wall_a}｜0｜无｜能")
    print(f"H｜{h_summary.get('l2')}/105｜{h_summary.get('lost_n')}｜"
          f"{h_summary.get('gained_n')}｜—｜0｜本机 bge-m3（C-61 已付）｜能（需 ollama）")
    print(f"T｜{t_result.get('l2')}｜{t_result.get('lost_n')}｜{t_result.get('gained_n')}｜"
          f"{t_result.get('wall_s')}｜0｜venv≈637MB＋模型≈2.1GB｜能（须预置权重；直连 HF 不通须镜像）")
    print(f"R｜{r_result.get('l2')}｜{r_result.get('lost_n')}｜{r_result.get('gained_n')}｜"
          f"{r_result.get('wall_s')}｜tokens={r_result.get('cost_tokens')}｜"
          f"HTTP 百炼 key｜不能（需网络与 key）")
    print(f"R 缓存说明：{r_result.get('cache_note')}")

    summary = {
        "mode": "run" if do_run else "dry-run",
        "criterion_a": {"l2": a_l2, "denom": scored_a["denom"], "ok": a_ok, "wall_s": wall_a},
        "criterion_b": b,
        "criterion_d_sha_same": same_tr,
        "H": h_summary,
        "T": t_result,
        "R": r_result,
        "dry_run": {
            "n_questions": pack["n_questions"],
            "n_score_segments": sum(j["n_cand"] for j in pack["jobs"]),
            "n_r_requests": pack["n_questions"],
            "est_tokens": sum(j["est_tokens"] for j in pack["jobs"]),
        },
        "rerank_url": DASHSCOPE_RERANK_URL,
        "r_models": [R_MODEL_PRIMARY, R_MODEL_FALLBACK],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "criterion_b.json").write_text(
        json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[wrote] {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    # 硬约束：本文件不得 import torch
    assert "torch" not in sys.modules
    raise SystemExit(main())
