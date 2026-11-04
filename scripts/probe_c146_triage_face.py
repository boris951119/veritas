#!/usr/bin/env python3
# /// C-146 分流仪器：改前／改后反事实比对＋真产物分流读数（零 LLM、零现金）
"""
三段（--stage）：

- ``export``   合成夹具跑「改前（base tip 码）vs 改后（本枝码）」反事实比对：
               剥掉 triage 五键后逐字节相同 ⇒ 分流没吃掉 conflict_class／
               disposition／reason／entry。同时产出入仓快照
               ``tests/c146_pre_triage_snapshot.json``（测试读它，不读代码）。
- ``demo``     三案例 ``scripts/demo_offline.py`` 开旗跑一遍，读
               ``accounting.conflict_trace`` 的真行数与 by_triage 计数。
- ``assemble`` 只把已落盘的两段读数合成 artifacts／md（不再调用任何码）。

用法（本机 .venv，两棵树各自跑）：
    .venv/bin/python -X utf8 scripts/probe_c146_triage_face.py --stage export
    .venv/bin/python -X utf8 scripts/probe_c146_triage_face.py --stage demo
    .venv/bin/python -X utf8 scripts/probe_c146_triage_face.py --stage assemble
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE_REF = os.environ.get("VERITAS_C146_BASE_REF", "03bfd4a")
SNAPSHOT = ROOT / "tests" / "c146_pre_triage_snapshot.json"
ART_JSON = ROOT / "artifacts" / "C146_triage_face.json"
ART_MD = ROOT / "artifacts" / "C146_triage_face.md"
CASES = ("demo-solid-state", "bi-delivery-risk", "rumor-vs-official")
TRIAGE_KEYS = (
    "triage_class", "triage_class_cn", "triage_reason_code",
    "triage_reason_short", "triage_evidence",
)


def _load_base_module():
    """把改前 tip 的 conflict_trace.py 取出来当独立模块导入（不改工作树）。"""
    src = subprocess.run(
        ["git", "show", f"{BASE_REF}:app/core/conflict_trace.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    tmp = Path(tempfile.mkdtemp()) / "conflict_trace_base_c146.py"
    tmp.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "conflict_trace_base_c146", str(tmp))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod, src


def _strip_triage(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in TRIAGE_KEYS}


def stage_export() -> dict:
    from tests.c146_triage_fixtures import build_rows as branch_rows
    base_mod, base_src = _load_base_module()
    from tests.c146_triage_fixtures import ledger_cases, pair_cases

    # 用改前码原样重跑同一批夹具（输入构造相同，见 fixtures 文件头注释）
    base_rows = []
    for i, (_n, col, _segs) in enumerate(ledger_cases(), 1):
        base_rows.append(base_mod.trace_ledger_collision(col, index=i))
    for i, (_n, pair, dossier) in enumerate(pair_cases(), 1):
        base_rows.append(base_mod.trace_conflict_pair(
            pair, index=i, dossier=dossier))

    after = [_strip_triage(r) for r in branch_rows()]
    diffs = [
        {"i": i, "before": b, "after": a}
        for i, (b, a) in enumerate(zip(base_rows, after)) if b != a
    ]
    snap_payload = {
        "generated_from_base": BASE_REF,
        "n_rows": len(base_rows),
        "rows": base_rows,
        "note": "改前 tip 码对同一批 C-146 夹具的输出；测试据此证「剥掉 triage 五键＝与改前逐字节相同」",
    }
    SNAPSHOT.write_text(
        json.dumps(snap_payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    from app.core.conflict_trace import (
        CONFLICT_CLASSES, TRIAGE_CLASSES, apply_conflict_trace,
    )
    from app.core.evidence import Dossier
    from tests.c146_triage_fixtures import ledger_cases as _lc

    d = Dossier(question="分流禁品闸")
    cols = [c for _n, c, _s in _lc()]
    payload = apply_conflict_trace(d, collisions=cols, enabled=True)
    flat = json.dumps(payload, ensure_ascii=False)

    res = {
        "stage": "export",
        "base_ref": BASE_REF,
        "n_fixture_rows": len(base_rows),
        "n_rows_snapshot": snap_payload["n_rows"],
        "counterfactual_diffs": len(diffs),
        "diff_samples": diffs[:3],
        "triage_enum": sorted(TRIAGE_CLASSES),
        "conflict_class_enum": sorted(CONFLICT_CLASSES),
        "axes_orthogonal": not (set(TRIAGE_CLASSES) & set(CONFLICT_CLASSES)),
        "triage_keys_on_rows": list(TRIAGE_KEYS),
        "forbidden_face_hits": [
            k for k in ("gold", "金标", "coeff", "weights", "w_eff")
            if k in flat
        ],
    }
    return res


def stage_demo() -> dict:
    env = dict(os.environ)
    env["VERITAS_CONFLICT_TRACE"] = "1"
    out = subprocess.run(
        [sys.executable, "-X", "utf8", "scripts/demo_offline.py"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    per_case: dict[str, dict] = {}
    for case in CASES:
        p = ROOT / "cases" / case / "out_offline" / "report.json"
        if not p.exists():
            per_case[case] = {"error": "no_report_json"}
            continue
        j = json.loads(p.read_text(encoding="utf-8"))
        ct = (j.get("accounting") or {}).get("conflict_trace") or {}
        sm = ct.get("summary") or {}
        recs = ct.get("records") or []
        per_case[case] = {
            "n": sm.get("n"),
            "by_class": sm.get("by_class"),
            "by_disposition": sm.get("by_disposition"),
            "by_triage": sm.get("by_triage"),
            "triaged": sm.get("triaged"),
            "untriaged": sm.get("untriaged"),
            "rows": [
                {
                    "id": r.get("id"), "source": r.get("source"),
                    "conflict_class": r.get("conflict_class"),
                    "disposition": r.get("disposition"),
                    "triage_class": r.get("triage_class"),
                    "triage_reason_code": r.get("triage_reason_code"),
                    "metric": (r.get("entry") or {}).get("metric")
                              or (r.get("entry") or {}).get("topic"),
                } for r in recs
            ],
        }
    tot_triage: dict[str, int] = {}
    for v in per_case.values():
        for k, n in (v.get("by_triage") or {}).items():
            tot_triage[k] = tot_triage.get(k, 0) + int(n or 0)
    return {
        "stage": "demo",
        "demo_returncode": out.returncode,
        "per_case": per_case,
        "triage_total": tot_triage,
        "triage_total_n": sum(tot_triage.values()),
    }


def stage_assemble() -> dict:
    parts: dict[str, dict] = {}
    if ART_JSON.exists():
        old = json.loads(ART_JSON.read_text(encoding="utf-8"))
        parts = old.get("stages") or {}
    merged = {
        "ticket": "C-146",
        "base_ref": BASE_REF,
        "generated_by": "scripts/probe_c146_triage_face.py",
        "stages": parts,
    }
    ART_JSON.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    _render_md(merged)
    return merged


# ---- 跨树同形（改前树 vs 本枝树）------------------------------------------
_VOLATILE_KEY = re.compile(
    r"^(elapsed_s|elapsed|total_elapsed_s|chain_head|head_hash|hash|"
    r"prev_hash|digest|timestamp|generated_at|created_at|n_vec)$",
    re.I,
)


def _cross_normalizers(base_root: Path, br_root: Path):
    roots = {str(base_root): "<tree>", str(br_root): "<tree>"}
    ts = re.compile(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+\d{2}:\d{2})?")
    ident = re.compile(r"(?:CON|EV|CFL|SRC|LEDGER|PAIR)-[0-9a-f]{8,}")
    hexrun = re.compile(r"\b[0-9a-f]{8,}\b")

    def sub_text(s: str) -> str:
        for k, v in roots.items():
            s = s.replace(k, v)
        return hexrun.sub("<hex>", ts.sub("<ts>", s))

    def normalize(obj, counters):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                kk = sub_text(str(k))
                if ident.search(str(k)):
                    pre = str(k).split("-")[0]
                    counters[pre] = counters.get(pre, 0) + 1
                    kk = f"{pre}-<id{counters[pre]:03d}>"
                if _VOLATILE_KEY.match(kk):
                    continue
                out[kk] = normalize(v, counters)
            return out
        if isinstance(obj, list):
            return [normalize(v, counters) for v in obj]
        if isinstance(obj, str):
            return ident.sub(
                lambda m: f"{m.group(0).split('-')[0]}-<id>", sub_text(obj))
        if isinstance(obj, float):
            return round(obj, 6)
        return obj

    def walk(x, y, path="", out=None):
        out = [] if out is None else out
        if isinstance(x, dict) and isinstance(y, dict):
            for k in set(x) | set(y):
                if k not in x:
                    out.append((f"{path}.{k}", "added"))
                elif k not in y:
                    out.append((f"{path}.{k}", "removed"))
                else:
                    walk(x[k], y[k], f"{path}.{k}", out)
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                out.append((path, f"len {len(x)}->{len(y)}"))
            else:
                for i, (xi, yi) in enumerate(zip(x, y)):
                    walk(xi, yi, f"{path}[{i}]", out)
        elif x != y:
            out.append((path, "value"))
        return out

    return normalize, walk, sub_text


def stage_crossface(base_root: str, flag: str) -> dict:
    """两棵树（改前 tip／本枝）同跑 demo 后比产物面。

    flag=off ⇒ 判「关旗与改前逐字节同形」（差异必须为 0）；
    flag=on  ⇒ 判「开旗差异只落在 conflict_trace 面内」（面外差异必须为 0）。
    """
    br_root = ROOT
    base_cases = Path(base_root) / "cases"
    br_cases = br_root / "cases"
    normalize, walk, _sub = _cross_normalizers(Path(base_root), br_root)
    res = {
        "stage": "crossface", "flag": flag,
        "base_root": str(base_root), "base_ref": BASE_REF,
        "files": {}, "report_md_same": 0, "report_md_n": 0,
    }
    diff_total = 0
    trace_only_diff = 0
    outside = []
    for case in CASES:
        for rel in ("report.json", "report.md", "chain.jsonl"):
            pa, pb = base_cases / case / "out_offline" / rel, \
                br_cases / case / "out_offline" / rel
            if not (pa.exists() and pb.exists()):
                res["files"][f"{case}/{rel}"] = "MISSING"
                continue
            if rel.endswith(".json"):
                a = normalize(json.loads(pa.read_text(encoding="utf-8")), {})
                b = normalize(json.loads(pb.read_text(encoding="utf-8")), {})
                if rel == "report.json":
                    diffs = walk(a, b)
                    for path, kind in diffs:
                        diff_total += 1
                        if "conflict_trace" not in path:
                            outside.append((case, path, kind))
                    res["files"][f"{case}/{rel}"] = {
                        "n_diff_paths": len(diffs),
                        "all_inside_conflict_trace": all(
                            "conflict_trace" in p for p, _k in diffs),
                    }
                else:
                    same = json.dumps(a, sort_keys=True, ensure_ascii=False) == \
                        json.dumps(b, sort_keys=True, ensure_ascii=False)
                    res["files"][f"{case}/{rel}"] = {"same": same}
            elif rel.endswith(".md"):
                ta = _sub(pa.read_text(encoding="utf-8"))
                tb = _sub(pb.read_text(encoding="utf-8"))
                same = ta == tb
                res["report_md_n"] += 1
                res["report_md_same"] += int(same)
                res["files"][f"{case}/{rel}"] = {"same": same}
            else:
                # 逐跑日志面：剥链上易变键＋并行事件到达序后比多重集；
                # 再把 conflict_trace 载荷整个摘掉比一次 ⇒ 差异是否只长在分流面
                def _canon(line: str, drop_trace: bool) -> str:
                    s = _sub(line)
                    d = json.loads(s)
                    for key in ("hash", "mac", "payload_hash", "prev_hash",
                                "index", "timestamp", "ts"):
                        if key in d:
                            d[key] = "<vol>"
                    payload = d.get("payload")
                    if drop_trace and isinstance(payload, dict):
                        payload.pop("conflict_trace", None)
                        for k in ("n_demoted",):
                            payload.pop(k, None)
                    return json.dumps(d, ensure_ascii=False, sort_keys=True)

                la = [l for l in pa.read_text(encoding="utf-8").splitlines()
                      if l.strip()]
                lb = [l for l in pb.read_text(encoding="utf-8").splitlines()
                      if l.strip()]
                res["files"][f"{case}/{rel}"] = {
                    "n_lines": [len(la), len(lb)],
                    "same_multiset": sorted(
                        _canon(x, False) for x in la) == sorted(
                        _canon(x, False) for x in lb),
                    "same_multiset_wo_trace_payload": sorted(
                        _canon(x, True) for x in la) == sorted(
                        _canon(x, True) for x in lb),
                }
                if (not res["files"][f"{case}/{rel}"]["same_multiset"]
                        and res["files"][f"{case}/{rel}"][
                            "same_multiset_wo_trace_payload"]):
                    trace_only_diff += 1
    res["diff_paths_total"] = diff_total
    res["diff_paths_outside_conflict_trace"] = outside
    res["chain_diff_only_in_trace_payload_cases"] = trace_only_diff
    return res


def _render_md(doc: dict) -> None:
    st = doc.get("stages") or {}
    ex = st.get("export") or {}
    dm = st.get("demo") or {}
    lines = ["# C-146 分流读数（仪器现抄，非手打）", ""]
    lines += [
        "## 反事实比对（合成夹具）",
        f"- 改前码 ref＝`{ex.get('base_ref')}`；夹具行数＝"
        f"{ex.get('n_fixture_rows')}（快照同数＝{ex.get('n_rows_snapshot')}）",
        f"- 剥掉 triage 五键后与改前逐字节不同的行数＝**{ex.get('counterfactual_diffs')}**"
        "（0 ⇒ 分流没吃掉 conflict_class／disposition／reason／entry）",
        f"- 两轴正交（triage ∩ conflict_class 空）＝{ex.get('axes_orthogonal')}",
        f"- 禁品面命中（gold／金标／coeff／weights／w_eff）＝"
        f"{ex.get('forbidden_face_hits')}",
        "",
        "## 三案例真产物分流（开旗 demo_offline）",
        f"- demo 退出码＝{dm.get('demo_returncode')}；"
        f"四档合计＝{json.dumps(dm.get('triage_total'), ensure_ascii=False)}"
        f"（Σ＝{dm.get('triage_total_n')}）",
        "",
        "| 案例 | 行数 | by_class | by_disposition | by_triage |",
        "|---|---|---|---|---|",
    ]
    for case, v in (dm.get("per_case") or {}).items():
        lines.append(
            f"| {case} | {v.get('n')} | "
            f"{json.dumps(v.get('by_class'), ensure_ascii=False)} | "
            f"{json.dumps(v.get('by_disposition'), ensure_ascii=False)} | "
            f"{json.dumps(v.get('by_triage'), ensure_ascii=False)} |"
        )
    lines += ["", "### 逐行（谁被判成哪档）", ""]
    for case, v in (dm.get("per_case") or {}).items():
        for r in v.get("rows") or []:
            lines.append(
                f"- {case} `{r.get('id')}`（{r.get('source')}／"
                f"{r.get('metric')}）class={r.get('conflict_class')} "
                f"disp={r.get('disposition')} → **triage={r.get('triage_class')}**"
                f"·{r.get('triage_reason_code')}"
            )
    for flag, cf in (("off", st.get("crossface_off")), ("on", st.get("crossface_on"))):
        if not cf:
            continue
        lines += [
            "",
            f"## 跨树同形·旗＝{flag}（改前树 {cf.get('base_root')} vs 本枝）",
            f"- report.json 差异路径数＝{cf.get('diff_paths_total')}；"
            f"其中落在 conflict_trace 面外的＝"
            f"{len(cf.get('diff_paths_outside_conflict_trace') or [])}",
            f"- report.md 规范化同形＝{cf.get('report_md_same')}/"
            f"{cf.get('report_md_n')}",
            f"- 逐文件：{json.dumps(cf.get('files'), ensure_ascii=False)}",
        ]
    ART_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="export",
                    choices=["export", "demo", "crossface", "assemble"])
    ap.add_argument("--base-root", default="",
                    help="改前 tip 那棵树的工作树根（crossface 用）")
    ap.add_argument("--flag", default="off", choices=["off", "on"],
                    help="crossface 比对时两棵树各自跑的旗")
    args = ap.parse_args()
    if args.stage == "assemble":
        doc = stage_assemble()
        print(json.dumps({"stages_present": sorted(
            (doc.get("stages") or {}).keys())}, ensure_ascii=False))
        return 0
    if args.stage == "crossface":
        if not args.base_root:
            print("crossface 需要 --base-root（改前树）")
            return 2
        res = stage_crossface(args.base_root, args.flag)
        key = f"crossface_{'on' if args.flag == 'on' else 'off'}"
    else:
        res = stage_export() if args.stage == "export" else stage_demo()
        key = args.stage
    parts: dict[str, dict] = {}
    if ART_JSON.exists():
        parts = json.loads(
            ART_JSON.read_text(encoding="utf-8")).get("stages") or {}
    parts[key] = res
    ART_JSON.write_text(json.dumps({
        "ticket": "C-146", "base_ref": BASE_REF,
        "generated_by": "scripts/probe_c146_triage_face.py",
        "stages": parts,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
