#!/usr/bin/env python3
"""C-48 件①：因果主张卡覆盖量尺（只量、零模型）。

读既有 report.json，不调模型、不写 app/、不改判定。

输入＝env CAUSAL_PROBE_ROOTS（逗号分隔的产物根；缺／空 ⇒ 退出码 2 带原因）。
逐根打印：证据条数、causal_claim 键在场率 vs 有内容率（分开计＝与 #160 同口径）、
四要素逐要素非空率（分子分母原样整数）、declared_relation=causation 且
relation=correlation 的降级条数、mechanism_completeness／design_tier／missing_links
分布；旧产物缺键按缺失计数、不得抛异常。

汇总一行"非空率 X%／降级声称 Y 条 ⇒ 件② 门槛（Y≥N）够不够"——够不够由
PIECE2_DEGRADED_THRESHOLD 当场比较算出，不许写死。

跑法：
    CAUSAL_PROBE_ROOTS=cases .venv/bin/python scripts/probe_causal_claim_coverage.py
    CAUSAL_PROBE_ROOTS=/tmp/s4runs/time-20261023-173124 \\
        .venv/bin/python scripts/probe_causal_claim_coverage.py
    CAUSAL_PROBE_ROOTS=cases,/tmp/s4runs/time-20261023-173124 \\
        .venv/bin/python scripts/probe_causal_claim_coverage.py

登记见 docs/dev-journal.md（C-48）；不进 tests/c37_zero_ref_registry.py。
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

# 件② 门槛：降级声称条数 ≥ 此值才"够"。改常量 ⇒ 汇总句结论必须跟着翻。
PIECE2_DEGRADED_THRESHOLD = 10

CLAIM_KEYS = ("intervention", "outcome", "population", "counterfactual")


def _die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _find_reports(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("report.json") if p.is_file())


def _claim_contentful(claim) -> bool:
    """有内容＝dict 且四要素任一非空（键在场≠有内容）。"""
    if not isinstance(claim, dict):
        return False
    return any(str(claim.get(k) or "").strip() for k in CLAIM_KEYS)


def _claim_full(claim) -> bool:
    """四要素全非空。"""
    if not isinstance(claim, dict):
        return False
    return all(str(claim.get(k) or "").strip() for k in CLAIM_KEYS)


def _missing_links_label(ev: dict) -> str:
    if "missing_links" not in ev:
        return "<missing>"
    ml = ev.get("missing_links")
    if ml is None:
        return "<null>"
    if not isinstance(ml, list):
        return f"<nonlist:{type(ml).__name__}>"
    if not ml:
        return "[]"
    return ",".join(sorted(str(x) for x in ml))


def _scan_root(root: Path) -> dict:
    """只读 JSON；缺键按缺失计数，不抛。"""
    reports = _find_reports(root)
    n_ev = 0
    key_present = 0
    contentful = 0
    full_nonempty = 0
    per_key = {k: 0 for k in CLAIM_KEYS}
    n_degraded = 0
    n_declared_missing = 0
    mech = Counter()
    design = Counter()
    links = Counter()

    for rp in reports:
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  WARN 跳过不可读 {rp}: {exc}")
            continue
        if not isinstance(data, dict):
            continue
        evidences = data.get("evidences") or []
        if not isinstance(evidences, list):
            continue
        for ev in evidences:
            if not isinstance(ev, dict):
                continue
            n_ev += 1
            # 键在场 ≠ 有内容（#160 同口径）
            if "causal_claim" in ev:
                key_present += 1
                claim = ev.get("causal_claim")
                if _claim_contentful(claim):
                    contentful += 1
                if _claim_full(claim):
                    full_nonempty += 1
                if isinstance(claim, dict):
                    for k in CLAIM_KEYS:
                        if str(claim.get(k) or "").strip():
                            per_key[k] += 1
            # 降级：declared=causation 且 relation=correlation；缺键不算降级
            if "declared_relation" not in ev:
                n_declared_missing += 1
                decl = ""
            else:
                decl = str(ev.get("declared_relation") or "")
            relation = str(ev.get("relation") or "")
            if decl == "causation" and relation == "correlation":
                n_degraded += 1
            # 分布：缺键 → <missing>
            if "mechanism_completeness" not in ev:
                mech["<missing>"] += 1
            else:
                mech[str(ev.get("mechanism_completeness") or "<empty>")] += 1
            if "design_tier" not in ev:
                design["<missing>"] += 1
            else:
                design[str(ev.get("design_tier") or "<empty>")] += 1
            links[_missing_links_label(ev)] += 1

    return {
        "root": str(root),
        "n_reports": len(reports),
        "n_ev": n_ev,
        "key_present": key_present,
        "contentful": contentful,
        "full_nonempty": full_nonempty,
        "per_key": per_key,
        "n_degraded": n_degraded,
        "n_declared_missing": n_declared_missing,
        "mech": dict(mech),
        "design": dict(design),
        "links": dict(links),
    }


def _pct(num: int, den: int) -> str:
    if den <= 0:
        return "n/a"
    return f"{100.0 * num / den:.1f}%"


def _print_face(st: dict) -> None:
    n = st["n_ev"]
    print(f"==== 面 {st['root']} ====")
    print(f"  report.json={st['n_reports']} 证据条数={n}")
    print(
        f"  causal_claim 键在场={st['key_present']}/{n} ({_pct(st['key_present'], n)})"
        f"  有内容={st['contentful']}/{n} ({_pct(st['contentful'], n)})"
        f"  （键在场≠有内容）"
    )
    print(f"  四要素全非空={st['full_nonempty']}/{n} ({_pct(st['full_nonempty'], n)})")
    for k in CLAIM_KEYS:
        v = st["per_key"][k]
        print(f"  四要素.{k} 非空={v}/{n} ({_pct(v, n)})")
    print(
        f"  降级声称（declared_relation=causation ∧ relation=correlation）"
        f"={st['n_degraded']} 条"
        f"（declared_relation 缺键={st['n_declared_missing']}）"
    )
    print(f"  mechanism_completeness 分布={st['mech']}")
    print(f"  design_tier 分布={st['design']}")
    print(f"  missing_links 分布={st['links']}")


def _enough_label(n_degraded: int) -> str:
    """当场比较；阈值改则结论跟着翻。"""
    return "够" if n_degraded >= PIECE2_DEGRADED_THRESHOLD else "不够"


def _print_summary(full_nonempty: int, n_ev: int, n_degraded: int) -> None:
    rate = _pct(full_nonempty, n_ev)
    label = _enough_label(n_degraded)
    print(
        f"==== 汇总 ===="
        f" 非空率 {rate}／降级声称 {n_degraded} 条"
        f" ⇒ 件② 门槛（Y≥{PIECE2_DEGRADED_THRESHOLD}）{label}"
    )
    # 明示这是 1.3 非必须加分件
    print(
        "（说明：这是《评分标准》1.3 的非必须加分件、人工评测，我们不预测得分）"
    )


def main() -> int:
    raw = os.environ.get("CAUSAL_PROBE_ROOTS")
    if raw is None or not str(raw).strip():
        _die(
            "缺环境变量 CAUSAL_PROBE_ROOTS（逗号分隔的产物根；"
            "例：CAUSAL_PROBE_ROOTS=cases,/tmp/s4runs/time-20261023-173124）"
        )
    roots: list[Path] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        roots.append(Path(part).expanduser())
    if not roots:
        _die("CAUSAL_PROBE_ROOTS 解析后为空（逗号分隔的产物根）")

    faces: list[dict] = []
    for root in roots:
        if not root.exists():
            _die(f"产物根不存在：{root}")
        if not root.is_dir():
            _die(f"产物根不是目录：{root}")
        reports = _find_reports(root)
        if not reports:
            _die(f"产物根下无 report.json：{root}")
        st = _scan_root(root)
        _print_face(st)
        faces.append(st)

    tot_ev = sum(f["n_ev"] for f in faces)
    tot_full = sum(f["full_nonempty"] for f in faces)
    tot_deg = sum(f["n_degraded"] for f in faces)
    _print_summary(tot_full, tot_ev, tot_deg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
