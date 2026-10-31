"""离线复放打分器：把历史产物 report.json 重新喂回零 LLM 机械闸，出一行可比较的质量数。

为什么需要它：451 项测试量的是输入侧（该找的文件找到了、编的数字拦住了），
「这句结论到底答没回答问题」以前只能靠人读报告。本地一次真模型跑批 1,384 秒
/ 6 万 token，跑得起、读不起——所以每次改动到底变好还是变坏，必须有零成本的
自动判据。

它做什么：读产物目录里的 report.json → Dossier.from_json 重建案卷 → 走
app.core.audit.audit_all（全部机械闸即时重算，不落盘）+ 置信度分布 + 引用覆盖
+ 未引用议题段 + 子问落点 + 成本账。零 LLM、零网络、零写入（除非 --save）。

它不做什么：**不改任何结论、不跑模型、不碰 app/ 的逻辑**。它只是把已有的闸
和已有的派生指标按同一口径复算一遍，输出可 diff 的数字。

用法：
    .venv/bin/python scripts/score_artifacts.py                 # 默认扫 cases/*/out*/
    .venv/bin/python scripts/score_artifacts.py cases/bi-delivery-risk/out_local14b_knife1
    .venv/bin/python scripts/score_artifacts.py --grep knife    # 只看名字含 knife 的产物
    .venv/bin/python scripts/score_artifacts.py --save /tmp/base.json
    .venv/bin/python scripts/score_artifacts.py --check /tmp/base.json   # 退化则 exit 1

判读口径（越小越好）：high/medium 灯数、warrant 黄灯、未引用议题段、单署名结论数、
秒与 token；（越大越好）：引用覆盖率、置信度最大值、子问已答数、**会签条数**
（多人共同署名的结论——榜单痛点「独立判断或简单投票」的正面回答）。
「归并」列是机械归并组数，不计好坏：0 组说明三个视角各说各话，太多组要防错并。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.audit import audit_scan  # noqa: E402
from app.core.conflicts import (  # noqa: E402
    dissent_conclusions, majority_conclusions)
from app.core.coverage_gap import (  # noqa: E402
    subquestion_status, unused_topic_segments)
from app.core.evidence import Dossier  # noqa: E402

# 越大越好的指标（diff 时按方向判退化）
# ⚠️ 2026-10-13 置信度加了第四分量（推理链完整性），conf_median/conf_max 的
# **刻度整体下移约 15%**（实测见 measure_baseline.py 第 5 件事）。跨这个改动比
# 基线必须先 `--save` 重存一份，否则会把「链开始计分」读成「答案变差」。
_HIGHER_BETTER = {"conf_max", "conf_median", "cited_share", "subq_answered",
                  "multi_author", "chain_median"}
# 越小越好的指标
_LOWER_BETTER = {"flags_high", "flags_medium", "flags_not_evaluated",
                 "warrant_flags", "scope_flags", "unused_topic",
                 "single_author", "subq_unanswered", "subq_gap", "n_rejected",
                 "elapsed_s", "tokens", "n_calls"}
_REFUSE_MARKS = ("议题未齐", "请写明", "请补充", "无法研判")


# ---------------------------------------------------------------- 找产物

def _default_artifacts() -> list[Path]:
    """cases/<案例>/out*/report.json——不含 history/ 快照（那是人工改出来的）。"""
    out = []
    for case_dir in sorted((ROOT / "cases").glob("*")):
        if not case_dir.is_dir():
            continue
        for out_dir in sorted(case_dir.glob("out*")):
            p = out_dir / "report.json"
            if p.is_file():
                out.append(p)
    return out


def _resolve(items: list[str]) -> list[Path]:
    """命令行给的路径：目录 → 目录下的 report.json；文件 → 原样。"""
    out: list[Path] = []
    for raw in items:
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / p
        if p.is_dir():
            f = p / "report.json"
            if f.is_file():
                out.append(f)
            else:
                out.extend(sorted(p.glob("*/report.json")))
        elif p.is_file():
            out.append(p)
        else:
            raise SystemExit(f"产物路径不存在：{raw}（不静默跳过）")
    return out


def _chain_broken(parts: list[dict]) -> dict:
    """统计一批 confidence_parts 里推理链断在哪几环（键用中文名，直接可读）。"""
    from app.core.chain_integrity import CHECK_LABEL_CN

    out: dict[str, int] = {}
    for p in parts:
        for check in ((p.get("chain_detail") or {}).get("broken") or []):
            name = CHECK_LABEL_CN.get(check, check)
            out[name] = out.get(name, 0) + 1
    return out


# ---------------------------------------------------------------- 单份打分

def score_artifact(path: Path) -> dict:
    """一份 report.json → 一行可比较的指标。任何异常向上抛，由调用方显式记为失败。"""
    dossier = Dossier.from_json(path)
    scan = audit_scan(dossier)
    flags = scan["flags"]
    not_eval = scan["not_evaluated"]
    summary = scan["summary"]

    majority = majority_conclusions(dossier)
    confs = [c.confidence for c in majority]
    parts = [c.confidence_parts or {} for c in majority]

    n_segments = sum(len(src.segments) for src in dossier.sources)
    cited = {sid for ev in dossier.evidences for sid in ev.segment_ids}
    cited_real = len([sid for sid in cited if dossier.segment(sid) is not None])
    unused = unused_topic_segments(dossier)
    subs = subquestion_status(dossier)

    acc = dossier.accounting or {}
    report_md = path.parent / "report.md"
    refused = ""
    if report_md.is_file():
        head = report_md.read_text(encoding="utf-8")[:600]
        refused = next((m for m in _REFUSE_MARKS if m in head), "")

    by_kind = {k: v for k, v in sorted(summary["by_kind"].items()) if v}
    insufficient = sum(1 for c in dossier.conclusions
                       if c.status == "insufficient")
    mech = (dossier.accounting or {}).get("mechanical_merge") or {}
    n_multi_author = sum(1 for p in parts
                         if int(p.get("n_authors", 0) or 0) >= 2)
    return {
        "artifact": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT)
                    else str(path),
        "question": (dossier.question or "")[:60],
        "refused": bool(refused),
        "refuse_mark": refused,
        # 零可用结论＝产品级失败：报告交得出来，但一条能用的判断都没有
        "no_answer": not majority,
        "n_sources": len(dossier.sources),
        "n_segments": n_segments,
        "n_conclusions": len(dossier.conclusions),
        "n_insufficient": insufficient,
        "n_majority": len(majority),
        # 协同是否真的发生：会签条数（榜单痛点「独立判断或简单投票」的正面回答）
        "multi_author": n_multi_author,
        "mech_groups": mech.get("n_mech_groups"),
        "n_dissent": len(dissent_conclusions(dossier)),
        "n_rejected": len(dossier.rejected),
        "panel": dossier.panel,
        "flags_high": summary["n_high"],
        "flags_medium": summary["n_medium"],
        # 未执行的闸：亮灯为 0 不等于核对通过，这一栏就是防止「零警示」被当成成绩
        "flags_not_evaluated": len(not_eval),
        "not_evaluated_kinds": sorted(n["kind"] for n in not_eval),
        "clean": summary["clean"],
        "flags_by_kind": by_kind,
        "warrant_flags": by_kind.get("warrant_theme", 0),
        # 推理链完整性（第四分量）：中位数 + 断在哪一环。三种情形必须分开：
        # 有分数=计了；chain=None 且带 chain_detail=链上无从判定；
        # 整个键都不存在=这份产物是旧口径落盘，不能混进「无从判定」冒充测过
        "chain_median": (round(statistics.median(
            [p["chain"] for p in parts if p.get("chain") is not None]), 4)
            if any(p.get("chain") is not None for p in parts) else None),
        "chain_unknown": sum(1 for p in parts
                             if "chain" in p and p.get("chain") is None),
        "chain_stamped": sum(1 for p in parts if p.get("chain") is not None),
        "chain_legacy": sum(1 for p in parts if "chain" not in p),
        "chain_broken": {k: v for k, v in sorted(
            _chain_broken(parts).items(), key=lambda x: -x[1])},
        # 范围诚实闸亮灯数：声称了范围却没声明覆盖的结论条数
        "scope_flags": by_kind.get("scope", 0),
        "conf_max": round(max(confs), 4) if confs else 0.0,
        "conf_median": round(statistics.median(confs), 4) if confs else 0.0,
        "single_author": sum(1 for p in parts
                             if int(p.get("n_authors", 1) or 1) <= 1),
        "cited_segments": cited_real,
        "cited_share": round(cited_real / n_segments, 4) if n_segments else 0.0,
        "unused_topic": len(unused),
        "unused_ids": [u.get("segment") or u.get("id") or "" for u in unused][:8],
        "subq_total": len(subs),
        "subq_answered": sum(1 for s in subs if s["status"] == "answered"),
        "subq_gap": sum(1 for s in subs if s["status"] == "gap"),
        "subq_unanswered": sum(1 for s in subs if s["status"] == "unanswered"),
        "elapsed_s": acc.get("elapsed_s"),
        "tokens": acc.get("tokens"),
        "n_calls": acc.get("n_calls"),
        "repair_accept_rate": acc.get("repair_accept_rate"),
    }


def score_all(paths: list[Path]) -> list[dict]:
    """逐份打分；复放失败不静默——记成一行 error 并保留异常摘要。"""
    rows: list[dict] = []
    for p in paths:
        try:
            rows.append(score_artifact(p))
        except Exception as exc:              # noqa: BLE001 判分器不得因单份崩掉
            rows.append({"artifact": str(p), "error": f"{type(exc).__name__}: {exc}"})
    return rows


# ---------------------------------------------------------------- 打印

_COLS = [
    ("产物", "artifact", 42),
    ("结论", "n_majority", 5),
    ("会签", "multi_author", 4),
    ("归并", "mech_groups", 4),
    ("不足", "n_insufficient", 4),
    ("红", "flags_high", 3),
    ("黄", "flags_medium", 3),
    ("未执行", "flags_not_evaluated", 4),
    ("warrant", "warrant_flags", 7),
    ("范围", "scope_flags", 4),
    ("置信max", "conf_max", 8),
    ("链中位", "chain_median", 7),
    ("单署", "single_author", 4),
    ("覆盖", "cited_share", 6),
    ("未引", "unused_topic", 4),
    ("子问", "subq_answered", 4),
    ("秒", "elapsed_s", 7),
    ("token", "tokens", 8),
]


def _cell(row: dict, key: str, width: int) -> str:
    val = row.get(key)
    if key == "artifact":
        parts = Path(str(val)).parts
        text = "/".join(parts[-3:]) if parts[-1] == "report.json" else "/".join(parts)
        while len(text) > width and len(text.split("/", 1)) > 1:
            text = text.split("/", 1)[1]      # 从左裁掉，保住「案例/产物目录」
    elif key == "n_majority":
        text = str(val)
        if row.get("no_answer"):
            text = "0⚠"
    elif isinstance(val, float):
        text = f"{val:g}"
    else:
        text = "-" if val is None else str(val)
    return text[:width].ljust(width)


def print_table(rows: list[dict]) -> None:
    head = "  ".join(name.ljust(w) for name, _, w in _COLS)
    print(head)
    print("-" * len(head))
    for row in rows:
        if row.get("error"):
            print(f"⚠ 复放失败  {row['artifact']}  →  {row['error']}")
            continue
        print("  ".join(_cell(row, key, w) for _, key, w in _COLS))
    silent = [r for r in rows if r.get("no_answer") and not r.get("error")]
    if silent:
        print(f"\n⚠ 零可用结论 {len(silent)} 份——"
              "若该题本应作答就是事故；若是故意设的「资料不足」拒答题则属正常，"
              "需人工认一眼：")
        for r in silent:
            why = f"全部「资料不足」×{r['n_insufficient']}" if r["n_insufficient"] \
                else f"结论 {r['n_conclusions']} 条无一进主表"
            print(f"   · {r['artifact']}  →  {why}"
                  + (f"，且报告首屏拒答（{r['refuse_mark']}）" if r.get("refused") else ""))
    bad = [r for r in rows if r.get("refused") and not r.get("no_answer")]
    if bad:
        print(f"\n⚠ 首屏含拒答字样 {len(bad)} 份：" +
              "、".join(r["artifact"] for r in bad))
    kinds: dict[str, int] = {}
    for r in rows:
        for k, v in (r.get("flags_by_kind") or {}).items():
            kinds[k] = kinds.get(k, 0) + v
    if kinds:
        print("黄红灯明细（全集合计）：" +
              "  ".join(f"{k}={v}" for k, v in sorted(
                  kinds.items(), key=lambda kv: -kv[1])))


# ---------------------------------------------------------------- 基线比对

def diff_vs_baseline(rows: list[dict], base: dict[str, dict]) -> list[str]:
    """返回退化描述列表（空 = 无退化）。方向按 _HIGHER/_LOWER_BETTER 判。"""
    problems: list[str] = []
    for row in rows:
        if row.get("error"):
            problems.append(f"{row['artifact']} 复放失败：{row['error']}")
            continue
        old = base.get(row["artifact"])
        if not old:
            continue                     # 新产物没有基线可比，不算退化
        for key in sorted(_LOWER_BETTER):
            new, prev = row.get(key), old.get(key)
            if isinstance(new, (int, float)) and isinstance(prev, (int, float)) \
                    and new > prev:
                problems.append(f"{row['artifact']} {key} 变差 {prev} → {new}")
        for key in sorted(_HIGHER_BETTER):
            new, prev = row.get(key), old.get(key)
            if isinstance(new, (int, float)) and isinstance(prev, (int, float)) \
                    and new < prev:
                problems.append(f"{row['artifact']} {key} 变差 {prev} → {new}")
        if row.get("refused") and not old.get("refused"):
            problems.append(f"{row['artifact']} 从「作答」退化为「拒答」")
        if row.get("no_answer") and not old.get("no_answer"):
            problems.append(f"{row['artifact']} 从「有可用结论」退化为「零结论」")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="离线复放打分器（零 LLM）")
    ap.add_argument("paths", nargs="*", help="产物目录或 report.json 路径")
    ap.add_argument("--grep", default="", help="只保留路径含此子串的产物")
    ap.add_argument("--save", default="", help="把本次结果写入该 JSON 当基线")
    ap.add_argument("--check", default="", help="与该 JSON 基线比对，退化则退出码 1")
    args = ap.parse_args()

    paths = _resolve(args.paths) if args.paths else _default_artifacts()
    if args.grep:
        paths = [p for p in paths if args.grep in str(p)]
    if not paths:
        print("没有匹配到任何产物（检查路径或 --grep）", file=sys.stderr)
        return 2

    rows = score_all(paths)
    print_table(rows)

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({r["artifact"]: r for r in rows},
                                  ensure_ascii=False, sort_keys=True, indent=2),
                       encoding="utf-8")
        print(f"\n基线已存：{out}（{len(rows)} 份）")
    if args.check:
        base = json.loads(Path(args.check).read_text(encoding="utf-8"))
        problems = diff_vs_baseline(rows, base)
        if problems:
            print(f"\n✗ 相对基线退化 {len(problems)} 项：")
            for p in problems[:40]:
                print("  · " + p)
            return 1
        print("\n✓ 相对基线无退化")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
