"""C-29 台账的三组基数（规模／过滤触发率／报告占比）——零 LLM，只读仓库外样例集。

为什么这条要进仓库（协议 §5 ㉕：单里的「实测」必须是一条别人也拿得到的命令）：
2026-10-20 C-29 第一轮验收打回那一格（R1），用的三组数此前只存在于我的 `/tmp` 探针里——
隔一天连我自己都复放不了。从此「新增那一节会不会把报告撑爆」「那道『定位不到就不生成』
的过滤开不开火」＝**一条可粘贴命令的输出**，第二轮验收与以后任何一张动 `precedent.py` 的单
都拿它对账（`.venv/bin/python scripts/probe_precedent_scale.py`）。

三种议题形状都要看，因为结论相反：
- **官方真实题面**（`conclusions.json` 里的 question，与 `measure_s4_gates.py:113` 同口径）
  ⇒ 行数很小（10-20 实测 0～21 行）；
- **案卷名当议题**＝AGENTS 第 4 步 `python -m app.pipeline <官方案例目录>` 那条 CLI 路的
  **默认形状**（`load_case` 给不出更具体的问题，`d.question` 就是目录名）
  ⇒ 议题锚退化、台账**无界生成**（10-20 第一轮实测 835／844 行，那一节占整份 `report.md` 的
  **90%／93%**——占比按 `sec_len*100//md_len` 下取整，旧句「91%」那支临时脚本 round 上来的）；
  第二轮 R1 返工后同一六态被双上限削到 **22／0／2／18／6／2** 行、最大占比 **24%**（见 C-29 第二轮验收）；
- 自家 `cases/`（入库）⇒ 当前 0 行，＝判据夹具的形状。

每行还带三列返工口径（C-29 第一轮打回那一格 R1 的判据基数）：**台账真数行数**（渲染截断后必须
披露「另有 N 组未展示」，N＝真数−展示数）、**引文落在 JSON 脚手架的行数**（`"doc_id"`/`"para_id"`/
`"text"` 出现在引文里＝那一行人读不了）、**其余节合计字数与其 1/3**（R1 要的那道"本节不许盖过报告"
的相对闸，分母刻意取「不含本节的其余节」以避免与本节字数互相定义、循环无解）。

本脚本**不调模型、不写任何仓库内产物**；`app/core/precedent.py` 尚未入库时（C-29 未收口）
打印一句提示后退出，执行方在自己含该模块的树上跑就有数。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OFFICIAL = os.environ.get(
    "OFFICIAL_CASES",
    os.path.expanduser("~/Desktop/veritas-testcases/样例集-拓尔思-20261012"))


def _rows_and_dropped(dossier) -> tuple[int, int, int]:
    """（候选对数, 生成行数, 被过滤数）＝那道「定位不到就不生成」的真实触发率。

    与 `build_precedent_ledger` 同一判据、同一取引文方式，只是把过滤前后的两个数都数出来
    （生产只给过滤后的那个，所以「这道闸开不开火」此前没人量过——C-29 判据 c② 就栽在这）。
    """
    from app.core import precedent as P

    pairs = P._candidate_pairs(dossier)
    dropped = 0
    for cur, prior, _timed in pairs:
        _sc, seg_c = P._seg_by_id(dossier, cur.seg_id)
        _sp, seg_p = P._seg_by_id(dossier, prior.seg_id)
        if seg_c is None or seg_p is None:
            dropped += 1
            continue
        q_c = P._quote_around(seg_c.text, cur.raw)
        q_p = P._quote_around(seg_p.text, prior.raw)
        if not P._locatable(q_c, seg_c.text) or not P._locatable(q_p, seg_p.text):
            dropped += 1
    return len(pairs), len(pairs) - dropped, dropped


def _section_share(dossier) -> tuple[int, int, int, int, int, int, int]:
    """（整份 report.md 字数, 那一节字数, 那一节 bullet 行数, 台账真实行数,
    引文落在 JSON 脚手架里的行数, 截断披露行数, 展示对照行数）。

    节字数与行数**从 `render_report_md` 的产物里切出来量**，不直调
    `render_precedent_lines`——生产路径的双上限（行数帽＋其余节字数 1/3）
    只在那条路上生效，直调会少走字数闸，量与产品对不上（第二轮 R1 验收订正）。

    后三列是 R1 那几格的口径：
    - 台账真实行数 vs 本节行数＝**渲染有没有截断**（截断后必须写"另有 N 组未展示"）；
    - 引文脚手架＝官方卷段落粒度把 JSON 字段留在段文本里，切出的"引文"其实是
      `"doc_id": "doc_006"` 这类键名 ⇒ 那一行人读不了（不是 C-29 的台账逻辑错，是料形状）。
    """
    from app.core.hashchain import HashChain
    from app.core.precedent import build_precedent_ledger
    from app.pipeline import render_report_md

    ledger = build_precedent_ledger(dossier)
    dossier.accounting["precedent"] = ledger.to_dict()
    md = render_report_md(dossier, HashChain(), [])
    title = "## 同类事件对照（案卷内）"
    lines = md.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == title), None)
    if start is None:                      # 节没渲出来＝产品缺陷，按 0 行记录
        sec_lines: list[str] = []
    else:
        end = next((j for j in range(start + 1, len(lines))
                    if lines[j].startswith("## ")), len(lines))
        sec_lines = lines[start:end]
    n_bullets = sum(1 for ln in sec_lines if ln.startswith("- "))
    n_pairs = sum(1 for ln in sec_lines if ln.startswith("- 指标："))
    n_hidden = sum(1 for ln in sec_lines if "未展示" in ln and "另有" in ln)
    scaffold = sum(
        1 for r in ledger.rows
        if any(m in (r.current_quote or "") + (r.prior_quote or "")
               for m in ('"doc_id"', '"para_id"', '"text"')))
    return (len(md), len("\n".join(sec_lines)), n_bullets, len(ledger.rows),
            scaffold, n_hidden, n_pairs)


def one(case_dir: Path, qid: str, question: str, title: str) -> tuple[int, int]:
    from app.core.fact_ledger import extract_facts
    from app.core.material import pack_material

    from app.ingest.case_loader import load_case

    t0 = time.perf_counter()
    # 每题一份干净案卷，别共享上题的 accounting
    dossier = load_case(case_dir, fetch_links=False)
    dossier.question = question or dossier.question
    extract_facts(dossier)
    t1 = time.perf_counter()
    pairs, kept, dropped = _rows_and_dropped(dossier)
    pack = pack_material(dossier)
    dossier.accounting["material_pack_selected"] = sorted(pack["selected"])
    md_len, sec_len, n_bul, n_rows, scaffold, n_hidden, n_pairs = _section_share(dossier)
    pct = sec_len * 100 // max(md_len, 1)
    rest = max(md_len - sec_len, 1)          # 「本节 ≤ 其余节合计 1/3」那道闸的分母（不含本节）
    gate = rest // 3
    # 双上限合规：展示对照行 ≤ 24；本节字数 ≤ 其余节 1/3
    cap_ok = n_pairs <= 24 and sec_len <= gate
    print(f"  [{title}] {qid:<12} {(question or '（议题为空）')[:34]:<36} "
          f"候选对={pairs:>4} 生成={kept:>4} 被过滤={dropped:>2}｜"
          f"该节 {n_bul:>4} 行／{sec_len:>7,} 字＝整份报告 {md_len:>7,} 字的 {pct:>2}%｜"
          f"台账真数 {n_rows:>4} 行｜展示 {n_pairs} 行｜披露行 {n_hidden}｜脚手架引文 {scaffold:>4} 行｜"
          f"其余节 {rest:>7,} 字（1/3 闸＝{gate:,}）｜双上限={'OK' if cap_ok else '❌超'}｜"
          f"用时 {time.perf_counter()-t0:.2f}s（抽事实 {t1-t0:.2f}s）")
    return pairs, dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None, help="只跑案卷名含该子串的官方案")
    ap.add_argument("--official-q", action="store_true",
                    help="只跑官方真实题面（默认两种议题形状都跑）")
    args = ap.parse_args()

    try:
        import app.core.precedent  # noqa: F401
    except ImportError:
        print("本树还没有 app/core/precedent.py（＝C-29 未收口）⇒ 无基数可量。"
              "执行方请在含该模块的交付树上跑本脚本。")
        return 0

    print("=== ① 入库演示案（判据夹具的形状）===")
    for cd in sorted((ROOT / "cases").iterdir()):
        if (cd / "manifest.yaml").exists():
            one(cd, "(manifest)", "", "自家演示案")

    print("\n=== ② 官方六案：真实题面 vs 议题＝案卷名（CLI 默认形状）===")
    root = Path(OFFICIAL)
    if not root.exists():
        print(f"样例集不在 {root}——这一段跳过（① 已跑完）")
        return 0
    tot_pairs = tot_drop = 0
    for cd in sorted(root.iterdir()):
        if not (cd / "conclusions.json").exists():
            continue
        if args.case and args.case not in cd.name:
            continue
        rows = json.loads((cd / "conclusions.json").read_text(encoding="utf-8"))
        seen: dict[str, str] = {}
        for r in rows:
            qid = str(r.get("question_id") or "").strip()
            q = str(r.get("question") or "").strip()
            if qid and q and qid not in seen:
                seen[qid] = q
        shapes = sorted(seen.items())
        if not args.official_q:
            shapes = shapes + [("(案卷名)", cd.name)]
        for qid, q in shapes:
            p, dr = one(cd, qid, q, "官方题面" if qid != "(案卷名)" else "案卷名议题")
            tot_pairs += p
            tot_drop += dr
    print(f"\n=== 过滤触发率合计（官方六案·全部议题形状）＝候选对 {tot_pairs:,}、"
          f"被「定位不到就不生成」摘掉 {tot_drop} 行 ===")
    print("⇒ 合计为 0 时这道闸＝belt-and-braces，不许对外写成"
          "「已验证的过滤能力」（＝C-29 判据 c② 的订正依据）。")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # pragma: no cover
        pass
    sys.exit(main())
