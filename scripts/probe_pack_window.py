"""C-19 前置实测探针：装箱按「字」、模型按「token」——金标段到底还剩几段看得见？

回答两个问题（零 LLM、零网络、**不写任何字节**）：

1. `MODE=sweep`（默认）：给定装箱字数预算（默认 19000＝2026-10-17 六案真跑那次的预算，
   实证来源 `chain.jsonl` 的 `material_pack.budget`），逐题算
   渲染后提示词字数／估算 token／是否超窗／超多少／金标段「入选」几段／**剪头保尾之后真看得见**几段。
   ⚠ 「入选」与「看得见」是两个数——服务端剪头时，入选但排在提示词头部的段一个字都没到达模型。
2. `MODE=ceiling`：装多少字，金标段的**窗口对齐可达上限**是多少——
   逐题找「渲染后整块真能进窗」的最大预算档，看金标存活几段。
3. `MODE=c53`：C-53 件①＝两批案卷逐题摊开装箱上限三刀＋row/pw 是否相等＋
   `production_pack_messages` 复算整条提示词对产物 `pack_window.est_tokens` 的差与成因；
   另附同一份新案卷「自身上限／改前同题上限」L2 换预复核（金标段键逐字、分母 87）。
   跑法：`MODE=c53 PYTHONPATH=. .venv/bin/python scripts/probe_pack_window.py`
   （可选 `RUN_NEW`／`RUN_OLD`；默认两批 `/tmp/s4runs/time-20261024-201518` 与 `…-001335`）。

口径纪律（三条都踩过坑，别再犯）：
- **入口必须是 `load_official_case`**（官方适配层只在 `run_official_case` 里调用，`app/pipeline.py:1514`）。
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


# ------------------------------------------------------------------ C-53 ----
RUN_NEW = Path(os.environ.get(
    "RUN_NEW", "/tmp/s4runs/time-20261024-201518"))
RUN_OLD = Path(os.environ.get(
    "RUN_OLD", "/tmp/s4runs/time-20261024-001335"))
C53_PERSONA = PERSONA
C53_WINDOW = None  # filled from Settings in mode_c53
C53_DENSITY = None


def _c53_iter_q(run: Path):
    for case_dir in sorted(p for p in run.iterdir() if p.is_dir()):
        if "吉隆" in case_dir.name or not (case_dir / "questions").exists():
            continue
        for qdir in sorted((case_dir / "questions").glob("q_*")):
            if (qdir / "report.json").exists():
                yield case_dir.name, qdir.name, qdir


def _c53_rows(run: Path) -> dict:
    rows_path = run / "rows.jsonl"
    if not rows_path.exists():
        return {}
    out = {}
    for line in rows_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out[(r["case"], r["qid"])] = r
    return out


def _c53_knives(dossier: Dossier, orig: int, window: int, density: float):
    """三刀同形 align_budget_to_window；早退／落点标注 winner。"""
    from app.core.material import production_pack_messages
    hard = max(1, int(window * density))
    set_material_budget(orig)
    msgs0 = production_pack_messages(
        dossier, persona=C53_PERSONA, profile_tier="standard")
    rec0 = estimate_prompt_window(
        msgs0, window_tokens=window, zh_chars_per_token=density)
    est0 = int(rec0["est_tokens"])
    ov0 = int(rec0.get("overflow_tokens") or 0)
    k3 = max(1, int(orig * window / max(est0, 1) * 0.92))
    if ov0 <= 0:
        return {
            "k1": orig, "k2": hard, "k3": k3,
            "winner": "orig已进窗(未开三刀)",
            "est0": est0, "ov0": ov0, "cand": orig,
        }
    cand = min(orig, hard, k3)
    if cand == k3 and k3 <= orig and k3 <= hard:
        w = "knife3=orig×window/est0×0.92"
    elif cand == hard and hard <= orig:
        w = "knife2=window×density"
    else:
        w = "knife1=orig"
    return {
        "k1": orig, "k2": hard, "k3": k3,
        "winner": w, "est0": est0, "ov0": ov0, "cand": cand,
    }


def _c53_batch_table(label: str, run: Path, rows: dict,
                     window: int, density: float) -> list[dict]:
    from app.core.material import production_pack_messages
    print(f"\n======== {label} {run.name} ========")
    hdr = (f"{'case':18} {'qid':5} {'rowBud':>6} {'pwBud':>6} {'eq':>3} "
           f"{'k1orig':>6} {'k2hard':>6} {'k3rat':>6} {'winner':32} "
           f"{'pw.est':>7} {'re.est':>7} {'re.ch':>6} {'dTok':>5} {'d%':>6} cause")
    print(hdr)
    out = []
    for case, qid, qdir in _c53_iter_q(run):
        rep = json.loads((qdir / "report.json").read_text(encoding="utf-8"))
        pw = (rep.get("accounting") or {}).get("pack_window") or {}
        row = rows.get((case, qid), {})
        row_b = int(row.get("budget_used") or 0)
        pw_b = int(pw.get("budget") or 0)
        eq = row_b == pw_b
        dos = Dossier.from_dict(rep)
        orig = row_b or pw_b or BUDGET
        k = _c53_knives(dos, orig, window, density)
        winner = k["winner"]
        if int(pw.get("n_iters") or 0) == 1 and pw.get("fits") and eq:
            winner = "orig已进窗(未开三刀)"
        elif (not eq) and pw_b < row_b:
            diffs = [
                ("knife1=orig", abs(pw_b - k["k1"])),
                ("knife2=window×density", abs(pw_b - k["k2"])),
                ("knife3=orig×window/est0×0.92", abs(pw_b - k["k3"])),
            ]
            best = min(diffs, key=lambda x: x[1])
            if best[1] <= max(50, int(pw_b * 0.03)):
                winner = best[0] + "(对齐落点)"
            else:
                winner = (f"迭代缩档(落点{pw_b};三刀最近={best[0]}Δ{best[1]})")
        set_material_budget(pw_b)
        msgs = production_pack_messages(
            dos, persona=C53_PERSONA, profile_tier="standard")
        rec = estimate_prompt_window(
            msgs, window_tokens=window, zh_chars_per_token=density)
        pw_est = int(pw.get("est_tokens") or 0)
        re_est = int(rec["est_tokens"])
        re_ch = int(rec["total_chars"])
        d_tok = re_est - pw_est
        d_pct = abs(d_tok) / max(pw_est, 1) * 100
        # skinny（fit_safe／messages_for 同形）对照 → 成因判定
        set_material_budget(pw_b)
        pack_material(dos)
        skinny = [
            {"role": "system", "content": render_system_prompt(C53_PERSONA)},
            {"role": "user", "content": render_segments_block(dos)},
        ]
        sk = estimate_prompt_window(
            skinny, window_tokens=window, zh_chars_per_token=density)
        skills_delta = re_est - int(sk["est_tokens"])
        if d_pct <= 5:
            cause = "OK≤5%(现码生产同形)"
        else:
            cause = (f"GAP:现码重装选段漂移(skillsΔ={skills_delta:+d};"
                     f"非覆盖面洞)")
        row_out = {
            "case": case, "qid": qid,
            "row_budget": row_b, "pw_budget": pw_b, "eq": eq,
            "k1": k["k1"], "k2": k["k2"], "k3": k["k3"],
            "winner": winner,
            "pw_est": pw_est, "re_est": re_est, "re_chars": re_ch,
            "d_tok": d_tok, "d_pct": round(d_pct, 2), "cause": cause,
            "skills_delta": skills_delta,
        }
        out.append(row_out)
        print(f"{case[:18]:18} {qid:5} {row_b:6} {pw_b:6} "
              f"{'Y' if eq else 'N':>3} {k['k1']:6} {k['k2']:6} {k['k3']:6} "
              f"{winner:32} {pw_est:7} {re_est:7} {re_ch:6} "
              f"{d_tok:+5} {d_pct:5.1f}% {cause}")
    ok = sum(1 for r in out if r["d_pct"] <= 5)
    print(f"est差 n_ok={ok}/{len(out)}  max={max(r['d_pct'] for r in out):.1f}%")
    return out


def _c53_budget_float(run_new: Path, run_old: Path) -> None:
    print("\n======== 两批同题上限差（判据 b）========")
    print(f"{'case':18} {'qid':5} {'new_pw':>7} {'old_pw':>7} {'Δ':>7} {'Δ%':>6}")
    sum_n = sum_o = 0
    max_abs = (0, "", "", 0, 0)
    for case, qid, qdir in _c53_iter_q(run_new):
        pw_n = int(((json.loads((qdir / "report.json").read_text(
            encoding="utf-8")).get("accounting") or {}).get(
            "pack_window") or {}).get("budget") or 0)
        q_old = run_old / case / "questions" / qid / "report.json"
        pw_o = 0
        if q_old.exists():
            pw_o = int(((json.loads(q_old.read_text(encoding="utf-8")).get(
                "accounting") or {}).get("pack_window") or {}).get(
                "budget") or 0)
        d = pw_n - pw_o
        pct = d / max(pw_o, 1) * 100
        sum_n += pw_n
        sum_o += pw_o
        if abs(d) > max_abs[0]:
            max_abs = (abs(d), case, qid, pw_n, pw_o)
        print(f"{case[:18]:18} {qid:5} {pw_n:7} {pw_o:7} {d:+7} {pct:+5.1f}%")
    shrink = (1 - sum_n / sum_o) * 100 if sum_o else 0
    print(f"合计 new={sum_n} old={sum_o} 小{shrink:.1f}%；"
          f"单题最大|Δ|={max_abs[0]} "
          f"({max_abs[1]}/{max_abs[2]} {max_abs[3]} vs {max_abs[4]})")


def _c53_l2_swap(run_new: Path, run_old: Path) -> None:
    """同一份新案卷：自身上限 vs 改前同题上限 → 须复现 40/87 与 48/87。"""
    try:
        from scripts.probe_recall_funnel import (
            DEFAULT_GOLD, gold_paras_for_question,
        )
    except Exception:
        from probe_recall_funnel import (  # type: ignore
            DEFAULT_GOLD, gold_paras_for_question,
        )

    def budgets(run: Path) -> dict:
        out = {}
        for case, qid, qdir in _c53_iter_q(run):
            rep = json.loads((qdir / "report.json").read_text(encoding="utf-8"))
            pw = (rep.get("accounting") or {}).get("pack_window") or {}
            out[(case, qid)] = int(pw.get("budget") or 0)
        return out

    old_b = budgets(run_old)
    tot_own = tot_old = den = 0
    per: dict[str, list[int]] = {}
    print("\n======== L2 换预复核（判据 a；金标段键逐字）========")
    for case, qid, qdir in _c53_iter_q(run_new):
        rep = json.loads((qdir / "report.json").read_text(encoding="utf-8"))
        dos = Dossier.from_dict(rep)
        gold, _sk = gold_paras_for_question(DEFAULT_GOLD / case, qid)
        if not gold:
            continue
        own = int(((rep.get("accounting") or {}).get(
            "pack_window") or {}).get("budget") or 0)
        ob = old_b.get((case, qid), 0)

        def hit(budget: int) -> int:
            if not budget:
                return 0
            set_material_budget(budget)
            sel = {str(x) for x in (pack_material(dos).get("selected") or [])}
            return sum(1 for _d, para in gold if para in sel)

        h_own, h_old = hit(own), hit(ob)
        tot_own += h_own
        tot_old += h_old
        den += len(gold)
        c = per.setdefault(case, [0, 0, 0])
        c[0] += len(gold)
        c[1] += h_own
        c[2] += h_old
    print(f"分母={den}  自身上限 L2={tot_own}/{den}  "
          f"改前同题上限 L2={tot_old}/{den}")
    for case, (d, a, b) in sorted(per.items()):
        print(f"  {case[:30]:30} den={d:3} own={a:3} old-bud={b:3}")
    if den == 87:
        ok_a = (tot_own == 40 and tot_old == 48)
        print(f"判据 a 复现 40/87 与 48/87：{'✅' if ok_a else '❌ 须逐案拆差'}")
    else:
        print(f"⚠ 分母={den}≠87（吉隆是否混入？）")


def mode_c53() -> None:
    if not RUN_NEW.is_dir() or not RUN_OLD.is_dir():
        sys.exit(f"MODE=c53 需要两批跑次目录：RUN_NEW={RUN_NEW} RUN_OLD={RUN_OLD}")
    st = Settings.from_env()
    window = int(st.model_context_tokens)
    density = float(st.zh_chars_per_token)
    print(f"MODE=c53 window={window} density={density} "
          f"NEW={RUN_NEW} OLD={RUN_OLD}")
    rows_new = _c53_rows(RUN_NEW)
    rows_old = _c53_rows(RUN_OLD)
    _c53_batch_table("NEW最终码", RUN_NEW, rows_new, window, density)
    _c53_batch_table("OLD改前", RUN_OLD, rows_old, window, density)
    _c53_budget_float(RUN_NEW, RUN_OLD)
    _c53_l2_swap(RUN_NEW, RUN_OLD)



def main() -> None:
    if MODE == "c53":
        mode_c53()
        return
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
