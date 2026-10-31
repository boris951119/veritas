"""C-43 口头票／丁＝precision 路线定向量尺（只读探针）。

问题：六案产物里 rejected 可定位段（约 60 条）能不能用**只依赖我方产物**
的机械规则压到十几条、同时保住已知 exact 命中（约 11），使
Precision_conf ≥ 0.55（评分 2.5 精度档 2 分）？

纪律：
- 零 LLM、零网络、不写 app/、不把样例集／六案产物复制进仓。
- 规则一律先按机制定、不看金标挑；金标只用于事后评分。
- 候选池＝C-42 丁档 rejected 一路（同 `_stream_rejected` 定位口径）。
- 不改导出／判定主路径；本脚本是定向量尺。

跑法：
    OFFICIAL_RUN=/tmp/s4runs/time-20261023-173124 \\
        .venv/bin/python scripts/probe_conflict_precision.py

环境变量（均可覆盖；缺目录或空目录 ⇒ 退出码 2，不许静默印 0）：
    OFFICIAL_CASES  官方样例集根（默认 ~/Desktop/veritas-testcases/样例集-拓尔思-20261012）
    OFFICIAL_RUN    六案跑产物根（默认 /tmp/s4runs/time-20261023-173124）
"""

from __future__ import annotations

from typing import Callable

import glob
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.core.evidence import Dossier  # noqa: E402
from app.core.fact_ledger import find_collisions  # noqa: E402
from app.export.official import _segment_locator  # noqa: E402

# 复用 C-41／C-42 同探针的 rejected 定位与金标换形（不许另造口径）
from scripts.probe_conflict_coverage import (  # noqa: E402
    _REJECTED_SEG_RE,
    _gold_conf_items,
    _stream_rejected,
)

OFFICIAL_CASES = os.environ.get(
    "OFFICIAL_CASES",
    os.path.expanduser("~/Desktop/veritas-testcases/样例集-拓尔思-20261012"),
)
OFFICIAL_RUN = os.environ.get(
    "OFFICIAL_RUN",
    "/tmp/s4runs/time-20261023-173124",
)

_NUM_RE = re.compile(r"\d")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
# 多口径／伤亡人数类词＝机制特征（金标 partial_support 常见主题，非金标字面）
_METRIC_RE = re.compile(
    r"(伤亡|遇难|死亡|人数|生还|失踪|面积|公里|米|吨|人次|游客|"
    r"比例|百分之|％|%|口径|为准|计入|不含|截至|统计|约|至少|累计)"
)
_KOU_RE = re.compile(r"(口径|为准|计入|不含|含|截至|统计|约|至少|累计|分别|两种|不同)")
_P_TIER = 0.55  # 官方精度档 2 分线


def _die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _require_dir(label: str, path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_dir():
        _die(f"找不到{label}目录：{p}")
    return p


def _case_of(report_path: str, run_root: Path) -> str:
    """report 相对跑次根的第一级目录名＝案名。"""
    rel = Path(report_path).resolve().relative_to(run_root.resolve())
    return rel.parts[0]


def _load_reports(run_root: Path) -> list[tuple[str, Path, Dossier]]:
    paths = sorted(glob.glob(str(run_root / "*/questions/*/report.json")))
    if not paths:
        _die(f"跑次目录下找不到 report.json：{run_root}")
    out: list[tuple[str, Path, Dossier]] = []
    for p in paths:
        case = _case_of(p, run_root)
        raw = json.loads(Path(p).read_text(encoding="utf-8"))
        out.append((case, Path(p), Dossier.from_dict(raw)))
    return out


def _gold_by_case(cases_root: Path) -> tuple[dict[str, set[tuple[str, str]]], list[dict]]:
    """逐案金标段键＋全量 conflicting_facts 条目（91 条口径）。"""
    by_case: dict[str, set[tuple[str, str]]] = {}
    all_items: list[dict] = []
    case_dirs = sorted(
        d for d in cases_root.iterdir()
        if d.is_dir() and (d / "conclusions.json").is_file()
    )
    if not case_dirs:
        _die(f"官方样例集下无 conclusions.json：{cases_root}")
    for cd in case_dirs:
        items = _gold_conf_items(cd)
        keys = {
            (str(it["doc_id"]), str(it["para_id"]))
            for it in items
            if it.get("doc_id") and it.get("para_id")
        }
        by_case[cd.name] = keys
        all_items.extend(items)
    return by_case, all_items


def _para_use_counts(dossier: Dossier) -> dict[tuple[str, str], int]:
    """(doc,para) → 被多少条结论引用。"""
    use: dict[tuple[str, str], set[str]] = defaultdict(set)
    for c in dossier.conclusions:
        for ev in dossier.evidences_of(c.id):
            for sid in ev.segment_ids:
                loc = _segment_locator(dossier, sid)
                if loc and loc[0] and loc[1]:
                    use[loc].add(c.id)
    return {k: len(v) for k, v in use.items()}


def _build_rejected_pool(
    reports: list[tuple[str, Path, Dossier]],
) -> dict[tuple[str, str], dict]:
    """跨报告并 rejected 可定位段；附机制特征（只读我方产物）。

    键＝(doc_id, para_id)；与 C-42 丁档 rejected 一路同形。
    """
    # 先扫四路标签，便于「两路以上重叠」特征（仍不扩候选池）
    route_tags: dict[tuple[str, str], set[str]] = defaultdict(set)
    conflict_tie: set[tuple[str, str]] = set()
    ledger_cross: set[tuple[str, str]] = set()
    ledger_spread: dict[tuple[str, str], float] = {}
    used_by: dict[tuple[str, str], int] = defaultdict(int)
    seg_text: dict[tuple[str, str], str] = {}

    for _case, _path, d in reports:
        for loc, n in _para_use_counts(d).items():
            used_by[loc] = max(used_by[loc], n)
        for src in d.sources or []:
            doc_id = str((src.meta or {}).get("doc_id") or src.id or "")
            for seg in src.segments or []:
                key = (doc_id, str(seg.id))
                text = getattr(seg, "text", "") or ""
                if text and key not in seg_text:
                    seg_text[key] = text
        for pair in (d.conflicts or []):
            if not isinstance(pair, dict):
                continue
            a_id, b_id = pair.get("a_id"), pair.get("b_id")
            res = pair.get("resolution") if isinstance(pair.get("resolution"), dict) else {}
            win = res.get("winner_id")
            tie = win not in (a_id, b_id)
            for cid in [x for x in (a_id, b_id) if x]:
                for ev in d.evidences_of(cid):
                    for sid in ev.segment_ids:
                        loc = _segment_locator(d, sid)
                        if not loc or not loc[0] or not loc[1]:
                            continue
                        route_tags[loc].add("conflicts")
                        if tie:
                            conflict_tie.add(loc)
        for col in find_collisions(d):
            vals = [abs(x.value) for x in col.facts if x.value is not None]
            spread = (max(vals) / min(vals)) if vals and min(vals) > 0 else 0.0
            for fa in col.facts:
                loc = _segment_locator(d, fa.seg_id)
                if not loc or not loc[0] or not loc[1]:
                    continue
                route_tags[loc].add("fact_ledger")
                if col.cross_source:
                    ledger_cross.add(loc)
                ledger_spread[loc] = max(ledger_spread.get(loc, 0.0), spread)
        for con in d.conclusions:
            if con.status != "dissent":
                continue
            for ev in d.evidences_of(con.id):
                for sid in ev.segment_ids:
                    loc = _segment_locator(d, sid)
                    if loc and loc[0] and loc[1]:
                        route_tags[loc].add("dissent")

    pool: dict[tuple[str, str], dict] = {}
    raw_n = 0
    discarded_n = 0
    for case, _path, d in reports:
        raw_n += len([r for r in (d.rejected or []) if isinstance(r, dict)])
        entries, discarded, _empty = _stream_rejected(d)
        discarded_n += len(discarded)
        for e in entries:
            key = (e["doc_id"], e["para_id"])
            route_tags[key].add("rejected")
            quote = str(e.get("text") or e.get("statement") or "")
            # 原文优先用 segment 文本；没有就用 quote
            body = seg_text.get(key) or quote
            feat = pool.get(key)
            if feat is None:
                feat = {
                    "case": case,
                    "doc_id": key[0],
                    "para_id": key[1],
                    "quote": quote,
                    "body": body,
                    "routes": set(),
                }
                pool[key] = feat
            else:
                # 同段多报告：合并 quote／body（更长者优先）
                if len(quote) > len(feat["quote"]):
                    feat["quote"] = quote
                if len(body) > len(feat["body"]):
                    feat["body"] = body
            feat["routes"] |= route_tags.get(key, set()) | {"rejected"}

    for key, feat in pool.items():
        quote = feat["quote"]
        body = feat["body"]
        feat["routes"] = set(feat["routes"]) | route_tags.get(key, set())
        feat["n_routes"] = len(feat["routes"])
        feat["has_num"] = bool(_NUM_RE.search(quote))
        feat["has_year"] = bool(_YEAR_RE.search(quote))
        feat["metric_hit"] = bool(_METRIC_RE.search(quote))
        feat["kou"] = bool(_KOU_RE.search(body) or _KOU_RE.search(quote))
        feat["quote_len"] = len(quote)
        feat["used_by_concl"] = used_by.get(key, 0)
        feat["tie"] = key in conflict_tie
        feat["cross_source"] = key in ledger_cross
        feat["spread"] = ledger_spread.get(key, 0.0)
        feat["multi_route"] = feat["n_routes"] >= 2

    meta = {
        "raw_rejected": raw_n,
        "discarded": discarded_n,
        "locable_unique": len(pool),
    }
    return pool, meta


# 规则＝机制先验；金标只事后评分。名字固定，便于复放对照。
RULES: list[tuple[str, Callable[[dict], bool]]] = [
    ("0 rejected 全部（起点）", lambda e: True),
    ("1 rejected∧引文含数字", lambda e: e["has_num"]),
    ("2 rejected∧引文含年份", lambda e: e["has_year"]),
    ("3 rejected∧引文含人数/口径词", lambda e: e["metric_hit"]),
    ("4 rejected∧段含口径词", lambda e: e["kou"]),
    ("5 rejected∧两路以上重叠", lambda e: e["multi_route"]),
    ("6 rejected∧被≥2结论引用", lambda e: e["used_by_concl"] >= 2),
    ("7 rejected∧引文≤80字", lambda e: e["quote_len"] <= 80),
    ("8 rejected∧引文≤120字", lambda e: e["quote_len"] <= 120),
    ("9 rejected∧数字∧口径词", lambda e: e["has_num"] and e["kou"]),
    ("10 rejected∧数字∧两路重叠", lambda e: e["has_num"] and e["multi_route"]),
    ("11 rejected∧数字∧引文≤120", lambda e: e["has_num"] and e["quote_len"] <= 120),
    ("12 rejected∧平局冲突同段", lambda e: e["tie"]),
    ("13 rejected∧对撞cross_source", lambda e: e["cross_source"]),
    ("14 rejected∧数字∧年份", lambda e: e["has_num"] and e["has_year"]),
    ("15 rejected∧数字∧人数词∧≤120字",
     lambda e: e["has_num"] and e["metric_hit"] and e["quote_len"] <= 120),
]


def _score(
    keys: list[tuple[str, str]],
    gold_keys: set[tuple[str, str]],
    gold_n_items: int,
) -> dict:
    n = len(keys)
    hits = sum(1 for k in keys if k in gold_keys)
    p = 0.0 if n == 0 else hits / n
    r_keys = 0.0 if not gold_keys else hits / len(gold_keys)
    r_items = 0.0 if gold_n_items == 0 else hits / gold_n_items
    return {
        "n": n,
        "hits": hits,
        "fp": n - hits,
        "P": p,
        "R_keys": r_keys,
        "R_items": r_items,
        "ge_055": p >= _P_TIER if n else False,
    }


def _print_table(title: str, rows: list[tuple[str, dict]]) -> None:
    print(title)
    print(f"{'规则':<36}{'交出':>6}{'命中':>6}{'假阳':>6}{'P':>8}{'≥0.55':>6}")
    for name, s in rows:
        flag = "YES" if s["ge_055"] else "no"
        if s["n"] == 0:
            print(f"{name:<36}{0:>6}{'—':>6}{'—':>6}{'—':>8}{'—':>6}")
        else:
            print(
                f"{name:<36}{s['n']:>6}{s['hits']:>6}{s['fp']:>6}"
                f"{s['P']:>8.3f}{flag:>6}"
            )


def main() -> int:
    cases_root = _require_dir("官方样例集", OFFICIAL_CASES)
    run_root = _require_dir("六案跑产物", OFFICIAL_RUN)

    print("=== C-43／丁 precision 定向量尺（零 LLM、零网络）===")
    print(f"OFFICIAL_CASES={cases_root}")
    print(f"OFFICIAL_RUN={run_root}")
    print(
        "复算："
        f"OFFICIAL_CASES={cases_root} OFFICIAL_RUN={run_root} "
        ".venv/bin/python scripts/probe_conflict_precision.py"
    )

    gold_by_case, gold_items = _gold_by_case(cases_root)
    gold_keys = set().union(*gold_by_case.values()) if gold_by_case else set()
    print(
        f"金标 conflicting_facts 条目={len(gold_items)}；"
        f"去重段键={len(gold_keys)}；案数={len(gold_by_case)}"
    )

    reports = _load_reports(run_root)
    print(f"report.json 份数={len(reports)}")
    pool, meta = _build_rejected_pool(reports)
    print(
        f"rejected 原始={meta['raw_rejected']}；"
        f"因定位不到丢弃={meta['discarded']}；"
        f"可定位去重段键（起点）={meta['locable_unique']}"
    )
    if meta["locable_unique"] == 0:
        _die("rejected 可定位段为空——四路全空时不许静默印 0 当结论")

    # —— 主表：全六案 in-sample ——
    rows: list[tuple[str, dict]] = []
    for name, cond in RULES:
        keys = [k for k, e in pool.items() if cond(e)]
        rows.append((name, _score(keys, gold_keys, len(gold_items))))
    _print_table("\n【主表】rejected 池上机械规则（金标只事后评分）", rows)

    base = rows[0][1]
    print(
        f"\n起点＝rejected 全部：交出 {base['n']}、命中 {base['hits']}、"
        f"P={base['P']:.3f}（目标：压到十几条且保住 ~{base['hits']} 命中、P≥{_P_TIER}）"
    )

    # 达标规则（in-sample）
    passers = [(n, s) for n, s in rows if s["n"] > 0 and s["ge_055"]]
    near = sorted(
        [(n, s) for n, s in rows if s["n"] > 0],
        key=lambda x: (-x[1]["P"], x[1]["n"]),
    )
    print("\n【in-sample 最优】按 P 降序前 5：")
    for n, s in near[:5]:
        print(
            f"  · {n}: 交出 {s['n']} 命中 {s['hits']} "
            f"P={s['P']:.3f} R_keys={s['R_keys']:.4f}"
        )

    # —— 留一案交叉：每案轮流 unseen；在其余五案上按 P 选（n≥8 才有资格）——
    print("\n【留一案交叉】规则只在其余五案上按 P 选（训练集 n≥8），评被留出案：")
    case_names = sorted(gold_by_case)
    picked: list[tuple[str, str, float, int, int]] = []
    for hold in case_names:
        best = None  # (rule_name, train_P, train_n)
        for name, cond in RULES:
            train_keys = [k for k, e in pool.items() if cond(e) and e["case"] != hold]
            if len(train_keys) < 8:
                continue
            train_gold = set().union(
                *(gold_by_case[c] for c in case_names if c != hold)
            )
            tp = sum(1 for k in train_keys if k in train_gold) / len(train_keys)
            if best is None or tp > best[1]:
                best = (name, tp, len(train_keys))
        if best is None:
            print(f"  留出 {hold[:24]}：无合格规则（训练集 n≥8）")
            continue
        cond = dict(RULES)[best[0]]
        test_keys = [k for k, e in pool.items() if cond(e) and e["case"] == hold]
        hit = sum(1 for k in test_keys if k in gold_by_case[hold])
        picked.append((hold, best[0], best[1], len(test_keys), hit))
        p_s = f"{hit / len(test_keys):.3f}" if test_keys else "—"
        print(
            f"  留出 {hold[:24]} 训练选「{best[0]}」训练P={best[1]:.3f} "
            f"⇒ unseen 交出 {len(test_keys)} 命中 {hit} P={p_s}"
        )
    tn = sum(p[3] for p in picked)
    th = sum(p[4] for p in picked)
    gen_p = (th / tn) if tn else 0.0
    if tn:
        print(f"  合计 unseen＝交出 {tn}、命中 {th} ⇒ **泛化 P={gen_p:.3f}**")
    else:
        print("  合计 unseen＝无可评交出")

    # —— 可达上限 ——
    print("\n【逐案可达上限】池内能定位到的金标真段／该案金标段键：")
    pool_keys = set(pool)
    for c in case_names:
        gk = gold_by_case[c]
        reach = sum(1 for k in gk if k in pool_keys)
        print(
            f"  {c[:28]:<28} 金标段键 {len(gk):2d}  池内可达 {reach:2d} "
            f"⇒ 召回上限 {reach / len(gk) if gk else 0:.2f}"
        )
    reach_unique = len(pool_keys & gold_keys)
    print(
        f"  合计池内可达金标段键（去重）={reach_unique}/{len(gold_keys)} "
        f"⇒ 召回键上限 {reach_unique / len(gold_keys) if gold_keys else 0:.4f}"
        f"（逐案加总会因跨案同键虚高，以去重为准）"
    )

    # —— 硬结论 ——
    best_name, best_s = near[0]
    print("\n======== 硬结论 ========")
    print(
        f"rejected 起点：{base['n']} 条 → 规则后最优「{best_name}」："
        f"{best_s['n']} 条、命中 {best_s['hits']}/{base['hits']}、"
        f"P={best_s['P']:.3f}"
    )
    if passers:
        print(
            f"in-sample 有 {len(passers)} 条规则 P≥{_P_TIER}："
            + "；".join(f"{n}(P={s['P']:.3f},n={s['n']})" for n, s in passers)
        )
    else:
        print(f"in-sample **没有任何**规则达到 P≥{_P_TIER}。")
    print(f"留一案交叉泛化 P={gen_p:.3f}（unseen 交出 {tn}／命中 {th}）。")

    buy = bool(passers) and gen_p >= _P_TIER
    # 更严：即便 in-sample 过线，泛化不过也不算买得到
    if passers and gen_p < _P_TIER:
        verdict = (
            f"**这 2 分买不到**：in-sample 虽有规则过 {_P_TIER}，"
            f"但留一案泛化 P={gen_p:.3f}＜{_P_TIER}；"
            "只在自家六案上量、unseen 4 专题更无保证。"
        )
    elif passers and gen_p >= _P_TIER:
        verdict = (
            f"**这 2 分买得到（有条件）**：in-sample 与留一案泛化均 ≥{_P_TIER}；"
            "仍须在 unseen 4 专题复核，且本尺未改主路径。"
        )
    else:
        verdict = (
            f"**这 2 分买不到**：机械规则压 rejected "
            f"做不到 P≥{_P_TIER}（最优 in-sample P={best_s['P']:.3f}，"
            f"泛化 P={gen_p:.3f}）；代价半小时已花完，死心。"
        )
    print(verdict)
    print(
        "边界：本尺只读探针、未改 app/ 判定／导出；"
        "官方第二步是大模型语义判定、本探针不做。"
    )
    print(f"BUYABLE_2PTS={'yes' if buy else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
