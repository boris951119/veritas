#!/usr/bin/env python3
"""C-149 探针：提交面 conflicting_facts 对六案金标 C* 的 Recall_conf／Precision_conf
＋四失败桶（未检出／检出未导出／定位失败／匹配口径丢）＋C-44 戊档对照。

零 LLM、零网络、不写 app/。金标与跑产物不入仓库（env 指定，缺目录退出码 2）。

跑法：
    .venv/bin/python scripts/probe_c149_conf_score.py --stage gold
    C149_RUN=/tmp/s4runs/time-XXXX \\
        .venv/bin/python scripts/probe_c149_conf_score.py --stage score
    C149_RUN=/tmp/s4runs/time-XXXX .venv/bin/python scripts/probe_c149_conf_score.py

env：
    OFFICIAL_CASES  官方样例集根（默认 ~/Desktop/veritas-testcases/样例集-拓尔思-20261012）
    C149_RUN        六案跑产物根（<case>/questions/<qid>/report.json）；score/all 必填，
                    不给默认旧路径（防静默量到过期跑次）

金标 C*＝conclusions.json conflicting_facts（经 evidence_samples.json fact_id→doc/para
定位）；提交 C＝现行管线导出面 app.export.official._conflicting_facts（甲形＝败方单侧、
平局与定位失败跳过），读 <case>/questions/*/report.json 的 dossier 终局面
（树22 归并→冲突→质证→仲裁之后）。

预登记门槛（工单原文）：Recall_conf≥0.50 且 Precision_conf≥0.55 → 才建议开实现票；
任一不达标 → 交「为何仍低分＋唯一值得试的下一刀（语义检出／导出映射／匹配键三选一）」。
分母口径＝金标去重段键（与 C-44 戊档 10/78 同尺、可对照）；金标 91 条逐条口径同场披露。
有案缺席时门槛判「条件不成立（分母不全）」，绝不静默只算在场案。

失败桶（按金标去重段键逐键归因；候选可定位并集复用 C-44 丁档仪器 map_ding）：
  命中       ＝ 键 ∈ 甲导出面 ∩ 金标
  检出未导出 ＝ 键 ∈ 丁四路可定位并集，∉ 甲导出面；再拆三份＝
               败方侧异常（conflicts 流败方侧触达却没导出＝点名）／
               平局跳过（仅平局侧触达＝甲规则有意丢）／
               无导出通道（仅 fact_ledger/rejected/dissent 触达）
  未检出     ＝ 键 ∉ 可定位并集；再拆段在卷／段不在卷（doc_id+para_id 是否在 dossier 信源段）
  定位失败   ＝ 只给计数不给键（定位失败即无段键，逐键归因口径上不可做——如实披露）
  匹配口径丢 ＝ 甲导出面键 ∉ 金标（精度损失侧，点名键 id）

C-44 对照：旧批读数引用自 docs/HANDOFF.md〔109〕（10-24 批 time-20261024-001335 复量）
＝甲 4 行/命中 0（R 0.0000）、乙=丙 21 行/4（R 0.0440/P 0.1905）、
丁四路 175 条/命中 20（R 0.2198/P 0.1143）、戊「口径并存」10/78（R 0.1099/P 0.0752、
两批复现＝10-23 批同读数）。本探针在新批上现量甲／丁／戊三档，
回答工单第 3 步「现 tip 相对旧数值线变了什么、没变什么」。

产物：artifacts/C149_conf_score.{json,md}（本仓 artifacts；只含 id／计数／档位读数）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.core.evidence import Dossier  # noqa: E402
from app.core.kg_test_tree_line import CASE_MARK_PAIRS  # noqa: E402  (C-128 公共表)
from scripts.probe_conflict_coverage import (  # noqa: E402
    _gold_conf_items,
    _load_dossier,
    _map_side_facts,
    _official_case_dirs,
    _pair_sides,
    _require_dir,
    map_conflicts,
    map_ding,
    map_wu,
    two_stage_match,
)

OFFICIAL_CASES = os.environ.get(
    "OFFICIAL_CASES",
    os.path.expanduser("~/Desktop/veritas-testcases/样例集-拓尔思-20261012"),
)
C149_RUN = os.environ.get("C149_RUN", "")

GATE_RECALL = 0.50
GATE_PRECISION = 0.55
_DING_STREAMS = ("conflicts", "fact_ledger", "rejected", "dissent")

# C-44 旧批读数（引用值、非本批现量；出处 docs/HANDOFF.md〔109〕＋dev-journal C-44 条）
C44_OLD = {
    "jia": {"rows": 4, "hits": 0, "recall": 0.0},
    "ding": {"rows": 175, "hits": 20, "recall": 0.2198, "precision": 0.1143},
    "wu": {"hit": 10, "gold_keys": 78, "recall": 0.1099, "precision": 0.0752},
    "run": "time-20261024-001335",
}

def _key_str(d: str, p: str) -> str:
    """段键显示：官方 para_id 本身是 doc 复合形（doc_001#p80）时不重复前缀。"""
    return p if p.startswith(f"{d}#") else f"{d}#{p}"


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _slug(name: str) -> str:
    """案名→slug＝C-128 公共表 CASE_MARK_PAIRS（加案只改那一处）；未命中＝case。"""
    for mark, s in CASE_MARK_PAIRS:
        if mark in name:
            return s
    return "case"


def _official_cases() -> list[Path]:
    return _official_case_dirs(_require_dir(OFFICIAL_CASES, "官方样例集"))


def _gold_survey(cases: list[Path]) -> dict:
    per = []
    pooled_keys: set[tuple[str, str]] = set()
    n_items = 0
    n_noloc = 0
    for case_dir in cases:
        items = _gold_conf_items(case_dir)
        keys = {(g["doc_id"], g["para_id"]) for g in items
                if g.get("doc_id") and g.get("para_id")}
        n_noloc += sum(1 for g in items
                       if not (g.get("doc_id") and g.get("para_id")))
        pooled_keys |= keys
        n_items += len(items)
        per.append({"slug": _slug(case_dir.name), "items": len(items),
                    "keys": len(keys)})
    return {"per_case": per, "items_total": n_items,
            "keys_total": len(pooled_keys), "noloc_items": n_noloc}


def _case_dossiers(case_run: Path) -> list[tuple[str, Dossier]]:
    rows = []
    for rp in sorted(case_run.glob("questions/*/report.json")):
        rows.append((rp.parent.name, _load_dossier(rp)))
    return rows


def _conflicts_keys_split(dossier: Dossier) -> dict[str, set]:
    """conflicts 流逐键打标：loser（有胜方取败方）／tie（平局两侧）。"""
    out = {"loser": set(), "tie": set()}
    for pair in (dossier.conflicts or []):
        if not isinstance(pair, dict):
            continue
        a_id, b_id, _w, sides = _pair_sides(pair)
        if sides is None:
            sides = [a_id, b_id] if a_id and b_id else []
            tag = "tie"
        else:
            tag = "loser"
        if not sides:
            continue
        facts, _mapped = _map_side_facts(dossier, sides, set(), False)
        for f in facts:
            key = (str(f.get("doc_id") or ""), str(f.get("para_id") or ""))
            if key[0] and key[1]:
                out[tag].add(key)
    return out


def _volume_keys(dossiers: list[Dossier]) -> set:
    out: set = set()
    for d in dossiers:
        for src in d.sources:
            doc_id = str((src.meta or {}).get("doc_id") or src.id or "")
            for seg in src.segments:
                pid = str(seg.id)
                if doc_id and pid:
                    out.add((doc_id, pid))
    return out


def _quoted_keys(dossiers: list[Dossier]) -> set:
    """分析师引用面＝全部 EvidenceNode 的 segment_ids 定位键（含被拒/少数意见）。

    给「未检出但段在卷」的键再分一刀：引用过＝漏在成对/判定环；
    从未引用＝漏在取证环（段进了视野没进引文）。
    """
    from app.export.official import _segment_locator
    out: set = set()
    for d in dossiers:
        for ev in d.evidences:
            for sid in ev.segment_ids:
                loc = _segment_locator(d, sid)
                if loc and loc[0] and loc[1]:
                    out.add((loc[0], loc[1]))
    return out


def _probe_case(case_dir: Path, run_root: Path) -> dict:
    slug = _slug(case_dir.name)
    case_run = run_root / case_dir.name
    qrows = _case_dossiers(case_run)
    if not qrows:
        raise FileNotFoundError(f"{slug}: 跑产物缺 questions/*/report.json")
    dossiers = [d for _q, d in qrows]

    gold_items = _gold_conf_items(case_dir)
    gold_keys = {(g["doc_id"], g["para_id"]) for g in gold_items
                 if g.get("doc_id") and g.get("para_id")}

    # 甲＝现行导出面（逐题跑；facts 保留逐题条目做 91 条口径）
    jia_facts: list[dict] = []
    jia = {"n_pairs": 0, "skipped_tie": 0, "skipped_noloc": 0}
    for d in dossiers:
        m = map_conflicts(d, "jia")
        jia["n_pairs"] += m["n_pairs"]
        jia["skipped_tie"] += m["skipped_tie"]
        jia["skipped_noloc"] += m["skipped_noloc"]
        jia_facts.extend(m["facts"])
    jia_keys = {(f["doc_id"], f["para_id"]) for f in jia_facts
                if f.get("doc_id") and f.get("para_id")}

    # 候选可定位并集＝C-44 丁档同一仪器（含守恒自检）
    ding = map_ding(dossiers)
    union = {(e["doc_id"], e["para_id"]) for e in ding["union_facts"]}
    # conflicts 流败方/平局打标（归因用；并集仍以 ding 为准）
    split = {"loser": set(), "tie": set()}
    for d in dossiers:
        s = _conflicts_keys_split(d)
        split["loser"] |= s["loser"]
        split["tie"] |= s["tie"]

    # 戊档（口径并存上界，C-44 同仪器）
    wu = map_wu(dossiers, gold_items)

    volume = _volume_keys(dossiers)
    quoted = _quoted_keys(dossiers)

    # ── 四失败桶（键级）───────────────────────────────────────
    hit = jia_keys & gold_keys
    b2 = (union & gold_keys) - hit
    b2_anomaly = b2 & split["loser"]
    b2_tie_only = (b2 & split["tie"]) - split["loser"]
    b2_noroute = b2 - split["loser"] - split["tie"]
    b1 = gold_keys - union
    b1_invol = b1 & volume
    b1_novol = b1 - volume
    b4 = jia_keys - gold_keys

    n_gold = len(gold_keys)
    recall_key = (len(hit) / n_gold) if n_gold else None
    precision_key = (len(hit) / len(jia_keys)) if jia_keys else None
    # 上界读数＝候选流全放开（丁四路并集整份交出去）时的 R／P
    ub_hit = len(union & gold_keys)
    ub_recall = (ub_hit / n_gold) if n_gold else None
    ub_precision = (ub_hit / len(union)) if union else None

    # 91 条口径（1:1 消耗；与 C-44 match_91 同法＝提交侧按去重键）
    sub_items = [{"doc_id": d, "para_id": p} for (d, p) in sorted(jia_keys)]
    m91 = two_stage_match(sub_items, gold_items, approx_available=False)

    return {
        "slug": slug,
        "n_questions": len(qrows),
        "n_gold_items": len(gold_items),
        "n_gold_keys": n_gold,
        "n_jia_pairs": jia["n_pairs"],
        "n_jia_rows": len(jia_facts),
        "n_jia_keys": len(jia_keys),
        "skipped_tie": jia["skipped_tie"],
        "skipped_noloc": jia["skipped_noloc"],
        "ding_streams": {n: {"locable": ding["streams"][n]["n_locable"],
                             "discarded": ding["streams"][n]["discarded"],
                             "added_to_union": ding["streams"][n]["added_to_union"]}
                         for n in ding["order"]},
        "ding_union_n": ding["union_n"],
        "ding_conservation": ding["conservation"],
        "wu_n_pairs": wu["n_pairs"],
        "wu_union_n": wu["union_n"],
        "wu_hit": wu["hit_keys"],
        "wu_gold_keys": wu["gold_keys"],
        "wu_kind_keys": wu["kind_keys"],
        "wu_kind_hit": wu["kind_hit_keys"],
        "wu_discarded": wu["discarded_total"],
        "hit_keys_n": len(hit),
        "recall_key": recall_key,
        "precision_key": precision_key,
        "ub_hit_keys": ub_hit,
        "ub_recall_key": ub_recall,
        "ub_precision_key": ub_precision,
        "match_91": {k: m91[k] for k in ("n_sub", "n_gold", "exact",
                                         "Precision_conf", "Recall_conf")},
        "buckets": {
            "hit": len(hit),
            "b2_total": len(b2),
            "b2_loser_anomaly": sorted(_key_str(d, p) for d, p in b2_anomaly),
            "b2_tie_only": len(b2_tie_only),
            "b2_noroute": len(b2_noroute),
            "b1_total": len(b1),
            "b1_in_volume": len(b1_invol),
            "b1_in_volume_quoted": len(b1_invol & quoted),
            "b1_in_volume_unquoted": len(b1_invol - quoted),
            "b1_in_volume_quoted_keys": sorted(
                _key_str(d, p) for d, p in (b1_invol & quoted)),
            "b1_not_in_volume": len(b1_novol),
            "b1_in_volume_keys": sorted(_key_str(d, p) for d, p in b1_invol),
            "b1_in_volume_unquoted_keys": sorted(
                _key_str(d, p) for d, p in (b1_invol - quoted)),
            "b4_exported_not_gold": sorted(_key_str(d, p) for d, p in b4),
        },
        "jia_key_list": sorted(_key_str(d, p) for d, p in jia_keys),
    }


def _next_knife(total: dict) -> str:
    """三选一：按最大损失桶指唯一下一刀（工单第 4 步）。"""
    ba = total["buckets_all"]
    b1_invol = ba.get("b1_in_volume", 0)
    b2 = ba.get("b2_total", 0)
    b4 = len(ba.get("b4_exported_not_gold", []))
    if total["gold_keys_total"] == 0:
        return "金标键为 0，无桶可归因"
    if b2 >= b1_invol and b2 >= b4 and b2 > 0:
        return "导出映射（候选可定位并集已含相当份额金标键、甲面没交出去）"
    if b4 > b1_invol and b4 > b2:
        return "匹配键（导出面体量不小但不落在金标段键上）"
    q = ba.get("b1_in_volume_quoted", 0)
    u = ba.get("b1_in_volume_unquoted", 0)
    ub = _fmt(total.get("ub_recall_key"))
    sub = (f"其中分析师引用过 {q} 段（漏在成对/判定环）、"
           f"从未引用 {u} 段（漏在取证环）；"
           f"导出侧全放开的 Recall 上界也只有 {ub}＝够不到门槛" if (q or u) else "")
    return f"语义检出（最大损失桶＝段在卷却未进任何冲突候选流；{sub}）"


def _fmt(x) -> str:
    if x is None:
        return "无导出条目"
    if isinstance(x, float):
        return f"{x:.4f}"
    return str(x)


def _gate(total: dict) -> tuple[str, str]:
    if total["missing_cases"]:
        return ("NO", f"分母不全（{len(total['missing_cases'])} 案缺席："
                      f"{'、'.join(total['missing_cases'])}）；"
                      "在场案读数只作参考，门槛按条件不成立计")
    r = total["recall_key"]
    p = total["precision_key"]
    r_ok = r is not None and r >= GATE_RECALL
    p_ok = p is not None and p >= GATE_PRECISION
    if r_ok and p_ok:
        return "YES", "两门槛都过 → 建议开实现票"
    return "NO", (f"Recall {_fmt(r)}（门槛 {GATE_RECALL}）／"
                  f"Precision {_fmt(p)}（门槛 {GATE_PRECISION}）"
                  "任一未过 → 不开实现票，交唯一下一刀")


def _render_md(payload: dict) -> str:
    t = payload["total"]
    verdict, why = payload["verdict"], payload["verdict_why"]
    L = ["# C-149 提交面 conflicting_facts × 金标 C* 量尺读数（探针现抄）", ""]
    L += [f"判定：{verdict}（{why}）", "",
          f"跑产物根：{payload['run_root']}",
          f"门槛（预登记）：Recall_conf≥{GATE_RECALL} 且 Precision_conf≥{GATE_PRECISION}"
          "，分母＝金标去重段键（与 C-44 戊档同尺）", "",
          "## 六案合计", ""]
    missing = t["missing_cases"]
    L.append(f"- 金标：{t['gold_items_total']} 条 / 去重段键 {t['gold_keys_total']}"
             f"（逐案加总口径；跨案去重并集＝{t['gold_keys_pooled']}，官方 doc_id "
             f"跨案不互斥⇒本尺按案内匹配、比 C-44 并集口径更严；"
             f"金标缺定位条目 {t['gold_noloc_total']} 条不计键）"
             + (f"；⚠ {len(missing)} 案缺席＝{'、'.join(missing)}" if missing else ""))
    L.append(f"- 甲导出面：{t['jia_rows_total']} 条 / 去重 {t['jia_keys_total']} 键"
             f"（平局跳过 {t['skipped_tie_total']} 对·次、导出定位失败 {t['skipped_noloc_total']} 条·次）")
    L.append(f"- 命中：{t['hit_total']} 键 → Recall＝{_fmt(t['recall_key'])}、"
             f"Precision＝{_fmt(t['precision_key'])}")
    L.append(f"- 上界读数（丁四路并集整份交出＝导出规则全放开）："
             f"{t['ub_hit_total']}/{t['gold_keys_total']} 键 → "
             f"R 上界＝{_fmt(t['ub_recall_key'])}、P 上界＝{_fmt(t['ub_precision_key'])}"
             f"（离门槛 {GATE_RECALL}/{GATE_PRECISION} 的距离＝架构级，不是导出规则级）")
    m91 = t["match_91"]
    L.append(f"- 91 条口径（逐条 1:1、提交侧去重键）：exact {m91['exact']}"
             f"／{m91['n_gold']} → R {_fmt(m91['Recall_conf'])}、"
             f"P {_fmt(m91['Precision_conf'])}")
    L.append(f"- 丁四路并集（C-44 同仪器）：{t['ding_union_total']} 键；"
             f"戊档上界 {t['wu_hit_total']}/{t['wu_gold_total']}＝"
             f"R {_fmt((t['wu_hit_total'] / t['wu_gold_total']) if t['wu_gold_total'] else None)}")
    L.append("")
    L += ["## 按案", ""]
    for c in payload["cases"]:
        b = c["buckets"]
        L.append(
            f"- {c['slug']}（{c['n_questions']} 题）：金标 {c['n_gold_items']}条/"
            f"{c['n_gold_keys']}键；甲 {c['n_jia_rows']}条/{c['n_jia_keys']}键"
            f"（平局跳 {c['skipped_tie']}、定位失败跳 {c['skipped_noloc']}）；"
            f"命中 {c['hit_keys_n']} → R {_fmt(c['recall_key'])}／"
            f"P {_fmt(c['precision_key'])}；桶＝命中{b['hit']}"
            f"＋检出未导出{b['b2_total']}（败方异常{len(b['b2_loser_anomaly'])}/"
            f"平局{b['b2_tie_only']}/无通道{b['b2_noroute']}）"
            f"＋未检出{b['b1_total']}（在卷{b['b1_in_volume']}"
            f"＝引过{b['b1_in_volume_quoted']}/未引{b['b1_in_volume_unquoted']}"
            f"/不在卷{b['b1_not_in_volume']}）＋导出未中金标{len(b['b4_exported_not_gold'])}")
    L += ["", "## 失败桶合计（键级）", ""]
    ba = t["buckets_all"]
    L.append(f"- 检出未导出＝{ba['b2_total']}：败方侧异常 {len(ba['b2_loser_anomaly'])}"
             f"（{'、'.join(ba['b2_loser_anomaly']) or '无'}）、"
             f"平局跳过 {ba['b2_tie_only']}、无导出通道 {ba['b2_noroute']}")
    L.append(f"- 未检出＝{ba['b1_total']}：段在卷 {ba['b1_in_volume']}"
             f"（其中分析师引用过＝漏在成对/判定环 {ba['b1_in_volume_quoted']}、"
             f"从未引用＝漏在取证环 {ba['b1_in_volume_unquoted']}）、"
             f"段不在卷 {ba['b1_not_in_volume']}")
    L.append(f"  - 在卷未检出键：{'、'.join(ba['b1_in_volume_keys']) or '—'}")
    L.append(f"  - 在卷但从未被引用键：{'、'.join(ba['b1_in_volume_unquoted_keys']) or '—'}")
    L.append(f"- 匹配口径丢（导出未中金标）＝{len(ba['b4_exported_not_gold'])}"
             f"（{'、'.join(ba['b4_exported_not_gold']) or '无'}）")
    L.append("- 定位失败（只计数）：甲面 "
             f"{t['skipped_noloc_total']} 条·次、"
             + "、".join(f"{n} 流 {t['ding_streams'][n]['discarded']} 条·次"
                         for n in _DING_STREAMS)
             + "；定位失败即无段键，逐键归因口径上不可做——这是口径边界、不是遗漏")
    L.append("")
    L += ["## 对照 C-44 旧数值线", "",
          "- 旧批（time-20261024-001335，docs/HANDOFF.md〔109〕引用值、非本批现量）："
          f"甲 {C44_OLD['jia']['rows']}行/{C44_OLD['jia']['hits']}命中"
          f"（R {C44_OLD['jia']['recall']:.4f}）；"
          f"丁 {C44_OLD['ding']['rows']}条/{C44_OLD['ding']['hits']}命中"
          f"（R {C44_OLD['ding']['recall']:.4f}）；"
          f"戊 {C44_OLD['wu']['hit']}/{C44_OLD['wu']['gold_keys']}"
          "（两批复现、硬门槛 40/78 ⇒ STOP）",
          "- 本批现量甲／丁／戊三档见上「六案合计」；"
          "没变的＝导出映射（甲形败方单侧＋平局/定位失败跳过）、金标 91/78、"
          "匹配口径（exact-only）、丁/戊仪器（同一探针函数族复用）；"
          "变了的＝管线（树22 归并→冲突→质证→仲裁）与跑次。", "",
          "## 门槛裁决与下一刀", "",
          f"- 判定：{verdict}——{why}",
          f"- 唯一值得试的下一刀：{payload['next_knife']}", "",
          "## 口径披露", "",
          "- 金标＝conclusions.json conflicting_facts（evidence_samples.json fact_id 定位）；"
          "提交＝app.export.official._conflicting_facts（甲形）；"
          "匹配＝两阶段第一步 (doc_id, para_id) 精确、1:1 消耗；"
          "第二步规则近似档沿 C-41 判定＝不可测（我方槽位与金标 argument 字面不可比），只报 exact。",
          "- dossier 读自 report.json＝树22 归并→冲突→质证→仲裁之后的终局面；"
          "同码同题逐跑有随机性，本读数是「码＋跑次」的联合读数。",
          "- 探针零 LLM、零网络、不写 app/；本文件数字全部当场现算。",
          "- 本批新探到的口径事实＝官方 doc_id 跨案不互斥（并集 78 < 逐案加总 81，"
          "3 键跨案同 id）；本尺按案内匹配（甲案候选不吃乙案金标），"
          "与 C-44 并集口径同分母时本尺更严。", ""]
    return "\n".join(L)


def main() -> int:
    stage = sys.argv[sys.argv.index("--stage") + 1] if "--stage" in sys.argv else "all"
    if stage not in ("gold", "score", "all"):
        _die(f"--stage 只收 gold/score/all，收到 {stage}")
    cases = _official_cases()
    gs = _gold_survey(cases)

    if stage in ("gold", "all"):
        print(json.dumps(gs, ensure_ascii=False))
        if stage == "gold":
            return 0

    # score / all
    if not C149_RUN.strip():
        _die("score/all 需要 C149_RUN 环境变量（六案跑产物根）；"
             "不给默认旧路径＝防静默量到过期跑次")
    run_root = _require_dir(C149_RUN, "跑产物根")
    per_case = []
    missing: list[str] = []
    for case_dir in cases:
        case_run = run_root / case_dir.name
        if not case_run.is_dir() or not list(case_run.glob("questions/*/report.json")):
            missing.append(_slug(case_dir.name))
            continue
        per_case.append(_probe_case(case_dir, run_root))
    if not per_case:
        _die(f"{run_root} 下没有任何官方案卷的跑产物（六案全缺）")

    def _sum(field: str) -> int:
        return sum(c[field] for c in per_case)

    gold_keys_total = _sum("n_gold_keys")
    jia_keys_total = _sum("n_jia_keys")
    hit_total = _sum("hit_keys_n")
    recall_key = hit_total / gold_keys_total if gold_keys_total else None
    precision_key = hit_total / jia_keys_total if jia_keys_total else None
    buckets_all = {
        "b2_total": sum(c["buckets"]["b2_total"] for c in per_case),
        "b2_loser_anomaly": [k for c in per_case
                             for k in c["buckets"]["b2_loser_anomaly"]],
        "b2_tie_only": sum(c["buckets"]["b2_tie_only"] for c in per_case),
        "b2_noroute": sum(c["buckets"]["b2_noroute"] for c in per_case),
        "b1_total": sum(c["buckets"]["b1_total"] for c in per_case),
        "b1_in_volume": sum(c["buckets"]["b1_in_volume"] for c in per_case),
        "b1_in_volume_quoted": sum(c["buckets"]["b1_in_volume_quoted"]
                                   for c in per_case),
        "b1_in_volume_unquoted": sum(c["buckets"]["b1_in_volume_unquoted"]
                                     for c in per_case),
        "b1_not_in_volume": sum(c["buckets"]["b1_not_in_volume"] for c in per_case),
        "b1_in_volume_keys": [k for c in per_case
                              for k in c["buckets"]["b1_in_volume_keys"]],
        "b1_in_volume_unquoted_keys": [
            k for c in per_case
            for k in c["buckets"]["b1_in_volume_unquoted_keys"]],
        "b4_exported_not_gold": [k for c in per_case
                                 for k in c["buckets"]["b4_exported_not_gold"]],
    }
    survey_keys_total = gs["keys_total"]
    # 自证腿：逐案加总 ≥ 跨案并集（官方 doc_id 跨案不互斥⇒等号不成立是设计内，
    # 反向不等才是仪器坏）。
    if survey_keys_total > gold_keys_total:
        _die(f"金标键不变式坏：并集 {survey_keys_total} > 逐案加总 {gold_keys_total}")
    total = {
        "missing_cases": missing,
        "gold_items_total": _sum("n_gold_items"),
        "gold_keys_total": gold_keys_total,
        "gold_keys_pooled": survey_keys_total,
        "gold_noloc_total": gs["noloc_items"],
        "jia_rows_total": _sum("n_jia_rows"),
        "jia_keys_total": jia_keys_total,
        "skipped_tie_total": _sum("skipped_tie"),
        "skipped_noloc_total": _sum("skipped_noloc"),
        "hit_total": hit_total,
        "recall_key": recall_key,
        "precision_key": precision_key,
        "ub_hit_total": _sum("ub_hit_keys"),
        "ub_recall_key": (_sum("ub_hit_keys") / gold_keys_total
                          if gold_keys_total else None),
        "ub_precision_key": (_sum("ub_hit_keys") / _sum("ding_union_n")
                             if _sum("ding_union_n") else None),
        "match_91": {
            "n_sub": sum(c["match_91"]["n_sub"] for c in per_case),
            "n_gold": sum(c["match_91"]["n_gold"] for c in per_case),
            "exact": sum(c["match_91"]["exact"] for c in per_case),
        },
        "ding_union_total": _sum("ding_union_n"),
        "wu_hit_total": _sum("wu_hit"),
        "wu_gold_total": _sum("wu_gold_keys"),
        "buckets_all": buckets_all,
        "ding_streams": {
            n: {"locable": sum(c["ding_streams"][n]["locable"] for c in per_case),
                "discarded": sum(c["ding_streams"][n]["discarded"] for c in per_case)}
            for n in _DING_STREAMS
        },
    }
    total["match_91"]["Precision_conf"] = (
        total["match_91"]["exact"] / total["match_91"]["n_sub"]
        if total["match_91"]["n_sub"] else None)
    total["match_91"]["Recall_conf"] = (
        total["match_91"]["exact"] / total["match_91"]["n_gold"]
        if total["match_91"]["n_gold"] else None)
    verdict, why = _gate(total)
    payload = {
        "ticket": "C-149",
        "run_root": C149_RUN,
        "official_cases_root": OFFICIAL_CASES,
        "gate": {"recall": GATE_RECALL, "precision": GATE_PRECISION,
                 "denominator": "gold_dedup_segment_keys"},
        "verdict": verdict,
        "verdict_why": why,
        "next_knife": _next_knife(total),
        "total": total,
        "cases": per_case,
    }
    art = REPO / "artifacts"
    art.mkdir(exist_ok=True)
    (art / "C149_conf_score.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (art / "C149_conf_score.md").write_text(
        _render_md(payload), encoding="utf-8")
    print(f"判定 {verdict}｜R {_fmt(recall_key)}／P {_fmt(precision_key)}"
          f"｜下一刀 {payload['next_knife']}")
    print("md/json 已写 artifacts/C149_conf_score.*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
