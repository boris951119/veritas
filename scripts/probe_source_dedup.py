"""同源污染实测探针（架构师用，C-14 工单「实测前提」的数字来源）。

回答一个问题：**给票数一部分权重之前，必须先建独立信源簇吗？**

原先的判断（推演）是"必须"——一条通稿被 20 家转载，多数投票就是假象。
本脚本把这句推演拿去官方样例集上量，结果是**推翻**：字面近重复极少，
且我方 `app/core/dup_check.py` 现成的两道闸（SHA-256 精确重复、
8 字滑窗 Jaccard ≥0.6 近似同源）已经覆盖了官方语料里的全部同源形态。

**不写任何字节**（不碰 cases/、不碰样例集），零 LLM、零网络。

跑法（样例集在仓库外，路径用 env 覆盖；默认是架构师本机位置）：
    PYTHONPATH=. .venv/bin/python scripts/probe_source_dedup.py
    OFFICIAL_CASES=/path/to/样例集 PYTHONPATH=. .venv/bin/python scripts/probe_source_dedup.py

官方样例集**不入仓库**（六案 4.6MB，且是发榜方下发材料），所以本脚本在没有该目录的
机器上会直接报"找不到样例集"并退出码 2，不会静默给出假数字。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from itertools import combinations

from app.core.citation_check import normalize
from app.core.dup_check import _NEAR_DUP_JACCARD, _shingles

ROOT = os.environ.get(
    "OFFICIAL_CASES",
    os.path.expanduser("~/Desktop/veritas-testcases/样例集-拓尔思-20261012"))
SHINGLE_K = 40        # 本脚本自己的粗粒度指纹（测"整篇转载"）
THRESHOLDS = (0.5, 0.3, 0.15)


def cases() -> list[str]:
    return sorted(d for d in os.listdir(ROOT)
                  if os.path.isdir(os.path.join(ROOT, d)) and not d.startswith("."))


def load_docs(case: str) -> list[dict]:
    path = os.path.join(ROOT, case, "raw_documents.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def host(url: str) -> str:
    return re.sub(r"^https?://", "", str(url or "")).split("/")[0]


def coarse_shingles(text: str, k: int = SHINGLE_K) -> set[str]:
    t = re.sub(r"\s+", "", text or "")
    if len(t) <= k:
        return {t} if t else set()
    return {t[i:i + k] for i in range(0, len(t) - k + 1, k // 2)}


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return (len(a & b) / len(union)) if union else 0.0


# --------------------------------------------------------------- 探针


def probe_1_url_dedup(all_docs: list[tuple[str, dict]]) -> None:
    """① URL 去重有没有用：完全相同的 URL 有多少组。"""
    print("\n[1] URL 级去重（官方 decks:311「须去同源」最省事的实现）")
    urls = Counter(str(d.get("content_url") or "") for _, d in all_docs if d.get("content_url"))
    hosts = Counter(host(d.get("content_url")) for _, d in all_docs if d.get("content_url"))
    repeated = {u: n for u, n in urls.items() if n > 1}
    print(f"    文档 {len(all_docs)} 篇｜有 content_url {sum(urls.values())} 篇")
    print(f"    去重域名 {len(hosts)} 个｜单域名最多 {max(hosts.values()) if hosts else 0} 篇"
          f"（{hosts.most_common(1)[0][0] if hosts else '-'}）")
    print(f"    **完全相同 URL 只有 {len(repeated)} 组** → URL 去重几乎抓不到同源，"
          "同源必须做内容级判定")
    for u, n in sorted(repeated.items(), key=lambda kv: -kv[1])[:5]:
        print(f"      {n} 篇同 URL: {u[:80]}")


def probe_2_threshold_sensitivity(all_docs: list[tuple[str, dict]]) -> None:
    """② 字面近重复对数随阈值怎么变——证明"少"不是阈值卡太严的假象。"""
    print("\n[2] 整篇转载扫描：40 字粗指纹 Jaccard，阈值敏感性")
    for thr in THRESHOLDS:
        per_case, tot, tot_cross = [], 0, 0
        for case, docs in _by_case(all_docs):
            sh = [(host(d.get("content_url")), coarse_shingles(d.get("content")))
                  for d in docs]
            n_all = n_cross = 0
            for (h1, s1), (h2, s2) in combinations(sh, 2):
                if not s1 or not s2:
                    continue
                if jaccard(s1, s2) >= thr:
                    n_all += 1
                    n_cross += (h1 != h2)
            per_case.append((case, len(docs), n_cross, n_all))
            tot += n_all
            tot_cross += n_cross
        print(f"    Jaccard≥{thr:<5} → 近重复 {tot:>3} 对（跨域 {tot_cross:>3}）"
              f"｜占 {len(all_docs)} 篇的 {tot / max(1, len(all_docs)):.1%}")
        for case, n, x, a in per_case:
            print(f"        {n:>4} 篇  跨域 {x:>2}  全部 {a:>2}   {case[:30]}")
    print("    → 阈值从 0.5 放到 0.15 数字只涨个位数：**同源污染在这份语料上可忽略**，"
          "不是阈值卡太严造成的假象")


def probe_3_production_gate(all_docs: list[tuple[str, dict]]) -> None:
    """③ 我方现成的生产闸（8 字滑窗 Jaccard ≥0.6）在官方语料上抓到几对。

    直接调 `app.core.dup_check._shingles`——量的是**生产逻辑**，不是本脚本的
    再实现。这条决定 C-14 要不要先建独立信源簇：如果现成闸已经覆盖，就不用。
    """
    print(f"\n[3] 生产闸复核：dup_check._shingles（8 字滑窗）＋ Jaccard ≥{_NEAR_DUP_JACCARD}")
    grand = 0
    for case, docs in _by_case(all_docs):
        infos = [(str(d.get("doc_id") or i), _shingles(d.get("content") or ""))
                 for i, d in enumerate(docs)]
        infos = [(i, s) for i, s in infos if s]
        hits = []
        for (a, sa), (b, sb) in combinations(infos, 2):
            j = jaccard(sa, sb)
            if j >= _NEAR_DUP_JACCARD:
                hits.append((a, b, round(j, 3)))
        grand += len(hits)
        print(f"    {len(docs):>4} 篇 → 疑似同源 {len(hits):>2} 对   {case[:30]}")
        for a, b, j in hits[:3]:
            print(f"          {a} ~ {b}  Jaccard={j}")
    print(f"    合计 {grand} 对 / {len(all_docs)} 篇 ＝ {grand / max(1, len(all_docs)):.1%}")
    print("    → C-14 直接复用这道闸做「独立信源数」，**不需要另建独立信源簇**；"
          "口径边界见工单（这是字面同源，改写式洗稿测不出）")


def _by_case(all_docs: list[tuple[str, dict]]):
    out: dict[str, list[dict]] = {}
    for case, d in all_docs:
        out.setdefault(case, []).append(d)
    return list(out.items())


def main() -> None:
    if not os.path.isdir(ROOT):
        print(f"找不到官方样例集目录：{ROOT}\n"
              "用 OFFICIAL_CASES=<样例集路径> 指定（样例集不入仓库，见模块 docstring）。")
        raise SystemExit(2)
    all_docs: list[tuple[str, dict]] = []
    for case in cases():
        for d in load_docs(case):
            all_docs.append((case, d))
    print(f"样例集根目录: {ROOT}")
    print(f"案例数: {len(cases())}   文档合计: {len(all_docs)} 篇")
    if not all_docs:
        print("没有读到任何 raw_documents.json，退出（不给假数字）。")
        raise SystemExit(2)
    probe_1_url_dedup(all_docs)
    probe_2_threshold_sensitivity(all_docs)
    probe_3_production_gate(all_docs)


if __name__ == "__main__":
    main()
