#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-60：四臂纸面筛选（甲条数／乙时点数字／丙改选／甲＋乙）。

构造侧**零模型**；只在判分侧串行调用本机 14B（复用 measure_s4_gates.judge_one
与 JUDGE_SYSTEM，一字不改）。产物只落 /tmp；app/ 零 diff。

四臂（假想提交面，同一题集同一顺序）：
  甲＝每题最多 3 条内部结论（report.json，status∈{majority,dissent}，按 confidence 降序）
  乙＝现行 headline 后追加该结论已引证据 quote 里抽出的时点／数字 token
  丙＝次高置信的另一条内部结论（无次高 ⇒ 空句，记 disclosure）
  甲＋乙＝甲的每条都带乙后缀

乙抽取规则（docstring 钉死）：
  - 数字＝`app.core.numeric_check.extract_nums`（audit 数字闸同源）对 quote 文本；
  - 时点＝`app.core.temporal_check._YEAR_IN_TEXT`（as-of 闸同源）对 quote 文本；
  - 去重：保序唯一；截断：时点最多 4 个、数字最多 8 个；后缀形如
    ``｜时点：a；b｜数字：1；2``；两侧皆空则不加后缀；**不许编造、不许新词表**。

判据 a：同分母 18／同金标文件／同 JUDGE_SYSTEM／同 max_score 取法 → 打印
「口径相同＝True」。
判据 e：构造入口 `gold_root is None`；打印构造期读过的文件清单。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from app.core.numeric_check import extract_nums
from app.core.temporal_check import _YEAR_IN_TEXT

# 评判腿一字不改
from measure_s4_gates import (  # noqa: E402
    JUDGE_SYSTEM,
    MODEL,
    OFFICIAL,
    judge_one,
    lock_local,
    settings_for,
)

DEFAULT_RUN = Path("/tmp/s4runs/time-20261026-123957")
DEFAULT_A_ROWS = Path("/tmp/s4runs/calib-20261026-171536/rows.jsonl")
DEFAULT_OUT = Path("/tmp/c60_submission_variants")
ARMS = ("甲", "乙", "丙", "甲＋乙")
AGREE_KEYS = ("一致", "部分一致", "不一致", "未答", "评判失败")


class FileTracker:
    """构造期读文件登记（判据 e）。"""

    def __init__(self) -> None:
        self.files: list[str] = []

    def read_text(self, path: Path) -> str:
        p = path.resolve()
        self.files.append(str(p))
        return p.read_text(encoding="utf-8")

    def read_json(self, path: Path):
        return json.loads(self.read_text(path))


def _usable(cons: list[dict]) -> list[dict]:
    rows = [
        c for c in cons
        if c.get("status") in ("majority", "dissent")
        and str(c.get("statement") or "").strip()
    ]
    rows.sort(key=lambda c: (-float(c.get("confidence") or 0.0), str(c.get("id") or "")))
    return rows


def _tokens_from_quotes(quotes: list[str]) -> tuple[list[str], list[str]]:
    times: list[str] = []
    nums: list[str] = []
    seen_t: set[str] = set()
    seen_n: set[str] = set()
    for q in quotes:
        for m in _YEAR_IN_TEXT.finditer(q or ""):
            tok = m.group(0).replace(" ", "")
            if tok not in seen_t:
                seen_t.add(tok)
                times.append(tok)
        for n in extract_nums(q or ""):
            raw = (n.raw or "").strip()
            if raw and raw not in seen_n:
                seen_n.add(raw)
                nums.append(raw)
    return times[:4], nums[:8]


def _suffix(times: list[str], nums: list[str]) -> str:
    parts = []
    if times:
        parts.append("时点：" + "；".join(times))
    if nums:
        parts.append("数字：" + "；".join(nums))
    return ("｜" + "｜".join(parts)) if parts else ""


def _quotes_for(con: dict, evidences: list[dict]) -> list[str]:
    cid = con.get("id")
    out = []
    for e in evidences:
        if e.get("conclusion_id") == cid:
            q = str(e.get("quote") or "").strip()
            if q:
                out.append(q)
    return out


def construct_variants(
    run_dir: Path,
    *,
    gold_root: Path | None,
    tracker: FileTracker,
) -> dict:
    """构造四臂假想提交面。金标路径必须为 None（判据 e）。"""
    assert gold_root is None, "判据 e：构造侧金标路径必须为 None"
    cases = sorted(
        d for d in run_dir.iterdir()
        if d.is_dir() and (d / "questions").is_dir() and (d / "conclusions.json").is_file()
    )
    units: list[dict] = []
    for case_dir in cases:
        submitted = tracker.read_json(case_dir / "conclusions.json")
        conf_rows = []
        conf_path = case_dir / "confidence.json"
        if conf_path.is_file():
            conf_rows = tracker.read_json(conf_path)
        score_by_cid = {
            str(r["conclusion_id"]): float(r["score"])
            for r in conf_rows
            if isinstance(r, dict) and r.get("conclusion_id") is not None
            and isinstance(r.get("score"), (int, float))
        }
        by_q_scores: dict[str, list[float]] = {}
        for r in conf_rows:
            if isinstance(r, dict) and r.get("question_id") is not None:
                by_q_scores.setdefault(str(r["question_id"]), []).append(
                    float(r.get("score") or 0.0))

        sub_by_q = {
            str(r["question_id"]): str(r.get("conclusion") or "")
            for r in submitted if isinstance(r, dict) and r.get("question_id") is not None
        }
        for qid in sorted(sub_by_q.keys()):
            q_dir = case_dir / "questions" / qid
            rep_path = q_dir / "report.json"
            if not rep_path.is_file():
                units.append({
                    "case": case_dir.name, "qid": qid,
                    "headline": sub_by_q[qid],
                    "max_score": max(by_q_scores.get(qid) or [0.0]) if by_q_scores.get(qid) else None,
                    "arms": {a: [] for a in ARMS},
                    "note": "无 report.json",
                })
                continue
            rep = tracker.read_json(rep_path)
            cons = [c for c in (rep.get("conclusions") or []) if c.get("status") != "merged"]
            evidences = list(rep.get("evidences") or [])
            usable = _usable(cons)
            headline = sub_by_q[qid]
            # 定位 headline 对应内部结论（给乙抽 quote）
            head_con = next(
                (c for c in usable
                 if str(c.get("statement") or "").strip() == headline.strip()),
                usable[0] if usable else None,
            )
            # —— 甲 ——
            jia = []
            for c in usable[:3]:
                jia.append({
                    "id": str(c["id"]),
                    "statement": str(c["statement"]).strip(),
                    "confidence": float(c.get("confidence") or 0.0),
                    "status": str(c.get("status") or ""),
                })
            # —— 乙 ——
            if head_con is not None:
                t, n = _tokens_from_quotes(_quotes_for(head_con, evidences))
                yi_stmt = headline.strip() + _suffix(t, n)
                yi = [{
                    "id": f"YI::{qid}",
                    "statement": yi_stmt,
                    "confidence": float(head_con.get("confidence") or 0.0),
                    "status": "submitted",
                }]
            else:
                yi = [{
                    "id": f"YI::{qid}",
                    "statement": headline.strip(),
                    "confidence": float(max(by_q_scores.get(qid) or [0.0])),
                    "status": "submitted",
                }]
            # —— 丙 ——
            if len(usable) >= 2:
                c2 = usable[1]
                bing = [{
                    "id": str(c2["id"]),
                    "statement": str(c2["statement"]).strip(),
                    "confidence": float(c2.get("confidence") or 0.0),
                    "status": str(c2.get("status") or ""),
                }]
                bing_note = ""
            else:
                bing = [{
                    "id": f"BING_EMPTY::{qid}",
                    "statement": "",
                    "confidence": 0.0,
                    "status": "empty",
                }]
                bing_note = "无次高（majority/dissent < 2）"
            # —— 甲＋乙 ——
            jia_yi = []
            for c in usable[:3]:
                t, n = _tokens_from_quotes(_quotes_for(c, evidences))
                jia_yi.append({
                    "id": str(c["id"]),
                    "statement": str(c["statement"]).strip() + _suffix(t, n),
                    "confidence": float(c.get("confidence") or 0.0),
                    "status": str(c.get("status") or ""),
                })
            units.append({
                "case": case_dir.name,
                "qid": qid,
                "headline": headline,
                "max_score": max(by_q_scores.get(qid) or [0.0]) if by_q_scores.get(qid) else None,
                "score_by_cid": {k: score_by_cid[k] for k in score_by_cid
                                 if any(c.get("id") == k for c in usable[:3])},
                "arms": {"甲": jia, "乙": yi, "丙": bing, "甲＋乙": jia_yi},
                "note": bing_note,
            })
    return {
        "run_dir": str(run_dir),
        "n_units": len(units),
        "units": units,
        "construct_files": list(dict.fromkeys(tracker.files)),
    }


def _count_agreements(rows: list[dict]) -> dict[str, int]:
    c = Counter(r.get("agreement") for r in rows)
    return {k: int(c.get(k, 0)) for k in AGREE_KEYS}


def _load_a_ref(rows_path: Path) -> dict[str, int]:
    rows = [json.loads(l) for l in rows_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return _count_agreements(rows)


def _judge_arm(
    label: str,
    units: list[dict],
    gold_by: dict[tuple[str, str], str],
    client,
    model: str,
) -> dict:
    rows = []
    t0 = time.time()
    for u in units:
        key = (u["case"], u["qid"])
        gold = gold_by[key]
        if label == "A":
            ours = [{
                "id": f"SUB::{u['qid']}",
                "statement": u["headline"],
                "confidence": float(u["max_score"] or 0.0),
                "status": "submitted",
            }]
        else:
            ours = list(u["arms"][label])
        # 空句仍交给 judge_one（口径：未答）
        verdict = judge_one(client, model, gold, ours)
        rows.append({
            "case": u["case"], "qid": u["qid"],
            "agreement": verdict.get("agreement"),
            "matched": verdict.get("matched"),
            "why": verdict.get("why"),
            "error": verdict.get("error"),
            "n_ours": len([x for x in ours if str(x.get("statement") or "").strip()]),
        })
        print(f"  [{label}] {u['case'][:14]}/{u['qid']} → {verdict.get('agreement')}",
              flush=True)
    elapsed = time.time() - t0
    counts = _count_agreements(rows)
    return {"label": label, "counts": counts, "rows": rows, "elapsed_s": round(elapsed, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN))
    ap.add_argument("--a-rows", default=str(DEFAULT_A_ROWS))
    ap.add_argument("--gold-root", default=OFFICIAL,
                    help="只给判分侧用；构造入口强制 None")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--skip-judge", action="store_true",
                    help="只构造、不调 14B（自检用）")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    a_rows_path = Path(args.a_rows)
    gold_root = Path(args.gold_root)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # —— 构造（金标路径 = None）——
    tracker = FileTracker()
    pack = construct_variants(run_dir, gold_root=None, tracker=tracker)
    (out_dir / "variants.json").write_text(
        json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[构造] n_units={pack['n_units']} 读文件数={len(pack['construct_files'])}")
    print("[构造] 文件清单（判据 e）：")
    for f in pack["construct_files"]:
        print(f"  {f}")
    gold_s = str(gold_root.resolve())
    leaked = [f for f in pack["construct_files"] if f.startswith(gold_s)]
    if leaked:
        raise SystemExit(f"判据 e FAIL：构造读到金标 {leaked}")
    print("判据 e：构造未读金标＝True", flush=True)

    # —— 判据 a 可比性 ——
    a_ref = _load_a_ref(a_rows_path)
    same_denom = pack["n_units"] == 18
    # 金标文件存在性（判分侧才打开）
    gold_files = []
    gold_by: dict[tuple[str, str], str] = {}
    for u in pack["units"]:
        gp = gold_root / u["case"] / "conclusions.json"
        gold_files.append(str(gp.resolve()))
        rows = json.loads(gp.read_text(encoding="utf-8"))
        g = next((r for r in rows if str(r.get("question_id")) == u["qid"]), None)
        gold_by[(u["case"], u["qid"])] = str((g or {}).get("conclusion") or "")
    same_gold = len(set(gold_files)) == 6 and all(Path(f).is_file() for f in set(gold_files))
    same_judge = JUDGE_SYSTEM.startswith("你在做结论级语义对齐")
    # max_score 取法＝confidence.json 按 question_id 取 max（与 _submitted_conclusions 同）
    same_max = all(
        ("max_score" in u) for u in pack["units"]
    )
    ok_a = same_denom and same_gold and same_judge and same_max
    print(
        f"口径相同＝{ok_a}（分母18＝{same_denom} 金标六案＝{same_gold} "
        f"JUDGE_SYSTEM＝{same_judge} max_score取法＝{same_max}）",
        flush=True,
    )
    if not ok_a:
        raise SystemExit("判据 a FAIL：口径不同，退回")

    print(f"A 臂参照（存盘）四态：{a_ref}", flush=True)
    print(f"判据 f：甲／甲＋乙＝多行提交假想原型；若赢，落地须改提交面形状并重估官方接收面。",
          flush=True)

    if args.skip_judge:
        print("--skip-judge：跳过 14B", flush=True)
        return 0

    # —— 评判（串行）——
    gate = lock_local()
    print(f"[评判] {gate}", flush=True)
    from app.llm.model_client import ModelClientFactory

    st = settings_for(None)
    client = ModelClientFactory(st).create()

    results: dict[str, dict] = {}

    # 判据 c：A 同料连跑两次
    print("\n=== 判据 c：A 臂抖动（同料×2）===", flush=True)
    a1 = _judge_arm("A", pack["units"], gold_by, client, MODEL)
    a2 = _judge_arm("A", pack["units"], gold_by, client, MODEL)
    results["A_run1"] = a1
    results["A_run2"] = a2
    jitter = {
        k: abs(a1["counts"].get(k, 0) - a2["counts"].get(k, 0)) for k in AGREE_KEYS
    }
    jitter_agree = jitter["一致"]
    jitter_l1 = sum(jitter.values())
    print(f"A_run1={a1['counts']}  A_run2={a2['counts']}", flush=True)
    print(f"抖动：一致Δ={jitter_agree}  四态L1={jitter_l1}", flush=True)

    # 四臂
    for arm in ARMS:
        print(f"\n=== 臂 {arm} ===", flush=True)
        results[arm] = _judge_arm(arm, pack["units"], gold_by, client, MODEL)
        # 跑完释放——下一臂继续用同一 client；进程结束才真正释放 14B
        print(f"臂 {arm} 完成 elapsed={results[arm]['elapsed_s']}s counts={results[arm]['counts']}",
              flush=True)

    # —— 汇总表 ——
    def delta(arm_counts: dict) -> dict[str, int]:
        return {k: arm_counts.get(k, 0) - a_ref.get(k, 0) for k in ("一致", "部分一致", "不一致", "未答")}

    lines = []
    lines.append("======== C-60 四臂表 ========")
    lines.append(
        f"口径相同＝True｜分母={pack['n_units']}｜金标根={gold_root}｜"
        f"JUDGE_SYSTEM 指纹={JUDGE_SYSTEM[:24]}…｜max_score=confidence.json per-qid max"
    )
    lines.append(f"A参照(存盘) 一致={a_ref.get('一致',0)} 部分={a_ref.get('部分一致',0)} "
                 f"不一致={a_ref.get('不一致',0)} 未答={a_ref.get('未答',0)}")
    lines.append(f"A抖动 run1={a1['counts']} run2={a2['counts']} "
                 f"一致Δ={jitter_agree} L1={jitter_l1}")
    lines.append("")
    lines.append(f"{'臂':<8}{'一致':>4}{'部分':>4}{'不一':>4}{'未答':>4} "
                 f"{'Δ一致':>6}{'Δ坏':>6}{'抖动门槛':>8}{'判据d':>8}")
    # 坏＝不一致+未答
    a_bad = a_ref.get("不一致", 0) + a_ref.get("未答", 0)
    verdicts = {}
    for arm in ARMS:
        c = results[arm]["counts"]
        d = delta(c)
        bad = c.get("不一致", 0) + c.get("未答", 0)
        d_bad = bad - a_bad
        # 判据 d：一致≥+2 且坏项（不一致+未答）合计不增。
        # 票面「不减」若按字面会惩罚「不一致→一致」；本探针按「不增 Δ≤0」执行并回执明示。
        win_raw = (d["一致"] >= 2) and (d_bad <= 0)
        separable = not (jitter_agree > 0 and abs(d["一致"]) < jitter_agree)
        win = bool(win_raw and separable)
        verdicts[arm] = {
            "delta": d, "d_bad": d_bad, "win_raw": win_raw,
            "separable": separable, "win": win,
        }
        if win:
            tag = "赢"
        elif win_raw and not separable:
            tag = "分不开"
        else:
            tag = "未赢"
        lines.append(
            f"{arm:<8}{c.get('一致',0):>4}{c.get('部分一致',0):>4}"
            f"{c.get('不一致',0):>4}{c.get('未答',0):>4} "
            f"{d['一致']:>+6}{d_bad:>+6}{jitter_agree:>8}{tag:>8}"
        )
    lines.append("")
    lines.append(
        "判据 d＝一致净增≥2 且（不一致+未答）合计不增（Δ≤0；票面『不减』按『不增』）；"
        "判据 c＝|Δ一致| 须≥抖动一致Δ（抖动>0）。"
    )
    lines.append("判据 f＝甲／甲＋乙 为多行假想原型；落地须改提交形状并重估官方接收面。")
    # 件② 落地清单（仅赢臂）
    winners = [a for a, v in verdicts.items() if v["win"]]
    landing = []
    if winners:
        for w in winners:
            if w == "甲":
                landing.append(
                    "甲：改 app/export/official.py 提交层（每题 1 条→最多 3 条 majority/dissent）；"
                    "官方接收面形状变（多行）；需用户授权改提交契约＋配对真跑。"
                )
            elif w == "乙":
                landing.append(
                    "乙：改提交 headline 渲染（追加证据 quote 时点／数字 token，"
                    "抽法＝extract_nums＋_YEAR_IN_TEXT）；形状仍每题一条；"
                    "需授权改导出文案＋配对真跑。"
                )
            elif w == "丙":
                landing.append(
                    "丙：改选题逻辑（次高置信替代当前 headline 选取）；"
                    "形状仍每题一条；需授权改 _conclusion_text／选取键＋配对真跑。"
                )
            elif w == "甲＋乙":
                landing.append(
                    "甲＋乙：甲的多行形状＋乙的 token 后缀同时落地；"
                    "官方接收面形状变；需授权改导出契约＋配对真跑。"
                )
    else:
        landing.append("无臂过判据 d ⇒ 件② 空（不写落地改动）。")

    text = "\n".join(lines)
    print("\n" + text, flush=True)
    print("\n件② 落地清单：")
    for x in landing:
        print(" -", x)

    summary = {
        "a_ref": a_ref,
        "jitter": {"run1": a1["counts"], "run2": a2["counts"],
                   "agree_delta": jitter_agree, "l1": jitter_l1},
        "arms": {a: {"counts": results[a]["counts"], "elapsed_s": results[a]["elapsed_s"],
                     **verdicts[a]} for a in ARMS},
        "winners": winners,
        "landing": landing,
        "comparability": {
            "口径相同": True, "n_units": pack["n_units"],
            "gold_root": str(gold_root), "JUDGE_SYSTEM_head": JUDGE_SYSTEM[:40],
        },
        "construct_files": pack["construct_files"],
        "criterion_f": "甲／甲＋乙＝多行假想原型；落地须改提交形状并重估官方接收面",
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "report.txt").write_text(
        text + "\n\n件②：\n" + "\n".join(landing) + "\n", encoding="utf-8")
    for name, blob in results.items():
        (out_dir / f"rows_{name}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in blob["rows"]) + "\n",
            encoding="utf-8")
    print(f"\n[wrote] {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
