"""官方客观分下界：只做 2.1 第一阶段精确匹配（doc_id + para_id）。

不含第二阶段语义匹配。结论正确率（2.3，需大模型）不算。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


DISCLAIMER = "仅第一阶段精确匹配＝官方分的下界，未含语义匹配"
# 第二行口径：按金标遍历，双方为空的侧不进平均。
EMPTY_EXCLUDED_NOTE = "未含语义匹配，且双方为空的侧已剔除"


def _load(path: Path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "records" in data:
        return list(data["records"])
    if not isinstance(data, list):
        raise ValueError(f"{path} 须为 JSON 数组")
    return data


def _pairs(rows: list[dict], key: str | None = None) -> list[tuple[str, str]]:
    out = []
    for row in rows:
        if key is not None:
            for item in row.get(key) or []:
                out.append((str(item.get("doc_id") or ""), str(item.get("para_id") or "")))
        else:
            out.append((str(row.get("doc_id") or ""), str(row.get("para_id") or "")))
    return out


def exact_hits(submitted: list[tuple[str, str]],
               gold: list[tuple[str, str]]) -> int:
    """一对一：同一 (doc_id, para_id) 的金标最多被一条提交命中一次。"""
    left = Counter(gold)
    hits = 0
    for key in submitted:
        if left[key] > 0:
            left[key] -= 1
            hits += 1
    return hits


def precision_recall(submitted: list[tuple[str, str]],
                     gold: list[tuple[str, str]]) -> tuple[float, float]:
    hits = exact_hits(submitted, gold)
    # 金标非空而提交为空时，空集不是「全都对」。双方都空由调用方把权重记 0，不在这里记 1。
    precision = 0.0 if not submitted else hits / len(submitted)
    recall = 1.0 if not gold else hits / len(gold)
    return precision, recall


def f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score_f1_src(precision: float, recall: float) -> int:
    """2.2.1。优档还要求 P 与 R 都 ≥ 0.80；F1 已达优但 P/R 不够时落到良。"""
    value = f1(precision, recall)
    if value >= 0.85 and precision >= 0.80 and recall >= 0.80:
        return 7
    if value >= 0.75:
        return 5
    if value >= 0.65:
        return 3
    return 0


def score_recall_sup(recall: float) -> int:
    if recall >= 0.85:
        return 6
    if recall >= 0.70:
        return 4
    if recall >= 0.55:
        return 2
    return 0


def score_precision_sup(precision: float) -> int:
    if precision >= 0.90:
        return 6
    if precision >= 0.80:
        return 4
    if precision >= 0.70:
        return 2
    return 0


def score_recall_conf(recall: float) -> int:
    if recall >= 0.80:
        return 7
    if recall >= 0.65:
        return 5
    if recall >= 0.50:
        return 3
    return 0


def score_precision_conf(precision: float) -> int:
    if precision >= 0.85:
        return 6
    if precision >= 0.70:
        return 4
    if precision >= 0.55:
        return 2
    return 0


def _weighted(per_question: list[tuple[float, int]]) -> float:
    weight = sum(w for _, w in per_question)
    if weight <= 0:
        return 0.0
    return sum(value * w for value, w in per_question) / weight


def _fact_index(rows: list[dict]) -> dict[str, tuple[str, str]]:
    """evidence_samples 的 fact_id → (doc_id, para_id)。同案内 fact_id 唯一。"""
    index: dict[str, tuple[str, str]] = {}
    for row in rows:
        fact_id = row.get("fact_id")
        if fact_id is None or str(fact_id) == "":
            continue
        index[str(fact_id)] = (
            str(row.get("doc_id") or ""),
            str(row.get("para_id") or ""),
        )
    return index


def _gold_fact_pairs(rows: list[dict], key: str,
                     index: dict[str, tuple[str, str]],
                     unresolved: list[str]) -> list[tuple[str, str]]:
    """金标 fact 元素没有 para_id，先按 fact_id 换形成附录 A.3 的 (doc_id, para_id)。

    换不上的留在金标侧（哨兵键，提交侧对不上），并记入 unresolved。不许静默丢掉，
    否则分母变小、召回会被抬高。
    """
    out: list[tuple[str, str]] = []
    for row in rows:
        for item in row.get(key) or []:
            if not isinstance(item, dict):
                unresolved.append("")
                out.append(("__unresolved__", ""))
                continue
            fact_id = item.get("fact_id")
            if fact_id is not None and str(fact_id) != "":
                pair = index.get(str(fact_id))
                if pair and pair[0] and pair[1]:
                    out.append(pair)
                else:
                    unresolved.append(str(fact_id))
                    out.append(("__unresolved__", str(fact_id)))
                continue
            para_id = str(item.get("para_id") or "")
            if para_id:
                out.append((str(item.get("doc_id") or ""), para_id))
            else:
                unresolved.append("")
                out.append(("__unresolved__", ""))
    return out


def score_submission(evidence_path: Path, conclusions_path: Path,
                     gold_evidence_path: Path, gold_conclusions_path: Path,
                     samples_path: Path | None = None,
                     raw_documents_path: Path | None = None) -> dict:
    evidence = _load(evidence_path)
    conclusions = _load(conclusions_path)
    gold_evidence = _load(gold_evidence_path)
    gold_conclusions = _load(gold_conclusions_path)
    # 默认同案 evidence_samples 就是金标证据文件；测试可另给一份只用于换形。
    samples = _load(samples_path) if samples_path is not None else gold_evidence
    index = _fact_index(samples)
    unresolved: list[str] = []

    p_src, r_src = precision_recall(_pairs(evidence), _pairs(gold_evidence))
    f_src = f1(p_src, r_src)

    grouped: dict[str, list[dict]] = {}
    for row in conclusions:
        grouped.setdefault(str(row.get("question_id") or ""), []).append(row)
    gold_ids = {str(row.get("question_id") or "") for row in gold_conclusions}
    repeated_questions = sum(1 for rows in grouped.values() if len(rows) > 1)
    sup_p: list[tuple[float, int]] = []
    sup_r: list[tuple[float, int]] = []
    conf_p: list[tuple[float, int]] = []
    conf_r: list[tuple[float, int]] = []
    empty_both = 0
    gold_empty_submitted = 0
    missing_questions = 0
    bare_supporting = 0
    for gold in gold_conclusions:
        qid = str(gold.get("question_id") or "")
        rows = grouped.get(qid) or []
        if not rows:
            missing_questions += 1
            row: dict = {}
        else:
            # 硬档在合并前逐行判定。整题没交已经按 0 进分母，不再算裸结论。
            for one in rows:
                if not (one.get("supporting_facts") or []):
                    bare_supporting += 1
            # 只有一行时不并集：一行内部的重复段落对要留给一对一消耗，避免改掉已验收的上帝提交读数。
            if len(rows) == 1:
                row = rows[0]
            else:
                row = {
                    "supporting_facts": _union_facts(rows, "supporting_facts"),
                    "conflicting_facts": _union_facts(rows, "conflicting_facts"),
                }
        sub_sup = _pairs([row], "supporting_facts")
        gold_sup = _gold_fact_pairs([gold], "supporting_facts", index, unresolved) if gold else []
        sub_conf = _pairs([row], "conflicting_facts")
        gold_conf = _gold_fact_pairs([gold], "conflicting_facts", index, unresolved) if gold else []
        sp, sr = precision_recall(sub_sup, gold_sup)
        cp, cr = precision_recall(sub_conf, gold_conf)
        empty_both += _empty_both_side(len(gold_sup), len(sub_sup))
        empty_both += _empty_both_side(len(gold_conf), len(sub_conf))
        gold_empty_submitted += _gold_empty_submitted_side(len(gold_sup), len(sub_sup))
        gold_empty_submitted += _gold_empty_submitted_side(len(gold_conf), len(sub_conf))
        # 2.4：rubric:225「先逐条结论计算，再按标准答案规模加权汇总」。
        # :227 与 :249 都写「加权平均」，所以 Precision_sup 与 Recall_sup 的权重都是金标条数。
        # 金标该侧为空则权重 0，不进平均。
        sup_p.append((sp, len(gold_sup)))
        sup_r.append((sr, len(gold_sup)))
        # 2.5：rubric:252 起把 C／C* 定义成全局集合比值，没有加权句。
        # 这里只改成按金标题集遍历；精确率权重仍是提交条数，召回权重仍是金标条数。
        conf_p.append((cp, _precision_weight(len(sub_conf))))
        conf_r.append((cr, _recall_weight(len(gold_conf))))

    p_sup, r_sup = _weighted(sup_p), _weighted(sup_r)
    p_conf, r_conf = _weighted(conf_p), _weighted(conf_r)
    score_241 = score_recall_sup(r_sup)
    if bare_supporting:
        score_241 = 0
    extra_questions = sum(1 for qid in grouped if qid not in gold_ids)
    return {
        "Precision_src": p_src,
        "Recall_src": r_src,
        "F1_src": f_src,
        "score_2_2_1": score_f1_src(p_src, r_src),
        "Precision_sup": p_sup,
        "Recall_sup": r_sup,
        "score_2_4_1": score_241,
        "score_2_4_2": score_precision_sup(p_sup),
        "Precision_conf": p_conf,
        "Recall_conf": r_conf,
        "score_2_5_1": score_recall_conf(r_conf),
        "score_2_5_2": score_precision_conf(p_conf),
        "unresolved_fact_ids": len(unresolved),
        "empty_both_excluded": empty_both,
        "gold_empty_submitted": gold_empty_submitted,
        "missing_questions": missing_questions,
        "bare_supporting": bare_supporting,
        "extra_questions": extra_questions,
        "repeated_questions": repeated_questions,
        "recall_src_ceiling": recall_src_ceiling_line(gold_evidence, raw_documents_path),
    }


def _union_facts(rows: list[dict], key: str) -> list[dict]:
    """同一题多行的事实按 (doc_id, para_id) 取并集，顺序取第一次出现。"""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for row in rows:
        for item in row.get(key) or []:
            if not isinstance(item, dict):
                continue
            pair = (str(item.get("doc_id") or ""), str(item.get("para_id") or ""))
            if pair in seen:
                continue
            seen.add(pair)
            out.append({"doc_id": pair[0], "para_id": pair[1]})
    return out


def _empty_both_side(gold_n: int, submitted_n: int) -> int:
    return 1 if gold_n == 0 and submitted_n == 0 else 0


def _gold_empty_submitted_side(gold_n: int, submitted_n: int) -> int:
    return 1 if gold_n == 0 and submitted_n > 0 else 0


def _precision_weight(submitted_n: int) -> int:
    """2.5 精确率权重＝提交条数。2.4 不用这个函数。"""
    return submitted_n


def _recall_weight(gold_n: int) -> int:
    """金标条数。金标为空则 0，不得记成 1。"""
    return gold_n


def _corpus_para_ids(raw_path: Path) -> set[str]:
    ids: set[str] = set()
    for doc in _load(raw_path):
        for para in doc.get("paragraphs") or []:
            para_id = para.get("para_id")
            if para_id:
                ids.add(str(para_id))
    return ids


def recall_src_ceiling_line(gold_evidence: list[dict],
                            raw_documents_path: Path | None) -> str:
    """本案上限＝(金标条数 − para_id 不在本案语料的条数) / 金标条数。不印跨案合计。"""
    gold_n = len(gold_evidence)
    if raw_documents_path is None:
        return f"本案金标 {gold_n} 条，Recall_src 上限未核（未提供 --raw-documents）"
    if gold_n == 0:
        return "本案金标 0 条，Recall_src 上限未核（金标为空）"
    corpus = _corpus_para_ids(raw_documents_path)
    in_corpus = sum(1 for row in gold_evidence if str(row.get("para_id") or "") in corpus)
    return f"Recall_src 上限 {in_corpus}/{gold_n}＝{in_corpus / gold_n:.1%}"


def format_report(metrics: dict) -> str:
    unresolved = int(metrics.get("unresolved_fact_ids") or 0)
    empty_both = int(metrics.get("empty_both_excluded") or 0)
    gold_empty_submitted = int(metrics.get("gold_empty_submitted") or 0)
    missing = int(metrics.get("missing_questions") or 0)
    extra = int(metrics.get("extra_questions") or 0)
    bare = int(metrics.get("bare_supporting") or 0)
    repeated = int(metrics.get("repeated_questions") or 0)
    lines = [
        DISCLAIMER,
        EMPTY_EXCLUDED_NOTE,
        str(metrics.get("recall_src_ceiling") or ""),
        f"{unresolved} 条金标 fact_id 无法解析",
        f"{empty_both} 侧双方为空，未计入",
        f"{gold_empty_submitted} 侧金标为空但提交了证据（官方 2.4 按金标规模加权，此侧不进平均）",
        f"提交缺 {missing} 道题（按金标遍历，这些题记 0 分）",
        f"提交含 {extra} 道金标里没有的题",
    ]
    if bare:
        lines.append(f"{bare} 条结论提交了但无支撑证据（官方 2.4.1 硬档）")
    if repeated:
        lines.append(f"{repeated} 道题在提交里重复出现（已按并集合并）")
    for key in (
        "Precision_src", "Recall_src", "F1_src", "score_2_2_1",
        "Precision_sup", "Recall_sup", "score_2_4_1", "score_2_4_2",
        "Precision_conf", "Recall_conf", "score_2_5_1", "score_2_5_2",
    ):
        value = metrics[key]
        if isinstance(value, float):
            lines.append(f"{key}={value:.4f}")
        else:
            lines.append(f"{key}={value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="官方客观分下界（仅精确匹配）")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--conclusions", required=True)
    parser.add_argument("--gold-evidence", required=True)
    parser.add_argument("--gold-conclusions", required=True)
    parser.add_argument(
        "--evidence-samples", default=None,
        help="fact_id→para_id 换形表；缺省用 --gold-evidence（官方样例里二者是同一文件）",
    )
    parser.add_argument(
        "--raw-documents", default=None,
        help="本案语料。给出后按本案金标计算 Recall_src 上限；不给则标明未核",
    )
    args = parser.parse_args(argv)
    samples = Path(args.evidence_samples) if args.evidence_samples else None
    raw_documents = Path(args.raw_documents) if args.raw_documents else None
    metrics = score_submission(
        Path(args.evidence), Path(args.conclusions),
        Path(args.gold_evidence), Path(args.gold_conclusions),
        samples_path=samples,
        raw_documents_path=raw_documents,
    )
    print(format_report(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
