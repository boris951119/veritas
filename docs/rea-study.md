# REA（morluto/rea）源码研读：veritas 值得吸取的优点

日期：2026-10-13 　性质：外部竞品研读，**未改动任何生产代码**
本地副本：`~/Developer/rea`（shallow clone，54.8 MB，非本仓库内容，不入库）
核实方式：所有 REA 侧结论均由我本人 `sed`/`grep` 复核过原文，标注 `文件:行号`；
子 Agent 的转述若未经复核不写入本文。

---

## 0. 一句话结论

REA 和 veritas 解的是同一道题——**如何让模型产出的每个结论都可追责、可复核、
且不许把猜测当事实**。它在"把状态钉成类型、把未完成钉成失败"这两件事上做得比
我们硬；我们在"不可信内容双层围栏"和"无闸不注册"上做得比它硬。
最值得搬的是三条：**证据自认证 ID**、**coverage 三态的类型级不可构造**、
**义务台账的 fail-closed 判分**。

---

## 1. REA 侧：已核实的事实

### 1.1 证据记录是一条 strict 类型，多一个字段就拒收

`src/domain/evidence.ts:113-132`（`.strict()` 在 132 行）：

| 字段 | 约束 | 对 veritas 的含义 |
|---|---|---|
| `evidence_id` | `ev_` + 64 位 hex **语义摘要**，非随机 | 见 §3-P0-1 |
| `subject` | nullable，含 sha256 / format / architecture | 证据指向的文件身份 |
| `analysis_profile` | **必填**、可为 `null`，且参与语义身份 | "用什么配置得出的"进 ID |
| `raw_result` | nullable，provider 原始输出 | 与规范化结果分离 |
| `confidence` | 枚举 `observed` / `derived` / `inferred` | **结论怎么来的** |
| `authority` | 枚举 `shipped-artifact` / `controlled-replay` / `historical-reference` / `external-service` / `analyst-inference` | **证据够不够格** |
| `limitations` | 字符串数组 | 每条证据自带局限 |
| `relationship_coverage` | 三态判别联合，默认 `null` | 见 §3-P0-2 |
| `evidence_links` | `ev_` 摘要数组 | 证据间引用成图 |

`parseEvidence` 会**重算摘要并拒绝**（`evidence.ts:161-171, 269-276`），
profile 与 provider 不一致单独报错（`135-154`）。
文档层再补一刀：记录里出现未支持字段"先于认证被拒绝"
（`docs/mcp-contracts.md:16-19`），实现是 zod strictObject，
`parseBundle` 先 `.parse` 后 `authenticateBundle`（`src/domain/evidenceBundle.ts:251-271`）。

### 1.2 非法状态**构造不出来**，而不是靠测试拦

`src/domain/relationshipCoverage.ts:1-22`（全文 22 行，已逐行读）：

```ts
const completeCoverage = z.strictObject({ status: z.literal("complete") });
const partialCoverage  = z.strictObject({ status: z.literal("partial"),
                                          limitations: z.array(...).min(1) });
const unknownCoverage  = z.strictObject({ status: z.literal("unknown"),
                                          reason: z.string().min(1) });
```

要点：**"部分覆盖"必须至少带一条 limitations，"未知"必须带 reason**，
否则对象根本造不出来。这是类型级约束，不是约定，也不是 lint。

配套的语义规则（`docs/mcp-contracts.md:39-49`、`docs/tool-design.md:55-56`）：

> "An empty call list with partial or unknown coverage is **not proof** that
> the function has no calls."
> "Missing coverage is unknown, not absence."

遍历层同样区分（`src/application/CallPathTracing.ts:243-250`）：
有未解析的边 → `goal_status: unknown`；穷尽才 → `not_reached`。
**"我没找到"和"它不存在"是两个不同的返回值。**

### 1.3 义务台账：没做完会被机器判成 open，不会混成"完成"

`docs/reconstruction-obligation-ledgers.md:1-20`（原文已读）——
`build_reconstruction_obligation_ledger` 把已认证的 Evidence 确定性地收成
一份重建义务清单，闭合条件极其保守：

> "A required obligation closes only when one manifest binding supplies a
> unique owner, any required parser/schema/domain type, every required case
> fixture, and a passing verifier **whose authority is comparable to the
> original observation**."
> "Contradictions, duplicate definitions or owners, residual unknowns, missing
> dependencies, and unavailable authority keep closure open or failed."

一个空请求返回的是 **`unknown` 台账**，不是"没活儿干"：
"absence of source Evidence never claims closure"（同文件 22-25 行段）。
绿色单测关不掉打包进程义务（同文件 317-321 行段）。

就绪度聚合十条 fail-closed 规则（`docs/reconstruction-readiness.md:47-69`）：
**`fail` / `unknown` / `unsupported` / `truncated` / `skipped` 永不聚合为 `pass`**。

### 1.4 残余未知是有生命周期的账，不是文案

`src/domain/residualUnknown.ts:81-121`：status 五态
（`open` / `investigating` / `blocked` / `contradicted` / `resolved`），
每条未知声明 `required_authority` / `required_confidence` / `required_environment`
（即"要什么级别的证据才能把它关掉"），带修订摘要链（145-150），
**`resolved` 必须挂合格证据**（151-165，`evidenceBundle.ts` 的
`validateVerifiedResolution` 在导入时校验，断链/悬空引用/无合格证据均报错）。

### 1.5 已知答案评分器：零 LLM、fail-closed，而且**它自己也有一组必须失败的测试**

`src/evaluation/KnownAnswerEvaluation.ts`：
- 期望值是 `FixtureClaimExpectation`：期望值 + 来源绑定
  （operation / confidence / authority / subject sha256 / 参数选择器），
  `tests/evaluation/model-evals/knownAnswerEvaluation.test.ts:69-83`；
- 结论缺期望 → `claim_missing` 失败（`:403`）；全部 passed 才 passed（`:500-502`）；
- **rubric 为空或重复 → 评分器直接失败**（`KnownAnswerEvaluation.ts:459-464`
  `invalid_fixture_rubric`）；
- 反幻觉负例（全部期望 failed）：编造文字、多余字段、外层散文、缺 authority、
  2 万层嵌套 JSON、**confidence/authority 越级夸大**、证据信封被篡改
  （`knownAnswerEvaluation.test.ts:113-238, 270-283, 377-383`）。

注意分层口径（`docs/testing.md:190-232`）：`tests/evaluation/` **只测打分器自身的
确定性逻辑**，真实模型试验是手动车道；注入 provider 的 acceptance 只算集成，
"测试通过 ≠ 真实 provider 行为成立"（`:226-228`）。

### 1.6 把隐性纪律钉成正则 + 审计白名单

`scripts/verify/architecture-guards.mjs`（136 行，已逐行读）对 `src/` 全部非测试
`.ts` 去注释后跑 5 条检查，违规 exit 1。头注释写明**每条规则背后都是一个真实
bug 类**：

1. `src/domain/` 禁 `localeCompare`（ICU 随宿主变，须用 `compareUnicodeCodePoints`）；
2. 全局禁 `.join("\0")` 做变长字段拼 key（`["a\0b"]` 与 `["a","b"]` 碰撞会**丢一条发现**），
   白名单 1 个文件且带书面理由；
3. TS 包装节点 unwrap 只许发生在 `javascriptAstValues.ts` 一处（`satisfies` 类漂移 bug）；
4. AST 遍历禁碰 `VISITOR_KEYS`（须走统一 traverse，防深链爆栈）；
5. 新增反引号-NUL key 必须扩展审计白名单并注明理由（审计日期 2026-10-10 写在码注释里）。

配套 `verify:module-boundaries`，`.oxlintrc.json` 按目录禁 import
（application 测试禁引 server/cli，composition 测试禁 child_process/net）。

### 1.7 卫生阈值与 CI 车道分级

- `.jscpd.json:2` 重复率阈值 **3.0%**（minLines 5 / minTokens 50，扫 src+tests）；
- `knip.json` 十条规则全 `error`（未用依赖、未用导出、幽灵依赖即红）；
- `.oxlintrc.json`：complexity ≤ 20、max-depth 4、max-lines 500、函数 100 行、max-params 4；
- 20 个 `real-*.yml` 真实工具车道**不在每个 PR 跑**，由 `scripts/ci/plan.mjs` +
  `scopes.mjs` 按 diff 文件所有权触发（`ci.yml:39-75`），付费工具车道仅 provider
  文件变更或手动自托管触发（`docs/testing.md:736-738`）；
- fixture 三策略：CI 现场编译（Go 1.26.1，期望值对照编译器 oracle）、
  **按 release + SHA-256 钉死拉取**（Wakaru 1.14.0，`real-javascript-recovery.yml:31-37`）、
  显式脚本拉公开 APK 存 ignored 目录；
- `required` 聚合作业用 `scripts/ci/required.mjs` 拒绝 failed / cancelled /
  **意外 skipped**（`ci.yml:658-698`）；
- 契约漂移防护：`metadata:check` / `mcp-catalog:check` / `mcp-registry:check` /
  `docs:check:built` 全部是"重生成再比对，不一致非零退出"，
  docs 作业后跑 `git diff --exit-code`（`package.json:98-101,240`、`ci.yml:587-588`）。

### 1.8 提示词纪律（原文摘录，对我们的主席/仲裁层有用）

- `SKILL.md:221-225`：Every conclusion must distinguish observations, inferences,
  and unknowns. Cite Evidence IDs … never imply that static analysis observed
  execution.（**静态分析不得谎称观测到执行**）
- `references/native-and-artifacts.md:73-75`：Addresses and recovered pseudocode
  are analysis observations, not original source.
- `references/evidence-workflows.md:18-20`：a missing match in partial source
  Evidence does not establish absence.
- `references/javascript-applications.md:95-96`：An absent item fact is not
  evidence of absence.
- `docs/mcp-prompts.md:98`：An empty completion list does not establish that the
  target has no procedures.
- `references/evidence-workflows.md:44-49`：static differences remain candidates,
  not causal proof … **A pass covers only declared comparable claims, not global
  equivalence.**（通过只覆盖"已声明的可比断言"，不是全局等价——这句直接对应
  我们"stub 全绿≠质量没退化"）
- `SKILL.md:262-265`：do not describe a broad investigation as complete while
  required questions remain open.
- `SKILL.md:163-167`：Never choose an example app on the user's behalf.
  （**不许替用户挑样本**——这条是我们的用例集该照抄的纪律）

### 1.9 skill 是"手写正文 + 代码生成事实元数据 + CI 比对"

`package.json:276` `artifacts:skills` → `scripts/generate-skill-metadata.mjs`：
源在 `.agents/skills/**`（人手写），发布产物在 `skills/**`（生成）；脚本把
`tool_count`（来自 catalog 身份）和把 `@latest` **钉成固定发布版本**注入正文，
手写源里若自己写了 `tool_count`/`catalog_digest` 直接报错
（`generate-skill-metadata.mjs:26-29, 39, 61-67`）。
即：**提示词被当成可校验产物**，但这是**构建期一致性闸**，
不是 veritas 的**运行期模型输出闸**——定位不同，别混为一谈。

---

## 2. veritas 现状：已核对，别自己吓自己

| 能力 | REA 做法 | veritas 现状 | 判定 |
|---|---|---|---|
| 不可信输入 | `_meta.provenance.untrusted_content` 打标（`mcp-contracts.md:123`） | `app/core/untrusted.py`：注入特征扫描（中英双语）+ 围栏 + **二阶围栏**（分析师产出回流也包边界） | **我们更强** |
| 纪律↔闸配对 | 靠文档与 CI 一致性 | `app/core/skills.py:24-28` `KNOWN_GATES` 九闸 + "无闸不注册" | **我们更强** |
| 未覆盖显影 | coverage 三态**类型级强制** | `app/core/coverage_gap.py` 报未引用段落 + 复合子问三态（展示层） | **形态在，强制力缺** |
| 证据身份 | `ev_` + 语义摘要，parse 即验 | `_new_id("EV")` 随机；防篡改靠 `chain.jsonl` 整链哈希 | **缺单条自认证** |
| 结论怎么来的 | `confidence` observed/derived/inferred + `authority` 五档 | `EvidenceNode.level` A–D 是**信源可信度**，`relation` 是关系类型 | **缺一根正交轴** |
| 未完成判分 | 义务台账 + 就绪度十条 fail-closed | 报告文案披露"库内 N / 纳入 M""未入选≠审完全库" | **是文案，不是机器态** |
| 未知闭环 | `residual_unknown` 五态 + 解决需合格证据 | 有"少数意见"展示，无带证据门控的未知账 | **缺** |
| 输出预算 | 超预算返 `resource_constraint` + 可执行 continuation | `material_char_budget` 只管**输入**装箱 | **缺** |
| 评分器自测 | 一整族 must-fail 负例（编造/越级/篡改/空 rubric） | `tests/test_score_artifacts.py` 已有 3 条 must-light（`warrant_flags==1`、`no_answer`、`mech_groups is None` 不得瞎猜 0） | **已有雏形，缺的是负例种类** |
| 状态不可坍缩 | `skipped/unknown/truncated` 永不聚合为 `pass` | `audit*.py` 中**无** skipped/not_applicable 语义（grep 零命中）：不进场 = 零 flag = 看起来像通过 | **缺，且是 fail-open 实漏** |
| 架构守卫 | 5 条正则 + 审计白名单 | 无 | **缺，且便宜** |
| 慢车道隔离 | diff 所有权触发 real-* | 无 CI（本地开发） | **缺，14B 场景刚需** |

---

## 3. 吸取清单（按性价比排序，成本 = 单人净工时）

### P0-1 证据自认证 ID（内容寻址）｜约 2 小时｜零运行成本

REA：`evidence_id = "ev_" + canonical_digest(除 id 外语义投影)`，
`parseEvidence` 重算并拒绝（`evidence.ts:237-276`）。
搬法：`EvidenceNode` 增加 `fingerprint`（对 quote + segment_ids + level + relation +
author 的规范化摘要），`from_dict` 时重算比对，不符即抛；`chain.jsonl` 保留整链。
收益：现在改 `report.json` 里一条证据的文字，整条链还能通过局部校验；
有了自认证 ID，**摘出单条证据也能独立验真**，MCP `ingest_external` 的第三方
证据也立刻有了身份。
成功判据：新增一条测试——改一个字节 → 该证据 fingerprint 校验必须红；
全库重放 → 存量案例 fingerprint 全绿。

### P0-2 coverage 三态钉成类型（"部分"必带局限、"未知"必带理由）｜约 4 小时｜零运行成本

REA：`relationshipCoverage.ts:1-22`，造不出非法状态。
搬法：给 `Conclusion` 加 `coverage`（frozen dataclass 或 pydantic）：
`complete` / `partial(limitations: 非空)` / `unknown(reason: 非空)`，
构造即校验；`partial` 且 limitations 为空 → **TypeError，不是 warning**。
再把"报告出现 全部/所有/不存在/没有 且 coverage≠complete"升级成
`discourse_check` 里的一道措辞闸（黄灯）。
收益：直接打在产品判决里那条"开放题早退报废"的痛点上——早退从此在数据结构
层就要留痕，模型想含混收场也没有无痛的路径。
成功判据：用 `python -c` 构造 `partial(limitations=[])` 必须抛；
一条 stub 测试让模型输出"所有信源都表明…"且 coverage=partial → 闸亮黄。

### P0-3 补齐评分器的 must-fail 负例族｜约 2 小时｜零运行成本

**更正记录**：本文初稿写"未见判分器自身的负例族"，不准确。
`tests/test_score_artifacts.py`（107 行）已有三条 must-light 断言：
`warrant_flags == 1`（理由与主张脱节必须亮）、`no_answer is True`（零结论必须判产品级失败）、
`mech_groups is None` 且注释明写"旧产物没这字段，**不得瞎猜 0**"
（`tests/test_score_artifacts.py:56-60, 66-70`）——最后这条正是 REA 的 fail-closed 思路，
我们已有雏形。所以差距是**负例种类**，不是"尺子没量过"。

REA 多出来的是种类覆盖：`src/evaluation/KnownAnswerEvaluation.ts:459-464`
让 **rubric 为空或重复时评分器自身失败**（`invalid_fixture_rubric`），
外加一整族**期望失败**的输入：编造文字、外层套散文、缺 authority、2 万层嵌套 JSON、
**confidence/authority 越级夸大**、证据信封被改一字
（`knownAnswerEvaluation.test.ts:113-238, 270-283, 377-383`）。
族的意义：**把评分器改坏一点，CI 立刻红**；现有三条断言覆盖不到这个场景
（例如把 `conf_median` 的比较方向写反，测不出来）。

搬法：造 5 份故意做错的 `report.json` —— ①引文在原文里根本不存在 ②结论声称
"所有信源"但 `cited_share` 只有 6% ③逐字改一个字节 ④期望表为空/重复
⑤低可信信源却标 A 级——断言评分器逐条必须判红。
成功判据：负例族进 pytest；手工把评分器某处比较改成 `>=`，测试必须变红。

### P0-4 让"闸没跑成"不再等于"通过"（不进场必须留痕）｜约 3 小时｜零运行成本

**这是本次研读在我们自己代码里挖出的实漏，比 REA 的任何一条都优先。**
两条已核实的证据：

1. `app/core/numeric_check.py:275-281` 计数闸的注释自陈"**只核 skill 教的显式
   「计数:M/N」格式**"——模型不写这个格式，这道闸一条都不跑，输出零 flag。
2. `grep -n "skip|not_applicable|无法核对|degraded"` 在 `audit.py`、
   `citation_check.py`、`numeric_check.py` 中**零命中**：闸只有"亮灯/没亮"两种输出，
   没有第三种"本闸因缺字段未能执行"。

合起来的后果：免检与通过坍缩成同一个状态，`score_artifacts` 的
`flags_high=0 / flags_medium=0` 在两种情况下长得一模一样。REA 明令禁止这种聚合
（`docs/reconstruction-readiness.md:47-69`：`fail/unknown/unsupported/truncated/skipped`
**永不聚合为 `pass`**，其中 `skipped` 被单独列出来正是因为它最容易混成通过）。

搬法：给 `audit_all` 的返回加一栏 `not_evaluated`（kind + 未执行原因 + 命中的结论/段落数），
`summarize` 与 `score_artifacts` 各加 `flags_not_evaluated` 计数，报告与工作台显影成
"以下核对本次未能执行"；措辞纪律补一条——**全称量词（全部/所有/均/无一）必须与
coverage=complete 配对**，否则走新措辞闸亮黄（接 P0-2）。
成功判据：一份故意不含任何 `计数:M/N` 格式的产物 → `not_evaluated` 必须包含 `counting`，
且 `flags_not_evaluated > 0` 时评分器不得给出"零警示"结论。

### P1-4 议题义务台账（fail-closed，把"未做完全库"变成机器态）｜1–1.5 天｜零运行成本

REA：`reconstruction-obligation-ledgers.md:10-18`，空输入返回 `unknown` 而非完成；
就绪度 `fail/unknown/unsupported/truncated/skipped` 永不聚合为 `pass`
（`reconstruction-readiness.md:47-69`）。
搬法：新增 `app/core/obligation_ledger.py`——按议题 × 子问生成义务清单
（每条 = 议题项 + 需要的最低证据等级 + 状态），状态枚举含
`open / unmet_authority / contradicted / no_material / covered`；
主席汇总前跑一遍，**存在 open ⇒ 报告头部与工作台亮"本案未闭合 N 项 + 原因"**，
且 `score_artifacts` 把"未闭合数"当成一等分数。
收益：把现在写在报告文案里的"未入选不等于已审完全库"升级成机器可判、
可回归、可对比的分数；这也是编队零会签痛点的第二只眼（义务没人认领 = unowned）。
成功判据：故意抽掉某议题的唯一 A 级信源重放 → 该义务必须落 `no_material`，
报告未闭合计数 +1，且总分下降。

### P1-5 架构守卫：把我们的隐性规矩钉成正则 + 白名单｜约 1.5 小时｜纯文本扫描，零成本

REA 的每条规则背后都是一个真实 bug 类（`architecture-guards.mjs` 头注释 1-17 行）。
我们的等价规矩（建议先三条，逐条注明"为什么"）：
- `app/core/**` 禁 import litellm/openai → 保"零 LLM 可离线重放"这条命根子；
- 只有 `app/core/hashchain.py` 允许写 `chain.jsonl` → 防旁路写链破坏可审计性；
- `app/core/**` 禁用 `datetime.now()` / `random.random()` 之类不确定源 →
  机械闸必须可复现（这条对我们复放打分器是直接收益）。
落地：`scripts/verify_architecture_guards.py` + `tests/test_architecture_guards.py`，
白名单需带注释理由（照 REA 的写法）。
成功判据：在 `app/core/audit.py` 临时加一行 `import litellm` → pytest 必须红。

### P1-6 未知台账（带证据门控的闭环）｜约 1 天｜零运行成本

REA：`residualUnknown.ts:81-121`，每条未知声明"要什么级别的证据才能关掉我"，
`resolved` 必须挂合格证据，导入时校验断链（`evidenceBundle.ts` 300-420 段）。
搬法：`app/core/open_questions.py`，status `open/investigating/blocked/
contradicted/resolved` + `required_level`；主席回答议题前必须消费一遍，
未 resolved 的进报告"待核清单"；**resolved 但没有合格证据支撑 → 黄灯**。
成功判据：一条测试——把 open 问题直接标 resolved 且无新证据 → 闸亮灯。

### P2-7 confidence / authority 双正交轴（别和 A–D 混）｜约 4 小时

REA 把"证据是怎么来的"（observed/derived/inferred）和"证据够不够格"
（shipped-artifact/…/analyst-inference）与信源可信度**分开三根轴**。
veritas 现在只有 `level`（A–D，信源侧）+ `relation`。
搬法：`EvidenceNode` 加 `derivation ∈ {quoted, computed, inferred}`——
`quoted` 才许逐字命中闸；`computed` 走 `numeric_check` 复算；`inferred` 必须
降权并进措辞闸（"推断"字样不许伪装成事实）。
收益：置信度分量面板多一根真正有解释力的轴，且和现有九道闸天然对齐。

### P2-8 输出侧预算与续读引用｜约 1 天

REA：超 10 MiB 帧预算时返回 `resource_constraint(details.resource:"transport")`
+ `evidence_reference` + **预填好的可执行 continuation 请求**
（`mcp-contracts.md:51-71`、`src/server/toolResult.ts:53`）。
veritas 只有输入装箱。搬法：MCP `get_report` 加"摘要 + 证据 ID 引用 +
按需 `inspect_evidence(ids)`"的两段式，避免大案卷一次撑爆调用方上下文。
收益：对比赛演示（第三方 Agent 直连）是实打实的可用性提升。

### P2-9 慢车道隔离（为本地 14B 设计）｜约 0.5 天

REA：`scripts/ci/plan.mjs` 按 diff 文件所有权决定触发哪些 `real-*` 车道，
`required` 聚合拒绝意外 skipped（`ci.yml:39-75, 658-698`）。
veritas 对应：把命令分成 **门禁层**（零 LLM：pytest + 评分器 + 架构闸，秒级）
和 **真实层**（14B，14 tok/s，只在改 prompt/agent/闸阈值时手动跑，
且用例输入按 SHA-256 钉死可离线重放）。
收益：直接回答"加质量闸会不会拖慢开发循环"——不会，慢的都隔离在门禁外。

---

## 4. 明确不搬的三条（避免迷信外部项目）

1. **不搬它的整套 Evidence/Bundle/信封序列化体系。** 那是为"第三方工具产物入卷 +
   跨会话传输 + 认证"设计的，我们的对手盘是案卷与提示词，不是多 provider 二进制证据。
   照搬会把 `evidence.py` 撑成不可维护的大对象——`jscpd` 3% 阈值那种一刀切也是。
2. **不学它的 skill 加载机制。** REA 的 SKILL.md 靠 LLM 读 description 自判 +
   Markdown 链接软跳转（`SKILL.md:1-6, 29, 267-278`），是**软约束**；
   我们的 `skills.py` 是程序化触发 + 配闸硬约束，这一点上我们是更强的那一方。
   只借它的**纪律措辞**（§1.8），不借它的**加载机制**。
3. **不追求 729 个测试文件这个数字。** 我们的问题从来不是测试不够多，
   而是"测试全绿"与"答案质量"之间缺一条可回归的链路。P0-3 + P1-4 才是补这条链，
   加测试数量是无效功。

---

## 5. 研读过程中顺手拿到的一个实锤

派去读 REA 的子 Agent 报告"工具输出里混入了伪装成用户新指令的劫持文本，
要求注册 MCP、写配置"，它拒绝执行并继续原任务。我复核了仓库：
`grep` 全库无任何 `ignore previous instructions` / 伪装指令，命中的全是
`per**ssi**on`、instruc**ti ons** 这类词内巧合（我的正则太松）。
**结论：REA 是干净的，报警源是我们自己的工具输出噪声。**

这件事的价值比它本身大：一个专职只读分析的 Agent，在**没有任何真实攻击**的情况下，
仅凭环境噪声就产生了"被劫持"的判断。这正是 `app/core/untrusted.py` 存在的理由——
不可信内容不等于"有恶意"，**任何来源不明的文字都不该被当成指令**。
建议在答辩里把这条讲成"我们自己观察到的误判案例"，比讲抽象的注入攻击有说服力。

---

## 6. 待办（未动代码，等拍板）

本文档只是研读结论。上面 10 条任何一条要落地，我按条开工并自带回归测试。
建议顺序：**P0-4（不进场留痕）→ P0-2（coverage 三态钉类型）→ P0-3（补负例族）→
P0-1（证据自认证 ID）→ P1-5（架构闸）**，五条合计约 11 小时，
全部零运行成本、不碰在线链、不动 14B 额度。
P0-4 排最前，是因为它是本次研读在**我们自己代码里**挖出的实漏（免检与通过坍缩成
同一个状态），不是从 REA 搬来的理念；P1-4 议题义务台账（1–1.5 天）收益最大但要新模块，
留到前面几条见效之后再动。

---

## 7. 本文研读过程中新量出的基线，与未闭合台账

用 REA 的规矩给自己记账：**没写在这里的，不算已核实；未闭合的，不许凭"没提"就算完。**

### 7.1 存量产物实测基线（2026-10-13，零 LLM 离线）

| 指标 | 实测值 |
|---|---|
| 测试基线 | `462 passed in 2.77s`（AGENTS.md 第 2 步的"415 passed"已过时） |
| 存量产物 / 结论 | 28 份 `report.json`，304 条结论 |
| 声称范围或"不存在"的断言 | 36 条 |
| 其中已被现有九道闸亮灯的 | **30 条（83%）** |
| 其中全绿静默放行的 | **6 条（占全体结论 2.0%）** ← P0-2 的真实显影量 |
| 含全称量词的结论 | 17 条，**17/17 引用覆盖 <25%**，最低 1.8% |
| 计数闸免检率 | **99.3%**（304 条仅 2 条写 `计数:M/N`，`numeric_check.py:271`） |
| 未闭合子问合计 | 6 项 / 28 份，**每案只拆出 2 项**（存量全是窄题） |

漏网样本（企业情报案例，甲方会据此做决定的话）：
「所有客户项目中未发现已发生的人员流失风险」覆盖 7.0%；
「客户D项目无坏账风险，账龄分析均为低风险」覆盖 1.8%；
「客户C项目执行进度100%无延期风险」覆盖 7.0%。

### 7.2 未闭合清单（状态截至 2026-10-13 收工）

1. **开放题早退能否被这批改动改善：仍无数据。** 存量 34 份产物全窄题，探针打不出早退。
   取证成本：官方开放题改前/改后各 3 次 ≈ 3 小时 14B 机时、0 元
   （实测单次 1968s / 1384s / 378s）。**状态：open——等 10-14 官方用例，仪器已就绪。**
2. ~~子问分解是 P1-4 的地基，未验证~~ → **地基已修**（见 §8）；但主席显式声明那条通路
   （`obligations()` 第 1 优先级）模型侧还没写进 JSON 契约。**状态：open，P1-4 正式版的前置。**
3. ~~实测数字来自一次性内联脚本，不可复放~~ → **已销**：`scripts/measure_baseline.py`。
4. `AGENTS.md` 第 2 步通过判据数字过时（写 415；10-13 日内 462 → 收工 **500**）。
   **状态：open（属文档，未擅自改）。**
5. 条目编号 `P0-4` 与 `P1-4` 撞号。**状态：open（cosmetic）。**
6. §3 正文措辞仍是"夸大版"（写于实测前），准确数字以 §7.1 与本节为准。
   **状态：open（待清洗）。**

---

## 8. 落地记录（2026-10-13 当日四项，全部零 token、不碰在线链路）

| # | 交付 | 关键文件 | 验收（同一批存量产物） |
|---|---|---|---|
| 1 | 基线测量存盘 | `scripts/measure_baseline.py` + 6 测 | 复现 304/36/30/6/99.3%；纠正产物数为 **34 份**（此前误报 28） |
| 2 | 完整性判据台账地基 | `coverage_gap.obligations()/ledger_limitation()` | **台账为空 5 份 → 0 份**；来源偏弱必带声明；e2e 出口已验 |
| 3 | P0-4 闸不进场留痕 | `app/core/gate_applicability.py`、`audit_scan()` | 计数闸免检 **32/34**、计算复算 31/34 等实底显影；报告不再无脑写「全部通过 ✅」 |
| 4 | P0-2 覆盖三态 + 范围闸 | `scope_state.py`、`scope_check.py`、skill `scope_honesty` | **越权断言漏网 6 条 → 0 条**（36/36 全部亮灯） |
| 5 | 测试会话禁真调用（守卫） | `model_client.RealCallGuardedError` + `_resolve_*_fn` + `conftest.arm_no_real_calls()` | 忘塞桩的测试**当场炸**而非静默花云端 key；生产路径实测未上膛、行为不变 |

第 5 项的成因值得留档：`ModelClient` 原写法是
`completion = self._completion_fn or _default_completion_fn()`（`:525`），
而 `app/config.py:48` 在 import 时 `load_dotenv()`——**任何测试忘了注入桩，
就会一路走到真 litellm 花钱，测试还是绿的**。所以修了两层：守卫拦掉真加载器，
调用点改成「缺桩即配置错误」（`_resolve_completion_fn`），并由
`test_call_sites_no_longer_fall_through_to_the_real_loader` 钉住不许再写回 `or` 兜底。

顺带抓到的网络成本（与本机环境有关，值得记住）：litellm 一被 import 就去
`raw.githubusercontent.com` 拉模型价格表，本机网络下**超时约 10 秒**才回落本地备份
——门禁时间从 2.8s 跳到 14s 就是它。`tests/conftest.py` 已设
`LITELLM_LOCAL_MODEL_COST_MAP=True`，回到 **3.63s**。生产 CLI 每次启动同样付这 10 秒，
`.env` 里也建议加这一行（属你的密钥文件，未代改）。

黄牌总数上升是**预期的**：新增的是显影不是劣化。`score_artifacts.py` 多出「未执行」「范围」两列，
`measure_baseline.py` 一条命令可复放全部前值。测试：`462 → 501 passed`，零失败零跳过，2.8 秒。

过程里被测试与自检当场抓住的四个真问题（没有一个是靠推理发现的）：

1. `measure()` 里 `path.relative_to(ROOT)` 对临时目录产物抛 `ValueError`——只在测试路径下炸；
2. 两处准入探针 lambda 误用外层变量名 `dossier`，`NameError` 被自己的 `except` 吞掉后
   **伪装成「该闸未执行」的留痕**——正是本次要治的病在施治过程中复发，靠"亮灯与未执行不得并存"
   这条不变量扫出 21 处矛盾才暴露；
3. 插入 skill 时吃掉了下一条的 `name=` 行，被既有的注册表清单守护测试拦住；
4. **存量产物的 `accounting` 里没有台账键**（早于本次白名单），工作台于是显示「没有判据」——
   留痕只在新数据上生效。修法是在读取侧即时复算（`server._dossier_payload`，与 flags 同一口径），
   由 `test_payload_recomputes_ledger_for_legacy_artifacts` 钉住。

真进程验证（非 TestClient）：`app.server` 起来后 `/api/dossier?case=bi-delivery-risk` 返回
台账 2 条（来源=议题子问）、未执行闸 4 道、`scope` 灯 2 条、`clean=False`；
离线桩真案卷跑出的 `report.md` 同段落均正确渲染。
