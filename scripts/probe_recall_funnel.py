# -*- coding: utf-8 -*-
"""C-51：证据／结论链路四层召回漏桶探针——只读、零 LLM。

分母唯一＝官方金标 supporting_facts 段落全集（经同案 evidence_samples
把 fact_id → para_id；按 doc_id＋para_id 去重）。定位不上记
skipped_no_locator，不进分母、不做近似匹配。

四桶（均对同一分母）：
  L1 案卷到达     ＝金标段落 id 落在 report.json dossier.sources[*].segments
  L2 提示词到达   ＝落在 material_pack_selected
                   ⚠ 现场两批 report.accounting 被 pipeline 白名单剥掉该键
                   （app/pipeline.py kept 集合不含 material_pack_selected）；
                   本探针用 pack_material(Dossier.from_dict(report)) 按同份
                   pack_window.budget 确定性复算，并与 chain.jsonl 的
                   material_pack.n_selected 交叉印证。
  L3 被主张引用   ＝任一证据 quote 逐字命中金标 quote，或 segment_ids 命中
                   金标 para_id（两法都计；汇总取并）
  L4 提交面可见   ＝出现在用 app.export.official.export_official 从同一份
                   report 现导到临时目录的 conclusions.json.supporting_facts
                   （零模型、不入仓）

用法：
    PYTHONPATH=. .venv/bin/python scripts/probe_recall_funnel.py \\
        --run-dir /tmp/s4runs/time-20261024-001335
    PYTHONPATH=. .venv/bin/python scripts/probe_recall_funnel.py --help
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material, set_material_budget  # noqa: E402
from app.export.official import export_official  # noqa: E402

DEFAULT_GOLD = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"


@dataclass
class Bucket:
    numer: int
    denom: int

    @property
    def rate(self) -> float:
        return (self.numer / self.denom) if self.denom else 0.0

    def as_pair(self) -> str:
        return f"{self.numer}/{self.denom}"


@dataclass
class QuestionResult:
    case: str
    qid: str
    denom: int
    skipped_no_locator: int
    l1: Bucket
    l2: Bucket
    l3: Bucket
    l3_para: Bucket
    l3_quote: Bucket
    l4: Bucket
    pack_n_selected: int
    pack_n_selected_chain: int | None
    l4_mode: str
    notes: list[str] = field(default_factory=list)

    @property
    def product(self) -> float:
        return self.l1.rate * self.l2.rate * self.l3.rate * self.l4.rate

    @property
    def product_delta(self) -> float:
        return abs(self.product - self.l4.rate)

    @property
    def stage_losses(self) -> dict[str, int]:
        """逐级损失（条）＝上一桶分子 − 下一桶分子。R-C51-1 主攻层口径。"""
        return {
            "L1->L2": self.l1.numer - self.l2.numer,
            "L2->L3": self.l2.numer - self.l3.numer,
            "L3->L4": self.l3.numer - self.l4.numer,
        }

    @property
    def leak_by_layer(self) -> dict[str, float]:
        """保留：绝对未到达率（1−rate）；主攻层改看 stage_losses。"""
        return {
            "L1": 1.0 - self.l1.rate,
            "L2": 1.0 - self.l2.rate,
            "L3": 1.0 - self.l3.rate,
            "L4": 1.0 - self.l4.rate,
        }

    @property
    def main_leak(self) -> str:
        """主攻层＝逐级损失 argmax；与次大差 <15 条 ⇒「分不开」。"""
        losses = self.stage_losses
        ranked = sorted(losses.items(), key=lambda kv: -kv[1])
        if len(ranked) >= 2 and (ranked[0][1] - ranked[1][1]) < 15:
            return "分不开"
        return ranked[0][0]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="召回漏桶四层探针：L1 案卷／L2 装箱／L3 引用／L4 提交面（零 LLM、只读）",
    )
    p.add_argument(
        "--run-dir",
        dest="run_dir",
        metavar="DIR",
        required=True,
        help="跑次目录（含 <案名>/questions/<qid>/report.json）",
    )
    p.add_argument(
        "--gold-dir",
        dest="gold_dir",
        metavar="DIR",
        default=str(DEFAULT_GOLD),
        help="官方样例集根目录（默认 ~/Desktop/veritas-testcases/样例集-拓尔思-20261012）",
    )
    p.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="以 JSON 输出（便于复放比对）",
    )
    p.add_argument(
        "--compare-dir",
        dest="compare_dir",
        metavar="DIR",
        default=None,
        help="C-54 读数出口：再量一批并与 --run-dir 四桶／逐案／结论数并列",
    )
    return p.parse_args(argv)


def gold_paras_for_question(
    case_dir: Path, qid: str,
) -> tuple[dict[tuple[str, str], set[str]], int]:
    """返回 ({(doc_id, para_id): {quotes...}}, skipped_no_locator)。

    supporting_facts 本身无 para_id；经同案 evidence_samples 用 fact_id 联接。
    """
    cj = case_dir / "conclusions.json"
    es = case_dir / "evidence_samples.json"
    if not cj.is_file():
        return {}, 0
    conclusions = json.loads(cj.read_text(encoding="utf-8"))
    samples = {}
    if es.is_file():
        for row in json.loads(es.read_text(encoding="utf-8")):
            fid = str(row.get("fact_id") or "")
            if fid:
                samples[fid] = row
    out: dict[tuple[str, str], set[str]] = {}
    skipped = 0
    for row in conclusions:
        if str(row.get("question_id") or "") != qid:
            continue
        for sf in row.get("supporting_facts") or []:
            fid = str(sf.get("fact_id") or "")
            sample = samples.get(fid)
            para = str((sample or {}).get("para_id") or "")
            doc = str((sample or {}).get("doc_id") or sf.get("doc_id") or "")
            if not para or not doc:
                skipped += 1
                continue
            key = (doc, para)
            out.setdefault(key, set()).add(str(sf.get("quote") or ""))
    return out, skipped


def dossier_segment_ids(dossier: Dossier) -> set[str]:
    ids: set[str] = set()
    for src in dossier.sources:
        for seg in src.segments:
            if seg.id:
                ids.add(str(seg.id))
            loc = getattr(seg, "locator", None)
            if loc:
                ids.add(str(loc))
    return ids


def reconstruct_pack_selected(dossier: Dossier) -> tuple[set[str], int]:
    """§3.4：accounting 无 material_pack_selected 时，按 pack_window.budget 复算。"""
    pw = (dossier.accounting or {}).get("pack_window") or {}
    budget = int(pw.get("budget") or 0) or None
    if budget:
        set_material_budget(budget)
    pack = pack_material(dossier)
    selected = {str(x) for x in (pack.get("selected") or [])}
    return selected, len(selected)


def chain_pack_n_selected(report_path: Path) -> int | None:
    chain = report_path.parent / "chain.jsonl"
    if not chain.is_file():
        return None
    for line in chain.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "material_pack":
            payload = obj.get("payload") or {}
            n = payload.get("n_selected")
            return int(n) if n is not None else None
    return None


def cited_hits(
    gold: dict[tuple[str, str], set[str]], dossier: Dossier,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
    """返回 (para_id 命中集, quote 逐字命中集, 并集)。"""
    ev_segs: set[str] = set()
    ev_quotes: set[str] = set()
    for ev in dossier.evidences:
        for sid in ev.segment_ids or []:
            ev_segs.add(str(sid))
        q = str(ev.quote or "")
        if q:
            ev_quotes.add(q)
    hit_para: set[tuple[str, str]] = set()
    hit_quote: set[tuple[str, str]] = set()
    for key, quotes in gold.items():
        _doc, para = key
        if para in ev_segs:
            hit_para.add(key)
        if any(q and q in ev_quotes for q in quotes):
            hit_quote.add(key)
    return hit_para, hit_quote, hit_para | hit_quote


def export_supporting_locs(
    dossier: Dossier, qid: str, question: str, tmp_parent: Path,
) -> set[tuple[str, str]]:
    """L4：现导 export_official → supporting_facts 的 (doc_id, para_id) 集。"""
    out_dir = tmp_parent / f"l4-{qid}"
    export_official(
        [({"question_id": qid, "question": question}, dossier)],
        out_dir,
    )
    path = out_dir / "conclusions.json"
    if not path.is_file():
        return set()
    rows = json.loads(path.read_text(encoding="utf-8"))
    locs: set[tuple[str, str]] = set()
    for row in rows:
        for sf in row.get("supporting_facts") or []:
            doc = str(sf.get("doc_id") or "")
            para = str(sf.get("para_id") or "")
            if doc and para:
                locs.add((doc, para))
    return locs


def measure_question(
    report_path: Path,
    case_dir: Path,
    *,
    l4_tmp: Path,
    # 测试夹具可注入覆盖集，便于反向腿
    override_dossier_ids: set[str] | None = None,
    override_pack: set[str] | None = None,
    override_cited: set[tuple[str, str]] | None = None,
    override_exported: set[tuple[str, str]] | None = None,
    gold_override: dict[tuple[str, str], set[str]] | None = None,
) -> QuestionResult:
    case = report_path.parts[-4]
    qid = report_path.parts[-2]
    rep = json.loads(report_path.read_text(encoding="utf-8"))
    dossier = Dossier.from_dict(rep)

    if gold_override is not None:
        gold, skipped = gold_override, 0
    else:
        gold, skipped = gold_paras_for_question(case_dir, qid)
    denom = len(gold)

    dossier_ids = override_dossier_ids if override_dossier_ids is not None \
        else dossier_segment_ids(dossier)
    if override_pack is not None:
        pack_sel, pack_n = override_pack, len(override_pack)
    else:
        pack_sel, pack_n = reconstruct_pack_selected(dossier)
    chain_n = chain_pack_n_selected(report_path)

    if override_cited is not None:
        hit_para = hit_quote = hit_either = override_cited
        l3_para_n = l3_quote_n = len(override_cited)
    else:
        hit_para, hit_quote, hit_either = cited_hits(gold, dossier)
        l3_para_n = sum(1 for k in gold if k in hit_para)
        l3_quote_n = sum(1 for k in gold if k in hit_quote)

    if override_exported is not None:
        exported = override_exported
    else:
        # export_official 会 print；静默一下
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            exported = export_supporting_locs(
                dossier, qid, str(rep.get("question") or dossier.question),
                l4_tmp,
            )

    def _count(pred_set: set, key_attr: str = "para") -> int:
        if key_attr == "para":
            return sum(1 for _doc, para in gold if para in pred_set)
        return sum(1 for k in gold if k in pred_set)

    l1_n = _count(dossier_ids, "para")
    l2_n = _count(pack_sel, "para")
    l3_n = sum(1 for k in gold if k in hit_either)
    l4_n = sum(1 for k in gold if k in exported)

    notes: list[str] = []
    acc = rep.get("accounting") or {}
    if "material_pack_selected" not in acc:
        notes.append(
            "§3.4 L2：report.accounting 无 material_pack_selected"
            "（pipeline kept 白名单剥掉）；已用 pack_material 按 pack_window.budget 复算"
        )
    if chain_n is not None and chain_n != pack_n:
        notes.append(
            f"§3.4 L2 交叉：chain.n_selected={chain_n} ≠ 复算 {pack_n}"
        )

    return QuestionResult(
        case=case,
        qid=qid,
        denom=denom,
        skipped_no_locator=skipped,
        l1=Bucket(l1_n, denom),
        l2=Bucket(l2_n, denom),
        l3=Bucket(l3_n, denom),
        l3_para=Bucket(l3_para_n, denom),
        l3_quote=Bucket(l3_quote_n, denom),
        l4=Bucket(l4_n, denom),
        pack_n_selected=pack_n,
        pack_n_selected_chain=chain_n,
        l4_mode="export_official→/tmp",
        notes=notes,
    )


def discover_reports(run_dir: Path) -> list[Path]:
    return sorted(run_dir.rglob("questions/*/report.json"))


def measure_run(
    run_dir: Path, gold_dir: Path, *, l4_tmp: Path,
) -> list[QuestionResult]:
    results: list[QuestionResult] = []
    for rp in discover_reports(run_dir):
        case = rp.parts[-4]
        case_dir = gold_dir / case
        results.append(measure_question(rp, case_dir, l4_tmp=l4_tmp))
    return results


def aggregate(results: list[QuestionResult]) -> dict:
    def _sum(attr: str) -> tuple[int, int]:
        num = sum(getattr(r, attr).numer for r in results)
        den = sum(getattr(r, attr).denom for r in results)
        return num, den

    totals = {}
    for name in ("l1", "l2", "l3", "l4"):
        n, d = _sum(name)
        totals[name] = {"numer": n, "denom": d,
                        "rate": (n / d) if d else 0.0}
    # L3 两法合计
    for name in ("l3_para", "l3_quote"):
        n, d = _sum(name)
        totals[name] = {"numer": n, "denom": d,
                        "rate": (n / d) if d else 0.0}
    leaks = {
        "L1": 1.0 - totals["l1"]["rate"],
        "L2": 1.0 - totals["l2"]["rate"],
        "L3": 1.0 - totals["l3"]["rate"],
        "L4": 1.0 - totals["l4"]["rate"],
    }
    stage_losses = {
        "L1->L2": totals["l1"]["numer"] - totals["l2"]["numer"],
        "L2->L3": totals["l2"]["numer"] - totals["l3"]["numer"],
        "L3->L4": totals["l3"]["numer"] - totals["l4"]["numer"],
    }
    ranked = sorted(stage_losses.items(), key=lambda kv: -kv[1])
    if len(ranked) >= 2 and (ranked[0][1] - ranked[1][1]) < 15:
        main = "分不开"
    else:
        main = ranked[0][0]
    product = (
        totals["l1"]["rate"] * totals["l2"]["rate"]
        * totals["l3"]["rate"] * totals["l4"]["rate"]
    )
    return {
        "n_questions": len(results),
        "totals": totals,
        "leaks": leaks,
        "stage_losses": stage_losses,
        "main_leak": main,
        "product": product,
        "product_vs_l4_delta": abs(product - totals["l4"]["rate"]),
        "gap_to_0_97": 0.97 - totals["l4"]["rate"],
        "skipped_no_locator_total": sum(r.skipped_no_locator for r in results),
    }


def _fmt_rate(b: Bucket) -> str:
    return f"{b.as_pair()}={b.rate:.4f}"


def print_human(run_dir: Path, results: list[QuestionResult], agg: dict) -> None:
    print(f"=== run-dir={run_dir}  n_questions={agg['n_questions']}  "
          f"L4 路径=export_official→/tmp（零模型、不入仓） ===")
    print(f"{'case':<28}{'qid':<8}"
          f"{'L1':>14}{'L2':>14}{'L3':>14}{'L3p':>10}{'L3q':>10}{'L4':>14}"
          f"{'leak':>8}{'Δprod':>8}{'skip':>5}")
    for r in results:
        print(
            f"{r.case[:26]:<28}{r.qid:<8}"
            f"{_fmt_rate(r.l1):>14}{_fmt_rate(r.l2):>14}"
            f"{_fmt_rate(r.l3):>14}{r.l3_para.as_pair():>10}{r.l3_quote.as_pair():>10}"
            f"{_fmt_rate(r.l4):>14}"
            f"{r.main_leak:>8}{r.product_delta:>8.4f}{r.skipped_no_locator:>5}"
        )
        for note in r.notes:
            print(f"  note: {note}")
        if r.pack_n_selected_chain is not None:
            print(f"  pack_n_selected 复算={r.pack_n_selected} "
                  f"chain={r.pack_n_selected_chain}")
    t = agg["totals"]
    print("--- 全案合计 ---")
    for name in ("l1", "l2", "l3", "l3_para", "l3_quote", "l4"):
        row = t[name]
        print(f"  {name}: {row['numer']}/{row['denom']}={row['rate']:.4f}")
    print(f"  主漏层={agg['main_leak']}  stage_losses={agg['stage_losses']}  "
          f"leaks(绝对)={agg['leaks']}")
    print(f"  四桶连乘={agg['product']:.4f}  "
          f"vs L4={t['l4']['rate']:.4f}  "
          f"Δ={agg['product_vs_l4_delta']:.4f}")
    if agg["product_vs_l4_delta"] > 0.02:
        print("  解释：四桶均对同一金标分母取绝对到达率，连乘 ≠ 漏斗条件概率积；"
              "L4 直接对分母才是总到达率。Δ>0.02 属口径必然，非计算错误。")
    gap = agg["gap_to_0_97"]
    main = agg["main_leak"]
    if main == "分不开":
        print(f"  离 0.97 差 {gap*100:.2f} 个百分点；"
              f"逐级损失最大两级差<15条⇒分不开，不许硬指一层")
    else:
        print(f"  离 0.97 差 {gap*100:.2f} 个百分点；"
              f"主漏在 {main}；下一张票只准朝该层开刀")
    print(f"  skipped_no_locator 合计={agg['skipped_no_locator_total']}")


def _conclusion_stats(run_dir: Path) -> dict:
    """C-54 读数出口：结论数＋提交面高档（confidence≥0.8）条数。"""
    n_conc = 0
    n_high = 0
    for case_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        if "吉隆" in case_dir.name:
            continue
        qroot = case_dir / "questions"
        if not qroot.is_dir():
            continue
        for qdir in sorted(qroot.glob("q_*")):
            rp = qdir / "report.json"
            if not rp.exists():
                continue
            rep = json.loads(rp.read_text(encoding="utf-8"))
            for c in rep.get("conclusions") or []:
                if not isinstance(c, dict):
                    continue
                n_conc += 1
                conf = c.get("confidence")
                score = None
                if isinstance(conf, (int, float)):
                    score = float(conf)
                elif isinstance(conf, dict):
                    score = float(conf.get("score") or conf.get("value") or 0)
                if score is not None and score >= 0.8:
                    n_high += 1
    return {"n_conclusions": n_conc, "n_high_band": n_high}


def _print_c54_compare(
    label_a: str, run_a: Path, res_a: list, agg_a: dict,
    label_b: str, run_b: Path, res_b: list, agg_b: dict,
) -> None:
    """两批四桶并列＋逐案拆开＋结论数／高档同表（C-54 判据 c）。"""
    print("\n=== C-54 两批四桶并列 ===")
    ta, tb = agg_a["totals"], agg_b["totals"]
    print(f"{'bucket':<8}{label_a:>16}{label_b:>16}")
    for name in ("l1", "l2", "l3", "l4"):
        a, b = ta[name], tb[name]
        print(f"{name:<8}{a['numer']:>4}/{a['denom']:<4}"
              f"={a['rate']:.4f}  {b['numer']:>4}/{b['denom']:<4}"
              f"={b['rate']:.4f}")
    sa, sb = _conclusion_stats(run_a), _conclusion_stats(run_b)
    print(f"结论数   {sa['n_conclusions']:>16}{sb['n_conclusions']:>16}")
    print(f"高档≥0.8 {sa['n_high_band']:>16}{sb['n_high_band']:>16}")
    print("\n=== C-54 逐案 L2 拆开 ===")
    by_a: dict[str, list[int]] = {}
    by_b: dict[str, list[int]] = {}
    for r in res_a:
        c = by_a.setdefault(r.case, [0, 0])
        c[0] += r.l2.numer
        c[1] += r.l2.denom
    for r in res_b:
        c = by_b.setdefault(r.case, [0, 0])
        c[0] += r.l2.numer
        c[1] += r.l2.denom
    print(f"{'case':30}{label_a:>12}{label_b:>12}")
    for case in sorted(set(by_a) | set(by_b)):
        a = by_a.get(case, [0, 0])
        b = by_b.get(case, [0, 0])
        print(f"  {case[:28]:28} {a[0]:3}/{a[1]:<3}     {b[0]:3}/{b[1]:<3}")
    # 门槛提示
    l2a, l2b = ta["l2"]["numer"], tb["l2"]["numer"]
    l3a, l3b = ta["l3"]["numer"], tb["l3"]["numer"]
    l4a, l4b = ta["l4"]["numer"], tb["l4"]["numer"]
    print(f"\n判据 c 门槛（相对基线 L2=40 L3=15 L4=7；"
          f"{label_a} 为改后重算）："
          f"L2 {l2a}（须>40） L3 {l3a}（须≥15） L4 {l4a}（须≥7）")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"目录不存在：{run_dir}", file=sys.stderr)
        return 2
    gold_dir = Path(args.gold_dir)
    if not gold_dir.is_dir():
        print(f"找不到官方样例集：{gold_dir}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="c51-l4-") as td:
        results = measure_run(run_dir, gold_dir, l4_tmp=Path(td))
        if not results:
            print(f"未找到 report.json：{run_dir}", file=sys.stderr)
            return 2
        agg = aggregate(results)
        if args.as_json:
            payload = {
                "run_dir": str(run_dir),
                "gold_dir": str(gold_dir),
                "l4_mode": "export_official→/tmp",
                "questions": [
                    {
                        "case": r.case, "qid": r.qid,
                        "denom": r.denom,
                        "skipped_no_locator": r.skipped_no_locator,
                        "l1": {"numer": r.l1.numer, "denom": r.l1.denom},
                        "l2": {"numer": r.l2.numer, "denom": r.l2.denom},
                        "l3": {"numer": r.l3.numer, "denom": r.l3.denom},
                        "l3_para": {"numer": r.l3_para.numer, "denom": r.l3_para.denom},
                        "l3_quote": {"numer": r.l3_quote.numer, "denom": r.l3_quote.denom},
                        "l4": {"numer": r.l4.numer, "denom": r.l4.denom},
                        "main_leak": r.main_leak,
                        "product": r.product,
                        "product_delta": r.product_delta,
                        "pack_n_selected": r.pack_n_selected,
                        "pack_n_selected_chain": r.pack_n_selected_chain,
                        "notes": r.notes,
                    }
                    for r in results
                ],
                "aggregate": agg,
                "conclusion_stats": _conclusion_stats(run_dir),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_human(run_dir, results, agg)
            stats = _conclusion_stats(run_dir)
            print(f"  结论数={stats['n_conclusions']}  "
                  f"高档≥0.8={stats['n_high_band']}")
        if args.compare_dir:
            cmp = Path(args.compare_dir)
            if not cmp.is_dir():
                print(f"compare-dir 不存在：{cmp}", file=sys.stderr)
                return 2
            with tempfile.TemporaryDirectory(prefix="c51-l4b-") as td2:
                res_b = measure_run(cmp, gold_dir, l4_tmp=Path(td2))
                if not res_b:
                    print(f"compare-dir 无 report：{cmp}", file=sys.stderr)
                    return 2
                agg_b = aggregate(res_b)
                if not args.as_json:
                    print_human(cmp, res_b, agg_b)
                    stats_b = _conclusion_stats(cmp)
                    print(f"  结论数={stats_b['n_conclusions']}  "
                          f"高档≥0.8={stats_b['n_high_band']}")
                _print_c54_compare(
                    "NEW改后", run_dir, results, agg,
                    "OLD批2", cmp, res_b, agg_b,
                )
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("必须显式传 --run-dir <跑次目录>（#68：禁止默认扫盘）",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main())
