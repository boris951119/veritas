# ROADMAP — 21 天冲刺

评审权重：原型实测 70% + 方案答辩 30%。提交通道：智汇科学城小程序（演示视频 ≤5min + 方案文档 + 源码包）。

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

- [ ] `server.py` + `web/`：证据图三级下钻、置信度分量面板、冲突清单视图、人工修改重算
- [ ] 哈希链防篡改校验演示（改一字即红）
- [ ] MCP 接口：分析师智能体暴露为标准工具
- [ ] 科研情报案例打磨：15–30 份混合信源，**故意埋入冲突结论与低可信信源**（让冲突消解与置信度差异有戏可演）
- [ ] ≤5 分钟演示视频 + 方案文档
- [ ] 打包联调，小程序提交流程走通

## 待对齐（外部依赖）

- [ ] 榜单附件 / 需求方输入输出规范 / 验收口径拿到后校准
- [ ] 团队组队：榜单要求 2–5 人
- [ ] 比赛额度与模型 key 规则确认
