# C-127 合 main 交账

- 结论：枝 `qoder/c127-cache-disclose-summarize` 已合入 main 并 push 成功；合并方式＝fast-forward，冲突＝无；`VERITAS_TEST_TREE_LINE` 合后仍默认关；cache 披露键与 `batch_summarize_case` 脚本确认在 main；旁证与枝上跑次逐位一致。

## 三笔 tip 与 push

- 基线 main：`57e768782e21d31871959ed3b44cfbff5a020895`（C-125 docs tip，祖先含 `349156e`）
- 枝 tip：`9881dbb5485eb1241c27b6d42b6505049d4edc90`
- 合后 main：`9881dbb5485eb1241c27b6d42b6505049d4edc90`（fast-forward，零冲突；8 文件 +493/−7，全部为 C-127 面）
- push：成功，`57e7687..9881dbb main -> main`（未 force）
- 只合了这一枝；C-123／C-113／C-121／C-122／C-124 均未并入。

## 旗默认与合后面

- `Settings().test_tree_line`＝False、`Settings.from_env().test_tree_line`＝False（合后现场核）。
- 披露键在位：`app/core/kg_test_tree_line.py` 含 cache 态计算与 `accounting["kg_test_tree"]["cache"]` 写账；建库脚本在位：`scripts/kg_lab/batch_summarize_case.py`（热路径零自动建库语义未变）。
- 关旗 off-face 与合前逐位同：kg_submit 面 sha16 `c6ff9d478007b287`、装箱 selected sha16 `be657d8db1e7dbde`、sel_n＝362、pack 额外参数＝空。
- 整套测试在枝上已量（同 commit）：7 failed／1224 passed／1 skipped＝既有同 7 红基线＋C-127 五格绿，无新红。

## 旁证（合后 main 现场复跑，六案门控暖缓存）

- 刘翔（regression）@7＝12（期望 12）；微密度 57%≥57%。
- holdout：王虹 86%、柬泰 80%、AI171 80%（各≥2/3）；@7＝6/4/5。
- 金标→细读全 1.0；泄漏＝0；门槛①②③全 OK，READY=YES，异常＝（无）。
- 与枝上跑次逐位一致，唯一差异＝墙钟（277.1s→276.7s）。

## 禁项核对

- `VERITAS_TEST_TREE_LINE` 未改默认开；未合 C-123／C-113／C-121／C-122／C-124；`case_slug="case"` 默认态未顺手修（另票）；无官方卷原文进产物；无 Markdown 表。

## 产物索引

- 旁证复跑：`artifacts/c125/C125_six_case_gate.md`／`.json`（合后 main 版，墙钟 276.7s）
- 件②交账（随枝入库）：`artifacts/C127_cache_disclose_summarize.md`／`.json`
- 件①只量：`artifacts/C127_cache_gap_measure.md`／`.json`（主仓工作树未 commit，/tmp 有备份）
- 交账本件：`artifacts/C127_merge.md`／`.json`
