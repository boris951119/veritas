#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-120 件①：树17 q_003 回落解剖（零 LLM，只读渲染面）。

尺源：C-113 枝树（`tree17_focus_cite` 只在这棵枝上存在）。
对照＝同一题同一案卷，旗关 vs 旗开，量「分析师真正看到的资料面」：
  · 盒（装箱结果）两臂是否相同
  · 点名名单 must 里有多少段本来不在盒内
  · 渲染后的资料面长了多少字、金标段落在哪个位置
  · 按声明窗模拟尾部截断⇒金标段会不会「在盒内却进不了模型眼前」

用法：
  cd <枝树> && PYTHONPATH=. .venv/bin/python -u scripts/probe_c120_q003_autopsy.py \
      --out <主仓>/artifacts/C120_q003_autopsy.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.prompts import render_segments_block  # noqa: E402
from app.config import Settings, resolve_model_window  # noqa: E402
from app.core.kg_density_bridge import density_submit_surface  # noqa: E402
from app.core.kg_submit_surface import (  # noqa: E402
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)
from app.core.material import pack_material  # noqa: E402
from app.core.tree17_focus_cite import apply_tree17_focus_cite  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from app.llm.connections import resolve_credentials  # noqa: E402
from scripts.measure_s4_gates import lock_local  # noqa: E402
from scripts.probe_c66_multi_box import selected_locs  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    gold_paras_for_question,
)
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits  # noqa: E402

CASES = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
C85 = Path("/tmp/c85_k180")
CASE = "刘翔编制“二选一”事件"
MAIN = Path("/Users/liuboyu/Developer/veritas")
MODEL_ID = "openai/veritas-qwen3-14b"
QIDS = ("q_001", "q_002", "q_003")
# 字/token：本机 14B 真密度区间（短提示会拉低，分析师长腿实测 1.60～1.65）
DENSITIES = (1.45, 1.60)


def _meta() -> dict[tuple[str, str], dict]:
    raw = json.loads((C85 / "score_input.json").read_text(encoding="utf-8"))
    return {(j["case"], j["qid"]): j for j in raw}


def _gold_seg(gold: set) -> set[str]:
    return {
        str(loc) if "#" in str(loc) else f"{doc}#{loc}"
        for doc, loc in gold
    }


def _arm(case: str, query: str, budget: int, gs: set[str], *, cite: bool):
    os.environ["VERITAS_TREE17_FOCUS_CITE"] = "1" if cite else "0"
    d = load_official_case(CASES / case)
    d.question = query
    bridge = density_submit_surface(
        d, top_n=180, order=None, gold_ids=gs or None, use_stage1=True,
    )
    leaks = audit_forbidden_keys(bridge["surface"])
    d.accounting["kg_submit"] = bridge["surface"]
    d.accounting["kg_cap_segments"] = False
    apply_kg_submit_surface(d, enabled=True)
    p = pack_material(d, budget_chars=budget, **pack_kwargs_for_kg(d))
    sel = {str(x) for x in (p.get("selected") or [])}
    d.accounting["material_pack_selected"] = sorted(sel)
    must: list[str] = []
    if cite:
        m = apply_tree17_focus_cite(d, enabled=True)
        must = [str(x) for x in (m or {}).get("must_consider") or []]
        leaks += audit_forbidden_keys(m or {})
    block = render_segments_block(d)
    return {
        "d": d, "sel": sel, "must": must, "block": block, "leaks": leaks,
        "gold_in_box": sorted(g for g in gs if g in sel),
    }


def _rendered_ids(block: str) -> list[str]:
    """资料面里实际出现的段（按出现顺序，取 [doc_xxx#pN] 标记）。"""
    import re

    return re.findall(r"\[(doc_[0-9a-zA-Z]+#p[0-9]+)\]", block)


def _probe_q(qid: str, m: dict, gold_dict: dict, settings) -> dict[str, Any]:
    query, budget = m["query"], int(m["budget"])
    gold = set(gold_dict.keys())
    gs = _gold_seg(gold)
    off = _arm(CASE, query, budget, gs, cite=False)
    on = _arm(CASE, query, budget, gs, cite=True)

    b_off, b_on = off["block"], on["block"]
    ids_off, ids_on = _rendered_ids(b_off), _rendered_ids(b_on)
    must_set = set(on["must"])
    extra = sorted(must_set - off["sel"])          # 点名里本来不在盒内的段
    n_gold = len(on["gold_in_box"])
    # 尾部截断模拟：按字/token 估输入 token，落在声明窗之外的部分＝可能被截
    win_info = resolve_model_window(settings, MODEL_ID, do_probe=False)
    win = int(win_info.get("window_tokens") or 0)
    cut: dict[str, Any] = {"window_source": win_info.get("source"),
                           "window_rule": win_info.get("rule"),
                           "window_detail": win_info.get("detail")}
    for dens in DENSITIES:
        est = len(b_on) / dens
        room = int(win * dens) if win > 0 else 0
        cut[f"dens_{dens}"] = {
            "est_tokens_block_only": round(est, 1),
            "room_chars_in_window": room,
            "block_chars": len(b_on),
            "tail_chars_out": max(0, len(b_on) - room),
        }
    # 每段金标在开／关两臂资料面里的位置（偏移占全长比例）
    by_id = {seg.id: seg for src in on["d"].sources for seg in src.segments}
    gold_pos: dict[str, Any] = {}
    for g in on["gold_in_box"]:
        marker = f"[{g}]"
        po, pn = b_off.find(marker), b_on.find(marker)
        gold_pos[g] = {
            "text_head": str(getattr(by_id.get(g), "text", "") or "")[:26],
            "off_present": po >= 0,
            "on_present": pn >= 0,
            "off_ratio": round(po / max(1, len(b_off)), 4) if po >= 0 else None,
            "on_ratio": round(pn / max(1, len(b_on)), 4) if pn >= 0 else None,
            "on_chars_from_head": pn,
        }
    return {
        "qid": qid,
        "denom": len(gold),
        "box_same": sorted(off["sel"]) == sorted(on["sel"]),
        "n_sel_off": len(off["sel"]), "n_sel_on": len(on["sel"]),
        "gold_in_box": on["gold_in_box"],
        "must": on["must"],
        "must_in_box": sorted(must_set & on["sel"]),
        "must_extra_not_in_box": extra,
        "n_must_extra": len(extra),
        "must_gold_hits": sorted(must_set & gs),
        "must_non_gold": sorted(must_set - gs),
        "block_chars_off": len(b_off),
        "block_chars_on": len(b_on),
        "block_delta_chars": len(b_on) - len(b_off),
        "n_rendered_off": len(ids_off),
        "n_rendered_on": len(ids_on),
        "rendered_added": [x for x in ids_on if x not in set(ids_off)],
        "rendered_missing": [x for x in ids_off if x not in set(ids_on)],
        "order_changed_prefix": (
            ids_off[:8] != ids_on[:8] if ids_off and ids_on else None
        ),
        "window_tokens_declared": win,
        "block_diff_span": _diff_span(b_off, b_on),
        "tail_cut": cut,
        "gold_positions": gold_pos,
        "leaks": off["leaks"] + on["leaks"],
        "md5_off": _fp(b_off), "md5_on": _fp(b_on),
    }


def _fp(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def _diff_span(a: str, b: str) -> dict[str, Any]:
    """两臂资料面的「最长公共前／后缀」差＝证明开臂只插了一块还是动了别的。"""
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[len(a) - 1 - j] == b[len(b) - 1 - j]:
        j += 1
    return {
        "common_prefix_chars": i,
        "common_suffix_chars": j,
        "removed_chars": len(a) - i - j,
        "added_chars": len(b) - i - j,
        "pure_insertion": (len(a) - i - j) == 0,
        "added_head": b[i:len(b) - j][:260],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(MAIN / "artifacts/C120_q003_autopsy.md"))
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--only", default="q_003", help="逗号分隔；默认只解剖 q_003")
    args = ap.parse_args()

    note = lock_local()
    print(note, flush=True)
    creds = resolve_credentials("openai/veritas-qwen3-14b") or {}
    print("base_url=", creds.get("base_url"), "（本票零 LLM 调用）", flush=True)

    for k, v in {
        "VERITAS_KG_SUBMIT_SURFACE": "1",
        "VERITAS_KG_STAGE1": "1",
        "VERITAS_KG_REHYDRATE_BOX": "1",
        "VERITAS_MULTI_BOX": "0",
        "VERITAS_SECOND_PASS": "0",
        "VERITAS_REVIEW_BOOST": "0",
        "VERITAS_TREE17_FOCUS_CITE": "0",
    }.items():
        os.environ[k] = v

    settings = Settings.from_env()
    settings.models = ["openai/veritas-qwen3-14b"]
    settings = settings.validate()

    meta = _meta()
    rows = []
    for qid in [x.strip() for x in args.only.split(",") if x.strip()]:
        gold_dict, _skipped = gold_paras_for_question(
            Path(args.gold_dir) / CASE, qid)
        rows.append(_probe_q(qid, meta[(CASE, qid)], gold_dict, settings))
        print(f"… {qid} 盒同={rows[-1]['box_same']} "
              f"资料面 {rows[-1]['block_chars_off']}→{rows[-1]['block_chars_on']} 字 "
              f"点名外加 {rows[-1]['n_must_extra']} 段", flush=True)

    leaks = sum(len(r["leaks"]) for r in rows)
    payload = {
        "件": "C-120 件①（解剖，零 LLM）",
        "枝树": str(ROOT), "枝tip": os.popen(
            f"git -C {ROOT} rev-parse --short HEAD").read().strip(),
        "main_tip": os.popen(
            f"git -C {MAIN} rev-parse --short HEAD").read().strip(),
        "case": CASE, "qids": [r["qid"] for r in rows],
        "leaks": leaks, "rows": rows,
        "note": "gold_ids 在 density_submit 只做披露不参与选段（已读源码核实）；"
                "本票不产模型调用。",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C-120 件① — 树17 q_003 回落解剖（零 LLM）",
        "",
        f"> 枝树 `{payload['枝tip']}`（C-113）· main `{payload['main_tip']}` · "
        "旗开／关只比渲染面，不跑模型。",
        f"> 泄漏审计（FORBIDDEN_PACK_KEYS）＝**{leaks}**。",
        "",
    ]
    for r in rows:
        lines += [
            f"## {r['qid']}（金标 denom={r['denom']}）",
            "",
            f"- 盒：关 {r['n_sel_off']} 段／开 {r['n_sel_on']} 段；"
            f"两臂盒**{'相同' if r['box_same'] else '不同'}**",
            f"- 资料面字数：关 {r['block_chars_off']} → 开 {r['block_chars_on']}"
            f"（Δ{r['block_delta_chars']:+d}）；渲染段数 {r['n_rendered_off']} → "
            f"{r['n_rendered_on']}",
            f"- 点名名单 must={len(r['must'])}，其中不在盒内＝{r['n_must_extra']} 段："
            f"{r['must_extra_not_in_box']}",
            f"- must ∩ 金标＝{r['must_gold_hits']}；must 非金标 {len(r['must_non_gold'])} 段",
            f"- 渲染面新开出的段＝{r['rendered_added']}；关臂有开臂反而没有的＝"
            f"{r['rendered_missing']}",
            f"- 两臂资料面逐字对照：公共前缀 {r['block_diff_span']['common_prefix_chars']} 字／"
            f"公共后缀 {r['block_diff_span']['common_suffix_chars']} 字／"
            f"开臂净插入 {r['block_diff_span']['added_chars']} 字／"
            f"删掉 {r['block_diff_span']['removed_chars']} 字 ⇒ "
            f"**{'纯插入（其余资料面一字未动）' if r['block_diff_span']['pure_insertion'] else '除插入还改动了别的'}**；"
            f"插入内容起手＝`{r['block_diff_span']['added_head'][:120]}`",
            f"- 窗（do_probe=False＝只取声明）＝{r['window_tokens_declared']} tok，"
            f"来源={r['tail_cut'].get('window_source')}·"
            f"{r['tail_cut'].get('window_detail')}；尾部截断模拟＝"
            f"{json.dumps({k: v for k, v in r['tail_cut'].items() if not k.startswith('window')}, ensure_ascii=False)}",
            "- 金标在开臂资料面里的位置：",
        ]
        for g, p in r["gold_positions"].items():
            lines.append(
                f"  - `{g}`「{p['text_head']}…」 在场(关/开)={p['off_present']}/"
                f"{p['on_present']} 位置比例(关/开)={p['off_ratio']}/{p['on_ratio']} "
                f"距面首={p['on_chars_from_head']} 字"
            )
        lines.append("")
    text = "\n".join(lines)
    out.write_text(text + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(text, flush=True)
    print("wrote", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
