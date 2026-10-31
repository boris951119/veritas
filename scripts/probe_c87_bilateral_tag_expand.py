#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-87：切片大→小打标 → 标签扩写 ↔ 议题扩写 → BM25 → 支撑终审（只量）。

协议（用户双边扩写方案；先吉隆一案打通）：
  1) 短段规则桩；长段 LLM 紧凑打标 path+ents（大→小）
  2) Agent1：对「唯一 path」扩写（同义/别称/上位/因果）；禁只吐热词
  3) Agent2：议题扩写（同义/类别/答案形推测）
  4) 用「标签扩写文本」作伪文档，对扩写议题做 BM25，取前 K
  5) 与原 BM25-K 池去重披露；终审只问「能否支撑主张」
  6) 可观测门（分析师建议＝量尺不是保险）：
       gate_substance   扩写含实体/时间/量名/因果 的占比
       gate_hotword     扩写相对议题热词的重叠率（过高＝滑回热词坑）
       gate_unique_pool 召回相对 BM25-K 的独有段占比
       gate_unique_gold 独有段里的金标数（相对 BM25-K 未召回金标）
       lost / L2        终审装箱相对 A0

判据（吉隆打通＝非六案逃逸票）：
  - 门全绿且该案 L2>A0 且 lost=0 → 值得扩六案
  - 任一关键门红 → 方案未过，不进生产

用法：
  # 吉隆打标（可恢复）
  PYTHONPATH=. .venv/bin/python scripts/probe_c87_bilateral_tag_expand.py \\
      --run-dir /tmp/six2 --case-filter 吉隆 --tag --out-dir /tmp/c87_jilong
  # 扩标签 + 扩议题 + 召回 + 审
  ... --expand-labels --expand-questions --retrieve --review --score --out-dir /tmp/c87_jilong
  # 一键（打标若已有缓存会跳过）
  ... --auto --case-filter 吉隆 --out-dir /tmp/c87_jilong
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bm25 import _tokens  # noqa: E402
from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from scripts.probe_c62_rerank_arms import (  # noqa: E402
    _bm25_table,
    _pack_with_scores,
    _query_of,
)
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c84_llm_rerank import (  # noqa: E402
    _budget,
    _lock_local,
    _parse_scores,
)
from scripts.probe_c85_anchor_review import (  # noqa: E402
    DEFAULT_BATCH,
    DEFAULT_MODEL,
    _fuse,
    _ollama_chat,
    extract_anchors,
    _fallback_anchors,
    _gold_keys,
)


def _parse_json_obj(raw: str) -> dict:
    """比 C-85 更耐脏：截 think、取首个对象、容忍尾部 Extra data。"""
    text = re.sub(r"<think>.*?</think>", "", raw.strip(), flags=re.S)
    m = re.search(r"\{", text)
    if not m:
        raise ValueError(f"无 JSON：{raw[:200]}")
    blob = text[m.start():]
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError:
        obj, _end = json.JSONDecoder().raw_decode(blob)
    if not isinstance(obj, dict):
        raise ValueError("JSON 非对象")
    return obj
from scripts.probe_recall_funnel import DEFAULT_GOLD, discover_reports  # noqa: E402

SHORT_MAX = 20
DEFAULT_TAG_BATCH = 16
DEFAULT_K = 120
DEFAULT_BM25_K = 60
# 可观测门阈值（吉隆打通用；六案另议）
GATE_SUBSTANCE_MIN = 0.70
GATE_HOTWORD_MAX = 0.55
GATE_UNIQUE_POOL_MIN = 0.25
_TEMPLATE_PATH = "领域/事件/地点或主体/切面"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _ollama_chat_long(model: str, prompt: str, *, timeout: int = 600,
                      num_predict: int = 1400) -> str:
    """打标用：比 C-85 默认更高的 num_predict，避免批 JSON 截断。"""
    import os
    import urllib.request
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": num_predict},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str((data.get("message") or {}).get("content") or "")


def _case_qid(rp: Path) -> tuple[str, str]:
    return rp.parts[-4], rp.parts[-2]


def _clip(text: str, n: int = 180) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _hot_terms(question: str) -> set[str]:
    """议题热词：去掉极短 token。"""
    return {t for t in _tokens(question) if len(t) >= 2}


_ENTITY_RE = re.compile(
    r"("
    r"\d{1,4}年|\d{1,2}月|\d{1,2}日|\d{1,2}时|\d{1,2}分|"
    r"\d+(?:\.\d+)?(?:人|名|米|公里|万吨|亿元|%|例|架|艘)|"
    r"冰川|堰塞|口岸|泥石流|崩塌|失联|遇难|救援|航班|坠毁|冲突"
    r")"
)


def _has_substance(terms: list[str]) -> bool:
    blob = " ".join(terms)
    if _ENTITY_RE.search(blob):
        return True
    # 因果链词
    if any(x in blob for x in ("导致", "引发", "起因", "因", "造成", "→", "->", "致使")):
        return True
    return False


def _hotword_overlap(terms: list[str], hot: set[str]) -> float:
    toks: list[str] = []
    for t in terms:
        toks.extend(_tokens(t))
    if not toks:
        return 1.0
    hit = sum(1 for t in toks if t in hot)
    return hit / len(toks)


# ---------------------------------------------------------------------------
# 伪文档 BM25（标签扩写文本作 doc）
# ---------------------------------------------------------------------------

def _bm25_over_docs(
    docs: list[tuple[str, str]], query: str,
) -> list[tuple[str, float]]:
    """轻量 BM25：docs=[(id, text)]，返回 [(id, score)] 降序。"""
    if not docs:
        return []
    tok_docs = [(sid, _tokens(text)) for sid, text in docs]
    n = len(tok_docs)
    df: dict[str, int] = {}
    for _, toks in tok_docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    avgdl = sum(len(toks) for _, toks in tok_docs) / n
    q_terms = set(_tokens(query))
    k1, b = 1.5, 0.75
    out: list[tuple[str, float]] = []
    for sid, toks in tok_docs:
        if not toks:
            out.append((sid, 0.0))
            continue
        tf: Counter[str] = Counter(toks)
        dl = len(toks)
        sc = 0.0
        for t in q_terms:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            f = tf[t]
            sc += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        out.append((sid, float(sc)))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def _rrf_fuse(rankings: list[list[tuple[str, float]]], *, k: int = 60) -> list[tuple[str, float]]:
    fused: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        rank = 0
        for sid, score in ranking:
            if score <= 0:
                continue
            fused[sid] += 1.0 / (k + rank + 1)
            rank += 1
    out = [(sid, round(sc, 6)) for sid, sc in fused.items()]
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


# ---------------------------------------------------------------------------
# Phase 1: 打标
# ---------------------------------------------------------------------------

def _stub_tag(text: str) -> dict[str, Any]:
    ents = _ENTITY_RE.findall(text)[:4]
    return {
        "p": "短片/杂讯/未知/其他",
        "e": list(dict.fromkeys(ents)),
        "src": "rule",
    }


def _tag_prompt(batch: list[tuple[int, str]]) -> str:
    items = "\n".join(f"[{i}] {_clip(t, 160)}" for i, t in batch)
    return "\n".join([
        "编目员。每段输出大→小路径+实体。不答题、不扩写、不编造原文没有的实体。",
        "p 用 / 连接，至少三段：领域/事件/地点或主体；有把握再加第四段切面。",
        "切面可选：成因|时点|量值|伤亡|救援|处置|地质|交通|其他。",
        "e＝原文可核验实体/时间/量名，最多 4 个；没有则 []。",
        "正确示例：p=\"自然灾害/泥石流/吉隆口岸/伤亡\" e=[\"43人遇难\",\"9月5日\"]",
        "也正确：p=\"自然灾害/泥石流/吉隆口岸\" e=[\"8月26日\"]",
        "错误示例：p=\"领域/事件/地点或主体/切面\"（禁止照抄说明文字）。",
        "段落：", items,
        '只输出 JSON：{"items":[{"i":0,"p":"自然灾害/泥石流/吉隆口岸/伤亡","e":["43人遇难"]}]}',
    ])


def collect_case_segments(run_dir: Path, case_filter: str) -> tuple[str, Path, list[dict]]:
    """取命中 case_filter 的第一案（同案多题共用信源）。"""
    rps = [rp for rp in discover_reports(run_dir) if case_filter in rp.parts[-4]]
    if not rps:
        raise SystemExit(f"无案卷匹配 case-filter={case_filter!r}")
    # 按案名分组，取第一个案的 q_001 报告
    by_case: dict[str, list[Path]] = defaultdict(list)
    for rp in rps:
        by_case[rp.parts[-4]].append(rp)
    case = sorted(by_case.keys())[0]
    rp = sorted(by_case[case], key=lambda p: p.parts[-2])[0]
    rep = json.loads(rp.read_text(encoding="utf-8"))
    segs = []
    for src in rep.get("sources") or []:
        for seg in src.get("segments") or []:
            segs.append({
                "id": seg["id"],
                "source_id": seg.get("source_id") or src.get("id"),
                "text": (seg.get("text") or "").strip(),
            })
    return case, rp, segs


def phase_tag(
    run_dir: Path,
    out_dir: Path,
    *,
    case_filter: str,
    model: str,
    batch_size: int,
    limit_segs: int | None,
) -> dict:
    _lock_local()
    out_dir.mkdir(parents=True, exist_ok=True)
    case, rp, segs = collect_case_segments(run_dir, case_filter)
    if limit_segs is not None:
        segs = segs[: max(1, limit_segs)]

    cache_path = out_dir / "tags.json"
    done: dict[str, dict] = {}
    if cache_path.is_file():
        done = json.loads(cache_path.read_text(encoding="utf-8"))

    # 规则桩短段
    long_ids: list[str] = []
    for s in segs:
        sid, text = s["id"], s["text"]
        if sid in done and done[sid].get("p"):
            continue
        if len(text) <= SHORT_MAX:
            done[sid] = _stub_tag(text)
        else:
            long_ids.append(sid)

    text_of = {s["id"]: s["text"] for s in segs}
    # 待打标长段
    todo = [sid for sid in long_ids if sid not in done or not done[sid].get("p")]
    t0 = time.time()
    n_calls = 0
    n_fail = 0

    def _flush() -> None:
        cache_path.write_text(
            json.dumps(done, ensure_ascii=False), encoding="utf-8")

    _flush()
    print(
        f"======== C-87 --tag case={case} ========\n"
        f"总段＝{len(segs)}｜短段已桩＝{sum(1 for s in segs if len(s['text'])<=SHORT_MAX)}｜"
        f"长段待打＝{len(todo)}｜批＝{batch_size}",
        flush=True,
    )

    for bi in range(0, len(todo), batch_size):
        batch_ids = todo[bi: bi + batch_size]
        local = [(i, text_of[sid]) for i, sid in enumerate(batch_ids)]
        prompt = _tag_prompt(local)
        try:
            raw = _ollama_chat_long(model, prompt, timeout=600)
        except Exception as exc:
            print(f"  打标网络/调用失败 batch@{bi}: {exc}", flush=True)
            n_fail += 1
            for sid in batch_ids:
                done[sid] = {
                    **_stub_tag(text_of[sid]),
                    "p": "降级/调用失败/未知/其他",
                    "src": "fail",
                }
            _flush()
            continue
        n_calls += 1
        try:
            obj = _parse_json_obj(raw)
            items = obj.get("items") or []
        except Exception:
            raw2 = _ollama_chat_long(
                model, prompt + "\n再次确认：只输出完整 JSON；p 禁止照抄说明文字。",
                timeout=600)
            n_calls += 1
            try:
                obj = _parse_json_obj(raw2)
                items = obj.get("items") or []
            except Exception as exc:
                print(f"  打标失败 batch@{bi}: {exc}", flush=True)
                n_fail += 1
                for sid in batch_ids:
                    # 降级：规则从原文抽实体
                    done[sid] = {
                        **_stub_tag(text_of[sid]),
                        "p": "降级/未解析/未知/其他",
                        "src": "fail",
                    }
                _flush()
                continue

        by_i = {}
        for it in items:
            try:
                by_i[int(it.get("i"))] = it
            except Exception:
                continue
        for i, sid in enumerate(batch_ids):
            it = by_i.get(i)
            stub = _stub_tag(text_of[sid])
            if it is None:
                # 批 JSON 缺该项：实体启发式路径，不算模板拒
                ents = stub["e"]
                locus = ents[0] if ents else "未知"
                done[sid] = {
                    "p": f"未归类/事件片段/{locus}/其他",
                    "e": ents,
                    "src": "partial_miss",
                }
                continue
            p = str(it.get("p") or "").strip()
            e = [str(x).strip() for x in (it.get("e") or []) if str(x).strip()][:4]
            if not e:
                e = stub["e"]
            # 至少「领域/事件/地点」三段（≥2 个 /）；四段更佳但不强求切面
            bad = (
                (not p)
                or p == _TEMPLATE_PATH
                or p.count("/") < 2
                or p.startswith("未标/")
                or p.startswith("降级/")
                or "领域/事件" in p
            )
            if bad:
                locus = (e[0] if e else "未知")[:24]
                done[sid] = {
                    "p": f"未归类/事件片段/{locus}/其他",
                    "e": e,
                    "src": "path_repair",
                }
            else:
                done[sid] = {"p": p, "e": e, "src": "llm"}
        _flush()
        done_n = min(bi + len(batch_ids), len(todo))
        print(
            f"  tag [{done_n}/{len(todo)}] calls={n_calls} "
            f"elapsed={round(time.time()-t0,0):.0f}s",
            flush=True,
        )

    meta = {
        "phase": "tag",
        "case": case,
        "report": str(rp),
        "n_segs": len(segs),
        "n_tagged": len(done),
        "n_calls": n_calls,
        "n_fail": n_fail,
        "batch_size": batch_size,
        "model": model,
        "elapsed_s": round(time.time() - t0, 1),
        "short_max": SHORT_MAX,
    }
    (out_dir / "tag_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    # 段清单（供后续）
    (out_dir / "segments.json").write_text(
        json.dumps({"case": case, "report": str(rp), "segs": segs}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"打标完成 调用＝{n_calls} 失败批＝{n_fail} 墙钟＝{meta['elapsed_s']}s → {cache_path}")
    return meta


# ---------------------------------------------------------------------------
# Phase 2: 唯一 path 扩写（Agent1）
# ---------------------------------------------------------------------------

def _label_expand_prompt(path: str, ents_samples: list[str], hot_block: str) -> str:
    return "\n".join([
        "检索助理。任务：为这条「切片标签」扩写检索用语，不要答题。",
        "扩写维度：同义／别称／类别上位／因果链推测。",
        "硬约束：禁止只吐议题热词或通稿套话；每条扩写须含可核验实体、时间、量名或因果链词。",
        f"标签 path：{path}",
        f"常见实体样例：{json.dumps(ents_samples[:8], ensure_ascii=False)}",
        f"议题热词（禁止只围着这些转）：{hot_block}",
        '只输出 JSON：{"expand":["检索句1","检索句2",...],"keywords":["词1",...]}',
        "expand 3～8 条；keywords 最多 12 个。",
    ])


def phase_expand_labels(
    out_dir: Path,
    *,
    model: str,
    questions: list[str],
    llm_min_count: int = 3,
    llm_top_n: int = 60,
) -> dict:
    _lock_local()
    tags = json.loads((out_dir / "tags.json").read_text(encoding="utf-8"))
    # 聚 path → 实体样例 + 频次
    by_path: dict[str, list[str]] = defaultdict(list)
    path_count: Counter[str] = Counter()
    for sid, rec in tags.items():
        p = str(rec.get("p") or "未标")
        path_count[p] += 1
        for e in rec.get("e") or []:
            if e and e not in by_path[p]:
                by_path[p].append(str(e))

    hot = set()
    for q in questions:
        hot |= _hot_terms(q)
    hot_block = "、".join(sorted(hot)[:24])

    cache_path = out_dir / "label_expansions.json"
    done: dict[str, dict] = {}
    if cache_path.is_file():
        done = json.loads(cache_path.read_text(encoding="utf-8"))

    paths = sorted(by_path.keys(), key=lambda x: (-path_count[x], x))
    # 高频 path 才走 LLM；长尾／短片／未归类用规则扩（path 切段＋实体）
    llm_candidates = [
        p for p in paths
        if path_count[p] >= llm_min_count
        and not p.startswith(("短片/", "降级/", "未归类/"))
    ][:llm_top_n]
    llm_set = set(llm_candidates)

    t0 = time.time()
    n_calls = 0
    n_rule = 0
    substance_hit = 0
    hot_rates: list[float] = []

    print(
        f"======== C-87 --expand-labels 唯一path＝{len(paths)} "
        f"LLM档＝{len(llm_set)}(≥{llm_min_count}取前{llm_top_n}) ========",
        flush=True,
    )
    for i, p in enumerate(paths, 1):
        if p in done and (done[p].get("expand") or done[p].get("keywords")):
            exp = done[p]
        else:
            ents = by_path[p][:8]
            use_rule = p not in llm_set or p.startswith(("短片/", "降级/", "未归类/"))
            if use_rule:
                # path 切段当关键词 + 实体
                parts = [x for x in p.split("/") if x and x not in ("未知", "其他", "未归类")]
                exp = {
                    "expand": (ents[:3] or parts[:3] or [p]),
                    "keywords": list(dict.fromkeys(parts + ents))[:12],
                    "src": "rule",
                }
                n_rule += 1
            else:
                prompt = _label_expand_prompt(p, ents, hot_block)
                raw = _ollama_chat(model, prompt)
                n_calls += 1
                try:
                    exp = _parse_json_obj(raw)
                except Exception:
                    raw2 = _ollama_chat(model, prompt + "\n再次确认：只输出 JSON。")
                    n_calls += 1
                    try:
                        exp = _parse_json_obj(raw2)
                    except Exception:
                        exp = {
                            "expand": [p] + ents[:3],
                            "keywords": ents[:6],
                            "_fallback": True,
                        }
                exp["expand"] = [
                    str(x).strip() for x in (exp.get("expand") or []) if str(x).strip()
                ][:8]
                exp["keywords"] = [
                    str(x).strip() for x in (exp.get("keywords") or []) if str(x).strip()
                ][:12]
                exp["src"] = exp.get("src") or "llm"
            done[p] = exp
            cache_path.write_text(
                json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")

        terms = list(exp.get("expand") or []) + list(exp.get("keywords") or [])
        if _has_substance(terms):
            substance_hit += 1
        hot_rates.append(_hotword_overlap(terms, hot))
        if i % 50 == 0 or i == len(paths):
            print(
                f"  lab-exp [{i}/{len(paths)}] llm_calls={n_calls} rule={n_rule}",
                flush=True,
            )

    # 合成每段伪文档
    synth: dict[str, str] = {}
    for sid, rec in tags.items():
        p = str(rec.get("p") or "")
        exp = done.get(p) or {}
        parts = [p]
        parts.extend(rec.get("e") or [])
        parts.extend(exp.get("expand") or [])
        parts.extend(exp.get("keywords") or [])
        synth[sid] = " ".join(str(x) for x in parts if x)

    (out_dir / "synth_docs.json").write_text(
        json.dumps(synth, ensure_ascii=False), encoding="utf-8")

    n_paths = max(1, len(paths))
    avg_hot = sum(hot_rates) / max(1, len(hot_rates))
    gates = {
        "gate_substance": {
            "value": round(substance_hit / n_paths, 4),
            "threshold_min": GATE_SUBSTANCE_MIN,
            "ok": (substance_hit / n_paths) >= GATE_SUBSTANCE_MIN,
            "n_ok": substance_hit,
            "n": len(paths),
        },
        "gate_hotword": {
            "value": round(avg_hot, 4),
            "threshold_max": GATE_HOTWORD_MAX,
            "ok": avg_hot <= GATE_HOTWORD_MAX,
        },
    }
    meta = {
        "phase": "expand_labels",
        "n_paths": len(paths),
        "n_llm_paths": len(llm_set),
        "n_rule": n_rule,
        "llm_min_count": llm_min_count,
        "llm_top_n": llm_top_n,
        "n_calls": n_calls,
        "elapsed_s": round(time.time() - t0, 1),
        "model": model,
        "gates": gates,
    }
    (out_dir / "label_expand_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"标签扩写完成 path＝{len(paths)} 调用＝{n_calls} "
        f"substance={gates['gate_substance']} hotword={gates['gate_hotword']}",
        flush=True,
    )
    return meta


# ---------------------------------------------------------------------------
# Phase 3: 议题扩写（Agent2）
# ---------------------------------------------------------------------------

def _question_expand_prompt(question: str) -> str:
    return "\n".join([
        "检索助理。为议题扩写检索问句，不要答题。",
        "维度：同义／别称／类别范围／「答案可能长什么样」的推测（量名、时点、因果链形态）。",
        "硬约束：禁止只吐议题热词或通稿套话；须带可核验实体、时间、量名或因果链形态。",
        f"议题：{question}",
        '只输出 JSON：{"queries":[".."],"keywords":[".."],'
        '"answer_shape":["答案可能含的量名/时点/因果形态",...]}',
        "queries 3～8 条；keywords≤16；answer_shape≤6。",
    ])


def phase_expand_questions(
    run_dir: Path,
    out_dir: Path,
    *,
    case_filter: str,
    model: str,
) -> dict:
    _lock_local()
    jobs = []
    for rp in discover_reports(run_dir):
        case, qid = _case_qid(rp)
        if case_filter not in case:
            continue
        rep = json.loads(rp.read_text(encoding="utf-8"))
        dossier = Dossier.from_dict(rep)
        jobs.append({
            "case": case,
            "qid": qid,
            "query": _query_of(dossier),
            "budget": _budget(rep),
            "report": str(rp.resolve()),
        })
    if not jobs:
        raise SystemExit(f"无题匹配 case-filter={case_filter!r}")

    cache_path = out_dir / "question_expansions.json"
    done: dict[str, dict] = {}
    if cache_path.is_file():
        done = json.loads(cache_path.read_text(encoding="utf-8"))

    t0 = time.time()
    n_calls = 0
    substance_hit = 0
    hot_rates: list[float] = []
    print(f"======== C-87 --expand-questions 题数＝{len(jobs)} ========", flush=True)
    for ji, job in enumerate(jobs, 1):
        key = f"{job['case']}::{job['qid']}"
        if key in done and (done[key].get("queries") or done[key].get("keywords")):
            obj = done[key]
            print(f"  q-exp [{ji}/{len(jobs)}] {key[:40]} 缓存", flush=True)
        else:
            prompt = _question_expand_prompt(job["query"])
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
                    obj = {
                        "queries": [job["query"]],
                        "keywords": [],
                        "answer_shape": [],
                        "_fallback": True,
                    }
            qs = [str(x).strip() for x in (obj.get("queries") or []) if str(x).strip()]
            if job["query"] not in qs:
                qs = [job["query"]] + qs
            obj["queries"] = list(dict.fromkeys(qs))[:10]
            obj["keywords"] = [
                str(x).strip() for x in (obj.get("keywords") or []) if str(x).strip()
            ][:16]
            obj["answer_shape"] = [
                str(x).strip() for x in (obj.get("answer_shape") or []) if str(x).strip()
            ][:6]
            done[key] = obj
            cache_path.write_text(
                json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  q-exp [{ji}/{len(jobs)}] {key[:40]} n_q={len(obj['queries'])}", flush=True)

        terms = (
            list(obj.get("queries") or [])
            + list(obj.get("keywords") or [])
            + list(obj.get("answer_shape") or [])
        )
        if _has_substance(terms):
            substance_hit += 1
        hot_rates.append(_hotword_overlap(terms, _hot_terms(job["query"])))

    (out_dir / "question_jobs.json").write_text(
        json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")

    n = max(1, len(jobs))
    avg_hot = sum(hot_rates) / max(1, len(hot_rates))
    gates = {
        "gate_substance_q": {
            "value": round(substance_hit / n, 4),
            "threshold_min": GATE_SUBSTANCE_MIN,
            "ok": (substance_hit / n) >= GATE_SUBSTANCE_MIN,
        },
        "gate_hotword_q": {
            "value": round(avg_hot, 4),
            "threshold_max": GATE_HOTWORD_MAX,
            "ok": avg_hot <= GATE_HOTWORD_MAX,
        },
    }
    meta = {
        "phase": "expand_questions",
        "n_questions": len(jobs),
        "n_calls": n_calls,
        "elapsed_s": round(time.time() - t0, 1),
        "model": model,
        "gates": gates,
    }
    (out_dir / "question_expand_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"议题扩写完成 调用＝{n_calls} gates={gates}", flush=True)
    return meta


# ---------------------------------------------------------------------------
# Phase 4: 双边 BM25 召回 + 独有门
# ---------------------------------------------------------------------------

def phase_retrieve(
    out_dir: Path,
    *,
    k: int,
    bm25_k: int,
    gold_dir: Path,
) -> dict:
    synth = json.loads((out_dir / "synth_docs.json").read_text(encoding="utf-8"))
    jobs = json.loads((out_dir / "question_jobs.json").read_text(encoding="utf-8"))
    qexp = json.loads((out_dir / "question_expansions.json").read_text(encoding="utf-8"))
    docs = list(synth.items())

    score_jobs = []
    gate_rows = []
    for job in jobs:
        key = f"{job['case']}::{job['qid']}"
        exp = qexp.get(key) or {}
        queries = [str(q).strip() for q in (exp.get("queries") or []) if str(q).strip()]
        if not queries:
            queries = [job["query"]]
        # answer_shape / keywords 并成一路
        extra = list(exp.get("keywords") or []) + list(exp.get("answer_shape") or [])
        if extra:
            queries = list(dict.fromkeys(queries + [" ".join(extra[:12])]))

        rankings = [_bm25_over_docs(docs, q) for q in queries]
        fused = _rrf_fuse(rankings)
        label_scores = {sid: float(sc) for sid, sc in fused}
        for sid in synth:
            label_scores.setdefault(sid, 0.0)
        ids = [sid for sid, _ in fused[:k]]

        # 原文 BM25 对照池
        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        text_of = {
            seg.id: (seg.text or "")
            for src in dossier.sources for seg in src.segments
        }
        bm25_ranked = _bm25_table(dossier)
        bm25_scores = dict(bm25_ranked)
        bm25_pool = {sid for sid, _ in bm25_ranked[:bm25_k]}

        label_pool = set(ids)
        unique = label_pool - bm25_pool
        overlap = label_pool & bm25_pool

        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        # gold keys are (doc, para); selected_locs maps sid→loc
        # 用 selected_locs 风格：从 id 拆 doc#pN
        def _locs(sids: set[str]) -> set[tuple[str, str]]:
            out = set()
            for sid in sids:
                if "#" not in sid:
                    continue
                doc, para = sid.split("#", 1)
                out.add((doc, para if para.startswith("p") else f"p{para}"))
                # 金标里 para 有时不带 p
                out.add((doc, para.lstrip("p") if para.startswith("p") else para))
                out.add((doc, para))
            return out

        # 更稳：走 selected_locs
        loc_label = selected_locs(dossier, label_pool)
        loc_bm25 = selected_locs(dossier, bm25_pool)
        gold_in_label = gold & loc_label
        gold_in_bm25 = gold & loc_bm25
        unique_gold = gold_in_label - gold_in_bm25
        missed_by_both = gold - gold_in_label - gold_in_bm25

        row = {
            "case": job["case"],
            "qid": job["qid"],
            "denom": denom,
            "k": k,
            "bm25_k": bm25_k,
            "n_label_pool": len(label_pool),
            "n_bm25_pool": len(bm25_pool),
            "n_overlap": len(overlap),
            "n_unique": len(unique),
            "unique_ratio": round(len(unique) / max(1, len(label_pool)), 4),
            "gold_in_label": len(gold_in_label),
            "gold_in_bm25": len(gold_in_bm25),
            "unique_gold": len(unique_gold),
            "missed_by_both": len(missed_by_both),
        }
        gate_rows.append(row)

        score_jobs.append({
            **job,
            "ids": ids,
            "texts": [text_of.get(i, "") for i in ids],
            "bm25_scores": bm25_scores,  # 原文 BM25，终审 fuse 破并列用
            "label_scores": label_scores,
            "cand_mode": "bilateral_label_bm25",
            "k": k,
            "expand_queries": queries,
            "unique_ids": sorted(unique)[:50],
            "gate_row": row,
        })

    path = out_dir / "score_input.json"
    path.write_text(json.dumps(score_jobs, ensure_ascii=False), encoding="utf-8")

    # 聚合门
    tot_unique = sum(r["n_unique"] for r in gate_rows)
    tot_pool = sum(r["n_label_pool"] for r in gate_rows)
    tot_unique_gold = sum(r["unique_gold"] for r in gate_rows)
    tot_gold_bm25 = sum(r["gold_in_bm25"] for r in gate_rows)
    tot_gold_label = sum(r["gold_in_label"] for r in gate_rows)
    avg_unique_ratio = (
        sum(r["unique_ratio"] for r in gate_rows) / max(1, len(gate_rows))
    )
    gates = {
        "gate_unique_pool": {
            "value": round(avg_unique_ratio, 4),
            "threshold_min": GATE_UNIQUE_POOL_MIN,
            "ok": avg_unique_ratio >= GATE_UNIQUE_POOL_MIN,
            "n_unique": tot_unique,
            "n_pool": tot_pool,
        },
        "gate_unique_gold": {
            "value": tot_unique_gold,
            "ok": tot_unique_gold > 0,  # 至少捞到 BM25 池外金标
            "gold_in_label": tot_gold_label,
            "gold_in_bm25": tot_gold_bm25,
            "note": "独有金标>0 才算双边扩写买到覆盖",
        },
    }
    meta = {
        "phase": "retrieve",
        "k": k,
        "bm25_k": bm25_k,
        "n_questions": len(score_jobs),
        "gates": gates,
        "rows": gate_rows,
    }
    (out_dir / "retrieve_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "prepare_meta.json").write_text(
        json.dumps({
            "n_questions": len(score_jobs),
            "k": k,
            "cand_mode": "bilateral_label_bm25",
            "use_bm25_fuse": True,
            "protocol": "tag→label-expand↔q-expand→BM25→support-review",
            "score_input": str(path),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("======== C-87 --retrieve ========", flush=True)
    print(json.dumps(gates, ensure_ascii=False, indent=2), flush=True)
    for r in gate_rows:
        print(
            f"  {r['qid']}: label金={r['gold_in_label']}/{r['denom']} "
            f"bm25金={r['gold_in_bm25']} 独有金={r['unique_gold']} "
            f"独有段比={r['unique_ratio']}",
            flush=True,
        )
    return meta


# ---------------------------------------------------------------------------
# Phase 5: 终审（只问支撑）
# ---------------------------------------------------------------------------

def _support_review_prompt(
    question: str, anchors: dict, batch: list[tuple[int, str]],
) -> str:
    n = len(batch)
    max_high = max(1, min(3, n // 4))
    lines = [
        "你是资料审查员。唯一问题：这段材料「能否直接支撑」回答该议题的主张？",
        "不要问「像不像问句／像不像议题措辞」。换说法／别称／同指只要能支撑争点就高分。",
        "同学课（同事件但裁不了争点）必须低分。不要编造段落外事实。拿不准宁低勿高。",
        "",
        f"议题：{question}",
        f"审查锚：{json.dumps(anchors, ensure_ascii=False)}",
        "",
        "分档：",
        "  9–10＝直接支撑争点",
        "  6–8＝部分支撑",
        "  3–5＝弱相关背景",
        "  0–2＝无关／换主体／纯态度／同学课噪声",
        f"本批最多 {max_high} 个 9–10 分。",
        "",
        "段落：",
    ]
    for i, t in batch:
        lines.append(f"[{i}] {_clip(t, 220)}")
    lines.append("")
    lines.append(f'只输出 JSON：{{"scores":[...共{n}个0-10数字]}}')
    return "\n".join(lines)


def _score_batches_support(
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
        prompt = _support_review_prompt(question, anchors, local)
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
                print(f"    支撑审批评失败 start={start}：{exc}", flush=True)
                part = [0.0] * len(local)
        for j, sc in enumerate(part):
            scores[start + j] = float(sc)
    return scores, n_calls


def phase_review(
    out_dir: Path,
    *,
    model: str,
    batch_size: int,
    copy_anchors_from: str = "",
) -> dict:
    _lock_local()
    if copy_anchors_from:
        src = Path(copy_anchors_from)
        if src.is_file():
            # 只拷贝本 out_dir 题相关的锚
            jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
            keys = {f"{j['case']}::{j['qid']}" for j in jobs}
            all_anc = json.loads(src.read_text(encoding="utf-8"))
            subset = {k: v for k, v in all_anc.items() if k in keys}
            if subset:
                (out_dir / "anchors.json").write_text(
                    json.dumps(subset, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"复用锚 {len(subset)} 题 ← {src}", flush=True)

    jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    anchors_all = extract_anchors(out_dir, model=model, limit=None)
    cache = out_dir / "llm_scores_b.json"
    done: dict[str, list[float]] = {}
    if cache.is_file():
        done = json.loads(cache.read_text(encoding="utf-8"))

    t0 = time.time()
    n_calls = 0
    print(f"======== C-87 --review 支撑终审 题数＝{len(jobs)} ========", flush=True)
    for ji, job in enumerate(jobs, 1):
        key = f"{job['case']}::{job['qid']}"
        if key in done and len(done[key]) == len(job["ids"]):
            print(f"  审 [{ji}/{len(jobs)}] {key[:40]} 缓存", flush=True)
            continue
        anc = anchors_all.get(key) or _fallback_anchors(job["query"])
        sc, c = _score_batches_support(
            job["query"], anc, job["texts"], model=model, batch_size=batch_size)
        n_calls += c
        done[key] = sc
        cache.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        print(f"  审 [{ji}/{len(jobs)}] {key[:40]} n={len(sc)} calls+={c}", flush=True)

    meta = {
        "phase": "review",
        "model": model,
        "batch_size": batch_size,
        "n_calls": n_calls,
        "elapsed_s": round(time.time() - t0, 1),
        "prompt": "support_only",
    }
    (out_dir / "score_meta_b.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"终审墙钟＝{meta['elapsed_s']}s 调用＝{n_calls}", flush=True)
    return meta


# ---------------------------------------------------------------------------
# Phase 6: 装箱量尺 + 总门
# ---------------------------------------------------------------------------

def phase_score(out_dir: Path, gold_dir: Path) -> dict:
    jobs = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    scores_all = json.loads((out_dir / "llm_scores_b.json").read_text(encoding="utf-8"))
    rows = []
    lost_n = gained_n = 0
    tot = Counter()
    for job in jobs:
        key = f"{job['case']}::{job['qid']}"
        sc = scores_all.get(key)
        if not sc or len(sc) != len(job["ids"]):
            raise SystemExit(f"缺分或不齐：{key}")
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

        # fuse：审查分主序，原文 BM25 破并列；候选外段分＝0
        bm25_scores = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        for sid in id_scores:
            bm25_scores.setdefault(sid, 0.0)
        # 未进候选的段审查分视为 0
        fused = _fuse(bm25_scores, id_scores, use_bm25=True)
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
            "B_hits": hits_l, "B_n": len(sel_l),
            "lost": len(lost), "gained": len(gained),
        })
        tot["denom"] += denom
        tot["a0_hits"] += hits_a
        tot["a0_n"] += len(sel_a)
        tot["arm_hits"] += hits_l
        tot["arm_n"] += len(sel_l)

    summary = {
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "a0": {
            "l2_hits": int(tot["a0_hits"]),
            "n_selected": int(tot["a0_n"]),
            "precision": round(tot["a0_hits"] / tot["a0_n"], 4) if tot["a0_n"] else 0,
            "recall": round(tot["a0_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        "B": {
            "l2_hits": int(tot["arm_hits"]),
            "n_selected": int(tot["arm_n"]),
            "precision": round(tot["arm_hits"] / tot["arm_n"], 4) if tot["arm_n"] else 0,
            "recall": round(tot["arm_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        "lost_n": lost_n,
        "gained_n": gained_n,
        "rows": rows,
    }

    # 汇总各阶段门
    all_gates: dict[str, Any] = {}
    for name in (
        "label_expand_meta.json",
        "question_expand_meta.json",
        "retrieve_meta.json",
    ):
        p = out_dir / name
        if p.is_file():
            m = json.loads(p.read_text(encoding="utf-8"))
            all_gates.update(m.get("gates") or {})

    improved = summary["B"]["l2_hits"] > summary["a0"]["l2_hits"]
    lost_ok = summary["lost_n"] == 0
    gates_ok = all(bool(g.get("ok")) for g in all_gates.values()) if all_gates else False
    verdict = {
        "improved_vs_a0": improved,
        "lost_ok": lost_ok,
        "gates_ok": gates_ok,
        "worth_expand_to_six": bool(improved and lost_ok and gates_ok),
        "note": (
            "吉隆打通票：L2>A0 且 lost=0 且可观测门全绿 → 才扩六案；"
            "否则方案未过，不进生产。"
        ),
    }
    payload = {
        "summary": summary,
        "gates": all_gates,
        "verdict": verdict,
        "protocol": "C-87",
    }
    (out_dir / "summary_b.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("======== C-87 量尺 ========", flush=True)
    print(
        f"A0＝{summary['a0']['l2_hits']}/{summary['denom']}  "
        f"B＝{summary['B']['l2_hits']}/{summary['denom']}  "
        f"lost＝{lost_n} gained＝{gained_n}",
        flush=True,
    )
    for qid_row in rows:
        print(
            f"  {qid_row['qid']}: A0={qid_row['a0_hits']}/{qid_row['denom']} "
            f"B={qid_row['B_hits']}/{qid_row['denom']} "
            f"lost={qid_row['lost']} gained={qid_row['gained']}",
            flush=True,
        )
    print("可观测门：", flush=True)
    print(json.dumps(all_gates, ensure_ascii=False, indent=2), flush=True)
    print("裁决：", json.dumps(verdict, ensure_ascii=False, indent=2), flush=True)
    print(f"落盘 {out_dir / 'summary_b.json'}", flush=True)
    return payload


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", default="/tmp/c87_jilong")
    ap.add_argument("--gold-dir", default="")
    ap.add_argument("--case-filter", default="吉隆")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--tag-batch", type=int, default=DEFAULT_TAG_BATCH)
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--bm25-k", type=int, default=DEFAULT_BM25_K)
    ap.add_argument("--limit-segs", type=int, default=None,
                    help="打标段数上限（烟雾用）")
    ap.add_argument("--copy-anchors-from", default="")
    ap.add_argument("--tag", action="store_true")
    ap.add_argument("--expand-labels", action="store_true")
    ap.add_argument("--expand-questions", action="store_true")
    ap.add_argument("--retrieve", action="store_true")
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--auto", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    gold_dir = Path(args.gold_dir) if args.gold_dir else DEFAULT_GOLD
    run_dir = Path(args.run_dir)

    do_all = args.auto
    if args.tag or do_all:
        phase_tag(
            run_dir, out_dir,
            case_filter=args.case_filter,
            model=args.model,
            batch_size=args.tag_batch,
            limit_segs=args.limit_segs,
        )

    # 收集议题文本（扩标签时避开热词）
    questions: list[str] = []
    qjobs_path = out_dir / "question_jobs.json"
    if qjobs_path.is_file():
        questions = [j["query"] for j in json.loads(qjobs_path.read_text(encoding="utf-8"))]
    else:
        for rp in discover_reports(run_dir):
            case, _qid = _case_qid(rp)
            if args.case_filter not in case:
                continue
            rep = json.loads(rp.read_text(encoding="utf-8"))
            questions.append(_query_of(Dossier.from_dict(rep)))

    if args.expand_questions or do_all:
        phase_expand_questions(
            run_dir, out_dir,
            case_filter=args.case_filter, model=args.model,
        )
        # 刷新 questions
        questions = [
            j["query"]
            for j in json.loads((out_dir / "question_jobs.json").read_text(encoding="utf-8"))
        ]

    if args.expand_labels or do_all:
        if not (out_dir / "tags.json").is_file():
            raise SystemExit("缺 tags.json，先 --tag")
        phase_expand_labels(out_dir, model=args.model, questions=questions)

    if args.retrieve or do_all:
        for need in ("synth_docs.json", "question_expansions.json", "question_jobs.json"):
            if not (out_dir / need).is_file():
                raise SystemExit(f"缺 {need}")
        phase_retrieve(out_dir, k=args.k, bm25_k=args.bm25_k, gold_dir=gold_dir)

    if args.review or do_all:
        if not (out_dir / "score_input.json").is_file():
            raise SystemExit("缺 score_input.json，先 --retrieve")
        phase_review(
            out_dir, model=args.model, batch_size=args.batch_size,
            copy_anchors_from=args.copy_anchors_from,
        )

    if args.score or do_all:
        phase_score(out_dir, gold_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
