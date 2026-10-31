"""C-70：双轴相关性软闸量尺（默认 --dry-run＝零 HTTP 零模型）。

跑法::

    PYTHONPATH=. .venv/bin/python scripts/probe_c70_relevance_soft.py --dry-run
    PYTHONPATH=. .venv/bin/python scripts/probe_c70_relevance_soft.py \\
        --from /tmp/six2 \\
        --gold /path/to/样例集-拓尔思-20261012

打印六条读数（开／关两臂）＋反向腿＋确定性。文档点名只写 stem＝probe_c70_relevance_soft。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from app.core.evidence import Dossier  # noqa: E402
from app.core.material import pack_material, set_material_budget  # noqa: E402
from app.core.relevance import (  # noqa: E402
    classify_sources, match_score_source, match_vocab, set_relevance_soft_gate,
)
from scripts.probe_recall_funnel import (  # noqa: E402
    DEFAULT_GOLD, discover_reports, gold_paras_for_question,
)


def _measure_arm(run_dir: Path, gold_dir: Path, *, soft: bool) -> dict:
    set_relevance_soft_gate(soft)
    n_zero = 0
    n_gold_zero = 0
    n_pack = 0
    n_nongold = 0
    n_l2 = 0
    denom = 0
    n_zero_overlap = 0
    n_sm_pos = 0
    n_sm_zero = 0
    for rp in discover_reports(run_dir):
        case, qid = rp.parts[-4], rp.parts[-2]
        rep = json.loads(rp.read_text(encoding="utf-8"))
        d = Dossier.from_dict(rep)
        budget = int(((rep.get("accounting") or {}).get(
            "pack_window") or {}).get("budget") or 0)
        set_material_budget(budget)
        rows = classify_sources(d)
        n_zero += sum(1 for r in rows if r["level"] == "zero"
                      and "人工强制排除" not in str(r.get("reason") or ""))
        by = {s.id: s for s in d.sources}
        vocab = match_vocab(d.question)
        from app.core.citation_check import normalize
        from app.core.premise_check import extract_entities
        from app.core.relevance import _coverage, _latin_hit
        ents = extract_entities(d.question)
        for r in rows:
            src = by.get(r["source_id"])
            if src is None or not ents:
                continue
            text = normalize("".join(seg.text for seg in src.segments))
            best = max((_coverage(e, text) for e in ents), default=0.0)
            if best > 0 or _latin_hit(ents, text):
                continue
            n_zero_overlap += 1
            sm = float(r.get("s_match") if soft and r.get("s_match") is not None
                       else match_score_source(src, vocab))
            if sm > 0:
                n_sm_pos += 1
            else:
                n_sm_zero += 1
        pack = pack_material(d)
        sel = set(pack.get("selected") or [])
        n_pack += len(sel)
        gold, _ = gold_paras_for_question(gold_dir / case, qid)
        gold_paras = {p for _doc, p in gold}
        denom += len(gold_paras)
        n_l2 += sum(1 for p in gold_paras if p in sel)
        n_nongold += sum(1 for s in sel if s not in gold_paras)
        seg2src = {seg.id: src.id for src in d.sources for seg in src.segments}
        levels = {r["source_id"]: r for r in rows}
        for _doc, para in gold:
            sid = seg2src.get(para, "")
            lv = (levels.get(sid) or {}).get("level")
            if lv == "zero" and "人工强制排除" not in str(
                    (levels.get(sid) or {}).get("reason") or ""):
                n_gold_zero += 1
    return {
        "soft": soft,
        "gold_in_auto_zero": n_gold_zero,
        "denom": denom,
        "auto_zero_sources": n_zero,
        "l2": n_l2,
        "pack": n_pack,
        "nongold": n_nongold,
        "zero_overlap": n_zero_overlap,
        "sm_pos": n_sm_pos,
        "sm_zero": n_sm_zero,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="C-70 软闸量尺")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--from", dest="run_dir", type=Path, default=None)
    p.add_argument("--gold", type=Path, default=None)
    p.add_argument("--determinism", action="store_true",
                   help="同码两遍＋跨进程一遍")
    args = p.parse_args(argv)
    run_dir = args.run_dir
    gold = args.gold or Path(DEFAULT_GOLD)
    if args.dry_run or run_dir is None:
        print("mode=dry-run（零 HTTP 零模型；加 --from 才量）")
        print(f"  would --from {run_dir or '/tmp/six2'}")
        print(f"  would --gold {gold}")
        return 0

    off = _measure_arm(run_dir, gold, soft=False)
    on = _measure_arm(run_dir, gold, soft=True)
    print("=== 关闸（软闸=0＝改前）===")
    print(f"金标段所在源被标自动 zero＝{off['gold_in_auto_zero']}/{off['denom']}")
    print(f"自动 zero 信源＝{off['auto_zero_sources']}（18 题相加）")
    print(f"L2＝{off['l2']}/{off['denom']}")
    print(f"进箱＝{off['pack']}  非金标进箱＝{off['nongold']}")
    print(f"议题零重合＝{off['zero_overlap']}  s_match>0＝{off['sm_pos']}  "
          f"s_match==0＝{off['sm_zero']}")
    print("=== 开闸（软闸=1）===")
    print(f"金标段所在源被标自动 zero＝{on['gold_in_auto_zero']}/{on['denom']}")
    print(f"自动 zero 信源＝{on['auto_zero_sources']}（18 题相加）")
    print(f"L2＝{on['l2']}/{on['denom']}")
    print(f"进箱＝{on['pack']}  非金标进箱＝{on['nongold']}")
    print(f"议题零重合＝{on['zero_overlap']}  s_match>0＝{on['sm_pos']}  "
          f"s_match==0＝{on['sm_zero']}")
    print("=== 对照 ===")
    print(f"ΔL2＝{on['l2'] - off['l2']:+d}  Δ进箱＝{on['pack'] - off['pack']:+d}  "
          f"Δ非金标＝{on['nongold'] - off['nongold']:+d}")
    # 反向腿：关闸必须回到 15／180
    rev_ok = (off["gold_in_auto_zero"] == 15 and off["auto_zero_sources"] == 180)
    print(f"反向腿（关闸 15/180）＝{'OK' if rev_ok else 'FAIL'} "
          f"got {off['gold_in_auto_zero']}/{off['auto_zero_sources']}")

    if args.determinism:
        a = _measure_arm(run_dir, gold, soft=True)
        b = _measure_arm(run_dir, gold, soft=True)
        same = a == b
        print(f"确定性同码两遍＝{'OK' if same else 'FAIL'}")
        # 跨进程
        cmd = [sys.executable, str(Path(__file__).resolve()),
               "--from", str(run_dir), "--gold", str(gold)]
        env = dict(**{k: v for k, v in __import__("os").environ.items()})
        env["PYTHONPATH"] = str(_REPO)
        r = subprocess.run(cmd, capture_output=True, text=True, env=env,
                           cwd=str(_REPO))
        cross_ok = r.returncode == 0 and f"L2＝{on['l2']}/{on['denom']}" in r.stdout
        print(f"确定性跨进程＝{'OK' if cross_ok else 'FAIL'} rc={r.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
