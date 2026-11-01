#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-82 打分侧：PyLate ColBERT MaxSim（须用 /tmp/venv_rerank，勿用主 .venv）。

默认模型＝jinaai/jina-colbert-v2（多语；六案中文可分）。
输入＝out_dir/score_input.json；输出＝out_dir/colbert_scores.json。

  HF_ENDPOINT=https://hf-mirror.com \\
    /tmp/venv_rerank/bin/python scripts/score_c82_colbert_pylate.py \\
        --out-dir /tmp/c82_colbert
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

CAP = 650  # 与 C-62 T 臂同形截断；只影响打分输入


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="/tmp/c82_colbert")
    ap.add_argument(
        "--model", default="jinaai/jina-colbert-v2",
        help="PyLate ColBERT 模型名",
    )
    ap.add_argument("--batch-size", type=int, default=8)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    inp_path = out_dir / "score_input.json"
    if not inp_path.is_file():
        raise SystemExit(f"缺 {inp_path}：先 probe_c82_colbert.py --prepare")

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    import torch
    from pylate import models, scores

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"加载 {args.model} device＝{device} …", flush=True)
    t0 = time.time()
    model = models.ColBERT(
        args.model, device=device, trust_remote_code=True)
    print(f"加载完成 {round(time.time() - t0, 1)}s", flush=True)

    inp = json.loads(inp_path.read_text(encoding="utf-8"))
    out: dict[str, list[float]] = {}
    t_all = time.time()
    for i, (key, row) in enumerate(inp.items(), 1):
        query = row["query"]
        texts = [(t or "")[:CAP] for t in row["texts"]]
        t1 = time.time()
        q_emb = model.encode(
            [query], is_query=True, batch_size=1, show_progress_bar=False)
        d_emb = model.encode(
            texts, is_query=False, batch_size=args.batch_size,
            show_progress_bar=False)
        qe = q_emb[0]
        sc: list[float] = []
        qt = torch.tensor(qe).unsqueeze(0).float()
        for di in d_emb:
            dt = torch.tensor(di).unsqueeze(0).float()
            s = scores.colbert_scores(qt, dt)
            sc.append(float(s.reshape(-1)[0]))
        out[key] = sc
        print(
            f"  [{i}/{len(inp)}] {key[:40]} n={len(texts)} "
            f"{round(time.time() - t1, 1)}s",
            flush=True,
        )

    out_path = out_dir / "colbert_scores.json"
    out_path.write_text(json.dumps(out), encoding="utf-8")
    meta = {
        "model": args.model,
        "device": device,
        "cap_chars": CAP,
        "n_questions": len(out),
        "elapsed_s": round(time.time() - t_all, 1),
    }
    (out_dir / "score_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"打分总墙钟＝{meta['elapsed_s']}s → {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
