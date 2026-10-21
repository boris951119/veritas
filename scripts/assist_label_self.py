# -*- coding: utf-8 -*-
"""#38 第一步＝**模型辅助标注**（只出草稿，**不入库**；最终 label 必须人签）。

为什么要它：C-24 的校准曲线要 `对／部分／错` 三种人签 label，而候选清单里 256 行
`label` 全空。用户 2026-10-22 拍＝**甲**＝我用**本机 Ollama 14B** 先标一遍、
**用户抽检签字**后才是真标定集。⇒ 本脚本产的是**草稿**，一律落 `/tmp/s4runs/`，
**绝不写 `calibration/`**（未经人签的 label 不入库）。

安全闸（照 `measure_s4_gates.lock_local`，不发一次请求就退出）：
网关必须硬钉本机 Ollama＋假密钥 `ollama`＋单模型链，任何不满足直接 SystemExit。

一条防编造的机械核：模型给的「支撑片段」必须在喂给它的那几条逐字引文里**逐字可定位**，
定位不到 ⇒ 这行 `flag="支撑片段不可定位"`、label 记空，**不计入**（宁缺毋标）。

用法：
    .venv/bin/python scripts/assist_label_self.py --limit 60
    .venv/bin/python scripts/assist_label_self.py --help        # 无密钥可跑
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = Path("/tmp/s4runs")
ALLOWED = ("对", "部分", "错")
MAX_QUOTES_CHARS = 1200          # 单行喂给模型的引文总量上限（防超窗）
LABEL_SYSTEM = (
    "你在为一条「置信度校准」的标定集做**辅助标注**，最终由人签字。"
    "只依据我给你的逐字引文判断这条结论，不使用你自己的知识、不补全没给的数字。\n"
    "三档口径（必须逐字选一个）：\n"
    "对＝引文直接支撑该结论的主体、指标与程度，且没有与引文矛盾；\n"
    "部分＝方向对但范围／程度／时点有一处明显偏差，或只支撑到结论的一半；\n"
    "错＝引文里没有支撑，或与引文直接矛盾（包括把「未提及」说成「已发生」）。\n"
    "只输出一个 JSON 对象，不解释、不额外文本：\n"
    '{"label":"对|部分|错","why":"不超过 40 字的中文理由",'
    '"quote":"从给定引文里逐字抄出来的支撑片段（找不到就写空串）",'
    '"sure":true}'
)


def _locks() -> str:
    """复用测量脚本里那把闸（规则只许一条，别自己再写一份）。"""
    from scripts.measure_s4_gates import lock_local

    return lock_local()


def _find_conclusion(case: str, cid: str) -> dict[str, Any] | None:
    """按候选清单同一批产物树（cases/<case>/out*/report.json）取回结论原文与引文。"""
    for rp in sorted((ROOT / case).glob("out*/report.json")):
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        by_id = {str(c.get("id")): c for c in (data.get("conclusions") or [])}
        con = by_id.get(cid)
        if not con:
            continue
        ev_by_id = {str(e.get("id")): e for e in (data.get("evidences") or [])}
        quotes = []
        for eid in (con.get("evidence_ids") or []):
            q = str((ev_by_id.get(str(eid)) or {}).get("quote") or "").strip()
            if q:
                quotes.append(q)
        total = 0
        kept: list[str] = []
        for q in quotes:
            if total + len(q) > MAX_QUOTES_CHARS:
                break
            kept.append(q)
            total += len(q)
        return {"question": str(data.get("question") or ""),
                "statement": str(con.get("statement") or ""),
                "status": str(con.get("status") or ""),
                "confidence": con.get("confidence"),
                "quotes": kept, "n_quotes": len(quotes),
                "dropped_quotes": max(0, len(quotes) - len(kept)),
                "report": str(rp)}
    return None


def _norm(s: str) -> str:
    """去 Markdown 强调与空白后的比对文本（引文里 **62%** 这种，模型常连着抄或拆着抄）。"""
    return re.sub(r"[\s\*_`]+", "", s).lower()


def _unlocatable(quote: str, quotes: list[str]) -> str:
    """把模型抄的支撑片段按分隔符拆段，逐段要求在给定引文里逐字可定位。

    返回第一个定位不到的片段（截断），全定位到返回空串。片段 <6 字不参与（标点噪声）。
    """
    normed = [_norm(q) for q in quotes]
    for frag in re.split(r"[|｜\n…]+|\.{3}", quote):
        f = _norm(frag)
        if len(f) < 6:
            continue
        if not any(f in n for n in normed):
            return frag[:24]
    return ""


def _label_one(client, model: str, rec: dict[str, Any]) -> dict[str, Any]:
    lines = [f"[{i + 1}] {q}" for i, q in enumerate(rec["quotes"])]
    user = (f"研判议题：{rec['question']}\n\n待标结论：{rec['statement']}\n\n"
            "逐字引文（唯一可用依据）：\n" + ("\n".join(lines) or "（案卷里没有给它任何引文）"))
    t0 = time.perf_counter()
    try:
        from app.agents.base import extract_json

        resp = client.chat(model, [{"role": "system", "content": LABEL_SYSTEM},
                                   {"role": "user", "content": user}], json_mode=True)
        data = extract_json(resp.content)
        el = time.perf_counter() - t0
        label = str(data.get("label") or "").strip()
        quote = str(data.get("quote") or "").strip()
        flag = ""
        if label not in ALLOWED:
            flag = f"label 越界({label})"
        if label in ALLOWED and quote:
            bad = _unlocatable(quote, rec["quotes"])
            if bad:
                flag = f"支撑片段不可定位({bad})"
        if label in ALLOWED and not quote:
            flag = flag or "无支撑片段"
        return {"model_label": label if not flag else "",
                "why": str(data.get("why") or "")[:80],
                "quote": quote[:160], "sure": bool(data.get("sure")),
                "flag": flag, "elapsed_s": round(el, 2),
                "tokens": getattr(resp, "total_tokens", None)}
    except Exception as exc:                       # 标注失败要留痕，不许当成「错」
        return {"model_label": "", "why": "", "quote": "", "sure": False,
                "flag": f"调用失败({type(exc).__name__})",
                "elapsed_s": round(time.perf_counter() - t0, 2), "tokens": None}


def run(cands_path: Path, limit: int) -> int:
    gate = _locks()
    from app.llm.model_client import ModelClientFactory
    from scripts.measure_s4_gates import MODEL, settings_for

    client = ModelClientFactory(settings_for(None)).create()
    rows = [json.loads(l) for l in cands_path.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    todo = rows[:limit] if limit else rows
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = OUT / f"assist-label-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[assist] {gate}\n候选 {len(rows)} 行，本轮标 {len(todo)} 行，草稿目录＝{out_dir}"
          "（**不写 calibration/**）", flush=True)

    drafts: list[dict[str, Any]] = []
    for n, r in enumerate(todo, 1):
        rec = _find_conclusion(r["case"], r["conclusion_id"])
        if not rec or not rec["statement"]:
            drafts.append({**r, "model_label": "", "flag": "案卷里找不到该结论",
                           "why": "", "quote": "", "sure": False,
                           "elapsed_s": 0.0})
            print(f"  {n:>3} {r['case'][-18:]} {r['conclusion_id'][:14]} 找不到结论", flush=True)
            continue
        got = _label_one(client, MODEL, rec)
        row = {**r, "statement": rec["statement"][:120], "score": rec["confidence"],
               "n_quotes": rec["n_quotes"], "dropped_quotes": rec["dropped_quotes"],
               **got}
        drafts.append(row)
        with (out_dir / "draft_labels.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  {n:>3} {r['case'][-18:]} {r['conclusion_id'][:14]} "
              f"分 {float(rec['confidence'] or 0):.3f} → {got['model_label'] or '—'} "
              f"{('｜' + got['flag']) if got['flag'] else ''} ({got['elapsed_s']}s)", flush=True)

    ok = [d for d in drafts if d["model_label"] in ALLOWED]
    counts = {k: sum(1 for d in ok if d["model_label"] == k) for k in ALLOWED}
    summary = {"dir": str(out_dir), "n_rows": len(drafts), "n_labeled": len(ok),
               "counts": counts, "n_flagged": len(drafts) - len(ok),
               "flags": sorted({d["flag"] for d in drafts if d.get("flag")}),
               "avg_s": round(sum(d["elapsed_s"] for d in drafts) / max(1, len(drafts)), 2),
               "signed": False,
               "note": "草稿＝模型先标；未经用户抽检签字不得进 calibration/、不得当 ground truth"}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    md = ["# 自标定集抽检表（模型先标，等你签字）", "",
          "| # | 案例 | 结论（截断） | 置信 | 模型标 | 理由 | 支撑片段 | 旗 |",
          "|---|---|---|---|---|---|---|---|"]
    for i, d in enumerate(drafts, 1):
        md.append(f"| {i} | {d['case'].split('/')[-1]} | {d.get('statement', '')[:40]} "
                  f"| {float(d.get('score') or 0):.3f} | {d['model_label'] or '—'} "
                  f"| {d.get('why', '')} | {(d.get('quote') or '')[:36]} | {d.get('flag', '')} |")
    (out_dir / "spot_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(f"抽检表＝{out_dir / 'spot_check.md'}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--candidates", default=str(ROOT / "calibration/candidates_self.jsonl"))
    ap.add_argument("--limit", type=int, default=60,
                    help="标前 N 行（0＝全量）；默认 60＝达标行数")
    args = ap.parse_args()
    path = Path(args.candidates)
    if not path.is_file():
        raise SystemExit(f"找不到候选清单 {path}（先生成：python scripts/calibrate_confidence.py "
                         "--emit-candidates）")
    return run(path, max(0, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
