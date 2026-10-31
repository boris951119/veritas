# Obsidian KG hybrid recall spike

实验树：`/Users/liuboyu/Developer/veritas-obsidian-kg-exp`（分支 `exp/obsidian-kg`）。  
**禁止改主仓**；默认关；不 commit／不 push／不合入，除非另拍。

## 管道

1. `app/kg_lab/slices.py` — 箱内段 → `vaults/kg-lab/slices/{slug}/{doc}__{para}.md`
2. `summarize.py` — 本机 Ollama（`veritas-qwen3-14b`, `think=false`）→ `vaults/kg-lab/summaries/`
3. `graph.py` — Entity／Event 笔记 + `causes|enables|contradicts` + `adjacency.json`
4. `index_build.py` — 原文／摘要 BM25 + `bge-m3` embedding → `artifacts/kg-index/`
5. `recall_arms.py` — 五臂 + oracle 对照
6. `probe_kg_spike_recall.py` → `/tmp/kg_spike_recall/`

召回宇宙＝`pack_material` 已进箱段（对齐 C-104）。金标 id／quote 禁止进查询／排序特征。

## 跑

```bash
cd /Users/liuboyu/Developer/veritas-obsidian-kg-exp
PYTHONPATH=. .venv/bin/python -u scripts/kg_lab/probe_kg_spike_recall.py \
  --case-filter 刘翔 --out-dir /tmp/kg_spike_recall --workers 2

# 六案（摘要墙钟大）：
# ... --case-filter '' 
```

样例只读软链：`data/trs-samples` → `~/Desktop/veritas-testcases/样例集-拓尔思-20261012/`。
