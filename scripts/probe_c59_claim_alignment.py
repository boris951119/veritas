#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-59：提交面「部分一致」成因诊断（只量、零模型、app/ 零 diff）。

分类定义（一字不改，见工单）：
  ① 主体对但数字／时点错
  ② 范围过宽或过窄
  ③ 粒度不同（金标多条、我们归并成一条，或反之）
  ④ 判定方向相反
  ⑤ 语义方向对，但措辞口径不同
机械信号互相矛盾、或全都指不出方向 ⇒ 「待人工」（不许硬塞进第⑤类）。

机械信号（只许这三类；`why` 只展示、不分箱）：
  - 数字／时点 token 集合差：数字＝`app.core.numeric_check.extract_nums` 的
    raw 串（跳过紧贴字母的嵌入码，如 AI171）；时点＝下方 `_TIME_RE`
    命中原串；两侧集合对称差非空 ⇒ 数字／时点信号。范围／措辞用的内容词＝
    现成 `app.core.bm25._tokens` 双字切（零新增分词器）。
  - 条数差：金标该 `question_id` 行数 vs 我们 `conclusions.json` 同行数
    （提交层每题至多一条 headline）。
  - 方向词：只用 `scripts/run_eval.py` 的 `_OPPOSITIONS` 现成对立词表
    （不许新增领域词／专题词）；一侧命中 left、另一侧命中 right ⇒ 方向相反。

可修／不可修（判据 b）：
  ① 可修；② 可修；③ 不可修（提交层结构＝每题一条 headline，金标多行时
    无法在现结构里逐条对齐）；④ 可修；⑤ 可修；待人工＝不标可修。

原料默认：
  --base-rows  /tmp/s4runs/calib-20261026-171330/rows.jsonl
  --c57-rows   /tmp/s4runs/calib-20261026-171536/rows.jsonl
  案级 conclusions ← 各 summary.json 的 source
  金标 ← ~/Desktop/veritas-testcases/样例集-拓尔思-20261012/<案>/conclusions.json

禁品：禁止 import ModelClientFactory／client.chat／lock_local；产物只打 stdout
（可选 --out /tmp/...）；金标不进任何特征以外的用途（本探针只做离线集合差）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from app.core.bm25 import _tokens as _bm25_tokens  # 现成分词；禁 ModelClientFactory／lock_local／chat
from app.core.numeric_check import extract_nums
from scripts.run_eval import _OPPOSITIONS  # 现成方向词表

# 时点抽法（零模型）：年/月/日/时/分/「许」与 HH:MM
_TIME_RE = re.compile(
    r"(?:"
    r"\d{4}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?)?"
    r"|\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?"
    r"|\d{1,2}\s*日"  # 「8日晨」
    r"|\d{1,2}\s*时\s*\d{1,2}\s*分?(?:\s*\d{1,2}\s*秒)?"
    r"|\d{1,2}:\d{2}(?:\s*许)?"
    r"|\d{1,2}\s*时\s*许"
    r")"
)

CATS = (
    "①主体对但数字／时点错",
    "②范围过宽或过窄",
    "③粒度不同",
    "④判定方向相反",
    "⑤语义方向对但措辞口径不同",
    "待人工",
)

FIXABLE = {
    "①主体对但数字／时点错": ("可修", "数字／时点口径可在提交措辞或证据选取上对齐"),
    "②范围过宽或过窄": ("可修", "范围边界可在结论裁剪上收／放"),
    "③粒度不同": (
        "不可修",
        "提交层结构上每题只交一条 headline；金标若多行无法在现结构逐条对齐",
    ),
    "④判定方向相反": ("可修", "判定极性可在归并／仲裁侧改"),
    "⑤语义方向对但措辞口径不同": ("可修", "措辞口径可改、不必动判定合式"),
    "待人工": ("—", "机械信号矛盾或全无方向，不标可修"),
}


def _is_ascii_letter(ch: str) -> bool:
    return len(ch) == 1 and (("A" <= ch <= "Z") or ("a" <= ch <= "z"))


def _num_tokens(text: str) -> set[str]:
    """数字 token＝extract_nums 的 raw；跳过拉丁字母嵌入码（AI171／F-16）。

    ⚠ 只用 ASCII 字母判嵌入——`str.isalpha()` 对汉字也为真，会把「242人」整段误杀。
    """
    text = text or ""
    out: set[str] = set()
    for n in extract_nums(text):
        raw = (n.raw or "").strip()
        if not raw:
            continue
        i = text.find(raw)
        if i >= 0:
            j = i - 1
            if j >= 0 and text[j] == "-" and j >= 1:
                j -= 1
            left = text[j] if j >= 0 else ""
            right = text[i + len(raw)] if i + len(raw) < len(text) else ""
            if _is_ascii_letter(left) or _is_ascii_letter(right):
                continue
            # 「07级」班级届次＝编号不是计量数字
            if right == "级":
                continue
        out.add(re.sub(r"\s+", "", raw))
    return out


def _time_tokens(text: str) -> set[str]:
    return {re.sub(r"\s+", "", m.group(0)) for m in _TIME_RE.finditer(text or "")}


def _num_time_union(text: str) -> set[str]:
    """数字∪时点；去掉已被时点串覆盖的数字碎片（11月→11、19时44分→44）。"""
    times = _time_tokens(text)
    nums = {n for n in _num_tokens(text) if not any(n in t for t in times)}
    return nums | times


def _content_tokens(text: str) -> set[str]:
    """内容词＝仓库现成 BM25 双字切（`app.core.bm25._tokens`），零新增分词器。"""
    return set(_bm25_tokens(text or ""))


def _direction_opposite(a: str, b: str) -> bool:
    """现成 _OPPOSITIONS：一侧 left、另一侧 right（或反过来）。"""
    for left, right in _OPPOSITIONS:
        a_l = any(k in a for k in left)
        a_r = any(k in a for k in right)
        b_l = any(k in b for k in left)
        b_r = any(k in b for k in right)
        if (a_l and b_r) or (a_r and b_l):
            return True
    return False


def _same_side_polarity(a: str, b: str) -> bool:
    """两侧命中同一对立侧（同向）；两边都没命中不算同向信号。"""
    for left, right in _OPPOSITIONS:
        a_l = any(k in a for k in left)
        a_r = any(k in a for k in right)
        b_l = any(k in b for k in left)
        b_r = any(k in b for k in right)
        if (a_l and b_l and not a_r and not b_r) or (
            a_r and b_r and not a_l and not b_l
        ):
            return True
    return False


def classify(ours: str, gold: str, n_our_rows: int, n_gold_rows: int) -> dict:
    """返回 category／signals／detail；why 不参与。"""
    o, g = ours or "", gold or ""
    num_sym = _num_time_union(o) ^ _num_time_union(g)
    num_signal = bool(num_sym)

    oc, gc = _content_tokens(o), _content_tokens(g)
    # 范围：一方内容词真子集（且对方多出 ≥2 词，避免标点噪声）
    scope_narrow = bool(oc) and oc < gc and len(gc - oc) >= 2
    scope_wide = bool(gc) and gc < oc and len(oc - gc) >= 2
    scope_signal = scope_narrow or scope_wide

    row_signal = n_our_rows != n_gold_rows
    dir_opp = _direction_opposite(o, g)

    inter, sym = oc & gc, oc ^ gc
    # ⑤ 正向信号：有共享内容词、有措辞差、无数字时点差、无方向相反；
    # 同向极性命中加分但不强制（多数题词表打不中）
    wording_signal = (
        bool(inter) and bool(sym) and not num_signal and not dir_opp
        and len(inter) >= 2
    )

    hard: list[str] = []
    details: list[str] = []
    if num_signal:
        hard.append("①主体对但数字／时点错")
        details.append(
            f"数字／时点对称差={sorted(num_sym)[:12]}"
            f"{'…' if len(num_sym) > 12 else ''}"
        )
    if scope_signal:
        hard.append("②范围过宽或过窄")
        kind = "过窄（我方⊂金标）" if scope_narrow else "过宽（金标⊂我方）"
        details.append(f"范围={kind}；多出词数={len(gc - oc) if scope_narrow else len(oc - gc)}")
    if row_signal:
        hard.append("③粒度不同")
        details.append(f"条数差 金标行={n_gold_rows} vs 我方行={n_our_rows}")
    if dir_opp:
        hard.append("④判定方向相反")
        details.append("方向词=_OPPOSITIONS 左右侧交叉命中")

    soft_detail = ""
    if wording_signal:
        soft_detail = (
            f"措辞差：共享词={len(inter)} 对称差词={len(sym)}"
            + ("；同向极性命中" if _same_side_polarity(o, g) else "")
        )

    if len(hard) >= 2:
        cat = "待人工"
        reason = "机械信号互相矛盾：" + "＋".join(hard)
    elif len(hard) == 1:
        cat = hard[0]
        reason = details[0]
    elif wording_signal:
        cat = "⑤语义方向对但措辞口径不同"
        reason = soft_detail
    else:
        cat = "待人工"
        reason = "机械信号全指不出方向（无数字／时点差、无范围真子集、无条数差、无方向交叉、共享词不足）"

    return {
        "category": cat,
        "signal": reason,
        "signals_fired": hard + (["⑤"] if wording_signal else []),
        "n_our_rows": n_our_rows,
        "n_gold_rows": n_gold_rows,
        "fixable": FIXABLE[cat][0],
        "fix_note": FIXABLE[cat][1],
    }


def _load_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _source_from_summary(rows_path: Path) -> Path:
    summary = json.loads((rows_path.parent / "summary.json").read_text(encoding="utf-8"))
    src = Path(summary["source"])
    if not src.is_dir():
        raise SystemExit(f"summary.source 不是目录：{src}")
    return src


def _concl_by_qid(path: Path) -> dict[str, list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    if not isinstance(data, list):
        raise SystemExit(f"conclusions.json 不是数组：{path}")
    for row in data:
        qid = str(row.get("question_id") or "")
        out.setdefault(qid, []).append(str(row.get("conclusion") or ""))
    return out


def analyze_arm(
    label: str,
    rows_path: Path,
    gold_root: Path,
) -> dict:
    rows = _load_rows(rows_path)
    src = _source_from_summary(rows_path)
    summary = json.loads((rows_path.parent / "summary.json").read_text(encoding="utf-8"))
    agree = Counter(r.get("agreement") for r in rows)
    partial = [r for r in rows if r.get("agreement") == "部分一致"]

    items = []
    for r in partial:
        case, qid = r["case"], r["qid"]
        our_map = _concl_by_qid(src / case / "conclusions.json")
        gold_map = _concl_by_qid(gold_root / case / "conclusions.json")
        our_list = our_map.get(qid) or []
        gold_list = gold_map.get(qid) or []
        ours = our_list[0] if our_list else ""
        gold = gold_list[0] if gold_list else ""
        clf = classify(ours, gold, len(our_list), len(gold_list))
        items.append({
            "case": case,
            "qid": qid,
            "ours": ours,
            "gold": gold,
            "why_display": r.get("why") or "",
            **clf,
        })

    cat_counts = Counter(it["category"] for it in items)
    # 空交付：summary.n_sub_empty；并列出提交 headline 为空的题
    empty_q = []
    for r in rows:
        case, qid = r["case"], r["qid"]
        our_map = _concl_by_qid(src / case / "conclusions.json")
        texts = our_map.get(qid) or []
        if not texts or not any(t.strip() for t in texts):
            empty_q.append(f"{case}/{qid}")

    return {
        "label": label,
        "source": str(src),
        "rows_path": str(rows_path),
        "n_units": len(rows),
        "agree": dict(agree),
        "n_partial": len(partial),
        "n_sub_empty_summary": summary.get("n_sub_empty"),
        "empty_headlines": empty_q,
        "cat_counts": {c: cat_counts.get(c, 0) for c in CATS},
        "items": items,
    }


def _print_arm(arm: dict) -> None:
    print(f"\n======== {arm['label']} ========")
    print(f"source={arm['source']}")
    print(f"rows={arm['rows_path']}")
    a = arm["agree"]
    print(
        f"四态：一致={a.get('一致', 0)} 部分一致={a.get('部分一致', 0)} "
        f"不一致={a.get('不一致', 0)} 未答={a.get('未答', 0)} "
        f"（n_units={arm['n_units']}）"
    )
    print(
        f"空交付：summary.n_sub_empty={arm['n_sub_empty_summary']}；"
        f"headline 空题={arm['empty_headlines'] or '∅'}"
    )
    cc = arm["cat_counts"]
    parts = [cc[c] for c in CATS]
    formula = "+".join(str(x) for x in parts) + f"={sum(parts)}"
    print(f"判据 a：{'＋'.join(CATS)} ⇒ {formula} ；部分一致={arm['n_partial']} ⇒ "
          f"{'OK' if sum(parts) == arm['n_partial'] else 'FAIL'}")
    print("\n成因计数：")
    for c in CATS:
        fix, note = FIXABLE[c]
        print(f"  {c}  {cc[c]}  [{fix}] {note}")

    # 每类一条最小样例（首次出现）
    print("\n最小样例（每类第一条；两句原文逐字）：")
    seen: set[str] = set()
    for it in arm["items"]:
        cat = it["category"]
        if cat in seen:
            continue
        seen.add(cat)
        print(f"\n【{cat}】{it['case']}/{it['qid']}  信号={it['signal']}")
        print(f"  我方：{it['ours']}")
        print(f"  金标：{it['gold']}")
        print(f"  why(仅展示)：{it['why_display'][:160]}")

    print("\n逐题机械信号：")
    for it in arm["items"]:
        print(
            f"  {it['case'][:14]}/{it['qid']} → {it['category']}｜{it['signal']}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument(
        "--base-rows",
        default="/tmp/s4runs/calib-20261026-171330/rows.jsonl",
    )
    ap.add_argument(
        "--c57-rows",
        default="/tmp/s4runs/calib-20261026-171536/rows.jsonl",
    )
    ap.add_argument(
        "--gold-root",
        default=str(
            Path.home()
            / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
        ),
    )
    ap.add_argument("--out", default="", help="可选：把全文再写一份到 /tmp")
    args = ap.parse_args()

    gold_root = Path(args.gold_root)
    if not gold_root.is_dir():
        raise SystemExit(f"金标根不存在：{gold_root}")

    arms = [
        analyze_arm("基线臂 time-20261025-232801", Path(args.base_rows), gold_root),
        analyze_arm("C-57 臂 time-20261026-123957", Path(args.c57_rows), gold_root),
    ]

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        for arm in arms:
            _print_arm(arm)
        print("\n======== 成因表（两臂）========")
        print(f"{'类':<22}{'基线':>6}{'C-57':>6}{'可修':>8}")
        base_cc, c57_cc = arms[0]["cat_counts"], arms[1]["cat_counts"]
        for c in CATS:
            print(
                f"{c:<22}{base_cc[c]:>6}{c57_cc[c]:>6}{FIXABLE[c][0]:>8}"
            )
        bsum = sum(base_cc[c] for c in CATS)
        csum = sum(c57_cc[c] for c in CATS)
        bf = "+".join(str(base_cc[c]) for c in CATS) + f"={bsum}"
        cf = "+".join(str(c57_cc[c]) for c in CATS) + f"={csum}"
        print(f"判据 a 基线：{bf} （部分一致={arms[0]['n_partial']}）")
        print(f"判据 a C-57：{cf} （部分一致={arms[1]['n_partial']}）")
        print(
            f"判据 c 基线：一致={arms[0]['agree'].get('一致',0)} "
            f"部分={arms[0]['agree'].get('部分一致',0)} "
            f"不一致={arms[0]['agree'].get('不一致',0)} "
            f"未答={arms[0]['agree'].get('未答',0)} "
            f"空交付={arms[0]['n_sub_empty_summary']}"
        )
        print(
            f"判据 c C-57：一致={arms[1]['agree'].get('一致',0)} "
            f"部分={arms[1]['agree'].get('部分一致',0)} "
            f"不一致={arms[1]['agree'].get('不一致',0)} "
            f"未答={arms[1]['agree'].get('未答',0)} "
            f"空交付={arms[1]['n_sub_empty_summary']}"
        )
        ok = bsum == arms[0]["n_partial"] and csum == arms[1]["n_partial"]
        print(f"\n判据 a 总闸：{'PASS' if ok else 'FAIL'}")
        if not ok:
            raise SystemExit("判据 a 失败：分类和 ≠ 部分一致题数")

    text = buf.getvalue()
    print(text, end="")
    if args.out:
        outp = Path(args.out)
        outp.write_text(text, encoding="utf-8")
        print(f"\n[wrote] {outp}", flush=True)

    # 机器可读一份落 /tmp（不进仓库）
    dump = {
        "arms": [
            {
                **{k: v for k, v in arm.items() if k != "items"},
                "items": arm["items"],
            }
            for arm in arms
        ]
    }
    dump_path = Path("/tmp/c59_claim_alignment.json")
    dump_path.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[wrote] {dump_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
