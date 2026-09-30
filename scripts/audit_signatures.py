"""签名审计：全库函数参数 >3 清单（重构方案 §3 的常驻判据）。

用法：.venv/bin/python scripts/audit_signatures.py [阈值=3]
退出码：发现超标即 1（可挂 CI/评审钩子）。self/*args/**kwargs 不计。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def audit(threshold: int = 3) -> list[tuple[int, str, str]]:
    rows: list[tuple[int, str, str]] = []
    for p in sorted(Path("app").rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [*node.args.posonlyargs, *node.args.args]
                if args and args[0].arg == "self":
                    args = args[1:]
                total = len(args) + len(node.args.kwonlyargs)
                if total > threshold:
                    rows.append((total, f"{p}:{node.lineno}", node.name))
    rows.sort(reverse=True)
    return rows


if __name__ == "__main__":
    threshold = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    rows = audit(threshold)
    if not rows:
        print(f"全部函数参数 ≤{threshold} ✅")
        sys.exit(0)
    print(f"参数 >{threshold} 的函数 {len(rows)} 个：")
    for n, loc, name in rows:
        print(f"  {n}p  {loc}  {name}")
    sys.exit(1)
