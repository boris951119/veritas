"""本机 Ollama：每段 Summary（事实句／实体／关键词／可选因果提示）→ 链回 Slice。"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from app.core.evidence import Dossier
from app.kg_lab.config import SUMMARIES_DIR, SUMMARY_MODEL, SUMMARY_WORKERS
from app.kg_lab.ollama_client import generate_json
from app.kg_lab.slices import safe_name, segment_map

_PROMPT = """只根据段落输出紧凑 JSON（禁止段外事实；控制长度）：
{{"facts":["短句1","短句2"],"entities":["专名≤6个"],"keywords":["词≤6个"],"causal":[{{"type":"causes|enables|contradicts","subj":"A","obj":"B"}}],"source_role":"官方|当事人|转述|评论|制度|","opposition_terms":[],"amount_status":"none|disclosed|established|officially_unconfirmed","amount_note":"","procedure_dates":[]}}
causal 可空数组。facts 1-3 条，每条≤40字。不要写通稿背景、赛绩。
若段内出现对话／对立口径（如不愿走、不想走、没让我走、未放行、买断、安置争议），必须把原文关键短句写入 facts，并把对立词写入 keywords 和 opposition_terms（不得改写主语）。
槽位只在段内有据时填写：说话人角色、对立口径词、数额是披露／既定／官方未确认、手续日期。没有就留空。

段落：
{text}
"""


def _salvage_json(text: str) -> dict[str, Any]:
    """截断 JSON 尽力抢救（qwen 常顶满 num_predict）。"""
    s = (text or "").strip()
    if not s:
        return {}
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        pass
    # 截到最后一个完整字段附近，补闭合
    if not s.startswith("{"):
        return {}
    # 去掉未闭合字符串的残尾
    for cut in range(len(s), max(len(s) - 400, 20), -1):
        frag = s[:cut].rstrip().rstrip(",")
        for closer in ("}", "]}" , "]} }", "\"]}", "\"]}"):
            cand = frag + closer
            # 粗算括号
            if cand.count("{") < cand.count("}"):
                continue
            # 补足花括号
            while cand.count("{") > cand.count("}"):
                cand += "}"
            while cand.count("[") > cand.count("]"):
                # 插在末尾 } 前
                if cand.endswith("}"):
                    cand = cand[:-1] + "]}"
                else:
                    cand += "]"
            try:
                obj = json.loads(cand)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    return {}


def _empty_summary(doc_id: str, para_id: str) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "para_id": para_id,
        "facts": [],
        "entities": [],
        "keywords": [],
        "causal": [],
        "summary_text": "",
        "model": SUMMARY_MODEL,
        "ok": False,
    }


def summary_blob(obj: dict[str, Any]) -> str:
    """检索用摘要字段（facts+entities+keywords）。"""
    parts: list[str] = []
    for f in obj.get("facts") or []:
        if f:
            parts.append(str(f))
    for e in obj.get("entities") or []:
        if e:
            parts.append(str(e))
    for k in obj.get("keywords") or []:
        if k:
            parts.append(str(k))
    return "\n".join(parts)


def heuristic_summary(doc_id: str, para_id: str, text: str) -> dict[str, Any]:
    """LLM 失败时的本地回退：首句作 facts + 粗实体／关键词（仍链回 para_id）。"""
    body = (text or "").strip()
    # 按句号切 1～3 短句
    parts = []
    buf = ""
    for ch in body:
        buf += ch
        if ch in "。！？；\n" and len(buf.strip()) >= 8:
            parts.append(buf.strip())
            buf = ""
            if len(parts) >= 3:
                break
    if not parts and body:
        parts = [body[:60]]
    facts = [p[:40] for p in parts[:3]]
    # 连续汉字≥2 的专名粗抽（频次优先）
    import re
    toks = re.findall(r"[\u4e00-\u9fff]{2,8}", body)
    freq: dict[str, int] = {}
    for t in toks:
        freq[t] = freq.get(t, 0) + 1
    entities = [t for t, _ in sorted(freq.items(), key=lambda x: (-x[1], -len(x[0])))[:6]]
    keywords = entities[:6]
    return {
        "doc_id": doc_id,
        "para_id": para_id,
        "facts": facts,
        "entities": entities,
        "keywords": keywords,
        "causal": [],
        "summary_text": summary_blob({
            "facts": facts, "entities": entities, "keywords": keywords,
        }),
        "model": "heuristic_fallback",
        "ok": bool(facts or entities),
        "fallback": True,
    }


def summarize_one(
    *,
    doc_id: str,
    para_id: str,
    text: str,
    max_chars: int = 1800,
) -> dict[str, Any]:
    body = (text or "").strip()
    if len(body) > max_chars:
        body = body[:max_chars] + "…"
    if not body:
        return _empty_summary(doc_id, para_id)
    t0 = time.perf_counter()
    resp: dict[str, Any] = {}
    try:
        resp = generate_json(_PROMPT.format(text=body))
        parsed = resp.get("parsed") or {}
        if not parsed:
            parsed = _salvage_json(str(resp.get("raw") or ""))
    except Exception as e:  # noqa: BLE001 — 单段失败不阻断
        out = heuristic_summary(doc_id, para_id, text)
        out["error"] = str(e)
        out["wall_s"] = round(time.perf_counter() - t0, 3)
        return out
    facts = [str(x).strip() for x in (parsed.get("facts") or []) if str(x).strip()][:3]
    entities = [str(x).strip() for x in (parsed.get("entities") or []) if str(x).strip()][:8]
    keywords = [str(x).strip() for x in (parsed.get("keywords") or []) if str(x).strip()][:8]
    causal_raw = parsed.get("causal") or []
    causal: list[dict[str, str]] = []
    if isinstance(causal_raw, list):
        for c in causal_raw:
            if not isinstance(c, dict):
                continue
            typ = str(c.get("type") or "").strip().lower()
            if typ not in {"causes", "enables", "contradicts"}:
                continue
            subj = str(c.get("subj") or "").strip()
            obj = str(c.get("obj") or "").strip()
            if not subj or not obj:
                continue
            causal.append({
                "type": typ,
                "subj": subj,
                "obj": obj,
                "hint": str(c.get("hint") or "").strip(),
            })
    from app.kg_lab.summary_slots import slots_from_llm, with_slot_text

    slots = slots_from_llm(parsed, text)
    out = {
        "doc_id": doc_id,
        "para_id": para_id,
        "facts": facts,
        "entities": entities,
        "keywords": keywords,
        "causal": causal,
        "summary_text": "",
        "model": SUMMARY_MODEL,
        "ok": bool(facts or entities or keywords),
        "wall_s": round(time.perf_counter() - t0, 3),
        "eval_count": resp.get("eval_count"),
    }
    out.update(slots)
    out["summary_text"] = with_slot_text(out)
    if not out["ok"]:
        fb = heuristic_summary(doc_id, para_id, text)
        fb["wall_s"] = out["wall_s"]
        fb["eval_count"] = out.get("eval_count")
        fb["llm_empty"] = True
        return fb
    return out


def summary_path(case_slug: str, doc_id: str, para_id: str) -> Path:
    return SUMMARIES_DIR / case_slug / f"{safe_name(doc_id, para_id)}.json"


def write_summary_note(case_slug: str, summary: dict[str, Any]) -> Path:
    """JSON 缓存 + 可选 md 链回 slice。"""
    doc_id = str(summary["doc_id"])
    para_id = str(summary["para_id"])
    path = summary_path(case_slug, doc_id, para_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md = path.with_suffix(".md")
    slice_link = f"[[slices/{case_slug}/{safe_name(doc_id, para_id)}]]"
    lines = [
        "---",
        "type: summary",
        f"doc_id: {json.dumps(doc_id, ensure_ascii=False)}",
        f"para_id: {json.dumps(para_id, ensure_ascii=False)}",
        f"slice: {json.dumps(slice_link, ensure_ascii=False)}",
        "---",
        "",
        f"← {slice_link}",
        "",
        "## Facts",
    ]
    for f in summary.get("facts") or []:
        lines.append(f"- {f}")
    lines += ["", "## Entities"]
    for e in summary.get("entities") or []:
        lines.append(f"- [[{e}]]")
    lines += ["", "## Keywords"]
    for k in summary.get("keywords") or []:
        lines.append(f"- {k}")
    if summary.get("causal"):
        lines += ["", "## Causal hints"]
        for c in summary["causal"]:
            lines.append(
                f"- {c['type']}: {c['subj']} → {c['obj']}"
                + (f"（{c['hint']}）" if c.get("hint") else "")
            )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_summary(case_slug: str, doc_id: str, para_id: str) -> dict[str, Any] | None:
    path = summary_path(case_slug, doc_id, para_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_paras(
    dossier: Dossier,
    *,
    case_slug: str,
    para_ids: set[str],
    workers: int = SUMMARY_WORKERS,
    force: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """对箱内段做摘要；已有缓存则跳过。"""
    smap = segment_map(dossier)
    # doc_id lookup
    doc_of: dict[str, str] = {}
    for src in dossier.sources:
        for seg in src.segments:
            doc_of[str(seg.id)] = str(src.id)

    targets = sorted(p for p in para_ids if p in smap)
    if limit is not None:
        targets = targets[: max(0, int(limit))]

    todo: list[tuple[str, str, str]] = []
    cached = 0
    for pid in targets:
        doc_id = doc_of[pid]
        cached_path = summary_path(case_slug, doc_id, pid)
        if not force and cached_path.is_file():
            try:
                prev = json.loads(cached_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                prev = {}
            # 空摘要（常见＝think 吃预算）视为未完成，重跑
            if prev.get("ok"):
                cached += 1
                continue
        todo.append((doc_id, pid, smap[pid].text or ""))

    done = 0
    errors = 0
    t0 = time.perf_counter()

    def _job(item: tuple[str, str, str]) -> dict[str, Any]:
        doc_id, pid, text = item
        s = summarize_one(doc_id=doc_id, para_id=pid, text=text)
        write_summary_note(case_slug, s)
        return s

    results: list[dict[str, Any]] = []
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futs = {pool.submit(_job, it): it for it in todo}
            for fut in as_completed(futs):
                try:
                    s = fut.result()
                    results.append(s)
                    if not s.get("ok"):
                        errors += 1
                except Exception:  # noqa: BLE001
                    errors += 1
                done += 1
                if done % 25 == 0 or done == len(todo):
                    print(
                        f"  summarize {done}/{len(todo)} "
                        f"(cached_skip={cached}, err={errors})",
                        flush=True,
                    )

    return {
        "case": case_slug,
        "n_targets": len(targets),
        "n_cached_skip": cached,
        "n_new": len(todo),
        "n_errors": errors,
        "wall_s": round(time.perf_counter() - t0, 3),
        "workers": workers,
        "model": SUMMARY_MODEL,
    }
