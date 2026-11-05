# C-127 件① 缓存缺席只量（零 LLM）

- 结论：缺口复现——开旗路径暖／冷两臂 accounting 键集逐位同，**零**摘要／vault／cache 类披露键；`batch_summarize_case` 主仓无对等入口且实验版依赖已被摘的 `slices.union_pack_ids`，端口须带自含 universe 逻辑（scripts 侧）。
- 基线：HEAD＝`57e7687`（祖先含 `349156e`）✓；`Settings.test_tree_line`／from_env＝False/False（出厂关，未动）✓。
- 方法：旗开（env 只在探针进程内设 `VERITAS_TEST_TREE_LINE=1`）、刘翔案 q_001、`ensure_test_tree_submit(force=True)` 现场跑；冷臂＝把 `.kg_lab_vault` 整目录挪走（`.kgcache` 留＝C-125 冷缓存同场景），跑完即还原。

## 1) 缺席披露键现状

- 暖臂 `accounting["kg_test_tree"]` 键集（10 键）：close_read_n／embed／k／line／n_pairs／pool_n／route／rows_n／stage1_names／universe_n。
- 冷臂（vault 挪走）键集：**逐位相同**，零新增键；`embed` 仍报 `status=ok, n_vec=372`（向量缓存按 para_id 命中，摘要缺席完全不可见）。
- 顶层 accounting 含 miss/cold/cache/summary/vault/warm 字样的键：两臂均＝无。
- `build_test_tree_surface` 返回 dict 同样零披露（keys：box/close_read/density/embed/hints/k/n_pairs/pool_n/route/rows_n/stage1_names/surface/universe_n）。
- ＝与 C-126①判定一致：缺席＝静默（读数差异的实证在 C-125 冷缓存三案红，本单不复跑密度）。

## 2) 摘要建库脚本差集

- `app.kg_lab.summarize.summarize_paras`／`summary_path`：**在仓**（`app/kg_lab/summarize.py`，与实验仓字节一致）。
- 开旗热路径是否自动调 `summarize_paras`：**否**（grep app/ 全仓零调用；`kg_test_tree_line` 不 import summarize）＝只读暖缓存，符合预期。
- `batch_summarize_case`：实验仓 `scripts/kg_lab/batch_summarize_case.py` 有；主仓**无对等脚本／接线**。
- 端口注意：实验脚本 `from app.kg_lab.slices import union_pack_ids`——该函数在主仓已按金标隔离闸摘除（eval 侧）；端口版须把「读 conclusions.json 取议题＋pack 并集」逻辑自含在 scripts/ 侧（同 `scripts/probe_c125_six_case_gate.py` 的 `_questions_from_conclusions`/`_union_pack_ids` 法），`load_official_case` 用仓内 `app.ingest.official_case`。

## 3) 旗关默认路径旁证（引合后基线，只记表）

- 刘翔@7＝12（期望 12）；holdout＝王虹 86%／柬泰 80%／AI171 80%（各≥2/3）；金标→细读全 1.0；泄漏＝0；READY=YES（`artifacts/c125/C125_six_case_gate.md`，合后 main 缓存对齐复跑，墙钟 279.4s）。
- 本单未改尺、未复跑；件②改完后以同尺复跑对照。

## 4) 复现步骤（一句）

`mv .kg_lab_vault /tmp/aside && VERITAS_TEST_TREE_LINE=1 跑 build_test_tree_surface（刘翔）看 accounting["kg_test_tree"] 键集与暖臂逐位同、无缺席键，跑完 mv 回`（探针存 /tmp/c127/probe_cache.py，未入库）。
