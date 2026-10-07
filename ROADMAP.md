# ROADMAP — 21 天冲刺

评审权重：原型实测 70% + 方案答辩 30%。提交通道：智汇科学城小程序（方案 PPT + 方案文档 + 源码包；本轮交件不要求演示视频）。现场比赛另备讲解 PPT + 工作台实测。

## 第 1 周：最小闭环（D1–D7）

- [x] 基建搬运：`model_client` / `rate_limiter` 整文件移植 + `budget` / `connections` / `load_yaml_robust` 精简重写到 `app/llm/`（import 适配，独立于 token-burner）
- [x] `core/evidence.py`：Source / Segment / EvidenceNode / Conclusion 数据模型（含相关 vs 因果标注、证据等级字段）
- [x] `core/hashchain.py`：append-only 研判日志哈希链 + `verify_chain()`
- [x] `ingest/`：PDF / HTML / Markdown / TXT 切段入库（PDF 走 pypdf 可选依赖）
- [x] 引文核对器（零 LLM）：逐字引文必须在所指 Segment 中机械命中，不合格证据打回
- [x] 单分析师最小闭环：案例 → 报告 v0（JSON + MD + chain.jsonl）
- [x] tests 42 项全 stub 全绿 + deepseek-v4-flash 真实网关冒烟通过

## 第 2 周：多智能体与可信层（D8–D14）

- [x] ≥2 类分析师并行独立研判（硬隔离：提示词构造保证互不可见；3 视角编队；单点失败降级）
- [x] `core/conflicts.py`：冲突检测 → 质证辩论（轮数护栏=1、单侧失败降级）→ 仲裁（程序证据加权 + LLM 说理）→ 保留少数意见（败方 status=dissent 不删除）
- [x] `core/confidence.py`：三分量融合（强度×覆盖×跨智能体一致性）+ 人工修改后增量重算入口 `recompute_conclusion`
- [x] 报告 v1：结构化 JSON + Markdown 双出口（含分歧识别与消解、少数意见章节）

## 第 3 周：可视化与交付（D15–D21）

- [x] `server.py` + `web/`：证据图三级下钻、置信度分量面板、冲突清单视图、人工修改（删证据/改权重/改信源可信度）后重算并以 human 事件入链
- [x] 哈希链防篡改校验演示（工作台一键「篡改演示」：内存副本改一字即红，磁盘不动）
- [x] MCP 接口：分析师智能体暴露为标准工具（`app/mcp_server.py`：5 工具 = 3 零 LLM 只读 + run_analyst/run_judgment；mcp 1.x/2.x 双兼容；stdio 起真服务的协议级测试）
- [x] 科研情报案例打磨：正式案例素材扩容（新增案例二 `cases/bi-delivery-risk/`：企业情报·数据中台交付风险研判——6 份脱敏信源、10 种文类中精选 6 类、内置回款/延期/人员风险信号与真实仲裁冲突；离线桩双案例兜底；引文核对器排版宽容化 + 零证据结论出清）
- [x] 交件方案 PPT（`dist/veritas-交件方案.pptx`，脚本 `scripts/build_contest_pptx.py`）
- [x] 现场讲解 PPT（`dist/veritas-现场讲解.pptx`，对齐 demo-script 三动作）
- [x] 评测集三指标（`eval/benchmark.jsonl` + `scripts/run_eval.py` → BM25 Recall / 冲突召回 / 编造检出）
- [ ] 方案文档定稿 + 打包联调，小程序提交流程走通（U 盘自包含包已备，见 AGENTS.md）

## 待对齐（外部依赖）

- [ ] 榜单附件 / 需求方输入输出规范 / 验收口径拿到后校准
- [ ] 团队组队：榜单要求 2–5 人
- [ ] 比赛额度与模型 key 规则确认
