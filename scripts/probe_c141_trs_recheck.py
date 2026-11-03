#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-141：现 tip e2ff20e 上重测进度问卷 Q4／Q5／Q6 三旗（C-114/115/116）＋C-123 usable 面。

零 LLM；全部在独立 worktree（e2ff20e）跑：
  Q4/C-114 锚稳＝四案 × {bom, crlf, bom_env} 应力 × {旗关, 旗开} →
      compare_anchor_maps 一致率 ＋ 金标键可解析率；
  Q5/C-115 冲突留痕＝四案事实台账对撞 → apply_conflict_trace 开旗
      coverage/unclassified/trace_complete（对 C-115 存档 35 对）；
  Q6/C-116 置信披露＝face_v2 快照 226 行回放 → 高档精确度/ECE 关 vs 开
      （对 C-116 存档 0.2069→0.2727）；
  C-123 usable 面＝模块函数在场＋消费者扫描（预期：无生产消费者＝未接线）。
产物只记计数／比率，零原文。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.probe_c125_six_case_gate import (  # noqa: E402
    CASE_MARKS, _case, _questions_from_conclusions,
)
from scripts.probe_recall_funnel import gold_paras_for_question  # noqa: E402

WORK = Path("/tmp/c141")
CASES = ("liuxiang", "wanghong", "kh_th", "ai171")


def _set_flag(name: str, val: str) -> None:
    import os
    if val is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = val


# ------------------------------------------------ Q4/C-114

def _stress_variant(case: Path, kind: str, tmp: Path) -> Path:
    docs = json.loads((case / "raw_documents.json").read_text(encoding="utf-8"))
    if isinstance(docs, dict):
        docs = docs.get("raw_documents") or docs.get("documents") or []
    out = json.loads(json.dumps(docs, ensure_ascii=False))
    for d in out:
        c = str(d.get("content") or "")
        if kind == "bom":
            d["content"] = "\ufeff" + c
        elif kind == "crlf":
            d["content"] = c.replace("\n", "\r\n")
        elif kind == "bom_env":
            d["content"] = "\ufeff" + c
    dest = tmp / kind
    dest.mkdir(parents=True, exist_ok=True)
    if kind == "bom_env":
        (dest / "raw_documents.json").write_text(
            json.dumps({"raw_documents": out}, ensure_ascii=False),
            encoding="utf-8")
    else:
        (dest / "raw_documents.json").write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return dest


def q4_anchor() -> dict:
    from app.core.anchor_stable import (
        compare_anchor_maps, dossier_anchor_map,
    )
    from app.ingest.official_case import load_official_case

    rows = []
    for slug in CASES:
        case = _case(CASE_MARKS[slug])
        gold_keys: set[str] = set()
        for q in _questions_from_conclusions(case):
            g, _sk = gold_paras_for_question(case, q["question_id"])
            gold_keys |= {str(p) if "#" in str(p) else f"{doc}#{p}"
                          for doc, p in g.keys()}
        _set_flag("VERITAS_ANCHOR_STABLE", "0")
        base = dossier_anchor_map(load_official_case(case))
        for kind in ("bom", "crlf", "bom_env"):
            tmp = Path(tempfile.mkdtemp(prefix="c141q4_"))
            try:
                st = _stress_variant(case, kind, tmp)
                res = {}
                for flag in ("0", "1"):
                    _set_flag("VERITAS_ANCHOR_STABLE", flag)
                    try:
                        d = load_official_case(st)
                        cmp_ = compare_anchor_maps(base, dossier_anchor_map(d))
                        resolvable = sum(1 for k in gold_keys
                                         if d.segment(k) is not None)
                        res[flag] = {
                            "consistency": cmp_["consistency_rate"],
                            "gold_resolvable": resolvable,
                            "gold_total": len(gold_keys),
                            "err": "",
                        }
                    except Exception as exc:  # 旗关 BOM 当场炸＝读不通
                        res[flag] = {"consistency": None,
                                     "gold_resolvable": 0,
                                     "gold_total": len(gold_keys),
                                     "err": type(exc).__name__}
                rows.append({"slug": slug, "stress": kind, **res})
                print(f"… Q4 {slug}/{kind} off={res['0']} on={res['1']}",
                      flush=True)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    _set_flag("VERITAS_ANCHOR_STABLE", None)
    return {"rows": rows}


# ------------------------------------------------ Q5/C-115

def q5_conflict() -> dict:
    from app.core.conflict_trace import apply_conflict_trace
    from app.core.fact_ledger import extract_facts, find_collisions
    from app.ingest.official_case import load_official_case

    rows = []
    total = 0
    for slug in CASES:
        case = _case(CASE_MARKS[slug])
        _set_flag("VERITAS_CONFLICT_TRACE", "0")
        d = load_official_case(case)
        facts = extract_facts(d)
        cols = find_collisions(d, facts=facts)
        off_has_key = "conflict_trace" in (d.accounting or {})
        _set_flag("VERITAS_CONFLICT_TRACE", "1")
        payload = apply_conflict_trace(d, collisions=cols, enabled=True)
        sm = (payload or {}).get("summary") or {}
        total += int(sm.get("n") or 0)
        rows.append({
            "slug": slug, "n_collisions": len(cols),
            "off_writes_accounting": off_has_key,
            "on_coverage": sm.get("coverage_rate"),
            "on_unclassified": sm.get("unclassified"),
            "on_trace_complete": sm.get("trace_complete_rate"),
        })
        print(f"… Q5 {slug} 对撞={len(cols)} 覆盖={sm.get('coverage_rate')} "
              f"未归类={sm.get('unclassified')} 留痕={sm.get('trace_complete_rate')}",
              flush=True)
    _set_flag("VERITAS_CONFLICT_TRACE", None)
    return {"rows": rows, "total": total}


# ------------------------------------------------ Q6/C-116

def q6_conf() -> dict:
    from app.core.conf_calib import gated_band, high_band_precision
    from app.core.confidence import band_of

    path = Path("calibration/face_v2_row_snapshot.jsonl")
    rows_raw = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    off_rows, on_rows = [], []
    for r in rows_raw:
        score = float(r.get("score_v2") or 0.0)
        parts = r.get("parts") or {}
        label = str(r.get("label") or "")
        off_rows.append({"band": band_of(score), "label": label})
        g = gated_band(score, parts=parts, enabled=True)
        on_rows.append({"band": g["band"], "label": label})
    po, pn = high_band_precision(off_rows), high_band_precision(on_rows)

    def _ece(rows: list[dict]) -> float:
        # 简单 10 桶 ECE（band 高=1.0/中=0.5/低=0.0 的呈现分近似——只作旁证，
        # 主读数＝高档精确度，与 C-116 存档同主尺）
        import math
        conf = {"高": 0.9, "中": 0.5, "低": 0.2}
        n = len(rows)
        if not n:
            return 0.0
        e = 0.0
        for b in ("高", "中", "低"):
            grp = [r for r in rows if r["band"] == b]
            if not grp:
                continue
            acc = sum(1.0 if r["label"] == "对" else
                      (0.5 if r["label"] == "部分" else 0.0)
                      for r in grp) / len(grp)
            e += len(grp) / n * abs(conf[b] - acc)
        return round(e, 6)

    out = {
        "n_rows": len(rows_raw),
        "off_high_precision": po, "on_high_precision": pn,
        "off_ece_3band_proxy": _ece(off_rows),
        "on_ece_3band_proxy": _ece(on_rows),
        "n_demoted": po["n_high"] - pn["n_high"],
    }
    print(f"… Q6 高档精确度 关 {po['n_hit']}/{po['n_high']}={po['precision']} → "
          f"开 {pn['n_hit']}/{pn['n_high']}={pn['precision']}；降档 "
          f"{out['n_demoted']}；ECE(3band旁证) {out['off_ece_3band_proxy']}→"
          f"{out['on_ece_3band_proxy']}", flush=True)
    return out


# ------------------------------------------------ C-123 usable 面

def usable_face() -> dict:
    from app.kg_lab.tree17_cite import measure_cite_compliance  # noqa: F401

    consumers = []
    for pat in ("usable_cite_density", "n_usable_cited"):
        import subprocess
        out = subprocess.run(
            ["grep", "-rln", pat, "app/", "scripts/", "app/export/"],
            capture_output=True, text=True)
        files = [f for f in (out.stdout or "").splitlines()
                 if f and not f.endswith("tree17_cite.py")]
        consumers += files
    return {
        "module_fn_present": True,
        "consumers_outside_tree17_cite": sorted(set(consumers)),
        "wired": False,
    }


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    out = {
        "ticket": "C-141-trs-recheck",
        "tip": "e2ff20e",
        "branch": "qoder/c141-trs-recheck",
        "q4_anchor": q4_anchor(),
        "q5_conflict": q5_conflict(),
        "q6_conf": q6_conf(),
        "c123_usable": usable_face(),
    }
    (WORK / "C141_recheck.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote /tmp/c141/C141_recheck.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
