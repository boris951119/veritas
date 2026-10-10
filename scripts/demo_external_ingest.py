#!/usr/bin/env python3
"""答辩演示：第三方智能体假引文入卷 → 机械打回并署名提交方。

零 LLM、零网络。用法：.venv/bin/python scripts/demo_external_ingest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from app.demo_external import run_external_reject_demo

    result = run_external_reject_demo()
    attr = result["attribution"]
    print("=== 外部智能体入卷演示（零 LLM）===")
    print(f"提交方：{attr['agent']}（{attr['agent_id']}）")
    print(f"提交时间：{attr['submitted_at']}")
    print(f"结论数：{attr['n_conclusions']}　存活证据：{attr['n_evidence_kept']}　打回：{attr['n_rejected']}")
    for r in attr.get("rejected") or []:
        print(f"  ✗ 打回 [{r.get('conclusion_id')}]")
        print(f"    假引文：{r.get('quote')}")
        print(f"    原因：{'；'.join(r.get('problems') or [])}")
    print()
    print("对照：真引文是否入卷 →",
          "是" if result["true_quote_kept"] else "否")
    print("假引文是否仍存活 →",
          "否（正确）" if not result["fake_quote_surviving"] else "是（异常）")
    print()
    print("答辩一句：第三方按 MCP/契约把结论送进来，假引文过同一道闸，")
    print("打回记录写明是谁提交的——责任可指认，不是我们替对方背锅。")
    print()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (attr["n_rejected"] >= 1 and result["true_quote_kept"]
                 and not result["fake_quote_surviving"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
