#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-85：树13「先锚后审」只量（方案 B；过线才自动开方案 C 补召回）。

B 协议（与 C-84 不同＝先立审查标准再审段）：
  1) BM25 前 K 候选（同 C-84 构造）
  2) 本地 LLM 从议题抽出审查锚 JSON（每题 1 次）
  3) 按锚批审「能否直接支撑」→ 分装箱（LLM 主序、BM25 破并列）
  金标不进提示词；OPENAI_* 钉本机。

C 协议（仅当 B 相对 A0 的 L2 严格提升才开）：
  4) 看哪些锚在高分段覆盖弱
  5) 从 K 外按锚词补召回 M 段 → 再审 → 并入分表再装

判据：
  a  A0＝48/105
  b  臂 L2≥54 且 lost＝0（不过⇒逃逸；B 提升才开 C，C 另判）

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c85_anchor_review.py \\
      --run-dir /tmp/six2 --prepare --score-b --run-b --out-dir /tmp/c85_b
  # 一键：B 完若提升自动 C
  ... --prepare --auto --out-dir /tmp/c85_auto
  # K×3（180）仍用 BM25 选候选
  ... --auto --k 180 --out-dir /tmp/c85_k180
  # K×3 且关 BM25（轮转选候选＋装箱不破并列）
  ... --auto --k 180 --no-bm25 --out-dir /tmp/c85_k180_nobm25
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from scripts.probe_c62_rerank_arms import (  # noqa: E402
    _bm25_table,
    _pack_with_scores,
    build_candidates,
)
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c84_llm_rerank import (  # noqa: E402
    _budget,
    _clip_seg,
    _lock_local,
    _parse_scores,
)
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    discover_reports,
    gold_paras_for_question,
)

TARGET_A0 = 48
TARGET_DENOM = 105
TARGET_L2 = 54
DEFAULT_K = 60
DEFAULT_BATCH = 12
DEFAULT_MODEL = "veritas-qwen3-14b:latest"
DEFAULT_REFILL = 40
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _round_robin_ids(dossier: Dossier, n: int) -> list[str]:
    """跨信源轮转取段——关 BM25 选候选时用，避免只吃到第一篇。"""
    queues = [[seg.id for seg in src.segments] for src in dossier.sources]
    out: list[str] = []
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop(0))
    return out


def prepare(
    run_dir: Path,
    out_dir: Path,
    *,
    k: int,
    cand_mode: str = "bm25",
) -> dict:
    """cand_mode＝bm25｜round_robin（关 BM25 选候选）。全表 bm25_scores 仍写入供对照／可选破并列。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        text_of = {
            seg.id: (seg.text or "")
            for src in dossier.sources for seg in src.segments
        }
        ranked = _bm25_table(dossier)
        bm25_scores = dict(ranked)
        query, cands_b, _, _ = build_candidates(dossier, n=k)
        if cand_mode == "bm25":
            ids = [c["id"] for c in cands_b]
        elif cand_mode == "round_robin":
            ids = _round_robin_ids(dossier, k)
        else:
            raise ValueError(f"未知 cand_mode：{cand_mode}")
        jobs.append({
            "case": case,
            "qid": qid,
            "query": query,
            "budget": _budget(rep),
            "report": str(rp.resolve()),
            "ids": ids,
            "texts": [text_of.get(i, "") for i in ids],
            "bm25_scores": bm25_scores,
            "cand_mode": cand_mode,
            "k": k,
        })
    path = out_dir / "score_input.json"
    path.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    meta = {
        "n_questions": len(jobs), "k": k, "cand_mode": cand_mode,
        "score_input": str(path),
    }
    (out_dir / "prepare_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("======== C-85 --prepare ========")
    print(f"题数＝{len(jobs)}｜K＝{k}｜cand_mode＝{cand_mode} → {path}")
    return meta


def _ollama_chat(model: str, prompt: str, *, timeout: int = 600) -> str:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 900},
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str((data.get("message") or {}).get("content") or "")


def _parse_json_obj(raw: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", raw.strip(), flags=re.S)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"无 JSON：{raw[:200]}")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("JSON 非对象")
    return obj


def _anchor_prompt(question: str) -> str:
    return "\n".join([
        "你是研判资料审查员。只做一件事：从议题抽出「审查锚」（判决标准），不要答题。",
        "同义／别称可写在 aliases。不要编造议题未出现的实体。",
        f"议题：{question}",
        "只输出 JSON：",
        '{"subject":"主体","dispute":"要裁的争点/分歧","time_or_number":"关键时点或数字或空",'
        '"must_hit":["过闸至少应对上的要点",...],'
        '"aliases":["别称或同指",...],'
        '"reject_if":["同学课噪声典型：相关但裁不了题的情形",...]}',
    ])


def _review_prompt(
    question: str, anchors: dict, batch: list[tuple[int, str]],
) -> str:
    n = len(batch)
    max_high = max(1, min(3, n // 4))
    lines = [
        "你是资料审查员。任务：判断每段能否作为「直接支撑」回答该议题。",
        "先看审查锚，再看段落。换说法／别称／同指算对齐；同学课（同事件但裁不了争点）必须低分。",
        "不要编造段落外事实。拿不准宁低勿高。",
        "",
        f"议题：{question}",
        f"审查锚：{json.dumps(anchors, ensure_ascii=False)}",
        "",
        "分档：",
        "  9–10＝直接支撑争点（锚对齐，含换说法）",
        "  6–8＝部分支撑（有事实但缺关键锚）",
        "  3–5＝弱相关背景",
        "  0–2＝无关／换主体／纯态度／同学课噪声",
        "否决上限：换主体≤1；只有背景热闹≤2；纯态度≤3；说不清对哪条锚≤4。",
        f"本批 {n} 段：9–10 分不超过 {max_high} 段。",
        "段落：",
    ]
    for i, text in batch:
        lines.append(f"[{i}] {_clip_seg(text)}")
    lines.append(
        "只输出："
        f'{{\"scores\":[{{\"i\":0,\"score\":0到10}},...]}} 长度＝{n}。'
    )
    return "\n".join(lines)


def _fallback_anchors(question: str) -> dict:
    return {
        "subject": "",
        "dispute": question[:120],
        "time_or_number": "",
        "must_hit": [question[:80]],
        "aliases": [],
        "reject_if": ["仅背景", "换主体", "纯态度"],
        "_fallback": True,
    }


def extract_anchors(
    out_dir: Path, *, model: str, limit: int | None,
) -> dict:
    _lock_local()
    jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    if limit is not None:
        jobs = jobs[: max(1, limit)]
    path = out_dir / "anchors.json"
    done: dict[str, dict] = {}
    if path.is_file():
        done = json.loads(path.read_text(encoding="utf-8"))
    t0 = time.time()
    n_calls = 0
    for ji, job in enumerate(jobs, 1):
        key = f"{job['case']}::{job['qid']}"
        if key in done and isinstance(done[key], dict) and done[key].get("dispute"):
            print(f"  锚 [{ji}/{len(jobs)}] {key[:36]} 缓存", flush=True)
            continue
        prompt = _anchor_prompt(job["query"])
        raw = _ollama_chat(model, prompt)
        n_calls += 1
        try:
            obj = _parse_json_obj(raw)
        except Exception:
            raw2 = _ollama_chat(model, prompt + "\n再次确认：只输出 JSON。")
            n_calls += 1
            try:
                obj = _parse_json_obj(raw2)
            except Exception:
                print(f"    锚解析失败，用回退：{key[:40]}", flush=True)
                obj = _fallback_anchors(job["query"])
        done[key] = obj
        path.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  锚 [{ji}/{len(jobs)}] {key[:36]} ok", flush=True)
    meta = {
        "phase": "anchors", "model": model, "n_calls": n_calls,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (out_dir / "anchors_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"抽锚墙钟＝{meta['elapsed_s']}s 调用＝{n_calls} → {path}")
    return done


def _score_batches(
    question: str,
    anchors: dict,
    texts: list[str],
    *,
    model: str,
    batch_size: int,
) -> tuple[list[float], int]:
    scores = [0.0] * len(texts)
    n_calls = 0
    for start in range(0, len(texts), batch_size):
        local = [(i, t) for i, t in enumerate(texts[start:start + batch_size])]
        prompt = _review_prompt(question, anchors, local)
        raw = _ollama_chat(model, prompt)
        n_calls += 1
        try:
            part = _parse_scores(raw, len(local))
        except Exception as exc:
            raw2 = _ollama_chat(model, prompt + "\n再次确认：只输出 JSON。")
            n_calls += 1
            try:
                part = _parse_scores(raw2, len(local))
            except Exception:
                print(f"    审批评失败 start={start}：{exc}", flush=True)
                part = [0.0] * len(local)
        for j, sc in enumerate(part):
            scores[start + j] = float(sc)
    return scores, n_calls


def score_b(
    out_dir: Path, *, model: str, batch_size: int, limit: int | None,
) -> dict:
    _lock_local()
    jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    if limit is not None:
        jobs = jobs[: max(1, limit)]
    anchors_all = extract_anchors(out_dir, model=model, limit=limit)
    cache = out_dir / "llm_scores_b.json"
    done: dict[str, list[float]] = {}
    if cache.is_file():
        done = json.loads(cache.read_text(encoding="utf-8"))
    t0 = time.time()
    n_calls = 0
    for ji, job in enumerate(jobs, 1):
        key = f"{job['case']}::{job['qid']}"
        if key in done and len(done[key]) == len(job["ids"]):
            print(f"  审B [{ji}/{len(jobs)}] {key[:36]} 缓存", flush=True)
            continue
        anc = anchors_all.get(key) or _fallback_anchors(job["query"])
        sc, c = _score_batches(
            job["query"], anc, job["texts"], model=model, batch_size=batch_size)
        n_calls += c
        done[key] = sc
        cache.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        print(f"  审B [{ji}/{len(jobs)}] {key[:36]} n={len(sc)} calls+={c}", flush=True)
    meta = {
        "phase": "B", "model": model, "batch_size": batch_size,
        "n_calls": n_calls, "elapsed_s": round(time.time() - t0, 1),
        "note": "不含抽锚调用（见 anchors_meta）",
    }
    (out_dir / "score_meta_b.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"B审墙钟＝{meta['elapsed_s']}s 调用＝{n_calls} → {cache}")
    return meta


def _fuse(
    bm25_scores: dict[str, float],
    id_scores: dict[str, float],
    *,
    use_bm25: bool,
) -> dict[str, float]:
    out = {sid: 0.0 for sid in bm25_scores}
    if not use_bm25:
        for sid, sc in id_scores.items():
            out[sid] = float(sc)
        return out
    max_b = max(bm25_scores.values()) if bm25_scores else 1.0
    max_b = max_b if max_b > 0 else 1.0
    for sid, sc in id_scores.items():
        b = float(bm25_scores.get(sid, 0.0)) / max_b
        out[sid] = float(sc) * 1000.0 + b
    return out


def _gold_keys(gold_dir: Path, case: str, qid: str):
    g, _ = gold_paras_for_question(gold_dir / case, qid)
    return set(g.keys()), len(g)


def _use_bm25_from_meta(out_dir: Path) -> bool:
    meta_path = out_dir / "prepare_meta.json"
    if not meta_path.is_file():
        return True
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if "use_bm25_fuse" in meta:
        return bool(meta["use_bm25_fuse"])
    return meta.get("cand_mode", "bm25") == "bm25"


def run_measure(
    out_dir: Path,
    gold_dir: Path,
    *,
    scores_name: str,
    arm_key: str,
) -> dict[str, Any]:
    jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    scores_all = json.loads((out_dir / scores_name).read_text(encoding="utf-8"))
    use_bm25 = _use_bm25_from_meta(out_dir)
    tot = Counter()
    rows = []
    lost_n = gained_n = 0
    for job in jobs:
        key = f"{job['case']}::{job['qid']}"
        sc = scores_all.get(key)
        if not sc:
            raise SystemExit(f"缺分：{key} in {scores_name}")
        # sc may be list aligned to ids, or dict sid->score (C)
        if isinstance(sc, dict):
            id_scores = {str(k): float(v) for k, v in sc.items()}
        else:
            if len(sc) != len(job["ids"]):
                raise SystemExit(f"分不齐：{key}")
            id_scores = {cid: float(s) for cid, s in zip(job["ids"], sc)}

        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        budget = int(job["budget"])
        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        if denom == 0:
            continue

        p0 = pack_material(dossier, budget_chars=budget)
        sel_a = {str(x) for x in (p0.get("selected") or [])}
        loc_a = selected_locs(dossier, sel_a)
        hits_a = l2_hits(gold, loc_a)

        bm25_scores = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        # 审查分覆盖的 sid 若全表没有（理论上不会），补进 fuse 底表
        for sid in id_scores:
            bm25_scores.setdefault(sid, 0.0)
        fused = _fuse(bm25_scores, id_scores, use_bm25=use_bm25)
        sel_l = _pack_with_scores(dossier, budget, fused)
        loc_l = selected_locs(dossier, sel_l)
        hits_l = l2_hits(gold, loc_l)

        lost = (gold & loc_a) - loc_l
        gained = (gold & loc_l) - loc_a
        lost_n += len(lost)
        gained_n += len(gained)
        rows.append({
            "case": job["case"], "qid": job["qid"], "denom": denom,
            "a0_hits": hits_a, "a0_n": len(sel_a),
            f"{arm_key}_hits": hits_l, f"{arm_key}_n": len(sel_l),
            "lost": len(lost), "gained": len(gained),
        })
        tot["denom"] += denom
        tot["a0_hits"] += hits_a
        tot["a0_n"] += len(sel_a)
        tot["arm_hits"] += hits_l
        tot["arm_n"] += len(sel_l)

    return {
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "a0": {
            "l2_hits": int(tot["a0_hits"]),
            "n_selected": int(tot["a0_n"]),
            "precision": round(tot["a0_hits"] / tot["a0_n"], 4) if tot["a0_n"] else 0,
            "recall": round(tot["a0_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        arm_key: {
            "l2_hits": int(tot["arm_hits"]),
            "n_selected": int(tot["arm_n"]),
            "precision": round(tot["arm_hits"] / tot["arm_n"], 4) if tot["arm_n"] else 0,
            "recall": round(tot["arm_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        "lost_n": lost_n,
        "gained_n": gained_n,
        "rows": rows,
    }


def judge(summary: dict, arm_key: str) -> dict:
    a_ok = summary["a0"]["l2_hits"] == TARGET_A0 and summary["denom"] == TARGET_DENOM
    arm = summary[arm_key]
    b_ok = (
        arm["l2_hits"] >= TARGET_L2
        and summary["lost_n"] == 0
        and summary["denom"] == TARGET_DENOM
    )
    improved = arm["l2_hits"] > summary["a0"]["l2_hits"]
    return {
        "a": {"ok": a_ok, "got": f"{summary['a0']['l2_hits']}/{summary['denom']}"},
        "b": {
            "ok": b_ok,
            "got": f"{arm['l2_hits']}/{summary['denom']}",
            "lost_n": summary["lost_n"],
            "gained_n": summary["gained_n"],
        },
        "improved_vs_a0": improved,
    }


def _print_summary(summary: dict, arm_key: str, j: dict) -> None:
    print(f"======== C-85 {arm_key} 到达面 ========")
    print(f"题数＝{summary['n_questions']}｜分母＝{summary['denom']}")
    for name in ("a0", arm_key):
        r = summary[name]
        print(
            f"  {name.upper():3}｜L2 {r['l2_hits']}/{summary['denom']} "
            f"（{r['recall']:.3f}）｜装入 {r['n_selected']}｜纯度 {r['precision']:.4f}"
        )
    print(f"相对 A0：lost＝{summary['lost_n']}｜gained＝{summary['gained_n']}")
    print("判据 a", "✅" if j["a"]["ok"] else "❌", j["a"])
    print("判据 b", "✅" if j["b"]["ok"] else "❌（逃逸）", j["b"])
    print("相对 A0 提升", "✅" if j["improved_vs_a0"] else "❌", 
          f"（门槛＝L2 > A0）")


def _anchor_terms(anc: dict) -> list[str]:
    terms: list[str] = []
    for k in ("subject", "dispute", "time_or_number"):
        v = str(anc.get(k) or "").strip()
        if v:
            terms.append(v)
    for lst_k in ("must_hit", "aliases"):
        for x in anc.get(lst_k) or []:
            s = str(x).strip()
            if s:
                terms.append(s)
    # 拆短词
    out: list[str] = []
    for t in terms:
        out.append(t)
        for m in re.findall(r"[\u4e00-\u9fff]{2,8}|\b[A-Za-z0-9\-.]{2,}\b", t):
            out.append(m)
    seen, uniq = set(), []
    for x in out:
        if x not in seen and len(x) >= 2:
            seen.add(x)
            uniq.append(x)
    return uniq[:24]


def _weak_anchors(anc: dict, id_scores: dict[str, float], text_of: dict[str, str]) -> list[str]:
    """高分（≥8）段文本盖不住的 must_hit／dispute 词 → 弱锚，拿去补召回。"""
    high_txt = " ".join(
        text_of.get(sid, "") for sid, sc in id_scores.items() if sc >= 8.0
    )
    weak = []
    seeds = list(anc.get("must_hit") or []) + [str(anc.get("dispute") or "")]
    for seed in seeds:
        seed = str(seed).strip()
        if len(seed) < 2:
            continue
        # 种子本身或其 2+ 字片段是否出现在高分段
        parts = re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z0-9]{3,}", seed) or [seed[:8]]
        if not any(p in high_txt for p in parts):
            weak.append(seed)
    return weak[:6] or _anchor_terms(anc)[:4]


def score_c_refill(
    out_dir: Path,
    *,
    model: str,
    batch_size: int,
    refill_n: int,
    limit: int | None,
) -> dict:
    """在 B 分基础上，按弱锚从 K 外补召回并再审，合并为 sid→score。"""
    _lock_local()
    jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    if limit is not None:
        jobs = jobs[: max(1, limit)]
    anchors_all = json.loads((out_dir / "anchors.json").read_text(encoding="utf-8"))
    scores_b = json.loads((out_dir / "llm_scores_b.json").read_text(encoding="utf-8"))
    out_path = out_dir / "llm_scores_c.json"
    done: dict[str, dict[str, float]] = {}
    if out_path.is_file():
        done = json.loads(out_path.read_text(encoding="utf-8"))

    t0 = time.time()
    n_calls = 0
    for ji, job in enumerate(jobs, 1):
        key = f"{job['case']}::{job['qid']}"
        if key in done and done[key]:
            print(f"  审C [{ji}/{len(jobs)}] {key[:36]} 缓存", flush=True)
            continue
        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        text_of = {
            seg.id: (seg.text or "")
            for src in dossier.sources for seg in src.segments
        }
        bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        ranked = sorted(bm25.items(), key=lambda x: (-x[1], x[0]))
        in_k = set(job["ids"])
        b_list = scores_b[key]
        id_scores = {cid: float(s) for cid, s in zip(job["ids"], b_list)}
        anc = anchors_all.get(key) or _fallback_anchors(job["query"])
        weak = _weak_anchors(anc, id_scores, text_of)
        terms = _anchor_terms({**anc, "must_hit": weak})
        use_bm25 = _use_bm25_from_meta(out_dir)

        # K 外候选：按锚词命中；BM25 开则次键用 bm25，关则只按命中+sid
        outside = []
        for sid, bsc in ranked:
            if sid in in_k:
                continue
            txt = text_of.get(sid, "")
            hit = sum(1 for t in terms if t and t in txt)
            if hit <= 0:
                continue
            outside.append((hit, bsc if use_bm25 else 0.0, sid))
        outside.sort(key=lambda x: (-x[0], -x[1], x[2]))
        refill_ids = [sid for _h, _b, sid in outside[:refill_n]]
        refill_texts = [text_of.get(sid, "") for sid in refill_ids]

        keep_ge6 = 0
        if refill_ids:
            sc_refill, c = _score_batches(
                job["query"], anc, refill_texts, model=model, batch_size=batch_size)
            n_calls += c
            for sid, sc in zip(refill_ids, sc_refill):
                # 只接受审过及格的补段，避免噪声灌入
                if sc >= 6.0:
                    id_scores[sid] = max(id_scores.get(sid, 0.0), float(sc))
                    keep_ge6 += 1
        done[key] = id_scores
        out_path.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        print(
            f"  审C [{ji}/{len(jobs)}] {key[:36]} "
            f"refill={len(refill_ids)} keep≥6={keep_ge6} "
            f"weak={weak[:2]}",
            flush=True,
        )

    meta = {
        "phase": "C", "model": model, "refill_n": refill_n,
        "n_calls": n_calls, "elapsed_s": round(time.time() - t0, 1),
    }
    (out_dir / "score_meta_c.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"C补审墙钟＝{meta['elapsed_s']}s 调用＝{n_calls} → {out_path}")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", default="/tmp/c85_anchor")
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--refill-n", type=int, default=DEFAULT_REFILL)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--no-bm25", action="store_true",
        help="关 BM25：候选改跨源轮转取 K；装箱只用审查分（不破并列）",
    )
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--score-b", action="store_true")
    ap.add_argument("--run-b", action="store_true")
    ap.add_argument("--score-c", action="store_true")
    ap.add_argument("--run-c", action="store_true")
    ap.add_argument("--auto", action="store_true",
                    help="prepare+B 全流程；若 L2>A0 自动开 C")
    ap.add_argument(
        "--copy-anchors-from", default="",
        help="复用已有 anchors.json（省抽锚调用）",
    )
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    gold_dir = Path(args.gold_dir)
    cand_mode = "round_robin" if args.no_bm25 else "bm25"

    if args.prepare or args.auto:
        meta = prepare(
            Path(args.run_dir), out_dir, k=args.k, cand_mode=cand_mode)
        meta["use_bm25_fuse"] = not args.no_bm25
        meta["no_bm25"] = bool(args.no_bm25)
        (out_dir / "prepare_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.copy_anchors_from:
            src = Path(args.copy_anchors_from)
            if src.is_file():
                (out_dir / "anchors.json").write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"复用锚 ← {src}")
            else:
                print(f"警告：锚文件不存在 {src}，将现场抽锚", flush=True)

    if args.score_b or args.auto:
        score_b(
            out_dir, model=args.model, batch_size=args.batch_size, limit=args.limit)

    summary_b = None
    j_b = None
    if args.run_b or args.auto:
        summary_b = run_measure(
            out_dir, gold_dir, scores_name="llm_scores_b.json", arm_key="B")
        j_b = judge(summary_b, "B")
        _print_summary(summary_b, "B", j_b)
        (out_dir / "summary_b.json").write_text(
            json.dumps({"summary": summary_b, "judge": j_b},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"落盘 {out_dir / 'summary_b.json'}")

    do_c = args.score_c or args.run_c
    if args.auto:
        if j_b and j_b["improved_vs_a0"]:
            print("\n>>> B 相对 A0 有提升 → 自动开方案 C（弱锚补召回）\n", flush=True)
            do_c = True
        else:
            print("\n>>> B 未相对 A0 提升 L2 → 跳过方案 C\n", flush=True)

    if do_c and (args.score_c or args.auto):
        score_c_refill(
            out_dir, model=args.model, batch_size=args.batch_size,
            refill_n=args.refill_n, limit=args.limit,
        )

    if do_c and (args.run_c or args.auto):
        summary_c = run_measure(
            out_dir, gold_dir, scores_name="llm_scores_c.json", arm_key="C")
        j_c = judge(summary_c, "C")
        _print_summary(summary_c, "C", j_c)
        (out_dir / "summary_c.json").write_text(
            json.dumps({"summary": summary_c, "judge": j_c},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"落盘 {out_dir / 'summary_c.json'}")

    if summary_b is not None and not j_b["a"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
