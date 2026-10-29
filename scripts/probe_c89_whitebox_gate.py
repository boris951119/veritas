#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-89：装箱前白箱三态闸只量（默认关／生产零 diff）。

挂点：BM25／扩写召回出候选之后 → gate → 仅 allow 进 `pack_material` 分表。
借鉴唯稳律：主机侧硬闸、拒标＝review 通道；非因果发现、不接 DSH。

对照臂：
  A0 现产装箱
  C85K60 / C85K180 / C86 ＝读已有 summary（若路径在）
  GATE ＝以 C-86 候选为召回池（六案双边扩写召回最近产物）+ 闸后装箱
  GATE_C85 ＝以 C-85-K60 候选＋审查分，闸后只留 allow 再装

读数：L2／lost／池内金标／独有金标（相对 K180／C86）／拒标率／误杀金标／墙钟。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c89_whitebox_gate.py \\
      --run-dir /tmp/six2 --out-dir /tmp/c89_gate \\
      --c86-dir /tmp/c86_expand --c85-dir /tmp/c85_auto --c85-k180-dir /tmp/c85_k180 \\
      --tags /tmp/c87b_constrain/tags_repaired.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material  # noqa: E402
from scripts.c89_whitebox_gate import gate_segment  # noqa: E402
from scripts.probe_c62_rerank_arms import _pack_with_scores  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _fuse, _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

TARGET_A0 = 48
TARGET_DENOM = 105
TARGET_L2 = 54


def _load_summary_arm(path: Path, arm_key: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    blob = json.loads(path.read_text(encoding="utf-8"))
    summary = blob.get("summary") or blob
    arm = summary.get(arm_key) or summary.get("B") or summary.get("C")
    if not arm:
        return None
    return {
        "l2_hits": arm.get("l2_hits"),
        "n_selected": arm.get("n_selected"),
        "lost_n": summary.get("lost_n"),
        "gained_n": summary.get("gained_n"),
        "source": str(path),
        "arm_key": arm_key,
    }


def _apply_gate_to_scores(
    *,
    question: str,
    text_of: dict[str, str],
    candidate_ids: list[str],
    base_scores: dict[str, float],
    tags: dict[str, dict] | None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """候选上跑闸：非 allow 分置 0；返回新分表＋账。"""
    stats = Counter()
    reasons = Counter()
    gated: dict[str, str] = {}
    gold_notes: list[dict] = []  # filled by caller if needed

    out = {str(k): float(v) for k, v in base_scores.items()}
    # 非候选保持原分？票意＝召回后闸。只闸候选：候选外分清零，避免「闸外走私」。
    cand_set = set(candidate_ids)
    for sid in list(out.keys()):
        if sid not in cand_set:
            out[sid] = 0.0

    for sid in candidate_ids:
        rec = (tags or {}).get(sid) or {}
        v = gate_segment(
            text_of.get(sid, ""),
            question,
            path=rec.get("p"),
            tag_ents=list(rec.get("e") or []) or None,
            tag_src=rec.get("src"),
        )
        gated[sid] = v.state
        stats[v.state] += 1
        reasons[f"{v.state}:{v.reason}"] += 1
        if v.state != "allow":
            out[sid] = 0.0
        else:
            # 保留原候选分；若原分为 0 给极小正分以免全灭
            if out.get(sid, 0.0) <= 0:
                out[sid] = 1.0
    return out, {
        "counts": dict(stats),
        "reasons": dict(reasons),
        "n_cand": len(candidate_ids),
        "n_allow": int(stats.get("allow", 0)),
        "reject_rate": round(
            1.0 - (stats.get("allow", 0) / max(1, len(candidate_ids))), 4),
        "gated": gated,
    }


def measure_jobs(
    jobs: list[dict],
    gold_dir: Path,
    *,
    tags: dict[str, dict] | None,
    tags_case_substr: str = "吉隆",
    use_llm_fuse: bool,
    arm_key: str,
) -> dict[str, Any]:
    t0 = time.time()
    rows = []
    lost_n = gained_n = 0
    tot = Counter()
    gate_tot = Counter()
    gold_in_pool = gold_allow = gold_killed = 0
    reason_tot = Counter()

    for job in jobs:
        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        text_of = {
            seg.id: (seg.text or "")
            for src in dossier.sources for seg in src.segments
        }
        budget = int(job["budget"])
        gold, denom = _gold_keys(gold_dir, job["case"], job["qid"])
        if denom == 0:
            continue

        bm25 = {str(k): float(v) for k, v in job["bm25_scores"].items()}
        ids = list(job["ids"])
        if use_llm_fuse and job.get("llm_scores"):
            id_scores = {cid: float(s) for cid, s in zip(ids, job["llm_scores"])}
            base = _fuse(bm25, id_scores, use_bm25=True)
        else:
            base = dict(bm25)
            # 候选外已在 gate 里清零；候选内用 bm25

        # 标签仅用于匹配案（避免 doc_001 跨案串味）
        job_tags = tags if (tags and tags_case_substr in job["case"]) else None
        scores, gmeta = _apply_gate_to_scores(
            question=job["query"],
            text_of=text_of,
            candidate_ids=ids,
            base_scores=base,
            tags=job_tags,
        )
        for k, v in (gmeta.get("counts") or {}).items():
            gate_tot[k] += v
        for k, v in (gmeta.get("reasons") or {}).items():
            reason_tot[k] += v

        # 池内金标／allow／误杀
        loc_pool = selected_locs(dossier, set(ids))
        gold_pool = gold & loc_pool
        gold_in_pool += len(gold_pool)
        allow_ids = {sid for sid, st in gmeta["gated"].items() if st == "allow"}
        loc_allow = selected_locs(dossier, allow_ids)
        gold_allow_set = gold & loc_allow
        gold_allow += len(gold_allow_set)
        killed = gold_pool - gold_allow_set
        gold_killed += len(killed)

        p0 = pack_material(dossier, budget_chars=budget)
        sel_a = {str(x) for x in (p0.get("selected") or [])}
        loc_a = selected_locs(dossier, sel_a)
        hits_a = l2_hits(gold, loc_a)

        sel = _pack_with_scores(dossier, budget, scores)
        loc = selected_locs(dossier, sel)
        hits = l2_hits(gold, loc)
        lost = (gold & loc_a) - loc
        gained = (gold & loc) - loc_a
        lost_n += len(lost)
        gained_n += len(gained)

        rows.append({
            "case": job["case"], "qid": job["qid"], "denom": denom,
            "a0_hits": hits_a, "a0_n": len(sel_a),
            f"{arm_key}_hits": hits, f"{arm_key}_n": len(sel),
            "lost": len(lost), "gained": len(gained),
            "n_cand": gmeta["n_cand"],
            "n_allow": gmeta["n_allow"],
            "reject_rate": gmeta["reject_rate"],
            "gold_in_pool": len(gold_pool),
            "gold_allow": len(gold_allow_set),
            "gold_killed": len(killed),
            "gate_counts": gmeta["counts"],
        })
        tot["denom"] += denom
        tot["a0_hits"] += hits_a
        tot["a0_n"] += len(sel_a)
        tot["arm_hits"] += hits
        tot["arm_n"] += len(sel)

    elapsed = round(time.time() - t0, 2)
    return {
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "elapsed_s": elapsed,
        "a0": {
            "l2_hits": int(tot["a0_hits"]),
            "n_selected": int(tot["a0_n"]),
            "recall": round(tot["a0_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        arm_key: {
            "l2_hits": int(tot["arm_hits"]),
            "n_selected": int(tot["arm_n"]),
            "recall": round(tot["arm_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        "lost_n": lost_n,
        "gained_n": gained_n,
        "pool_gold": gold_in_pool,
        "allow_gold": gold_allow,
        "gold_killed": gold_killed,
        "gate_counts": dict(gate_tot),
        "gate_reasons_top": reason_tot.most_common(12),
        "reject_rate_cand": round(
            1.0 - (gate_tot.get("allow", 0) / max(1, sum(gate_tot.values()))), 4),
        "rows": rows,
    }


def judge(summary: dict, arm_key: str) -> dict:
    a_ok = summary["a0"]["l2_hits"] == TARGET_A0 and summary["denom"] == TARGET_DENOM
    arm = summary[arm_key]
    b_ok = (
        arm["l2_hits"] >= TARGET_L2
        and summary["lost_n"] == 0
        and summary["denom"] == TARGET_DENOM
    )
    return {
        "a": {"ok": a_ok, "got": f"{summary['a0']['l2_hits']}/{summary['denom']}"},
        "b": {
            "ok": b_ok,
            "got": f"{arm['l2_hits']}/{summary['denom']}",
            "lost_n": summary["lost_n"],
            "gained_n": summary["gained_n"],
        },
        "escape": not b_ok,
    }


def _jobs_from_probe_dir(
    probe_dir: Path, *, scores_name: str | None = None,
) -> list[dict]:
    jobs = json.loads((probe_dir / "score_input.json").read_text(encoding="utf-8"))
    llm = None
    if scores_name and (probe_dir / scores_name).is_file():
        llm = json.loads((probe_dir / scores_name).read_text(encoding="utf-8"))
    out = []
    for job in jobs:
        key = f"{job['case']}::{job['qid']}"
        row = dict(job)
        if llm and key in llm:
            sc = llm[key]
            if isinstance(sc, list):
                row["llm_scores"] = sc
            elif isinstance(sc, dict):
                row["llm_scores"] = [float(sc.get(i, 0.0)) for i in job["ids"]]
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default="/tmp/six2",
                    help="对照产物根（本探针主路径不读；保留 CLI 兼容）")
    ap.add_argument("--out-dir", default="/tmp/c89_gate")
    ap.add_argument("--gold-dir", default="")
    ap.add_argument("--c86-dir", default="/tmp/c86_expand")
    ap.add_argument("--c85-dir", default="/tmp/c85_auto")
    ap.add_argument("--c85-k180-dir", default="/tmp/c85_k180")
    ap.add_argument("--tags", default="/tmp/c87b_constrain/tags_repaired.json",
                    help="可选；有则启用路径／实体拒标规则（吉隆覆盖）")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gold_dir = Path(args.gold_dir) if args.gold_dir else DEFAULT_GOLD

    # 自检闸
    from scripts.c89_whitebox_gate import self_check
    self_check()

    tags = None
    tag_path = Path(args.tags) if args.tags else None
    if tag_path and tag_path.is_file():
        tags = json.loads(tag_path.read_text(encoding="utf-8"))
        print(f"载入 tags {len(tags)} ← {tag_path}", flush=True)
    else:
        print("无 tags：闸仅走正文规则（六案仍可跑）", flush=True)

    # 对照读数（已有 summary）
    contrasts = {
        "C85K60_C": _load_summary_arm(
            Path(args.c85_dir) / "summary_c.json", "C"),
        "C85K180_C": _load_summary_arm(
            Path(args.c85_k180_dir) / "summary_c.json", "C"),
        "C86_B": _load_summary_arm(
            Path(args.c86_dir) / "summary_b.json", "B"),
    }
    print("======== 对照臂（已有产物）========", flush=True)
    for name, row in contrasts.items():
        if row:
            print(
                f"  {name}: L2={row['l2_hits']} lost={row.get('lost_n')} "
                f"gained={row.get('gained_n')} ← {row['source']}",
                flush=True,
            )
        else:
            print(f"  {name}: 缺产物", flush=True)

    payload: dict[str, Any] = {
        "protocol": "C-89",
        "note": "借鉴唯稳律：装箱前三态闸／拒标通道；非因果发现；默认关、生产零 diff",
        "contrasts": contrasts,
        "tags_loaded": bool(tags),
    }

    # 臂 GATE：C-86 候选 + 闸（BM25 分，不用再开审查模型）
    c86 = Path(args.c86_dir)
    if not (c86 / "score_input.json").is_file():
        raise SystemExit(f"缺 C-86 score_input：{c86}")
    jobs_c86 = _jobs_from_probe_dir(c86, scores_name=None)
    print("\n======== GATE＝C86候选+白箱闸（BM25分）========", flush=True)
    sum_gate = measure_jobs(
        jobs_c86, gold_dir, tags=tags, use_llm_fuse=False, arm_key="GATE")
    j_gate = judge(sum_gate, "GATE")
    payload["GATE"] = {"summary": sum_gate, "judge": j_gate}
    print(
        f"GATE: A0={sum_gate['a0']['l2_hits']}/{sum_gate['denom']} "
        f"臂={sum_gate['GATE']['l2_hits']}/{sum_gate['denom']} "
        f"lost={sum_gate['lost_n']} gained={sum_gate['gained_n']} "
        f"池金={sum_gate['pool_gold']} allow金={sum_gate['allow_gold']} "
        f"误杀金={sum_gate['gold_killed']} 拒标率={sum_gate['reject_rate_cand']} "
        f"耗时={sum_gate['elapsed_s']}s "
        f"{'过线' if j_gate['b']['ok'] else '逃逸'}",
        flush=True,
    )
    print(f"  闸计数={sum_gate['gate_counts']}", flush=True)
    print(f"  原因Top={sum_gate['gate_reasons_top'][:8]}", flush=True)

    # 臂 GATE_C85：C-85 候选+审查分 fuse + 闸
    c85 = Path(args.c85_dir)
    if (c85 / "score_input.json").is_file() and (c85 / "llm_scores_c.json").is_file():
        jobs_c85 = _jobs_from_probe_dir(c85, scores_name="llm_scores_c.json")
        print("\n======== GATE_C85＝C85候选+审查分+白箱闸 ========", flush=True)
        sum_c85 = measure_jobs(
            jobs_c85, gold_dir, tags=tags, use_llm_fuse=True, arm_key="GATE_C85")
        j_c85 = judge(sum_c85, "GATE_C85")
        payload["GATE_C85"] = {"summary": sum_c85, "judge": j_c85}
        print(
            f"GATE_C85: A0={sum_c85['a0']['l2_hits']}/{sum_c85['denom']} "
            f"臂={sum_c85['GATE_C85']['l2_hits']}/{sum_c85['denom']} "
            f"lost={sum_c85['lost_n']} gained={sum_c85['gained_n']} "
            f"池金={sum_c85['pool_gold']} allow金={sum_c85['allow_gold']} "
            f"误杀金={sum_c85['gold_killed']} 拒标率={sum_c85['reject_rate_cand']} "
            f"耗时={sum_c85['elapsed_s']}s "
            f"{'过线' if j_c85['b']['ok'] else '逃逸'}",
            flush=True,
        )
        print(f"  闸计数={sum_c85['gate_counts']}", flush=True)

    # 独有金标相对对照（用池金粗比；装箱后 L2 另见上）
    def _unique_vs(name: str, other_l2: int | None) -> None:
        if other_l2 is None:
            return
        mine = sum_gate["GATE"]["l2_hits"]
        print(f"  相对{name} L2 Δ={mine - other_l2:+d}", flush=True)

    print("\n======== 相对对照 ΔL2 ========", flush=True)
    if contrasts.get("C85K60_C"):
        _unique_vs("C85K60_C", contrasts["C85K60_C"]["l2_hits"])
    if contrasts.get("C85K180_C"):
        _unique_vs("C85K180_C", contrasts["C85K180_C"]["l2_hits"])
    if contrasts.get("C86_B"):
        _unique_vs("C86_B", contrasts["C86_B"]["l2_hits"])

    (out_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n落盘 {out_dir / 'summary.json'}", flush=True)
    print(
        f"app diff：本票只加 scripts/（c89_whitebox_gate.py + probe_c89）；"
        f"生产默认不动。",
        flush=True,
    )
    return 0 if (j_gate["b"]["ok"] or (
        "GATE_C85" in payload and payload["GATE_C85"]["judge"]["b"]["ok"]
    )) else 1


if __name__ == "__main__":
    raise SystemExit(main())
