# -*- coding: utf-8 -*-
"""提交面 vs 内部面：数「我们交了几条、没交的那些是什么态」——零 LLM，只读仓库外跑产物。

为什么这条要进仓库（协议 §5 ㉕：单里的「实测」必须是一条别人也拿得到的命令）：
C-21 出单（2026-10-18）时正文写了四个数＝内部结论 137／majority 40／insufficient 54／其余 43。
**10-21 深夜为发单重锚时，在同一份产物目录上重数＝141／40／58／2＋41**——54 与 137 是我当年
从「三桶之和」倒推的、不是数出来的（＝交接 §0 ㊴ 记的第 15 处自我订正）。没有这条命令，
下一张动导出层的单还会继续拿我抄错的数当期望值。

读的是**跑产物**，不是仓库内文件：官方样例集与 `cases/*/out*`、`/tmp/s4runs/` 都不入库
（坑 8），所以本脚本对「目录不存在／没有 report.json」的处理是**打印一句提示后正常退出 0**，
允许它先于任何功能入库。

三个基数各自的用途（都打在同一张表上，方便当场对账）：
1. **逐态真数**（majority／insufficient／dissent／merged）＋全量 ⇒ `字段说明.md` 那句样本面披露
   的期望值；merged 是「已并入组结论、只作溯源保留」的副本（`app/agents/arbiter.py:128`），
   **绝不能混进 M**，否则「内部结论 M 条」被虚增 29%（10-20 实测 49/169）。
2. **可核等式** `majority == confidence.json 行数` ⇒ 导出层那道 `status != "majority" ⇒ continue`
   还在不在（C-21 反向格的产物级证据，不必读代码）。
3. **零证据不对称** ⇒ `insufficient` 的 `evidence_ids` 两轮六案 113 条全空，
   `majority` 的 `evidence_ids` 两轮六案 97 条全非空 ⇒ 「凡进提交面必带证据；凡被标不足在提交面
   上等价于不存在」。这句是 C-13／C-19 要用的形状，也是本单不许「顺手把不足提进提交物」的事实依据。

用法：
    .venv/bin/python scripts/probe_sample_face.py [RUN_DIR ...]
    .venv/bin/python scripts/probe_sample_face.py            # 默认扫 /tmp/s4runs/time-*
给 RUN_DIR 时它应当是 `measure_s4_gates.py time` 那一层（下面长这样）：
    <RUN_DIR>/<案卷名>/{evidence.json,confidence.json,...,questions/<qid>/report.json}
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
from pathlib import Path

STATUSES = ("majority", "insufficient", "dissent", "merged")
PREFIX = "资料不足"


def scan_case(case_dir: Path) -> dict | None:
    files = sorted(glob.glob(str(case_dir / "questions" / "*" / "report.json")))
    if not files:
        return None
    st = collections.Counter()
    other = collections.Counter()
    insuff_no_prefix = 0
    insuff = insuff_zero = maj = maj_zero = 0
    for f in files:
        dossier = json.loads(Path(f).read_text(encoding="utf-8"))
        for con in dossier.get("conclusions", []) or []:
            s = str(con.get("status") or "")
            (st if s in STATUSES else other)[s] += 1
            has_ev = bool(con.get("evidence_ids"))
            if s == "insufficient":
                insuff += 1
                if not has_ev:
                    insuff_zero += 1
                if not str(con.get("statement") or "").strip().startswith(PREFIX):
                    insuff_no_prefix += 1
            elif s == "majority":
                maj += 1
                if not has_ev:
                    maj_zero += 1
    conf_rows = 0
    cf = case_dir / "confidence.json"
    if cf.is_file():
        conf_rows = len(json.loads(cf.read_text(encoding="utf-8")) or [])
    out = dict(name=case_dir.name, n_q=len(files), total=sum(st.values()) + sum(other.values()),
               conf_rows=conf_rows, insuff=insuff, insuff_zero=insuff_zero, maj=maj,
               maj_zero=maj_zero, insuff_no_prefix=insuff_no_prefix)
    for s in STATUSES:
        out[s] = st[s]
    out["other"] = dict(other)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", nargs="*", help="跑产物根目录（默认 /tmp/s4runs/time-*）")
    ap.add_argument("--root", default=os.environ.get("S4_RUNS_ROOT", "/tmp/s4runs"),
                    help="未给 runs 时从这里挑 time-* 目录")
    args = ap.parse_args(argv)

    runs = [Path(p) for p in args.runs]
    if not runs:
        runs = sorted(Path(args.root).glob("time-*"))
    if not runs:
        print(f"提示：没找到任何跑产物（试过的 root＝{args.root}）。")
        print("跑产物不入库属正常（AGENTS 坑 8）。要拿这组数就先跑一次：")
        print("  .venv/bin/python scripts/measure_s4_gates.py time <官方案例目录...>")
        return 0

    total = collections.Counter()
    others: dict[str, int] = collections.Counter()  # type: ignore[assignment]
    print("案卷 | 题 | 全量 | majority | insufficient | dissent | merged | "
          "conf行 | insuff零证据 | majority零证据 | insuff无前缀")
    for rd in runs:
        if not rd.is_dir():
            print(f"[跳过] 目录不存在：{rd}")
            continue
        rows = []
        for cd in sorted(p for p in rd.iterdir() if p.is_dir()):
            r = scan_case(cd)
            if r:
                rows.append(r)
        if not rows:
            print(f"[跳过] {rd}：其下没有 questions/*/report.json")
            continue
        print(f"\n### {rd}")
        for r in rows:
            for k in ("n_q", "total", "conf_rows", "insuff", "insuff_zero", "maj",
                      "maj_zero", "insuff_no_prefix", *STATUSES):
                total[k] += r[k]
            for k, v in r["other"].items():
                others[k] += v
            print(f"{r['name'][:22]} | {r['n_q']} | {r['total']} | {r['majority']} | "
                  f"{r['insufficient']} | {r['dissent']} | {r['merged']} | {r['conf_rows']} | "
                  f"{r['insuff_zero']}/{r['insufficient']} | {r['maj_zero']}/{r['majority']} | "
                  f"{r['insuff_no_prefix']}")

    t = total
    print("\n=== 合计 ===")
    print(f"题目录 {t['n_q']} ｜ 内部结论全量 {t['total']} ｜ majority {t['majority']} ｜ "
          f"insufficient {t['insufficient']} ｜ dissent {t['dissent']} ｜ merged {t['merged']}")
    if others:
        print(f"⚠ 状态机之外的取值（不在 evidence.py:194-200 那条枚举里）：{dict(others)}")
    summed = sum(t[s] for s in STATUSES) + sum(others.values())
    print(f"\n=== 可核等式 ===")
    print(f"① 逐态之和 {summed} == 全量 {t['total']}  ⇒ {'OK' if summed == t['total'] else '不成立'}")
    print(f"② confidence.json 行数 {t['conf_rows']} == majority {t['majority']}  ⇒ "
          f"{'OK（那道过滤还在）' if t['conf_rows'] == t['majority'] else '不成立（过滤被改过头）'}")
    print(f"③ non-merged 面 {t['total'] - t['merged']}（＝报告里『本次纳入』那一类计数用的口径，"
          f"见 measure_s4_gates.py:138／:381）")
    print(f"④ insufficient 零证据 {t['insuff_zero']}/{t['insufficient']} ｜ "
          f"majority 零证据 {t['maj_zero']}/{t['majority']}  ⇒ "
          f"{'不对称成立（不足态在提交面上等价于不存在）' if t['maj_zero'] == 0 else '⚠ 提交面出现了零证据多数态，查 C-15 裸结论闸'}")
    print(f"⑤ insufficient 不带「{PREFIX}」前缀 {t['insuff_no_prefix']}/{t['insufficient']}"
          f" ⇒ 这些行的句子是实质判断而状态是不足＝措辞与状态耦合，属 C-13／C-19 地界")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover
        pass
    sys.exit(main())
