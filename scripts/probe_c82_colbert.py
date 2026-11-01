#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-82：ColBERT／late-interaction（MaxSim）只量 L2＋纯度——生产零 diff。

形态对齐 C-62：BM25 前 120 段候选 → ColBERT MaxSim 重打分 → 同一 pack_material
（monkeypatch rank_segments）。本脚本**不 import torch**；打分由
``scripts/score_c82_colbert_pylate.py`` 在 ``/tmp/venv_rerank`` 侧完成。

臂：
  A0＝现行 BM25 密度装箱（必须 48/105）
  CB＝候选段 ColBERT 分、非候选分＝0 后再装箱

判据：
  a  A0＝48/105
  b  CB：L2≥54 且相对 A0 金标 lost＝0（与 C-62 同门槛；过线才谈合入）
  另披露纯度；不过线⇒逃逸、默认不动

用法：
  # 1) 构造候选（主 .venv）
  PYTHONPATH=. .venv/bin/python scripts/probe_c82_colbert.py \\
      --run-dir /tmp/six2 --prepare --out-dir /tmp/c82_colbert

  # 2) 打分（venv_rerank＋已装 pylate／jina-colbert-v2）
  /tmp/venv_rerank/bin/python scripts/score_c82_colbert_pylate.py \\
      --out-dir /tmp/c82_colbert

  # 3) 量尺
  PYTHONPATH=. .venv/bin/python scripts/probe_c82_colbert.py \\
      --run-dir /tmp/six2 --run --out-dir /tmp/c82_colbert
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
from scripts.probe_c62_rerank_arms import (  # noqa: E402
    CAND_N,
    _pack_with_scores,
    build_candidates,
    construct_jobs as c62_construct,
    scores_from_rerank_on_candidates,
)
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD,
    gold_paras_for_question,
)

TARGET_A0 = 48
TARGET_DENOM = 105
TARGET_CB_L2 = 54


def _gold_keys(gold_dir: Path, case: str, qid: str):
    gold, _sk = gold_paras_for_question(gold_dir / case, qid)
    return set(gold.keys()), len(gold)


def prepare(run_dir: Path, out_dir: Path) -> dict:
    """构造候选＋写出 score 输入（全文）；金标不读。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    pack = c62_construct(run_dir, gold_root=None, out_dir=out_dir)
    score_inp: dict[str, Any] = {}
    for job in pack["jobs"]:
        key = f"{job['case']}::{job['qid']}"
        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        blob = json.loads(Path(job["cand_path"]).read_text(encoding="utf-8"))
        cands = blob["candidates"]
        text_of = {
            seg.id: (seg.text or "")
            for src in dossier.sources for seg in src.segments
        }
        score_inp[key] = {
            "case": job["case"],
            "qid": job["qid"],
            "query": job["query"],
            "ids": [c["id"] for c in cands],
            "texts": [text_of.get(c["id"], "") for c in cands],
            "sha": job["sha"],
            "budget": job["budget"],
            "report": job["report"],
        }
    inp_path = out_dir / "score_input.json"
    inp_path.write_text(
        json.dumps(score_inp, ensure_ascii=False), encoding="utf-8")
    meta = {
        "n_questions": pack["n_questions"],
        "cand_n": CAND_N,
        "score_input": str(inp_path),
        "run_dir": str(run_dir.resolve()),
    }
    (out_dir / "prepare_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("======== C-82 --prepare ========")
    print(f"题数＝{meta['n_questions']}｜候选/题＝{CAND_N}")
    print(f"score_input＝{inp_path}")
    print("下一步：/tmp/venv_rerank/bin/python scripts/score_c82_colbert_pylate.py "
          f"--out-dir {out_dir}")
    return meta


def run_measure(out_dir: Path, gold_dir: Path) -> dict[str, Any]:
    scores_path = out_dir / "colbert_scores.json"
    if not scores_path.is_file():
        raise SystemExit(f"缺打分缓存：{scores_path}（先跑 score_c82_colbert_pylate.py）")
    score_inp = json.loads((out_dir / "score_input.json").read_text(encoding="utf-8"))
    cb_scores_all = json.loads(scores_path.read_text(encoding="utf-8"))

    tot = Counter()
    rows = []
    lost_n = gained_n = 0

    for key, job in score_inp.items():
        case, qid = job["case"], job["qid"]
        dossier = Dossier.from_dict(
            json.loads(Path(job["report"]).read_text(encoding="utf-8")))
        budget = int(job["budget"])
        gold, denom = _gold_keys(gold_dir, case, qid)
        if denom == 0:
            continue

        # A0
        p0 = pack_material(dossier, budget_chars=budget)
        sel_a = {str(x) for x in (p0.get("selected") or [])}
        loc_a = selected_locs(dossier, sel_a)
        hits_a = l2_hits(gold, loc_a)

        # CB
        cand_ids = list(job["ids"])
        raw_sc = cb_scores_all.get(key)
        if not raw_sc or len(raw_sc) != len(cand_ids):
            raise SystemExit(f"打分长度不齐：{key}")
        # bm25 全表（只为拿到全集键）
        _, _, bm25_scores, _ = build_candidates(dossier, n=CAND_N)
        cands = [{"id": i} for i in cand_ids]
        fused = scores_from_rerank_on_candidates(bm25_scores, cands, raw_sc)
        sel_c = _pack_with_scores(dossier, budget, fused)
        loc_c = selected_locs(dossier, sel_c)
        hits_c = l2_hits(gold, loc_c)

        lost = (gold & loc_a) - loc_c
        gained = (gold & loc_c) - loc_a
        lost_n += len(lost)
        gained_n += len(gained)

        rows.append({
            "case": case, "qid": qid, "denom": denom,
            "a0_hits": hits_a, "a0_n": len(sel_a),
            "cb_hits": hits_c, "cb_n": len(sel_c),
            "lost": len(lost), "gained": len(gained),
        })
        tot["denom"] += denom
        tot["a0_hits"] += hits_a
        tot["a0_n"] += len(sel_a)
        tot["cb_hits"] += hits_c
        tot["cb_n"] += len(sel_c)

    summary = {
        "n_questions": len(rows),
        "denom": int(tot["denom"]),
        "a0": {
            "l2_hits": int(tot["a0_hits"]),
            "n_selected": int(tot["a0_n"]),
            "precision": round(tot["a0_hits"] / tot["a0_n"], 4) if tot["a0_n"] else 0,
            "recall": round(tot["a0_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        "cb": {
            "l2_hits": int(tot["cb_hits"]),
            "n_selected": int(tot["cb_n"]),
            "precision": round(tot["cb_hits"] / tot["cb_n"], 4) if tot["cb_n"] else 0,
            "recall": round(tot["cb_hits"] / tot["denom"], 4) if tot["denom"] else 0,
        },
        "lost_n": lost_n,
        "gained_n": gained_n,
        "rows": rows,
    }
    return summary


def judge(summary: dict) -> dict[str, Any]:
    a_ok = (
        summary["a0"]["l2_hits"] == TARGET_A0
        and summary["denom"] == TARGET_DENOM
    )
    b_ok = (
        summary["cb"]["l2_hits"] >= TARGET_CB_L2
        and summary["lost_n"] == 0
        and summary["denom"] == TARGET_DENOM
    )
    return {
        "a": {"ok": a_ok, "got": f"{summary['a0']['l2_hits']}/{summary['denom']}"},
        "b": {
            "ok": b_ok,
            "got_l2": f"{summary['cb']['l2_hits']}/{summary['denom']}",
            "want_l2": f">={TARGET_CB_L2}",
            "lost_n": summary["lost_n"],
            "gained_n": summary["gained_n"],
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", default="/tmp/c82_colbert")
    ap.add_argument("--gold-dir", default=str(DEFAULT_GOLD))
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    run_dir = Path(args.run_dir)

    if args.prepare:
        prepare(run_dir, out_dir)
        return 0

    if args.dry_run or not args.run:
        print("======== C-82 --dry-run ========")
        print("将：A0 vs ColBERT MaxSim（jina-colbert-v2，候选120）")
        print("判据 a＝A0 48/105；b＝CB L2≥54 且 lost=0")
        print("本 dry-run 不读金标、不打分、不装箱。")
        print(f"准备：--prepare --out-dir {out_dir}")
        return 0

    summary = run_measure(out_dir, Path(args.gold_dir))
    print("======== C-82 到达面 ========")
    print(f"题数＝{summary['n_questions']}｜分母＝{summary['denom']}")
    for name in ("a0", "cb"):
        r = summary[name]
        print(
            f"  {name.upper():3}｜L2 {r['l2_hits']}/{summary['denom']} "
            f"（{r['recall']:.3f}）｜装入 {r['n_selected']}｜纯度 {r['precision']:.4f}"
        )
    print(f"相对 A0：lost＝{summary['lost_n']}｜gained＝{summary['gained_n']}")
    j = judge(summary)
    print("判据 a", "✅" if j["a"]["ok"] else "❌", j["a"])
    print("判据 b", "✅" if j["b"]["ok"] else "❌（逃逸）", j["b"])
    (out_dir / "summary.json").write_text(
        json.dumps({"summary": summary, "judge": j},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"落盘 {out_dir / 'summary.json'}")
    return 0 if j["a"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
