#!/usr/bin/env python3
"""C-36：单参数温度拟合（零 LLM、只读 labels_self＋回灌重算）。

网格 T∈[0.7, 1.3] step 0.05；5 折 CV 报外推 ECE；写
calibration/temperature_receipt.json。

映射只许缩放、不许挪均值：
    score = clip01(mean + T * (raw - mean))
mean 由该提交物／该折 pooled 当场算。生产默认 T=1.0。

⚠ T≤0.7 可把分布挤进一箱、把 ECE 刷到 ~0.0218；常数预测子 ECE=0——
所以 ECE 单独变小 ≠ 改进；退化检查失败即使 ECE=0 也不录取。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.calibrate_confidence import (  # noqa: E402
    BIN_EDGES,
    bin_index,
    label_accuracy,
)
from scripts.score_face_v2_report import (  # noqa: E402
    auc_binary,
    load_joined_rows,
    score_v2_of_parts,
)

T_MIN, T_MAX, T_STEP = 0.7, 1.3, 0.05
DEFAULT_T = 1.0


def clip01(x: float) -> float:
    return min(1.0, max(0.0, float(x)))


def apply_T(raw: float, *, mean: float, t: float) -> float:
    return clip01(mean + float(t) * (float(raw) - mean))


def ece_of(scores: list[float], labels: list[str]) -> float:
    """与 calibrate_confidence.compute_curve 同口径的 ECE。"""
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


def degeneracy_check(scores: list[float]) -> tuple[bool, str]:
    """同分／近常数分布 ⇒ 不合格。"""
    if not scores:
        return False, "空分数序列"
    uniq = {round(float(s), 6) for s in scores}
    if len(uniq) <= 1:
        return False, f"同分退化：全部 {len(scores)} 行唯一值={next(iter(uniq))}"
    # 单箱独占 ≥95% 也视作退化
    counts = [0 for _ in BIN_EDGES]
    for s in scores:
        counts[bin_index(s)] += 1
    n = len(scores)
    top = max(counts) / n
    if top >= 0.95:
        return False, f"分箱退化：单箱占比 {top:.3f} ≥ 0.95"
    return True, "ok"


def _folds(n: int, k: int = 5) -> list[list[int]]:
    """连续块 5 折（可复放，不打乱）。"""
    sizes = [n // k + (1 if i < n % k else 0) for i in range(k)]
    folds = []
    start = 0
    for sz in sizes:
        folds.append(list(range(start, start + sz)))
        start += sz
    return folds


def grid_T() -> list[float]:
    out = []
    t = T_MIN
    # 防浮点：用整数格
    n_steps = int(round((T_MAX - T_MIN) / T_STEP))
    for i in range(n_steps + 1):
        out.append(round(T_MIN + i * T_STEP, 4))
    return out


def fit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    raws = [float(r["score_v2"]) for r in rows]
    labels = [r["label"] for r in rows]
    n = len(rows)
    folds = _folds(n, 5)
    grid = grid_T()
    # 每 T：5 折 OOS 分数拼起来算 ECE
    cv_rows = []
    for t in grid:
        oos_scores = [0.0] * n
        for hold in folds:
            train_idx = [i for i in range(n) if i not in set(hold)]
            mean_tr = sum(raws[i] for i in train_idx) / max(1, len(train_idx))
            for i in hold:
                oos_scores[i] = apply_T(raws[i], mean=mean_tr, t=t)
        ece = ece_of(oos_scores, labels)
        ok, reason = degeneracy_check(oos_scores)
        cv_rows.append({
            "T": t,
            "oos_ece": round(ece, 6),
            "degeneracy_ok": ok,
            "degeneracy_reason": reason,
        })
    # 选：退化通过的 T 里 OOS ECE 最小；若相对 T=1.0 改善 < 0.001 则保留 1.0
    # （本数据上 ECE 对 T 几乎平坦，盲选最小会落到 0.7 挤箱边界）
    viable = [r for r in cv_rows if r["degeneracy_ok"]]
    if viable:
        best = min(viable, key=lambda r: (r["oos_ece"], abs(r["T"] - 1.0)))
        at_1 = next((r for r in viable if abs(r["T"] - 1.0) < 1e-9), None)
        if at_1 is not None and (at_1["oos_ece"] - best["oos_ece"]) < 0.001:
            chosen_T = DEFAULT_T
        else:
            chosen_T = best["T"]
    else:
        chosen_T = DEFAULT_T
    mean_all = sum(raws) / n
    final_scores = [apply_T(s, mean=mean_all, t=chosen_T) for s in raws]
    bins = five_bins(final_scores, labels)
    auc = auc_binary(final_scores, labels)
    ok, reason = degeneracy_check(final_scores)
    return {
        "chosen_T": chosen_T,
        "default_T_production": DEFAULT_T,
        "T_domain": [T_MIN, T_MAX],
        "T_step": T_STEP,
        "n": n,
        "mean_pooled": round(mean_all, 6),
        "cv": cv_rows,
        "bins": bins,
        "AUC": round(auc, 6) if auc == auc else None,
        "ECE": round(ece_of(final_scores, labels), 6),
        "degeneracy_ok": ok,
        "degeneracy_reason": reason,
        "mapping": "score = clip01(mean + T*(raw - mean)); mean = pooled of that submit/fold",
        "note": (
            "T≤0.7 可把 ECE 刷低到挤箱退化值；常数预测子 ECE=0；"
            "ECE 单独下降 ≠ 改进。生产默认 T=1.0。"
        ),
        "replay": (
            ".venv/bin/python scripts/fit_temperature.py "
            "--labels calibration/labels_self.jsonl "
            "--out calibration/temperature_receipt.json"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", type=Path,
                    default=_REPO / "calibration" / "labels_self.jsonl")
    ap.add_argument("--out", type=Path,
                    default=_REPO / "calibration" / "temperature_receipt.json")
    args = ap.parse_args(argv)
    rows = load_joined_rows(labels_path=args.labels)
    # 确保用 v2 分数
    for r in rows:
        r["score_v2"] = score_v2_of_parts(r["parts"])
    receipt = fit(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out}")
    print(f"chosen_T={receipt['chosen_T']} ECE={receipt['ECE']} "
          f"AUC={receipt['AUC']} degeneracy_ok={receipt['degeneracy_ok']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
