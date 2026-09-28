# ROADMAP — 21 天冲刺

评审权重：原型实测 70% + 方案答辩 30%。提交通道：智汇科学城小程序（演示视频 ≤5min + 方案文档 + 源码包）。

## 第 1 周：最小闭环（D1–D7）

- [ ] 基建搬运：`model_client` / `budget` / `rate_limiter` / `model_ledger` / `load_yaml_robust` 从 token-burner 复制到 `app/llm/`，适配 import 独立于原仓库
- [ ] `core/evidence.py`：Source / Segment / EvidenceNode / Conclusion 数据模型（含相关 vs 因果标注、证据等级字段）
- [ ] `core/hashchain.py`：append-only 研判日志哈希链 + `verify_chain()`
- [ ] `ingest/`：PDF / HTML / Markdown / TXT 切段入库
- [ ] 引文核对器（零 LLM）：逐字引文必须在所指 Segment 中机械命中，不合格证据打回
- [ ] 单分析师最小闭环：案例 → 报告 v0
- [ ] tests 随写（全 stub，无 key 全绿）

## 第 2 周：多智能体与可信层（D8–D14）

- [ ] ≥2 类分析师并行独立研判（硬隔离：第一轮互不可见）
- [ ] `core/conflicts.py`：冲突检测 → 辩论（轮数护栏 + 循环检测）→ 仲裁（证据加权）→ 保留少数意见
- [ ] `core/confidence.py`：三分量置信度融合 + 人工修改后增量重算
- [ ] 报告 v1：结构化 JSON + Markdown 双出口

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
