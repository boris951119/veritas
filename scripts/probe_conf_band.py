"""C-20 分档（band / band_rel）的全部基数——零 LLM、零网络、只读历史产物。

为什么这条要进仓库（协议 §5 ㉕：单里的「实测」必须是一条别人也拿得到的命令）：
C-20 单里那三组数（内部结论集 258 条、提交物 40 条、分位切点 0.1777/0.2667）此前分别来自
一支 10-17 的一次性 heredoc 与一份 `/tmp` 产物的 `summary.json`，隔几天连我自己都复放不了；
而且**第三组（分位切点）从来没有一条仓库内命令产出过**——它偏偏是本单 `band_rel` 的全部实质。
从此「高置信档到底是不是结构性为空」「分位切点落在哪」＝一条可粘贴命令的输出：

    .venv/bin/python scripts/probe_conf_band.py                       # 仓库内 cases/*/out*（两口径都打）
    .venv/bin/python scripts/probe_conf_band.py --from /tmp/s4runs/time-20261020-174839
    .venv/bin/python scripts/probe_conf_band.py --mode exported --json

**两个口径不许混用**（C-20 单里我先写错过一次，已在单内更正）：
- `exported`＝**提交物口径**：读 `confidence.json` 每行的 `score`。评分标准 3.2.3 与《需求说明》
  达标行「高置信（≥0.8）正确率 ≥85%」消费的都是这一口径 ⇒ **判据引用高档条数一律用它**。
- `internal`＝**内部结论集口径**：读 `report.json` 里 `status=="majority"` 的 `confidence`。
  它比提交物宽（`insufficient`／被裸结论闸丢掉的题也在里面），只用来解释「为什么高档为空是
  合式的结构性质」，**不许当提交物的分档面**。
  这一口径同时打 `confidence_parts.strength` 的分布——`score = strength × coverage ×
  agreement_factor × chain_factor` 四个因子每个都 ≤1，所以 strength 的上界就是整条链的第一道天花板。

分位切点两种定义都打，因为 C-20 只拍板了「同跑次分位档」这一件事、没拍插值法：
- `q34_67`＝`statistics.quantiles(scores, n=100, method="inclusive")` 的第 34／67 个切点（单里那对数的口径）；
- `tercile`＝`statistics.quantiles(scores, n=3, method="inclusive")` 的两个切点（1/3、2/3）。
两者在 n=40 这种小样本上**不相等**，`band_rel_rule` 必须把「方法名＋样本数＋当次切点」写到
别人能照着复算的程度（判据 b 要独立重推一遍），所以这里把两种都量出来、由单指定用哪一种。
档边界一律 `>=`（与 `band_of` 同向）：`score >= hi ⇒ 高`、`score >= lo ⇒ 中`、否则 `低`。

本脚本**不调模型、不写任何字节**；一个产物都找不到时打印一句提示并以退出码 2 结束
（不静默给一堆 0——0 与「没扫到」是两回事，`probe_pack_window.py` 那条口径同样适用）。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BAND_HIGH = 0.8   # 官方《需求说明》达标行原话「高置信（≥0.8）」
BAND_MID = 0.5    # 我方设定（官方从未写过中/低分界）——文案里不许说成官方给的
INTERP = "inclusive"   # statistics.quantiles 的插值法；写进 band_rel_rule 的就是这个词


def _pct(n: int, total: int) -> str:
    return "n/a" if not total else f"{n * 100 // total}%"


def _cuts(scores: list[float]) -> dict:
    """两种分位定义的切点；样本 <2 时 statistics.quantiles 会抛，这里返回 None 让上层显影。"""
    out: dict = {"n": len(scores)}
    if len(scores) < 2:
        out["q34_67"] = None
        out["tercile"] = None
        return out
    q100 = statistics.quantiles(scores, n=100, method=INTERP)
    out["q34_67"] = (round(q100[33], 4), round(q100[66], 4))
    ter = statistics.quantiles(scores, n=3, method=INTERP)
    out["tercile"] = (round(ter[0], 4), round(ter[1], 4))
    return out


def _band_counts(scores: list[float], lo: float | None, hi: float | None) -> dict:
    if lo is None or hi is None:
        return {"高": None, "中": None, "低": None}
    hi_n = sum(1 for s in scores if s >= hi)
    mid_n = sum(1 for s in scores if lo <= s < hi)
    return {"高": hi_n, "中": mid_n, "低": len(scores) - hi_n - mid_n}


def _describe(scores: list[float]) -> dict:
    s = sorted(scores)
    d: dict = {
        "n": len(s),
        "min": round(s[0], 4) if s else None,
        "max": round(s[-1], 4) if s else None,
        "median": round(statistics.median(s), 4) if s else None,
        "mean": round(statistics.fmean(s), 4) if s else None,
        "ge_0.8": sum(1 for x in s if x >= 0.8),
        "ge_0.6": sum(1 for x in s if x >= 0.6),
        "ge_0.5": sum(1 for x in s if x >= 0.5),
        "lt_0.4": sum(1 for x in s if x < 0.4),
        "abs_bands": _band_counts(s, BAND_MID, BAND_HIGH),
    }
    c = _cuts(s)
    d["cuts"] = c
    d["rel_bands_q34_67"] = _band_counts(s, *(c["q34_67"] or (None, None)))
    d["rel_bands_tercile"] = _band_counts(s, *(c["tercile"] or (None, None)))
    return d


def collect_exported(roots: list[Path]) -> tuple[list[float], list[Path]]:
    scores: list[float] = []
    files: list[Path] = []
    for root in roots:
        for p in sorted(root.rglob("confidence.json")):
            try:
                rows = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(rows, list):
                continue
            files.append(p)
            for r in rows:
                if isinstance(r, dict) and r.get("score") is not None:
                    scores.append(float(r["score"]))
    return scores, files


def collect_internal(roots: list[Path]) -> tuple[list[float], list[float], list[Path]]:
    scores: list[float] = []
    strengths: list[float] = []
    files: list[Path] = []
    for root in roots:
        for p in sorted(root.rglob("report.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            cons = d.get("conclusions") if isinstance(d, dict) else None
            if not isinstance(cons, list):
                continue
            files.append(p)
            for c in cons:
                if not isinstance(c, dict) or c.get("status") != "majority":
                    continue
                scores.append(float(c.get("confidence") or 0.0))
                parts = c.get("confidence_parts") or {}
                if parts:
                    strengths.append(float(parts.get("strength") or 0.0))
    return scores, strengths, files


def _print_block(title: str, d: dict, files: list[Path]) -> None:
    n = d["n"]
    print(f"\n### {title}")
    print(f"  样本文件 {len(files)} 份 · n={n}")
    if not n:
        print("  （这个口径一条都没扫到——不是 0 条高档，是没有样本）")
        return
    print(f"  min={d['min']} max={d['max']} median={d['median']} mean={d['mean']}")
    print(f"  ≥0.8 {d['ge_0.8']} 条（{_pct(d['ge_0.8'], n)}）· "
          f"≥0.6 {d['ge_0.6']} 条 · ≥0.5 {d['ge_0.5']} 条 · "
          f"<0.4 {d['lt_0.4']} 条（{_pct(d['lt_0.4'], n)}）")
    ab = d["abs_bands"]
    print(f"  band（绝对档 0.8/0.5，0.8＝官方原话、0.5＝我方设定）：高 {ab['高']}／中 {ab['中']}／低 {ab['低']}")
    c = d["cuts"]
    for key, label in (("q34_67", "band_rel 34%/67%"), ("tercile", "band_rel 1/3–2/3")):
        cut = c.get(key)
        rb = d["rel_bands_q34_67"] if key == "q34_67" else d["rel_bands_tercile"]
        if cut is None:
            print(f"  {label}：样本 <2，切点不可算（band_rel 走小样本分支）")
            continue
        print(f"  {label}（method={INTERP}）：切点 {cut[0]}／{cut[1]} ⇒ 高 {rb['高']}／中 {rb['中']}／低 {rb['低']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="C-20 分档基数探针（零 LLM、只读）")
    ap.add_argument("--from", dest="src", action="append", default=None,
                    help="产物根目录（可重复）；缺省＝仓库内 cases/*/out*")
    ap.add_argument("--mode", choices=("both", "exported", "internal"), default="both")
    ap.add_argument("--json", action="store_true", help="只打机器可读 JSON")
    args = ap.parse_args(argv)

    if args.src:
        roots = [Path(s).expanduser() for s in args.src]
        missing = [str(r) for r in roots if not r.exists()]
        if missing:
            print(f"[probe_conf_band] 目录不存在：{', '.join(missing)}", file=sys.stderr)
            return 2
    else:
        roots = sorted((ROOT / "cases").glob("*/out*"))
        if not roots:
            print("[probe_conf_band] 仓库内 cases/*/out* 一个都没有；"
                  "先跑 scripts/demo_offline.py，或用 --from 指一份历史产物", file=sys.stderr)
            return 2

    out: dict = {"roots": [str(r) for r in roots]}
    found_any = False

    if args.mode in ("both", "exported"):
        scores, files = collect_exported(roots)
        found_any = found_any or bool(files)
        out["exported"] = _describe(scores)
        out["exported"]["files"] = len(files)
        if not args.json:
            _print_block("提交物口径（confidence.json 的 score 行）＝评分标准与达标行消费的那一面",
                         out["exported"], files)

    if args.mode in ("both", "internal"):
        scores, strengths, files = collect_internal(roots)
        found_any = found_any or bool(files)
        out["internal"] = _describe(scores)
        out["internal"]["files"] = len(files)
        out["internal_strength"] = _describe(strengths) if strengths else {"n": 0}
        if not args.json:
            _print_block("内部结论集口径（report.json 的 majority confidence）——只用于解释结构性质",
                         out["internal"], files)
            st = out["internal_strength"]
            if st.get("n"):
                print(f"  其中 confidence_parts.strength：n={st['n']} max={st['max']} "
                      f"≥0.8 {st['ge_0.8']} 条（{_pct(st['ge_0.8'], st['n'])}）"
                      "  ← score 的第一个因子，它顶不满则 score 必然顶不满")
            else:
                # 两个互斥状态不许共用一句会说谎的模板（协议 §5 ㉒）：
                # 没扫到产物 ≠ 扫到了但产物早于链分量上线。
                if not files:
                    print("  其中 confidence_parts.strength：没有样本可统计"
                          "（这个口径一个 report.json 都没扫到）")
                else:
                    print(f"  其中 confidence_parts.strength：{len(files)} 份 report.json 里"
                          " 一条 majority 结论都没有 confidence_parts.strength"
                          "（那批产物早于链分量上线，或结论没有 confidence_parts）")

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    if not found_any:
        print("[probe_conf_band] 两种口径都没扫到产物（confidence.json / report.json 都不在）",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
