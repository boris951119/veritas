# -*- coding: utf-8 -*-
"""C-156 件①：现 tip 交卷 confidence.json 的档分布＋字段在场＋复算可跟性（零模型、零网络、只读）。

口径（跑前写死，别在看完读数之后改）：
- 三个面分开数，别混：①逐案 confidence.json 自己的绝对档 band；②同案的 band_rel（案内 pooled
  34/67 切点，见 app/export/official.py 的 C-20 段）；③跨案 pooled 重算的两种档。
- 「评委按式能算出同分」＝只拿 substitution 里印出来的那几个数（四位）手算加权和，再按
  gates 披露走封顶，看能不能落在报告 score 的 ±1e-4／±5e-4 里。这里刻意**不**用 aggregate_raw
  （评委看不到未取整值才算真可跟），未取整值只作第二腿对照。
- 缺字段＝该键在任意一行缺席或为 null（null 与缺失分开计，语义不同：chain=null 是「无从判定」
  这一既有档，不是导出漏键）。
- 本产物只含分数数值、计数与 sha 前缀；不含任何官方语料正文、不含结论文本。
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

KEYS_TOP = [
    "question_id", "conclusion_id", "信源可信度", "证据数量与一致性",
    "推理链完整性", "formula", "terms", "substitution", "score",
    "dossier_confidence", "band", "band_rule", "band_rel", "band_rel_rule",
]
KEYS_TERMS = [
    "strength", "coverage", "agreement", "agreement_factor", "chain",
    "chain_factor", "chain_for_aggregate", "aggregate_raw", "gates",
]
BANDS = ["高", "中", "低", "不可分"]


def dist(values: list[str]) -> dict[str, int]:
    out = {b: 0 for b in BANDS}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return {k: n for k, n in out.items() if k in out and (n or k in BANDS)}


def band_abs(score: float, hi: float = 0.8, mid: float = 0.5) -> str:
    if score >= hi:
        return "高"
    if score >= mid:
        return "中"
    return "低"


def rel_cuts(xs: list[float]) -> tuple[float, float] | None:
    if len(xs) < 2:
        return None
    q = statistics.quantiles(xs, n=100, method="inclusive")
    return q[33], q[66]


def band_rel(xs: list[float], s: float) -> str:
    if s <= 0.0:
        return "低"
    cuts = rel_cuts(xs)
    if cuts is None:
        return "低"
    lo, hi = cuts
    if hi - lo < 1e-9:
        if s > hi + 1e-9:
            return "高"
        if s < lo - 1e-9:
            return "低"
        return "不可分"
    if s >= hi:
        return "高"
    if s >= lo:
        return "中"
    return "低"


def parse_substitution(line: str) -> dict | None:
    """从 substitution 里把印出来的四个代入数抠出来（评委就是照这行手算的）。"""
    try:
        body = line.split("clip01(", 1)[1].split(")", 1)[0]
        # body = 0.10 + 0.25*0.3501 + 0.20*0.5 + 0.15*0.75 + 0.30*0.5625
        parts = [p.strip() for p in body.split("+")]
        base = float(parts[0])
        coefs, vals = [], []
        for p in parts[1:]:
            c, v = p.split("*")
            coefs.append(float(c))
            vals.append(float(v))
        tail = line.split("=", 1)[1].strip()
        reported = float(tail)
        gates_note = "none"
        if "gates[" in line:
            gates_note = line.split("gates[", 1)[1].split("]", 1)[0]
        return {"base": base, "coefs": coefs, "vals": vals, "reported": reported,
                "gates_note": gates_note}
    except Exception:  # noqa: BLE001
        return None


def audit_case(conf_path: Path) -> dict:
    rows = json.loads(conf_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        return {"case": conf_path.parent.name, "n_rows": 0, "shape_bad": True}
    scores = [float(r.get("score") or 0.0) for r in rows]
    abs_bands = [str(r.get("band") or "") for r in rows]
    rel_bands = [str(r.get("band_rel") or "") for r in rows]
    miss_keys: dict[str, int] = {}
    for k in KEYS_TOP:
        n = sum(1 for r in rows if k not in r)
        if n:
            miss_keys[k] = n
    null_keys: dict[str, int] = {}
    for k in KEYS_TOP:
        n = sum(1 for r in rows if k in r and r[k] is None)
        if n:
            null_keys[k] = n
    terms = [r.get("terms") if isinstance(r.get("terms"), dict) else {} for r in rows]
    terms_miss = {}
    for k in KEYS_TERMS:
        n = sum(1 for t in terms if k not in t)
        if n:
            terms_miss[k] = n
    terms_null = {}
    for k in KEYS_TERMS:
        n = sum(1 for t in terms if k in t and t[k] is None)
        if n:
            terms_null[k] = n
    gates_present = sum(1 for t in terms if isinstance(t.get("gates"), dict))
    gates_fired = sum(
        1 for t in terms
        if isinstance(t.get("gates"), dict)
        and any(isinstance(v, dict) and v.get("fired") for v in t["gates"].values())
    )
    # 复算可跟性（只吃 substitution 印出来的数）
    diff_1e4 = diff_5e4 = unparsable = 0
    worst = 0.0
    for r in rows:
        got = parse_substitution(str(r.get("substitution") or ""))
        if not got:
            unparsable += 1
            continue
        raw = got["base"] + sum(c * v for c, v in zip(got["coefs"], got["vals"]))
        raw = min(1.0, max(0.0, raw))
        calc = raw
        note = got["gates_note"]
        if note and note != "none":
            if "G2" in note:
                calc = 0.0
            if "G1" in note:
                calc = min(calc, 0.40)
            if "G3" in note:
                calc = min(calc, 0.45)
        d = abs(round(calc, 4) - got["reported"])
        worst = max(worst, d)
        if d <= 1e-4:
            diff_1e4 += 1
        if d <= 5e-4:
            diff_5e4 += 1
    # 跨档一致率（档与「强度」吻合的机械侧代理＝档对 aggregate_raw 单调，不该有档倒挂）
    inversions = 0
    paired = sorted(zip(scores, abs_bands), key=lambda x: x[0])
    rank = {"低": 0, "中": 1, "高": 2}
    prev = -1
    for s, b in paired:
        cur = rank.get(b, 0)
        if cur < prev:
            inversions += 1
        prev = max(prev, cur)
    return {
        "case": conf_path.parent.name,
        "n_rows": len(rows),
        "score_min": round(min(scores), 4) if scores else None,
        "score_max": round(max(scores), 4) if scores else None,
        "score_median": round(statistics.median(scores), 4) if scores else None,
        "band_abs": dist(abs_bands),
        "band_rel": dist(rel_bands),
        "top_key_missing": miss_keys,
        "top_key_null": null_keys,
        "terms_key_missing": terms_miss,
        "terms_key_null": terms_null,
        "gates_dict_rows": gates_present,
        "gates_fired_rows": gates_fired,
        "sub_reproducible_1e-4": diff_1e4,
        "sub_reproducible_5e-4": diff_5e4,
        "sub_unparsable": unparsable,
        "sub_worst_abs_diff": round(worst, 6),
        "band_abs_inversions": inversions,
        "dossier_vs_row_score_mismatch": sum(
            1 for r in rows
            if abs(float(r.get("dossier_confidence") or 0.0) - float(r.get("score") or 0.0)) > 1e-9
        ),
    }


def main() -> int:
    roots = [Path(a) for a in sys.argv[1:]] or [
        Path("/tmp/s4runs/time-20261104-135401"),
        Path("/tmp/c153runs/time-20261104-221631"),
    ]
    out_md = Path("artifacts/C156_baseline.md")
    out_json = Path("artifacts/C156_baseline.json")
    cases: list[dict] = []
    all_scores: list[float] = []
    for root in roots:
        if not root.is_dir():
            continue
        for cf in sorted(root.glob("*/confidence.json")):
            one = audit_case(cf)
            one["root"] = str(root)
            cases.append(one)
            if not one.get("shape_bad"):
                rows = json.loads(cf.read_text(encoding="utf-8"))
                all_scores.extend(float(r.get("score") or 0.0) for r in rows)
    pooled_abs = dist([band_abs(s) for s in all_scores])
    pooled_rel = dist([band_rel(all_scores, s) for s in all_scores])
    cuts = rel_cuts(all_scores)
    summary = {
        "n_cases": len(cases),
        "n_rows": sum(c["n_rows"] for c in cases),
        "pooled_score_min": round(min(all_scores), 4) if all_scores else None,
        "pooled_score_max": round(max(all_scores), 4) if all_scores else None,
        "pooled_score_median": round(statistics.median(all_scores), 4) if all_scores else None,
        "pooled_quantiles_p25_p50_p75_p90": [
            round(statistics.quantiles(all_scores, n=100, method="inclusive")[i], 4)
            for i in (24, 49, 74, 89)
        ] if len(all_scores) >= 2 else None,
        "pooled_band_abs": pooled_abs,
        "pooled_band_rel": pooled_rel,
        "pooled_rel_cuts": None if cuts is None else [round(cuts[0], 4), round(cuts[1], 4)],
        "rows_ge_080": sum(1 for s in all_scores if s >= 0.80),
        "rows_ge_060": sum(1 for s in all_scores if 0.60 <= s < 0.80),
        "rows_ge_050": sum(1 for s in all_scores if 0.50 <= s < 0.60),
        "rows_lt_050": sum(1 for s in all_scores if s < 0.50),
        "rows_zero": sum(1 for s in all_scores if s <= 0.0),
        "sub_reproducible_1e-4_total": sum(c["sub_reproducible_1e-4"] for c in cases),
        "sub_unparsable_total": sum(c["sub_unparsable"] for c in cases),
        "gates_fired_rows_total": sum(c["gates_fired_rows"] for c in cases),
        "band_abs_inversions_total": sum(c["band_abs_inversions"] for c in cases),
    }
    payload = {"roots": [str(r) for r in roots], "summary": summary, "cases": cases}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    L = ["# C-156 件①｜现 tip 交卷 confidence.json 基线（档分布＋字段在场＋复算可跟性）", ""]
    L += [f"跑次根＝{'、'.join(str(r) for r in roots)}｜案 {summary['n_cases']} 份｜行 {summary['n_rows']} 条（全部现读，零模型）", ""]
    L += ["## 合式（app/core/confidence.py 现读，未改）", ""]
    L += [
        "- raw = clip01(b 0.10 + s 0.25·strength + c 0.20·coverage + a 0.15·agreement_factor + h 0.30·chain_score)；",
        "- 硬门：G1 引文命中率<0.6 ⇒ 封顶 0.40；G2 n_evidence≤0 ⇒ 归零；G3 premise_broken 非空 ⇒ 封顶 0.45；",
        "- 绝对档：≥0.8 高／≥0.5 中／否则低（0.8＝官方达标行原文、0.5＝我方设定）；band_rel＝同面 pooled 的 34／67 切点。",
    ]
    L += ["", "## 档分布（pooled 全量）", ""]
    L += [f"- 绝对档＝{json.dumps(pooled_abs, ensure_ascii=False)}｜分位档＝{json.dumps(pooled_rel, ensure_ascii=False)}（切点 lo={summary['pooled_rel_cuts'][0] if summary['pooled_rel_cuts'] else None} hi={summary['pooled_rel_cuts'][1] if summary['pooled_rel_cuts'] else None}）",
          f"- score 数值面：min={summary['pooled_score_min']} 中位={summary['pooled_score_median']} max={summary['pooled_score_max']}；四分位 P25/P50/P75/P90＝{summary['pooled_quantiles_p25_p50_p75_p90']}",
          f"- 分段条数：≥0.80＝{summary['rows_ge_080']}｜0.60–0.79＝{summary['rows_ge_060']}｜0.50–0.59＝{summary['rows_ge_050']}｜<0.50＝{summary['rows_lt_050']}｜0 分＝{summary['rows_zero']}"]
    L += ["", "## 逐案（绝对档／分位档／行）", ""]
    for c in cases:
        L += [f"- {c['root'].rsplit('/', 1)[-1]}｜{c['case']}：{c['n_rows']} 行｜绝对档 {json.dumps(c['band_abs'], ensure_ascii=False)}｜分位档 {json.dumps(c['band_rel'], ensure_ascii=False)}｜score min/med/max {c['score_min']}/{c['score_median']}/{c['score_max']}"]
    L += ["", "## 三条缺口（改前只量出来的洞）", ""]
    n_re = summary["sub_reproducible_1e-4_total"]
    L += [
        f"- 复算可跟性：照 substitution 印出来的四位数手算加权和＋按 gates 封顶，落在报告 score ±1e-4 的行＝{n_re}/{summary['n_rows']}（不可解析行＝{summary['sub_unparsable_total']}）；逐案最差绝对差＝{max((c['sub_worst_abs_diff'] for c in cases), default=None)}。",
        f"- 顶键／分项键在场：缺键行合计＝{sum(sum(c['top_key_missing'].values()) for c in cases)}（键级缺失面见 json 件）；terms 缺键合计＝{sum(sum(c['terms_key_missing'].values()) for c in cases)}；terms.gates 为 dict 的行＝{sum(c['gates_dict_rows'] for c in cases)}/{summary['n_rows']}、其中至少触发一道的＝{summary['gates_fired_rows_total']}。",
        f"- 档与强度吻合：绝对档单调性倒挂行数合计＝{summary['band_abs_inversions_total']}（0＝档随 score 单调，问题不在排序而在分布）；dossier_confidence 与本行 score 不一致的行数合计＝{sum(c['dossier_vs_row_score_mismatch'] for c in cases)}。",
    ]
    L += ["", "## 卫生与红线", ""]
    L += [
        "- 零 LLM、零网络、只读现跑次；app/ 未动（本件只出基线）。",
        "- 产物不含官方语料正文与结论文本：只有 score 数值、计数、档名与键名。",
    ]
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"产物：{out_md} / {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
