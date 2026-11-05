#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-120 件②：q_003 回落的逐遍配对（本地 14B，零现金）。

为什么要这一件：C-113 只跑了「关一趟／开一趟」，而 L3 只差 1 段＝
正好等于跑动噪声的量级 ⇒ 一次配对证不了「名单让模型少引一段」。
本件把同一题同一臂重复 N 遍，先量噪声，再看开臂是不是稳定少引。

三条候选主因各自钉死：
  a 名单带偏（可复现）＝开臂把结论引向 must 里的非金标段，稳定多引非金标／少引金标
  b 输出抖动（噪声主导）＝关臂自身各遍 L3 就跳 ≥1
  c 转写打回＝丢的那段其实被提出过，但引文逐字核对不过（check_evidence 报因）
本票不动生产逻辑，只跑枝树现码；旗只在这条命令里临时置 1／0。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.base import Analyst  # noqa: E402
from app.config import Settings  # noqa: E402
from app.core.citation_check import check_evidence  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from app.llm.model_client import ModelClient  # noqa: E402
from scripts.measure_s4_gates import lock_local  # noqa: E402
from scripts.probe_c120_q003_autopsy import (  # noqa: E402
    CASE, CASES, C85, MODEL_ID, MAIN, _arm, _gold_seg, _meta,
)
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD, cited_hits, gold_paras_for_question,
)

QID = "q_003"
PASSES = 3


def _analyst(d, settings) -> None:
    analyst = Analyst(
        name="mainstream",
        persona="主流研判分析师，依据资料作答并给出逐字引文",
        model=settings.models[0],
        client=ModelClient(settings),
        settings=settings,
        profile_tier="compliant",
    )
    analyst.analyze(d)


def _pass_stats(d, gold_dict: dict, gs: set[str], box: list[str]) -> dict[str, Any]:
    hit_para, hit_quote, hit_either = cited_hits(gold_dict, d)
    keys = set(gold_dict.keys())
    hit_ids = {
        str(p) if "#" in str(p) else f"{doc}#{p}" for doc, p in hit_either
    }
    cited_ids: set[str] = set()
    for e in d.evidences:
        cited_ids.update(str(x) for x in (e.segment_ids or []))
    ev_detail = []
    for e in d.evidences:
        fails = check_evidence(e, d) or []
        ev_detail.append({
            "seg_ids": [str(x) for x in (e.segment_ids or [])],
            "quote_head": str(e.quote or "")[:36],
            "check_fails": fails,
        })
    return {
        "l3": sum(1 for k in keys if k in hit_either),
        "hit_para_n": sum(1 for k in keys if k in hit_para),
        "hit_quote_n": sum(1 for k in keys if k in hit_quote),
        "cited_gold_ids": sorted(hit_ids & set(box)),
        "seen_not_id_face": [g for g in box if g not in cited_ids],
        "n_evidences": len(d.evidences),
        "n_conclusions": len(d.conclusions),
        "cited_ids_all": sorted(cited_ids),
        "evidences": ev_detail,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=PASSES)
    ap.add_argument("--out", default=str(MAIN / "artifacts/C120_q003_noise.md"))
    args = ap.parse_args()

    note = lock_local()
    print(note, flush=True)
    for k, v in {
        "VERITAS_KG_SUBMIT_SURFACE": "1",
        "VERITAS_KG_STAGE1": "1",
        "VERITAS_KG_REHYDRATE_BOX": "1",
        "VERITAS_MULTI_BOX": "0",
        "VERITAS_SECOND_PASS": "0",
        "VERITAS_REVIEW_BOOST": "0",
    }.items():
        os.environ[k] = v

    settings = Settings.from_env()
    settings.models = [MODEL_ID]
    settings.multi_box = False
    settings.second_pass_enabled = False
    settings.review_boost = False
    settings.llm_timeout_seconds = 600
    settings = settings.validate()

    # C-113 读数里 q_003 丢的那段（从枝树产物现算，不硬编码）
    c113 = json.loads(
        (ROOT / "artifacts/C113_tree17_focus_cite.json").read_text(encoding="utf-8"))
    row113 = next(r for r in c113["rows"] if r["qid"] == QID)
    box113 = set(row113["off_gold_in_box"])
    hit_off_113 = box113 - set(row113["off_seen_not"])
    hit_on_113 = box113 - set(row113["on_seen_not"])
    lost = sorted(hit_off_113 - hit_on_113)
    print(f"… C-113 那次 q_003 丢的金标＝{lost}（现算自枝树产物）", flush=True)

    meta = _meta()
    m = meta[(CASE, QID)]
    gold_dict, _sk = gold_paras_for_question(
        Path(str(DEFAULT_GOLD)) / CASE, QID)
    gold = set(gold_dict.keys())
    gs = _gold_seg(gold)

    passes: list[dict[str, Any]] = []
    leaks_total = 0
    for label in ("off", "on"):
        cite = label == "on"
        for i in range(1, args.passes + 1):
            os.environ["VERITAS_TREE17_FOCUS_CITE"] = "1" if cite else "0"
            t0 = time.perf_counter()
            arm = _arm(CASE, m["query"], int(m["budget"]), gs, cite=cite)
            d = arm["d"]
            d.conclusions.clear()
            d.evidences.clear()
            _analyst(d, settings)
            st = _pass_stats(d, gold_dict, gs, arm["gold_in_box"])
            leaks_total += len(arm["leaks"])
            wl = (d.accounting or {}).get("window_ledger") or {}
            pw = (d.accounting or {}).get("prompt_window") or {}
            over = [n for n in (d.ingest_notes or [])
                    if isinstance(n, dict) and n.get("kind") == "prompt_over_window"]
            rec = {
                "arm": label, "pass": i,
                "box_n": len(arm["sel"]),
                "denom": len(gold),
                "gold_in_box": arm["gold_in_box"],
                "must": arm["must"],
                "must_gold_in_box_hits": sorted(
                    set(arm["must"]) & set(st["cited_gold_ids"])),
                "must_non_gold_cited": sorted(
                    (set(arm["must"]) & set(st["cited_ids_all"])) - gs),
                "block_chars": len(arm["block"]),
                "server_input_tokens": wl.get("input_tokens"),
                "prompt_window_status": pw.get("status"),
                "over_window_note": bool(over),
                "over_window_detail": [
                    {k: v for k, v in n.items() if k != "kind"} for n in over][:1],
                "lost_target_cited": [g for g in lost if g in st["cited_gold_ids"]],
                "lost_target_claimed_id": [
                    g for g in lost
                    if any(g in e["seg_ids"] for e in st["evidences"])],
                "lost_target_evidence": [
                    e for e in st["evidences"]
                    if any(g in e["seg_ids"] for g in lost)],
                "wall_s": round(time.perf_counter() - t0, 1),
                **st,
            }
            passes.append(rec)
            print(f"… {label}#{i} L3={st['l3']}/{len(gold)} "
                  f"ev={st['n_evidences']} cons={st['n_conclusions']} "
                  f"目标段被引＝{rec['lost_target_cited']} "
                  f"({rec['wall_s']}s)", flush=True)
            arm["d"] = None

    off_l3 = [p["l3"] for p in passes if p["arm"] == "off"]
    on_l3 = [p["l3"] for p in passes if p["arm"] == "on"]
    off_span = (max(off_l3) - min(off_l3)) if off_l3 else 0
    on_span = (max(on_l3) - min(on_l3)) if on_l3 else 0
    off_mean = sum(off_l3) / max(1, len(off_l3))
    on_mean = sum(on_l3) / max(1, len(on_l3))
    target_lost_all_on = all(not p["lost_target_cited"] for p in passes if p["arm"] == "on")
    target_lost_some_off = any(not p["lost_target_cited"] for p in passes if p["arm"] == "off")
    # 判据（第二版，订正过）：四条各自独立，互不蕴含
    #   reproducible_shift＝开臂每遍都把证据名额花在「点名但非金标」段上，关臂没有
    #   l3_separated＝两臂 L3 集合完全分离（这才配叫「稳定增益／稳定回落」）
    #   transcribe_reject＝目标段被提出过，但逐字核对不过（生产链会打回）
    #   noise_covers_gap＝均值差的绝对值 ≤ 任一臂自身跨度
    on_ng = [len(p["must_non_gold_cited"]) for p in passes if p["arm"] == "on"]
    off_ng = [len(p["must_non_gold_cited"]) for p in passes if p["arm"] == "off"]
    reproducible_shift = bool(on_ng) and bool(off_ng) and min(on_ng) > max(off_ng)
    l3_separated = bool(off_l3) and bool(on_l3) and (
        min(on_l3) > max(off_l3) or max(on_l3) < min(off_l3))
    transcribe_reject = any(
        e["check_fails"]
        for p in passes
        for e in p["lost_target_evidence"]
    )
    transcribe_reject_by_arm = {
        arm: sum(
            1 for p in passes if p["arm"] == arm
            for e in p["lost_target_evidence"] if e["check_fails"]
        ) for arm in ("off", "on")
    }
    noise_covers_gap = abs(on_mean - off_mean) <= max(off_span, on_span)
    cause_b = noise_covers_gap and not l3_separated
    cause_a = reproducible_shift
    cause_c = transcribe_reject
    # 旧版 cause_c 写成了「提出过就算」＝恒真倾向，已订正（见 md 仪器坑第 3 条）

    lines = [
        "# C-120 件② — q_003 回落逐遍配对（本地 14B）",
        "",
        f"> 枝树 `{os.popen(f'git -C {ROOT} rev-parse --short HEAD').read().strip()}`"
        f" · main `{os.popen(f'git -C {MAIN} rev-parse --short HEAD').read().strip()}`"
        f" · 每臂 {args.passes} 遍 · 温度＝{settings.llm_temperature} · 泄漏 {leaks_total}。",
        "",
        f"- C-113 那次丢的金标＝`{lost}`（现算自枝树产物）",
        f"- 关臂各遍 L3＝{off_l3}（跨度 {off_span}）；开臂各遍 L3＝{on_l3}（跨度 {on_span}）",
        f"- 均值：关 {off_mean:.2f} → 开 {on_mean:.2f}（Δ {on_mean - off_mean:+.2f}）",
        f"- 目标段是否被引：开臂 {'全部没引' if target_lost_all_on else '有引到'}／"
        f"关臂 {'有遍没引' if target_lost_some_off else '每遍都引'}",
        "",
        "## 主因判定（四条独立，互不蕴含）",
        "",
        f"- b 噪声盖住均值差＝**{cause_b}**（|Δ均值| {abs(on_mean - off_mean):.2f} ≤ 臂内最大跨度 "
        f"{max(off_span, on_span)}；两臂 L3 集合完全分离＝{l3_separated}）",
        f"- a 名单带偏可复现＝**{cause_a}**（每遍「点名但非金标」被引条数 开 {on_ng} vs 关 {off_ng}）",
        f"- c 转写打回＝**{cause_c}**（目标段被提出但逐字核对不过：关 "
        f"{transcribe_reject_by_arm['off']} 条／开 {transcribe_reject_by_arm['on']} 条）",
        f"- d 超窗灯＝两臂各 {sum(1 for p in passes if p['arm']=='off' and p['over_window_note'])}"
        f"／{sum(1 for p in passes if p['arm']=='on' and p['over_window_note'])} 遍亮"
        "（`prompt_over_window`；这只说明我们的估算超窗，不证明服务端截到哪儿）",
        "",
        "## 逐遍",
        "",
    ]
    for p in passes:
        lines.append(
            f"- {p['arm']}#{p['pass']}: L3={p['l3']}/{p['denom']} "
            f"para命中={p['hit_para_n']} quote命中={p['hit_quote_n']} "
            f"ev={p['n_evidences']} cons={p['n_conclusions']} "
            f"目标段被引={p['lost_target_cited']} 提出过={p['lost_target_claimed_id']} "
            f"非金标点名段被引={len(p['must_non_gold_cited'])} "
            f"证据核对失败={sum(1 for e in p['evidences'] if e['check_fails'])}/{p['n_evidences']} "
            f"超窗灯={p['over_window_note']} "
            f"资料面={p['block_chars']}字 服务端入参tok={p['server_input_tokens']} "
            f"{p['wall_s']}s"
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    out.write_text(text + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps({
        "qid": QID, "passes_per_arm": args.passes, "lost_target": lost,
        "off_l3": off_l3, "on_l3": on_l3, "off_mean": off_mean, "on_mean": on_mean,
        "off_span": off_span, "on_span": on_span,
        "cause_a_list_bias": cause_a, "cause_b_noise": cause_b, "cause_c_transcribe": cause_c,
        "reproducible_shift": reproducible_shift, "l3_separated": l3_separated,
        "noise_covers_gap": noise_covers_gap,
        "transcribe_reject_by_arm": transcribe_reject_by_arm,
        "must_non_gold_cited_by_arm": {"off": off_ng, "on": on_ng},
        "leaks": leaks_total, "temperature": settings.llm_temperature,
        "rows": passes,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(text, flush=True)
    print("wrote", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
