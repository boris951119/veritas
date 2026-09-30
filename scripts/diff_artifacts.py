"""离线产物归一化比对：重构「不改变行为」的硬判据。

产物含 uuid 派生的 id 与哈希，逐字节必不相同——归一化（id/哈希/时间
置换为占位符）后必须一致。用法：

    .venv/bin/python scripts/diff_artifacts.py save   # 存基线
    .venv/bin/python scripts/diff_artifacts.py check  # 与基线比对
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_CASES = ("demo-solid-state", "bi-delivery-risk")
_FILES = ("report.md", "chain.jsonl", "report.json")
_BASE = Path("/tmp/veritas_artifacts_baseline")

_ID = re.compile(r"\b(?:CON|EV|CFL|SRC|PA)-[0-9a-zA-Z]{8,}\b")
_IDX = re.compile(r'"index": \d+')
_SRC_KEPT = re.compile(r"\bSRC\d+#s\d+\b")   # 确定性段 id 保留
_HASH = re.compile(r"\b[0-9a-f]{64}\b")
_TS = re.compile(r"\b20\d{2}-\d{2}-\d{2}[T ][0-9:.+Z-]+\b")


def normalize(text: str) -> str:
    def _sub_id(m: re.Match) -> str:
        return m.group(0) if _SRC_KEPT.fullmatch(m.group(0)) \
            else m.group(0).split("-")[0] + "-X"
    text = _ID.sub(_sub_id, text)
    text = _HASH.sub("H", text)
    text = _TS.sub("TS", text)
    text = _IDX.sub('"index": I', text)
    return text


def _iter_normalized() -> dict[str, str]:
    out: dict[str, str] = {}
    for case in _CASES:
        for name in _FILES:
            p = Path("cases") / case / "out_offline" / name
            if p.is_file():
                text = normalize(p.read_text(encoding="utf-8"))
                if name == "chain.jsonl":
                    # 并行事件（analyst_done 等）完成次序不定——内容全同
                    # 仅行序不同，属可接受差异：排序后比对
                    text = "\n".join(sorted(text.splitlines()))
                out[f"{case}/{name}"] = text
    return out


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "save":
        _BASE.mkdir(parents=True, exist_ok=True)
        for key, text in _iter_normalized().items():
            (_BASE / key.replace("/", "__")).write_text(text, encoding="utf-8")
        print(f"基线已存: {_BASE}（{len(_iter_normalized())} 个产物）")
        return 0
    if not _BASE.is_dir():
        print("无基线——先 save"); 
        return 2
    diffs = 0
    for key, text in _iter_normalized().items():
        base = _BASE / key.replace("/", "__")
        if not base.is_file():
            print(f"  ？基线缺 {key}")
            continue
        if base.read_text(encoding="utf-8") != text:
            diffs += 1
            print(f"  ✗ {key} 归一化后不一致")
        else:
            print(f"  ✓ {key}")
    print("归一化比对：", "全部一致 ✅" if diffs == 0 else f"{diffs} 个不一致 ❌")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
