#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-84：树13 子智能体重排只量——BM25 前 K → 本地 LLM 打「支撑证据」分 → 同装箱。

验证想法：换说法／同意思靠大模型辨，不靠再换向量。生产零 diff／默认不动。

协议：
  · 候选＝BM25 前 K（默认 60；与 C-62 同形构造）
  · 打分＝本机 Ollama（默认 veritas-qwen3-14b），分批 JSON；零现金
  · 非候选分＝0，再走 pack_material（monkeypatch rank_segments）
  · 金标只用于离线 L2／纯度；不喂进提示词
  · 安全：OPENAI_* 钉 127.0.0.1；只打本机 /api/chat
  · prompt-ver＝v2（默认）＝直接支撑＋否决规则＋禁止满分扎堆＋议题锚；
    v1＝首轮宽松「像相关」提示（对照用）

判据：
  a  A0＝48/105
  b  LLM 臂 L2≥54 且相对 A0 lost＝0（与精排同族；不过⇒逃逸）
  另披露纯度与墙钟

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c84_llm_rerank.py \\
      --run-dir /tmp/six2 --prepare --out-dir /tmp/c84_llm_v2
  PYTHONPATH=. .venv/bin/python scripts/probe_c84_llm_rerank.py \\
      --run-dir /tmp/six2 --score --out-dir /tmp/c84_llm_v2
  PYTHONPATH=. .venv/bin/python scripts/probe_c84_llm_rerank.py \\
      --run-dir /tmp/six2 --run --out-dir /tmp/c84_llm_v2
  # 冒烟：只跑 1 题
  ... --score --limit 1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.export.official import _segment_locator  # noqa: E402
from scripts.probe_c62_rerank_arms import (  # noqa: E402
    _pack_with_scores,
    build_candidates,
)
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
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
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
SEG_CAP = 420  # v2 加长；仍控提示词
SEG_TAIL = 120  # 超长时保留尾部（别称／时间常在段末）
DEFAULT_PROMPT_VER = "v2"


def _lock_local() -> None:
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1/v1"
    os.environ["OPENAI_API_KEY"] = "ollama-local-only"
    assert "127.0.0.1" in os.environ["OPENAI_BASE_URL"]


def _budget(rep: dict) -> int:
    b = ((rep.get("accounting") or {}).get("pack_window") or {}).get("budget")
    if b is None:
        raise ValueError("缺 pack_window.budget")
    return int(b)


def prepare(run_dir: Path, out_dir: Path, *, k: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        query, cands, bm25_scores, _ = build_candidates(dossier, n=k)
        text_of = {
            seg.id: (seg.text or "")
            for src in dossier.sources for seg in src.segments
        }
        jobs.append({
            "case": case,
            "qid": qid,
            "query": query,
            "budget": _budget(rep),
            "report": str(rp.resolve()),
            "ids": [c["id"] for c in cands],
            "texts": [text_of.get(c["id"], "") for c in cands],
            "bm25_scores": bm25_scores,
        })
    path = out_dir / "score_input.json"
    # bm25_scores 键多，单独瘦身：只留候选分表用全表键名列表太大——仍写入（六案可承受）
    path.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    meta = {"n_questions": len(jobs), "k": k, "score_input": str(path)}
    (out_dir / "prepare_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("======== C-84 --prepare ========")
    print(f"题数＝{len(jobs)}｜K＝{k} → {path}")
    return meta


def _ollama_chat(model: str, prompt: str, *, timeout: int = 600) -> str:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 800},
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


def _parse_scores(raw: str, n: int) -> list[float]:
    """从模型输出抠 JSON 分数列表，长度必须＝n。"""
    text = raw.strip()
    # 去掉可能的 think 块
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"无 JSON：{raw[:200]}")
    obj = json.loads(m.group(0))
    if isinstance(obj, dict) and "scores" in obj:
        arr = obj["scores"]
        if arr and isinstance(arr[0], dict):
            # [{"i":0,"score":7}, ...] 或 {"id":...}
            by_i = {}
            for row in arr:
                if "i" in row:
                    by_i[int(row["i"])] = float(row.get("score") or 0)
                elif "id" in row:
                    # id 为批内 0..n-1 字符串
                    by_i[int(row["id"])] = float(row.get("score") or 0)
            out = [by_i.get(i, 0.0) for i in range(n)]
        else:
            out = [float(x) for x in arr]
    elif isinstance(obj, list):
        out = [float(x) for x in obj]
    else:
        raise ValueError(f"无法解析 scores：{obj!r}")
    if len(out) != n:
        raise ValueError(f"分数长度 {len(out)}≠{n}")
    return out


def _clip_seg(text: str) -> str:
    """超长段：留头 + 尾，降低别称／时间被切掉的概率。"""
    t = (text or "").replace("\n", " ").strip()
    if len(t) <= SEG_CAP:
        return t
    head = SEG_CAP - SEG_TAIL - 5
    if head < 80:
        return t[:SEG_CAP]
    return t[:head] + " … " + t[-SEG_TAIL:]


def _anchors_from_question(question: str) -> list[str]:
    """从议题粗抽锚：数字／年月时／书名号／较长专名片段。不求全，只给模型对照。"""
    q = question or ""
    found: list[str] = []
    for pat in (
        r"\d{4}年\d{1,2}月\d{1,2}日",
        r"\d{1,2}时\d{1,2}分(?:至\d{1,2}分)?(?:许)?",
        r"\d+(?:\.\d+)?%",
        r"\d+(?:\.\d+)?万?",
        r"「[^」]{1,24}」",
        r"“[^”]{1,24}”",
        r"《[^》]{1,24}》",
    ):
        found.extend(re.findall(pat, q))
    # 连续 2～8 个汉字的专名候选（去停用碎片）
    stop = {"还是", "应以", "还是以", "还是用", "是否", "如何", "什么", "哪些", "以及", "或者"}
    for m in re.findall(r"[\u4e00-\u9fff]{2,8}", q):
        if m in stop or m in found:
            continue
        if any(x in m for x in ("根据", "关于", "问题", "请问", "以下")):
            continue
        found.append(m)
    # 去重保序
    out, seen = [], set()
    for x in found:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:16]


def _batch_prompt_v1(question: str, batch: list[tuple[int, str]]) -> str:
    lines = [
        "你是研判材料重排器。任务：判断每段能否作为「回答该议题」的支撑证据。",
        "同义／换说法／别称也算支撑；仅背景、重复口号、无关叙述给低分。",
        "不要编造段落外事实。",
        f"议题：{question}",
        "段落（批内编号 i 从 0 起）：",
    ]
    for i, text in batch:
        lines.append(f"[{i}] {_clip_seg(text)[:280]}")
    lines += [
        f"请只输出一个 JSON 对象，格式严格为："
        f'{{\"scores\":[{{\"i\":0,\"score\":0到10的数字}},...]}}，'
        f"数组长度必须等于 {len(batch)}，i 为上面的编号。",
    ]
    return "\n".join(lines)


def _batch_prompt_v2(question: str, batch: list[tuple[int, str]]) -> str:
    anchors = _anchors_from_question(question)
    anchor_line = "、".join(anchors) if anchors else "（从议题自行抽出主体／时间／数字／地点）"
    n = len(batch)
    max_high = max(1, min(3, n // 4))  # 一批里高分名额收紧
    lines = [
        "你是研判材料重排器。只为「装箱优先级」打分，不是写摘要。",
        "核心问题：这段是否直接支撑回答该议题（含换说法／别称／同指）？",
        "「跟话题沾边」≠支撑。不要编造段落外事实。",
        "",
        "分档（必须拉开差距，禁止多数段落同分满分）：",
        "  9–10＝直接回答议题要点（事实／数字／时点／主体对得上，换说法也算）",
        "  6–8＝部分支撑（有相关事实但缺议题关键点）",
        "  3–5＝弱相关背景",
        "  0–2＝无关、换主体、纯态度口号、重复无新信息",
        "",
        "否决（命中则分数上限）：",
        "  · 只有事件背景／花絮，没有议题要的那个事实 → ≤2",
        "  · 主体／地点／事件换了（别的口岸／空难／人物） → ≤1",
        "  · 只有态度、呼吁、评论，无可核对事实 → ≤3",
        "  · 说不清对应议题哪一句 → ≤4，且不得打 9–10",
        "",
        f"本批共 {n} 段：打 9–10 的不超过 {max_high} 段；其余必须明显更低。",
        "若拿不准，宁低勿高。",
        "",
        f"议题：{question}",
        f"议题锚（对齐这些再给高分；别称／同指算对齐）：{anchor_line}",
        "段落（批内编号 i 从 0 起）：",
    ]
    for i, text in batch:
        lines.append(f"[{i}] {_clip_seg(text)}")
    lines += [
        "请只输出一个 JSON 对象，格式严格为："
        f'{{\"scores\":[{{\"i\":0,\"score\":0到10的数字}},...]}}，'
        f"数组长度必须等于 {n}，i 为上面的编号；不要解释。",
    ]
    return "\n".join(lines)


def _batch_prompt(
    question: str, batch: list[tuple[int, str]], *, prompt_ver: str,
) -> str:
    if prompt_ver == "v1":
        return _batch_prompt_v1(question, batch)
    if prompt_ver == "v2":
        return _batch_prompt_v2(question, batch)
    raise ValueError(f"未知 prompt-ver：{prompt_ver}")


def score_llm(
    out_dir: Path,
    *,
    model: str,
    batch_size: int,
    limit: int | None,
    prompt_ver: str = DEFAULT_PROMPT_VER,
) -> dict:
    _lock_local()
    jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    if limit is not None:
        jobs = jobs[: max(1, limit)]
    cache_path = out_dir / "llm_scores.json"
    done: dict[str, list[float]] = {}
    if cache_path.is_file():
        done = json.loads(cache_path.read_text(encoding="utf-8"))

    t0 = time.time()
    n_calls = 0
    for ji, job in enumerate(jobs, 1):
        key = f"{job['case']}::{job['qid']}"
        if key in done and len(done[key]) == len(job["ids"]):
            print(f"  [{ji}/{len(jobs)}] {key[:36]} 缓存命中", flush=True)
            continue
        ids = job["ids"]
        texts = job["texts"]
        q = job["query"]
        scores = [0.0] * len(ids)
        for start in range(0, len(ids), batch_size):
            # 批内 i 从 0 重编号
            local = [(i, t) for i, t in enumerate(texts[start:start + batch_size])]
            prompt = _batch_prompt(q, local, prompt_ver=prompt_ver)
            raw = _ollama_chat(model, prompt)
            n_calls += 1
            try:
                part = _parse_scores(raw, len(local))
            except Exception as exc:
                # 一次重试
                raw2 = _ollama_chat(model, prompt + "\n再次确认：只输出 JSON。")
                n_calls += 1
                try:
                    part = _parse_scores(raw2, len(local))
                except Exception:
                    print(f"    批 {start} 解析失败，该批记 0：{exc}", flush=True)
                    print(f"    raw头：{raw[:180]!r}", flush=True)
                    part = [0.0] * len(local)
            for j, sc in enumerate(part):
                scores[start + j] = float(sc)
        done[key] = scores
        cache_path.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        print(
            f"  [{ji}/{len(jobs)}] {key[:36]} n={len(ids)} "
            f"calls累计={n_calls}",
            flush=True,
        )

    meta = {
        "model": model,
        "batch_size": batch_size,
        "prompt_ver": prompt_ver,
        "seg_cap": SEG_CAP,
        "seg_tail": SEG_TAIL,
        "n_questions_scored": len(jobs),
        "n_calls": n_calls,
        "elapsed_s": round(time.time() - t0, 1),
        "ollama": OLLAMA,
    }
    (out_dir / "score_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"打分墙钟＝{meta['elapsed_s']}s 调用＝{n_calls} → {cache_path}")
    return meta


def _gold_keys(gold_dir: Path, case: str, qid: str):
    g, _ = gold_paras_for_question(gold_dir / case, qid)
    return set(g.keys()), len(g)


def run_measure(out_dir: Path, gold_dir: Path) -> dict[str, Any]:
    jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    scores_all = json.loads((out_dir / "llm_scores.json").read_text(encoding="utf-8"))
    tot = Counter()
    rows = []
    lost_n = gained_n = 0
    for job in jobs:
        key = f"{job['case']}::{job['qid']}"
        sc = scores_all.get(key)
        if not sc or len(sc) != len(job["ids"]):
            raise SystemExit(f"缺分或不齐：{key}")
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

        cands = [{"id": i} for i in job["ids"]]
        # bm25 全表：从 job 恢复；prepare 已写入
        bm25_scores = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        # LLM 主序；并列时按 BM25 打破（避免同分落成段 id 字母序乱排）
        max_b = max(bm25_scores.values()) if bm25_scores else 1.0
        max_b = max_b if max_b > 0 else 1.0
        fused = {sid: 0.0 for sid in bm25_scores}
        for cid, llm_sc in zip(job["ids"], sc):
            b = float(bm25_scores.get(cid, 0.0)) / max_b
            fused[cid] = float(llm_sc) * 1000.0 + b
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
            "llm_hits": hits_l, "llm_n": len(sel_l),
            "lost": len(lost), "gained": len(gained),
        })
        tot["denom"] += denom
        tot["a0_hits"] += hits_a
        tot["a0_n"] += len(sel_a)
        tot["llm_hits"] += hits_l
        tot["llm_n"] += len(sel_l)

    return {
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "a0": {
            "l2_hits": int(tot["a0_hits"]),
            "n_selected": int(tot["a0_n"]),
            "precision": round(tot["a0_hits"] / tot["a0_n"], 4) if tot["a0_n"] else 0,
            "recall": round(tot["a0_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        "llm": {
            "l2_hits": int(tot["llm_hits"]),
            "n_selected": int(tot["llm_n"]),
            "precision": round(tot["llm_hits"] / tot["llm_n"], 4) if tot["llm_n"] else 0,
            "recall": round(tot["llm_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        "lost_n": lost_n,
        "gained_n": gained_n,
        "rows": rows,
    }


def judge(summary: dict) -> dict:
    a_ok = summary["a0"]["l2_hits"] == TARGET_A0 and summary["denom"] == TARGET_DENOM
    b_ok = (
        summary["llm"]["l2_hits"] >= TARGET_L2
        and summary["lost_n"] == 0
        and summary["denom"] == TARGET_DENOM
    )
    return {
        "a": {"ok": a_ok, "got": f"{summary['a0']['l2_hits']}/{summary['denom']}"},
        "b": {
            "ok": b_ok,
            "got": f"{summary['llm']['l2_hits']}/{summary['denom']}",
            "lost_n": summary["lost_n"],
            "gained_n": summary["gained_n"],
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", default="/tmp/c84_llm")
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--prompt-ver", default=DEFAULT_PROMPT_VER, choices=["v1", "v2"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)

    if args.dry_run and not (args.prepare or args.score or args.run):
        print("======== C-84 --dry-run ========")
        print(
            f"形态＝BM25 前 K={args.k} → Ollama {args.model} "
            f"批={args.batch_size} prompt={args.prompt_ver} → 装箱"
        )
        print("判据 a＝A0 48/105；b＝LLM L2≥54 且 lost=0")
        return 0

    if args.prepare:
        prepare(Path(args.run_dir), out_dir, k=args.k)
        if not args.score and not args.run:
            return 0

    if args.score:
        score_llm(
            out_dir, model=args.model, batch_size=args.batch_size,
            limit=args.limit, prompt_ver=args.prompt_ver,
        )
        if not args.run:
            return 0

    if args.run:
        # 若 score_input 被 --limit 截过，measure 仍读全量；要求全量分数
        summary = run_measure(out_dir, Path(args.gold_dir))
        print("======== C-84 到达面 ========")
        print(
            f"题数＝{summary['n_questions']}｜分母＝{summary['denom']}｜"
            f"prompt={args.prompt_ver}"
        )
        for name in ("a0", "llm"):
            r = summary[name]
            print(
                f"  {name.upper():3}｜L2 {r['l2_hits']}/{summary['denom']} "
                f"（{r['recall']:.3f}）｜装入 {r['n_selected']}｜纯度 {r['precision']:.4f}"
            )
        print(f"相对 A0：lost＝{summary['lost_n']}｜gained＝{summary['gained_n']}")
        j = judge(summary)
        print("判据 a", "✅" if j["a"]["ok"] else "❌", j["a"])
        print("判据 b", "✅" if j["b"]["ok"] else "❌（逃逸）", j["b"])
        (out_dir / "summary.json").write_text(
            json.dumps(
                {"summary": summary, "judge": j, "prompt_ver": args.prompt_ver},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        print(f"落盘 {out_dir / 'summary.json'}")
        return 0 if j["a"]["ok"] else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
