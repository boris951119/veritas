# C-126 测试树全线对照遗漏核对（只读盘点）

- 结论：R44 交付链七项里六项「有」、KG 前端「部分」（跳边臂两仓都不在链上）；文件级零缺模块；真缺口 2 只（都在仪器面：摘要缓存缺席无披露、向量缓存不校验文本）。
- 基线：HEAD＝`57e7687`（含代码侧 `349156e`）✓。对照源＝实验仓已挂载（`/Users/liuboyu/Developer/veritas-obsidian-kg-exp`，非「实验仓未挂载」态）。旗只读：`VERITAS_TEST_TREE_LINE` 默认关未动。

## 逐项对照（0～6）

- **0) 切段／标签槽位＝有**。主仓路径：`app/core/kg_test_tree_line.py` L120/166-184 → `app/kg_lab/index_build.build_corpus_rows`（段级 doc#pN）＋`source_role._meta_from_row`（来源细类/角色）＋`case_lexicon`→`tag_schema`（主体 actors/aliases）＋`portable_tags`（渠道经 `channel_tier`；`has_time_nail` 时间钉 L151/181、`has_amount_nail` 数额 L152/182）＋`r8_fit._BASE_DIMS`（subject_match/claim_align/amount_status/time_anchor，L259 断言在码）。实验路径：同名同文件（除 slices/config 外字节一致）。依据：开旗函数逐只显式调用（L171-184），六案门控腿C 系数键数＝35 全在打分。
- **1) KG 召回前端＝部分**。主仓路径：`stage1_pool.fuse_r19`（kg_test_tree_line L159，`neighbor_window=1`）→ 邻块臂＋五臂混合 RRF（经典⊕视图⊕权威回应⊕R38 英核跨语⊕邻块，pool_ranked）。跳边（实体/因果一跳）：`recall_arms` 一跳函数＋`graph.load_adjacency`＝**有仓无路**——主仓零调用；实验侧也只有 `scripts/kg_lab/probe_r2b_q002_measure.py`（探针）调过，R44 链不走。`graph.py` 建库（entities/events/edges）只由实验 `batch_summarize_case.py` 跑。依据：grep 调用图＋fuse_r19 源码；与实验 R44 交付口径一致，非端口遗漏。
- **2) 问句 expand／paraphrase＝有（与实验同参）**。主仓路径：`index_build.keyword_expand_query`（top_n 缺省＝`query_expand.DEFAULT_EXPAND_TOP_N=16`，经典臂＋每视图臂都过）＋`rule_paraphrase_questions(n=DEFAULT_PARAPHRASE_N=1)` 进经典 RRF（每条改写出摘要＋嵌入两腿）；LLM 视图改写＝关（`use_llm_views=False`，与实验 R44 链同参）。依据：两常量字面量在 `app/kg_lab/query_expand.py` L59-60；fuse_r19 源码 `_fuse_rrf`/`_view_rankings`。
- **3) 一筛 stage1→pool＝有**。主仓路径：`fuse_r19` pool 序 → `multidim_weight.build_bundle` → `r8_fit.evaluate`（coeff＝仓内 `app/kg_lab/r9_coeff.json` R9 拟合 35 键＋`r21_coeff` 微移，`test_tree_coeff()` 同实验 `run_r22._coeff_names` 式）；出口只 ranked 序，`l2=[]` 零金标（L188）。依据：kg_test_tree_line L159-190；六案门控腿A 复现 R44。
- **4) 二筛 stage2→box＝有**。主仓路径：`stage2_authority.authority_rerank(density_cut=True, k_min=3, k_max=7)`（L199-208）→ `density_submit.density_constrained_submit` 可变 k∈[3,7]＋密度条；`build_conflict_pairs`（stage2 L120/371/381）；同引语簇并段（`inbox_rerank` L247 簇逻辑，stage2 经 `inbox_rerank` 传递）；交卷前显式 rank_order 进 surface。依据：stage2_authority 源码＋六案门控密度读数。
- **5) 交卷窄面＝有**。主仓路径：`layer_boundary.stage2_box_export`→`build_submit_surface`→`pack_hints_from_submit`；`audit_forbidden_keys` 两处＋泄漏即 raise（kg_test_tree_line L225-238）；接线证据＝`app/pipeline.py` L604-611：旗开→`ensure_test_tree_submit` 写 `accounting["kg_submit"]`→`apply_kg_submit_surface`→`pack_kwargs_for_kg` 读 `kg_pack_hints`→`pack_material(**_kg_pack_kw)`（priority/focus/max_segments；max_segments 默认不硬顶）；零系数＝`assert_clean_pack_kwargs`＋`assert_submit_no_coeff` 双闸。
- **6) 树17 引用层＝有**。主仓路径：`tree17_cite.apply_tree17_cite(box, metas, question, anchors, align_to_box=True, gold_ids=None, support_ids=None)`（L227-231，只读盒＋rank＋pairs；gold 只进量尺——本链两处 None）；`plan.close_read` 进 surface（L233）。依据：调用点＋门控腿B 金标→细读全 1.0（量尺侧）。

## 另两项

- **暖启动缓存依赖说明＝部分**。嵌入降级有披露：`embed.status="fallback_lexical"` 进 `kg_test_tree` accounting（kg_test_tree_line L140-149）。**摘要缓存缺席＝静默**：`summarize.load_summary` 返 None → rows 无 summary_text → 嵌入 blob（`_embed_pack` 长段吃 summary 前 200 字）与 BM25 摘要面同时变样，无披露键、无警告。现行说明只在：`app/kg_lab/config.py` docstring（gitignore 缓存根）、`artifacts/C125_merge.md` 更正记录（冷缓存三案红实证）。**向量缓存按 para_id 复用不校验文本**（`index_build.ensure_embeddings` L217-224：pid 在缓存即跳过）＝换摘要后不整份换缓存＝白跑。
- **模块清单＝文件级零缺**。实验仓 `app/kg_lab` 37 项全部在主仓（主仓 36 py＋数据件 `r9_coeff.json`，实验无此数据件）。内容差 3 处＝`__init__.py`／`config.py`（缓存根改 `.kg_lab_vault`/`.kgcache`）／`slices.py`（摘 4 只 eval 侧函数过金标隔离闸，`pack_selected_for_question` 保留且内部＝生产 `pack_material` 装箱面）。实验 `scripts/kg_lab` 57 只 runner＝eval 侧按设计不端口（门控由主仓 `scripts/probe_c125_six_case_gate.py` 承担）。

## 缺口表（下一刀输入；本单不修）

- **缺口1（半端口·仪器面·真缺口）**：摘要缓存缺席无披露键——`embed` 有 fallback 披露、summary 没有；冷缓存会静默改变嵌入 blob 与 BM25 摘要面（C-125 冷缓存三案红实证）。主仓无对应代码；实验同。
- **缺口2（仪器面·真缺口）**：向量缓存按 para_id 复用不校验文本——只补摘要不重嵌＝读数不更新的坑仍在 `ensure_embeddings`。
- **缺口3（口径澄清·两仓一致）**：跳边臂（实体/因果一跳＋graph 建库器）＝有仓无路——R44 交付链本就不含，开它属新实验票，不属端口遗漏。
- **缺口4（仅实验有·按设计）**：摘要建库器 `batch_summarize_case.py` 未端口——主仓无缓存自建能力，摘要缓存只能拷自实验仓（或下一刀决定是否端口＋钉重建协议）。
- **非缺口澄清**：六只拟合器模块（`eval_metrics`/`slice_dims`/`box_filter`/`opposition_patch`/`r14_stages`/`r15_stage2`）主仓零内部调用＝有仓无路，但实验侧也只被 R-runner（拟合/扫参）调用——拟合仪器留 eval 侧正是层边界要求（系数不出一筛），非遗漏。
- **仅文档有**：无（R42/R44 清单项都能指到码或调用图；未发现只在文档里出现的环节）。

## 方法与限制

- 以读码＋grep 调用图为主（pipeline L599-611、kg_test_tree_line 313 行全读、fuse_r19/_fuse_rrf/_view_rankings、stage2_authority、slices、ensure_embeddings）；开旗「走到」的证据＝显式调用点＋C-125 六案门控腿C 实跑（embed=ok、系数键数=35、密度读数），不是只看文件在仓。
- 本单零 LLM、零真跑、零代码改动；旗默认未动；未合任何枝。
