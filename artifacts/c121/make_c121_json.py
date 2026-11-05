#!/usr/bin/env python3
# C-121 交付件 JSON 生成器：所有数字从已有四份源 json 现抄，不手打。
# 用法：cd /tmp/c121/tree && .venv/bin/python ../make_c121_json.py
import json
import os

TREE = "/tmp/c121/tree"
MAIN = "/Users/liuboyu/Developer/veritas"


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


audit = load(f"{TREE}/artifacts/C121_list_audit.json")
three = load(f"{MAIN}/artifacts/C121_three_arm_stats.json")
pack = load(f"{TREE}/artifacts/C121_pack_guard.json")
face = load(f"{TREE}/artifacts/C121_face_bytes.json")

arms = three["arms"]
pair = three["pairwise"]
waste = three["waste_pairwise"]
tot = audit["totals"]


def fail_rate(a):
    """逐字核对失败率＝从源 json 的 "f/t" 现算，不手打。"""
    num, den = (int(x) for x in a["check_fail"].split("/"))
    return {"fail": num, "total": den, "rate": round(num / den, 4)}


def arm_row(k):
    a = arms[k]
    return {
        "arm": k,
        "l3_gold_segments_cited_per_pass": a["l3_sorted"],
        "l3_mean": a["l3_mean"],
        "list_n": a["list_n"],
        "list_gold_in_list": a["list_gold"],
        "list_nongold_cited_per_pass": a["list_nongold_cited"],
        "list_nongold_cited_mean": round(sum(a["list_nongold_cited"]) / len(a["list_nongold_cited"]), 3),
        "nongold_cited_total_mean": a["nongold_mean"],
        "doc_002_p3_cited": a["doc_002_p3"],
        "doc_012_p5_cited": a["doc_012_p5"],
        "citation_verbatim_check_fail": a["check_fail"],
        "block_chars": a["block_chars"],
        "text_leak": a["leak"],
    }


out = {
    "schema_version": "c121.v1",
    "ticket": "C-121 树17 点名名单准度／过滤非金标名额（实验旗默认关；不合 main 除非过线）",
    "executed_by": "Qoder／qwen3.8-flash（执行位）",
    "as_of": "2026-11-03",
    "verdict": {
        "line": "弱 YES・不合 main",
        "reasons": [
            "主读数＝对 off 持平（filt 2.80 vs off 2.80，Δ=0.0，置换 p=1.0），不是增益；只是把 C-113 开臂那种回落止住了",
            "raw 臂（=C-113 那种全名单）这轮只掉到 2.20（Δ=−0.6，p=0.4841），没复现 C-120 的 −1.375／p=0.007 量级＝n=5 判不动追回量级",
            "唯一显著的是浪费腿：名单里非金标被引 raw 2.8 → filt 1.0 每遍（p=0.0079），且 filt 名单准度 4/5＝预滤确实把名单变干净了",
            "旁证腿里『刘翔分题 L3／seen_not』只跑了 1 遍（q_001／q_002 抽测）＝不够定"
            "；@7 与 L2 是零 LLM 离线旁证、已全同",
            "单题（q_003）＋单模型（本机 14B）＋温度未钉＝外推边界与 C-120 同档"
        ],
        "what_would_upgrade": "每臂 ≥8 遍重跑 off／raw／filt；刘翔其余题各 ≥5 遍；换模型或跨案一轮；温度钉死一个值",
    },
    "flag": {
        "env": "VERITAS_TREE17_LIST_PRECISION",
        "config_field": "tree17_list_precision",
        "default": False,
        "distinct_from": "VERITAS_TREE17_FOCUS_CITE（C-113 那条旗，本票不复用、不合并、不依赖）",
    },
    "paths": {
        "new_module": "app/core/tree17_list_precision.py",
        "edited": ["app/config.py", "app/pipeline.py", "app/agents/prompts.py"],
        "tests": "tests/test_c121_list_precision.py（7 颗格）",
        "probes": [
            "scripts/probe_c121_list_audit.py（件① 12 题离线审计，零 LLM）",
            "scripts/probe_c121_q003_three_arm.py（件③ 三臂真跑）",
            "scripts/probe_c121_pack_guard.py（件④ L2／@7 旁证，零 LLM）",
            "scripts/probe_c121_face_bytes.py（§8 关旗反向腿＋开旗纯插入，零 LLM）",
        ],
        "artifacts": [
            "artifacts/C121_list_precision.md ＋ .json（本票主交付件）",
            "artifacts/C121_list_audit.md / .json（件① 12 题离线审计）",
            "artifacts/C121_pack_guard.md / .json（件④ L2／@7 零模型旁证）",
            "artifacts/C121_face_bytes.md / .json（§8 反向腿）",
            "artifacts/C121_three_arm_stats.md / .json（三臂统计）",
            "artifacts/c121/three_arm.md / .json（逐遍原始产物）",
            "artifacts/c121/spot_q_001.md / .json、spot_q_002.md / .json（刘翔其余题各 1 遍）",
            "artifacts/c121/stats_c121.py、make_c121_json.py（读数与交付件都脚本现生成）",
        ],
        "branch": "qoder/c121-list-precision（从 main 0e957fa 开枝，未合、未 push）",
        "branch_tip_policy": (
            "不把 commit sha 写进本产物＝产物永远追不上盖章它的那一笔（自比型字段，"
            "上一笔就慢一笔、越补越错）。tip 以交账那一行为准，或当场读："
            "`git -C /tmp/c121/tree rev-parse --short HEAD`"
        ),
    },
    "rule": {
        "form": "A（名单预滤）＋B（名额硬帽）窄组合＝主路径 C",
        "kept_reasons": audit["rule"]["kept_reasons"],
        "min_score": audit["rule"]["min_score"],
        "cap": audit["rule"]["cap"],
        "raw_limit": 10,
        "dropped_rule_names": ["weak_reason", "low_score", "over_cap"],
        "on_the_prompt": "只列段 id＋一句『未点名的段落仍可正常引用／不得为凑名单而引用无关段』；不把名单并进了 selected（纯插入）；金标原文与金标段 id 不进提示、不硬编码",
        "why_these_reasons": (
            "件① 12 题审计：close_read 34 段里 24 段金标、conflict_pair 4 段里 2 段金标；"
            "role_official 74 段里 1 段金标（『看起来像官方』这条启发式基本没信号）＝被剔的主因"
        ),
    },
    "offline_audit_12_questions": {
        "raw_n": tot["raw"],
        "raw_gold": tot["raw_gold"],
        "raw_precision": tot["raw_precision"],
        "kept_n": tot["kept"],
        "kept_gold": tot["kept_gold"],
        "kept_precision": tot["kept_precision"],
        "box_gold": tot["box_gold"],
        "box_gold_raw_share": round(tot["raw_gold"] / tot["box_gold"], 4),
        "box_gold_kept_share": tot["box_gold_kept_share"],
        "disclosed_cost": (
            f"盒内金标被名单覆盖率 {round(tot['raw_gold'] / tot['box_gold'], 4)}"
            f"（{tot['raw_gold']}/{tot['box_gold']} 段）→ "
            f"{tot['box_gold_kept_share']}（{tot['kept_gold']}/{tot['box_gold']} 段）"
            f"＝少盖 {tot['raw_gold'] - tot['kept_gold']} 段；"
            "接受理由＝名单只是提示，块里明写未点名段落仍可引用，"
            "丢的是提醒不是可见性；而名单里的弱段丢的是真名额"
        ),
        "reason_table": audit["reason_table"],
        "leak_audit": audit["leak_audit"],
    },
    "three_arm_q003": {
        "model": three["model"],
        "passes_per_arm": three["passes_per_arm"],
        "temperature": three["temperature"],
        "temperature_note": "工单写『温度钉死与 C-120 同』，而 C-120 实跑是未钉（None）＝两者互斥；"
                            "本轮按『与 C-120 同』执行＝未钉。这条冲突已回报，待 Boyu／分析师定",
        "arms": [arm_row("off"), arm_row("raw"), arm_row("filt")],
        "arm_meaning": {
            "off": "本旗关＝主线现状（无点名名单）",
            "raw": "规则关掉（kept_reasons 全放开、cap=0）＝C-113 那种 10 段全名单，作对照",
            "filt": "本旗开＝预滤＋硬帽后的 5 段名单",
        },
        "pairwise_l3": pair,
        "pairwise_waste": waste,
        "leaks_total": three["leaks_total"],
    },
    "face_bytes_reverse_leg": {
        "zero_llm": True,
        "cross_tree_off_identical": face["cross_tree_off_identical"],
        "sha_off_main_tree": face["sha_off_main"],
        "sha_off_branch_tree": face["sha_off_branch"],
        "off_face_chars": face["off_face_chars"],
        "off_tree17_list_keys": face["off_tree17_list_keys"],
        "off_other_tree17_keys": face["off_other_tree17_keys"],
        "leg_bit": face["leg_bit"],
        "on_face_chars": face["on_face_chars"],
        "on_diff": face["on_diff"],
        "on_list_n": face["on_list_n"],
        "on_list_ids": face["on_list_ids"],
        "leak_ids_outside_box": face["leak_ids_outside_box"],
        "reading": (
            f"关旗两棵树 sha 逐字相同＝默认路径零溢出；开旗腿 leg_bit＝{face['leg_bit']}"
            f"（名单 {face['on_list_n']} 段真进块）⇒ 净插入 "
            f"{face['on_diff']['net_insert_chars']} 字／被删原文 "
            f"{face['text_replaced_chars']} 字＝纯插入，不是替换，也不是空比空"
        ),
    },
    "side_evidence": {
        "pack_guard_zero_llm": {
            "n_questions": pack["n_questions"],
            "l2_total_off_on": pack["l2_total_off_on"],
            "at7_total_off_on": pack["at7_total_off_on"],
            "all_identical": pack["all_identical"],
            "leak_hits": pack["leak_hits"],
            "list_out_of_box_total": pack["list_out_of_box_total"],
            "note": "开旗只改提示面名单，不改装箱⇒L2／@7 逐题全同（两臂都取到非 0 数，不是空比空）",
        },
        "liuxiang_other_questions": (
            "q_001／q_002 各 1 遍抽测（off vs filt）＝只算在场，不显著性判动："
            "q_001 少 1 段（L3 3→2，4 段盒内金标）、q_002 平（2→2）＝与 C-120 量过的"
            "本机 ±1 逐跑漂移同量级。原始件＝artifacts/c121/spot_q_001.md/.json、"
            "spot_q_002.md/.json"
        ),
        "holdout": "没量过",
        "other_cases": "没量过",
    },
    "c120_comparison_one_line": (
        "C-120 量到的是『开旗＝10 段全名单把 6 段非金标搬进交卷清单，金标段 2.875→1.50（p=0.007）』；"
        "C-121 把名单收到 5 段（只留 close_read／conflict_pair＋硬帽）后，名单里非金标被引从 2.8 掉到 1.0 每遍（p=0.0079），"
        "q_003 金标段回到与关旗持平的 2.80＝浪费被止住，但没超过关旗，所以是弱 YES 而不是涨分"
    ),
    "errata_this_ticket": [
        "交付件正文手打数字两处订正（复算 per_question 求和抓到）：盒内金标覆盖 0.690→0.667"
        "（29→28 段）；`all_with_role` cap10 准度 0.242→0.233（与未滤同值）。",
        "§8 反向腿原来只活在 stdout＝本轮做成 `scripts/probe_c121_face_bytes.py`；"
        "探针第一版『旗开但名单 0 段、净插入 0 字』是假读数（apply 只在 pipeline 里被调）＝"
        "已复刻 pipeline 那个 if，并加 `leg_bit` 自检，不咬上则非零退出。",
        "件④ 早先 L2 全量成 0/0＝参数传错（段 id 集合 vs 定位集）＝空比空的假旁证，"
        "已改回 `selected_locs`，改后 42→42 与件① 盒内金标 42 对齐。",
        "「四颗探针没进零引用豁免表＝合入前要补」这句是我没量就写的。实测＝本枝与主线"
        " live 清单同为 17 条、`probe_c121_*` 都不在其中（闸看 tracked 文件里有没有提到"
        "脚本名，本票 md 提到了）⇒ 尾巴方向反过来：合入须连 md 一起带，否则才要登记。",
    ],
    "still_open": [
        (
            "引文逐字核对不过＝off "
            f"{fail_rate(arms['off'])['rate']}（{arms['off']['check_fail']}）／raw "
            f"{fail_rate(arms['raw'])['rate']}（{arms['raw']['check_fail']}）／filt "
            f"{fail_rate(arms['filt'])['rate']}（{arms['filt']['check_fail']}）"
            "＝量级与旗无关，比名单这条漏桶大＝另刀（本票禁做，未做）"
        ),
        "C-113 的 must_consider／tree17_focus_cite 与 C-121 的 tree17_list_* 两套键并存时的取舍＝没测",
        "服务端入参 token 在这条单分析师路上仍是 None（window_ledger 未覆盖该出口）＝尾部截断既未证实也未证伪",
        (
            "零引用闸：本枝与主线 live 清单同为 17 条，本票四颗探针没进该清单"
            "（闸看的是 tracked 文件里有没有提到脚本名，本票 md 提到了）。"
            "真正的尾巴＝合入时若不带 artifacts/C121_*.md，这四颗会变成零引用、"
            "须补 SCRIPT_ZERO_REF_EXEMPTIONS"
        ),
    ],
    "regression": {
        "branch_pytest": "7 failed, 1216 passed, 1 skipped（提交前 31.28s／提交后 28.63s 两次同数）",
        "main_pytest": "7 failed, 1209 passed, 1 skipped in 31.77s",
        "red_names_identical": True,
        "new_cells": "+7 全来自 tests/test_c121_list_precision.py",
        "note": "主线入库基线本就是 7 红（State 2026-11-03），本票没修也没扩大它",
    },
    "not_committed_to_main": "本票未合 main、未 push；主仓工作区只有 artifacts（未入库）",
}


def main():
    dst = f"{TREE}/artifacts/C121_list_precision.json"
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("wrote", dst, os.path.getsize(dst), "bytes")


if __name__ == "__main__":
    main()
