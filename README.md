# veritas — 多智能体可信研判与证据链溯源

> AI for Science · OPC 2026 杂交学科挑战创新挑战赛参赛软件
> 榜单：《多智能体可信研判与证据链溯源》（评审 = 原型实测 70% + 方案答辩 30%）

独立新写，不改动 token-burner 仓库；仅借鉴其多智能体编排、零 LLM 机械判分、工作台三套范式，并复制少量自有模型基建（清单见 ROADMAP 第 1 周）。

## 定位

输入多源异构资料（文献 PDF / 专利 / 新闻 / 网页 / 专家笔记），输出带完整证据链的结构化研判报告：

| 榜单硬需求 | 实现路径 |
|---|---|
| 多智能体协同研判 | ≥2 类不同视角分析师**独立研判**（互不可见对方结论）→ 辩论 → 仲裁 |
| 证据链自动构建 | 结论→证据→来源三级溯源，下钻至原文段落；引文逐字机械核对（零 LLM） |
| 结论置信度量化 | 信源可信度 × 证据数量与一致性 × 推理链完整性；分量可解释、可增量重算 |
| 冲突识别与消解 | 冲突清单 + 辩论/仲裁/证据加权消解，保留少数意见 |
| 推理轨迹可视化 | 证据图/推理树工作台，人工修改（删证据/改权重/改结论）后重算 |

加分项：相关 vs 因果区分与证据等级标注；研判日志哈希链防篡改；MCP 标准接口接入第三方智能体。

## 目录结构

```
veritas/
├── app/
│   ├── core/       # evidence 数据模型 / hashchain 防篡改 / confidence 融合 / conflicts 消解
│   ├── agents/     # 分析师（多视角独立研判）/ 仲裁者 / 辩论编排
│   ├── ingest/     # 多源摄取：pdf / html / md / txt / json → Source + Segment
│   ├── llm/        # 模型基建（自 token-burner 复制的自有代码，独立适配）
│   ├── pipeline.py # 端到端编排
│   ├── server.py   # FastAPI 可视化工作台
│   └── mcp_server.py # MCP 标准接口（研判能力暴露为智能体可调用工具）
├── web/            # 前端单页（证据图 / 推理树 / 置信度面板）
├── cases/          # 演示案例：固态电池科研情报 + 数据中台交付风险企业情报（信源已脱敏）
├── tests/          # 全 stub 测试，无 key 即全绿
├── scripts/        # 演示 / 评测 / 打包脚本
└── docs/           # 方案文档（答辩材料）
```

## 快速开始（macOS / Windows 通用）

**换机部署（U 盘携带、现场 Windows 机）**：看 [AGENTS.md](AGENTS.md)——
给 AI 智能体执行的分步部署指引（环境自检 → 一键脚本 → 零 key 验证 →
离线演示兜底 → 在线研判），配套 `setup-windows.bat` / `setup-mac.sh`。
打包：`bash scripts/make_usb_bundle.sh`（排除 `.venv`，现场重建）。

```bash
# 1) 环境（Python 3.9–3.12 均兼容；Windows 用 setup-windows.bat）
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt litellm   # litellm 仅真实调用需要

# 2) 网关配置：.env 放 OPENAI_API_KEY / OPENAI_BASE_URL（不进 git，模板 .env.example），
#    config.json 可覆盖模型清单（参考 config.example.json）

# 3) 跑一个研判案例（在线；案例二 bi-delivery-risk 为企业情报·交付风险研判）
.venv/bin/python -m app.pipeline cases/demo-solid-state

# 3b) 离线演示兜底（零网络零 key，全流程出产物）
.venv/bin/python scripts/demo_offline.py

# 3c) 可视化工作台（证据图下钻 / 人工修改重算 / 防篡改演示）
.venv/bin/python -m app.server --port 8765   # 浏览器开 http://127.0.0.1:8765/

# 3d) MCP 标准接口（可选：pip install mcp 后，智能体直连研判工具）
.venv/bin/python -m app.mcp_server           # stdio；list_cases/get_report/verify_chain/run_*

# 4) 测试（零 key 全绿；未装 mcp 时协议测试自动跳过）
.venv/bin/python -m pytest tests/ -q
```

演示案例 `cases/demo-solid-state` 已埋入乐观报告 / 怀疑笔记 / 新闻汇编三种
信源，manifest.yaml 里声明的 `type`/`credibility` 会参与置信度加权。
案例二 `cases/bi-delivery-risk`（数据中台交付风险研判）从企业内部文档
脱敏构建——6 份信源覆盖技术方案/账目/进度/人员等 6 类文类，内置真实
仲裁冲突与引文打回演示；构建脚本 `scripts/build_bi_case.py`。

## 路线图

见 [ROADMAP.md](ROADMAP.md) —— 21 天里程碑。第 1–3 周已全部落地：
最小闭环 → 多智能体协同与可信层 → 可视化工作台 + MCP 标准接口，
64 项测试全绿（零 key）+ 真实网关冒烟通过。
