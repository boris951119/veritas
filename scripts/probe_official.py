"""官方样例集实测探针（架构师用，C-12 工单「实测前提」七条数字的来源）。

只读官方样例集，把工单里引用的每个数字重算一遍并打印。工单说"逐条可重算"，
靠的就是这个文件。**不写任何字节**（不碰 cases/、不碰样例集），零 LLM、零网络。

跑法（样例集在仓库外，路径用 env 覆盖；默认是架构师本机位置）：
    .venv/bin/python scripts/probe_official.py
    OFFICIAL_CASES=/path/to/样例集 .venv/bin/python scripts/probe_official.py

官方样例集**不入仓库**（六案 4.6MB，且是发榜方下发材料），所以本脚本在没有该目录的
机器上会直接报"找不到样例集"并退出码 2，不会静默给出假数字。
"""

from __future__ import annotations

import json
import os
import re
import statistics
from collections import Counter

ROOT = os.environ.get(
    "OFFICIAL_CASES",
    os.path.expanduser("~/Desktop/veritas-testcases/样例集-拓尔思-20261012"))
DENSITY = 0.687        # 实测中文 tok/字（C-9 前置实测）
BUDGET = 80_000        # app/config.py material_char_budget 默认（字）
CTX_LOCAL = 16_384     # 本机 Ollama Modelfile num_ctx
SEGMENT_MAX = 650      # app/core/material.py 渲染截断


def cases() -> list[str]:
    return sorted(d for d in os.listdir(ROOT)
                  if os.path.isdir(os.path.join(ROOT, d)) and not d.startswith("."))


def load(case: str, name: str):
    with open(os.path.join(ROOT, case, name), encoding="utf-8") as f:
        return json.load(f)


def probe_1_scale() -> None:
    print("=" * 78)
    print("① 规模与「理论最小必读量」：金标段字数 vs 预算 vs 本机窗口")
    print("=" * 78)
    print(f"{'案例':<24}{'文档':>5}{'总字数':>10}{'金标段字数':>10}"
          f"{'占比':>7}{'超预算':>8}{'超窗口':>8}")
    td = tc = 0
    for c in cases():
        docs = load(c, "raw_documents.json")
        byid = {d["doc_id"]: d for d in docs}
        gold = load(c, "evidence_samples.json")
        total = sum(len(d.get("content") or "") for d in docs)
        need, seen = 0, set()
        for e in gold:
            d = byid.get(e["doc_id"])
            if not d:
                continue
            paras = {p["para_id"]: p for p in (d.get("paragraphs") or [])}
            p = paras.get(e["para_id"])
            key = (e["doc_id"], e["para_id"])
            if not p or key in seen:
                continue
            seen.add(key)
            need += p["char_end"] - p["char_start"]
        td += len(docs)
        tc += total
        win_chars = CTX_LOCAL / DENSITY
        print(f"{c[:22]:<24}{len(docs):>5}{total:>10,}{need:>10,}"
              f"{100 * need / total:>6.1f}%{total / BUDGET:>7.1f}x"
              f"{need / win_chars:>7.2f}x")
    print(f"{'合计':<24}{td:>5}{tc:>10,}")
    print(f"  本机窗口 {CTX_LOCAL} tok ÷ {DENSITY} tok/字 ≈ {CTX_LOCAL / DENSITY:,.0f} 字"
          f"  →  六案金标段全部装得下＝上表「超窗口」列均 < 1.00x")


def probe_2_para_semantics() -> None:
    print()
    print("=" * 78)
    print("② para_id 语义：金标 quote 与段偏移的关系（决定适配层能否保全匹配键）")
    print("=" * 78)
    rel = Counter()
    qlen, plen, miss = [], [], 0
    for c in cases():
        byid = {d["doc_id"]: d for d in load(c, "raw_documents.json")}
        for e in load(c, "evidence_samples.json"):
            d = byid.get(e["doc_id"])
            if not d:
                rel["doc_id 缺失"] += 1
                continue
            content = d.get("content") or ""
            paras = {p["para_id"]: p for p in (d.get("paragraphs") or [])}
            p = paras.get(e["para_id"])
            if not p:
                miss += 1
                rel["para_id 在 paragraphs 里找不到"] += 1
                continue
            full = content[p["char_start"]:p["char_end"]]
            q = e["quote"]
            qlen.append(len(q))
            plen.append(p["char_end"] - p["char_start"])
            if full == q:
                rel["quote == 该段完整切片"] += 1
            elif q in full:
                rel["quote 是该段的真子串"] += 1
            elif full in q:
                rel["quote 跨段（该段切片是 quote 的子串）"] += 1
            elif content.find(q) < 0:
                rel["quote 在 content 里找不到"] += 1
            else:
                rel["quote 跨多段（位置可定位）"] += 1
    for k, v in rel.most_common():
        print(f"  {v:>4}  {k}")
    print(f"  para_id 缺失合计: {miss}")
    print(f"  金标 quote 字数: 中位 {statistics.median(qlen):.0f} "
          f"p90 {sorted(qlen)[int(len(qlen) * .9)]} max {max(qlen)}")
    print(f"  金标所在段字数: 中位 {statistics.median(plen):.0f} "
          f"p90 {sorted(plen)[int(len(plen) * .9)]} max {max(plen)}"
          f"   ← max > SEGMENT_MAX={SEGMENT_MAX}，故禁止二次切段")


def probe_3_noise_segments() -> None:
    print()
    print("=" * 78)
    print("③ 噪声段：全库段长分布，以及「<5 字的段是否承载金标」")
    print("=" * 78)
    allp, goldp = [], []
    for c in cases():
        byid = {d["doc_id"]: d for d in load(c, "raw_documents.json")}
        for d in byid.values():
            for p in (d.get("paragraphs") or []):
                allp.append(p["char_end"] - p["char_start"])
        for e in load(c, "evidence_samples.json"):
            d = byid.get(e["doc_id"])
            if not d:
                continue
            for p in (d.get("paragraphs") or []):
                if p["para_id"] == e["para_id"]:
                    goldp.append(p["char_end"] - p["char_start"])
    tiny = sum(1 for x in allp if x < 5)
    print(f"  全库段落 {len(allp):,} 段：中位 {statistics.median(allp):.0f} 字，"
          f"<5 字 {tiny} 段（{100 * tiny / len(allp):.1f}%），max {max(allp):,} 字")
    print(f"  >SEGMENT_MAX({SEGMENT_MAX}) 的段: {sum(1 for x in allp if x > SEGMENT_MAX)} 段")
    print(f"  金标所在段 {len(goldp)} 个，其中 <5 字的 = {sum(1 for x in goldp if x < 5)} 个"
          f"   ← 0 即「过滤 <5 字段安全」的依据")


def probe_4_credibility() -> None:
    print()
    print("=" * 78)
    print("④ source_credibility 与「是否承载金标证据」的相关性")
    print("=" * 78)
    pairs = []
    for c in cases():
        docs = load(c, "raw_documents.json")
        byid = {d["doc_id"]: d for d in docs}
        gd = {e["doc_id"] for e in load(c, "evidence_samples.json") if e["doc_id"] in byid}
        cg = [byid[d]["source_credibility"] for d in gd
              if isinstance(byid[d].get("source_credibility"), (int, float))]
        cn = [d["source_credibility"] for d in docs if d["doc_id"] not in gd
              and isinstance(d.get("source_credibility"), (int, float))]
        ranked = sorted(docs, key=lambda d: -(d.get("source_credibility") or 0))
        pos = [ranked.index(byid[d]) + 1 for d in gd]
        print(f"  {c[:20]:<22} 金标文档 {len(gd):>3} 篇  cred 均值 "
              f"{statistics.mean(cg):.3f} vs 非金标 {statistics.mean(cn):.3f}"
              f"（差 {statistics.mean(cg) - statistics.mean(cn):+.3f}）"
              f"  金标文档 cred 中位排名 第{statistics.median(pos):.0f}/{len(docs)}")
        for d in docs:
            v = d.get("source_credibility")
            if isinstance(v, (int, float)):
                pairs.append((v, 1 if d["doc_id"] in gd else 0))
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)
    r = cov / (statistics.pstdev(xs) * statistics.pstdev(ys))
    hi = [y for x, y in pairs if x >= 0.85]
    lo = [y for x, y in pairs if x < 0.60]
    print(f"\n  全 {len(pairs)} 篇点二列相关 r = {r:+.4f}   ← 近零")
    print(f"  cred>=0.85 的 {len(hi)} 篇承载金标 {sum(hi)} 篇（{100 * sum(hi) / len(hi):.0f}%）")
    print(f"  cred< 0.60 的 {len(lo)} 篇承载金标 {sum(lo)} 篇（{100 * sum(lo) / len(lo):.0f}%）")
    print(f"  全体基准 {100 * sum(ys) / len(ys):.0f}%   → 该字段禁用于检索排序／过滤")


def probe_5_gold_defects() -> None:
    print()
    print("=" * 78)
    print("⑤ 金标与原始数据自身的缺陷（不是圣经，评分器必须容错）")
    print("=" * 78)
    t = Counter()
    argbad = Counter()
    kj = n = 0
    for c in cases():
        for d in load(c, "raw_documents.json"):
            pt = (d.get("publish_time") or "").strip()
            if not pt:
                t["publish_time 为空"] += 1
            elif re.match(r"^\d{4}-\d{2}-\d{2}", pt):
                t["publish_time 可解析"] += 1
            else:
                t["publish_time 是相对时间或站点名"] += 1
                if len(t) < 99:
                    argbad[f"publish_time 异常值: {pt[:12]}"] += 1
        for e in load(c, "evidence_samples.json"):
            a = e.get("argument") or {}
            n += 1
            if "数值口径" in a:
                kj += 1
            for k in a:
                if k not in ("时间", "主体", "地点", "内容", "影响", "数值口径"):
                    argbad[f"argument 非规范键「{k}」"] += 1
            for req in ("主体", "内容"):
                if req not in a:
                    argbad[f"argument 缺「{req}」"] += 1
    for k, v in t.most_common():
        print(f"  {v:>4}  {k}")
    print(f"  金标证据 {n} 条，带「数值口径」槽 {kj} 条（{100 * kj / n:.0f}%）")
    for k, v in argbad.most_common(12):
        print(f"  {v:>4}  {k}")


def probe_6_concentration() -> None:
    print()
    print("=" * 78)
    print("⑥ 金标证据的文档集中度（召回难点在「超长单文档内定位段落」）")
    print("=" * 78)
    for c in cases():
        docs = load(c, "raw_documents.json")
        byid = {d["doc_id"]: d for d in docs}
        per = Counter(e["doc_id"] for e in load(c, "evidence_samples.json")
                      if e["doc_id"] in byid)
        top = per.most_common(3)
        s = "  ".join(
            f"{k}({v}条/{len(byid[k].get('content') or '') :,}字/{len(byid[k].get('paragraphs') or [])}段"
            f"/cred {byid[k].get('source_credibility')})".replace(" ,", ",")
            for k, v in top)
        print(f"  {c[:20]:<22} 金标落 {len(per):>3}/{len(docs):<4} 篇   Top: {s}")


def main() -> None:
    if not os.path.isdir(ROOT):
        print(f"找不到官方样例集目录：{ROOT}\n"
              f"用 OFFICIAL_CASES=<样例集路径> 指定（样例集不入仓库，见模块 docstring）。")
        raise SystemExit(2)
    print(f"样例集根目录: {ROOT}")
    print(f"案例数: {len(cases())}   常量: DENSITY={DENSITY} BUDGET={BUDGET:,} "
          f"CTX_LOCAL={CTX_LOCAL} SEGMENT_MAX={SEGMENT_MAX}")
    probe_1_scale()
    probe_2_para_semantics()
    probe_3_noise_segments()
    probe_4_credibility()
    probe_5_gold_defects()
    probe_6_concentration()


if __name__ == "__main__":
    main()
