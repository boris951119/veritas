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
- 指标（2026-10-07 旧跑；产品侧已加强短议题装箱 / 数字入结论文 / 评分兜底，**需重跑刷新**）：
  - **M1** 证据链命中：ground 段被引用，或数值出现在引文中 → 旧 **60%（18/30）**
  - **M2** 数字覆盖：数值进结论文案或引文 → 旧 **43%（13/30）**
- 报告：`eval/report.md`
- 弱项（旧）：富恒新材 M1=0/5（议题过短 + 段落 ID 漂移）；居然之家/浪潮信息问数偏少

## 语料 v2（全量公告 — 已完成）

- 主副本：桌面 `~/Desktop/veritas-testcases/eval-corpus/`（约 **2012** 文件 / 1.6G）
- 覆盖：A 股 8 家两年全量公告 + 恒兴新材 + AOSL SEC（10-K/10-Q/8-K）
- 清单：桌面 `MANIFEST.md`（窗口 `2023-10-01~2025-10-01`）
- 重建：`build_eval_corpus.py`（缺 `BASE` 已补；支持 `--migrate-only` / `--max N`）
- 仓库 `eval/corpus/` 仍只留 B4 启动包摘要；大 PDF 不入 git
- 已知缺口：中国银行 1 条 H 股公告 static 空包（150B）
