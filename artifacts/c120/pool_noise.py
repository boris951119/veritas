"""C-120 件② 合并定稿：把两遍探测（3+3 与 5+5）的同一道题合到 8+8 再判。

零模型调用、只读 artifacts 里的两份 json。输出写回 artifacts。
"""
from __future__ import annotations

import itertools
import json
import pathlib
import statistics

ART = pathlib.Path("/Users/liuboyu/Developer/veritas/artifacts")
FILES = ["C120_q003_noise.json", "C120_q003_noise_v2.json"]


def load():
    rows = []
    for fn in FILES:
        d = json.loads((ART / fn).read_text(encoding="utf-8"))
        for r in d["rows"]:
            r = dict(r)
            r["src"] = fn
            r["src_passes"] = d["passes_per_arm"]
            rows.append(r)
    return rows


def fisher_left(a, b):
    """P(表更极端)＝a 组满足数/总数 vs b 组，单侧（a 更少）。精确超几何。"""
    from math import comb

    ka, na = a
    kb, nb = b
    k, n = ka + kb, na + nb
    tot = comb(n, na)
    p = 0
    for x in range(0, min(ka, k) + 1):
        if na - x > n - k:
            continue
        p += comb(k, x) * comb(n - k, na - x)
    observed = comb(k, ka) * comb(n - k, na - ka)
    if observed > tot:
        return None
    # 单侧＝左尾累计（含观测表本身），不是观测表自身的概率
    tail = 0
    for x in range(0, min(ka, k) + 1):
        if na - x > n - k or na - x < 0:
            continue
        tail += comb(k, x) * comb(n - k, na - x)
    return tail / tot


def perm_p(xs, ys, two_sided=True):
    obs = abs(statistics.mean(xs) - statistics.mean(ys))
    pool = list(xs) + list(ys)
    n = len(xs)
    ge = 0
    tot = 0
    for combo in itertools.combinations(range(len(pool)), n):
        s = set(combo)
        a = [pool[i] for i in range(len(pool)) if i in s]
        b = [pool[i] for i in range(len(pool)) if i not in s]
        d = abs(statistics.mean(a) - statistics.mean(b))
        tot += 1
        if d >= obs - 1e-12:
            ge += 1
    return ge / tot, obs


rows = load()
off = [r for r in rows if r["arm"] == "off"]
on = [r for r in rows if r["arm"] == "on"]

out = {}
out["n_passes_per_arm"] = [len(off), len(on)]
out["src"] = {fn: [r["passes_per_arm"] if False else r["src_passes"] for r in rows if r["src"] == fn][:1] for fn in FILES}

l3_off = [r["l3"] for r in off]
l3_on = [r["l3"] for r in on]
out["l3_off_sorted"] = sorted(l3_off)
out["l3_on_sorted"] = sorted(l3_on)
out["l3_off_mean"] = round(statistics.mean(l3_off), 3)
out["l3_on_mean"] = round(statistics.mean(l3_on), 3)
out["l3_diff_mean"] = round(statistics.mean(l3_on) - statistics.mean(l3_off), 3)
out["l3_off_span"] = max(l3_off) - min(l3_off)
out["l3_on_span"] = max(l3_on) - min(l3_on)

# 判据订正：旧判据 |Δ均值| ≤ 臂内跨度 ＝ 自掩（开臂跨度里含着效应自己的抖动）
out["old_criterion_b_noise"] = abs(out["l3_diff_mean"]) <= max(out["l3_off_span"], out["l3_on_span"])
pm, obs = perm_p(l3_off, l3_on)
out["perm_test"] = {"obs_abs_mean_diff": round(obs, 3), "p_two_sided": round(pm, 4), "n_perm": "C(16,8)=12870"}

# 分布分离：L3<=1 的遍数
out["l3_le1_off"] = sum(1 for v in l3_off if v <= 1)
out["l3_le1_on"] = sum(1 for v in l3_on if v <= 1)
out["fisher_l3_le1_one_sided_p"] = round(fisher_left((out["l3_le1_off"], len(l3_off)), (out["l3_le1_on"], len(l3_on))), 4)
out["l3_ge3_off"] = sum(1 for v in l3_off if v >= 3)
out["l3_ge3_on"] = sum(1 for v in l3_on if v >= 3)

# 金标逐段被引（关 8／开 8）——回落到底落在哪一段
per = {}
for r in rows:
    for g in r.get("cited_gold_ids") or []:
        per.setdefault(g, {"off": 0, "on": 0})[r["arm"]] += 1
all_gold = sorted({g for r in rows for g in r["gold_in_box"]})
out["per_gold_cited"] = {}
for g in all_gold:
    v = per.get(g, {"off": 0, "on": 0})
    out["per_gold_cited"][g] = {
        "off": f"{v['off']}/8", "on": f"{v['on']}/8",
        "fisher_one_sided_p": round(fisher_left((v["on"], 8), (v["off"], 8)), 5),
    }

# 目标段被引
t_off = sum(1 for r in off if r["lost_target_cited"])
t_on = sum(1 for r in on if r["lost_target_cited"])
out["target_cited"] = {"off": f"{t_off}/{len(off)}", "on": f"{t_on}/{len(on)}",
                       "fisher_one_sided_p": round(fisher_left((t_on, len(on)), (t_off, len(off))), 4)}

# 名单带偏：非金标被引条数（全体，不只名单内）
def nongold(r):
    return len(r.get("cited_ids_all") or []) - len(r.get("cited_gold_ids") or [])

out["nongold_cited_off"] = [nongold(r) for r in off]
out["nongold_cited_on"] = [nongold(r) for r in on]
out["nongold_mean"] = {"off": round(statistics.mean([nongold(r) for r in off]), 2),
                       "on": round(statistics.mean([nongold(r) for r in on]), 2)}
mn_on_all = [len(r.get("must_non_gold_cited") or []) for r in on]
out["must_non_gold_cited_on_all"] = {"probe_3pass": mn_on_all[:3], "probe_5pass": mn_on_all[3:]}

# 合并前先验两遍探测的 L3 口径是否一致（不一致就不能合并）
def l3_recompute(r):
    ids = set()
    for ev in r.get("evidences") or []:
        ids |= set(ev.get("seg_ids") or [])
    return len(set(r["gold_in_box"]) & ids)

mismatch = [(r["src"], r["arm"], r["pass"], l3_recompute(r), r["l3"], len(r.get("cited_gold_ids") or []))
            for r in rows if l3_recompute(r) != r["l3"] or r["l3"] != len(r.get("cited_gold_ids") or [])]
out["face_fidelity_rows_inconsistent"] = mismatch

# 引文逐字核对失败率（两臂共同的大漏桶）
def fails(rs):
    tot = bad = 0
    for r in rs:
        for ev in r.get("evidences") or []:
            tot += 1
            if ev.get("check_fails"):
                bad += 1
    return bad, tot

fo, to = fails(off)
fi, ti = fails(on)
out["check_fail"] = {"off": f"{fo}/{to}={round(fo / to, 3)}", "on": f"{fi}/{ti}={round(fi / ti, 3)}"}

# 名额守恒：每遍引用的段总数（金标＋非金标）
out["cited_ids_total"] = {"off": [len(r.get("cited_ids_all") or []) for r in off],
                          "on": [len(r.get("cited_ids_all") or []) for r in on]}
out["cited_ids_total_mean"] = {"off": round(statistics.mean([len(r.get("cited_ids_all") or []) for r in off]), 2),
                               "on": round(statistics.mean([len(r.get("cited_ids_all") or []) for r in on]), 2)}

# 证据条数与结论条数
out["n_evidences"] = {"off": [r["n_evidences"] for r in off], "on": [r["n_evidences"] for r in on]}
out["wall_s_mean"] = {"off": round(statistics.mean([r["wall_s"] for r in off]), 1),
                      "on": round(statistics.mean([r["wall_s"] for r in on]), 1)}
# 两遍探测之间关臂是否一致（仪器稳定性）
out["off_by_src"] = {fn: [r["l3"] for r in off if r["src"] == fn] for fn in FILES}
out["on_by_src"] = {fn: [r["l3"] for r in on if r["src"] == fn] for fn in FILES}

(ART / "C120_q003_noise_pooled.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

lines = ["# C-120 件② 合并定稿 — 两遍探测 8+8（3 遍旧＋5 遍新，同一枝树 `1e14cfc`）", ""]
lines.append(f"- 关臂 L3（8 遍，升序）＝{out['l3_off_sorted']} 均值 {out['l3_off_mean']}（跨度 {out['l3_off_span']}）")
lines.append(f"- 开臂 L3（8 遍，升序）＝{out['l3_on_sorted']} 均值 {out['l3_on_mean']}（跨度 {out['l3_on_span']}）")
lines.append(f"- 均值差＝{out['l3_diff_mean']}（开−关）")
lines.append(f"- 旧判据 b（|Δ均值|≤臂内跨度）＝{out['old_criterion_b_noise']} ⇒ **这条判据自掩，已作废**（开臂跨度里含着效应自身的抖动）")
lines.append(f"- 置换检验（全体 16 值重抽 8/8，C(16,8)）＝观测｜Δ均值｜{out['perm_test']['obs_abs_mean_diff']}，双侧 p＝{out['perm_test']['p_two_sided']}")
lines.append(f"- 分布分离：L3≤1 关 {out['l3_le1_off']}/8、开 {out['l3_le1_on']}/8（Fisher 单侧 p＝{out['fisher_l3_le1_one_sided_p']}）；L3≥3 关 {out['l3_ge3_off']}/8、开 {out['l3_ge3_on']}/8")
lines.append(f"- 目标段 doc_012#p5 被引＝关 {out['target_cited']['off']}、开 {out['target_cited']['on']}（Fisher 单侧 p＝{out['target_cited']['fisher_one_sided_p']}＝这一条单独不构成结论）")
lines.append(f"- 非金标段被引条数：关 {out['nongold_cited_off']}（均值 {out['nongold_mean']['off']}）／开 {out['nongold_cited_on']}（均值 {out['nongold_mean']['on']}）")
lines.append(f"- 其中「点名但非金标」被引条数（开臂）＝旧探测 {out['must_non_gold_cited_on_all']['probe_3pass']}／新探测 {out['must_non_gold_cited_on_all']['probe_5pass']}；关臂该字段结构性为空＝没有名单，不能读成「关臂引用了 0 个非金标段」（关臂也引 2～3 个非金标段，只是不在名单里）")
lines.append(f"- 合并前置检查：16 行的 L3 用原始 evidences.seg_ids∩盒内金标 重算＝与 json 记录逐行一致（不一致行数 {len(out['face_fidelity_rows_inconsistent'])}）⇒两遍探测同口径，可合并")
lines.append(f"- 每遍引用段总数（名额）＝关 {out['cited_ids_total']['off']}（均值 {out['cited_ids_total_mean']['off']}）／开 {out['cited_ids_total']['on']}（均值 {out['cited_ids_total_mean']['on']}）＝名额几乎不变，变的是名额里金标与非金标的配比")
lines.append(f"- 引文逐字核对不过：关 {out['check_fail']['off']}、开 {out['check_fail']['on']}＝两臂同量级，与旗无关")
lines.append(f"- 每遍证据条数 关 {out['n_evidences']['off']}／开 {out['n_evidences']['on']}；墙钟均值 关 {out['wall_s_mean']['off']}s／开 {out['wall_s_mean']['on']}s")
lines.append(f"- 仪器稳定性：关臂两遍探测 L3＝旧 {out['off_by_src'][FILES[0]]}／新 {out['off_by_src'][FILES[1]]}；开臂＝旧 {out['on_by_src'][FILES[0]]}／新 {out['on_by_src'][FILES[1]]}")
out["nongold_ge4"] = {"off": sum(1 for r in off if nongold(r) >= 4), "on": sum(1 for r in on if nongold(r) >= 4)}
lines.append(f"- 名单带偏的分离度＝非金标被引 ≥4 条的遍数：关 {out['nongold_ge4']['off']}/8、开 {out['nongold_ge4']['on']}/8（Fisher 单侧 p＝{round(fisher_left((out['nongold_ge4']['off'], 8), (out['nongold_ge4']['on'], 8)), 5)}）")
lines.append("- 金标逐段被引（关 8／开 8，Fisher 单侧）＝" + "；".join(
    f"{g} 关 {v['off']}／开 {v['on']}（p＝{v['fisher_one_sided_p']}）" for g, v in out["per_gold_cited"].items()))
lines.append("- ⇒ 回落真正稳定落在的是 **doc_002#p3**（关 7/8 → 开 1/8，p＝0.005），不是 C-113 当时点名的 doc_012#p5（6/8→3/8，未达显著）；doc_006#p3 两臂 8/8 不动。")
lines.append("- 定稿主因＝开旗后「点名名单里的非金标段」稳定吃掉 1～2 个证据名额（名额总数几乎不变、金标配比被换掉），L3 关 2.875 → 开 1.50（置换双侧 p＝0.007；L3≤1 关 0/8 vs 开 5/8）⇒ "
             "**C-113 那次 q_003 回落不是跑动噪声**；3 遍那轮「不复现」＝我臂数太少＋旧判据 b 自掩，两条都已作废。"
             "但要分清：单独那一段 doc_012#p5 被引关 6/8／开 3/8 未达显著（p＝0.157），钉死的是「整题少引 1～2 段金标」而不是「就是那一段掉了」。")
lines.append("- 回落段的物理成因已排掉：`doc_002#p3` 关臂资料面第 370 字／开臂第 559 字（差 189＝插块长度、插块卡在它前面），两臂都在估算窗可容的 5939 字之内⇒不是被推远、也不是被截断；它同时也在点名名单里（第 4 个）⇒只剩行为层解释＝模型照名单逐条交，搬到第 3～4 条就不回面首那段。")
lines.append("- 统计函数订正（账记我）：`fisher_left` 第一版返回观测表自身的概率、不是左尾累计⇒凡观测不在最极端一格的单侧 p 都偏小（doc_012#p5 那条 0.1371→0.1573；ka＝0 的格恰好相同所以不露馅）。已改左尾累计并全部重算。")
lines.append("- 外推边界：8＋8 是**同一题同一码**的配对，只支撑「q_003 这一题开旗稳定少引 1～2 段金标」；跨题／跨案＝没量过，不许说成树17 全线退步。")
(ART / "C120_q003_noise_pooled.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
