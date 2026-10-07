#!/usr/bin/env python3
"""版式难例回归：表头/单元格是否入卷文本；空抽是否披露。

用法：
  .venv/bin/python scripts/build_layout_fixtures.py
  .venv/bin/python scripts/run_layout_eval.py

默认后端 pypdf；Docling 安装且 VERITAS_PDF_BACKEND=docling 时可对比。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.ingest.pdf_backend import extract_pdf, resolved_backend, set_pdf_backend

_BENCH = _ROOT / "eval" / "layout" / "benchmark.jsonl"
_FIX = _ROOT / "eval" / "layout" / "fixtures"


def main() -> int:
    if not _FIX.is_dir() or not any(_FIX.glob("*.pdf")):
        from scripts.build_layout_fixtures import main as build
        build()
    set_pdf_backend(None)  # 跟环境变量
    backend = resolved_backend()
    items = [
        json.loads(line)
        for line in _BENCH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hits = 0
    cell_total = 0
    cell_hit = 0
    disclosed = 0
    rows = []
    for it in items:
        path = _FIX / it["file"]
        result = extract_pdf(path)
        text = result.text or ""
        empty = not text.strip()
        if it.get("expect_disclosed_empty"):
            ok = empty
            if ok:
                disclosed += 1
        else:
            needles = it.get("must_contain") or []
            cell_total += len(needles)
            got = [n for n in needles if n in text]
            cell_hit += len(got)
            ok = len(got) == len(needles)
            if ok:
                hits += 1
        rows.append({
            "id": it["id"], "ok": ok, "backend": result.backend,
            "fallback": bool(result.fallback_from),
            "n_chars": len(text),
            "missing": [n for n in (it.get("must_contain") or [])
                        if n not in text],
        })
    n = len(items)
    report = {
        "backend": backend,
        "n_items": n,
        "item_pass_rate": round(hits / max(1, n), 4),
        "cell_recall": round(cell_hit / max(1, cell_total), 4),
        "cell_hit": cell_hit,
        "cell_total": cell_total,
        "items": rows,
        "notes": (
            "默认 pypdf 测「能否抽到字」；跨页表头重建不在默认保证范围。"
            "Docling 需另装并设 VERITAS_PDF_BACKEND=docling。"
        ),
    }
    out = _ROOT / "dist" / "layout-eval-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"=== layout eval (backend={backend}) ===")
    print(f"item pass : {report['item_pass_rate']} ({hits}/{n})")
    print(f"cell recall: {report['cell_recall']} "
          f"({cell_hit}/{cell_total})")
    for r in rows:
        if not r["ok"]:
            print(f"  miss {r['id']}: {r['missing']}")
    print(f"JSON → {out}")
    return 0 if hits == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
