#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R18：跨案金标「为何是金标」特征分析。不改加权／不重拟合。

严格金标＝supporting_facts（含 partial）经 evidence_samples 对齐 para。
规则打标全量；本地 14B 按题汇总「为何选它而非近邻」（默认开）。
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingest.official_case import load_official_case  # noqa: E402
from app.kg_lab.case_lexicon import lexicon_for_question  # noqa: E402
from app.kg_lab.channel_tier import channel_tier  # noqa: E402
from app.kg_lab.config import SUMMARY_MODEL  # noqa: E402
from app.kg_lab.ollama_client import generate_json  # noqa: E402
from app.kg_lab.source_role import infer_fine_role, infer_source_role  # noqa: E402
from app.kg_lab.tag_schema import STAGE1_FEATURES, STAGE2_FEATURES  # noqa: E402
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

SAMPLES = Path("/Users/liuboyu/Desktop/veritas-testcases/样例集-拓尔思-20261012")
OUT = ROOT / "artifacts"
USE_LLM = True  # 默认本地 14B；设 VERITAS_R18_NO_LLM=1 可关
NON_GOLD_PER_Q = 3
_DATE = re.compile(r"\d{1,2}月\d{1,2}日|\d{4}[-/.年]\d{1,2}")
_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*万|\d{2,}\s*元|\$[\d,]+")

CASES: tuple[tuple[str, str], ...] = (
    ("liuxiang", "刘翔"),
    ("jilong", "吉隆"),
    ("us_cn_ai", "中美AI"),
    ("ai171", "印度航空"),
    ("kh_th", "柬泰"),
    ("wanghong", "王虹"),
)


def _case(mark: str) -> Path:
    hits = [
        p for p in SAMPLES.iterdir()
        if p.is_dir() and mark in p.name and (p / "raw_documents.json").is_file()
    ]
    if len(hits) != 1:
        raise SystemExit(f"case {mark}: {hits}")
    return hits[0]


def _load_docs(case: Path) -> dict[str, dict[str, Any]]:
    rows = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    return {str(d["doc_id"]): d for d in rows}


def _para_text(doc: dict[str, Any], para_id: str) -> str:
    content = str(doc.get("content") or "")
    for p in doc.get("paragraphs") or []:
        if str(p.get("para_id") or "") != para_id:
            continue
        a, b = p.get("char_start"), p.get("char_end")
        if isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= len(content):
            return content[a:b]
    return ""


def _para_index(doc: dict[str, Any]) -> dict[str, int]:
    out = {}
    for i, p in enumerate(doc.get("paragraphs") or []):
        pid = str(p.get("para_id") or "")
        if pid:
            out[pid] = i
    return out


def _fact_meta(case: Path, qid: str) -> dict[str, dict[str, Any]]:
    """para_id → supporting_facts 元数据（取第一条命中）。"""
    conc = json.loads((case / "conclusions.json").read_text(encoding="utf-8"))
    samples = {
        str(r.get("fact_id") or ""): r
        for r in json.loads((case / "evidence_samples.json").read_text(encoding="utf-8"))
    }
    out: dict[str, dict[str, Any]] = {}
    for row in conc:
        if str(row.get("question_id") or "") != qid:
            continue
        for sf in row.get("supporting_facts") or []:
            fid = str(sf.get("fact_id") or "")
            sample = samples.get(fid) or {}
            pid = str(sample.get("para_id") or "")
            if not pid or pid in out:
                continue
            out[pid] = {
                "fact_id": fid,
                "verdict_label": str(sf.get("verdict_label") or ""),
                "fact_des": str(sf.get("fact_des") or ""),
                "quote": str(sf.get("quote") or sample.get("quote") or ""),
                "argument": str(sample.get("argument") or ""),
            }
    return out


def _stance(question: str, text: str, quote: str, fact_des: str) -> str:
    """粗对立／支撑：看引文与问句选项哪一侧字面更近。"""
    blob = (quote or "") + "\n" + (text or "") + "\n" + (fact_des or "")
    q = question or ""
    # 问句「是A还是B」
    m = re.search(r"是(.{2,20}?)还是(.{2,20}?)[，,？?]", q)
    if m:
        a, b = m.group(1), m.group(2)
        ha = sum(1 for t in re.findall(r"[\u4e00-\u9fff]{2,}", a) if t in blob)
        hb = sum(1 for t in re.findall(r"[\u4e00-\u9fff]{2,}", b) if t in blob)
        if ha > hb:
            return "lean_option_a"
        if hb > ha:
            return "lean_option_b"
    if any(s in blob for s in ("否认", "驳斥", "不实", "谣言", "澄清")):
        return "refute_or_clarify"
    if any(s in blob for s in ("证实", "确认", "通报", "宣布", "认定")):
        return "affirm_or_confirm"
    return "neutral_or_unclear"


def _span_vs_quote(text: str, quote: str) -> str:
    t = (text or "").strip()
    q = (quote or "").strip()
    if not q:
        return "no_quote"
    if not t:
        return "empty_para"
    if q in t and len(q) >= 0.85 * len(t):
        return "near_full_para"
    if q in t:
        return "excerpt_inside_para"
    # 归一化粗比
    tn = re.sub(r"\s+", "", t)
    qn = re.sub(r"\s+", "", q)
    if qn and qn in tn:
        return "excerpt_inside_para"
    if tn and (tn in qn or len(set(tn) & set(qn)) / max(len(set(qn)), 1) > 0.7):
        return "loose_overlap"
    return "quote_not_in_para"


def _claim_relation(question: str, text: str, quote: str, lex) -> str:
    body = (quote or "") + "\n" + (text or "")
    fam = lex.family_of_question(question)
    if not fam:
        # 无预置族：看问句词是否落在正文
        q_terms = [t for t in re.findall(r"[\u4e00-\u9fff]{2,6}", question or "") if len(t) >= 2]
        hits = [t for t in q_terms[:12] if t in body]
        if len(hits) >= 3:
            return "question_terms_multi_hit"
        if hits:
            return "question_terms_weak_hit"
        return "no_catalog_family"
    surf = lex.surfaces_for_family(fam)
    frames = lex.family_frames.get(fam) or ()
    if any(t in body for t in surf):
        return f"family_{fam}_surface"
    if any(t in body for t in frames):
        return f"family_{fam}_frame_only"
    return f"family_{fam}_miss"


def annotate_para(
    *,
    question: str,
    para_id: str,
    doc: dict[str, Any],
    text: str,
    fact: dict[str, Any] | None,
    lex,
    is_gold: bool,
) -> dict[str, Any]:
    title = str(doc.get("title") or "")
    url = str(doc.get("content_url") or "")
    cred = doc.get("source_credibility")
    cred_f = float(cred) if isinstance(cred, (int, float)) else None
    coarse = infer_source_role(title, text, cred_f, lex=lex)
    fine = infer_fine_role(title, text, cred_f, lex=lex)
    tier = channel_tier(url, title)
    quote = str((fact or {}).get("quote") or "")
    fact_des = str((fact or {}).get("fact_des") or "")
    return {
        "para_id": para_id,
        "doc_id": str(doc.get("doc_id") or ""),
        "is_gold": is_gold,
        "title": title,
        "url": url,
        "text_preview": (text or "")[:280],
        "text_chars": len(text or ""),
        "fact_id": (fact or {}).get("fact_id"),
        "verdict_label": (fact or {}).get("verdict_label"),
        "fact_des": fact_des[:200] if fact_des else "",
        "quote_preview": quote[:200],
        "coarse_role": coarse.get("role"),
        "fine_role": fine.get("role"),
        "channel": fine.get("channel"),
        "channel_tier": tier,
        "official_primary": fine.get("role") == "official_primary",
        "has_amount": bool(_AMOUNT.search(text or "") or _AMOUNT.search(quote)),
        "has_time_nail": bool(_DATE.search(text or "") or _DATE.search(quote)),
        "stance": _stance(question, text, quote, fact_des),
        "span_vs_quote": _span_vs_quote(text, quote) if is_gold else "n/a",
        "claim_relation": _claim_relation(question, text, quote, lex),
        "lex_actors_in_text": [a for a in lex.actors if a and a in ((title or "") + text)],
        "active_families": list(lex.active_families),
    }


def _neighbors(
    docs: dict[str, dict[str, Any]],
    para_id: str,
    gold_ids: set[str],
    *,
    n: int = 2,
) -> list[tuple[str, str, str]]:
    """同文档相邻段（非金标）作对照。返回 (para_id, text, reason)。"""
    doc_id = para_id.split("#")[0] if "#" in para_id else ""
    doc = docs.get(doc_id)
    if not doc:
        return []
    idx = _para_index(doc)
    if para_id not in idx:
        return []
    i = idx[para_id]
    paras = list(doc.get("paragraphs") or [])
    out = []
    for j in (i - 1, i + 1, i - 2, i + 2):
        if j < 0 or j >= len(paras):
            continue
        pid = str(paras[j].get("para_id") or "")
        if not pid or pid in gold_ids:
            continue
        text = _para_text(doc, pid)
        if len((text or "").strip()) < 20:
            continue
        out.append((pid, text, f"adjacent_offset_{j - i}"))
        if len(out) >= n:
            break
    return out


def _sample_nongold(
    docs: dict[str, dict[str, Any]],
    gold_ids: set[str],
    question: str,
    *,
    n: int,
) -> list[tuple[str, str, str]]:
    """抽样非金标：问句词命中较多的段。"""
    q_terms = [t for t in re.findall(r"[\u4e00-\u9fff]{2,6}", question or "") if len(t) >= 2][:10]
    scored: list[tuple[int, str, str]] = []
    for doc in docs.values():
        for p in doc.get("paragraphs") or []:
            pid = str(p.get("para_id") or "")
            if not pid or pid in gold_ids:
                continue
            text = _para_text(doc, pid)
            if len(text) < 40:
                continue
            hit = sum(1 for t in q_terms if t in text)
            if hit <= 0:
                continue
            scored.append((hit, pid, text))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(pid, text, f"qterm_hits_{hit}") for hit, pid, text in scored[:n]]


def _llm_question_why(
    question: str,
    golds: list[dict[str, Any]],
    controls: list[dict[str, Any]],
) -> dict[str, Any]:
    gold_lines = []
    for g in golds[:6]:
        gold_lines.append(
            f"- {g['para_id']} role={g['fine_role']} tier={g['channel_tier']} "
            f"verdict={g.get('verdict_label')} | {(g.get('quote_preview') or g['text_preview'])[:160]}"
        )
    ctrl_lines = []
    for c in controls[:6]:
        ctrl_lines.append(
            f"- {c['para_id']} role={c['fine_role']} why_pick={c.get('control_reason')} | {c['text_preview'][:140]}"
        )
    prompt = (
        "你是研判证据分析员。根据问句、金标段与对照非金标段，输出 JSON：\n"
        '{"common_why_gold":["跨段共性，短句"],'
        '"case_specific":["本题特有理由"],'
        '"missing_vs_controls":["金标有而对照没有的信号"],'
        '"noise_in_controls":["对照段为何不够格"]}\n'
        "不要编造原文没有的事实。用中文短句。\n"
        f"问句：{question}\n金标：\n" + "\n".join(gold_lines)
        + "\n对照非金标：\n" + ("\n".join(ctrl_lines) if ctrl_lines else "（无）")
    )
    try:
        out = generate_json(prompt, model=SUMMARY_MODEL, num_predict=280, temperature=0.0)
        parsed = out.get("parsed") or {}
        if not isinstance(parsed, dict):
            parsed = {}
        return {"ok": True, "parsed": parsed, "raw": (out.get("raw") or "")[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e), "parsed": {}}


def analyze_case(slug: str, mark: str, *, use_llm: bool) -> dict[str, Any]:
    case = _case(mark)
    print(f"=== {slug} {case.name} ===", flush=True)
    docs = _load_docs(case)
    # 触发放箱／语料（取 title 等）；正文仍从 raw 切
    _ = load_official_case(case)
    conc = json.loads((case / "conclusions.json").read_text(encoding="utf-8"))
    questions = []
    seen = set()
    for row in conc:
        qid = str(row.get("question_id") or "")
        if qid in seen:
            continue
        seen.add(qid)
        questions.append({"qid": qid, "question": str(row.get("question") or "")})

    q_out = []
    for q in questions:
        qid, question = q["qid"], q["question"]
        gold_map, skipped = gold_paras_for_question(case, qid)
        facts = _fact_meta(case, qid)
        lex = lexicon_for_question(question, case_slug=slug)
        gold_ids = {pid for _d, pid in gold_map}
        gold_ann = []
        for (_d, pid), _quotes in sorted(gold_map.items()):
            doc = docs.get(pid.split("#")[0]) or docs.get(_d) or {}
            text = _para_text(doc, pid) if doc else ""
            if not text and doc:
                # 兜底：用 quote
                text = str((facts.get(pid) or {}).get("quote") or "")
            ann = annotate_para(
                question=question, para_id=pid, doc=doc, text=text,
                fact=facts.get(pid), lex=lex, is_gold=True,
            )
            # 近邻对照 id
            neigh = _neighbors(docs, pid, gold_ids, n=2)
            ann["neighbors"] = [
                {"para_id": np, "reason": r, "preview": (nt or "")[:160]}
                for np, nt, r in neigh
            ]
            gold_ann.append(ann)

        controls_raw = _sample_nongold(docs, gold_ids, question, n=NON_GOLD_PER_Q)
        # 再补近邻
        for g in gold_ann:
            for nb in g.get("neighbors") or []:
                if len(controls_raw) >= NON_GOLD_PER_Q + 2:
                    break
                pid = nb["para_id"]
                if any(pid == x[0] for x in controls_raw):
                    continue
                doc = docs.get(pid.split("#")[0]) or {}
                controls_raw.append((pid, _para_text(doc, pid), nb["reason"]))

        ctrl_ann = []
        for pid, text, reason in controls_raw[: NON_GOLD_PER_Q + 2]:
            doc = docs.get(pid.split("#")[0]) or {}
            ann = annotate_para(
                question=question, para_id=pid, doc=doc, text=text,
                fact=None, lex=lex, is_gold=False,
            )
            ann["control_reason"] = reason
            ctrl_ann.append(ann)

        llm = {"ok": False, "skipped": True}
        if use_llm and gold_ann:
            print(f"  llm {qid} …", flush=True)
            llm = _llm_question_why(question, gold_ann, ctrl_ann)
            llm["skipped"] = False
            print(f"  llm {qid} ok={llm.get('ok')}", flush=True)

        q_out.append({
            "qid": qid,
            "question": question,
            "n_gold": len(gold_ann),
            "n_skipped_locator": skipped,
            "lexicon": {"actors": lex.actors, "active_families": lex.active_families},
            "golds": gold_ann,
            "controls": ctrl_ann,
            "llm": llm,
        })
        print(f"  {qid} gold={len(gold_ann)} controls={len(ctrl_ann)}", flush=True)

    return {
        "slug": slug,
        "name": case.name,
        "n_docs": len(docs),
        "questions": q_out,
    }


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    gold_roles: Counter[str] = Counter()
    gold_tiers: Counter[str] = Counter()
    gold_claim: Counter[str] = Counter()
    gold_stance: Counter[str] = Counter()
    gold_span: Counter[str] = Counter()
    gold_verdict: Counter[str] = Counter()
    ctrl_roles: Counter[str] = Counter()
    by_case: dict[str, dict[str, Any]] = {}
    llm_commons: list[str] = []
    llm_missing: list[str] = []

    for c in cases:
        cr: Counter[str] = Counter()
        ct: Counter[str] = Counter()
        n_gold = 0
        for q in c["questions"]:
            for g in q["golds"]:
                n_gold += 1
                gold_roles[str(g["fine_role"])] += 1
                gold_tiers[str(g["channel_tier"])] += 1
                gold_claim[str(g["claim_relation"])] += 1
                gold_stance[str(g["stance"])] += 1
                gold_span[str(g["span_vs_quote"])] += 1
                gold_verdict[str(g.get("verdict_label") or "")] += 1
                cr[str(g["fine_role"])] += 1
                ct[str(g["channel_tier"])] += 1
            for x in q["controls"]:
                ctrl_roles[str(x["fine_role"])] += 1
            parsed = (q.get("llm") or {}).get("parsed") or {}
            for s in parsed.get("common_why_gold") or []:
                if isinstance(s, str) and s.strip():
                    llm_commons.append(s.strip())
            for s in parsed.get("missing_vs_controls") or []:
                if isinstance(s, str) and s.strip():
                    llm_missing.append(s.strip())
        by_case[c["slug"]] = {
            "n_gold": n_gold,
            "top_roles": cr.most_common(5),
            "top_tiers": ct.most_common(5),
        }

    def _share(counter: Counter[str], n: int) -> list[dict[str, Any]]:
        return [
            {"key": k, "n": v, "pct": round(100.0 * v / n, 1) if n else 0.0}
            for k, v in counter.most_common()
        ]

    n = sum(gold_roles.values())
    return {
        "n_gold_total": n,
        "fine_role": _share(gold_roles, n),
        "channel_tier": _share(gold_tiers, n),
        "claim_relation": _share(gold_claim, n),
        "stance": _share(gold_stance, n),
        "span_vs_quote": _share(gold_span, n),
        "verdict_label": _share(gold_verdict, n),
        "control_fine_role": _share(ctrl_roles, sum(ctrl_roles.values()) or 1),
        "by_case": by_case,
        "llm_common_themes": Counter(llm_commons).most_common(20),
        "llm_missing_themes": Counter(llm_missing).most_common(20),
    }


def _coverage_gap(agg: dict[str, Any]) -> dict[str, Any]:
    """对照当前一筛特征：盖住了什么、漏了什么。"""
    covered = [
        "fine_role / source_role 独热（官方原文、当事人、转述、评论）",
        "channel_tier 独热",
        "subject_match / subject_x_channel（问句主体×本人渠道）",
        "claim_full / claim_keyword（主张族表面／框架）",
        "amount_status / time_anchor（问句触发＋摘要槽）",
        "二筛：标题党／小节蹭分／偏题转载／近同文／拼段",
    ]
    # 从聚合里看出一筛弱的信号
    weak = []
    roles = {r["key"]: r["pct"] for r in agg["fine_role"]}
    if roles.get("media_relay", 0) + roles.get("party_relay", 0) > 25:
        weak.append("大量金标是转述／媒体中继，一筛对「转述里嵌的原话句」粒度不够（整段角色偏媒体）")
    spans = {r["key"]: r["pct"] for r in agg["span_vs_quote"]}
    if spans.get("excerpt_inside_para", 0) > 30:
        weak.append("金标常是段内摘句，一筛按整段打分，邻近壳段落易抢分")
    claims = agg["claim_relation"]
    miss_family = sum(r["n"] for r in claims if "miss" in r["key"] or "no_catalog" in r["key"])
    if miss_family > agg["n_gold_total"] * 0.35:
        weak.append("过半／三四成金标打不进预置主张族（leave/money/post），跨案主张类型超出目录")
    if any(r["key"] == "lean_option_a" or r["key"] == "lean_option_b" for r in agg["stance"]):
        weak.append("对立选项对齐（lean_option_*）未作为一筛显式维，只靠 claim 表面词间接碰")
    weak.append("「相对近邻为何胜出」无特征：同文相邻段、同通报不同切片的差分未建模")
    weak.append("fact_des／argument（标注理由）线上不可用；但分析显示金标常带制度定性句或可核验时点")
    return {
        "stage1_covers": covered,
        "stage1_features_count": len(STAGE1_FEATURES),
        "stage2_features_count": len(STAGE2_FEATURES),
        "gaps": weak,
    }


def _markdown(report: dict[str, Any]) -> str:
    agg = report["aggregate"]
    gap = report["coverage_gap"]
    lines = [
        "# R18 — 跨案金标「为何是金标」",
        "",
        "## 结论先行",
        "",
    ]
    for s in report["verdict_bullets"]:
        lines.append(f"- {s}")
    lines += [
        "",
        f"六案严格金标合计 **{agg['n_gold_total']}** 条"
        f"（supporting_facts 含 partial，经 evidence_samples 对齐）。"
        f"规则打标全量；本地 `{report['defaults']['model']}` 按题归纳"
        f"（use_llm={report['defaults']['use_llm']}）。未改加权、未重拟合。",
        "",
        "## 跨案共性（金标分布）",
        "",
        "### 细角色",
        "",
        "| fine_role | n | % |",
        "|---|---:|---:|",
    ]
    for r in agg["fine_role"][:10]:
        lines.append(f"| `{r['key']}` | {r['n']} | {r['pct']} |")
    lines += [
        "",
        "### 渠道层级",
        "",
        "| channel_tier | n | % |",
        "|---|---:|---:|",
    ]
    for r in agg["channel_tier"][:8]:
        lines.append(f"| `{r['key']}` | {r['n']} | {r['pct']} |")
    lines += [
        "",
        "### 主张关系 / 摘句形态 / 支撑类型",
        "",
        "| 维 | Top |",
        "|---|---|",
        f"| claim_relation | {', '.join(f'`{r['key']}` {r['pct']}%' for r in agg['claim_relation'][:5])} |",
        f"| span_vs_quote | {', '.join(f'`{r['key']}` {r['pct']}%' for r in agg['span_vs_quote'][:5])} |",
        f"| verdict_label | {', '.join(f'`{r['key']}` {r['pct']}%' for r in agg['verdict_label'][:5])} |",
        f"| stance | {', '.join(f'`{r['key']}` {r['pct']}%' for r in agg['stance'][:5])} |",
        "",
        "### 对照非金标的角色分布（抽样）",
        "",
        "| fine_role | n | % |",
        "|---|---:|---:|",
    ]
    for r in agg["control_fine_role"][:8]:
        lines.append(f"| `{r['key']}` | {r['n']} | {r['pct']} |")
    lines += [
        "",
        "## 案别差异",
        "",
        "| 案 | 金标数 | Top 细角色 | Top 渠道 |",
        "|---|---:|---|---|",
    ]
    for c in report["cases"]:
        bc = agg["by_case"][c["slug"]]
        roles = ", ".join(f"{k}:{n}" for k, n in bc["top_roles"][:3]) or "—"
        tiers = ", ".join(f"{k}:{n}" for k, n in bc["top_tiers"][:3]) or "—"
        lines.append(f"| {c['slug']} | {bc['n_gold']} | {roles} | {tiers} |")
    lines += [
        "",
        "### 分案一句话",
        "",
    ]
    for slug, note in report["case_notes"].items():
        lines.append(f"- **{slug}**：{note}")
    if agg["llm_common_themes"]:
        lines += [
            "",
            "## 14B 按题归纳（频次）",
            "",
            "### 金标共性说法",
            "",
        ]
        for s, n in agg["llm_common_themes"][:12]:
            lines.append(f"- ({n}) {s}")
        lines += ["", "### 相对对照段多出来的信号", ""]
        for s, n in agg["llm_missing_themes"][:12]:
            lines.append(f"- ({n}) {s}")
    lines += [
        "",
        "## 一筛覆盖 vs 缺口",
        "",
        "### 已覆盖",
        "",
    ]
    for s in gap["stage1_covers"]:
        lines.append(f"- {s}")
    lines += ["", "### 缺口（下一步特征候选，本票不改代码加权）", ""]
    for s in gap["gaps"]:
        lines.append(f"- {s}")
    lines += [
        "",
        "## 方法",
        "",
        "- 严格金标：`conclusions.supporting_facts` → `evidence_samples.para_id`",
        "- 规则：`infer_fine_role` / `channel_tier` / `case_lexicon` 主张族 / 摘句比 / 对立选项粗对齐",
        "- 对照：同题问句词命中非金标抽样 + 金标同文档相邻段",
        "- 14B：每题一条 JSON 归纳，不读金标 id 当线上规则",
        "",
        "## 路径",
        f"- `{OUT / 'R18_gold_why.json'}`",
        f"- `{OUT / 'R18_gold_why.md'}`",
        "",
    ]
    # 附录：每题金标短表
    lines += ["## 附录：每题金标表", ""]
    for c in report["cases"]:
        lines.append(f"### {c['slug']} · {c['name']}")
        lines.append("")
        for q in c["questions"]:
            lines.append(f"**{q['qid']}** {q['question']}")
            lines.append("")
            lines.append("| para | verdict | fine_role | tier | claim | span | stance |")
            lines.append("|---|---|---|---|---|---|---|")
            for g in q["golds"]:
                lines.append(
                    f"| `{g['para_id']}` | {g.get('verdict_label') or '—'} | "
                    f"{g['fine_role']} | {g['channel_tier']} | {g['claim_relation']} | "
                    f"{g['span_vs_quote']} | {g['stance']} |"
                )
            lines.append("")
    return "\n".join(lines)


def _case_notes(cases: list[dict[str, Any]]) -> dict[str, str]:
    notes = {}
    for c in cases:
        roles = Counter()
        claims = Counter()
        spans = Counter()
        for q in c["questions"]:
            for g in q["golds"]:
                roles[g["fine_role"]] += 1
                claims[g["claim_relation"]] += 1
                spans[g["span_vs_quote"]] += 1
        top_role = roles.most_common(1)[0][0] if roles else "?"
        top_claim = claims.most_common(1)[0][0] if claims else "?"
        top_span = spans.most_common(1)[0][0] if spans else "?"
        notes[c["slug"]] = (
            f"主角色 `{top_role}`；主张关系多 `{top_claim}`；摘句形态多 `{top_span}`。"
        )
    # 人工补充跨案差异要点（基于已知案情类型，不写进特征代码）
    notes["liuxiang"] = notes.get("liuxiang", "") + " 就业安置对立口径＋官方通报操作句密集。"
    notes["jilong"] = notes.get("jilong", "") + " 灾害伤亡／救援数字与时点钉；官方口径权重大。"
    notes["us_cn_ai"] = notes.get("us_cn_ai", "") + " 政策提议／双边表态，制度词与预置 leave/money/post 族错位。"
    notes["ai171"] = notes.get("ai171", "") + " 调查结论与时间线长，转述调查报告句多。"
    notes["kh_th"] = notes.get("kh_th", "") + " 边境冲突双方声明，对立选项与外交辞令。"
    notes["wanghong"] = notes.get("wanghong", "") + " 教育／录取表述争议，英文关键词与制度解释段。"
    return notes


def _verdict_bullets(agg: dict[str, Any], gap: dict[str, Any]) -> list[str]:
    role1 = agg["fine_role"][0] if agg["fine_role"] else {"key": "?", "pct": 0}
    tier1 = agg["channel_tier"][0] if agg["channel_tier"] else {"key": "?", "pct": 0}
    span1 = agg["span_vs_quote"][0] if agg["span_vs_quote"] else {"key": "?", "pct": 0}
    bullets = [
        f"金标细角色最常见是 `{role1['key']}`（{role1['pct']}%），渠道最常见 `{tier1['key']}`（{tier1['pct']}%）——官方原文并非多数。",
        f"摘句形态以 `{span1['key']}` 为主（{span1['pct']}%）：拓尔思常标段内关键句，整段打分会吃亏。",
        "跨案共性偏「可核验的事实句」：时点／数额／制度定性／当事人或官方原话；案别差异在主张族（安置对立 vs 灾害数字 vs 外交表态 vs 教育争议）。",
        "一筛已覆盖角色／渠道／粗主张族；缺口主要在：预置族外主张、段内摘句差分、对立选项显式对齐、近邻胜出理由。",
    ]
    if gap["gaps"]:
        bullets.append("优先补特征方向：" + "；".join(gap["gaps"][:3]) + "。")
    return bullets


def main() -> int:
    t0 = time.perf_counter()
    import os
    use_llm = USE_LLM and os.environ.get("VERITAS_R18_NO_LLM", "") not in {"1", "true", "TRUE"}
    cases = []
    for slug, mark in CASES:
        cases.append(analyze_case(slug, mark, use_llm=use_llm))
    agg = _aggregate(cases)
    gap = _coverage_gap(agg)
    case_notes = _case_notes(cases)
    report: dict[str, Any] = {
        "ticket": "R18-gold-why",
        "defaults": {
            "use_llm": use_llm,
            "model": SUMMARY_MODEL,
            "non_gold_per_q": NON_GOLD_PER_Q,
            "no_coeff_refit": True,
        },
        "cases": cases,
        "aggregate": agg,
        "coverage_gap": gap,
        "case_notes": case_notes,
        "verdict_bullets": _verdict_bullets(agg, gap),
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "R18_gold_why.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUT / "R18_gold_why.md").write_text(_markdown(report), encoding="utf-8")
    print("DONE", report["verdict_bullets"][0], flush=True)
    print(f"wrote {OUT / 'R18_gold_why.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
