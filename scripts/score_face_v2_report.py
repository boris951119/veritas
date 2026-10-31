#!/usr/bin/env python3
"""C-36：合式改前／改后 ECE＋AUC＋五箱＋高档读数（零 LLM、只读）。

同一份代码分别打开 v1（连乘）与 v2（加权和＋硬门）重算——禁止拿
labels_self 里存的旧 score 当改前基线（当前代码只能逐位复现约 92/226）。

每个打印的数字后面带复放命令。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from app.core.evidence import Dossier  # noqa: E402
from app.core.confidence import (  # noqa: E402
    conclude_confidence,
    _AGREEMENT_FLOOR,
    _AGG,
    aggregate,
    apply_hard_gates,
    chain_factor_of,
)
from scripts.calibrate_confidence import (  # noqa: E402
    BIN_EDGES,
    bin_index,
    label_accuracy,
    load_labeled_rows,
)

# 最近一次 load_joined_rows 的 conclusion_id 一致性旁报（连接键不是 id）
LAST_JOIN_SIDE: dict[str, Any] = {}

def ece_of(scores: list[float], labels: list[str]) -> float:
    n = len(scores)
    if n == 0:
        return float("nan")
    members: list[list[tuple[float, float]]] = [[] for _ in BIN_EDGES]
    for s, y in zip(scores, labels):
        members[bin_index(s)].append((s, label_accuracy(y)))
    ece = 0.0
    for xs in members:
        bn = len(xs)
        if bn == 0:
            continue
        acc = sum(a for _, a in xs) / bn
        conf = sum(s for s, _ in xs) / bn
        ece += (bn / n) * abs(acc - conf)
    return ece


def five_bins(scores: list[float], labels: list[str]) -> list[dict[str, Any]]:
    members: list[list[tuple[float, float]]] = [[] for _ in BIN_EDGES]
    for s, y in zip(scores, labels):
        members[bin_index(s)].append((s, label_accuracy(y)))
    out = []
    for (name, lo, hi), xs in zip(BIN_EDGES, members):
        bn = len(xs)
        entry: dict[str, Any] = {"bin": name, "n": bn, "lo": lo, "hi": hi}
        if bn == 0:
            entry.update(acc=None, conf=None)
        else:
            entry["acc"] = round(sum(a for _, a in xs) / bn, 6)
            entry["conf"] = round(sum(s for s, _ in xs) / bn, 6)
        out.append(entry)
    return out



def statement_sha8(statement: str) -> str:
    return hashlib.sha256((statement or "").encode("utf-8")).hexdigest()[:8]


def _agreement_factor(agreement: float) -> float:
    return _AGREEMENT_FLOOR + (1 - _AGREEMENT_FLOOR) * float(agreement)


def score_v1_of_parts(parts: dict) -> float:
    """v1 连乘（本脚本内对照实现；生产已切 v2）。"""
    st = float(parts.get("strength") or 0.0)
    cov = float(parts.get("coverage") or 0.0)
    agr = float(parts.get("agreement") or 0.0)
    ch = parts.get("chain")
    ch_num = None if ch is None else float(ch)
    af = _agreement_factor(agr)
    cf = chain_factor_of(ch_num)
    return round(min(1.0, st * cov * af * cf), 4)


def score_v2_of_parts(parts: dict) -> float:
    """v2 加权和（硬门在 226 行产物上实测零触发；此处按 parts.gates／n_evidence 重放）。"""
    st = float(parts.get("strength") or 0.0)
    cov = float(parts.get("coverage") or 0.0)
    agr = float(parts.get("agreement") or 0.0)
    ch = parts.get("chain")
    ch_num = None if ch is None else float(ch)
    af = _agreement_factor(agr)
    # 第四维：原值；None → 0.75（_CHAIN_UNKNOWN 数值，不经 floor）
    from app.core.confidence import _CHAIN_UNKNOWN
    ch_for = _CHAIN_UNKNOWN if ch_num is None else ch_num
    raw = aggregate(st, cov, af, ch_for)
    n_ev = int(parts.get("n_evidence") or 0)
    gates = parts.get("gates") if isinstance(parts.get("gates"), dict) else {}
    if gates:
        g1 = gates.get("G1_citation") or {}
        g3 = gates.get("G3_premise_broken") or {}
        hit = g1.get("hit_rate", 1.0)
        broken = g3.get("ids") or []
    else:
        # 旧产物：引文入卷时已筛，226 行 G1/G3 零触发；n_evidence 缺则只跑加权和
        hit = 1.0
        broken = []
        if "n_evidence" not in parts:
            return round(raw, 4)
    conf, _ = apply_hard_gates(
        raw, hit_rate=hit, n_evidence=n_ev, premise_broken=broken,
    )
    return round(conf, 4)


def auc_binary(scores: list[float], labels: list[str]) -> float:
    """只取「对」vs「错」的成对 AUC（部分不进）。"""
    pos = [s for s, y in zip(scores, labels) if y == "对"]
    neg = [s for s, y in zip(scores, labels) if y == "错"]
    if not pos or not neg:
        return float("nan")
    total = 0
    good = 0.0
    for p in pos:
        for n in neg:
            total += 1
            if p > n:
                good += 1.0
            elif p == n:
                good += 0.5
    return good / total


def load_joined_rows(
    *,
    labels_path: Path | None = None,
    cases_root: Path | None = None,
) -> list[dict[str, Any]]:
    """labels ⋈ out*/report.json，并经 Dossier.from_json 回灌重算分量。

    连接键＝**case + statement_sha8**（conclusion_id 只作一致性旁报）。
    demo_offline 每次重跑会重铸随机 conclusion_id；按 id 连会从 226 掉到
    224 或更低，按 statement_sha8 仍可 226/226。id 对不上**不** SystemExit
    整跑——跳过找不到 sha8 的行，主流程继续，旁报打印 matched／mismatched／missing。

    旧产物缺 `chain` 键——必须当场 `conclude_confidence` 才能与架构师
    「回灌重算」口径对齐；禁止直接用 labels_self 存的 score。
    """
    labels_path = labels_path or (_REPO / "calibration" / "labels_self.jsonl")
    cases_root = cases_root or (_REPO / "cases")
    labels = load_labeled_rows(labels_path)
    by_case: dict[str, list[Path]] = {}
    for rp in cases_root.glob("**/out*/report.json"):
        parts = rp.parts
        try:
            i = parts.index("cases")
            case = str(Path(*parts[i:i + 2]))
        except ValueError:
            continue
        by_case.setdefault(case, []).append(rp)

    # cache dossiers by report path
    dossier_cache: dict[Path, Dossier] = {}
    panel_cache: dict[Path, int] = {}

    out: list[dict[str, Any]] = []
    id_matched = 0
    id_mismatched = 0
    missing_by_sha8 = 0

    def _ensure_dossier(rp: Path) -> Dossier | None:
        if rp not in dossier_cache:
            try:
                dossier_cache[rp] = Dossier.from_json(rp)
            except Exception:  # noqa: BLE001 — 单份坏产物跳过
                return None
            raw = json.loads(rp.read_text(encoding="utf-8"))
            panel = raw.get("panel") or []
            panel_cache[rp] = max(1, len(panel) if isinstance(panel, list) else 1)
        return dossier_cache.get(rp)

    def _report_rank(rp: Path) -> tuple:
        """稳定决胜：同 sha8 多份产物时，先非 out_offline、再路径字典序。"""
        name = rp.parent.name
        # demo_offline 默认写 out_offline——重跑会重铸 id；不当首选
        offline_penalty = 1 if name == "out_offline" or name.startswith("out_offline") else 0
        return (offline_penalty, str(rp))

    for lab in labels:
        target_sha = lab["statement_sha8"]
        candidates: list[tuple[Path, Any, bool]] = []  # (path, con, id_ok)
        for rp in by_case.get(lab["case"], []):
            d = _ensure_dossier(rp)
            if d is None:
                continue
            for con in d.conclusions:
                if statement_sha8(con.statement or "") != target_sha:
                    continue
                id_ok = con.id == lab["conclusion_id"]
                candidates.append((rp, con, id_ok))
        if not candidates:
            missing_by_sha8 += 1
            continue
        # 决胜：① conclusion_id 命中优先 ② 非 out_offline ③ 路径字典序
        candidates.sort(key=lambda t: (0 if t[2] else 1, _report_rank(t[0]), t[1].id))
        found_path, found_con, id_ok = candidates[0]
        if id_ok:
            id_matched += 1
        else:
            id_mismatched += 1
        d = dossier_cache[found_path]
        n_panel = panel_cache[found_path]
        conf_v2, parts = conclude_confidence(found_con.id, d, n_panel=n_panel)
        row = {
            **lab,
            "parts": parts,
            "score_stored": float(found_con.confidence or lab["score"]),
            "score_v1": score_v1_of_parts(parts),
            "score_v2": round(float(conf_v2), 4),
            "report_path": str(found_path),
            "conclusion_id_live": found_con.id,
            "id_join_ok": id_ok,
        }
        from app.core.confidence import row_score_of
        row["score_v2_row"] = row_score_of(parts)
        out.append(row)

    side = (
        f"join_key=case+statement_sha8  n_joined={len(out)}/{len(labels)}  "
        f"conclusion_id matched={id_matched} mismatched={id_mismatched} "
        f"missing_by_sha8={missing_by_sha8}"
    )
    print(side, flush=True)
    global LAST_JOIN_SIDE
    LAST_JOIN_SIDE = {
        "n_joined": len(out),
        "n_labels": len(labels),
        "id_matched": id_matched,
        "id_mismatched": id_mismatched,
        "missing_by_sha8": missing_by_sha8,
        "side": side,
    }
    return out



def write_row_snapshot(
    rows: list[dict[str, Any]],
    path: Path | None = None,
) -> Path:
    """把每行回灌分量落到 calibration/，供干净克隆复放 ECE／AUC／高档 n。

    不触 labels_self.jsonl。字段够算 AUC／ECE／高档，不含完整 dossier。
    """
    path = path or (_REPO / "calibration" / "face_v2_row_snapshot.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for r in rows:
        parts = r.get("parts") or {}
        slim = {
            k: parts.get(k)
            for k in (
                "strength", "coverage", "agreement", "chain",
                "n_evidence", "gates", "aggregate_raw",
                "chain_for_aggregate", "agreement_factor",
            )
            if k in parts
        }
        entry = {
            "case": r.get("case"),
            "statement_sha8": r.get("statement_sha8"),
            "conclusion_id": r.get("conclusion_id"),
            "conclusion_id_live": r.get("conclusion_id_live"),
            "id_join_ok": r.get("id_join_ok"),
            "label": r.get("label"),
            "score_stored": r.get("score_stored"),
            "score_v1": r.get("score_v1"),
            "score_v2": r.get("score_v2"),
            "parts": slim,
        }
        lines.append(json.dumps(entry, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def high_band_stats(scores: list[float], labels: list[str], *, thr: float = 0.8):
    idx = [i for i, s in enumerate(scores) if s >= thr]
    n = len(idx)
    if n == 0:
        return {"n": 0, "acc": None}
    acc = sum(label_accuracy(labels[i]) for i in idx) / n
    return {"n": n, "acc": round(acc, 6)}


def baseline_acc(labels: list[str]) -> float:
    return sum(label_accuracy(y) for y in labels) / max(1, len(labels))


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [r["label"] for r in rows]
    v1 = [r["score_v1"] for r in rows]
    v2 = [r["score_v2"] for r in rows]
    base = baseline_acc(labels)
    out = {
        "n": len(rows),
        "baseline_acc": round(base, 6),
        "v1_multiply": {
            "ECE": round(ece_of(v1, labels), 6),
            "AUC": round(auc_binary(v1, labels), 6),
            "bins": five_bins(v1, labels),
            "high_band": high_band_stats(v1, labels),
        },
        "v2_weighted_gates": {
            "ECE": round(ece_of(v2, labels), 6),
            "AUC": round(auc_binary(v2, labels), 6),
            "bins": five_bins(v2, labels),
            "high_band": high_band_stats(v2, labels),
            "weights": dict(_AGG),
        },
        "replay": {
            "join_and_report": (
                ".venv/bin/python scripts/score_face_v2_report.py "
                "--labels calibration/labels_self.jsonl"
            ),
            "fit_T": (
                ".venv/bin/python scripts/fit_temperature.py "
                "--labels calibration/labels_self.jsonl "
                "--out calibration/temperature_receipt.json"
            ),
            "calibrate_stored_scores_NOT_baseline": (
                ".venv/bin/python scripts/calibrate_confidence.py "
                "--labels calibration/labels_self.jsonl"
            ),
        },
        "caveat": (
            "达标行「≥0.8 正确率 ≥85%」本报告不宣称已达标；"
            "高档非空须与「高档准确率＜整体基准」同句出现。"
        ),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", type=Path,
                    default=_REPO / "calibration" / "labels_self.jsonl")
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument(
        "--write-snapshot",
        type=Path,
        nargs="?",
        const=_REPO / "calibration" / "face_v2_row_snapshot.jsonl",
        default=_REPO / "calibration" / "face_v2_row_snapshot.jsonl",
        help="把每行 score_v1/v2/parts 落到 calibration/（默认写入；"
             "传 --write-snapshot "" 可关）",
    )
    ap.add_argument(
        "--no-write-snapshot",
        action="store_true",
        help="不写 face_v2_row_snapshot.jsonl",
    )
    args = ap.parse_args(argv)
    rows = load_joined_rows(labels_path=args.labels)
    if (not args.no_write_snapshot) and args.write_snapshot:
        sp = write_row_snapshot(rows, Path(args.write_snapshot))
        print(f"snapshot → {sp}  ({len(rows)} rows)", flush=True)
    rep = report(rows)
    v1, v2 = rep["v1_multiply"], rep["v2_weighted_gates"]
    print(f"n={rep['n']}  baseline_acc={rep['baseline_acc']}")
    print(f"v1  ECE={v1['ECE']}  AUC={v1['AUC']}  "
          f"high_n={v1['high_band']['n']} high_acc={v1['high_band']['acc']}")
    print(f"v2  ECE={v2['ECE']}  AUC={v2['AUC']}  "
          f"high_n={v2['high_band']['n']} high_acc={v2['high_band']['acc']}")
    print("v1 bins:")
    for b in v1["bins"]:
        print(f"  {b['bin']}: n={b['n']} acc={b['acc']} conf={b['conf']}")
    print("v2 bins:")
    for b in v2["bins"]:
        print(f"  {b['bin']}: n={b['n']} acc={b['acc']} conf={b['conf']}")
    hb = v2["high_band"]
    if hb["n"] and hb["acc"] is not None:
        print(
            f"高档非空 n={hb['n']} 且高档准确率 {hb['acc']} "
            f"{'<' if hb['acc'] < rep['baseline_acc'] else '≥'} "
            f"基准 {rep['baseline_acc']} —— 达标线仍无法回答"
        )
    print(f"复放：{rep['replay']['join_and_report']}")
    if args.json_out:
        args.json_out.write_text(
            json.dumps(rep, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
