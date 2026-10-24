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
    def leak_by_layer(self) -> dict[str, float]:
        return {
            "L1": 1.0 - self.l1.rate,
            "L2": 1.0 - self.l2.rate,
            "L3": 1.0 - self.l3.rate,
            "L4": 1.0 - self.l4.rate,
        }

    @property
    def main_leak(self) -> str:
        leaks = self.leak_by_layer
        ranked = sorted(leaks.items(), key=lambda kv: -kv[1])
        if len(ranked) >= 2 and abs(ranked[0][1] - ranked[1][1]) < 0.03:
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
    ranked = sorted(leaks.items(), key=lambda kv: -kv[1])
    if len(ranked) >= 2 and abs(ranked[0][1] - ranked[1][1]) < 0.03:
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
    print(f"  主漏层={agg['main_leak']}  leaks={agg['leaks']}")
    print(f"  四桶连乘={agg['product']:.4f}  "
          f"vs L4={t['l4']['rate']:.4f}  "
          f"Δ={agg['product_vs_l4_delta']:.4f}")
    if agg["product_vs_l4_delta"] > 0.02:
        print("  解释：四桶均对同一金标分母取绝对到达率，连乘 ≠ 漏斗条件概率积；"
              "L4 直接对分母才是总到达率。Δ>0.02 属口径必然，非计算错误。")
    gap = agg["gap_to_0_97"]
    print(f"  离 0.97 差 {gap*100:.2f} 个百分点；"
          f"主漏在 {agg['main_leak']}；下一张票只准朝该层开刀"
          if agg["main_leak"] != "分不开"
          else f"  离 0.97 差 {gap*100:.2f} 个百分点；最大两桶差<0.03⇒分不开，不许硬指一层")
    print(f"  skipped_no_locator 合计={agg['skipped_no_locator_total']}")


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
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_human(run_dir, results, agg)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("必须显式传 --run-dir <跑次目录>（#68：禁止默认扫盘）",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main())
