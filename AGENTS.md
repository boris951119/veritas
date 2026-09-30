# AGENTS.md — veritas 现场环境部署指引（供 AI 智能体执行）

目标：在一台**没有开发环境**的电脑上（主场景 Windows 10/11，次场景
macOS/Linux），从零把 veritas 跑起来。按步骤执行，每步都有明确的
通过判据；失败按「故障排查」处理。本目录即仓库根（含 `app/`、`tests/`、
`requirements.txt`）。

## 第 0 步：环境自检

1. 找 Python（需 **3.10+**，3.12 最佳）：
   - Windows：依次尝试 `py -3 --version`、`python --version`；
   - macOS/Linux：`python3 --version`。
2. 都没有或版本 < 3.10：
   - Windows：`winget install Python.Python.3.12`（无 winget 则用
     安装包，装时勾选 *Add python.exe to PATH*），装完**重开终端**；
   - macOS：`brew install python@3.12`。
3. 建议把仓库放在**纯英文路径**下（如 `C:\veritas`），避免个别第三方
   库对非 ASCII 路径的兼容问题。

## 第 1 步：建环境装依赖

优先直接跑一键脚本（等价于下面的手工命令）：

- Windows：`setup-windows.bat`（双击或终端执行）
- macOS/Linux：`bash setup-mac.sh`

手工命令（与脚本等价，智能体可任选）：

```bat
:: Windows（cmd）
py -3 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -r requirements.txt litellm
```

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt litellm
```

网络慢或不通时，pip 命令追加国内镜像：
`-i https://pypi.tuna.tsinghua.edu.cn/simple`

**注意**：不要拷贝或迁移旧机器上的 `.venv/` 目录——venv 不可跨机移植，
必须现场重建。

## 第 2 步：验证安装（不需要任何 API key、不需要网络）

```bat
:: Windows
.venv\Scripts\python -m pytest tests -q
```

```bash
# macOS / Linux
.venv/bin/python -m pytest tests -q
```

**通过判据**：`240 passed`（或更多，零 failed；未装 mcp 时少 1 条属正常）。测试全 stub，无需密钥。

## 第 3 步：离线演示（断网/无 key 时的完整演示兜底）

```bat
:: Windows
.venv\Scripts\python scripts\demo_offline.py
```

**通过判据**：先后打印**两个案例**的完整研判报告（含多分析师归并、
冲突消解、少数意见、防篡改校验 ✅），产物分别写入
`cases/demo-solid-state/out_offline/`（固态电池科研情报）与
`cases/bi-delivery-risk/out_offline/`（数据中台交付风险企业情报，
各含 `report.json` / `report.md` / `chain.jsonl`）。桩客户端离线模拟了
三分析师协同全流程，演示「系统长什么样」足够用。

## 第 4 步：在线真实研判（需要 API key）

1. 复制 `.env.example` 为 `.env`，填入 `OPENAI_API_KEY` 与
   `OPENAI_BASE_URL`（key 向项目负责人索取，**不在仓库里、不在 U 盘
   明文里**）。可选 `config.json` 覆盖模型清单（参考 `config.example.json`）。
2. 运行：

```bat
:: Windows（案例一：固态电池科研情报）
.venv\Scripts\python -m app.pipeline cases\demo-solid-state

:: 案例二：数据中台交付风险企业情报（可选，工作台多一个案例可切）
.venv\Scripts\python -m app.pipeline cases\bi-delivery-risk
```

**通过判据**：打印真实研判报告，产物写入 `cases/<案例>/out/`；
`chain.jsonl` 为全程哈希链研判日志。案例二由
`scripts/build_bi_case.py` 从脱敏语料构建（机构名已匿名化，可直接对外演示）。

## 第 5 步：可视化工作台（演示主入口）

```bat
:: Windows
.venv\Scripts\python -m app.server --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`（默认只读本机）。工作台读取
`cases/*/out*/report.json`：证据链三级下钻（结论→逐字引文→原文段落）、
置信度分量面板、冲突消解与少数意见视图、信源可信度调整、删证据/改权重
即时重算、哈希链校验与「篡改演示（改一字即红）」。新增**机械核对警示**
面板（计算复算/数字溯源/计数/归并守恒/质证引用/议题前提，零 LLM 即时
重算——人工改结论引入未溯源数字会当场亮黄灯）与 **skill 注册表**状态
（触发才注入提示词，每条纪律配一道机械闸）。人工修改会以 human
事件追加进 chain.jsonl（修改可审计，链仍自洽）。若 8765 被占用换端口
即可；依赖 fastapi/uvicorn（已在 requirements.txt，一键脚本会装）。

## 第 6 步：MCP 标准接口（可选，接第三方智能体）

```bat
:: Windows
.venv\Scripts\python -m pip install mcp
.venv\Scripts\python -m app.mcp_server
```

以 MCP（Model Context Protocol）stdio 服务把研判能力暴露为 6 个标准
工具：`list_cases` / `get_report` / `verify_chain`（零 LLM，离线可验，
任何 MCP 客户端如 Claude/其他智能体可直连）+ `ingest_external`
（第三方结论按契约入卷并过引文机械闸，零 LLM）+ `run_analyst` /
`run_judgment`（发起真实研判，需第 4 步的网关配置；与 CLI 同一条
管线代码路径）。mcp 1.x/2.x 均兼容；不装 mcp 不影响前 5 步与测试。

## 故障排查

| 症状 | 处理 |
|---|---|
| pytest 中文报 `UnicodeEncodeError` / GBK | 用 `python -X utf8 -m pytest tests -q`；本仓库 IO 已全钉 UTF-8，该错只会来自第三方输出 |
| 控制台中文乱码 | `chcp 65001` 后重跑 |
| pip 装不上 litellm | 加镜像参数重试；仍失败可暂时跳过——`pytest` 与 `demo_offline` 不依赖 litellm（懒加载），仅第 4 步在线研判需要 |
| PDF 信源摄取报 pypdf 缺失 | `pip install pypdf`（PDF 是可选格式，demo 案例不含 PDF 不影响演示） |
| venv 激活后命令找不到 | 直接用绝对路径调 python：`.venv\Scripts\python`（Win）/ `.venv/bin/python`（Mac） |
| 测试出现 failed | 把失败摘要原样反馈给开发者；在修好前用第 3 步离线演示兜底（未装 mcp 时 MCP 协议测试自动跳过，240 passed ± 1 skipped 属正常） |

## 仓库速览（供智能体理解上下文）

- 入口：`python -m app.pipeline <case_dir>`；编排：`app/pipeline.py`
- 三级证据链与判分：`app/core/`（evidence / citation_check / confidence / conflicts / hashchain）
- 零 LLM 机械闸族：`app/core/audit.py` 汇总（numeric_check 计算/溯源/计数、
  discourse_check 质证/仲裁/措辞、premise_check 前提）；skill 注册表
  `app/core/skills.py`（触发才注入，无闸的 skill 不注册）
- 模型自适应：用户接什么模型未知——生产路径先 1 次探测给模型打
  「纪律遵从」档（`app/llm/profile.py`，机械判分），noncompliant 档
  自动改注强化规则 + derived 结构化契约并启用打回修复环
  （`app/agents/repair.py`，变好才接受）；VERITAS_PROBE=0 可关
- 输入生命周期：事实对撞台账（`app/core/fact_ledger.py`，信源数字
  打架机械检出，注入提示词+报告兜底）、时序核对（`app/core/
  temporal_check.py` 时效闸/as-of 闸，manifest 可声明 published_at）、
  相关性分层（`app/core/relevance.py`，零相关不进提示词但报告披露）
- 检索与预算：纯 Python BM25 段级精排（`app/core/bm25.py`）+ 跨信源
  轮转装箱（`app/core/material.py`，`material_char_budget` 默认 8 万字，
  装不下全披露）；ES/向量不进默认链（方案文档「规模化路径」）
- 复合输入：压缩包安全拆封（`app/ingest/archive.py`，zip-slip/炸弹/
  数量/嵌套四道边界，7z/rar 明确不支持并披露）；链接清单检测与显式
  抓取（`app/ingest/links.py`，默认只披露，`--fetch-links`/
  `VERITAS_FETCH_LINKS=1` 开启，结果缓存 `cases/*/.fetched/` 可离线
  重放）；子目录有界遍历；**输入分诊账本**（`app/ingest/triage.py`，
  每个文件一条路由记录，报告渲染）；图片 OCR 转码（`app/ingest/ocr.py`，
  网关视觉探测通过时逐字转写为低可信派生信源，VERITAS_OCR=0 关）；
  相关性人工裁决（`POST /api/source/relevance`，入链）
- 开发日志：`docs/dev-journal.md` ——全部批次的问题来源/方案决策/
  改动/验证/**已知开放问题**，供外部 AI 审查代码用（附攻击面清单）
- 智能体：`app/agents/`（panel 三视角编队、arbiter 归并/冲突/质证/仲裁、
  chair 主席汇总层——正面回答议题，四道闸+零 LLM 模板兜底、repair 修复环）
- 演示案例：`cases/demo-solid-state/`（固态电池科研情报）与
  `cases/bi-delivery-risk/`（数据中台交付风险企业情报，信源已脱敏；
  由 `scripts/build_bi_case.py` 从外部语料构建）；manifest.yaml 声明信源类型与可信度
- 路线图：`ROADMAP.md`；架构说明：`README.md`
