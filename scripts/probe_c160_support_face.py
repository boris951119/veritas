#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-160 件①＋件②：客观 2.4 支撑面（引用可核＋条数）现状量尺＋刀梯反事实。

五条腿（全部零模型、零网络；只读现跑次产物＋官方样例集；金标只进量尺面）：

  腿 A｜交卷 2.4 现状＝尺用 `scripts/score_official.py` 原函数（先逐题算
        Precision_sup／Recall_sup，再按金标条数加权汇总），逐案＋pooled 出
        条数／命中／P／R／2.4.1／2.4.2 档位分／空引题数／裸支撑数。
  腿 B｜可核面＝① 锚可定位率：提交 (doc_id, para_id) 能否在该案
        `raw_documents.json` 的段落键里取到（段落文本按 char_start／char_end 切）；
        ② 引文逐字可核率：该题保留证据的 quote 过
        `app.core.citation_check.check_quote` vs 所指段原文。
  腿 C｜L3 引用过程面＝逐题候选池条数（台账／全部带证据结论／细读面／
        焦点面／Top-7 final／盒 rank／rerank 全序）＋打回行数＋空引题数＋
        引用合规（台账段有多少落在授权面内、多少段键在语料里取不到）。
  腿 D｜刀梯反事实＝把腿 C 那些池当提交面（含「池前 K 截断」），逐臂重量尺，
        看加宽／收窄／补回各能买到哪一档分；另配「本案全段」灌面上界参照。
  腿 E｜判别与补回臂＝金标盲的机械筛选（主体／议题数字／对立口径 cues，
        复用 C-97 的取词器）＋打回引文回贴（引文在官方原文逐字找得到的段）。
  旁证腿｜同一把尺在别的跑次根上重读腿 A 现状＝量逐跑方差，别拿一次读数当定数。

判据（开工前写死，跑完不改尺）＝
  主尺＝刘翔案（Boyu 2026-10-29 拍：其余案金标不一定全准，六案 pooled 只作方向旁证）；
  门槛甲（pooled 双档）＝某条**固定规则**臂（不是曲线择优挑出来的最大值）
      同时满足 pooled Recall_sup ≥ 0.55 且 pooled Precision_sup ≥ 0.70
      （＝2.4.1 ≥2 分且 2.4.2 ≥2 分），且刘翔单案同样两条都过；
  门槛乙（逐案＝按专题口径）＝官方按专题分别记分再相加（旧账「2.4.1 0/36」＝6 案×6 分），
      候选臂的 Σ案(2.4.1＋2.4.2) ≥ 现状臂＋2，且不许把现状已得分的案打成 0 分；
      K 只许用生产里已存在的常数（细读面宽＝3、Top-7 宽＝7），不许拿金标挑 K；
  曲线择优那档只作「上界披露」，不许当刀——选 K 用了金标＝把金标烧进规则，违红线；
  两门槛都不过 ⇒ 本票只量、不开刀。

档位判据（禁止空比空）＝每条比率核都自己取到分母；分母为 0 记 `not_measured`
  而不是 0／True；pooled 题数为 0 直接判 NO。

产物卫生＝只记 id／计数／比率／档位名，零官方语料正文与零结论文本；
  末尾另跑一道 25 字滑窗卫生扫描（官方六案语料 vs 本票两份产物）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.score_official import (  # noqa: E402
    _fact_index,
    _gold_fact_pairs,
    _load,
    _pairs,
    _weighted,
    exact_hits,
    precision_recall,
    score_precision_sup,
    score_recall_sup,
)
from app.core.citation_check import (  # noqa: E402
    _ELLIPSIS,
    check_quote,
    normalize,
)
# 判别 cues 取词＝生产探针已入册的金标盲规则（主体／议题数字／对立口径）
from scripts.probe_c97_support_rank import (  # noqa: E402
    extract_support_cues,
    support_features,
)

OFFICIAL_DEFAULT = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
PRIMARY_CASE = "刘翔编制“二选一”事件"

# 门槛（开工前写死）
RECALL_GATE = 0.55
PRECISION_GATE = 0.70

# 腿 D 的固定规则臂＝不看金标就能写进代码的规则；K 曲线只作上界披露
FIXED_ARMS = (
    "A_交卷现状",
    "B_本题台账",
    "C_全部带证据结论",
    "D_细读面",
    "E_焦点面",
    "F_Top7定稿",
    "G_盒rank",
    "H_rerank全序",
    "I_台账∪细读",
    "J_台账且逐字可核",
)
# 腿 E：判别（收窄）与补回臂＋灌面上界（灌面只披露、不当刀）
FILTER_ARMS = (
    "L_台账∪打回声明段",
    "S_台账∪打回回贴段",
    "M_提交且主体命中",
    "N_提交且主体且数字或口径",
    "O_台账且主体命中",
    "P_台账且主体且数字或口径",
    "Q_细读且主体命中",
)
CEILING_ARMS = ("K_本案全段（灌面上界）",)
CANDIDATE_ARMS = FIXED_ARMS + FILTER_ARMS
# 逐案（按专题）口径下的「rank／带宽内」候选刀：K 只用生产里已存在的常数
# （1＝现交卷每题一条的宽度、3＝细读面宽、7＝C-140 Top-7 宽），不许拿金标挑 K。
K_FIXED = (
    ("D_细读面", 3),
    ("E_焦点面", 3),
    ("B_本题台账", 3),
    ("I_台账∪细读", 3),
    ("H_rerank全序", 7),
)
# 开工前写死的第二道门槛：官方按专题分别记分再相加（旧账「2.4.1 0/36」＝6 案×6 分），
# 所以除了 pooled 双档门槛，还须量「逐案口径净涨」：
#   候选臂的 Σ案(2.4.1+2.4.2) ≥ 现状臂 + CASE_GAIN_GATE，且不许把已得分的案打成 0 分。
CASE_GAIN_GATE = 2
K_SWEEP = (1, 2, 3, 5, 7, 9, 12, 16, 20, 24, 28, 32)

_PID_RE = re.compile(r"doc_\d+#p\d+")


def _locate_in_corpus(quote: str, corpus_norm: dict[str, str]) -> list[str]:
    """把一条引文回贴到本案语料里逐字命中的段落（金标盲，只用官方原文）。"""
    q = normalize(quote)
    parts = [p for p in _ELLIPSIS.split(q) if p and not _ELLIPSIS.fullmatch(p)]
    if not parts:
        return []
    hits: list[str] = []
    for pid, text in corpus_norm.items():
        cursor = 0
        for part in parts:
            at = text.find(part, cursor)
            if at < 0:
                break
            cursor = at + len(part)
        else:
            hits.append(pid)
    return hits


def _rejected_declared_ids(report: dict[str, Any]) -> list[str]:
    """打回行里分析师声明的段键（problems 文案里的 doc_x#pN），只用于「补回」上界量。"""
    out: list[str] = []
    for row in report.get("rejected") or []:
        blob = json.dumps(row, ensure_ascii=False)
        out.extend(_PID_RE.findall(blob))
    return out


# ---------------------------------------------------------------- 数据装载

def _obj(path: Path) -> dict[str, Any]:
    """report.json 这类对象型产物（`_load` 只收数组，别混用）。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _seg_to_pair(seg: str) -> tuple[str, str]:
    """段键 `doc_002#p3` → (doc_id, para_id)；非该形状原样进 para_id。"""
    s = str(seg or "").strip()
    if not s:
        return ("", "")
    if "#" in s:
        return (s.split("#", 1)[0], s)
    return ("", s)


def _dedup_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for doc, para in pairs:
        if not para:
            continue
        key = (doc, para)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _corpus(raw_documents_path: Path) -> dict[str, str]:
    """para_id → 该段原文（按 char_start／char_end 从 content 切）。"""
    out: dict[str, str] = {}
    for doc in _load(raw_documents_path):
        content = str(doc.get("content") or "")
        for para in doc.get("paragraphs") or []:
            pid = str(para.get("para_id") or "")
            if not pid:
                continue
            start = para.get("char_start")
            end = para.get("char_end")
            if isinstance(start, int) and isinstance(end, int) and end >= start:
                out[pid] = content[start:end]
            else:
                out[pid] = ""
    return out


def _question_pools(report: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """一题的各候选池（有序、已去重成 (doc_id, para_id)）。"""
    evidences = report.get("evidences") or []
    # 本题台账＝分析师保留证据的段（按证据出场序）
    ledger: list[tuple[str, str]] = []
    for ev in evidences:
        ledger.extend(_seg_to_pair(s) for s in (ev.get("segment_ids") or []))
    ledger = _dedup_pairs(ledger)

    ev_by_id = {str(ev.get("id") or ""): ev for ev in evidences}
    all_concl: list[tuple[str, str]] = []
    for con in report.get("conclusions") or []:
        for eid in con.get("evidence_ids") or []:
            ev = ev_by_id.get(str(eid))
            if not ev:
                continue
            all_concl.extend(_seg_to_pair(s) for s in (ev.get("segment_ids") or []))
    all_concl = _dedup_pairs(all_concl)

    acc = report.get("accounting") or {}
    tree17 = acc.get("tree17_cite") or {}
    top7 = acc.get("submit_top7") or {}
    kg_submit = acc.get("kg_submit") or {}
    kg_tree = acc.get("kg_test_tree") or {}

    def _from(key: str, src: dict[str, Any]) -> list[tuple[str, str]]:
        return _dedup_pairs([_seg_to_pair(x) for x in (src.get(key) or [])])

    pools = {
        "B_本题台账": ledger,
        "C_全部带证据结论": all_concl,
        "D_细读面": _from("close_read_ids", tree17),
        "E_焦点面": _from("kg_focus_segment_ids", acc),
        "F_Top7定稿": _from("final_ids", top7),
        "G_盒rank": _from("rank_order", kg_submit),
        "H_rerank全序": _from("rerank_order", kg_tree),
    }
    seen_keys: set[tuple[str, str]] = set()
    union_i: list[tuple[str, str]] = []
    for pair in ledger + pools["D_细读面"]:
        if pair not in seen_keys:
            seen_keys.add(pair)
            union_i.append(pair)
    pools["I_台账∪细读"] = union_i
    # J（台账且逐字可核）在 measure_case 里按真核对结果填，这里不预置＝少一处会误导的死代码
    return pools


# ---------------------------------------------------------------- 腿 A/B/C

def measure_case(root: Path, case_name: str, gold_root: Path) -> dict[str, Any]:
    """单案：交卷现状＋可核面＋逐题池，全部现读。"""
    case_dir = root / case_name
    gold_dir = gold_root / case_name
    out: dict[str, Any] = {"case": case_name, "errors": []}
    if not (case_dir / "conclusions.json").exists():
        out["errors"].append("缺 conclusions.json")
        return out
    if not (gold_dir / "conclusions.json").exists():
        out["errors"].append("缺金标 conclusions.json")
        return out

    corpus = _corpus(gold_dir / "raw_documents.json") if (gold_dir / "raw_documents.json").exists() else {}
    corpus_norm = {pid: normalize(text) for pid, text in corpus.items()}
    out["corpus_para_n"] = len(corpus)

    sub_rows = _load(case_dir / "conclusions.json")
    gold_rows = _load(gold_dir / "conclusions.json")
    samples = _load(gold_dir / "evidence_samples.json")
    index = _fact_index(samples)
    unresolved: list[str] = []

    grouped: dict[str, list[dict]] = {}
    for row in sub_rows:
        grouped.setdefault(str(row.get("question_id") or ""), []).append(row)

    q_dirs = sorted((case_dir / "questions").glob("q_*")) if (case_dir / "questions").exists() else []
    per_q: dict[str, dict[str, Any]] = {}
    for qd in q_dirs:
        rp = qd / "report.json"
        if not rp.exists():
            continue
        report = _obj(rp)
        pools = _question_pools(report)
        evidences = report.get("evidences") or []
        # 逐字可核：该题每条保留证据的 quote vs 所指段原文（任一段命中即算命中）
        v_ok = 0
        v_checked = 0
        for ev in evidences:
            quote = str(ev.get("quote") or "")
            if not quote:
                continue
            v_checked += 1
            texts = [corpus.get(str(s), "") for s in (ev.get("segment_ids") or [])]
            texts = [t for t in texts if t]
            if not texts:
                continue
            if any(check_quote(quote, t).ok for t in texts):
                v_ok += 1
        # 池 J 只对「逐字可核」的证据开放（这里重算一遍，保证臂真被筛过）
        j_pairs: list[tuple[str, str]] = []
        for ev in evidences:
            quote = str(ev.get("quote") or "")
            segs = [_seg_to_pair(s) for s in (ev.get("segment_ids") or [])]
            if not segs:
                continue
            if quote and corpus:
                texts = [corpus.get(str(s), "") for s in (ev.get("segment_ids") or [])]
                texts = [t for t in texts if t]
                if not (texts and any(check_quote(quote, t).ok for t in texts)):
                    continue
            j_pairs.extend(segs)
        pools["J_台账且逐字可核"] = _dedup_pairs(j_pairs)
        per_q[qd.name] = {
            "pools": {k: v for k, v in pools.items()},
            "n_evidences": len(evidences),
            "n_rejected": len(report.get("rejected") or []),
            "rejected_ids": _rejected_declared_ids(report),
            "rejected_rows": report.get("rejected") or [],
            "question": str(report.get("question") or ""),
            "quote_checked": v_checked,
            "quote_ok": v_ok,
        }

    # 逐题（金标侧为准遍历，缺题按 0 进分母）
    sup_p: list[tuple[float, int]] = []
    sup_r: list[tuple[float, int]] = []
    hits_total = 0
    gold_total = 0
    sub_total = 0
    empty_gold = 0
    bare_rows = 0
    anchor_ok = 0
    anchor_checked = 0
    missing_questions = 0
    for gold in gold_rows:
        qid = str(gold.get("question_id") or "")
        rows = grouped.get(qid) or []
        if not rows:
            missing_questions += 1
            sub_pairs: list[tuple[str, str]] = []
        else:
            sub_pairs = _pairs(rows, "supporting_facts")
        gold_pairs = _gold_fact_pairs([gold], "supporting_facts", index, unresolved)
        p, r = precision_recall(sub_pairs, gold_pairs)
        w = len(gold_pairs)
        if w == 0:
            empty_gold += 1
        sup_p.append((p, w))
        sup_r.append((r, w))
        hits_total += exact_hits(sub_pairs, gold_pairs)
        gold_total += w
        sub_total += len(sub_pairs)
        if not sub_pairs:
            bare_rows += 1
        for doc, para in sub_pairs:
            anchor_checked += 1
            if corpus and para in corpus:
                anchor_ok += 1

    p_pool = _weighted(sup_p)
    r_pool = _weighted(sup_r)
    q_quote_checked = sum(v["quote_checked"] for v in per_q.values())
    q_quote_ok = sum(v["quote_ok"] for v in per_q.values())
    # A 臂按金标题集全覆盖（题目录缺产物但 conclusions 在＝仍按真提交算）
    pools_all: dict[str, dict[str, list[tuple[str, str]]]] = {
        qid: dict(d["pools"]) for qid, d in per_q.items()
    }
    for gold in gold_rows:
        qid = str(gold.get("question_id") or "")
        raw = [x for x in _pairs(grouped.get(qid) or [], "supporting_facts") if x[1]]
        pools_all.setdefault(qid, {})["A_交卷现状"] = raw

    # 腿 E｜判别/收窄臂（金标不进规则：只用问句 cues＋官方原文段落做机械判别）
    def _keep(pool: list[tuple[str, str]], cues: dict[str, Any], mode: str) -> list[tuple[str, str]]:
        kept: list[tuple[str, str]] = []
        for pair in pool:
            text = corpus.get(pair[1], "")
            if not text:
                continue
            feat = support_features(text, cues)
            if mode == "subj" and not feat["has_subj"]:
                continue
            if mode == "hard" and not (feat["has_subj"] and (feat["has_num"] or feat["has_alt"])):
                continue
            kept.append(pair)
        return kept

    for qid, d in per_q.items():
        pools = pools_all.setdefault(qid, {})
        cues = extract_support_cues(d["question"])
        a_arm = pools.get("A_交卷现状") or []
        b_arm = pools.get("B_本题台账") or []
        d_arm = pools.get("D_细读面") or []
        pools["M_提交且主体命中"] = _keep(a_arm, cues, "subj")
        pools["N_提交且主体且数字或口径"] = _keep(a_arm, cues, "hard")
        pools["O_台账且主体命中"] = _keep(b_arm, cues, "subj")
        pools["P_台账且主体且数字或口径"] = _keep(b_arm, cues, "hard")
        pools["Q_细读且主体命中"] = _keep(d_arm, cues, "subj")
        pools["L_台账∪打回声明段"] = _dedup_pairs(
            b_arm + [_seg_to_pair(x) for x in d["rejected_ids"]]
        )
        # 腿 F｜打回引文回贴：分析师声明的锚取不到，但引文在官方原文里逐字找得到段
        relocated: list[str] = []
        n_rej = n_rej_found = 0
        for row in (d.get("rejected_rows") or []):
            quote = str(row.get("quote") or "")
            if not quote:
                continue
            n_rej += 1
            found = _locate_in_corpus(quote, corpus_norm)
            if found:
                n_rej_found += 1
            relocated.extend(found)
        d["n_rejected_with_quote"] = n_rej
        d["n_rejected_relocated"] = n_rej_found
        d["n_relocated_pairs"] = len(set(relocated))
        pools["S_台账∪打回回贴段"] = _dedup_pairs(
            b_arm + [_seg_to_pair(x) for x in relocated]
        )
        # 合规率＝台账引用的段有多少落在授权面内（细读／焦点／Top7 定稿／盒／候选全序）
        band = (
            set(pools.get("D_细读面") or [])
            | set(pools.get("E_焦点面") or [])
            | set(pools.get("F_Top7定稿") or [])
            | set(pools.get("G_盒rank") or [])
            | set(pools.get("H_rerank全序") or [])
        )
        outside = [x for x in b_arm if x not in band]
        not_in_corpus = [x for x in b_arm if x[1] not in corpus]
        d["n_ledger"] = len(b_arm)
        d["n_ledger_outside_band"] = len(outside)
        d["n_ledger_not_in_corpus"] = len(not_in_corpus)
    corpus_pairs = _dedup_pairs([
        (pid.split("#", 1)[0], pid) for pid in corpus
    ])
    for gold in gold_rows:
        qid = str(gold.get("question_id") or "")
        pools_all.setdefault(qid, {})["K_本案全段（灌面上界）"] = corpus_pairs
    out.update({
        "questions": len(gold_rows),
        "questions_scored": len(sup_p),
        "missing_questions": missing_questions,
        "empty_gold_questions": empty_gold,
        "submitted_pairs": sub_total,
        "gold_pairs": gold_total,
        "hits_pairs": hits_total,
        "bare_questions": bare_rows,
        "precision_sup": round(p_pool, 4),
        "recall_sup": round(r_pool, 4),
        "score_2_4_1": score_recall_sup(r_pool),
        "score_2_4_2": score_precision_sup(p_pool),
        "anchor_checked": anchor_checked,
        "anchor_ok": anchor_ok,
        "quote_checked": q_quote_checked,
        "quote_ok": q_quote_ok,
        "unresolved_fact_ids": len(unresolved),
        "per_question": {
            qid: {
                "n_evidences": d["n_evidences"],
                "n_rejected": d["n_rejected"],
                "quote_checked": d["quote_checked"],
                "quote_ok": d["quote_ok"],
                "n_ledger": d.get("n_ledger", 0),
                "n_ledger_outside_band": d.get("n_ledger_outside_band", 0),
                "n_ledger_not_in_corpus": d.get("n_ledger_not_in_corpus", 0),
                "n_rejected_with_quote": d.get("n_rejected_with_quote", 0),
                "n_rejected_relocated": d.get("n_rejected_relocated", 0),
                "n_relocated_pairs": d.get("n_relocated_pairs", 0),
                "pool_n": {k: len(v) for k, v in d["pools"].items()},
            }
            for qid, d in sorted(per_q.items())
        },
        "ledger_pairs": sum(int(d.get("n_ledger") or 0) for d in per_q.values()),
        "ledger_outside_band": sum(
            int(d.get("n_ledger_outside_band") or 0) for d in per_q.values()
        ),
        "ledger_not_in_corpus": sum(
            int(d.get("n_ledger_not_in_corpus") or 0) for d in per_q.values()
        ),
        "rejected_with_quote": sum(
            int(d.get("n_rejected_with_quote") or 0) for d in per_q.values()
        ),
        "rejected_relocated": sum(
            int(d.get("n_rejected_relocated") or 0) for d in per_q.values()
        ),
        "_pools": pools_all,
        "_gold": {
            str(g.get("question_id") or ""): _gold_fact_pairs([g], "supporting_facts", index, [])
            for g in gold_rows
        },
    })
    return out


# ---------------------------------------------------------------- 腿 D 刀梯

def _arm_readout(
    cases: list[dict[str, Any]],
    arm: str,
    k: int | None,
) -> dict[str, Any]:
    """把某臂（可截前 K）当提交面，按同一把尺重量一遍。"""
    sup_p: list[tuple[float, int]] = []
    sup_r: list[tuple[float, int]] = []
    n_sub = 0
    n_gold = 0
    n_hits = 0
    n_q = 0
    empty_pool_q = 0
    per_case: dict[str, dict[str, Any]] = {}
    for case in cases:
        pools_all = case.get("_pools") or {}
        gold_map = case.get("_gold") or {}
        c_p: list[tuple[float, int]] = []
        c_r: list[tuple[float, int]] = []
        c_sub = c_gold = c_hits = c_q = 0
        # 以金标题集遍历：题目录缺产物／池取不到＝按空提交进分母（与腿 A 同形）
        for qid, gold_pairs in gold_map.items():
            pool = (pools_all.get(qid) or {}).get(arm) or []
            sub = pool[:k] if k is not None else pool
            if not sub:
                empty_pool_q += 1
            p, r = precision_recall(sub, gold_pairs)
            w = len(gold_pairs)
            c_p.append((p, w)); c_r.append((r, w))
            sup_p.append((p, w)); sup_r.append((r, w))
            # 分子用官方 exact_hits（一对一消耗），与 precision_recall 内部同一把尺
            hits = exact_hits(sub, gold_pairs)
            c_sub += len(sub); c_gold += w; c_hits += hits
            n_sub += len(sub); n_gold += w; n_hits += hits
            c_q += 1; n_q += 1
        if c_q:
            cp, cr = _weighted(c_p), _weighted(c_r)
            per_case[case["case"]] = {
                "n_questions": c_q, "submitted": c_sub, "gold": c_gold, "hits": c_hits,
                "precision": round(cp, 4), "recall": round(cr, 4),
                "score_2_4_1": score_recall_sup(cr), "score_2_4_2": score_precision_sup(cp),
            }
    if not n_q:
        return {"not_measured": "该臂一题都没取到（池缺失或金标缺题）", "n_questions": 0}
    p_pool, r_pool = _weighted(sup_p), _weighted(sup_r)
    s1, s2 = score_recall_sup(r_pool), score_precision_sup(p_pool)
    # 逐案（＝按专题）口径：官方记分是每专题各算再相加（旧账「2.4.1 0/36」就是这个口径）
    case_sum = sum(v["score_2_4_1"] + v["score_2_4_2"] for v in per_case.values())
    case_scoring = sum(
        1 for v in per_case.values() if v["score_2_4_1"] + v["score_2_4_2"] > 0
    )
    case_losing = [
        name for name, v in per_case.items() if v["score_2_4_1"] + v["score_2_4_2"] <= 0
    ]
    return {
        "n_questions": n_q, "submitted": n_sub, "gold": n_gold, "hits": n_hits,
        "precision": round(p_pool, 4), "recall": round(r_pool, 4),
        "score_2_4_1": s1, "score_2_4_2": s2, "score_sum": s1 + s2,
        "case_score_sum": case_sum, "cases_scoring": case_scoring,
        "cases_scoring_of": len(per_case), "cases_zero": case_losing,
        "empty_pool_questions": empty_pool_q,
        "per_case": per_case,
        "gates_pass": bool(r_pool >= RECALL_GATE and p_pool >= PRECISION_GATE),
    }


# ---------------------------------------------------------------- 卫生扫描

def _norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def _corpus_text(gold_root: Path) -> tuple[str, int]:
    parts: list[str] = []
    n_docs = 0
    for case in sorted(p for p in gold_root.iterdir() if p.is_dir()):
        rp = case / "raw_documents.json"
        if not rp.exists():
            continue
        for doc in _load(rp):
            parts.append(str(doc.get("content") or ""))
            n_docs += 1
    return _norm("".join(parts)), n_docs


def windows_hit(files: list[Path], corpus_norm: str, window: int = 25) -> dict[str, Any]:
    """产物全文归一化后滑窗，看有多少窗真出现在官方六案语料里（＝抄了原文才会发生）。

    自证：`corpus_chars` 与逐件 `windows` 一起报，任一为 0＝扫描没跑起来，不许算过。
    """
    cjk4 = re.compile(r"[、。，；：！？\u4e00-\u9fff]{4,}")
    n_windows = n_hit = n_prose = 0
    per_file: dict[str, dict[str, int]] = {}
    for f in files:
        p = _norm(f.read_text(encoding="utf-8", errors="ignore"))
        n_w = n_h = 0
        for i in range(max(0, len(p) - window + 1)):
            w = p[i:i + window]
            n_w += 1
            if w in corpus_norm:
                n_h += 1
                if cjk4.search(w):
                    n_prose += 1
        per_file[f.name] = {"chars": len(p), "windows": n_w, "hits": n_h}
        n_windows += n_w
        n_hit += n_h
    return {
        "corpus_chars": len(corpus_norm), "windows": n_windows, "hits": n_hit,
        "prose_hits": n_prose, "per_file": per_file,
    }


# ---------------------------------------------------------------- 旁证腿（跨跑次）

def quick_current(root: Path, case_name: str, gold_root: Path) -> dict[str, Any]:
    """只算腿 A 现状读数（不建池、不逐字核）＝给跨跑次方差用，成本低。"""
    case_dir, gold_dir = root / case_name, gold_root / case_name
    if not (case_dir / "conclusions.json").exists() or not (gold_dir / "conclusions.json").exists():
        return {}
    sub_rows = _load(case_dir / "conclusions.json")
    gold_rows = _load(gold_dir / "conclusions.json")
    index = _fact_index(_load(gold_dir / "evidence_samples.json"))
    unresolved: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for row in sub_rows:
        grouped.setdefault(str(row.get("question_id") or ""), []).append(row)
    sup_p: list[tuple[float, int]] = []
    sup_r: list[tuple[float, int]] = []
    n_sub = n_gold = n_hits = 0
    for gold in gold_rows:
        qid = str(gold.get("question_id") or "")
        sub = _pairs(grouped.get(qid) or [], "supporting_facts")
        gp = _gold_fact_pairs([gold], "supporting_facts", index, unresolved)
        p, r = precision_recall(sub, gp)
        sup_p.append((p, len(gp)))
        sup_r.append((r, len(gp)))
        n_sub += len(sub)
        n_gold += len(gp)
        n_hits += exact_hits(sub, gp)
    if not sup_p:
        return {}
    p_pool, r_pool = _weighted(sup_p), _weighted(sup_r)
    return {
        "n_questions": len(sup_p), "submitted": n_sub, "gold": n_gold, "hits": n_hits,
        "precision": round(p_pool, 4), "recall": round(r_pool, 4),
        "score_2_4_1": score_recall_sup(r_pool), "score_2_4_2": score_precision_sup(p_pool),
        "unresolved_fact_ids": len(unresolved),
    }


# ---------------------------------------------------------------- 渲染

def _render_md(verdict: str, checks: dict[str, Any], per_case: list[dict[str, Any]],
               ladder: dict[str, Any], roots: list[str], gold_root: Path) -> str:
    lines = [
        "# C-160 件①＋件②｜客观 2.4 支撑面：现状量尺＋刀梯反事实",
        "",
        f"跑次根＝{'、'.join(roots)}｜金标根＝{gold_root}｜判定＝{verdict}",
        "",
        "## 尺（开工前写死）",
        "",
        "- 尺＝官方 `scripts/score_official.py` 原函数：先逐题算 Precision_sup／Recall_sup，"
        "再按金标条数加权汇总；2.4.1 完整性档＝R≥0.85→6／≥0.70→4／≥0.55→2／否则 0；"
        "2.4.2 准确率档＝P≥0.90→6／≥0.80→4／≥0.70→2／否则 0。",
        f"- 有肉门槛甲（pooled 双档）＝固定规则臂同时 Recall≥{RECALL_GATE} 且 Precision≥{PRECISION_GATE}，"
        f"且主尺案（{PRIMARY_CASE}）同样两条都过。",
        f"- 有肉门槛乙（逐案＝按专题口径）＝候选臂的 Σ案(2.4.1＋2.4.2) ≥ 现状臂＋{CASE_GAIN_GATE}，"
        "且不许把现状已得分的案打成 0 分；K 只用生产里已有的常数（细读面宽／Top-7 宽），"
        "曲线择优只作上界披露、不当刀。",
        "",
        "## 件① 交卷 2.4 现状（pooled）",
        "",
        f"- 题：计分 {checks['pooled']['n_questions_scored']}／缺题 {checks['pooled']['missing_questions']}"
        f"／金标该侧空 {checks['pooled']['empty_gold_questions']}",
        f"- 条数：提交 {checks['pooled']['submitted_pairs']} 条 vs 金标 {checks['pooled']['gold_pairs']} 条"
        f"（一对一命中 {checks['pooled']['hits_pairs']}）",
        f"- 分面：Precision_sup={checks['pooled']['precision']} Recall_sup={checks['pooled']['recall']}"
        f" ⇒ 2.4.1={checks['pooled']['score_2_4_1']}／6、2.4.2={checks['pooled']['score_2_4_2']}／6",
        f"- 空引题（该题金标有支撑而提交为空）＝{checks['pooled']['bare_questions']}；"
        f"锚可定位 {checks['pooled']['anchor_ok']}/{checks['pooled']['anchor_checked']}；"
        f"引文逐字可核 {checks['pooled']['quote_ok']}/{checks['pooled']['quote_checked']}",
        f"- 引用合规：台账引用 {checks['pooled']['ledger_pairs']} 段，其中越出授权面"
        f"（细读／焦点／Top7 定稿／盒／候选全序之外）＝{checks['pooled']['ledger_outside_band']} 段，"
        f"段键在本案语料里根本取不到＝{checks['pooled']['ledger_not_in_corpus']} 段；"
        f"打回且有引文 {checks['pooled']['rejected_with_quote']} 行，引文能在官方原文逐字回贴到段的＝"
        f"{checks['pooled']['rejected_relocated']} 行",
        "",
        "## 件① 逐案",
        "",
    ]
    for c in per_case:
        lines.append(
            f"- {c['case']}｜题 {c['questions_scored']}｜提交 {c['submitted_pairs']} 条／"
            f"金标 {c['gold_pairs']} 条｜P={c['precision_sup']} R={c['recall_sup']}｜"
            f"2.4.1={c['score_2_4_1']} 2.4.2={c['score_2_4_2']}｜空引 {c['bare_questions']}｜"
            f"锚 {c['anchor_ok']}/{c['anchor_checked']}｜逐字 {c['quote_ok']}/{c['quote_checked']}"
        )
    lines += ["", "## 件② 逐题候选池条数（腿 C）", ""]
    for c in per_case:
        for qid, d in c["per_question"].items():
            pool_txt = "／".join(f"{k.split('_', 1)[1]}={v}" for k, v in d["pool_n"].items())
            lines.append(
                f"- {c['case']}｜{qid}｜保留证据 {d['n_evidences']}｜打回 {d['n_rejected']}｜"
                f"逐字可核 {d['quote_ok']}/{d['quote_checked']}｜池：{pool_txt}"
            )
    def _arm_line(arm: str, r: dict[str, Any]) -> str:
        pc = (r.get("per_case") or {}).get(PRIMARY_CASE) or {}
        return (
            f"- {arm}｜题 {r.get('n_questions', '—')}｜提交 {r.get('submitted', '—')} 条／"
            f"金标 {r.get('gold', '—')} 条｜P={r.get('precision', '—')} R={r.get('recall', '—')}｜"
            f"2.4.1={r.get('score_2_4_1', '—')} 2.4.2={r.get('score_2_4_2', '—')}"
            f"｜双档过线={'是' if r.get('gates_pass') else '否'}"
            f"｜主尺案 P={pc.get('precision', '—')} R={pc.get('recall', '—')}"
            f"／2.4.1={pc.get('score_2_4_1', '—')} 2.4.2={pc.get('score_2_4_2', '—')}"
        )

    lines += ["", f"## 件② 刀梯·加宽族（腿 D，pooled；固定规则臂 {len(FIXED_ARMS)} 条）", ""]
    for arm in FIXED_ARMS:
        lines.append(_arm_line(arm, ladder["fixed"].get(arm) or {}))
    lines += ["", f"## 件② 刀梯·判别与补回族（腿 E，pooled；{len(FILTER_ARMS)} 条）", ""]
    for arm in FILTER_ARMS:
        lines.append(_arm_line(arm, ladder["filter"].get(arm) or {}))
    lines += ["", "## 件② 灌面上界参照（只披露、不当刀）", ""]
    for arm in CEILING_ARMS:
        lines.append(_arm_line(arm, ladder["ceiling"].get(arm) or {}))
    lines += ["", "## 件② 逐案（按专题）口径＝Σ(2.4.1＋2.4.2)，满分 "
              f"{checks.get('口径_逐案满分', '—')}（现状得分案＝{checks.get('口径_现状得分案', '—')}）", ""]
    for label, group in (
        ("加宽族", ladder["fixed"]), ("判别与补回族", ladder["filter"]),
        ("固定 K 候选刀", ladder["kfixed"]), ("灌面上界", ladder["ceiling"]),
    ):
        lines.append(f"- ｜{label}｜")
        for arm, r in group.items():
            pc = r.get("per_case") or {}
            detail = "、".join(
                f"{k}＝{v['score_2_4_1']}/{v['score_2_4_2']}"
                for k, v in sorted(pc.items())
                if v["score_2_4_1"] + v["score_2_4_2"] > 0
            ) or "无案得分"
            lines.append(
                f"  - {arm}｜Σ={r.get('case_score_sum', '—')}｜"
                f"得分案 {r.get('cases_scoring', '—')}/{r.get('cases_scoring_of', '—')}｜{detail}"
            )
    lines += ["", "## 件② 上界披露（K 曲线，选 K 用了金标＝只看不当刀）", ""]
    for arm, curve in ladder["sweep"].items():
        if not curve:
            lines.append(f"- {arm}｜曲线没取到档（未量）")
            continue
        best = max(curve, key=lambda x: x["score_sum"])
        best_case = max(curve, key=lambda x: x["case_score_sum"])
        lines.append(
            f"- {arm}｜扫 {len(curve)} 档｜pooled 最高 2.4 合计={best['score_sum']}"
            f"（K={best['k']}、P={best['precision']}、R={best['recall']}）｜"
            f"逐案 Σ 最高={best_case['case_score_sum']}（K={best_case['k']}、"
            f"得分案 {best_case['cases_scoring']}）"
        )
    cross = checks.get("旁证_跨跑次") or []
    lines += ["", "## 件① 跨跑次旁证（只重读腿 A 现状＝逐跑方差面）", ""]
    if cross:
        for row in cross:
            if row.get("missing"):
                lines.append(f"- {row['root']}｜跑次根不在盘上＝未取到数")
                continue
            lines.append(
                f"- {row['case']}｜{row['root'].split('/')[-1]}｜题 {row['n_questions']}｜"
                f"提交 {row['submitted']} 条／金标 {row['gold']} 条／命中 {row['hits']}｜"
                f"P={row['precision']} R={row['recall']}｜2.4.1={row['score_2_4_1']} "
                f"2.4.2={row['score_2_4_2']}｜换形未解析 fact_id＝{row['unresolved_fact_ids']}"
            )
    else:
        lines.append("- 未指定 --cross-roots＝本件无跨跑次旁证。")

    lines += [
        "",
        "## 核（每条自己取到分母；分母 0 记 not_measured 不算过）",
        "",
    ]
    for k, v in checks.items():
        if k == "pooled" or k.startswith("旁证"):
            continue
        lines.append(f"- {k}＝{v}")
    lines += [
        "",
        "## 卫生与红线",
        "",
    ]
    hy = (checks.get("卫生") or {}).get("windows")
    if hy:
        per_txt = "；".join(
            f"{name} 归一化 {d['chars']} 字／{d['windows']} 窗／命中 {d['hits']}"
            for name, d in sorted((hy.get("per_file") or {}).items())
        )
        lines.append(
            f"- 卫生扫描＝{hy['hits']} 窗命中／{hy['windows']} 窗（官方六案语料归一化 "
            f"{hy['corpus_chars']} 字、{checks['卫生']['docs']} 份文档），其中散文命中＝"
            f"{hy['prose_hits']}。逐件：{per_txt}。"
        )
    else:
        lines.append("- 卫生扫描＝本行为第一版占位，同名最终件里已换成现量真数。")
    lines += [
        "- 零 LLM、零网络、只读现跑次产物；本件不改 `app/`；"
        "金标只进量尺面，未进任何生产规则或提示词。",
        "- 臂＝候选池原样当提交面重算官方尺；K 曲线的 K 用了金标⇒只作上界披露，不许当刀。",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 主流程

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C-160 支撑面量尺＋刀梯")
    parser.add_argument("--roots", nargs="+", required=True, help="跑次根（含各案 conclusions.json）")
    parser.add_argument("--gold-root", default=str(OFFICIAL_DEFAULT))
    parser.add_argument("--out-dir", default="/tmp/c160")
    parser.add_argument("--cases", nargs="*", default=None, help="只量指定案名")
    parser.add_argument("--cross-roots", nargs="*", default=None,
                        help="旁证跑次根（只重读腿 A 现状，跨跑次方差）")
    args = parser.parse_args(argv)

    gold_root = Path(args.gold_root)
    if not gold_root.exists():
        print(f"找不到官方样例集：{gold_root}")
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    roots = [Path(r) for r in args.roots]
    cases: list[dict[str, Any]] = []
    used_roots: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        names = args.cases or sorted(
            p.name for p in root.iterdir()
            if p.is_dir() and (p / "conclusions.json").exists()
        )
        for name in names:
            if any(c["case"] == name and c["_root"] == str(root) for c in cases):
                continue
            m = measure_case(root, name, gold_root)
            m["_root"] = str(root)
            cases.append(m)
        used_roots.append(str(root))

    scored = [c for c in cases if c.get("questions_scored")]
    per_case_view = [
        {k: v for k, v in c.items() if not k.startswith("_")} for c in scored
    ]

    # pooled 现状＝跨案把所有金标题拉平，同尺同权重（金标条数）
    sup_p: list[tuple[float, int]] = []
    sup_r: list[tuple[float, int]] = []
    for c in scored:
        gold_map = c.get("_gold") or {}
        for qid, pairs in gold_map.items():
            sub = (c.get("_pools", {}).get(qid) or {}).get("A_交卷现状") or []
            p, r = precision_recall(sub, pairs)
            sup_p.append((p, len(pairs)))
            sup_r.append((r, len(pairs)))
    p_all, r_all = _weighted(sup_p), _weighted(sup_r)
    pooled = {
        "n_questions_scored": len(sup_p),
        "missing_questions": sum(int(c.get("missing_questions") or 0) for c in scored),
        "empty_gold_questions": sum(int(c.get("empty_gold_questions") or 0) for c in scored),
        "submitted_pairs": sum(int(c.get("submitted_pairs") or 0) for c in scored),
        "gold_pairs": sum(int(c.get("gold_pairs") or 0) for c in scored),
        "hits_pairs": sum(int(c.get("hits_pairs") or 0) for c in scored),
        "bare_questions": sum(int(c.get("bare_questions") or 0) for c in scored),
        "anchor_ok": sum(int(c.get("anchor_ok") or 0) for c in scored),
        "anchor_checked": sum(int(c.get("anchor_checked") or 0) for c in scored),
        "quote_ok": sum(int(c.get("quote_ok") or 0) for c in scored),
        "quote_checked": sum(int(c.get("quote_checked") or 0) for c in scored),
        "ledger_pairs": sum(int(c.get("ledger_pairs") or 0) for c in scored),
        "ledger_outside_band": sum(int(c.get("ledger_outside_band") or 0) for c in scored),
        "ledger_not_in_corpus": sum(int(c.get("ledger_not_in_corpus") or 0) for c in scored),
        "rejected_with_quote": sum(int(c.get("rejected_with_quote") or 0) for c in scored),
        "rejected_relocated": sum(int(c.get("rejected_relocated") or 0) for c in scored),
        "precision": round(p_all, 4), "recall": round(r_all, 4),
        "score_2_4_1": score_recall_sup(r_all), "score_2_4_2": score_precision_sup(p_all),
    }

    # 腿 D＋腿 E：固定规则臂（加宽族／判别族）＋K 曲线（曲线只作上界披露）
    ladder: dict[str, Any] = {"fixed": {}, "filter": {}, "ceiling": {}, "kfixed": {}, "sweep": {}}
    for arm in FIXED_ARMS:
        ladder["fixed"][arm] = _arm_readout(scored, arm, None)
    for arm in FILTER_ARMS:
        ladder["filter"][arm] = _arm_readout(scored, arm, None)
    for arm in CEILING_ARMS:
        ladder["ceiling"][arm] = _arm_readout(scored, arm, None)
    for arm, k in K_FIXED:
        ladder["kfixed"][f"{arm}@K={k}"] = _arm_readout(scored, arm, k)
    for arm in ("H_rerank全序", "E_焦点面", "B_本题台账", "C_全部带证据结论", "D_细读面"):
        curve = []
        for k in K_SWEEP:
            r = _arm_readout(scored, arm, k)
            if r.get("n_questions"):
                curve.append({"k": k, "precision": r["precision"], "recall": r["recall"],
                              "score_sum": r["score_sum"], "submitted": r["submitted"],
                              "hits": r["hits"], "gates_pass": r["gates_pass"],
                              "case_score_sum": r["case_score_sum"],
                              "cases_scoring": r["cases_scoring"]})
        ladder["sweep"][arm] = curve

    def _arm(arm: str) -> dict[str, Any]:
        return ladder["fixed"].get(arm) or ladder["filter"].get(arm) or {}

    passing = [
        arm for arm in CANDIDATE_ARMS
        if _arm(arm).get("gates_pass")
        and ((_arm(arm).get("per_case") or {}).get(PRIMARY_CASE) or {}).get("score_2_4_1", 0) > 0
        and ((_arm(arm).get("per_case") or {}).get(PRIMARY_CASE) or {}).get("score_2_4_2", 0) > 0
    ]
    # 只过 2.4.2 首档（P≥0.70）的候选＝「收窄买准确率」那条路的读数
    precision_only = [
        arm for arm in CANDIDATE_ARMS
        if float(_arm(arm).get("precision") or 0) >= PRECISION_GATE
        and float((_arm(arm).get("per_case") or {}).get(PRIMARY_CASE, {}).get("precision") or 0)
        >= PRECISION_GATE
    ]
    any_measured = bool(scored) and pooled["n_questions_scored"] > 0 and pooled["gold_pairs"] > 0

    # 第二道门槛（逐案＝按专题口径）：候选臂要把现状分抬净涨 ≥CASE_GAIN_GATE 且不掉已得分的案
    def _scoring_names(r: dict[str, Any]) -> set[str]:
        pc = r.get("per_case") or {}
        return {
            k for k, v in pc.items()
            if int(v.get("score_2_4_1") or 0) + int(v.get("score_2_4_2") or 0) > 0
        }

    a_now = ladder["fixed"]["A_交卷现状"] or {}
    a_case_sum = int(a_now.get("case_score_sum") or 0)
    a_scoring = _scoring_names(a_now)
    candidates_case = dict(ladder["kfixed"])
    for arm in CANDIDATE_ARMS:
        candidates_case[arm] = _arm(arm)
    uplift = [
        name for name, r in candidates_case.items()
        if int(r.get("case_score_sum") or 0) >= a_case_sum + CASE_GAIN_GATE
        and not (a_scoring - _scoring_names(r))
    ]
    drops = [
        name for name, r in candidates_case.items()
        if a_scoring - _scoring_names(r)
    ]

    checks: dict[str, Any] = {
        "pooled": pooled,
        "腿A_题数>0（非空比空）": pooled["n_questions_scored"] > 0,
        "腿A_金标条数>0": pooled["gold_pairs"] > 0,
        "腿A_提交条数>0": pooled["submitted_pairs"] > 0,
        "腿A_逐案都取到数": len(scored) == len(cases) and all(c.get("questions_scored") for c in scored),
        "腿B_语料段落键取到": all(int(c.get("corpus_para_n") or 0) > 0 for c in scored),
        "腿B_锚分母>0": pooled["anchor_checked"] > 0,
        "腿B_逐字分母>0": pooled["quote_checked"] > 0,
        "腿F_打回有引文行>0": pooled["rejected_with_quote"] > 0,
        "腿C_每题池面都取到数": all(
            set(d["pool_n"]) >= set(FIXED_ARMS) - {"A_交卷现状"}
            for c in scored for d in c["per_question"].values()
        ),
        "腿C_台账空题数": sum(
            1 for c in scored for d in c["per_question"].values()
            if (d["pool_n"].get("B_本题台账") or 0) == 0
        ),
        "腿D_A臂＝腿A现状读数": abs(
            float((ladder["fixed"]["A_交卷现状"] or {}).get("precision") or -1) - pooled["precision"]
        ) < 1e-9 and abs(
            float((ladder["fixed"]["A_交卷现状"] or {}).get("recall") or -1) - pooled["recall"]
        ) < 1e-9,
        "腿D_候选臂全取到读数": all(
            _arm(a).get("n_questions", 0) > 0 for a in CANDIDATE_ARMS
        ),
        "腿E_灌面上界取到读数": all(
            (ladder["ceiling"].get(a) or {}).get("n_questions", 0) > 0 for a in CEILING_ARMS
        ),
        "判定_双档过线臂": passing or "无（任何固定规则臂都没同时过 Recall≥0.55 与 Precision≥0.70）",
        "判定_仅准确率过线臂": precision_only or "无（没有臂把 pooled Precision 抬到 0.70）",
    }
    checks["口径_逐案现状Σ"] = a_case_sum
    checks["口径_逐案满分"] = 12 * len(a_now.get("per_case") or {})
    checks["口径_现状得分案"] = sorted(a_scoring)
    checks["口径_净涨臂"] = (
        uplift or f"无（没有候选臂把逐案 Σ 抬到现状 {a_case_sum}＋{CASE_GAIN_GATE} 以上且不掉已得分案）"
    )
    checks["口径_会清零现状分的臂"] = drops or "无"
    for name, val in list(checks.items()):
        if isinstance(val, bool):
            checks[name] = "过" if val else "红"

    ceiling = ladder["ceiling"].get(CEILING_ARMS[0]) or {}
    checks["参照_灌面能买到什么"] = (
        f"{CEILING_ARMS[0]}：R={ceiling.get('recall')}（2.4.1={ceiling.get('score_2_4_1')}）"
        f"／P={ceiling.get('precision')}（2.4.2={ceiling.get('score_2_4_2')}）"
        f"＝把全案卷段落都当支撑交，只买完整性档、准确率必 0"
    )

    # 旁证腿＝同一份尺在别的跑次上重读现状（跨跑次方差，不建池、零模型）
    cross: list[dict[str, Any]] = []
    for raw in (args.cross_roots or []):
        croot = Path(raw)
        if not croot.exists():
            cross.append({"root": str(croot), "missing": True})
            continue
        for case_dir in sorted(p for p in croot.iterdir() if p.is_dir()):
            one = quick_current(croot, case_dir.name, gold_root)
            if one:
                cross.append({"root": str(croot), "case": case_dir.name, **one})
    checks["旁证_跨跑次"] = cross

    # 卫生扫描
    md_path = out_dir / "C160_support_face.md"
    json_path = out_dir / "C160_support_face.json"
    payload = {
        "ticket": "C-160", "roots": used_roots, "gold_root": str(gold_root),
        "gates": {"recall": RECALL_GATE, "precision": PRECISION_GATE},
        "primary_case": PRIMARY_CASE,
        "pooled": pooled, "per_case": per_case_view,
        "ladder": ladder, "checks": checks,
        "passing_arms": passing, "precision_only_arms": precision_only,
    }
    verdict = "NO（腿没量成）"
    if any_measured:
        if passing:
            verdict = "YES（pooled 双档过线臂＝开实现刀）"
        elif uplift:
            verdict = "YES（逐案口径净涨臂＝开实现刀）＝" + "、".join(uplift)
        elif precision_only:
            verdict = (
                "PARTIAL（无臂双档过线；只有收窄臂过 2.4.2 准确率首档＝"
                + "、".join(precision_only) + "，是否开刀等拍板）"
            )
        else:
            verdict = "PARTIAL（量到了，无固定规则臂过线＝只量不开刀）"
    payload["verdict"] = verdict
    # 第一版先落盘（卫生句写「待扫描」），扫完再整件重写＝产物里的数字全是现量
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    md_path.write_text(
        _render_md(verdict, checks, per_case_view, ladder, used_roots, gold_root), encoding="utf-8")

    corpus_norm, n_docs = _corpus_text(gold_root)
    hy = windows_hit([md_path, json_path], corpus_norm)
    checks["卫生"] = {"windows": hy, "docs": n_docs,
                  "判定": "过" if hy["prose_hits"] == 0 and hy["windows"] > 0 else "红"}
    payload["hygiene"] = checks["卫生"]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    md_path.write_text(
        _render_md(verdict, checks, per_case_view, ladder, used_roots, gold_root), encoding="utf-8")

    print(f"判定 {verdict}")
    print(f"pooled 现状：P={pooled['precision']} R={pooled['recall']} "
          f"⇒ 2.4.1={pooled['score_2_4_1']} 2.4.2={pooled['score_2_4_2']}"
          f"（题 {pooled['n_questions_scored']}、提交 {pooled['submitted_pairs']} 条／金标 {pooled['gold_pairs']} 条）")
    for arm in CANDIDATE_ARMS + CEILING_ARMS:
        r = _arm(arm) or ladder["ceiling"].get(arm) or {}
        print(f"  臂 {arm}: P={r.get('precision')} R={r.get('recall')} "
              f"2.4.1={r.get('score_2_4_1')} 2.4.2={r.get('score_2_4_2')} "
              f"主尺案 P={(r.get('per_case', {}).get(PRIMARY_CASE) or {}).get('precision')}")
    print(f"卫生：窗 {hy['windows']}／命中 {hy['hits']}／散文 {hy['prose_hits']}")
    print(f"产物：{md_path} ／ {json_path}")
    return 0 if any_measured else 1


if __name__ == "__main__":
    raise SystemExit(main())
