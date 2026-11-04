#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-158：加分 4.1 因果面判尺（零 LLM、零网络、零现金；只记 id／计数／比率）。

量两件事，分子分母原样出：
- 4.1.1 三档判定（直接因果／间接传导／仅相关）＋理由是否**逐行在场且非空**，
  以及主张卡四要素非空率（这条本刀不改：没生产者填卡就是 0，不许硬编）；
- 4.1.2 证据等级标注（A｜B｜C｜D＋官方名）在因果面的在场率。

两条腿＝同一批产物的两个面：
    stored    ＝改前：直接读跑次里已落盘的 causal_evidence.json（没有新字段＝基线）
    reexport  ＝改后：把同一份 report.json 装回 Dossier，走真
                ``app.export.official.export_official`` 重新导出后读同一段面
                （零模型调用；除本刀新增字段外，行内容应与 stored 逐字段同）

跑法：
    .venv/bin/python -X utf8 scripts/probe_c158_causal_face.py stored \\
        --root /tmp/s4runs/time-20261104-135401 --out /tmp/c158/stored.json
    .venv/bin/python -X utf8 scripts/probe_c158_causal_face.py reexport \\
        --root ... --out /tmp/c158/reexport.json
    .venv/bin/python -X utf8 scripts/probe_c158_causal_face.py assemble
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
ART_JSON = REPO / "artifacts" / "C158_causal_face.json"
ART_MD = REPO / "artifacts" / "C158_causal_face.md"
CLAIM_KEYS = ("intervention", "outcome", "population", "counterfactual")
VERDICTS = ("直接因果", "间接传导", "仅相关")
# 跑前写死的判据（本刀自定的闸，改判据须改代码＝留痕）
GATE_VERDICT_COVER = 1.0        # 每行都要有三档判定
GATE_REASON_COVER = 1.0         # 且理由非空
GATE_NO_INVENTION = True        # 四要素非空率不得因为「填了」而上升


def _load(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows_of(doc: Any) -> list[dict]:
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    return [r for r in (doc.get("rows") or doc.get("records") or [])
            if isinstance(r, dict)]


def score_rows(rows: list[dict]) -> dict:
    n = len(rows)

    def cover(key, non_empty=True) -> int:
        out = 0
        for r in rows:
            if key not in r:
                continue
            if non_empty and not str(r.get(key) or "").strip():
                continue
            out += 1
        return out

    claim_any = sum(1 for r in rows
                    if any(str(r.get(k) or "").strip() for k in CLAIM_KEYS))
    verdict_vals = Counter(str(r.get("因果判定") or "") for r in rows)
    return {
        "n_rows": n,
        "四要素任一非空": claim_any,
        "四要素全非空": sum(1 for r in rows
                        if all(str(r.get(k) or "").strip() for k in CLAIM_KEYS)),
        "因果判定在场": cover("因果判定"),
        "判定理由非空": cover("判定理由"),
        "升档条件非空": cover("升档条件"),
        "三档分布": {k: verdict_vals.get(k, 0) for k in VERDICTS},
        "三档之外": {k: v for k, v in verdict_vals.items()
                    if k not in VERDICTS and k},
        "证据等级在场": cover("证据等级"),
        "证据等级_官方在场": cover("证据等级_官方"),
        "等级参与加权句在场": cover("等级参与加权"),
        "degraded_reason 非空": cover("degraded_reason"),
    }


def gate_block(score: dict) -> dict:
    n = score["n_rows"]
    return {"n_rows": n,
            "verdict_cover": (round(score["因果判定在场"] / n, 4) if n else None),
            "reason_cover": (round(score["判定理由非空"] / n, 4) if n else None),
            "meets_verdict_cover": bool(n) and score["因果判定在场"] == n,
            "meets_reason_cover": bool(n) and score["判定理由非空"] == n,
            "gate_no_invention": GATE_NO_INVENTION,
            "thresholds_pre_written": {
                "verdict_cover": GATE_VERDICT_COVER,
                "reason_cover": GATE_REASON_COVER}}


def level_face(root: str) -> dict:
    """4.1.2 的另一半＝evidence.json 的等级面（本刀之前就已在场，现抄为基线）。"""
    files = sorted(glob.glob(os.path.join(root, "*", "evidence.json")))
    n = with_level = 0
    dist: Counter = Counter()
    for f in files:
        for r in _rows_of(_load(Path(f))):
            n += 1
            lvl = str(r.get("level") or "")
            off = str(r.get("level_official") or "")
            if lvl and off:
                with_level += 1
                dist[f"{lvl}（{off}）"] += 1
    return {"n_rows": n, "files": len(files),
            "等级与官方名同时在场": with_level,
            "覆盖率": (round(with_level / n, 4) if n else None),
            "分布": dict(dist.most_common())}


def stage_stored(root: str, out: str) -> dict:
    files = sorted(glob.glob(os.path.join(root, "*", "causal_evidence.json")))
    if not files:
        raise SystemExit(f"跑不到：{root} 下没有 */causal_evidence.json")
    rows: list[dict] = []
    for f in files:
        rows.extend(_rows_of(_load(Path(f))))
    doc = {"stage": "stored", "root": root, "n_files": len(files),
           "score": score_rows(rows), "gate": gate_block(score_rows(rows)),
           "level_face": level_face(root)}
    _emit(doc, out)
    return doc


def stage_reexport(root: str, out: str) -> dict:
    """同一批 report.json 装回 Dossier ⇒ 走真 export_official（零模型调用）。"""
    from app.core.evidence import Dossier
    from app.export.official import export_official

    paths = sorted(glob.glob(os.path.join(root, "*", "questions", "*",
                                           "report.json")))
    if not paths:
        raise SystemExit(f"跑不到：{root} 下没有 */questions/*/report.json")
    tmp = Path(tempfile.mkdtemp(prefix="c158_"))
    runs: list[tuple[dict, Any]] = []
    for p in paths:
        rep = _load(Path(p))
        qid = Path(p).parts[-2]
        runs.append(({"question_id": qid,
                      "question": str(rep.get("question") or "")},
                     Dossier.from_dict(rep)))
    export_official(runs, tmp)
    f = tmp / "causal_evidence.json"
    rows = _rows_of(_load(f)) if f.is_file() else []
    shutil.rmtree(tmp, ignore_errors=True)
    if not rows:
        raise SystemExit("跑不到：重导出里没有 causal_evidence 行")
    sc = score_rows(rows)
    doc = {"stage": "reexport", "root": root, "n_questions": len(runs),
           "score": sc, "gate": gate_block(sc),
           "样例三行": [
               {"conclusion_id": r.get("conclusion_id"),
                "question_id": r.get("question_id"),
                "因果判定": r.get("因果判定"),
                "判定理由": str(r.get("判定理由") or "")[:60] + "…",
                "升档条件": str(r.get("升档条件") or "")[:60] + "…",
                "证据等级": r.get("证据等级"),
                "证据等级_官方": r.get("证据等级_官方")}
               for r in rows[:3]]}
    _emit(doc, out)
    return doc


def _emit(doc: dict, out: str) -> None:
    print(json.dumps({"score": doc["score"], "gate": doc["gate"]},
                     ensure_ascii=False, indent=1))
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")


def stage_assemble() -> int:
    sp = Path("/tmp/c158/stored.json")
    rp = Path("/tmp/c158/reexport.json")
    if not (sp.is_file() and rp.is_file()):
        print("跑不到：缺 /tmp/c158/stored.json 或 reexport.json")
        return 2
    s, r = _load(sp), _load(rp)
    sg, rg = s["gate"], r["gate"]
    verdict_pass = rg["meets_verdict_cover"] and rg["meets_reason_cover"]
    claim_moved = (r["score"]["四要素任一非空"]
                   != s["score"]["四要素任一非空"])
    if verdict_pass and not claim_moved:
        verdict = "PARTIAL"
        why = ["三档判定＋理由逐行在场（4.1.1 的「区分＋说明理由」面补齐）",
               "但四要素非空率未变＝没有生产者填卡，本刀不硬编 ⇒ 4.1.1 拿不满",
               "4.1.2 等级：evidence.json 早已在场（level＋level_official，"
               "且 LEVEL_WEIGHT 进 evidence_score），本刀把它带到 causal_evidence 面"]
    elif verdict_pass and claim_moved:
        verdict = "NO"
        why = ["四要素非空率上升但本刀不该填卡＝疑似硬编，必须查"]
    else:
        verdict = "NO"
        why = [f"判定或理由未逐行在场（verdict {sg['verdict_cover']}→"
               f"{rg['verdict_cover']}）"]
    doc = {"ticket": "C-158", "official_anchor": "4.1.1／4.1.2",
           "thresholds_pre_written": {"verdict_cover": GATE_VERDICT_COVER,
                                      "reason_cover": GATE_REASON_COVER,
                                      "no_invention": GATE_NO_INVENTION},
           "root": s.get("root"), "stored": s["score"], "stored_gate": sg,
           "reexport": r["score"], "reexport_gate": rg,
           "样例三行": r.get("样例三行"),
           "level_face_already_on": {
               "说明": ("4.1.2 的等级标注在 evidence.json 早已在场（level＋"
                    "level_official），本刀只把它带到 causal_evidence 面"),
               "现量": s.get("level_face")},
           "verdict": verdict, "why": why}
    ART_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    lines = [
        "# C-158 因果面读数（脚本现抄，非手打）",
        "",
        f"- 跑产物根＝`{doc['root']}`｜判据（跑前写死）＝{doc['thresholds_pre_written']}",
        f"- 改前（stored 已落盘件）＝{s['score']}",
        f"- 改后（同产物真重导出，零模型调用）＝{r['score']}",
        f"- 闸：判定逐行在场？{rg['meets_verdict_cover']}｜理由逐行非空？"
        f"{rg['meets_reason_cover']}｜四要素非空率是否被本刀推动？{claim_moved}"
        "（必须为否＝不硬编）",
        f"- 三档覆盖：{sg['verdict_cover']} → {rg['verdict_cover']}"
        f"｜理由覆盖：{sg['reason_cover']} → {rg['reason_cover']}",
        f"- 4.1.2 等级面（evidence.json，改前就已在场）＝"
        f"{s.get('level_face')}",
        "",
        "## 样例三行（判定＋理由＋升档条件＋等级）",
    ]
    for x in r.get("样例三行") or []:
        lines.append(f"- {x['conclusion_id']}（{x['question_id']}）"
                     f"＝{x['因果判定']}｜等级 {x['证据等级']}"
                     f"（{x['证据等级_官方']}）｜理由 {x['判定理由']}"
                     f"｜升档 {x['升档条件']}")
    lines += ["", f"**裁决＝{verdict}**",
              *[f"- {w}" for w in (why if isinstance(why, list) else [str(why)])],
              "",
              "产物卫生：本件只含 id／计数／比率与截断到 60 字的字段样例，"
              "不抄案卷原文。"]
    ART_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "why": why}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["stored", "reexport", "assemble"])
    ap.add_argument("--root", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if args.stage == "assemble":
        return stage_assemble()
    if not args.root or not Path(args.root).is_dir():
        print(f"跑不到：--root 缺或不存在（{args.root!r}）")
        return 2
    if args.stage == "stored":
        stage_stored(args.root, args.out)
    else:
        stage_reexport(args.root, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
