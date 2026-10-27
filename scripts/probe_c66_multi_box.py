#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-66 件①b：续盒／开大窗·材料到达面（入仓可复跑探针）。

四行臂（同六案 18 题、同金标分母 105、同 BM25＋密度键；只读现码 pack_material）：
  A0      ＝现行单窗（预算＝产物 accounting.pack_window.budget）⇒ 必须复现 48/105
  A1×2／×3＝同一案卷、预算 ×2／×3（单窗开大）
  B′2／B′3＝逐箱**段级剔除已装段**（信源本体保留）后重调 pack_material；
            三道闸每箱重跑、每箱预算同值；L2_union(≤1/≤2/≤3)

默认 ``--dry-run``＝零模型、零 HTTP、零付费、不 import torch，只打印将要做的事与题目数。
真量加 ``--run``。刀①＝``--no-strip``（第 2／3 盒从完整案卷重装）⇒ L2_union 必须回到 48。

判据：
  a  A0 复现 48/105（复现不出＝停手）
  b  --no-strip ⇒ L2_union(≤3)＝48（尺有牙）
  c  A1×2／×3 对上 66／74（oracle；对不上写进交账，不许静默改口径）
  e  构造侧 assert gold_root is None；金标只在计数一步打开
  f  命中按 (doc_id, para_id) 逐字匹配（app/export/official.py:_segment_locator）

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c66_multi_box.py \\
      --run-dir /path/to/six_case_run
  PYTHONPATH=. .venv/bin/python scripts/probe_c66_multi_box.py \\
      --run-dir /path/to/six_case_run --run
  PYTHONPATH=. .venv/bin/python scripts/probe_c66_multi_box.py \\
      --run-dir /path/to/six_case_run --run --no-strip
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from app.export.official import _segment_locator  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    discover_reports,
    gold_paras_for_question,
)

# 架构师件① 留档目标（判据 a／b／c；对不上不许改断言迁就）
TARGET_A0 = 48
TARGET_A1_2X = 66
TARGET_A1_3X = 74
TARGET_B_U2 = 65
TARGET_B_U3 = 71
TARGET_KNIFE = 48
TARGET_DENOM = 105


def _budget_from_report(rep: dict) -> int:
    pw = (rep.get("accounting") or {}).get("pack_window") or {}
    b = pw.get("budget")
    if b is None:
        raise ValueError("report 缺 accounting.pack_window.budget")
    return int(b)


def construct_jobs(
    run_dir: Path,
    *,
    gold_root: Path | None,
) -> dict:
    """构造侧：只扫跑次产物。金标路径必须为 None（判据 e）。"""
    assert gold_root is None, "判据 e：构造侧 gold_root 必须为 None"
    jobs = []
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        budget = _budget_from_report(rep)
        jobs.append({
            "case": case,
            "qid": qid,
            "budget": budget,
            "report": str(rp.resolve()),
        })
    return {
        "run_dir": str(run_dir.resolve()),
        "n_questions": len(jobs),
        "jobs": jobs,
    }


def fresh(raw: dict, drop: frozenset[str] = frozenset()) -> Dossier:
    """段级剔除已装段（信源本体保留）＝下一盒的案卷；每次从原始产物重建。"""
    d = Dossier.from_dict(raw)
    if drop:
        for src in d.sources:
            src.segments = [s for s in src.segments if str(s.id) not in drop]
    return d


def gold_keys_for(gold_dir: Path, case: str, qid: str) -> tuple[set[tuple[str, str]], int]:
    """判分侧才调用。返回 ({(doc_id, para_id), ...}, denom)。"""
    gold, _sk = gold_paras_for_question(gold_dir / case, qid)
    keys = set(gold.keys())
    return keys, len(gold)


def selected_locs(dossier: Dossier, selected: set[str]) -> set[tuple[str, str]]:
    """判据 f：段 id → (doc_id, para_id)；定位不到的丢掉。"""
    out: set[tuple[str, str]] = set()
    for sid in selected:
        loc = _segment_locator(dossier, sid)
        if loc is not None:
            out.add((str(loc[0]), str(loc[1])))
    return out


def l2_hits(gold: set[tuple[str, str]], locs: set[tuple[str, str]]) -> int:
    return len(gold & locs)


def classify_box_vs_box1_excluded(
    box_sel: set[str],
    box1_excluded_reasons: dict[str, str],
) -> Counter:
    """每箱装入段在首盒 excluded 名单里的成因分布（三类）。"""
    c: Counter = Counter()
    for sid in box_sel:
        reason = box1_excluded_reasons.get(sid)
        if reason is None:
            c["名单里没有＝上游闸挡掉或不在候选池"] += 1
        elif "BM25" in reason or "排序未入" in reason:
            c["BM25 排序未入预算"] += 1
        elif "预算" in reason or "窗口" in reason:
            # 「预算截断」与窗口对齐截断同归预算侧（首盒 cut_reason）
            c["预算截断"] += 1
        else:
            # 其它 reason 原文归入「预算截断」旁的披露桶，仍计三类之外的原文字串
            c[reason] += 1
    return c


def run_arms(
    jobs: list[dict],
    gold_dir: Path,
    *,
    strip: bool,
) -> dict[str, Any]:
    """真量四行臂＋刀①（strip=False 时）。金标只在本函数打开。"""
    tot = Counter()
    reason_tot = {2: Counter(), 3: Counter()}
    rows: list[dict] = []
    a0_ok_n = 0

    for job in jobs:
        budget = int(job["budget"])
        raw = json.loads(Path(job["report"]).read_text(encoding="utf-8"))
        # 完整案卷（计数／locator 用；剔除后的案卷只用装箱）
        dossier_full = fresh(raw)
        gold, denom = gold_keys_for(gold_dir, job["case"], job["qid"])
        if denom == 0:
            continue

        # —— A0 / 首盒 ——
        p1 = pack_material(dossier_full, budget_chars=budget)
        sel1 = {str(x) for x in (p1.get("selected") or [])}
        used1 = int(p1.get("used_chars") or 0)
        excl_reasons = {
            str(e.get("seg_id")): str(e.get("reason") or "")
            for e in (p1.get("excluded") or [])
        }

        # —— B′ 第 2／3 盒 ——
        if strip:
            p2 = pack_material(fresh(raw, frozenset(sel1)), budget_chars=budget)
            sel2 = {str(x) for x in (p2.get("selected") or [])}
            p3 = pack_material(
                fresh(raw, frozenset(sel1 | sel2)), budget_chars=budget)
            sel3 = {str(x) for x in (p3.get("selected") or [])}
        else:
            # 刀①：不剔除＝从完整案卷重装（与首盒同输入 ⇒ 选中集应同形）
            p2 = pack_material(dossier_full, budget_chars=budget)
            sel2 = {str(x) for x in (p2.get("selected") or [])}
            p3 = pack_material(dossier_full, budget_chars=budget)
            sel3 = {str(x) for x in (p3.get("selected") or [])}
        used2 = int(p2.get("used_chars") or 0)
        used3 = int(p3.get("used_chars") or 0)

        # —— A1 开大窗 ——
        a1_2 = {str(x) for x in (
            pack_material(dossier_full, budget_chars=2 * budget).get("selected") or [])}
        a1_3 = {str(x) for x in (
            pack_material(dossier_full, budget_chars=3 * budget).get("selected") or [])}

        u1, u2, u3 = sel1, sel1 | sel2, sel1 | sel2 | sel3
        assert sel1 <= u3, "构造保证破了：首盒段从并集里消失了（lost 定义失效）"

        # 判据 f：locator 一律走完整案卷（段 id 未改）
        loc1 = selected_locs(dossier_full, sel1)
        loc_u2 = selected_locs(dossier_full, u2)
        loc_u3 = selected_locs(dossier_full, u3)
        loc_a12 = selected_locs(dossier_full, a1_2)
        loc_a13 = selected_locs(dossier_full, a1_3)

        a0 = l2_hits(gold, loc1)
        a1_2x = l2_hits(gold, loc_a12)
        a1_3x = l2_hits(gold, loc_a13)
        l2_box1 = a0
        l2_u1 = a0
        l2_u2 = l2_hits(gold, loc_u2)
        l2_u3 = l2_hits(gold, loc_u3)

        lost = sorted(gold & loc1 - loc_u3)  # 构造上应恒空
        gained = sorted(gold & loc_u3 - loc1)

        r2 = classify_box_vs_box1_excluded(sel2, excl_reasons)
        r3 = classify_box_vs_box1_excluded(sel3, excl_reasons)
        reason_tot[2].update(r2)
        reason_tot[3].update(r3)

        fill1 = round(used1 / budget, 4) if budget else 0.0
        fill2 = round(used2 / budget, 4) if budget else 0.0
        fill3 = round(used3 / budget, 4) if budget else 0.0

        row = {
            "case": job["case"],
            "qid": job["qid"],
            "budget": budget,
            "n1": len(sel1), "n2": len(sel2), "n3": len(sel3),
            "used1": used1, "used2": used2, "used3": used3,
            "fill1": fill1, "fill2": fill2, "fill3": fill3,
            "a0": a0, "a1_2x": a1_2x, "a1_3x": a1_3x,
            "l2_box1": l2_box1,
            "l2_union_1": l2_u1, "l2_union_2": l2_u2, "l2_union_3": l2_u3,
            "lost_n": len(lost), "gained_n": len(gained),
            "gained": [{"doc_id": d, "para_id": p} for d, p in gained],
            "box2_vs_box1_excluded": dict(r2),
            "box3_vs_box1_excluded": dict(r3),
            "denom": denom,
            "strip": strip,
        }
        rows.append(row)
        tot["denom"] += denom
        for k in ("a0", "a1_2x", "a1_3x", "l2_box1",
                  "l2_union_1", "l2_union_2", "l2_union_3",
                  "lost_n", "gained_n"):
            tot[k] += row[k]
        if a0 == l2_hits(gold, loc1):
            a0_ok_n += 1  # 逐题自洽（恒真）；真正闸＝合计 48

    summary = {
        "strip": strip,
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "a0": int(tot["a0"]),
        "a1_2x": int(tot["a1_2x"]),
        "a1_3x": int(tot["a1_3x"]),
        "l2_box1": int(tot["l2_box1"]),
        "l2_union_1": int(tot["l2_union_1"]),
        "l2_union_2": int(tot["l2_union_2"]),
        "l2_union_3": int(tot["l2_union_3"]),
        "lost_n": int(tot["lost_n"]),
        "gained_n": int(tot["gained_n"]),
        "box2_reason_dist": dict(reason_tot[2]),
        "box3_reason_dist": dict(reason_tot[3]),
        "rows": rows,
    }
    return summary


def print_dry_run(pack: dict) -> None:
    print("======== C-66 --dry-run（零模型、零 HTTP、零付费、不 import torch）========")
    print(f"run_dir＝{pack['run_dir']}")
    print(f"题目数＝{pack['n_questions']}")
    print("将要做的事（需显式 --run）：")
    print("  A0     ＝pack_material(dossier, budget_chars=产物 pack_window.budget)")
    print("  A1×2／×3＝同 dossier、预算 ×2／×3")
    print("  B′2／B′3＝逐箱段级剔除已装段后重调 pack_material（每箱预算同值）")
    print("  刀①     ＝加 --no-strip：第 2／3 盒从完整案卷重装，L2_union 须回 48")
    print("  金标     ＝只在计数一步打开（构造侧 gold_root=None）")
    print("  命中口径＝(doc_id, para_id) ← _segment_locator")
    print("本 dry-run 未调用 pack_material、未读金标、未发任何网络／模型请求。")


def print_table(summary: dict) -> None:
    d = summary["denom"]
    print("\n======== 到达面合计 ========")
    print(f"题数＝{summary['n_questions']}｜分母＝{d}｜strip＝{summary['strip']}")
    print(f"A0 单窗           L2＝{summary['a0']}/{d}")
    print(f"A1 预算×2         L2＝{summary['a1_2x']}/{d}")
    print(f"A1 预算×3         L2＝{summary['a1_3x']}/{d}")
    print(f"B′ L2_box1        ＝{summary['l2_box1']}/{d}")
    print(f"B′ L2_union(≤1)   ＝{summary['l2_union_1']}/{d}")
    print(f"B′ L2_union(≤2)   ＝{summary['l2_union_2']}/{d}")
    print(f"B′ L2_union(≤3)   ＝{summary['l2_union_3']}/{d}")
    print(f"相对 A0 lost＝{summary['lost_n']}｜gained＝{summary['gained_n']}")
    print("\n第 2 盒装入段的『首盒成因』分布：")
    for r, c in sorted(summary["box2_reason_dist"].items(), key=lambda x: -x[1]):
        print(f"  {r}：{c}")
    print("第 3 盒装入段的『首盒成因』分布：")
    for r, c in sorted(summary["box3_reason_dist"].items(), key=lambda x: -x[1]):
        print(f"  {r}：{c}")
    print("\n逐题（A0｜A1×2｜A1×3｜∪1｜∪2｜∪3｜n1/n2/n3｜used｜fill｜预算）：")
    for r in summary["rows"]:
        print(
            f"{r['case'][:14]}/{r['qid']}｜"
            f"{r['a0']}｜{r['a1_2x']}｜{r['a1_3x']}｜"
            f"{r['l2_union_1']}｜{r['l2_union_2']}｜{r['l2_union_3']}｜"
            f"{r['n1']}/{r['n2']}/{r['n3']}｜"
            f"{r['used1']}/{r['used2']}/{r['used3']}｜"
            f"{r['fill1']:.2f}/{r['fill2']:.2f}/{r['fill3']:.2f}｜"
            f"{r['budget']}"
        )


def judge(summary: dict, *, is_knife: bool) -> dict[str, Any]:
    """判据 a／b／c 红绿。"""
    out: dict[str, Any] = {}
    a_ok = summary["a0"] == TARGET_A0 and summary["denom"] == TARGET_DENOM
    out["a"] = {
        "ok": a_ok,
        "got": f"{summary['a0']}/{summary['denom']}",
        "want": f"{TARGET_A0}/{TARGET_DENOM}",
    }
    if is_knife:
        b_ok = summary["l2_union_3"] == TARGET_KNIFE
        out["b"] = {
            "ok": b_ok,
            "got": summary["l2_union_3"],
            "want": TARGET_KNIFE,
            "note": "--no-strip 刀①",
        }
    else:
        c_ok = (
            summary["a1_2x"] == TARGET_A1_2X
            and summary["a1_3x"] == TARGET_A1_3X
        )
        out["c"] = {
            "ok": c_ok,
            "got": f"{summary['a1_2x']}/{summary['a1_3x']}",
            "want": f"{TARGET_A1_2X}/{TARGET_A1_3X}",
        }
        out["b_prime_u2"] = {
            "got": summary["l2_union_2"],
            "archivist": TARGET_B_U2,
            "match": summary["l2_union_2"] == TARGET_B_U2,
        }
        out["b_prime_u3"] = {
            "got": summary["l2_union_3"],
            "archivist": TARGET_B_U3,
            "match": summary["l2_union_3"] == TARGET_B_U3,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument(
        "--run-dir", required=True,
        help="六案跑次归档目录（含 */questions/*/report.json）；不许默认 /tmp",
    )
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument(
        "--out", default="",
        help="可选：把 summary.json 写到此目录（默认不写盘到仓库）",
    )
    ap.add_argument("--dry-run", action="store_true", default=None)
    ap.add_argument("--run", action="store_true",
                    help="显式真量（零模型装箱＋金标计数）")
    ap.add_argument(
        "--no-strip", action="store_true",
        help="刀①：盒间不剔除已装段；L2_union 必须回到 48",
    )
    args = ap.parse_args(argv)

    do_run = bool(args.run)
    if args.dry_run is True and do_run:
        raise SystemExit("不能同时 --dry-run 与 --run")
    dry = not do_run

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"跑次不存在：{run_dir}", file=sys.stderr)
        return 2

    # —— 构造（不开金标）——
    print("[构造] gold_root=None …", flush=True)
    pack = construct_jobs(run_dir, gold_root=None)
    print(f"判据 e：构造未读金标＝True；题目数＝{pack['n_questions']}", flush=True)

    if dry:
        print_dry_run(pack)
        print("判据 a/b/c：需 --run 才出数（本 dry-run 停在计划披露）。")
        return 0

    gold_dir = Path(args.gold_dir)
    if not gold_dir.is_dir():
        print(f"金标目录不存在：{gold_dir}", file=sys.stderr)
        return 2

    strip = not bool(args.no_strip)
    print(f"\n[真量] strip＝{strip}（--no-strip＝{args.no_strip}）…", flush=True)
    summary = run_arms(pack["jobs"], gold_dir, strip=strip)
    print_table(summary)

    criteria = judge(summary, is_knife=not strip)
    print("\n======== 判据 ========")
    # e／f 结构性
    print("判据 e：构造侧 gold_root is None＝✅")
    print("判据 f：命中口径＝_segment_locator → (doc_id, para_id)＝✅（已用）")

    a = criteria["a"]
    print(f"判据 a：A0＝{a['got']}（要 {a['want']}）＝{'✅' if a['ok'] else '❌'}")
    if not a["ok"]:
        print("判据 a 红 ⇒ 口径飘了，停手交回（不许改断言迁就）。", flush=True)
        if args.out:
            Path(args.out).mkdir(parents=True, exist_ok=True)
            Path(args.out, "summary.json").write_text(
                json.dumps({"summary": summary, "criteria": criteria},
                           ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        return 3

    if not strip:
        b = criteria["b"]
        print(f"判据 b（刀① --no-strip）：L2_union(≤3)＝{b['got']}"
              f"（要 {b['want']}）＝{'✅' if b['ok'] else '❌'}")
        if not b["ok"]:
            print("判据 b 红 ⇒ 并集尺是假的，停手。", flush=True)
            return 3
    else:
        c = criteria["c"]
        print(f"判据 c：A1×2／×3＝{c['got']}（要 {c['want']}）＝"
              f"{'✅' if c['ok'] else '❌'}")
        if not c["ok"]:
            print("判据 c 红 ⇒ 与〔144〕oracle 对不上；写进交账，不许静默改口径。",
                  flush=True)
            # 不改断言；仍返回非零以便架构师看见
            rc = 4
        else:
            rc = 0
        print(f"对照 B′ ∪2＝{criteria['b_prime_u2']['got']}"
              f"（架构师留档 {TARGET_B_U2}）＝"
              f"{'✅' if criteria['b_prime_u2']['match'] else '≠'}")
        print(f"对照 B′ ∪3＝{criteria['b_prime_u3']['got']}"
              f"（架构师留档 {TARGET_B_U3}）＝"
              f"{'✅' if criteria['b_prime_u3']['match'] else '≠'}")
        if args.out:
            outp = Path(args.out)
            outp.mkdir(parents=True, exist_ok=True)
            (outp / "summary.json").write_text(
                json.dumps({"summary": summary, "criteria": criteria},
                           ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            print(f"[wrote] {outp / 'summary.json'}", flush=True)
        return rc

    if args.out:
        outp = Path(args.out)
        outp.mkdir(parents=True, exist_ok=True)
        (outp / "summary.json").write_text(
            json.dumps({"summary": summary, "criteria": criteria},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"[wrote] {outp / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    assert "torch" not in sys.modules
    raise SystemExit(main())
