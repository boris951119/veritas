#!/usr/bin/env python3
"""C-161 探针：客观 2.2 证据面现状量尺（只量不开刀）。

用法（架构师独立复放；零 LLM、零网络——本脚本不 import app/，只读已交卷产物）：
  干跑一臂（不出 pooled）：
    python scripts/probe_c161_evidence_face.py --run-root <跑次根> --gold-root <金标根> \
        --only-case 刘翔 --out-prefix /tmp/c161_dry/dry
  全量：
    python scripts/probe_c161_evidence_face.py --run-root <跑次根> --gold-root <金标根> \
        --out-prefix artifacts/C161_evidence_face

尺（开工前写死，禁止事后改门槛）：
- 计分函数＝score_official.precision_recall ＋ f1 ＋ score_f1_src（2.2.1 档）；
  逐案另现跑 score_official.score_submission 作交叉校验（同一份代码，不另写公式）
- 口径＝官方第一阶段精确匹配 (doc_id, para_id)；金标 fact_id 经本案 evidence_samples
  换形（_fact_index／_gold_fact_pairs）；未含第二阶段语义匹配＝下界
- pooled＝按案内一对一匹配再求和（Σ命中／Σ提交／Σ金标），与官方 2.2 全局集合比值同形；
  doc_id 跨案重名，故另出 naive-union 一臂只作披露、不当尺
- 有肉门槛（只用于「是否建议开实现票」，本票仍不开刀）＝
  pooled F1 ≥ 0.65 且 主尺案（刘翔"二选一"事件）F1 ≥ 0.65

件②分层（零 LLM，逐条 (doc_id, para_id) 落层，带 Σ层＝漏召总数 不变式）：
  L1 导出层丢＝该段在提交 conclusions 的 supporting/conflicting 里被引了，但没进交卷
    evidence.json
  L2 内部证据面有、导出没带＝该段出现在逐题 report.json 的 evidences[].segment_ids
  L3 进窗未引＝该段出现在逐题 progress.json 的材料面（material_pack_union／
    kg_focus_segment_ids／kg_priority_segment_ids），但三个面都没引
  L4 从未进产物面＝检索／装箱根本没把它弄进来
  正交旗（不是层）：相邻段指纹＝同 doc 里交卷面有 |Δpara| ≤ 1 的段，「导出／引用错段」
    的形态信号
判定写 artifacts/C161_evidence_face.{json,md}（数字全部现抄，禁手打）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import score_official as so  # noqa: E402  官方尺本体

MAIN_CASE_KEYWORD = "刘翔"
MEAT_GATE = 0.65
ADJACENCY_WINDOW = 1
PARA_INDEX = re.compile(r"#p(\d+)\Z")
MATERIAL_KEYS = ("material_pack_union", "kg_focus_segment_ids",
                 "kg_priority_segment_ids")
LAYER_KEYS = ("L1_cited_not_exported", "L2_internal_not_exported",
              "L3_boxed_not_cited", "L4_never_in_products")


def _load(path: Path):
    """官方尺的读法（只收 JSON 数组或带 records 的对象），逐字沿用。"""
    return so._load(path)


def _load_obj(path: Path):
    """过程面（report.json／progress.json）是对象不是数组，不走官方尺的 _load。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _pairs(rows: list[dict], key: str | None = None):
    return so._pairs(rows, key)


def para_index(para_id: str) -> int | None:
    m = PARA_INDEX.search(str(para_id or ""))
    return int(m.group(1)) if m else None


def locator(doc_id, para_id) -> tuple[str, str]:
    return (str(doc_id or ""), str(para_id or ""))


def case_dirs(run_root: Path, gold_root: Path) -> list[tuple[str, Path, Path]]:
    out = []
    for d in sorted(p for p in run_root.iterdir() if p.is_dir()):
        gold = gold_root / d.name
        if gold.is_dir():
            out.append((d.name, d, gold))
    return out


def one_to_one_residuals(submitted, gold):
    """一对一消耗后的残差多重集，并与 exact_hits 做守恒校验。

    校验＝|提交|＝命中＋误召残差、|金标|＝命中＋漏召残差；对不上直接抛，
    不把「空比空也算相同」带进产物。
    """
    hits = so.exact_hits(submitted, gold)
    cs, cg = Counter(submitted), Counter(gold)
    fp, fn = cs - cg, cg - cs
    if len(submitted) != hits + sum(fp.values()):
        raise AssertionError("提交侧守恒失败：|提交| != 命中 + 误召残差")
    if len(gold) != hits + sum(fn.values()):
        raise AssertionError("金标侧守恒失败：|金标| != 命中 + 漏召残差")
    return hits, fp, fn


def faces(case_dir: Path) -> dict[str, set]:
    """本案所有产物面里的 (doc_id, para_id) 落点集合，供漏召分层用。"""
    cited: set[tuple[str, str]] = set()
    for row in _load(case_dir / "conclusions.json"):
        for side in ("supporting_facts", "conflicting_facts"):
            for item in row.get(side) or []:
                if isinstance(item, dict):
                    cited.add(locator(item.get("doc_id"), item.get("para_id")))

    internal: set[tuple[str, str]] = set()
    boxed: set[tuple[str, str]] = set()
    n_qdirs = 0
    qroot = case_dir / "questions"
    if qroot.is_dir():
        for qdir in sorted(p for p in qroot.iterdir() if p.is_dir()):
            n_qdirs += 1
            rj = qdir / "report.json"
            if rj.exists():
                for ev in _load_obj(rj).get("evidences") or []:
                    doc = str(ev.get("doc_id") or "")
                    for sid in ev.get("segment_ids") or []:
                        sid = str(sid)
                        internal.add((doc or sid.split("#", 1)[0], sid))
            pj = qdir / "progress.json"
            if pj.exists():
                prog = _load_obj(pj)
                for key in MATERIAL_KEYS:
                    for sid in prog.get(key) or []:
                        sid = str(sid)
                        boxed.add((sid.split("#", 1)[0], sid))
    return {"cited_in_conclusions": cited,
            "in_internal_evidences": internal,
            "in_material_window": boxed,
            # 分层用到三张面的规模；L1／L2 记 0 时必须能自证「两侧都取到数」
            "face_sizes": {"cited_in_conclusions": len(cited),
                           "in_internal_evidences": len(internal),
                           "in_material_window": len(boxed),
                           "n_question_dirs": n_qdirs}}


def check_layer_sum(layers: dict[str, int], total: int) -> None:
    """分层不变式：Σ层必须等于漏召总数；少一层＝有段没交代去处。"""
    if sum(layers.values()) != total:
        raise AssertionError(
            f"分层不变式失败：Σ层＝{sum(layers.values())} != 漏召总数＝{total}")


def layer_fn(fn: Counter, faceset: dict[str, set], submitted: Counter) -> dict:
    """把每条漏召落到 L1‥L4，并出相邻段旗；Σ层≠漏召总数直接抛。"""
    layers = {k: 0 for k in LAYER_KEYS}
    detail: list[dict] = []
    submitted_idx: dict[str, list[int]] = {}
    for doc, para in submitted:
        idx = para_index(para)
        if doc and idx is not None:
            submitted_idx.setdefault(doc, []).append(idx)
    for key, n in sorted(fn.items()):
        if not key[0] or not key[1]:
            layer = "L4_never_in_products"
        elif key in faceset["cited_in_conclusions"]:
            layer = "L1_cited_not_exported"
        elif key in faceset["in_internal_evidences"]:
            layer = "L2_internal_not_exported"
        elif key in faceset["in_material_window"]:
            layer = "L3_boxed_not_cited"
        else:
            layer = "L4_never_in_products"
        idx = para_index(key[1])
        adjacent = any(abs(i - idx) <= ADJACENCY_WINDOW
                       for i in submitted_idx.get(key[0], [])) if idx is not None else False
        layers[layer] += n
        detail.append({"doc_id": key[0], "para_id": key[1], "count": n,
                       "layer": layer, "adjacent_submitted_para": adjacent})
    total = sum(fn.values())
    check_layer_sum(layers, total)
    return {"counts": layers, "detail": detail, "fn_total": total,
            "adjacency_flag": sum(1 for d in detail if d["adjacent_submitted_para"])}


def per_question(case_dir: Path, gold_conclusions: list[dict],
                 index: dict[str, tuple[str, str]], submitted: Counter) -> list[dict]:
    """逐题：金标该题要求几条、交卷证据面覆盖几条、结论侧引了几条。"""
    grouped: dict[str, list[dict]] = {}
    for row in _load(case_dir / "conclusions.json"):
        grouped.setdefault(str(row.get("question_id") or ""), []).append(row)
    rows = []
    for gold in gold_conclusions:
        qid = str(gold.get("question_id") or "")
        unresolved: list[str] = []
        sup = so._gold_fact_pairs([gold], "supporting_facts", index, unresolved)
        conf = so._gold_fact_pairs([gold], "conflicting_facts", index, unresolved)
        gold_all = sup + conf
        left = Counter(gold_all)
        covered = 0
        for key in submitted:
            if left[key] > 0:
                left[key] -= 1
                covered += 1
        cited_sup: list[tuple[str, str]] = []
        cited_conf: list[tuple[str, str]] = []
        for one in grouped.get(qid) or []:
            for side, bucket in (("supporting_facts", cited_sup),
                                 ("conflicting_facts", cited_conf)):
                for item in one.get(side) or []:
                    if isinstance(item, dict):
                        bucket.append(locator(item.get("doc_id"), item.get("para_id")))
        rows.append({
            "question_id": qid,
            "gold_supporting": len(sup),
            "gold_conflicting": len(conf),
            "gold_total": len(gold_all),
            "covered_by_submitted_evidence": covered,
            "missing_for_this_question": len(gold_all) - covered,
            "submitted_conclusions_cited_supporting": len(cited_sup),
            "submitted_conclusions_cited_conflicting": len(cited_conf),
            "unresolved_fact_ids": len(unresolved),
            "both_sides_empty": len(gold_all) == 0 and not (cited_sup or cited_conf),
        })
    return rows


def measure_case(name: str, case_dir: Path, gold_dir: Path) -> dict:
    paths = {
        "evidence": case_dir / "evidence.json",
        "conclusions": case_dir / "conclusions.json",
        "gold_evidence": gold_dir / "evidence_samples.json",
        "gold_conclusions": gold_dir / "conclusions.json",
    }
    for role, p in paths.items():
        if not p.exists():
            raise FileNotFoundError(f"{name} 缺证据件（{role}）：{p}")
    raw_path = gold_dir / "raw_documents.json"

    official = so.score_submission(
        paths["evidence"], paths["conclusions"],
        paths["gold_evidence"], paths["gold_conclusions"],
        samples_path=paths["gold_evidence"],
        raw_documents_path=raw_path if raw_path.exists() else None,
    )
    submitted = _pairs(_load(paths["evidence"]))
    gold = _pairs(_load(paths["gold_evidence"]))
    p, r = so.precision_recall(submitted, gold)
    # 交叉校验：本探针的命中口径必须与官方 score_submission 逐位相同
    if abs(p - official["Precision_src"]) > 1e-12 or abs(r - official["Recall_src"]) > 1e-12:
        raise AssertionError(f"{name} 现跑 P/R 与 score_submission 读数不一致")
    hits, fp, fn = one_to_one_residuals(submitted, gold)

    gold_rows = _load(paths["gold_evidence"])
    faceset = faces(case_dir)
    return {
        "case": name,
        "score_official_2_2": {
            "Precision_src": official["Precision_src"],
            "Recall_src": official["Recall_src"],
            "F1_src": official["F1_src"],
            "score_2_2_1": official["score_2_2_1"],
            "recall_src_ceiling": official["recall_src_ceiling"],
            "missing_questions": official["missing_questions"],
            "extra_questions": official["extra_questions"],
            "unresolved_fact_ids": official["unresolved_fact_ids"],
            "gold_evidence_keys_sample": sorted(gold_rows[0].keys()) if gold_rows else [],
        },
        "counts": {
            "submitted_evidence_rows": len(submitted),
            "gold_evidence_rows": len(gold),
            "one_to_one_hits": hits,
            "false_positive_residual": sum(fp.values()),
            "false_negative_residual": sum(fn.values()),
            "submitted_distinct_pairs": len(set(submitted)),
            "gold_distinct_pairs": len(set(gold)),
            "gold_rows_without_locator": sum(1 for k in gold if not k[0] or not k[1]),
            "submitted_rows_without_locator": sum(1 for k in submitted if not k[0] or not k[1]),
        },
        "fp_by_doc": {k: v for k, v in sorted(Counter(k[0] for k in fp).items())},
        "fn_by_doc": {k: v for k, v in sorted(Counter(k[0] for k in fn).items())},
        "gap_layering": layer_fn(fn, faceset, Counter(submitted)),
        "face_sizes": faceset["face_sizes"],
        "per_question": per_question(case_dir, _load(paths["gold_conclusions"]),
                                     so._fact_index(gold_rows), Counter(submitted)),
    }


def upper_bound_variants(cases: list[dict], run_root: Path, gold_root: Path) -> dict:
    """重复条／分母放宽两臂只作上界披露：不当尺、不进判定、不改任何出厂态。

    官方 2.2 的一对一消耗＝同一 locator 交两次只能顶两条金标，金标侧重复 locator
    因此必须重复提交才吃得满；本臂量「这条形式规则各值几分」。
    """
    def variant(dedupe_sub: bool, dedupe_gold: bool) -> dict:
        hits = sub_n = gold_n = 0
        for c in cases:
            s = _pairs(_load(run_root / c["case"] / "evidence.json"))
            g = _pairs(_load(gold_root / c["case"] / "evidence_samples.json"))
            if dedupe_sub:
                s = list(dict.fromkeys(s))
            if dedupe_gold:
                g = list(dict.fromkeys(g))
            h, _fp, _fn = one_to_one_residuals(s, g)
            hits += h
            sub_n += len(s)
            gold_n += len(g)
        p = 0.0 if not sub_n else hits / sub_n
        r = 0.0 if not gold_n else hits / gold_n
        return {"hits": hits, "submitted_rows": sub_n, "gold_rows": gold_n,
                "Precision_src": p, "Recall_src": r, "F1_src": so.f1(p, r),
                "score_2_2_1": so.score_f1_src(p, r)}

    rows = _pairs([r for c in cases for r in _load(run_root / c["case"] / "evidence.json")])
    golds = _pairs([r for c in cases for r in _load(gold_root / c["case"] / "evidence_samples.json")])
    per_case_sub = sum(c["counts"]["submitted_distinct_pairs"] for c in cases)
    per_case_gold = sum(c["counts"]["gold_distinct_pairs"] for c in cases)
    return {
        "note": "上界披露臂：真交卷仍走默认口径（此臂不当尺、不落地为改动）",
        "submitted_rows": len(rows),
        "submitted_distinct_within_case_sum": per_case_sub,
        "submitted_distinct_global": len(set(rows)),
        "gold_rows": len(golds),
        "gold_distinct_within_case_sum": per_case_gold,
        "gold_distinct_global": len(set(golds)),
        "gold_duplicate_rows_within_case": len(golds) - per_case_gold,
        "cross_case_locator_collisions_submitted": per_case_sub - len(set(rows)),
        "cross_case_locator_collisions_gold": per_case_gold - len(set(golds)),
        "submitted_dedup_only": variant(True, False),
        "gold_dedup_only": variant(False, True),
        "both_dedup": variant(True, True),
    }


def pool(cases: list[dict], run_root: Path, gold_root: Path) -> dict:
    """pooled＝按案内匹配再求和；naive-union 只作跨案重名披露。"""
    hits = sum(c["counts"]["one_to_one_hits"] for c in cases)
    sub_n = sum(c["counts"]["submitted_evidence_rows"] for c in cases)
    gold_n = sum(c["counts"]["gold_evidence_rows"] for c in cases)
    p = 0.0 if not sub_n else hits / sub_n
    r = 0.0 if not gold_n else hits / gold_n

    naive_sub: list[tuple[str, str]] = []
    naive_gold: list[tuple[str, str]] = []
    owners: dict[tuple[str, str], set[str]] = {}
    for c in cases:
        s = _pairs(_load(run_root / c["case"] / "evidence.json"))
        g = _pairs(_load(gold_root / c["case"] / "evidence_samples.json"))
        naive_sub += s
        naive_gold += g
        for k in set(s) | set(g):
            owners.setdefault(k, set()).add(c["case"])
    naive_hits = so.exact_hits(naive_sub, naive_gold)

    ceil_in = ceil_gold = 0
    for c in cases:
        m = re.search(r"上限 (\d+)/(\d+)", str(c["score_official_2_2"]["recall_src_ceiling"]))
        if m:
            ceil_in += int(m.group(1))
            ceil_gold += int(m.group(2))
    return {
        "basis": "按案内一对一匹配再求和（Σ命中/Σ提交/Σ金标），与官方 2.2 全局集合比值同形",
        "n_cases": len(cases),
        "submitted_evidence_rows": sub_n,
        "gold_evidence_rows": gold_n,
        "one_to_one_hits": hits,
        "Precision_src": p,
        "Recall_src": r,
        "F1_src": so.f1(p, r),
        "score_2_2_1": so.score_f1_src(p, r),
        "mean_of_cases_F1": sum(c["score_official_2_2"]["F1_src"] for c in cases) / len(cases),
        "recall_src_ceiling_pooled": {
            "para_id_in_case_corpus": ceil_in,
            "gold_rows": ceil_gold,
            "line": (f"Recall_src 上限 {ceil_in}/{ceil_gold}＝{ceil_in / ceil_gold:.1%}"
                     if ceil_gold else "上限未核（金标为空或语料件缺失）"),
        },
        "naive_union_disclosure_only": {
            "hits": naive_hits,
            "Precision_src": (naive_hits / len(naive_sub)) if naive_sub else 0.0,
            "Recall_src": (naive_hits / len(naive_gold)) if naive_gold else 0.0,
            "locator_keys_shared_across_cases": sum(1 for v in owners.values() if len(v) > 1),
            "note": "doc_id 跨案重名，此臂只说明「池成一集」会不会虚高，不进判定",
        },
    }


def meat_threshold(cases: list[dict], pooled: dict | None) -> dict:
    main_case = next((c for c in cases if MAIN_CASE_KEYWORD in c["case"]), None)
    main_f1 = main_case["score_official_2_2"]["F1_src"] if main_case else None
    pooled_f1 = pooled["F1_src"] if pooled else None
    ok_pooled = pooled_f1 is not None and pooled_f1 >= MEAT_GATE
    ok_main = main_f1 is not None and main_f1 >= MEAT_GATE
    return {
        "gate_pooled_F1_ge": {"gate": MEAT_GATE, "value": pooled_f1, "pass": bool(ok_pooled)},
        "gate_main_case_F1_ge": {
            "gate": MEAT_GATE, "case": main_case["case"] if main_case else None,
            "value": main_f1, "pass": bool(ok_main),
        },
        "both_pass": bool(ok_pooled and ok_main),
        "available": pooled is not None,
    }


def red_line_selfcheck() -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, text=True,
                              capture_output=True).stdout.strip()

    app_diff = git("diff", "--stat", "app/", "config.json")
    return {
        "head_short": git("rev-parse", "--short", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "app_and_config_diff_stat": app_diff,
        "app_and_config_diff_empty": app_diff == "",
        "probe_imports_app": False,
    }


def fmt(x) -> str:
    if isinstance(x, float):
        return "n/a" if x != x else f"{x:.4f}"
    return "n/a" if x is None else str(x)


def gap_statement(data: dict) -> str:
    t = data["totals"]
    fn = t["fn"]
    l1 = t["L1_cited_not_exported"]
    l2 = t["L2_internal_not_exported"]
    l3 = t["L3_boxed_not_cited"]
    l4 = t["L4_never_in_products"]
    if fn == 0:
        return "漏召为 0，本案面无缺口可归因（注意：这不代表无误召）"
    groups = (
        ("未进证据导出（L1＋L2）", l1 + l2),
        ("进窗未引／导出错段（L3，答题侧没引这条金标段）", l3),
        ("金标段从未进任何产物面（L4，检索／装箱侧）", l4),
    )
    name, best = max(groups, key=lambda g: g[1])
    rest = "、".join(f"{g[0]}＝{g[1]}/{fn}" for g in groups if g[0] != name)
    return (f"最大损失落在「{name}」＝{best}/{fn}"
            f"（{best / fn:.1%}）；其余：{rest}")


def render_md(data: dict) -> str:
    v, pooled = data["verdict"], data["pooled"]
    meat = v["meat_threshold"]
    lines = [
        f"# C-161 客观 2.2 证据面现状量尺 — 判定：{v['judgement']}",
        "",
        f"- 判定＝**{v['judgement']}**：{v['judgement_reason']}",
        f"- 建议开实现票＝**{v['recommend_implementation']}**；依据：{v['recommend_basis']}",
        f"- 有肉门槛（预先写死）＝pooled F1 ≥ {meat['gate_pooled_F1_ge']['gate']}："
        f"{meat['gate_pooled_F1_ge']['pass']}；主尺案 F1 ≥ {meat['gate_main_case_F1_ge']['gate']}："
        f"{meat['gate_main_case_F1_ge']['pass']}（案＝{meat['gate_main_case_F1_ge']['case']}）",
        f"- 跑次根＝{data['run_root']}；金标根＝{data['gold_root']}",
        f"- 尺＝{data['ruler']}",
        "- 本票零 LLM：探针不 import app/，只读已交卷产物",
        "",
        "## 件① pooled 读数",
        "",
    ]
    if pooled:
        lines += [
            f"- {pooled['basis']}（案数 {pooled['n_cases']}）",
            f"- 提交条数 {pooled['submitted_evidence_rows']}｜金标条数 {pooled['gold_evidence_rows']}"
            f"｜一对一命中 {pooled['one_to_one_hits']}",
            f"- Precision_src＝{fmt(pooled['Precision_src'])}｜Recall_src＝{fmt(pooled['Recall_src'])}"
            f"｜F1_src＝{fmt(pooled['F1_src'])}｜2.2.1＝**{pooled['score_2_2_1']} 分（满 7）**",
            f"- 逐案 F1 均值（仅披露，不当尺）＝{fmt(pooled['mean_of_cases_F1'])}",
            f"- {pooled['recall_src_ceiling_pooled']['line']}",
            f"- naive-union 披露臂：命中 {pooled['naive_union_disclosure_only']['hits']}、"
            f"跨案重名 locator 键 {pooled['naive_union_disclosure_only']['locator_keys_shared_across_cases']} 个"
            "（＝不把 6 案池成一集的理由；此臂不进判定）",
        ]
    else:
        lines.append("- 部分案干跑（--only-case），不出 pooled")
    ub = data.get("upper_bound_disclosure")
    if ub:
        def ub_line(name: str) -> str:
            v = ub[name]
            return (f"{name}＝命中 {v['hits']}／提交 {v['submitted_rows']}／金标 {v['gold_rows']}"
                    f"，P {fmt(v['Precision_src'])}／R {fmt(v['Recall_src'])}"
                    f"／F1 {fmt(v['F1_src'])}／2.2.1 {v['score_2_2_1']}")
        lines += [
            "",
            "### 上界披露臂（不当尺、不进判定）",
            "",
            f"- 案内重复 locator：提交 {ub['submitted_rows']} 条、案内去重后 "
            f"{ub['submitted_distinct_within_case_sum']} 条；金标 {ub['gold_rows']} 条、案内去重后 "
            f"{ub['gold_distinct_within_case_sum']} 条"
            f"（金标案内重复 {ub['gold_duplicate_rows_within_case']} 条＝同一 locator 被两条金标 fact 要求，"
            "一对一规则下只能靠重复提交吃满，而重复提交又压精确率）",
            f"- 跨案同名 locator 碰撞（案内匹配不受其影响，只在全局池化时虚高）："
            f"提交侧 {ub['cross_case_locator_collisions_submitted']} 对、"
            f"金标侧 {ub['cross_case_locator_collisions_gold']} 对",
            f"- {ub_line('submitted_dedup_only')}（＝只把交卷重复条并掉）",
            f"- {ub_line('gold_dedup_only')}（＝只把金标分母按 distinct 放宽）",
            f"- {ub_line('both_dedup')}（＝两侧都并掉，这是本面的形式上界）",
            "- 读法：这三臂只说明「locator 粒度／重复条」这条形式规则各值几分，"
            f"连两侧都并掉的形式上界 F1 也只有 {fmt(ub['both_dedup']['F1_src'])}"
            f"（2.2.1＝{ub['both_dedup']['score_2_2_1']} 分）＝"
            "重复条不是瓶颈，缺口是 locator 本身对不上；"
            "真实交卷口径仍是默认的一对一，据此不提分、不改出厂态",
        ]
    lines += ["", "## 件① 逐案表", "",
              "| 案 | 提交 | 金标 | 命中 | P_src | R_src | F1_src | 2.2.1 | 误召 | 漏召 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for c in data["cases"]:
        s, k = c["score_official_2_2"], c["counts"]
        lines.append(
            f"| {c['case']} | {k['submitted_evidence_rows']} | {k['gold_evidence_rows']} "
            f"| {k['one_to_one_hits']} | {fmt(s['Precision_src'])} | {fmt(s['Recall_src'])} "
            f"| {fmt(s['F1_src'])} | {s['score_2_2_1']} | {k['false_positive_residual']} "
            f"| {k['false_negative_residual']} |")
    lines += ["", "## 件① 逐案×逐题表（题级＝金标结论侧 fact_id 换形后）", ""]
    for c in data["cases"]:
        lines += [f"### {c['case']}", "",
                  "| 题 | 金标支撑 | 金标冲突 | 金标合计 | 交卷证据面覆盖 | 该题漏召 "
                  "| 结论引支撑 | 结论引冲突 | 金标 fact 换不上 | 双方空 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for q in c["per_question"]:
            lines.append(
                f"| {q['question_id']} | {q['gold_supporting']} | {q['gold_conflicting']} "
                f"| {q['gold_total']} | {q['covered_by_submitted_evidence']} "
                f"| {q['missing_for_this_question']} "
                f"| {q['submitted_conclusions_cited_supporting']} "
                f"| {q['submitted_conclusions_cited_conflicting']} "
                f"| {q['unresolved_fact_ids']} | {'是' if q['both_sides_empty'] else '否'} |")
        lines.append("")
    lines += [
        "## 件② 缺口分层（零 LLM）",
        "",
        "L1＝结论侧已引但没进交卷证据面（导出层丢）；L2＝逐题内部证据面有、导出没带；"
        "L3＝已进材料窗口但三面都没引；L4＝从未进任何产物面（检索／装箱）。"
        f"相邻段旗＝同 doc 内交卷面存在 |Δpara| ≤ {data['constants']['adjacency_window']} 的段"
        "（「导出／引用错段」形态信号，正交于层）。",
        "",
        "| 案 | 漏召 | L1 | L2 | L3 | L4 | 相邻段旗 | 误召 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in data["cases"]:
        g, cc = c["gap_layering"], c["gap_layering"]["counts"]
        lines.append(
            f"| {c['case']} | {g['fn_total']} | {cc['L1_cited_not_exported']} "
            f"| {cc['L2_internal_not_exported']} | {cc['L3_boxed_not_cited']} "
            f"| {cc['L4_never_in_products']} | {g['adjacency_flag']} "
            f"| {c['counts']['false_positive_residual']} |")
    t = data["totals"]
    lines.append(
        f"| **合计** | {t['fn']} | {t['L1_cited_not_exported']} "
        f"| {t['L2_internal_not_exported']} | {t['L3_boxed_not_cited']} "
        f"| {t['L4_never_in_products']} | {t['adjacency']} | {t['fp']} |")
    lines += [
        "",
        "- 不变式：Σ层＝漏召总数（逐案 assert 通过；合计 "
        f"{sum(t[k] for k in LAYER_KEYS)}＝{t['fn']}）",
        "- 分层三张面自身规模（现抄，用来自证「L1／L2 记 0」不是空比空）："
        + "；".join(
            f"{c['case']}＝结论引用 {c['face_sizes']['cited_in_conclusions']} 对、"
            f"内部证据面 {c['face_sizes']['in_internal_evidences']} 对、"
            f"材料窗口 {c['face_sizes']['in_material_window']} 段"
            f"（逐题目录 {c['face_sizes']['n_question_dirs']} 个）"
            for c in data["cases"]),
        "",
        f"- 落点结论（现抄）：{data['gap_where']}",
        "",
        f"## 件② 漏召明细（md 只列前 {data['constants']['md_detail_rows']} 条，全量在 json）",
        "",
        "| 案 | doc_id | para_id | 层 | 相邻段旗 |",
        "|---|---|---|---|---|",
    ]
    shown = 0
    for c in data["cases"]:
        for d in c["gap_layering"]["detail"]:
            if shown >= data["constants"]["md_detail_rows"]:
                break
            lines.append(f"| {c['case']} | {d['doc_id']} | {d['para_id']} "
                         f"| {d['layer']} | {'是' if d['adjacent_submitted_para'] else '否'} |")
            shown += 1
    lines += [
        "",
        "## 件③ 是否建议开实现票",
        "",
        f"- 建议＝**{v['recommend_implementation']}**（本票不实现）",
        f"- 依据：{v['recommend_basis']}",
        "",
        "## 口径缺口与限制（只披露，不当刀）",
        "",
    ]
    for note in data["caveats"]:
        lines.append(f"- {note}")
    rlc = data["red_line_selfcheck"]
    lines += [
        "",
        "## 红线自查",
        "",
        f"- 枝＝{rlc['branch']}；HEAD（现抄）＝{rlc['head_short']}",
        f"- app/ 与 config.json diff 为空＝{rlc['app_and_config_diff_empty']}"
        f"（diff 内容：{rlc['app_and_config_diff_stat'] or '（空）'}）",
        "- 未改默认旗／合式／仲裁公式／数值 STOP／cite_accept（保持 False）；"
        "三旗（CONFLICT_TRACE／SUBMIT_TOP7／ARB_CONTEXT）出厂态一字未动；"
        "未合 main；未碰 C-141；未合 C-149〜160 任何未合枝",
        "",
    ]
    return "\n".join(lines)


def build_payload(cases: list[dict], pooled: dict | None,
                  run_root: Path, gold_root: Path, md_detail_rows: int) -> dict:
    t_fn = sum(c["gap_layering"]["fn_total"] for c in cases)
    layers_sum = {layer: sum(c["gap_layering"]["counts"][layer] for c in cases)
                  for layer in LAYER_KEYS}
    totals = {
        "fn": t_fn, **layers_sum,
        "adjacency": sum(c["gap_layering"]["adjacency_flag"] for c in cases),
        "fp": sum(c["counts"]["false_positive_residual"] for c in cases),
        "submitted_rows": sum(c["counts"]["submitted_evidence_rows"] for c in cases),
        "gold_rows": sum(c["counts"]["gold_evidence_rows"] for c in cases),
    }
    meat = meat_threshold(cases, pooled)
    if pooled is None:
        judgement, reason = ("PARTIAL",
                             "尺跑通但为部分案干跑，未出 pooled 读数与全 6 案件①")
    else:
        judgement, reason = ("YES",
                             "官方尺在全部案交卷面跑通（逐案现跑 score_submission 交叉校验一致）、"
                             "件①②③④ 齐、分层与守恒不变式逐案通过")
    recommend = "是" if meat["both_pass"] else "否"
    if recommend == "是":
        basis = (f"有肉门槛两条全过：pooled F1＝{fmt(meat['gate_pooled_F1_ge']['value'])}，"
                 f"主尺案 F1＝{fmt(meat['gate_main_case_F1_ge']['value'])}，均 ≥ {MEAT_GATE}")
    else:
        bits = []
        for key, label in (("gate_pooled_F1_ge", "pooled F1"),
                           ("gate_main_case_F1_ge", "主尺案 F1")):
            g = meat[key]
            if g["value"] is None:
                bits.append(f"{label} 未取到数（部分案干跑）")
            elif not g["pass"]:
                bits.append(f"{label}＝{fmt(g['value'])} 距门槛 {g['gate']} 差 "
                            f"{g['gate'] - g['value']:.4f}")
        basis = "；".join(bits) if bits else "门槛全过但本票仍不实现"

    data = {
        "verdict": {"judgement": judgement, "judgement_reason": reason,
                    "recommend_implementation": recommend, "recommend_basis": basis,
                    "meat_threshold": meat},
        "run_root": str(run_root),
        "gold_root": str(gold_root),
        "ruler": "scripts/score_official.py: precision_recall + f1 + score_f1_src"
                 "（第一阶段精确匹配，未含语义匹配＝下界）",
        "constants": {"adjacency_window": ADJACENCY_WINDOW,
                      "meat_gate": MEAT_GATE, "main_case_keyword": MAIN_CASE_KEYWORD,
                      "md_detail_rows": md_detail_rows},
        "cases": cases,
        "pooled": pooled,
        "upper_bound_disclosure": (upper_bound_variants(cases, run_root, gold_root)
                                   if pooled else None),
        "totals": totals,
        "gap_where": "",
        "caveats": [
            "官方 2.1 的第二阶段语义匹配未跑（须调用大模型），本读数＝下界；"
            "语义匹配只会把精确匹配判出的漏召／误召往回收，不会把读数往上抬过真值",
            "《评分标准》附录 A.3 写「question_id＝2.2 的匹配键」，但金标证据文件"
            "evidence_samples 的字段里没有 question_id（现抄 keys 见 json 的 "
            "cases[].score_official_2_2.gold_evidence_keys_sample），"
            "故本面唯一可执行的官方读数＝案内全局集合比值；题级表按金标结论侧 "
            "fact_id→(doc_id, para_id) 换形另列，不与 2.2 混淆",
            "题级「金标合计」＝该题 supporting＋conflicting 两侧条数相加，"
            "同一 (doc_id, para_id) 双侧都出现时计 2 次；案级 2.2 只看证据文件本身",
            "Recall_src 上限按金标 para_id 是否落在本案语料算：不在语料的金标段永远追不回"
            "（属金标／语料不齐，不属本系统欠账），真上限须按该上限折",
            "缺题／双方空剔除：案级 2.2 的分母是提交证据文件与金标证据文件的条数，"
            "不走逐题权重，故不受「双方为空剔除」影响；该剔除只作用在 2.4／2.5 侧"
            "（official missing_questions／extra_questions 已随案记入 json）",
            "本票未改任何生产代码，读数为「现状量尺」而非提分声明；"
            "读数随跑次飘，跨票比较须同一跑次根",
        ],
        "red_line_selfcheck": red_line_selfcheck(),
    }
    data["gap_where"] = gap_statement(data)
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="C-161 客观 2.2 证据面量尺（只量不开刀）")
    ap.add_argument("--run-root", required=True)
    ap.add_argument("--gold-root", required=True)
    ap.add_argument("--out-prefix",
                    default=str(ROOT / "artifacts" / "C161_evidence_face"))
    ap.add_argument("--only-case", default=None,
                    help="干跑一臂：只量案名含此子串的案（不出 pooled）")
    ap.add_argument("--md-detail-rows", type=int, default=40)
    args = ap.parse_args(argv)

    run_root, gold_root = Path(args.run_root), Path(args.gold_root)
    all_picked = case_dirs(run_root, gold_root)
    if not all_picked:
        raise SystemExit("跑次根与金标根没有交集案例，未取到数（不许空比空）")
    picked = all_picked if not args.only_case else [
        c for c in all_picked if args.only_case in c[0]]
    if not picked:
        raise SystemExit(f"--only-case {args.only_case} 在两侧都没匹配到案")

    cases = [measure_case(n, d, g) for n, d, g in picked]
    pooled = pool(cases, run_root, gold_root) if len(picked) == len(all_picked) else None
    data = build_payload(cases, pooled, run_root, gold_root, args.md_detail_rows)

    out_prefix = Path(args.out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_prefix.with_suffix(".json")
    md_path = out_prefix.with_suffix(".md")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md = render_md(data)
    md_path.write_text(md, encoding="utf-8")

    print(md)
    print(f"[C-161] 已写 {json_path} 与 {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
