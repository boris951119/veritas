"""C-121 件③ 统计判据：三臂配对的分离度＋置换检验（纯离线，读 json）。

判据写法＝C-120 定稿那套：
  ① 分布分离（各臂触到地板／天花的遍数＋Fisher 单侧左尾累计）
  ② 两臂合并后的均值差做全枚举置换检验（不靠正态假设）
不用「|Δ均值| ≤ 臂内跨度 ⇒ 噪声主导」那条自掩判据（已在 C-120 作废）。
"""

from __future__ import annotations

import itertools
import json
import pathlib
import statistics
from math import comb
from typing import Any

SRC = pathlib.Path("/tmp/c121/three_arm.json")
OUT_MD = pathlib.Path("/Users/liuboyu/Developer/veritas/artifacts/C121_three_arm_stats.md")
OUT_JSON = pathlib.Path("/Users/liuboyu/Developer/veritas/artifacts/C121_three_arm_stats.json")


def fisher_left(a: int, na: int, b: int, nb: int) -> float:
    """单侧左尾：a 组「成功数」比 b 组少的观测＋更极端情形的概率。"""
    k, n = a + b, na + nb
    tot = comb(n, na)
    tail = 0
    for x in range(0, min(a, k) + 1):
        if na - x > n - k or na - x < 0:
            continue
        tail += comb(k, x) * comb(n - k, na - x)
    return tail / tot if tot else 1.0


def perm_p(xs: list[float], ys: list[float]) -> tuple[float, float]:
    obs = abs(statistics.mean(xs) - statistics.mean(ys))
    pool = list(xs) + list(ys)
    n = len(xs)
    ge = tot = 0
    for combo in itertools.combinations(range(len(pool)), n):
        s = set(combo)
        a = [pool[i] for i in range(len(pool)) if i in s]
        b = [pool[i] for i in range(len(pool)) if i not in s]
        tot += 1
        if abs(statistics.mean(a) - statistics.mean(b)) >= obs - 1e-12:
            ge += 1
    return ge / tot, obs


def main() -> int:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    rows = d["rows"]
    arms = {m: [r for r in rows if r["arm"] == m] for m in ("off", "raw", "filt")}
    out: dict[str, Any] = {
        "schema_version": "c121.stats.v1",
        "passes_per_arm": d["passes_per_arm"],
        "model": d["model"], "temperature": d["temperature"],
        "rule": d["rule"], "leaks_total": d["leaks_total"],
        "arms": {}, "pairwise": {}, "per_pass": {},
    }
    for m, rs in arms.items():
        l3 = [r["l3"] for r in rs]
        ng = [r["nongold_cited"] for r in rs]
        lng = [r["list_nongold_cited"] for r in rs]
        out["arms"][m] = {
            "l3_sorted": sorted(l3), "l3_mean": round(statistics.mean(l3), 3),
            "l3_span": max(l3) - min(l3),
            "nongold_cited": ng, "nongold_mean": round(statistics.mean(ng), 2),
            "list_nongold_cited": lng,
            "doc_002_p3": f"{sum(1 for r in rs if r['doc_002_p3_cited'])}/{len(rs)}",
            "doc_012_p5": f"{sum(1 for r in rs if r['doc_012_p5_cited'])}/{len(rs)}",
            "check_fail": (f"{sum(r['check_fail_n'] for r in rs)}"
                           f"/{sum(r['check_fail_tot'] for r in rs)}"),
            "n_evidences": [r["n_evidences"] for r in rs],
            "wall_s_mean": round(statistics.mean([r["wall_s"] for r in rs]), 1),
            "block_chars": rs[0]["block_chars"],
            "list_n": rs[0]["list_n"], "list_gold": rs[0]["list_gold"],
            "leak": sum(len(r["text_leak"]) + len(r["ids_outside_box"]) for r in rs),
        }
    pairs = [("off", "raw"), ("off", "filt"), ("raw", "filt")]
    # 次要读数：非金标浪费（名单里非金标被引条数）也做同样两件事
    for a, b in pairs:
        wa = [r["list_nongold_cited"] for r in arms[a]]
        wb = [r["list_nongold_cited"] for r in arms[b]]
        na = [r["nongold_cited"] for r in arms[a]]
        nb = [r["nongold_cited"] for r in arms[b]]
        pw, obsw = perm_p([float(x) for x in wa], [float(x) for x in wb])
        pn, obsn = perm_p([float(x) for x in na], [float(x) for x in nb])
        out.setdefault("waste_pairwise", {})[f"{a}_vs_{b}"] = {
            "list_nongold_mean": [round(statistics.mean(wa), 2),
                                  round(statistics.mean(wb), 2)],
            "list_nongold_abs_diff": round(obsw, 3),
            "list_nongold_perm_p": round(pw, 4),
            "nongold_total_mean": [round(statistics.mean(na), 2),
                                   round(statistics.mean(nb), 2)],
            "nongold_total_abs_diff": round(obsn, 3),
            "nongold_total_perm_p": round(pn, 4),
        }
    for a, b in pairs:
        la = [r["l3"] for r in arms[a]]
        lb = [r["l3"] for r in arms[b]]
        p, obs = perm_p(la, lb)
        # 分离度：≤1 段（地板）与 ≥3 段的遍数
        low_a, low_b = sum(1 for v in la if v <= 1), sum(1 for v in lb if v <= 1)
        hi_a, hi_b = sum(1 for v in la if v >= 3), sum(1 for v in lb if v >= 3)
        out["pairwise"][f"{a}_vs_{b}"] = {
            "mean_a": round(statistics.mean(la), 3),
            "mean_b": round(statistics.mean(lb), 3),
            "abs_mean_diff": round(obs, 3), "perm_p_two_sided": round(p, 4),
            "l3_le1": f"{a} {low_a}/{len(la)}｜{b} {low_b}/{len(lb)}",
            "l3_ge3": f"{a} {hi_a}/{len(la)}｜{b} {hi_b}/{len(lb)}",
            "fisher_le1": round(fisher_left(low_b, len(lb), low_a, len(la)), 4),
            "n_per_comb": f"C({len(la) + len(lb)},{len(la)})",
        }
    for m, rs in arms.items():
        out["per_pass"][m] = [
            {"pass": r["pass"], "l3": r["l3"], "cited_gold": r["cited_gold_ids"],
             "nongold_cited": r["nongold_cited"],
             "list_nongold_cited": r["list_nongold_cited"],
             "check_fail": f"{r['check_fail_n']}/{r['check_fail_tot']}",
             "wall_s": r["wall_s"]}
            for r in rs
        ]
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    L = ["# C-121 件③ 统计 — q_003 三臂配对（每臂 %d 遍）" % d["passes_per_arm"], "",
         f"> 模型＝{d['model']}（本机 Ollama）· 温度＝None（未钉＝与 C-120 同口径）"
         f"· 泄漏合计 {d['leaks_total']}。规则＝{d['rule']}。", ""]
    for m in ("off", "raw", "filt"):
        a = out["arms"][m]
        L.append(
            f"- {m}：名单 {a['list_n']} 段（金标 {a['list_gold']}）·块 {a['block_chars']} 字"
            f"｜L3 {a['l3_sorted']} 均值 {a['l3_mean']}（跨度 {a['l3_span']}）"
            f"｜非金标被引 {a['nongold_cited']} 均值 {a['nongold_mean']}"
            f"｜名单里非金标被引 {a['list_nongold_cited']}"
        )
        L.append(
            f"  - doc_002#p3 {a['doc_002_p3']}｜doc_012#p5 {a['doc_012_p5']}"
            f"｜逐字核对失败 {a['check_fail']}｜证据条数 {a['n_evidences']}"
            f"｜墙钟均值 {a['wall_s_mean']}s｜泄漏 {a['leak']}"
        )
    L += ["", "## 两两对照（分布分离＋全枚举置换检验）", ""]
    for key, v in out["pairwise"].items():
        L.append(
            f"- {key}：均值 {v['mean_a']} → {v['mean_b']}（｜Δ｜{v['abs_mean_diff']}）"
            f"，置换双侧 p＝{v['perm_p_two_sided']}（{v['n_per_comb']} 全枚举）"
            f"；L3≤1 {v['l3_le1']}（Fisher 单侧 p＝{v['fisher_le1']}）；L3≥3 {v['l3_ge3']}"
        )
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
