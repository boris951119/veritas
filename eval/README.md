# 评测资产说明（B3 / B4）

## B3 — 拓尔思对抗用例（零 LLM）

- 位置：桌面 `~/Desktop/veritas-testcases/`（56 案 × 8 考点）
- 跑法：`run_all.py` 指向本仓库 venv
- 测什么：摄取、机械闸、对撞、装箱、预检、PII…（不耗 key）
- 结果：此前已 **56 PASS / 0 FAIL**（约 0.3s）
- **测不了**：真模型冲突召回、置信度标定、主席汇总质量

## B4 — 上市语料真模型跑批

- 标注：`eval/questions.jsonl`（30 问，句子挖空 + ground 段）
- 语料：巨潮七家年报摘要/预告（仓库 `eval/corpus/`，桌面有同步副本）
- 跑法：
  - `scripts/run_eval_batch.py`（按公司合并议题，省额度）
  - `scripts/run_eval_batch.py --per-question --company 南山铝业`（逐问更准）
- 指标口径：
  - **M1** 证据链命中：ground 段被引用，或数值出现在引文中
  - **M2** 数字覆盖：数值进结论文案或引文
- **合并议题**（2026-10-10，FORCE_JUDGMENT + 挖坑问拼总议题）：七家 **M1/M2 = 30/30**
- **逐问**（`--per-question`）：更贴单问、更耗额度；成绩单与合并口径分列，勿混称
- 报告：`eval/report.md`（每次跑批覆盖写入）

## 选料召回抽检（真实语料，零 LLM）

- 题目：复用 `eval/questions.jsonl`（30 问）
- 语料：默认桌面全量库 `~/Desktop/veritas-testcases/eval-corpus`（可用
  `VERITAS_EVAL_CORPUS` / `--corpus` 覆盖）；按公司建磁盘索引缓存于
  `.tmp/recall_real_index/`
- 金标：指标词 + 答案值自动标 must-keep（弱数字须邻近共现；区分性短语收紧）
- 跑法：`.venv/bin/python scripts/run_recall_real.py`
- 量的是「must-keep 有没有进本次选料案卷」，不是模型答对不对
- 最新结果：`eval/recall_real_report.md`（2026-10-11：**30/30**，平均 Recall 100%）
- 合成金标仍见 `eval/recall_gold.py`（4 条可控边界，不替代本抽检）

## 语料 v2（全量公告 — 已完成）

- 主副本：桌面 `~/Desktop/veritas-testcases/eval-corpus/`（约 **2012** 文件 / 1.6G）
- 覆盖：A 股 8 家两年全量公告 + 恒兴新材 + AOSL SEC（10-K/10-Q/8-K）
- 清单：桌面 `MANIFEST.md`（窗口 `2023-10-01~2025-10-01`）
- 重建：`build_eval_corpus.py`（缺 `BASE` 已补；支持 `--migrate-only` / `--max N`）
- 仓库 `eval/corpus/` 仍只留 B4 启动包摘要；大 PDF 不入 git
- 已知缺口：中国银行 1 条 H 股公告 static 空包（150B）
