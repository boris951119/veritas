#!/usr/bin/env python3
"""C-24：置信度可靠性曲线与 ECE（零 LLM、只读标签文件）。

标定集来源必须是自家案例（cases/ 或 eval/）。官方样例（桌面 veritas-testcases、
/tmp/s4runs 等）一律不许进 --labels。真 label 依赖 task #38 人签；本脚本遇到
空 label／缺键／空 labeled_by 一律报错退出，不静默跳过。

用法：
    .venv/bin/python scripts/calibrate_confidence.py --help
    .venv/bin/python scripts/calibrate_confidence.py --labels path.jsonl \\
        [--out-dir /tmp/s4runs/calib-curve-<ts>]
    .venv/bin/python scripts/calibrate_confidence.py --emit-candidates \\
        calibration/candidates_self.jsonl

箱定义＝工单括号端点 0.0–0.2 … 0.8–1.0（按 0.2 步展开＝5 档；工单写「六箱」
按端点计。最后一档 [0.8, 1.0] 含右端）。箱内样本 <5 ⇒ insufficient，不给百分比。
ECE＝Σ (n_b / N) × |acc_b − mean_conf_b|（只对有样本的箱；insufficient 箱仍按
占比计入 ECE，准确率用该箱真实均值——样本虽少仍有点估计；对外曲线表对
insufficient 不展示百分比）。
高档覆盖率＝score≥0.8 条数／总数。

准确率口径：label「对」=1.0、「部分」=0.5、「错」=0.0，箱内取均值。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 工单括号端点 0.0–0.2 … 0.8–1.0 → 5 档（见模块 docstring）
BIN_EDGES: list[tuple[str, float, float]] = [
    ("0.0-0.2", 0.0, 0.2),
    ("0.2-0.4", 0.2, 0.4),
    ("0.4-0.6", 0.4, 0.6),
    ("0.6-0.8", 0.6, 0.8),
    ("0.8-1.0", 0.8, 1.0),
]
MIN_BIN_N = 5
HIGH_THRESH = 0.8
# 入库候选单行字节上限（防把全文 statement 塞进仓库）
MAX_CANDIDATE_LINE_BYTES = 512
ALLOWED_LABELS = {"对", "部分", "错"}
SELF_CASE_PREFIXES = ("cases/", "eval/")


def statement_sha8(statement: str) -> str:
    return hashlib.sha256((statement or "").encode("utf-8")).hexdigest()[:8]


def label_accuracy(label: str) -> float:
    if label == "对":
        return 1.0
    if label == "部分":
        return 0.5
    if label == "错":
        return 0.0
    raise ValueError(f"未知 label={label!r}（只认 对／部分／错）")


def bin_index(score: float) -> int:
    """半开 [lo, hi)，最后一档闭右端。score 钳到 [0, 1]。"""
    s = max(0.0, min(1.0, float(score)))
    for i, (_, lo, hi) in enumerate(BIN_EDGES):
        if i == len(BIN_EDGES) - 1:
            if lo <= s <= hi:
                return i
        elif lo <= s < hi:
            return i
    return len(BIN_EDGES) - 1


def _require_self_case(case: str, *, where: str) -> None:
    c = (case or "").strip()
    if not any(c == p.rstrip("/") or c.startswith(p) for p in SELF_CASE_PREFIXES):
        raise SystemExit(
            f"标定集来源必须是自家案例（cases/ 或 eval/），"
            f"不许默认去读桌面官方样例；违规 case={case!r} @ {where}"
        )
    for bad in ("s4runs", "veritas-testcases", "Desktop"):
        if bad in c:
            raise SystemExit(
                f"标定集来源必须是自家案例；检测到仓库外痕迹 {bad!r} in case={case!r}"
            )


def load_labeled_rows(path: Path) -> list[dict[str, Any]]:
    """读 --labels；空 label／缺键／空 labeled_by ⇒ 报错退出（不静默跳过）。"""
    if not path.is_file():
        raise SystemExit(f"--labels 文件不存在：{path}")
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise SystemExit(f"--labels 第 {lineno} 行不是 JSON：{e}") from e
        if not isinstance(obj, dict):
            raise SystemExit(f"--labels 第 {lineno} 行不是对象")
        where = f"{path}:{lineno}"
        if "label" not in obj:
            raise SystemExit(
                f"缺 label 键（整行缺键）@ {where}；"
                f"真 label 须人签（task #38），空缺不许静默跳过"
            )
        label = obj.get("label")
        if label is None or (isinstance(label, str) and not label.strip()):
            raise SystemExit(
                f"label 为空 @ {where}；真 label 须人签（task #38），"
                f"空缺不许静默跳过"
            )
        if "labeled_by" not in obj or not str(obj.get("labeled_by") or "").strip():
            raise SystemExit(
                f"labeled_by 为空或缺键 @ {where}；"
                f"真 label 须人签（task #38），空缺不许静默跳过"
            )
        label_s = str(label).strip()
        if label_s not in ALLOWED_LABELS:
            raise SystemExit(f"label 只认 对／部分／错，得 {label_s!r} @ {where}")
        case = str(obj.get("case") or "")
        _require_self_case(case, where=where)
        score = obj.get("score")
        if not isinstance(score, (int, float)):
            raise SystemExit(f"score 必须是数 @ {where}")
        rows.append({
            "case": case,
            "conclusion_id": str(obj.get("conclusion_id") or ""),
            "statement_sha8": str(obj.get("statement_sha8") or ""),
            "score": float(score),
            "band": obj.get("band"),
            "band_rel": obj.get("band_rel"),
            "label": label_s,
            "labeled_by": str(obj["labeled_by"]).strip(),
        })
    if not rows:
        raise SystemExit(f"--labels 无有效行：{path}")
    return rows


def compute_curve(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """纯函数：六／五箱曲线 + ECE + 高档覆盖率。可被测试直接 import。"""
    n = len(rows)
    buckets: list[dict[str, Any]] = []
    # 先分箱
    members: list[list[dict[str, Any]]] = [[] for _ in BIN_EDGES]
    for r in rows:
        members[bin_index(r["score"])].append(r)

    ece = 0.0
    for (name, lo, hi), xs in zip(BIN_EDGES, members):
        bn = len(xs)
        entry: dict[str, Any] = {
            "bin": name,
            "lo": lo,
            "hi": hi,
            "n": bn,
        }
        if bn == 0:
            entry["insufficient"] = True
            # 无样本：不算进 ECE 分子（占比 0）
            buckets.append(entry)
            continue
        accs = [label_accuracy(x["label"]) for x in xs]
        confs = [float(x["score"]) for x in xs]
        acc = sum(accs) / bn
        mean_conf = sum(confs) / bn
        ece += (bn / n) * abs(acc - mean_conf)
        entry["mean_confidence"] = round(mean_conf, 6)
        if bn < MIN_BIN_N:
            entry["insufficient"] = True
            # 不给百分比（别把没数据当 0）——准确率数值仍留给 ECE 内部，
            # 但对外字段 accuracy / accuracy_pct 缺省
        else:
            entry["insufficient"] = False
            entry["accuracy"] = round(acc, 6)
            entry["accuracy_pct"] = round(100.0 * acc, 2)
        buckets.append(entry)

    n_high = sum(1 for r in rows if float(r["score"]) >= HIGH_THRESH)
    return {
        "n": n,
        "bins": buckets,
        "ece": round(ece, 6),
        "high_coverage": round(n_high / n, 6) if n else 0.0,
        "high_coverage_count": n_high,
        "high_threshold": HIGH_THRESH,
        "accuracy_rule": "对=1.0／部分=0.5／错=0.0，箱内均值",
        "bin_note": "端点 0.0–0.2 … 0.8–1.0（0.2 步＝5 档；工单「六箱」按括号端点）",
    }


def print_table(curve: dict[str, Any]) -> None:
    print(f"n={curve['n']}  ECE={curve['ece']}  "
          f"高档覆盖率(≥{curve['high_threshold']})="
          f"{curve['high_coverage']} ({curve['high_coverage_count']}/{curve['n']})")
    print(f"{'bin':<10} {'n':>5} {'acc%':>8} {'mean_conf':>10} {'flag':<14}")
    for b in curve["bins"]:
        if b["n"] == 0:
            acc_s, mean_s, flag = "—", "—", "empty"
        elif b.get("insufficient"):
            acc_s = "insuff"
            mean_s = f"{b['mean_confidence']:.4f}"
            flag = "insufficient"
        else:
            acc_s = f"{b['accuracy_pct']:.2f}"
            mean_s = f"{b['mean_confidence']:.4f}"
            flag = "ok"
        print(f"{b['bin']:<10} {b['n']:>5} {acc_s:>8} {mean_s:>10} {flag:<14}")


def emit_candidates(dest: Path, *, cases_root: Path | None = None) -> int:
    """从本机 cases/**/out*/report.json 扫 majority 结论，写候选清单（label 留空）。

    只读产物、不调模型。band／band_rel 用 app.core.confidence 只读函数按单份
    report 的 majority 分数集当场算。去重键＝(case, statement_sha8)。
    """
    from app.core.confidence import band_of, band_rel_of  # 只读，不改 app/

    cases_root = cases_root or (ROOT / "cases")
    reports = sorted(cases_root.glob("**/out*/report.json"))
    seen: set[tuple[str, str]] = set()
    out_rows: list[dict[str, Any]] = []

    for rp in reports:
        try:
            parts = rp.resolve().parts
            ci = parts.index("cases")
            case_name = parts[ci + 1]
        except (ValueError, IndexError):
            continue
        case = f"cases/{case_name}"
        _require_self_case(case, where=str(rp))
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        concs = [
            c for c in (data.get("conclusions") or [])
            if isinstance(c, dict)
            and c.get("status") == "majority"
            and isinstance(c.get("confidence"), (int, float))
        ]
        if not concs:
            continue
        scores = [float(c["confidence"]) for c in concs]
        for c in concs:
            stmt = str(c.get("statement") or "")
            sha = statement_sha8(stmt)
            key = (case, sha)
            if key in seen:
                continue
            seen.add(key)
            score = float(c["confidence"])
            row = {
                "case": case,
                "conclusion_id": str(c.get("id") or ""),
                "statement_sha8": sha,
                "score": round(score, 4),
                "band": band_of(score),
                "band_rel": band_rel_of(scores, score),
                "label": "",
                "labeled_by": "",
            }
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            if len(line.encode("utf-8")) > MAX_CANDIDATE_LINE_BYTES:
                raise SystemExit(
                    f"候选单行超过 {MAX_CANDIDATE_LINE_BYTES} 字节 "
                    f"(case={case} id={row['conclusion_id']})；"
                    f"只许存 statement_sha8，不许塞全文"
                )
            out_rows.append(row)

    dest.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in out_rows
    )
    if out_rows:
        text += "\n"
    dest.write_text(text, encoding="utf-8")
    print(f"wrote {len(out_rows)} candidates → {dest}")
    return len(out_rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "C-24 置信度可靠性曲线与 ECE。"
            "标定集来源必须是自家案例（cases/ 或 eval/），"
            "不许默认去读桌面官方样例。"
        )
    )
    ap.add_argument(
        "--labels",
        type=Path,
        help="人签标定 jsonl（每行含 label 与 labeled_by；缺则报错退出）",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="曲线输出目录（默认 /tmp/s4runs/calib-curve-<ts>）",
    )
    ap.add_argument(
        "--emit-candidates",
        type=Path,
        nargs="?",
        const=ROOT / "calibration" / "candidates_self.jsonl",
        help="从本机 cases/**/out*/report.json 生成候选清单（label 留空）",
    )
    args = ap.parse_args(argv)

    if args.emit_candidates is not None:
        n = emit_candidates(Path(args.emit_candidates))
        return 0 if n >= 0 else 2

    if args.labels is None:
        ap.print_usage(sys.stderr)
        print(
            "错误：必须提供 --labels（标定集来源必须是自家案例 cases/ 或 eval/，"
            "不许默认去读桌面官方样例）。"
            "真 label 依赖 task #38 人签；本轮候选见 --emit-candidates。",
            file=sys.stderr,
        )
        return 2

    rows = load_labeled_rows(Path(args.labels))
    curve = compute_curve(rows)
    print_table(curve)

    out_dir = args.out_dir
    if out_dir is None:
        ts = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
        out_dir = Path(f"/tmp/s4runs/calib-curve-{ts}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    curve_path = out_dir / "curve.json"
    payload = {
        **curve,
        "source_labels": str(Path(args.labels).resolve()),
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    curve_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {curve_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
