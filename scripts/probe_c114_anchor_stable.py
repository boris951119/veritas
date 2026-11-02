#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-114：证据定位稳——重构／转存后再解析开／关对照（零 LLM 主尺）。

主尺：样例集金标 (doc_id, para_id) 在「导出→轻量改包装→再 load」后的一致率；泄漏＝0。
旁证：刘翔@7／holdout L2（装箱面，不因本票掉）。

用法：
  PYTHONPATH=. .venv/bin/python scripts/probe_c114_anchor_stable.py \\
      --out artifacts/C114_anchor_stable.md
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.anchor_stable import (  # noqa: E402
    compare_anchor_maps,
    dossier_anchor_map,
)
from app.core.kg_density_bridge import density_submit_surface  # noqa: E402
from app.core.kg_submit_surface import (  # noqa: E402
    FORBIDDEN_PACK_KEYS,
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)
from app.core.material import pack_material  # noqa: E402
from app.ingest.official_case import load_official_case  # noqa: E402
from scripts.probe_c66_multi_box import l2_hits, selected_locs  # noqa: E402
from scripts.probe_c85_anchor_review import _gold_keys  # noqa: E402
from scripts.probe_recall_funnel import DEFAULT_GOLD  # noqa: E402

CASES = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
C85 = Path("/tmp/c85_k180")
CASE_LX = "刘翔编制“二选一”事件"
QIDS = ("q_001", "q_002", "q_003")
HOLDOUT = (
    ("王虹“北大discouraged”事件", "wanghong"),
    ("柬泰边境争端（2025.12–2026.9）", "kh_th"),
    ("印度航空 AI171 空难（2025.6–2026.5）", "ai171"),
)
SAMPLE_CASES = (
    CASE_LX,
    "王虹“北大discouraged”事件",
    "柬泰边境争端（2025.12–2026.9）",
)


def _gold_para_ids(case_name: str) -> list[str]:
    """金标支撑／冲突 → para_id 列表（经 evidence_samples 补全）。"""
    case_dir = CASES / case_name
    samples = json.loads(
        (case_dir / "evidence_samples.json").read_text(encoding="utf-8")
    )
    by_fact = {
        str(r.get("fact_id") or ""): str(r.get("para_id") or "")
        for r in samples if isinstance(r, dict)
    }
    # 也收 samples 自身的 para_id
    paras: list[str] = []
    seen: set[str] = set()
    for r in samples:
        if not isinstance(r, dict):
            continue
        pid = str(r.get("para_id") or "").strip()
        if pid and pid not in seen:
            seen.add(pid)
            paras.append(pid)
    concl = json.loads((case_dir / "conclusions.json").read_text(encoding="utf-8"))
    for row in concl:
        if not isinstance(row, dict):
            continue
        for side in ("supporting_facts", "conflicting_facts"):
            for f in row.get(side) or []:
                if not isinstance(f, dict):
                    continue
                pid = str(f.get("para_id") or "").strip()
                if not pid:
                    pid = by_fact.get(str(f.get("fact_id") or ""), "")
                if pid and pid not in seen:
                    seen.add(pid)
                    paras.append(pid)
    return paras


def _embed_and_stress(docs: list[dict], *, kind: str) -> list[dict]:
    """模拟导出（嵌入 text）＋轻量转存应力。"""
    out: list[dict] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        content = str(doc.get("content") or "")
        paras_out = []
        for para in doc.get("paragraphs") or []:
            if not isinstance(para, dict) or "para_id" not in para:
                continue
            s = int(para.get("char_start") or 0)
            e = int(para.get("char_end") or 0)
            text = content[s:e]
            p2 = dict(para)
            p2["text"] = text  # 导出带正文指纹
            paras_out.append(p2)
        d2 = dict(doc)
        d2["paragraphs"] = paras_out
        if kind == "bom":
            d2["content"] = "\ufeff" + content
        elif kind == "crlf":
            d2["content"] = content.replace("\n", "\r\n")
        elif kind == "bom_crlf":
            d2["content"] = "\ufeff" + content.replace("\n", "\r\n")
        else:
            d2["content"] = content
        out.append(d2)
    return out


def _write_variant(
    src_case: Path, dest: Path, *, kind: str, envelope: bool,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    docs = json.loads((src_case / "raw_documents.json").read_text(encoding="utf-8"))
    stressed = _embed_and_stress(docs, kind=kind)
    payload: Any = {"raw_documents": stressed} if envelope else stressed
    (dest / "raw_documents.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # 旁证用：拷贝 conclusions / evidence_samples（load 不读它们）
    for name in ("conclusions.json", "evidence_samples.json"):
        p = src_case / name
        if p.is_file():
            shutil.copy2(p, dest / name)


def _measure_case(case_name: str, work: Path) -> dict[str, Any]:
    src = CASES / case_name
    gold_keys = _gold_para_ids(case_name)
    # baseline 旗关干净载入
    os.environ["VERITAS_ANCHOR_STABLE"] = "0"
    base_map = dossier_anchor_map(load_official_case(src))

    rows = []
    for kind in ("bom", "crlf", "bom_crlf"):
        for envelope in (False, True):
            tag = f"{kind}{'_env' if envelope else ''}"
            dest = work / case_name / tag
            if dest.exists():
                shutil.rmtree(dest)
            _write_variant(src, dest, kind=kind, envelope=envelope)

            os.environ["VERITAS_ANCHOR_STABLE"] = "0"
            try:
                off_d = load_official_case(dest)
                off = compare_anchor_maps(
                    base_map, dossier_anchor_map(off_d), keys=gold_keys,
                )
                off_err = ""
            except Exception as exc:  # noqa: BLE001 — 探针记账
                off = {
                    "n": len(gold_keys), "ok": 0, "consistency_rate": 0.0,
                    "missing_anchor": list(gold_keys), "drift": [],
                }
                off_err = f"{type(exc).__name__}: {exc}"

            os.environ["VERITAS_ANCHOR_STABLE"] = "1"
            try:
                on_d = load_official_case(dest)
                on = compare_anchor_maps(
                    base_map, dossier_anchor_map(on_d), keys=gold_keys,
                )
                on_err = ""
                leaks = audit_forbidden_keys(
                    (on_d.accounting or {}).get("anchor_stable") or {},
                )
            except Exception as exc:  # noqa: BLE001
                on = {
                    "n": len(gold_keys), "ok": 0, "consistency_rate": 0.0,
                    "missing_anchor": list(gold_keys), "drift": [],
                }
                on_err = f"{type(exc).__name__}: {exc}"
                leaks = []

            rows.append({
                "stress": tag,
                "gold_n": len(gold_keys),
                "off_rate": off["consistency_rate"],
                "off_ok": off["ok"],
                "off_missing": len(off.get("missing_anchor") or []),
                "off_drift": len(off.get("drift") or []),
                "off_err": off_err,
                "on_rate": on["consistency_rate"],
                "on_ok": on["ok"],
                "on_missing": len(on.get("missing_anchor") or []),
                "on_drift": len(on.get("drift") or []),
                "on_err": on_err,
                "leaks": leaks,
            })
    return {"case": case_name, "gold_n": len(gold_keys), "rows": rows}


def _meta() -> dict[tuple[str, str], dict]:
    if not (C85 / "score_input.json").exists():
        return {}
    return {
        (j["case"], j["qid"]): j
        for j in json.loads((C85 / "score_input.json").read_text(encoding="utf-8"))
    }


def _gold_seg(gold: set) -> set[str]:
    return {
        str(loc) if "#" in str(loc) else f"{doc}#{loc}"
        for doc, loc in gold
    }


def _at7(dossier, selected: set[str], gold: set) -> int:
    pri = [
        str(x) for x in (dossier.accounting or {}).get("kg_priority_segment_ids") or []
    ]
    head = [x for x in pri if x in selected][:7]
    if len(head) < 7:
        head = head + sorted(selected - set(head))[: 7 - len(head)]
    return l2_hits(gold, selected_locs(dossier, set(head)))


def _pack_l2(case_name: str, qid: str, flag: str) -> dict[str, int]:
    os.environ["VERITAS_ANCHOR_STABLE"] = flag
    os.environ["VERITAS_KG_SUBMIT_SURFACE"] = "1"
    os.environ["VERITAS_KG_STAGE1"] = "1"
    os.environ["VERITAS_KG_REHYDRATE_BOX"] = "1"
    meta = _meta().get((case_name, qid)) or {}
    query = str(meta.get("query") or qid)
    budget = int(meta.get("budget") or 12_000)
    gold, _denom = _gold_keys(DEFAULT_GOLD, case_name, qid)
    gold_seg = _gold_seg(gold)
    d = load_official_case(CASES / case_name)
    d.question = query
    bridge = density_submit_surface(
        d, top_n=180, order=None, gold_ids=gold_seg or None, use_stage1=True,
    )
    leaks = audit_forbidden_keys(bridge["surface"])
    d.accounting["kg_submit"] = bridge["surface"]
    d.accounting["kg_cap_segments"] = False
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    for bad in FORBIDDEN_PACK_KEYS:
        assert bad not in (kw or {})
    pack = pack_material(d, budget_chars=budget, **(kw or {}))
    selected = set(str(x) for x in (pack.get("selected") or []))
    d.accounting["material_pack_selected"] = sorted(selected)
    l2 = l2_hits(gold, selected_locs(d, selected))
    at7 = _at7(d, selected, gold)
    return {"l2": l2, "at7": at7, "gold": len(gold), "leaks": len(leaks)}


def _side_pack() -> dict[str, Any]:
    if not C85.is_dir() or not (C85 / "score_input.json").exists():
        return {"skipped": True, "reason": "no /tmp/c85_k180"}
    lx_off = [_pack_l2(CASE_LX, qid, "0") for qid in QIDS]
    lx_on = [_pack_l2(CASE_LX, qid, "1") for qid in QIDS]
    hold_off: list[dict] = []
    hold_on: list[dict] = []
    for case_name, _alias in HOLDOUT:
        for qid in QIDS:
            hold_off.append(_pack_l2(case_name, qid, "0"))
            hold_on.append(_pack_l2(case_name, qid, "1"))
    return {
        "skipped": False,
        "lx_at7_off": sum(x["at7"] for x in lx_off),
        "lx_at7_on": sum(x["at7"] for x in lx_on),
        "lx_l2_off": sum(x["l2"] for x in lx_off),
        "lx_l2_on": sum(x["l2"] for x in lx_on),
        "holdout_l2_off": sum(x["l2"] for x in hold_off),
        "holdout_l2_on": sum(x["l2"] for x in hold_on),
        "pack_leaks": sum(x["leaks"] for x in lx_off + lx_on + hold_off + hold_on),
        "lx_detail_off": lx_off,
        "lx_detail_on": lx_on,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/C114_anchor_stable.md")
    args = ap.parse_args()
    t0 = time.time()
    if not CASES.is_dir():
        print(f"missing cases: {CASES}", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="c114_anchor_"))
    try:
        case_reports = [_measure_case(c, work) for c in SAMPLE_CASES]
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # 汇总：所有应力行
    off_ok = on_ok = n_total = 0
    leaks_all: list = []
    gain_rows = 0
    flat_rows = 0
    for cr in case_reports:
        for r in cr["rows"]:
            n_total += r["gold_n"]
            off_ok += r["off_ok"]
            on_ok += r["on_ok"]
            leaks_all.extend(r["leaks"])
            if r["on_rate"] > r["off_rate"] + 1e-12:
                gain_rows += 1
            elif abs(r["on_rate"] - r["off_rate"]) <= 1e-12:
                flat_rows += 1

    off_rate = off_ok / n_total if n_total else 0.0
    on_rate = on_ok / n_total if n_total else 0.0
    side = _side_pack()

    # 过线：一致率相对旗关有稳定增益；泄漏0；旁证不回归
    leaks_n = len(leaks_all)
    side_ok = True
    if not side.get("skipped"):
        side_ok = (
            side["lx_at7_on"] >= 11
            and side["lx_at7_on"] >= side["lx_at7_off"]
            and side["holdout_l2_on"] >= side["holdout_l2_off"] - 1
        )
    pass_line = (
        on_rate > off_rate + 1e-12
        and gain_rows >= 1
        and leaks_n == 0
        and side_ok
    )
    advice = "YES" if pass_line else "NO"

    wall = time.time() - t0
    md_lines = [
        "# C-114 证据定位稳（重构后再解析开／关对照）",
        "",
        f"> 零 LLM 主尺；旗默认关；`VERITAS_ANCHOR_STABLE=1` 开。墙钟 {wall:.1f}s。",
        "> 挂点：`app/core/anchor_stable.py`；`app/ingest/official_case.py`（加固切片／解包）；"
        "`app/export/official.py`（缺锚披露）；`app/config.py`（旗）。",
        f"> 过线建议：**{advice}** — 一致率 关 {off_rate:.4f} → 开 {on_rate:.4f}；"
        f"泄漏={leaks_n}；增益应力行 {gain_rows}／持平 {flat_rows}。",
        "",
        "## 结论",
        "",
        f"- 一致率（金标键×应力）：关 **{off_ok}/{n_total}={off_rate:.4f}** → "
        f"开 **{on_ok}/{n_total}={on_rate:.4f}**",
        f"- 泄漏（FORBIDDEN_PACK_KEYS）：**{leaks_n}**",
        (
            f"- 旁证刘翔@7：关 {side.get('lx_at7_off')}／开 {side.get('lx_at7_on')}；"
            f"holdout L2：关 {side.get('holdout_l2_off')}／开 {side.get('holdout_l2_on')}"
            if not side.get("skipped")
            else f"- 旁证装箱：跳过（{side.get('reason')}）"
        ),
        f"- **合入建议：{'可建议合 main（仍默认关）' if advice == 'YES' else '不合 main'}**"
        "；本票不直接合；C-113 未并入。",
        "",
        "## 分案应力表",
        "",
    ]
    for cr in case_reports:
        md_lines.append(f"### {cr['case']}（金标键 {cr['gold_n']}）")
        md_lines.append("")
        md_lines.append(
            "| stress | off_ok/n | off_rate | on_ok/n | on_rate | Δ |"
        )
        md_lines.append("|---|---:|---:|---:|---:|---:|")
        for r in cr["rows"]:
            delta = r["on_rate"] - r["off_rate"]
            md_lines.append(
                f"| {r['stress']} | {r['off_ok']}/{r['gold_n']} | "
                f"{r['off_rate']:.3f} | {r['on_ok']}/{r['gold_n']} | "
                f"{r['on_rate']:.3f} | {delta:+.3f} |"
            )
            if r["off_err"] or r["on_err"]:
                md_lines.append(
                    f"  - err off=`{r['off_err']}` on=`{r['on_err']}`"
                )
        md_lines.append("")

    md_lines.append("## 一行验收")
    md_lines.append("")
    md_lines.append(
        f"过线建议 **{advice}**＋一致率 关{off_rate:.4f}/开{on_rate:.4f}"
        f"＋泄漏{leaks_n}＋旁证@7="
        f"{side.get('lx_at7_on', 'NA')}/holdout="
        f"{side.get('holdout_l2_on', 'NA')}"
    )
    md_lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    payload = {
        "advice": advice,
        "off_rate": off_rate,
        "on_rate": on_rate,
        "off_ok": off_ok,
        "on_ok": on_ok,
        "n_total": n_total,
        "leaks": leaks_n,
        "gain_rows": gain_rows,
        "flat_rows": flat_rows,
        "side": side,
        "cases": case_reports,
        "wall_s": wall,
        "hooks": [
            "app/core/anchor_stable.py",
            "app/ingest/official_case.py",
            "app/export/official.py",
            "app/config.py",
        ],
        "flag": "VERITAS_ANCHOR_STABLE",
        "flag_default": False,
    }
    args.out.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(md_lines[-3])
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
