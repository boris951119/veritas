#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现在就能做：本地检索抽检（拓展 / 同义盲区 / 大库选料）并落盘记录。

不跑完整研判（不烧分析师）。用法：
  OPENAI_API_KEY=ollama OPENAI_BASE_URL=http://127.0.0.1:11434/v1 \\
  VERITAS_MODELS=openai/veritas-qwen3-14b \\
  .venv/bin/python scripts/local_retrieval_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_MD = ROOT / "docs" / "local-retrieval-smoke-2026-10-12.md"
OUT_JSON = ROOT / "docs" / "local-retrieval-smoke-2026-10-12.json"
DESK = Path.home() / "Desktop" / "本地研判产物"


def _client():
    from app.config import Settings
    from app.llm.model_client import ModelClientFactory

    s = Settings.from_env()
    s.models = [os.environ.get("VERITAS_MODELS") or "openai/veritas-qwen3-14b"]
    return ModelClientFactory(s).create(), s.models[0]


def smoke_expand(client, model: str) -> list[dict]:
    from app.core.query_rewrite import prepare_search_info, sanitize_variants

    questions = [
        "南山铝业2024年累计现金分红比例为多少",
        "某制造公司会不会倒闭？",
        "客户是否拖欠回款？",
        "恒兴新材海外营收占比是多少？",
        "公司是否收到环保处罚？",
        "它的净利润呢",  # incomplete + prior below
        "应收账款结清了吗",
        "停工传闻是否属实？",
    ]
    prior_for = {"它的净利润呢": "南山铝业2024年累计现金分红比例是多少"}
    # 故意坏拓展：应被闸掉
    poison = {
        "南山铝业2024年累计现金分红比例为多少": [
            "中国银行2024年累计现金分红比例",
            "南山铝业2025年累计现金分红比例",
        ],
    }
    rows = []
    for q in questions:
        t0 = time.monotonic()
        info = prepare_search_info(
            q, prior=prior_for.get(q, ""), client=client, model=model, enabled=True)
        elapsed = round(time.monotonic() - t0, 1)
        dropped = sanitize_variants(q, poison.get(q, []), prior=prior_for.get(q, ""))
        rows.append({
            "question": q,
            "status": info.get("status"),
            "reason": info.get("reason"),
            "variants": info.get("variants") or [],
            "n_queries": info.get("n_queries"),
            "note": info.get("note") or "",
            "elapsed_s": elapsed,
            "poison_kept": dropped,  # 应为空
        })
        print(f"[expand] {info.get('status')} {elapsed}s | {q[:28]}… → {info.get('variants')}",
              flush=True)
    return rows


def smoke_blindspot(client, model: str) -> list[dict]:
    """同义盲区：原问单路 vs 模型拓展多路，看金标段名次。"""
    from app.core.bm25 import rank_segments
    from app.core.evidence import Dossier, Segment, Source, SourceType
    from app.core.query_rewrite import collect_search_queries, prepare_search_info

    cases = [
        {
            "id": "倒闭→资金链/停工",
            "q": "某制造公司会不会倒闭？",
            "gold": "OFF#s1",
            "sources": [
                ("RUMOR", "网传某制造公司马上要倒闭了。"),
                ("OFF", "官方通报：某制造公司资金链紧张但未停工。"),
                ("WX", "今天天气不错适合出游。"),
            ],
        },
        {
            "id": "回款↔应收",
            "q": "客户是否拖欠回款？",
            "gold": "AR#s1",
            "sources": [
                ("NOISE", "公司举办年会气氛热烈。"),
                ("AR", "期末应收账款余额上升，部分客户账期延长。"),
                ("OTHER", "股价今日上涨。"),
            ],
        },
        {
            "id": "停工↔停产",
            "q": "停工传闻是否属实？",
            "gold": "OFF#s1",
            "sources": [
                ("RUMOR", "有人说厂子已经停工了。"),
                ("OFF", "官方澄清：产线按计划运转，不存在全面停产。"),
                ("WX", "天气预报明天有雨。"),
            ],
        },
    ]
    rows = []
    for c in cases:
        d = Dossier(question=c["q"])
        for sid, text in c["sources"]:
            src = Source.create(sid, SourceType.NEWS, id=sid)
            src.segments = [Segment(id=f"{sid}#s1", source_id=sid, text=text, index=0)]
            d.add_source(src)
        base_qs = collect_search_queries(c["q"], [])
        info = prepare_search_info(c["q"], client=client, model=model, enabled=True)
        multi_qs = list(info.get("queries") or base_qs)
        single = [sid for sid, _ in rank_segments(d, queries=[c["q"]])]
        lexicon = [sid for sid, _ in rank_segments(d, queries=base_qs)]
        multi = [sid for sid, _ in rank_segments(d, queries=multi_qs)]

        def _rank(order: list[str], gold: str) -> int | None:
            return order.index(gold) + 1 if gold in order else None

        row = {
            "id": c["id"],
            "question": c["q"],
            "gold": c["gold"],
            "rank_original_only": _rank(single, c["gold"]),
            "rank_lexicon": _rank(lexicon, c["gold"]),
            "rank_model_expand": _rank(multi, c["gold"]),
            "expand_status": info.get("status"),
            "variants": info.get("variants") or [],
            "improved_vs_original": (
                (_rank(multi, c["gold"]) or 99) < (_rank(single, c["gold"]) or 99)
            ),
        }
        rows.append(row)
        print(f"[blind] {c['id']} orig={row['rank_original_only']} "
              f"lex={row['rank_lexicon']} exp={row['rank_model_expand']} "
              f"var={row['variants']}", flush=True)
    return rows


def smoke_corpus_select() -> dict:
    """大库选料：桌面南山铝业（≥50）→ N/M 披露。"""
    from app.config import Settings
    from app.pipeline import _load_case_dossier

    case = Path.home() / "Desktop/veritas-testcases/eval-corpus/南山铝业"
    if not case.is_dir():
        return {"ok": False, "error": f"语料不存在: {case}"}
    settings = Settings.from_env()
    settings.corpus_select_min_sources = 50
    settings.material_char_budget = 19_000
    q = "南山铝业2024年累计现金分红比例为多少"
    t0 = time.monotonic()
    print(f"[select] loading {case} …", flush=True)
    d = _load_case_dossier(case, settings, search_queries=[q])
    elapsed = round(time.monotonic() - t0, 1)
    sel = (d.accounting or {}).get("corpus_select") or {}
    note = str(sel.get("note") or "")
    # also check ingest note
    ingest = [n for n in (d.ingest_notes or []) if n.get("kind") == "corpus_select"]
    out = {
        "ok": bool(sel) or bool(ingest),
        "elapsed_s": elapsed,
        "n_sources_loaded": len(d.sources),
        "n_segments": sum(len(s.segments) for s in d.sources),
        "corpus_select": sel,
        "note": note or (ingest[0].get("detail") if ingest else ""),
        "has_NM_disclosure": ("库内" in note and "纳入" in note) or ("未入选" in note)
        or bool(sel.get("n_library_sources")),
    }
    print(f"[select] sources={out['n_sources_loaded']} note={out['note'][:120]!r}",
          flush=True)
    return out


def render_md(payload: dict) -> str:
    lines = [
        "# 本地检索抽检记录（2026-10-12）",
        "",
        "> 「现在就能做」三项：问句同义拓展抽检 / 同义盲区对照 / 大库选料冒烟。",
        "> 模型：本地 `veritas-qwen3-14b` @ Ollama。**不能**单独把架构图改绿。",
        "",
        f"- 生成时间：{payload.get('finished_at')}",
        f"- 总耗时：{payload.get('elapsed_s')}s",
        "",
        "## 1. 问句同义拓展抽检",
        "",
        "| 议题 | status | variants | 耗时 | 毒丸闸 |",
        "|---|---|---|---:|---|",
    ]
    n_ok = 0
    for r in payload["expand"]:
        if r["status"] == "ok":
            n_ok += 1
        var = "；".join(r["variants"][:2]) or "（无）"
        if r.get("question", "").startswith("南山铝业2024"):
            poison = "通过" if r.get("poison_kept") == [] else f"漏网{r.get('poison_kept')}"
        else:
            poison = "—"
        lines.append(
            f"| {r['question'][:36]} | {r['status']} | {var[:40]} | {r['elapsed_s']} | {poison} |"
        )
    lines += [
        "",
        f"**小结**：{n_ok}/{len(payload['expand'])} 题模型拓展 `status=ok`；"
        "换主体/捏造年份毒丸不得进入 variants（机械闸）。",
        "",
        "## 2. 同义盲区对照（金标段名次，越小越好）",
        "",
        "| 场景 | 仅原问 | 词表 | 模型拓展 | 是否优于仅原问 | variants |",
        "|---|---:|---:|---:|---|---|",
    ]
    for r in payload["blindspot"]:
        lines.append(
            f"| {r['id']} | {r['rank_original_only']} | {r['rank_lexicon']} | "
            f"{r['rank_model_expand']} | {'是' if r['improved_vs_original'] else '否'} | "
            f"{'；'.join(r['variants'][:2])[:36] or '—'} |"
        )
    improved = sum(1 for r in payload["blindspot"] if r["improved_vs_original"])
    lines += [
        "",
        f"**小结**：{improved}/{len(payload['blindspot'])} 场景模型多路优于「仅原问」。"
        "词表本身已覆盖部分同义；模型拓展的增量看 variants 是否带来新说法。",
        "",
        "## 3. 大库选料冒烟（南山铝业桌面全量库）",
        "",
    ]
    sel = payload["select"]
    if not sel.get("ok"):
        lines.append(f"- 失败：{sel.get('error') or sel}")
    else:
        lines += [
            f"- 耗时：{sel.get('elapsed_s')}s",
            f"- 本次纳入信源：{sel.get('n_sources_loaded')} 份 / "
            f"{sel.get('n_segments')} 段",
            f"- 选料账本：`{json.dumps(sel.get('corpus_select') or {}, ensure_ascii=False)[:200]}`",
            f"- 披露句：{sel.get('note') or '（无）'}",
            f"- N/M 类披露：{'有' if sel.get('has_NM_disclosure') else '无/弱'}",
        ]
    lines += [
        "",
        "## 4. 对架构图改绿的含义",
        "",
        "- 本记录满足「现在可做」抽检，**不满足**云端/官方验收。",
        "- 问句同义拓展 / BM25 两格仍黄；须真网关 +（官方用例或产品书面接受自建口径）。",
        "- 议题预检/前提格仍黄；须云端恒兴 10 问换成绩单。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    os.environ.setdefault("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    os.environ.setdefault("VERITAS_MODELS", "openai/veritas-qwen3-14b")
    os.environ.setdefault("VERITAS_OCR", "0")

    t_all = time.monotonic()
    print("=== local retrieval smoke start ===", flush=True)
    client, model = _client()
    print(f"model={model}", flush=True)

    expand = smoke_expand(client, model)
    # 毒丸复验钉在南山那题
    from app.core.query_rewrite import sanitize_variants
    for r in expand:
        if r["question"].startswith("南山铝业2024"):
            r["poison_kept"] = sanitize_variants(
                r["question"],
                ["中国银行2024年累计现金分红比例", "南山铝业2025年累计现金分红比例"],
            )

    blind = smoke_blindspot(client, model)
    select = smoke_corpus_select()

    from datetime import datetime, timezone

    payload = {
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_s": round(time.monotonic() - t_all, 1),
        "model": model,
        "expand": expand,
        "blindspot": blind,
        "select": select,
    }
    md = render_md(payload)
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    DESK.mkdir(parents=True, exist_ok=True)
    (DESK / OUT_MD.name).write_text(md, encoding="utf-8")
    (DESK / OUT_JSON.name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md, flush=True)
    print(f"\nWROTE {OUT_MD}", flush=True)
    print(f"DESKTOP {DESK / OUT_MD.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
