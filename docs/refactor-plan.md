# 重构方案：一个工具只做一件事 · 函数参数 ≤3

> 依据 2026-09-30 全库 AST 审计（参数 >3 的函数 21 个）+ 职责盘点。
> 铁律：**重构不改变行为**——240→244 基线测试不动、报告与链事件序列
> 不变；每项独立提交、独立可回滚。分级按「赛前风险」排序。

## 一、原则的落地口径（先定义，避免过度重构）

- **一个工具只做一件事**：「一件事」的粒度 = **主题**，不是函数行数。
  numeric_check 装四道数字闸（calc/provenance/counting/conservation）
  是一个主题——不拆；`render_segments_block` 是「装配分析师视野」这
  一件事——不拆。拆分只针对**一个函数里混了两个可独立变化的理由**。
- **参数 ≤3**：计位置参数 + 关键字参数；`self` 不计；`*args/**kwargs`
  转发不计。达标手段优先级：收进 dataclass（语义分组）> 提取模块级
  常量 > 拆函数。**禁止**为凑数把参数变成全局变量或传一个大而无当
  的 context dict（那是换汤不换药）。

## 二、审计结果（2026-09-30，AST 全量扫描）

参数 >3 共 18 个（self 不计；含 self 为 21）。按处置分四档：

### T0 赛前可做（纯签名收拢，零行为变化，合计约半天）

| 位置 | 现状 | 方案 |
|---|---|---|
| `pipeline.run_case`（9 参） | 注入点混杂：路径+桩+编队+案卷+开关 | 收进 `RunConfig` dataclass（settings/dossier/roster/probe/out_dir）；新签名 `run_case(case_dir, *, client=None, analysts=None, coordinator=None, cfg=None)`——4 参达标，测试注入面不变 |
| `repair.run_repair_round`（7 参） | ctx 散参 | 收 `RepairCtx(client, model, analysts)`；`max_repairs`/`render_segments_block` 已有默认值，保留关键字 |
| `ingest.case_loader.ingest_file`（7 参） | spec 逐字段展开 | 改 `ingest_file(path, source_id, spec: SourceSpec)`——spec 本就是 manifest 里的一等公民（type/credibility/title/published_at），顺手消灭 `_ingest_one` 的 4 参透传 |
| `discourse_check._check_refs`（6 参） | 定位字段拼盘 | 收 `RefContext(conclusion_id, conflict_id, side)`——三个定位字段本就是一个「位置」概念 |
| `ocr.transcribe_image`（4 参） | mime 有默认值 | 保留 4 参中 mime 为关键字默认即可？不——收 `(client, model, image: ImagePayload)`，ImagePayload 携带 bytes+mime，transcode 主流程与探测共用 |

### T1 赛后/有测试护栏再动（结构变化，行为面需快照对比）

| 位置 | 问题 | 方案 |
|---|---|---|
| `pipeline._run_collaboration`（6 参） | 编排参数一路透传 | 协同段收 `CollabContext(dossier, chain, analysts, coordinator, client, settings)`——它与 run_case 的 cfg 可共用一半字段 |
| `load_case` 的闭包嵌套（_triage/_process_file/_ingest_one/_handle_links） | 职责对但闭包共享状态多、难单测 | 类化 `CaseIngestor`（字段=dossier/manifest/counter），四个闭包变四个方法——对外 `load_case(case_dir, fetch_links)` 签名不变 |
| `archive.expand_archive` | zip/tar 两格式混在一个函数 | 拆 `expand_zip/expand_tar` + 共享 `_RejectLedger`（拒绝账本）——拒绝语义单点维护 |
| `mcp_server.ingest_external`（4 参） | MCP 工具签名受协议约束 | **不动**（对外接口，参数是契约；内部转发已薄） |

### T2 明确不拆（写明理由，防止未来误拆）

- `llm/model_client.py` 的 `__init__`/`chat`/`_call_with_retry`（7/4/5 参，self 不计）：
  自 token-burner 移植的基建，参数即网关全量旋钮；动它=动稳定层，
  收益低风险高。冻结。
- `hashchain.append`（5 参）：事件五元组是链的数据模型本身，收 dict
  反而失去显式性。冻结。
- `Source.create/EvidenceNode.create`（4 参）：keyword-only 的可选
  注入点，语义清晰。冻结。
- `server._mutate`（5 参）：骨架函数，五个参数各自必要。冻结。

### 顺带的职责盘点结论（无行动项，仅记录）

- `core/` 每模块一个主题（数字闸族/话语闸族/时序/相关性/检索/装箱/
  权限视图…）✅ 符合粒度口径；
- `agents/` 四角色（分析师/协调者/主席/修复）+提示词单一来源 ✅；
- 唯一灰区：`pipeline.py` 同时是编排器+报告渲染器（run_case 与
  render_report_md 同文件）——T1 顺手拆 `report.py` 出去，编排与
  渲染各自一件事。

## 三、执行序与验收

1. 每项一个 commit，消息前缀 `refactor:`；
2. 验收 = `pytest tests -q` 全绿（数量不降）**且** 离线演示产物
   `report.md`/`chain.jsonl` 与重构前逐字节一致（确定性管线做得到，
   这是「不改变行为」的硬判据——执行前先存基线产物）；
3. T0 全部完成后再评估 T1 是否进（赛前时间盒：T0 半天，T1 另需
   一天+快照对比脚本 `scripts/diff_artifacts.sh`）；
4. 审计脚本固化为 `scripts/audit_signatures.py`（本次一次性脚本转
   常驻），CI/本地随时重跑——参数超标在代码评审时自动可见。

## 四、不做清单（与原则冲突但刻意保留的，防止教条化）

- 不为参数达标引入「配置上帝对象」（一个 dict 传全场）；
- 不拆主题内聚的闸族文件；
- 不动 MCP 工具对外签名（协议契约）；
- 不动 llm/ 稳定层（移植代码，动它需要 token-burner 侧同步）。
