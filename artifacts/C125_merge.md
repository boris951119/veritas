# C-125 合 main 交账

- 结论：枝 `qoder/c125-test-tree-port` 已合入 main 并 push 成功；合并方式＝fast-forward，冲突＝无；`VERITAS_TEST_TREE_LINE` 合后仍默认关；旁证与枝上 YES 跑次逐位一致。

## 三笔 tip 与 push

- 基线 main：`0e957faa0952e6260c4f981d048d8ca785ec189a`（fetch 后与 origin/main 一致，无漂移）
- 枝 tip：`349156e59f41a51b9cf5ca214e29eb76cd862a03`
- 合后 main：`349156e59f41a51b9cf5ca214e29eb76cd862a03`（fast-forward，零冲突；40 文件、+10353 行，全部为 C-125 端口面）
- push：成功，`0e957fa..349156e main -> main`（未 force）
- 只合了这一枝；C-123／C-113／C-121／C-122／C-124 均未并入。

## 旗默认与关旗路径

- `Settings().test_tree_line`＝False、`Settings.from_env().test_tree_line`＝False（合后现场核）。
- 关旗 off-face 与合前跨树字节等证一致：kg_submit 面 sha16 `c6ff9d478007b287`、装箱 selected sha16 `be657d8db1e7dbde`、sel_n＝362、pack 额外参数＝空。关旗行为＝今日生产（预算＋BM25）。
- 整套测试：`7 failed, 1219 passed, 1 skipped`＝既有同 7 红基线＋C-125 十格全绿，无新红。

## 旁证（合后 main 现场复跑，六案门控）

- 刘翔（regression）@7＝12（期望 12）；微密度 57%≥57%。
- holdout：王虹 86%、柬泰 80%、AI171 80%（各≥2/3）；@7＝6/4/5。
- 金标→细读全 1.0；泄漏＝0；门槛①②③全 OK，READY=YES，异常＝（无）。
- 与枝上 YES 跑次逐位一致，唯一差异＝墙钟（387.6s→279.4s，暖缓存）。

## 更正记录（账记我）

- 第一遍合后复跑（主仓冷缓存）三案红：吉隆 44%、中美AI 33%、柬泰 43%，READY=NO。
- 定性＝运行时缓存缺席，非合并引入：端口线读数吃 gitignored 的 `.kg_lab_vault` 摘要缓存与 `.kgcache` 向量缓存；主仓冷起时 `build_corpus_rows` 读不到摘要，长段嵌入 blob 与 BM25 摘要面变样；且向量缓存按 para_id 复用、不校验文本，只补摘要不重嵌向量＝白跑。
- 处置＝把主仓缓存对齐到枝上 YES 跑次字节（摘要 vault 六案＋向量整份换；无摘要版向量缓存改名 `kg-index-nosummary-keep` 留档）后复跑，读数逐位回到枝上值。代码与量尺零改动。
- 教训＝跨树对照先对齐 gitignored 缓存字节，已入册。

## 产物索引

- 门控复跑（合后 main、缓存对齐）：`artifacts/c125/C125_six_case_gate.md`／`.json`（冷缓存第一遍存档在仓外 /tmp/c125/cold_run_red.md）
- 交账本件：`artifacts/C125_merge.md`／`.json`
