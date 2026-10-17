"""C-19 前置实测探针：装箱按「字」、模型按「token」——金标段到底还剩几段看得见？

回答两个问题（零 LLM、零网络、**不写任何字节**）：

1. `MODE=sweep`（默认）：给定装箱字数预算（默认 19000＝2026-10-17 六案真跑那次的预算，
   实证来源 `chain.jsonl` 的 `material_pack.budget`），逐题算
   渲染后提示词字数／估算 token／是否超窗／超多少／金标段「入选」几段／**剪头保尾之后真看得见**几段。
   ⚠ 「入选」与「看得见」是两个数——服务端剪头时，入选但排在提示词头部的段一个字都没到达模型。
2. `MODE=ceiling`：装多少字，金标段的**窗口对齐可达上限**是多少——
   逐题找「渲染后整块真能进窗」的最大预算档，看金标存活几段。

口径纪律（三条都踩过坑，别再犯）：
- **入口必须是 `load_official_case`**（官方适配层只在 `run_official_case` 里调用，`app/pipeline.py:1345`）。
  用 `_load_case_dossier`（演示案例路径）会拿到 `SRC1#s1` 这种 id，金标 `doc_012#p8` 一格都对不上＝假零。
- **估算必须按整条提示词算**（system＋议题行＋围栏＋对撞台账＋收尾指令），只算资料块会漏判超窗：
  本脚本按 19000 字预算复算＝**11/18 题超窗**，只算块是 9/18。
- **超窗之后的损失不是「超出多少丢多少」**。2026-10-17 深度暗号探针（`scripts/probe_context_window.py DEPTHS=1`）
  实测：25,147 字那次只超 1,531 tok，但 55% 深度之前的暗号**全部丢失**——服务端把整条提示词**截到最后约半窗**
  （16384 窗口报 8194、40960 窗口报 20482＝两点一致）。所以 `sweep` 模式并列两模型：
  `cut_half`＝实测（超窗即截到半窗）、`cut_overflow`＝乐观（超多少丢多少，已被实测否证，只作上界）。

跑法（样例集在仓库外；没有该目录会退出码 2，不会静默给假数字）：
    PYTHONPATH=. .venv/bin/python scripts/probe_pack_window.py
    MODE=ceiling BUDGET=19000 OFFICIAL_CASES=/path/to/样例集 PYTHONPATH=. .venv/bin/python scripts/probe_pack_window.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from app.agents.prompts import render_segments_block, render_system_prompt
from app.config import Settings
from app.core.evidence import Dossier
from app.core.material import pack_material, set_material_budget
from app.core.prompt_guard import estimate_prompt_window
from app.ingest.official_case import load_official_case

ROOT = os.environ.get(
    "OFFICIAL_CASES",
    os.path.expanduser("~/Desktop/veritas-testcases/样例集-拓尔思-20261012"))
MODE = os.environ.get("MODE", "sweep")
BUDGET = int(os.environ.get("BUDGET", "19000"))
PERSONA = "你是一名严谨的开源情报分析师，只依据给定资料作答。"
MARK = re.compile(r"\[([^\]\n]+)\] \(")      # 渲染块里的段标记：[seg_id] (locator) 正文
CAND_BUDGETS = [6_000, 9_000, 12_000, 15_000, 18_000, 21_000, 23_849,
                28_000, 34_000, 41_000, 50_000, 59_621]


def cases() -> list[Path]:
    if not os.path.isdir(ROOT):
        sys.exit(f"找不到官方样例集：{ROOT}（用 OFFICIAL_CASES 指定；样例集不入仓库）")
    return sorted(Path(ROOT) / d for d in os.listdir(ROOT)
                  if (Path(ROOT) / d / "raw_documents.json").exists())


def question_gold(case_dir: Path) -> list[tuple[str, str, set[str]]]:
    """[(question_id, 题面, 该案该题的金标段 id 集合)]，按金标出现序。

    `conclusions.json` 里 fact 元素存 `fact_id`，须经同案 `evidence_samples.json`
    换成 `(doc_id, para_id)` 形制的段 id（C-12 R-C12-1）。"""
    gold_all = json.loads((case_dir / "conclusions.json").read_text(encoding="utf-8"))
    samples = json.loads((case_dir / "evidence_samples.json").read_text(encoding="utf-8"))
    fid2 = {str(r.get("fact_id")): str(r.get("para_id") or "") for r in samples}
    out, seen = [], set()
    for d in gold_all:
        qid = str(d.get("question_id"))
        segs: set[str] = set()
        for key in ("supporting_facts", "conflicting_facts"):
            for f in d.get(key) or []:
                pid = str(f.get("para_id") or "") or fid2.get(str(f.get("fact_id")), "")
                if pid:
                    segs.add(pid)
        if qid not in seen:
            seen.add(qid)
            out.append([qid, str(d.get("question") or ""), set(segs)])
        else:
            for row in out:
                if row[0] == qid:
                    row[2] |= segs
    return [(qid, q, segs) for qid, q, segs in out]


def messages_for(dossier: Dossier, budget: int) -> tuple[list[dict], set[str]]:
    set_material_budget(budget)
    pack = pack_material(dossier, budget)
    user = render_segments_block(dossier)
    return ([{"role": "system", "content": render_system_prompt(PERSONA)},
             {"role": "user", "content": user}], pack["selected"])


def visible_ids(messages: list[dict], visible_tokens: int, density: float) -> set[str]:
    """剪头保尾模型：整条提示词只保最后 visible_tokens 个 token，前面的从头部删掉。
    返回仍留在可见区里的段 id。"""
    full = "\x00".join(str(m["content"]) for m in messages)
    system_len = len(str(messages[0]["content"])) + 1
    keep_chars = int(round(visible_tokens * density))
    cut = max(0, len(full) - keep_chars)
    ids: set[str] = set()
    for m in MARK.finditer(full):
        if m.start() >= max(cut, system_len):
            ids.add(m.group(1))
    return ids


def main() -> None:
    st = Settings.from_env()
    density = float(st.zh_chars_per_token)
    window = int(st.model_context_tokens)
    # sweep：超窗之后「模型真看得见多长」的两种模型（cut_half 为实测）
    vis_models = {"cut_half＝超窗即截到半窗（实测）": window // 2,
                  "cut_overflow＝只丢超出量（已否证，上界）": window}
    # ceiling：装箱目标该定在窗口的哪一处
    pack_caps = {"窗口满值": window,
                 "窗口×0.9": int(window * 0.9),
                 "窗口−输出预留": max(1, window - int(st.max_response_tokens))}
    caps = vis_models if MODE == "sweep" else pack_caps
    rows = []
    for case_dir in cases():
        slug = case_dir.name
        base = load_official_case(case_dir)
        for qid, question, gold in question_gold(case_dir):
            snap = Dossier.from_dict(base.to_dict())
            snap.question = question or "该案议题"
            if MODE == "sweep":
                msgs, selected = messages_for(snap, BUDGET)
                rec = estimate_prompt_window(
                    msgs, window_tokens=window, zh_chars_per_token=density)
                hit = {lbl: (len(gold & selected) if rec["overflow_tokens"] == 0
                             else len(gold & visible_ids(msgs, tok, density)))
                       for lbl, tok in caps.items()}
                rows.append({"case": slug, "qid": qid, "n_gold": len(gold),
                             "est_tokens": rec["est_tokens"],
                             "overflow": rec["overflow_tokens"],
                             "sel_hit": len(gold & selected), **hit})
                print(f"{slug}/{qid} 金标{len(gold):>2} 提示词{rec['total_chars']:>6}字"
                      f"≈{rec['est_tokens']:>6}tok "
                      f"{'超' if rec['overflow_tokens'] else '未超'}{rec['overflow_tokens']:>5}  "
                      f"入选 {len(gold & selected):>2}/{len(gold)}  "
                      + "  ".join(f"{lbl.split('＝')[0]} {n:>2}/{len(gold)}"
                                  for lbl, n in hit.items()),
                      flush=True)
            else:
                cache = {}
                for b in CAND_BUDGETS:
                    msgs, selected = messages_for(snap, b)
                    rec = estimate_prompt_window(
                        msgs, window_tokens=window, zh_chars_per_token=density)
                    cache[b] = (len(gold & selected), rec["est_tokens"],
                                len(str(msgs[1]["content"])), b)
                row = {"case": slug, "qid": qid, "n_gold": len(gold), "cache": cache}
                for lbl, cap in caps.items():
                    ok = [b for b in CAND_BUDGETS if cache[b][1] <= cap]
                    best = max(ok) if ok else None
                    row[lbl] = {"budget": best, "hit": cache[best][0] if best else 0,
                                "ratio": round(cache[best][2] / best, 2) if best else None}
                rows.append(row)
                print(f"{slug}/{qid} 金标{len(gold):>2} " + " | ".join(
                    f"{lbl}: {row[lbl]['budget']}字→{row[lbl]['hit']}/{len(gold)}"
                    f"(块×{row[lbl]['ratio']})" if row[lbl]["budget"] else f"{lbl}: 无档能进窗"
                    for lbl in caps), flush=True)

    tot = sum(r["n_gold"] for r in rows)
    print(f"\n=== 合计（六案金标段 {tot}，窗口 {window} tok，密度 {density} 字/tok，"
          f"MODE={MODE}{' 预算 ' + str(BUDGET) if MODE == 'sweep' else ''}）===")
    if MODE == "sweep":
        n_over = sum(1 for r in rows if r["overflow"] > 0)
        print(f"超窗题数 {n_over}/{len(rows)}")
        for lbl in caps:
            n = sum(r[lbl] for r in rows)
            print(f"金标真看得见（{lbl}）{n}/{tot} = {100 * n / tot:.1f}%")
        print(f"金标入选（装箱口径，不看剪头）{sum(r['sel_hit'] for r in rows)}/{tot} = "
              f"{100 * sum(r['sel_hit'] for r in rows) / tot:.1f}%")
        by: dict[str, dict] = {}
        for r in rows:
            c = by.setdefault(r["case"], {"n": 0, "over": 0, "gold": 0, "sel": 0,
                                          **{lbl: 0 for lbl in caps}})
            c["n"] += 1
            c["over"] += 1 if r["overflow"] > 0 else 0
            c["gold"] += r["n_gold"]
            c["sel"] += r["sel_hit"]
            for lbl in caps:
                c[lbl] += r[lbl]
        for k, v in by.items():
            print(f"  {k:<40} 超窗 {v['over']}/{v['n']} 题  入选 {v['sel']:>2}/{v['gold']:<3}"
                  f" = {100 * v['sel'] / v['gold']:5.1f}%  "
                  + "  ".join(f"{lbl.split('＝')[0]} {100 * v[lbl] / v['gold']:5.1f}%"
                              for lbl in caps))
    else:
        for lbl in caps:
            n = sum(r[lbl]["hit"] for r in rows)
            none = sum(1 for r in rows if not r[lbl]["budget"])
            print(f"装箱目标≤{lbl:<14} 窗口对齐可达上限 {n}/{tot} = {100 * n / tot:5.1f}%"
                  f"   无档能进窗的题 {none}/{len(rows)}")
        ratios = [r[lbl]["ratio"] for r in rows for lbl in caps if r[lbl]["ratio"]]
        if ratios:
            print(f"整条提示词字数／装箱字数 比值：min {min(ratios)} ～ max {max(ratios)}"
                  f"（＝窗口约束必须落在**渲染后的整条提示词**上，不能落在预算字数上）")


if __name__ == "__main__":
    main()
