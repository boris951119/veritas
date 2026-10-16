# HANDOFF · 当前状态与交接页

> **这份文件是跨工具交接的唯一入口。**
> 换任何开发工具（Cursor / Claude Code / Codex / 另一个 Qoder 会话）时，新工具只要读到本文件
> 就能接上进度；`AGENTS.md` 与 `CLAUDE.md` 都指向这里。
> **纪律**：每次收工或换工具前，对当前工具说一句「更新 HANDOFF 并提交」——
> 记忆不会跨工具走，**只有进了 git 的文件才算同步**。

最后更新：2026-10-16 · 分支 `cursor/knife11-second-pass-and-gates` · **官方样例集与《评分标准》已到手，「等材料期间不动代码」冻结解除**；
**C-9 第二轮架构师独立复放＝通过、已收口落 commit**（559×5 次绿／`from_env`＋`from_json` 双 0／est=19399 偏差 0.11%／flake 3-20≤6）；
**四张单已出齐，用户拍板「都一块做完」→ 执行序 C-10 → C-12 → C-14 → C-13**（串行，理由与验收口径见 §5.0 顶部框）。
C-10＝修 flake（10 分钟，只动测试）；C-12＝官方数据进得来／提交物出得去（1.5 天）；
C-14＝消解记录对齐官方五级＋票数只当破平器（0.5～1 天，口径由用户拍定：「票数占一部分权重，但绝对不是评判标准」）；
C-13＝推理树补中间结论层＋依赖边＋依赖传播（1 天，对着主观分最大单项 10 分）

> **分工与协作规则已单独成文**：[`docs/dev-protocol.md`](dev-protocol.md)——Qoder＝架构师/规划（出单、独立复放验收、review、同步图与本页、提 commit），
> Cursor＝执行工程师（按单实现、按 §3 处理开发中发现的问题、回写状态行）。**给 Cursor 的开工指令模板在该文件 §9，直接粘贴即可。**

## 1. 现在在哪儿

- 最近提交：`1703892 fix(输入层): 导入侧深层路径改拒收不再覆盖文件…（工单 C-6）`；上一笔代码提交 `56f1e7e feat(可信度): 推理链完整性进分`——
  置信度从三分量升为**四分量**（强度 × 覆盖 × 一致性 × **链完整性**），六环判定复用各道零 LLM 机械闸的输出，分数与警示同源。
- 测试：**入库版本 `pytest tests -q` = 553 passed**（零失败零跳过，约 4 秒）。C-9 第二轮收口后＝**559 passed，连跑 5 次全绿**；
  `test_panel_single_failure_degrades` 仍是顺序敏感的（HEAD 基线 6/20），热路径不再读配置后：Cursor 复放 **2/20**、
  架构师独立复放 **3/20**（第 1、5、12 次），均 ≤6。**两个数不一样但都对——这本来就是真竞态，失败次数每轮都漂，
  所以判据写「≤6」而不是「＝某个数」。flake 未根除**，根子仍是 C-10（共享脚本队列抢答），C-9 只是不再放大它。
  第一轮把该竞态放大到 13/20 的记录见 §5「C-9」复放。
  测试期有禁真调用守卫（`tests/conftest.py` 上膛，忘塞桩的测试当场炸，不会偷花云端 key）。
- 实测净效应：34 份存量产物 294 条可计分结论，链中位 0.75、满分仅 40.1%；
  置信度中位 0.2133 → 0.1813（**−15.0%**）。复放命令：`python scripts/measure_baseline.py`。
- **官方材料已于 2026-10-16 到手，「等材料期间不动代码」冻结解除**（用户同日拍板：全部解除、按新优先级连做）。
  材料在**仓库外**：`~/Desktop/veritas-testcases/样例集-拓尔思-20261012`（六案）与
  `~/Desktop/veritas-testcases/多智能体可信研判与证据链溯源`（三份官方文档）。
  **《评分标准》不在 PPT 文本层里**——它作为 OLE 嵌入对象藏在宣讲 PPT 第 14 页「3.3 评分规则」
  （`ppt/embeddings/Document1.docx`，64,808 字节），正常打开 PPT 只看到一个图标。
  已逐字提取存盘：[`docs/contest-scoring-rubric-2026-10-13.md`](contest-scoring-rubric-2026-10-13.md)
  （含原文四处自相矛盾的口径注）、[`docs/contest-decks-2026-10-13.md`](contest-decks-2026-10-13.md)。
  实测探针：`scripts/probe_official.py`（六案 486 篇／1,389,545 字／184 条金标／18 题，逐条可重算）。
  工单进度：C-1～C-6 已提交；**C-9 第二轮复放通过、已收口落 commit**（`1885131`）。
  **本轮四张单已出齐，用户拍板「都一块做完」→ 执行序 C-10 → C-12 → C-14 → C-13（串行，理由见 §5.0 顶部框）**：
  **C-10**（编队用例共享脚本队列＝顺序敏感的假红，flake 根因，10~20 分钟）→
  **C-12**（官方数据进得来／提交物出得去，撞车点已解除）→
  **C-14**（消解记录对齐官方五级＋票数只当破平器；前置实测已完成：同源污染 22 对／486 篇＝4.5%，
  `scripts/probe_source_dedup.py` ⇒ **独立信源簇不再是任何单的前置**，该条已降级）→
  **C-13**（推理树中间层：结论→结论依赖边＋受影响集识别与披露）。
  C-7 已降级；C-3/C-2b 待 C-12 落地后定价。
  输入层「漏了但知道漏了」自 2026-10-16 起对 **7 道召回口子全部成立**（披露≠召回，口子本身仍在）；
  C-6 合并后这句**也覆盖「添加文件夹」上传链路**（超深不再静默覆盖，改拒收＋披露）。
  但仍**不含对撞台账**——台账只记检出了什么，没有「没检出什么」的出口，别说成「系统所有漏检都有账面」。
  **10-16 又测出第二个例外（C-9，出口层）**：材料字数超过模型窗口时，Ollama **不报错、直接把提示词从头剪掉**，
  实测 8 万字超发时**角色纪律与研判议题一起消失**（暗号复述法证实），而账面全部显示"已纳入"。
  所以对外只能说「**输入层** 7 道口子漏了都留痕」，不能说「系统每一层漏了都留痕」。
  另：**「500 封顶那道口子必然触发」这句已被官方样例集否掉（2026-10-16 实测，`scripts/probe_official.py`）**——
  「单专题 ≤2000 篇」是宣讲会口径，**样例集六案实测只有 52～137 篇，500 封顶 0/6 触发**。
  真正在六案上 **6/6 触发**的是另两道：① `app/core/corpus_index.py:39` 的 **`_MAX_SOURCES = 50`**
  （选料阈值默认 50，六案 52～137 篇**全部走大库选料路径**，然后被砍到 50 份——吉隆案砍掉 87 篇、柬泰 55 篇）；
  ② **8 万字预算**（六案总字数 96,473～550,286，**全部超预算 1.2～6.9 倍**）。
  C-7 前置实测（合成材料，`scripts/measure_capacity.py`，［实测·合成］）那句"单抬①只多看见 1 份（20→21）"仍成立，
  但它的对象是 2000 篇的合成库；**在真材料上①根本不咬，所以 C-7 已降级**（详见 §5.0 该行）。
  选料排序是按 BM25 段分（`corpus_index.py:190-197`：`src_score` ＝ 该信源下段分最大值，
  先塞 8 个 `PROTECTED_TYPES` 保护位、再塞实体命中、最后按分补齐），**不参与 `source_credibility`**——
  这与实测「`source_credibility` 与金标承载 `r=+0.0526` 近零」一致，**是对的，别改**。
  真材料丢件率**现在可量了**：C-12 的下界评分器就是量它的工具（此前一直［未量］）。
  **同日的 C-9 把优先级压到了后面**：本地 14B 默认 `num_ctx=16384` ≈ 只吃得下 2.4 万字（按拟合密度折算；
  实测两端＝2 万字全中／8 万字被剪），而装箱预算 8 万字——
  **超发部分被服务端从提示词头部静默剪掉**，丢的是纪律与议题本身。这道口子在②③之后、且**零披露**，
  比「候选池只有 500」更靠前（C-7 的 A「抬预算」因此在本地模型上作废）。

## 2. 在等什么

**三样全到了（2026-10-16），本节已不再是阻塞项。** 官方邮件（接榜确认函 2026-10-14 提交）等的
① 榜单**验收标准**、② **评分标准细则**、③ **样例集**，都在 `~/Desktop/veritas-testcases/` 下：

| 等什么 | 到手了吗 | 在哪 |
|---|---|---|
| ① 验收标准（硬指标，未达即废榜） | **到了**，但**不是一份独立文档**——它体现在《评分标准》的分档锚点与「不合格＝0 分」线上，以及赛事规则 PPT 第 5 页那句"所有团队都未达成榜单验收指标 → 第一名只拿 2 万元赛事奖金"（即**可以没人成功揭榜**） | `docs/contest-scoring-rubric-2026-10-13.md`、`docs/contest-decks-2026-10-13.md` |
| ② 评分标准细则（每项给几分） | **到了**，100 分逐项到锚点：客观 50（证据提取 10·结论正确率 15·支撑证据 12·冲突证据 13）＋主观 40（系统完整性与可视化 20·置信度依据 10·冲突消解记录 10）＋加分 10（因果识别 8·证据等级 2） | 同上；**原文藏在宣讲 PPT 第 14 页的 OLE 嵌入对象 `ppt/embeddings/Document1.docx` 里**，PPT 文本层为空 |
| ③ 样例集（证据/结论字段结构） | **到了**，六案 486 篇／1,389,545 字／184 条金标证据／18 题；结构与提交物同构 | `~/Desktop/veritas-testcases/样例集-拓尔思-20261012`（**仓库外，不入仓库**） |

**仍未知的一件事**：隐藏**测试集**的规模（样例集最多 137 篇，但测试集"同结构"不等于同规模）。
这条是 C-7「500 封顶可配」现在**唯一**还剩的立项依据。
宣讲会情报与原文转写仍在：`docs/contest-briefing-2026-10-14.md`、`docs/contest-transcript-2026-10-14.txt`。

## 3. 材料到手后的动作顺序（原计划 vs 实际结论）

1. ~~先花半小时读样例集 JSON 字段结构~~ → **已做（2026-10-16）**，结论是**要做「逐题答题纸」改造，而且比预想的大**：
   `Dossier.question` 是单个字符串，官方却是**一案 3 题、以 `question_id` 为匹配键**；
   更硬的是官方输入形态（`raw_documents.json` 的 `content`＋偏移段落）**我方摄取根本不认**，
   且六份提交物字段**全仓 0 命中**。→ 已合并成 **C-12**（队列第二，前面只有一张 10 分钟的 C-10）。
   实测细节与七条前提见 §5「C-12」，复放 `scripts/probe_official.py`。
2. 按 `docs/scenario-review-2026-10-14.md` 的七条结论，往「人的研判十格对照表」上**贴分值**——
   **现在能贴真分值了**（此前只能贴推测）：评分项×环节对照表要按《评分标准》的 2.2／2.3／2.4／2.5／3.1／3.2／3.3／4.1 重画。
   **未做**，排在 C-12 之后（先有分数基线，再画对照表才有意义）。
3. ~~优先级最高的动手项：把「独立信源簇」做成数据结构~~ → **优先级判断已被官方材料两次改写**：
   它仍是官方点名的「难点 B·同源转发冒充多源」（且 2.1 多数投票判据明写"须去同源"），
   但 **2026-10-16 的 C-14 前置实测已经把「同源发生率」量出来了**（`scripts/probe_source_dedup.py`，
   不需要 C-12）：生产闸 `near_dup_pairs` 在六案 486 篇上只抓到 **22 对＝4.5%**，其中 6 对是 Jaccard=1.000 的原样转载；
   阈值从 0.5 放到 0.15 也只涨到 17 对（粗指纹口径）→ **同源污染可忽略，本项不再是任何单的前置条件**。
   仍需 C-12 才能量的是另一半：「同源到底吃掉多少**分**」（要评分器）。
   实测早已确定的一条：URL 去重没用（486 篇／226 域名／**完全相同 URL 只 3 组**），必须文本级聚类——
   而文本级聚类**已经有现成实现**（`dup_check._shingles` ＋ Jaccard），所以本项剩下的价值在篡改检测／孤证显影，不在召回。

## 4. 七个已知的坑（新工具必须先知道）

1. **别把推演当事实**。`docs/scenario-review-2026-10-14.md` 每条标了 [实测]/[推演]；
   2026-10-14 当天就有两次判断过头被更正（多智能体其实只差 2–3 分；「转载吹高置信度」一度被错误划掉）。
2. **置信度刻度变了**。跨 2026-10-14 比 `scripts/score_artifacts.py --check` 基线前，必须先 `--save` 重存，
   否则 −15% 的刻度下移会被读成「答案变差」。
3. **演示时别把「人工修改」讲成「改答案」**。官方原话：「不能人工对答案进行修正」。
   正确框定＝可审计的审校：human 事件进哈希链、改完自动重算、断链环节同步变化。
4. **存量 `cases/*/out` 是旧口径落盘**，工作台对它显示「链·旧口径未计」——这不是 bug，是没测过就不写；
   任何一次人工修改会走 `recompute_all` 按新口径重盖章并留痕。
5. **真实场景是舆情流式，不是静态案卷**（详见 scenario-review §1）。改任何分量前先回到这条，
   否则又会按错场景优化。
6. **对撞台账会静默漏掉真冲突，且「漏了但知道漏了」这句不适用于它**（2026-10-15 核代码新发现，用户案例存盘）。
   问的是：两条新闻时间地点人物一样、伤亡数字不一样，切段在伤亡处截断会不会把召回搞乱——
   **不会乱，会消失**。四条代码事实：指标词只在同段数字前取（`app/core/fact_ledger.py:87` `head = text[: num.start]`，
   `:89` 取不到即「裸数不进台账」）；对撞键是**字面** `(entity.lower(), metric)`（`:117`），纯中文实体被并进指标、
   `entity` 置空（`:96`）；无伤亡/死亡/遇难词表（本文件 grep 零命中，措辞一变 key 就分裂）；
   `find_collisions()` 全程不用 `Fact.date`（只在 `:142` 渲染显示），所以撞上也不能证明同一事件＝假对撞。
   附带：`segment.py:118` 句子边界优先，但 `:121` 句长超 650 且无标点时**退化为定长切**，可把「死亡12人」劈成两段
   ——docstring 的「从不切断句子中段」不成立，`test_ingest.py:126` 只测了带句号的材料。引文侧有半道兜底
   （`citation_check.py:60-65` 邻段正反拼接 + `:32` 去空白，但只声明一个 segment_id 就判未命中）。
   **漏检率与定长切发生率均［未量］**：台账只记检出了什么，没有「没检出什么」的出口；私有 gold 的
   `conflict_recall=1.0` 测的是刻意植入、措辞对齐的窄题冲突，不代表舆情真实措辞分布。
   图上位置：`docs/architecture-map-2026-10-12.html` ① 带「切段与断行愈合」（已由绿改黄）、
   ⑤ 缺口带「时间定向＋台账漏检」、指标承诺新增灰行「数字冲突漏检率·未量」、病因表第 5 条改为双向失效。
7. ~~**工作台「添加文件夹」会静默覆盖材料**~~（2026-10-16 实测发现；**工单 C-6 已修复并验收合并 `1703892`**，本条留作取证）。
   修复前：`import_case.py:41` 对 >4 段相对路径**截掉最后一段＝文件名**，两份深层文件塌成同一路径后
   `write_bytes` 后者覆盖前者，而接口照样返回 `n_written=2`、`skipped=[]`。探针实证：
   上传 `top/a/b/c/一月报告.txt`＋`二月报告.txt` → 磁盘只剩一份 `top/a/b/c`，内容是一月的对手，**零报错零披露**。
   修复后：一律拒收＋分原因披露（`deep_path`/`hidden_path`/`oversize`），拒收账进 `manifest.import_refused`
   → 报告「摄取披露」章，`resolve_case_file` 同源拒收（导进来的和认得出的用同一套规则）。
   **这条给协作留下的教训**：第一轮修复把
   「只认可摄取后缀」的计数同时用到了遍历封顶的超深分支上，**深层目录全是图片时 `dir_truncated` 整条消失＝C-1 回退**，
   而全量测试当时仍 552 绿（存量封顶用例清一色 `.md`）——**改共享计数函数必须逐调用分支复放，不能只看新文案那条**。

## 5. 待 Cursor 修复工单（Qoder 出验收，双方不口头交接）

> 用法：执行工程师（Cursor）按工单改，改完把「动了哪些文件 + 新增用例名 + `pytest` 尾行」写回本节该工单下面；
> 架构师（Qoder）按「验收判据」独立复放，记录写在同一格（通过／打回＋原因）。**不通过不合并。**
> 规则全文见 [`docs/dev-protocol.md`](dev-protocol.md)；开发中发现的问题按该文件 §3 分流，不许顺手改结论。

### 5.0 队列与门禁（谁动、什么条件下才动）

> **执行顺序（2026-10-16 用户拍板「都一块做完」，四张单一次交给 Cursor 串行做）：**
> **C-10 → C-12 → C-14 → C-13**，每张单的开工提示词都在该单末尾，按序粘贴即可。
> **为什么必须这个序**：① C-10 只动 `tests/test_collab.py`，修掉 flake 后，后三单的「连跑 5 次全绿」判据才站得住；
> ② C-12 改 `app/pipeline.py` 的编排（多题运行）＋建导出层，C-14 要给 `Resolution` 加字段供导出层读，
> C-13 要在 C-12 定型的编排里插一遍——**三单改同一处编排代码，并行必冲突**；
> ③ C-14 与 C-13 都碰 `arbiter`/`conflicts` 附近，故 C-13 的依赖抽取**必须放新模块 `app/core/dependency.py`**。
> **验收口径不变（协议 §4）**：四单可以连着做，但**每单各自回写状态行、各自等架构师独立复放**，
> **不通过的那单独返工，不牵连其余三单**；一工单一 commit（代码＋测试），文档另起一笔。
> ⚠️ 连做的已知代价：**C-12 若被打回，C-14 与 C-13 的基线（pytest passed 数、导出层字段）会跟着动**——
> 所以后两单回写时必须写清「基于 C-12 的哪个版本做的」，便于返工时定位。

| 单号 | 事项 | 依赖官方材料？ | 状态 | 工时 |
|---|---|---|---|---|
| ~~C-6~~ | 导入侧深层路径静默覆盖（拒收＋分原因披露）＋「可摄取文件数」按后缀对齐 | **不依赖** | **已通过验收并合并（`1703892`，两轮：第一轮判据①–⑥全过＋打回 R-C6-1，第二轮复放通过）**；剩 T-C6-1 尾巴（全 unknown 后缀目录不给份数） | — |
| **C-12** | **官方样例集进不来、提交物出不去**：`.json` 不在任何摄取白名单（`case_loader.py:50`／`readers.py:157`）→ 官方 `raw_documents.json` 被当**一整篇纯文本**读，`doc_id`／`para_id`／偏移全碎；且 `supporting_facts`／`conflicting_facts`／`fact_des`／`resolution_type`／`para_id`／`question_id` **全仓 grep 各 0 命中** | **材料已到手**（六案 486 篇／1,389,545 字／184 条金标／18 题，已实测） | **已出单＝摄取适配层（`para_id` 保全）＋多题运行＋四份提交 JSON 导出＋只算精确匹配的下界评分器**。定位要诚实：**这单要的是"能量出来"，不是"量出来高"**，跑出低分是合格结果。开工提示词已附单末（协议 §9.1） | **队列第二**（2026-10-16 出单，约 1.5 天；**排在 C-10 之后**，因为它的「连跑 5 次全绿」判据要靠 C-10 才站得住）；撞 `app/pipeline.py`——**C-9 已于同日验收通过并提交，撞车点解除，可立即开工** |
| **C-9** | **模型窗口超发＝提示词被服务端从头静默剪掉**（丢的是角色纪律＋研判议题本身），全链路零披露：装箱按字、模型按 token | **不依赖**（本机 14B 已测：默认 `num_ctx=16384` ≈ 2.4 万字（折算），现 8 万字预算超发约 3.4 倍） | **只做丙（加出口披露）**；乙／甲未拍板不做 | **已收口（2026-10-16）＝第二轮架构师独立复放通过、已落 commit**（R-C9-1 构造注入、R-C9-2 真路径用例；第一轮打回原因仍见复放记录）。复放实测：559 passed×5 次绿／`from_env`＋`from_json` 热路径双 0／真路径 est=19399、overflow=3015（对 19,378 锚点偏差 0.11%）／flake 3-20≤6／`cases/`＋`conftest.py` 零改动。**遗留：flake 未根除（根因是 C-10 的共享队列抢答），云端模型窗口仍未量**。**官方样例集到手后本单的定性变了（2026-10-16 实测）**：六案「理论最小必读量」＝金标段合计 4,826～19,591 字，**全部 ＜ 本机窗口折算的 ≈2.4 万字**（0.20x～0.82x）→ **不是材料装不下，是装进去的 96%～99% 是无关的**。所以丙（只加披露）现在是**治标**：真正的修法是乙（窗口成配置项、装箱以窗口为准）＋把召回做准；乙仍未拍板 |
| **C-13** | **推理树缺官方点名的三样**：`reasoning_graph.py:3-11` 的边只有 `supports/cites/from_source/authored_by/conflicts_with/rebuts/decides`——**无「中间结论」节点、无结论→结论依赖边**。~~人工改证据只重算直接被支撑的那条，不做依赖传播~~ → **出单前核代码发现这半句错**：`app/server.py:268` 的 `_mutate` 调的是 `recompute_all`＝**全量重算**，置信度数字不会漏。真缺的是 ② 没有「哪些结论受影响」的**识别与披露**、③ 上游失效时下游**不会被标记** | **材料已到手**（宣讲 PPT 第 8 页把三点讲死：①中间结论在哪 ②结论之间的依赖 ③依赖的传播） | **已出单**。对应评分 3.1.3＝**10 分，主观分最大单项**；四类元素里我们已有三类（依据／冲突点／消解结果），**缺的正是中间结论与逻辑链**，所以现在卡在 4~8 分档 → **全队列里"每工时换分"最高的一张**。顺带解锁加分项 4.1.1 的「间接传导」（官方要三级：直接因果／间接传导／仅相关，我方只有二级）。开工提示词已附单末（协议 §9.1） | **队列第四＝最后一张**（2026-10-16 出单，约 1 天）；**硬依赖 C-12＋C-14**（撞 `pipeline.py` 编排同一处；依赖抽取必须放新模块 `app/core/dependency.py`，不许塞进 C-14 要改的 `arbiter.py`） |
| **C-14** | **冲突消解：票数只当破平器 ＋ 消解记录对齐官方五级枚举**：`evidence_strength_of` 是**均值**（`confidence.py:76-81`）→ **票数在消解侧权重为 0**；`_WEIGHT_MARGIN=0.20` 以下那个势均力敌区间**没有任何机械依据**，直接交回 LLM；`method` 是自造值、无 `basis`、`dissent` 缺「重启条件」 | **材料已到手 → 前置实测已完成**：官方 `decks:311` 要求「须去同源」，实测**同源污染只有 22 对／486 篇＝4.5%**（生产闸 `near_dup_pairs` 口径），且**阈值从 0.5 放到 0.15 只涨 8 对** → **不需要先建独立信源簇，现成两道闸够用**。见下方「C-14 前置实测」 | **已出单**。口径由用户 2026-10-16 拍定：「票数占一部分权重，但绝对不是评判标准」→ 强度差 >0.20 按强度定（票数不参与），≤0.20 才比独立信源数，仍相同则 tie。对着评分 **3.3 冲突消解记录＝10 分**。开工提示词已附单末（协议 §9.1） | **队列第三**（2026-10-16 出单，约 0.5～1 天）；**硬依赖 C-12**（导出层须从 `Resolution.to_dict()` 读字段，C-12 已补前向约束）；与 C-13 不撞 |
| **C-7** | 超 500 文件时**取哪 500**：现按文件名排序（`case_loader.py:370`，上限在 `:352`），相关性在这一层不参与；500／深度 3 无 env、无 manifest 可配 | **材料已到手 → 立项理由被削弱**：官方六案 **52～137 篇**，全部远在 500 上限内（原「单专题 ≤2000 篇」是宣讲口径，样例集实测最多 137） | **已实测完毕 → 见下方 §「C-7 前置实测」**。原「相关性 vs 跨信源配额二选一」的问法作废；A 的「抬预算」半段被 C-9 否掉。**已出单＝只做 C（封顶变可配、默认值不变）**，定位要诚实：不解决召回，只防现场被自己的上限挡死——而"现场被挡死"这个前提现在只剩**隐藏测试集可能更大**这一条未证依据。开工提示词已附在单末第七段（协议 §9.1） | **降级到 C-12／C-14／C-13 之后**（撞 `app/config.py` 白名单；C-9 已提交 `1885131`，现在只排在这三单后面，不再被未提交改动挡住） |
| **C-10** | 编队用例共享一个脚本队列＝**顺序敏感的假红**：`run_panel` 用 `ThreadPoolExecutor` 并行提交（`app/agents/panel.py:93-94`），而 `ScriptedClient.chat` 从**同一个队列** `pop(0)`（`tests/test_collab.py:43`）——「谁抢到第 2 个响应」纯看调度，用例却断言 `失败者 == {"redteam"}` | **不依赖** | **C-9 复放时抓出，已证是先前就有的洞**：HEAD 干净树单跑 20 次失败 **6 次**；同一队列在 12 次重复里 redteam 11／technologist 1。**C-9 第二轮收口后架构师又独立测了一次：仍失败 3/20**（第 1、5、12 次）——即 R-C9-1 只是不再放大它（6→2~3），**洞还在**。修法＝按分析师身份路由响应（`ScriptedClient` 已支持 `callable(messages)->str`），禁 sleep／重试。**优先级高于其余全部四单**：全量测试现在掷骰子，此后每张单的「连跑 5 次全绿」判据都站在它上面。**已出单（10 分钟小单），排在队列最前** | **队列最前**（2026-10-16 出单，只动 `tests/test_collab.py`，与其余四单零重叠） |
| ~~C-11~~ | **单段字数 ＞ 整卷预算 → 该段被装箱器整段剔除**：实测单段 9 万字 → `pack_material` 选中 **0 段**、渲染后只剩 **53 字**（议题壳） | **不依赖** | **复放质疑 1 时顺带量出，当场查清＝不是静默洞**：该段照进 `pack["excluded"]`，reason「预算截断」（`app/core/material.py:120-126`），报告侧 `pipeline.py:1255-1258` 渲染进「未采信信源」。**披露在，召回不在**——真发生时的损失是"整段一个字都没进模型"，而文案只说"预算截断" | **撤销立项**，留一条呈现尾巴 T-C11-1：reason 改成"整段超出整卷预算，本段一字未入模型"（10 分钟，可与 C-7 同批） |
| ~~C-8~~ | 两侧深度一起抬到 5（真收深层目录） | **数已到手：官方材料最深 3 级** → 现上限（遍历 3 层／导入 4 段）本就够 | **撤销**（C-6 的 `deep_path` 拒收不会误伤真实材料，只会挡住人工塞进来的超深目录） | — |
| C-3 | 切段定长退化切（`segment.py:121`） | 需先量发生率 | 只记录 | 待定 |
| C-2b | 指标归一化／词表（治措辞分裂的真漏检） | **样例集已到手 → 可定价了**，但仍须先有 C-12（否则台账跑不到官方数据上）。~~且先做独立信源簇~~ → **这条前置已被 C-14 前置实测削弱**（同源只有 4.5%，见该行）；但**指标归一化本身与同源无关**，它治的是「死亡12人」vs「遇难12人」各占一个字面 key 的措辞分裂，仍须等六桶分类统计的数据说话 | 待 C-12 落地后先跑一次六桶分类统计，用数据决定这笔值不值得 | 约 1 天 |
| — | **独立信源簇**做成数据结构（覆盖分量、冲突判定、篡改检测、孤证显影的共同地基）。**官方已把它写成「难点 B·同源转发冒充多源」**：一条通讯社通稿被 20 家转载，"多源印证的前提是相互独立，否则「多数」是假象"；且 2.1 的多数投票判据明写「须去同源」 | **材料已到手 → 实测定了做法**：URL 去重没用（486 篇全有 `content_url`，去重域名 226 个、**完全相同 URL 只有 3 组**，最多的域名也只 12 篇）→ 同源是**文本近重复**，必须内容级聚类。金标里 `Majority_Vote` 只占 **1/91**，官方自己极少用多数投票。**但 2026-10-16 的 C-14 前置实测把「必须先建簇」这个前置条件推翻了**：生产闸 `near_dup_pairs`（8 字滑窗 Jaccard≥0.6）在六案上只抓到 **22 对／486 篇＝4.5%**，其中 6 对是 Jaccard=1.000 的原样转载 → **同源污染可忽略，C-14 直接调现成闸即可，本单不再是任何单的前置**。本单仍值得做（篡改检测／孤证显影要用），但**优先级下调** | 待用户 go（**已从前置降级为独立改进项**，排在 C-12／C-14／C-13 之后） | 约 1 天 |
| — | **「未定论／并列保留」必须成为一等结论姿态**：评分 2.3 明写"对『未定论』事项选边"＝**0 分**，评判要点③又写"完整呈现并列即判一致，不因未选边而降档"。而 chair 层现在的口径是「正面回答议题」 | **样例集已到手 → 已量出风险面**：18 题里 **4 题**金标结论是不可判定／并列（柬泰 q_002「现有记录**无法判定**谁先动武」、刘翔 q_003「素材**不足以**判定」、中美AI q_001、印航 q_001），选边即 4×1.0/18×15 ≈ **3.3 分归零** | 待出单（2.3 是 15 分，客观分第二大项） | 约 0.5 天 |
| ~~—~~ | ~~**`resolution_type` 五级枚举＋`basis`＋少数意见重启条件**~~ | — | **已并入 C-14**（2026-10-16）：五级枚举映射、`basis` 可核验快照、`reopen_when` 三样都是 C-14「要求」的第 3、4 条，不再单列。金标分布留作对照参考：`Source_Priority 29 · Other 28 · Credibility 24 · Most_Recent 9 · Majority_Vote 1`（91 条冲突侧）——**只对照，禁止调参逼近**（C-14 禁止条款 ⑩） | 并入 C-14 |
| — | **`fact_des`／`argument` 六槽／`entities` 的生成**（C-12 只留空并披露，不编造） | 官方 2.2.2 是**"填了即判错"**口径（`argument.时间`「原文无明确时间的应为空，填了即判错」）；**金标自身也有缺陷**：`数值口径` 槽只有 **17/184（9%）** 带、3 条用英文键 `content`、1 条缺 `主体` → **照抄金标也拿不到 `Field_acc=1.0`，这 3 分有天花板** | 待出单（排在 C-12 之后；要动抽取提示词与结构化契约） | 约 1 天 |
| — | `docs/proposal-formal.md:147/:151` 对外数字同步（旧口径 13,700 行／415 测；现值待 C-6 收口后用 `scripts/measure_baseline.py` 一次测齐） | 不依赖 | 待用户点头，架构师改文档 | 10 分钟 |

**材料到手当天的固定动作**（不排工期，来了就做）：① 读样例集 JSON 字段结构（决定要不要做「逐题答题纸」改造）；
② 跑一次台账六桶分类统计＋畸形指标密度，用数据决定 C-2b 值不值得占用簇改造那一天；
③ 拿真数据跑分诊账本，把「7 道召回口子」＋C-6 这条导入侧口子的丢件率从［未量］变成有数——
   **按 ≤2000 篇这个数，500 封顶那道口子的实际丢件率会远超其余各条，是当天第一个要量的。**
   量①的同时必须一起量②：合成实测显示可见份数的上界在选料层（8 万字＋50 份），见 §5「C-7 前置实测」。
④ **拿真材料字数 × 0.69（＝÷1.45）得到 token 需求，对照现场模型的 `num_ctx`**——C-9 已测出本地 14B 默认窗口约吃得下 2.4 万字（折算值），
   样例集一到，第一件事不是调召回，是**确认我们发出去的提示词有没有被服务端静默剪过**（暗号复述法可开箱重放）。

**用户手上两件事**：**均已回答（2026-10-16）**——单专题材料 ≤2000 篇、目录最深 3 级。
推论已写进上表：C-8 撤销（3 级本就在上限内，C-6 的超深拒收不会挡住真材料）；C-7 反过来变成硬口子
（2000 > 500，且现按文件名取前 500，剩余 1500 篇连案卷都进不去）。

### C-1｜目录遍历封顶＝静默丢材料（优先级最高，不依赖官方材料）

- **现状（已核代码）**：`app/ingest/case_loader.py:203`（`if depth > max_depth or len(out) >= max_files: return`）
  与 `:206`（`if len(out) >= max_files: break`）两处截断**不写任何 `ingest_notes`/`triage`**——
  超过 500 个文件或深于 3 层的材料**静默消失**。对照压缩包那条是有披露的（`app/ingest/archive.py:180` `truncated`）。
  `count_case_files`（`:226`）调同一个 `_collect_files`，所以大库选料预判（`app/pipeline.py:76`）与索引看到的是同一个被截断的数，**一起骗**。
  `tests/` 里搜不到 `max_files`/`max_depth`/`_collect_files`/`count_case_files` 任何用例。
- **要求（只做这两件）**：
  1. 封顶触发时写披露，且必须进报告出口：`dossier.ingest_notes`（`kind` 自定但要稳定）＋`triage` 一条，
     文案含「按文件名排序取前 N，另有 M 个文件/更深层目录未入卷」。**只写 logger 不算，必须是 `report.json` 里读得到的字段。**
  2. 补测试：至少三条——超 500 文件触发披露、超深度触发披露、未触发时**不得**多写披露（防空转假披露）。
     用 `tmp_path` 构造，零 LLM、零密钥。
- **明确禁止**：① 不许把 500/3 调大或去掉来"变绿"——那是把静默丢失放大成更大规模的静默丢失；
  ② 不许改遍历排序语义（现为按名排序）——它决定装箱与产物确定性，要改得单独评审；
  ③ 不许动 `app/ingest/segment.py` 与 `SEGMENTER_VERSION`（切段那条是另一格 C-3）；
  ④ 不许改 `tests/conftest.py` 的禁真调用守卫。
- **验收判据（Qoder 复放）**：
  - `.venv/bin/python -m pytest tests -q` → 0 failed，passed ≥ 535（532 ＋ 新增≥3）。
  - Qoder 自建 501 文件目录跑 `load_case`，检查 `report.json` 的 `ingest_notes`/`triage` 有截断条目、
    且 `count_case_files` 与披露数字对得上。
  - **存量产物不得多出披露**：封顶披露只应在触发时出现，存量案例都在 500 文件以内。
    Qoder 用一条 python 断言复放（不依赖基线文件）：对 `cases/*/out*/report.json` 全量扫，
    `ingest_notes` 里不应出现任何截断/超限条目；若出现说明改动溢到了正常路径，直接打回。
    （可选加测：先 `scripts/score_artifacts.py --save /tmp/b.json` 再改再 `--check /tmp/b.json`，
    得分表逐项不变——注意基线文件不在仓库里，必须在改代码**之前**生成。）
- **状态**：Cursor 已改完（2026-10-15）。｜ **验收**：**通过（2026-10-15 Qoder 独立复放，非采信自述）**。
  复放记录：① `pytest tests -q` = **535 passed**，0 失败。② 自建探针目录（503 个根文件 + `d1/d2/d3/d4/buried.txt`）→
  `taken=500 / skipped=5 / files_capped=True / depth_capped=True`，`count_case_files == taken`，`sources=500`，
  `ingest_notes` 与 `triage` 各 1 条。③ 反例两条均不产假披露：3 文件小目录＝0 条；只有空过深目录时
  `depth_capped=True` 但 `skipped=0 → truncated=False`。④ **硬判据**：全量扫 `cases/*/out*/report.json`，
  `dir_truncated` 命中 **0** 条——改动没溢到正常路径。⑤ 端到端渲染：`app/pipeline.py:1205 _render_excluded_sources`
  实测输出「按文件名排序取前 500，另有 5 个文件/更深层目录未入卷」，披露确实落到报告出口而非只进内存。
  ⑥ 调用点四处全部同步 `.files`（`server.py:397`、`import_case.py:122`、`case_loader.py:287/574`），无遗漏。
  **两个尾巴（不阻断合并）**：a) 渲染行前缀是空反引号（`"file": ""` 套通用模板），看着像漏字段，宜改成不带文件名的句式；
  b) **隐藏目录仍是静默跳过**（`case_loader.py:256` `startswith(".")` 无披露）——设计意图明确（.DS_Store/.expected.json），
  但材料放 `.xxx/` 会无声消失。**因此本单不得连带宣布「召回口子全部已披露」**，图上那句已改为把隐藏目录列为例外。
  （**2026-10-16 更新**：此尾巴由 §5 **C-5** 收口——名单外隐藏目录已写 `hidden_dir_skipped` 并落到报告「摄取披露」章，
  图上「7 道口子」节点已改成「7 道均已披露，口子本身仍在」；**披露≠召回**，材料依旧不入卷，别把这句讲成已解决。）
- **Cursor 回写**：
  - 动了哪些文件：`app/ingest/case_loader.py`（`CollectResult`＋封顶后继续计数＋`load_case` 写
    `kind=dir_truncated` / `route=dir_truncated`）、`app/ingest/triage.py`（ROUTE_LABEL/ORDER）、
    `app/server.py` / `app/ingest/import_case.py`（适配 `_collect_files` 新返回值）、
    `tests/test_collect_files_cap.py`（新建）。
  - 新增用例名：`test_max_files_triggers_dir_truncated_disclosure` /
    `test_max_depth_triggers_dir_truncated_disclosure` /
    `test_no_cap_no_dir_truncated_disclosure`。
  - `pytest` 尾行：`535 passed in 4.01s`（532＋3，零 failed）。
  - **给 Qoder 的核对提示 / 发现问题**：
    1. `count_case_files` 仍返回**截断后的 taken**（与披露 `taken` 对齐），不是 `taken+skipped`——
       验收断言应是 `count_case_files(d) == note["taken"]`。
    2. 只有 `skipped > 0` 才写披露；空的过深目录（无文件）不触发——别用空深目录测假阳性。
    3. 封顶后会**继续遍历计数**未入卷文件（旧逻辑 early-break）；超大目录（十万级）会比以前慢，
       这是披露准确性的代价，本单未做懒计数优化。
    4. `_collect_files` 返回类型从 `list` 改为 `CollectResult`（`.files`）；外部若还有未入库调用需适配。
    5. C-2 / C-3 本轮未动。

### C-2｜对撞台账补「漏检披露」（今日新发现，可先只做披露不做判定）

- **现状**：`app/core/fact_ledger.py:87` `head = text[: num.start]` 只在**同段、数字之前**取指标词，
  `:89` 取不到即 `continue`（注释「裸数不进台账」）；分组键 `:117` 是**字面** `(entity.lower(), metric)`，
  `:96` 把纯中文实体并进指标、`entity` 置空；文件内无伤亡/死亡/遇难词表。→ 两条新闻同主体同议题、
  措辞不同（死亡 vs 遇难）或指标词与数字被切段分家时，真冲突**静默消失**，报告只写检出了什么。
  详见 `docs/architecture-map-2026-10-12.html` ⑤ 缺口带与指标表「数字冲突漏检率·未量」。
- **本单范围（一句话）**：给台账加**分母可见性**——把"段落里有数字但没进台账"按原因分类计数并披露。
  **只加计数与披露，判定逻辑一行不碰**（判定改造依赖「独立信源簇」，材料到手后再动）。
- **必须遵守的接口约束（我已核过调用点，别自作主张改签名）**：
  - `extract_facts(dossier) -> list[Fact]` **签名不变**——外部有 4 处在用：
    `app/pipeline.py:270`、`app/core/fact_ledger.py:116`（`find_collisions` 内部）、
    `scripts/gen_eval_questions.py:68`、`tests/test_input_lifecycle.py:61`。
  - 建议实现：内部抽 `_scan(dossier) -> tuple[list[Fact], dict]`，`extract_facts` 变 `[0]` 的薄壳。
  - **扫描次数不得增加**：现状 pipeline 一条链已全扫 2 次（`find_collisions` 内 1 次 ＋ `:270` 的 `len(extract_facts(...))` 1 次），
    改后仍须 ≤2。`dev-journal.md:701` 把 `extract_facts` 的 500 段性能列为已知关注点，加第三次扫就是回归。
- **披露字段与口径（命名照抄，这是本单的命门）**：
  - `dossier.accounting["fact_ledger_stats"]`，键固定为
    `n_numbers`（`extract_nums` 命中的数字总数）、`n_facts`（入台账数）、
    `dropped`（原因 → 条数，原因枚举**只能是这六个**：`year`／`clause_ref`／`ordinal`／
    `no_metric`（数字前取不到指标词，即本单主靶）／`metric_rejected`（长度<2 或命中停用词）／`entity_stop`）。
  - 同一份内容进 `chain.jsonl` 的 `fact_ledger` 事件 payload（`app/pipeline.py:269` 那条），
    和报告「资料内数字冲突」章旁边一行文案。
  - **红线：字段名与文案不得出现"漏检率/召回率"**，只能叫「未采信数字分类计数」。
    理由写进代码注释：**真正的分母＝「本该对撞的数字对」机械不可知**，我们只能说"这些数字没进台账、因为取不到指标词"，
    不能说"漏了百分之几"。把不可知的东西包装成指标，正是这个项目反复挨打的地方。
- **明确禁止**：① 不改 `_ENTITY_METRIC`（`:26`）、`find_collisions` 分组键（`:117`）、1% 容差、
  `_METRIC_STOP`/`_ENTITY_STOP` 内容；② 不把裸数塞进台账来"让数字好看"；③ 不动 `app/ingest/segment.py`
  与 `SEGMENTER_VERSION`（那是 C-3）；④ 不加任何 LLM 调用；⑤ 不动 `tests/conftest.py` 禁真调用守卫；
  ⑥ **不改 `cases/` 下任何字节**（不重跑存量产物；新增字段只在未来 run 的 `report.json` 里出现）。
- **要求补的测试（`tests/test_input_lifecycle.py` 里加，零 LLM）**：
  a) 指标词与数字被分到两段 → `dropped["no_metric"] >= 1` 且 `facts` 不含该数（这就是「两条新闻伤亡不同检不出来」的最小复现）；
  b) 年份 / 条款引用 / 序数 各命中**自己**的 reason，不许混类（防一个筐装所有）；
  c) 全部数字正常入台账时 `sum(dropped.values()) == 0`（防空转假披露）。
- **验收判据（Qoder 独立复放，不采信自述）**：
  ① `pytest tests -q` 0 失败、passed 数与新增用例数对得上；
  ② 我自己造一份案卷（已知数字个数），**手工数一遍**六个桶，与 `fact_ledger_stats` 逐项相等；
  ③ `chain.jsonl` 的 `fact_ledger` 事件里能读到该 payload；报告 markdown 里能读到那行文案（端到端渲染，不是只看内存）；
  ④ `grep -rn "漏检率\|召回率" app/core/fact_ledger.py` 必须为空；
  ⑤ `git diff --stat cases/` 为空；⑥ 读代码确认全扫次数 ≤2。
- **状态**：已改完（2026-10-15）。｜ **验收**：**通过（2026-10-15 Qoder 独立复放）**，但**带一条必须记住的覆盖缺口**（见末段）。
  六条判据逐条：① `pytest tests -q` = **538 passed**，0 失败（＋3 条新用例，名称与工单要求一致）。
  ② 手工数桶：自建案卷（本季度营收 1200 万／2025 年／第 3.1 条／第 3 季度／死亡 12 人）→
  `n_numbers=5`，恒等式 `n_numbers == n_facts + sum(dropped)` 成立，`dropped` 键集合恰好等于工单六枚举，
  `n_facts == len(extract_facts(d))`。③ 落盘与渲染：`chain.jsonl` 的 `fact_ledger` 事件已带 `fact_ledger_stats`，
  `pipeline.py:332` 白名单已放行该键，`_render_fact_collisions` 端到端实测输出
  「未采信数字分类计数：共 1052 个数字，入台账 161 条；year 60、clause_ref 16、ordinal 0、no_metric 815…」。
  ④ 红线词：`grep -rn "漏检率\|召回率" app/` = 空。⑤ `git diff --stat cases/` = 空。
  ⑥ 扫描次数：**链上那段**从 2 次降到 **1 次**（`_scan` 兼得 facts 与 stats，`find_collisions(dossier, facts=…)`
  新增可选参不二次扫；其余 4 个调用方仍走 `facts=None` 老路径）。
  **但我 review 时发现这句不能写成"全 run 只扫 1 次"**：`_render_fact_collisions` 在 accounting 命中分支里
  仍调 `find_collisions(dossier)`（`app/pipeline.py` 该函数 `else` 分支），报告渲染期又扫一次——
  准确口径是**每 run 比改前少一次全扫**（改前：链上 2 次＋渲染 1 次；改后：链上 1 次＋渲染 1 次），
  而 `chair`/`prompts.facts_block`/`relevance`/`temporal_check` 各自的 `find_collisions` 是老问题、本单未动。
  判定路径逐字等价已核：分组键 `(entity.lower(), metric)`、1% 容差、两个停用词表均未改，
  六个 `continue` 分支只是加了计数。
  **覆盖缺口（本单未解决，别当已解决）**：真实舆情里的措辞分裂**不落进 `no_metric`，而是落进 `facts`**。
  实证两条：探针里「三、伤亡／死亡12人」因上文粘连凑够 4 个连续汉字，被当成 metric=「伤亡死亡」**直接入台账**；
  bi 语料 161 条 facts 的指标名全是字面碎片（「末零售客户规模」「据口径不一致导致」「回款比约定时间晚」）。
  → 两条新闻「死亡12人」vs「遇难12人」会各生成一个畸形指标、**永不相撞，而 stats 完全显示不出来**。
  所以「数字冲突漏检率」仍是**未量**，本单交付的是「取不到指标词」那一类的可见性（这一类在真语料上确实巨大：
  bi 案 1052 个数字里 815 个落 `no_metric`）。要治措辞分裂得动指标归一化／词表＝判定改造，
  依赖「独立信源簇」，**材料到手后另开工单（暂记 C-2b）**，不得并入本单收口。
  **Review 尾巴（R-2，未修，下一笔或并入 C-2b）**：`_render_fact_collisions` 的早退条件改成了
  `if not collisions and not has_drop: return`——于是**零对撞但有分母时**，报告仍会打出
  「## 资料内数字冲突（事实层对撞）」这个章名，底下只有一行分类计数。读者会以为有冲突却没列出来，
  答辩时容易被追问。修法很小：无 collisions 时换章名（如「## 台账未采信数字分类计数」）或把披露行挪出冲突章。
- **Cursor 回写**：
  - 动了哪些文件：`app/core/fact_ledger.py`（`_scan`→facts+`fact_ledger_stats`；
    `extract_facts` 薄壳签名不变；`find_collisions(..., facts=)` 可复用扫描；
    `format_dropped_disclosure`）、`app/pipeline.py`（卫生段一次 `_scan` 写入
    `accounting["fact_ledger_stats"]`＋chain payload；白名单两处加键；报告章旁一行文案）、
    `tests/test_input_lifecycle.py`（三用例）。
  - 新增用例名：`test_split_metric_number_counts_no_metric_and_stays_out` /
    `test_dropped_reasons_year_clause_ordinal_are_disjoint` /
    `test_all_numbers_facted_means_dropped_sum_zero`。
  - `pytest` 尾行：`538 passed in 3.66s`（535＋3，零 failed）；`git diff --stat cases/` 为空；
    `grep -rn "漏检率\|召回率" app/core/fact_ledger.py` 为空。

### C-3｜切段定长退化切（今日新发现，先记录，本单不开工）

- `app/ingest/segment.py:118` 句子边界优先，但 `:121` 在句长 >650 且无标点时退化为定长切，可把
  「死亡12人」劈成两段；docstring「从不切断句子中段」不成立，`tests/test_ingest.py:126` 只测了带句号的材料。
  **不开工的理由**：动切段边界会改所有 `segment_id`，牵动存量产物与 `SEGMENTER_VERSION` 废旧逻辑，
  且真实发生率［未量］——等样例集到手先量，再决定是修还是只披露。



### C-4｜报告章名误导（R-2 收口，呈现层，零判定风险）

- **现状（已实测复现）**：`app/pipeline.py:1211` 的早退条件被 C-2 放宽成
  `if not collisions and not has_drop: return`，于是**零对撞但有未采信数字**时也会打出
  `app/pipeline.py:1213` 的「## 资料内数字冲突（事实层对撞）」。
  实跑 `cases/demo-solid-state`：对撞 **0** 条、未采信 **7** 个，报告却出现这一章，
  底下只有一行分类计数——读者会读成"有冲突没列出来"。
  **改名安全性已 grep 过**：全仓库只有 `tests/test_input_lifecycle.py:230` 断言该字符串，
  而那条属"有对撞"路径（同断言还查「跨信源」），保留原章名即不受影响；
  `prompts.py:55`／`chair.py:110` 只是措辞引用不解析报告；`web/` 无命中（工作台不解析章名）。
- **要求（只动呈现，三分支）**：
  1. 有对撞 → 章名保持「## 资料内数字冲突（事实层对撞）」，分类计数行仍在本章内。
  2. 零对撞但有未采信数字 → 章名改为「## 台账未采信数字分类计数」，**不得**出现"冲突"字样。
  3. 零对撞且零未采信 → 整章不打（C-2 之前的行为，必须保住）。
- **明确禁止**：不改 `_scan`／`format_dropped_disclosure`／判定逻辑；不改统计口径；
  不动 `tests/test_input_lifecycle.py:230` 既有断言；不改 `cases/` 任何字节。
- **要求补的测试**：三分支各一条（第 2 条必须断言 md 里**不含**「资料内数字冲突」，
  防只改文案不改条件）。
- **验收判据（Qoder 独立复放）**：① `pytest tests -q` 0 失败；② 实跑 `demo-solid-state` 的
  `_render_fact_collisions` 确认章名变；③ 实跑 `bi-delivery-risk`（有真对撞）确认原章名保留；
  ④ `git diff --stat cases/` 为空；⑤ 读 diff 确认只动呈现分支与测试。
- **状态**：**已验收通过**（Qoder 独立复放，2026-10-16）。｜ **验收**：五条判据逐条复放，全过——
  ① `pytest tests -q` = **545 passed，0 failed**（与回写一致）；
  ② 探针实跑 `cases/demo-solid-state`：对撞 **0**、未采信 **7** → 章名变「## 台账未采信数字分类计数」，
     整章不出现"冲突"二字；③ 探针实跑 `cases/bi-delivery-risk`：对撞 **4** → 原章名
     「## 资料内数字冲突（事实层对撞）」保留；双零目录（无数字）→ 函数返回空、整章不打；
     `accounting` 命中与未命中两条分支章名一致（无分叉）；
  ④ `git diff --stat cases/` 为空；⑤ `app/pipeline.py` diff 仅 5 行＝章名三分支，
     `_scan`／`format_dropped_disclosure`／统计口径／早退条件均未动，测试三条都走
     `render_report_md` 真实出口（不是单测私有 helper），含"不含冲突字样"反向断言。
- **Cursor 回写**：
  - 动了哪些文件：`app/pipeline.py`（`_render_fact_collisions` 三分支章名）、
    `tests/test_input_lifecycle.py`（三用例）。
  - 新增用例名：`test_c4_chapter_with_collisions_keeps_conflict_title` /
    `test_c4_chapter_drops_only_uses_non_conflict_title` /
    `test_c4_chapter_absent_when_no_collision_no_drop`。
  - `pytest` 尾行：见 C-5 回写（两单同跑 `545 passed in 4.13s`）。

### C-5｜隐藏目录仍静默跳过（不收录，但必须披露）

- **口径已拍（2026-10-15 用户认可"不收录但披露"）**：隐藏目录里的材料**仍不入卷**，
  但不得静默消失——这是 C-1 收口后输入层剩下的**唯一**静默丢件口
  （`case_loader.py:256` `p.name.startswith(".")` 直接 `continue`，无 `ingest_notes`）。
- **要求**：
  1. 引入**工具目录名单**（`.git` `.venv` `node_modules` `.idea` `.vscode` `.pytest_cache` 等）：
     这些继续静默跳过**且不披露**（不是材料）。
     **特别点名 `.fetched` 与 `.corpus` 必须进此名单**——它们是抓取缓存与语料索引，真含文件，
     若报成"有材料未入卷"就每跑一次冒一条假警报，披露立刻变噪音。
  2. 名单外的隐藏目录 → 一条 `ingest_notes`＋一条 `triage`：出**目录名**与其中可摄取文件数，
     **不得逐个列文件名**（隐私与噪音）。
  3. 计数必须封顶（建议目录数 ≤50、文件数 ≤5000），超限文案写"另有更多未计"——
     否则一个巨型隐藏目录能把报告撑爆。
  4. 根级隐藏**文件**（`.DS_Store` 等）不在本单范围，保持现状静默。
- **明确禁止**：① 不许改成入卷（会复活 `.DS_Store`／`.expected.json` 回吃的老问题）；
  ② 不许动 `_is_artifact_dir` 现有名单与 C-1 的 `dir_truncated` 逻辑；
  ③ 不许放宽 500／深度 3 两道封顶；④ 不加 LLM；⑤ 不改 `cases/` 任何字节。
- **要求补的测试（零 LLM，`tmp_path`）**：a) `.materials/` 放 3 个 txt → 出一条披露，
  文案含目录名、不含文件名；b) `.git/` 放大量文件 → **不出**披露；
  c) `.fetched/index.json` 存在 → **不出**披露（假警报回归保护）；d) 无隐藏目录 → 零披露。
- **验收判据（Qoder 独立复放）**：① `pytest tests -q` 0 失败；② 自建探针目录逐项复放 a-d
  （含一个 5000 文件级隐藏目录测封顶）；③ 全量扫 `cases/*/out*/report.json` 无新披露条目；
  ④ 读 diff 确认 `dir_truncated` 与 `_is_artifact_dir` 未被顺手改动。
- **状态**：**已验收通过**（Qoder 独立复放，2026-10-16）。｜ **验收**：四条判据逐条复放，全过——
  ① `pytest tests -q` = **545 passed，0 failed**；
  ② **自建**探针目录复放 a–d（不复用 Cursor 用例）：`.materials` 放 3 个 txt → 恰好 **1** 条披露、
     `sources` 仍 **1**（确认仍未入卷）、detail 里 `a.txt`/`b.txt`/`secret_payload` 一个都没出现；
     `.git` 放 20 文件 → 0 披露；`.fetched/index.json` → 0 披露（假警报保护成立）；空目录 → 0 披露。
     封顶两测：**5005** 文件的隐藏目录 → `n_files=5000, files_capped=True`，**0.2s** 返回（早停真生效，
     不是数完再截）；**55** 个隐藏目录 → **50** 条＋1 条 overflow。
  ③ 存量零噪音：**36** 份 `cases/*/out*/report.json` 里 `hidden_dir_skipped`／`dir_truncated` 条目 **0**；
     六个真实案例目录直接跑 `_collect_files`，`hidden_dirs` 全为空。
  ④ diff 读毕：`_is_artifact_dir` 本体语义未改（遍历处仅并列调用新的 `_is_tool_skip_dir`），
     500／深度 3 未放宽，`dir_truncated` 分支未动；隐藏**文件**保持静默；空隐藏目录不造条目。
- **验收尾巴（两条，不影响本单通过）**：
  1. 文案里的"可摄取文件数"实为**目录内非隐藏文件数**，不按扩展名过滤——与 C-1
     `_count_ingestible` 同口径（不是回归），但**对外别说成"材料数"**。
  2. `_TOOL_SKIP_DIRS` 未含 `.qoder`／`.aone` 这类本机工具目录；若样例集目录里出现会冒一条披露，
     属**噪音不属漏检**，材料到手后按需补名单即可。
  3. 报告「摄取披露」章里目录名出现两次（通用模板前缀 `` `.materials` `` ＋ detail 正文「隐藏目录 .materials …」），
     读者视角略重复；纯排版问题，不改结论、不阻断合并。
- **Cursor 回写**：
  - 动了哪些文件：`app/ingest/case_loader.py`（`_TOOL_SKIP_DIRS`／隐藏目录计数封顶／
    `CollectResult.hidden_dirs`／`load_case` 写 `hidden_dir_skipped`）、
    `app/ingest/triage.py`（ROUTE）、`tests/test_hidden_dir_disclosure.py`（新建四用例）。
  - 新增用例名：`test_materials_hidden_dir_disclosed_without_filenames` /
    `test_git_hidden_dir_no_disclosure` /
    `test_fetched_cache_no_false_alarm` /
    `test_no_hidden_dir_no_disclosure`。
  - `pytest` 尾行：`545 passed in 4.13s`（538＋C-4×3＋C-5×4，零 failed）；
    `git diff --stat cases/` 为空。

### C-6｜导入侧静默丢件＋静默覆盖（②1）与「可摄取」口径虚高（②2）

- **本单不依赖官方材料**：改的是路径校验与披露出口，不碰判定、不碰统计口径。
- **现状（已实测复现，非推演）**：`app/ingest/import_case.py:41` 对超过 `MAX_DEPTH + 1` 段的相对路径做
  `parts = parts[: MAX_DEPTH + 1]`——**截掉的是最后一段，也就是文件名**。于是深层目录里的多个文件塌成同一条
  rel，`:146` 的 `path = case_dir / rel` 与 `:152` 的 `path.write_bytes(data)` 让后一份**覆盖**前一份
  （新建案卷 `write_imported_case` 在 `:220` 同一逻辑）。探针实跑（临时案卷，两份 5 段路径）：

  ```
  上传：top/a/b/c/一月报告.txt、top/a/b/c/二月报告.txt
  接口返回 n_written = 2   skipped = []          ← 账面说"两份都进来了"
  磁盘实际落盘: top/a/b/c  内容='二月回款25万'    ← 只剩一份，一月整份没了，零报错零披露
  ```

  触发入口是工作台最常用的「添加文件夹」：`web/index.html:865` 用 `f.webkitRelativePath || f.name` 当文件名上传，
  主办方给解压后的目录树时天然 ≥4 层。另两类拒收（dot 前缀、单文件 >20MB）只进 API 返回值的 `skipped`，
  而 `web/index.html:884` 只读 `n_written`，`ingest_notes`/`triage`/报告都不写——**与 C-1/C-5 同一类洞，只是发生在导入不在遍历**。
- **为什么选「拒收」不选「加后缀保文件」（决策依据，实测）**：遍历侧深度只到 4 段——
  `_collect_files` 实跑同一棵树的结果是 `入卷: top/a/b/c.md / top/a/b.md / top/a.md`，
  而 `top/a/b/c/d.md`（5 段）已 `depth_capped=True, skipped=1` 被 `dir_truncated` 披露。
  所以把 5 段路径**改名写到磁盘也进不了卷**：白占 `MAX_FILES` 名额与体积，成为永不入卷的僵尸文件；
  要真救就得同时压平目录，那案卷结构与主办方原目录对不上，核对原文与删除入口都得再解释一套改名规则。
  **本单口径＝承认丢件但让它可见**（与已验收的 C-5「不收录但披露」一致）。
- **要求（②1，四处落点缺一不可）**：
  1. `safe_relpath`：深度超限改为**返回 `None` 拒收**，绝不返回丢掉文件名的路径；**禁止**加后缀改名、禁止搬平目录。
  2. 拒收必须**分原因**，不许笼统报"不合法"：`deep_path`（层级超限）／`hidden_path`（dot 前缀目录或文件）／
     `oversize`（单文件 >20MB），文案带**原相对路径**（导入侧是用户自己选的清单，出文件名不涉隐私，
     与 C-5 隐藏目录"不列文件名"的口径**故意不同**，别顺手统一）。
  3. 披露落三处：① 返回值加 `refused: [{name, reason}]` 与 `n_refused`（保留现有 `skipped` 兼容读法或直接替换，
     但 `write_imported_case` 与 `append_imported_files` **两条路径口径必须一致**）；
     ② 写一条 `ingest_notes`＋`triage`，新 `kind/route = import_refused`（`triage.py` 补 ROUTE_LABEL／ORDER）；
     ③ 工作台导入结果显影「N 份未入卷（原因…）」，`web/index.html` 不得再只读 `n_written`。
  4. 报告侧：`import_refused` 要落到「摄取披露」章（`app/pipeline.py:1268` 那条渲染路径能吃到 `ingest_notes`，
     别新写渲染分支）。
- **要求（②2，计数口径对齐）**：`_count_ingestible`／`_count_ingestible_capped`
  （`app/ingest/case_loader.py:241/:261`）现在数的是"目录内所有非隐藏文件"，**不按扩展名过滤**——
  隐藏目录里放 500 张 .png 会报「500 个可摄取文件未入卷」，与 `readers.UNSUPPORTED_EXTS` 打架。
  改为**复用 `app/ingest/readers.py` 的后缀路由表**（不许另抄一份名单），只计真能摄取的；
  其中"存在但当前不支持的格式"另起一句「另有 N 个格式暂不支持」，不混进可摄取数。
  C-5 已验收的行为不许回退：仍是**达 cap 早停**、仍是目录名不列文件名。
- **明确禁止**：① 不动 `_collect_files` 的 500／深度 3 两道封顶；② 不动 `MAX_FILES=500`、`MAX_BYTES_*`
  与超限抛错（明确抛错不算静默）；③ 不加 LLM、不改判定与统计口径；④ 不改 `cases/` 任何字节；
  ⑤ 写入侧与解析侧**必须同一套规则**——`safe_relpath`／`resolve_case_file`／`remove_case_files` 三处的深度与
  dot 判定若不一致，须在回写里说明并给出「导入→删除→再导入」闭环证据，否则会出现"导进来删不掉"。
- **要求补的测试（零 LLM，`tmp_path`）**：
  a) 5 段路径两份（`top/a/b/c/一月.txt`＋`二月.txt`）→ `n_written=0`、`n_refused=2`、`reason=deep_path`，
     且磁盘上**不得**出现无扩展名的 `top/a/b/c` 文件（专防覆盖回归）；
  b) 4 段路径 `top/a/b/c.md` → 正常入卷、零拒收（防改得过严，边界与遍历侧对齐）；
  c) `.DS_Store`、`.git/config` → `reason=hidden_path`，披露出原路径；
  d) 单文件 >20MB → `reason=oversize`；
  e) `.materials/` 放 3 个 .png → C-5 的 `n_files` **不再计为 3**（png 不在支持后缀内），不支持格式单列；
     `.materials/` 放 3 个 .md → 仍 `n_files=3`（防把披露改成零）；
  f) 闭环：a) 里被拒的文件不得出现在 `resolve_case_file` 认可路径或工作台删除清单中。
- **验收判据（Qoder 独立复放）**：① `pytest tests -q` 0 失败；② 我把上面那条现状探针原样重跑，
  必须变成 `n_written=0 / n_refused=2 / 磁盘零残留`；③ 自建目录逐项复放 a–f；
  ④ 全仓 `cases/` 零 diff、36 份 `report.json` 无新条目；⑤ 读 diff 确认 `_collect_files` 封顶、
  `MAX_FILES`、`resolve_case_file` 未被顺手改动，且**没有任何重命名/压平逻辑**；
  ⑥ 实跑一次「添加文件夹」链路（`_ing_payload`/`append_imported_files`）确认拒收披露落到返回体与 `ingest_notes`。
- **尾巴（本单不做，写死触发条件）**：~~C 方案＝两侧深度一起抬到 5，让深层目录真入卷。~~
  **触发条件已于 2026-10-16 回答：官方材料最深 3 级** → 现上限本就覆盖，C 方案**撤销**；
  本单的 `deep_path` 拒收对真实材料不会触发，只会挡住人工塞进来的超深目录。
- **状态**：已改完两轮（2026-10-16），**验收通过并已合并 `1703892`**。｜ **验收**：判据 ①–⑥ 第一轮全过、R-C6-1 第二轮复放过＝**通过**。
- **Cursor 回写（R-C6-1，2026-10-16）**：
  - 动了哪些文件：`app/ingest/case_loader.py`（`_count_ingestible` 恢复非隐藏文件数供超深
    `skipped`；`_count_ingestible_capped`／`_hidden_dir_detail` 补图片第三档文案）、
    `tests/test_collect_files_cap.py`（新增 depth4 全 png 用例）、
    `tests/test_import_refuse.py`（png／doc 隐藏目录断言收紧）。
  - 新增用例名：`test_depth4_all_png_still_dir_truncated`。
  - `pytest` 尾行：`553 passed in 4.07s`（552＋1，零 failed）；`git diff --stat cases/` 为空。
  - (a)(b) 均已交：(b) 用既有 `_IMAGE_EXTS` 分档，**未改** `READERS`／`image_disclosed` 语义。
- **架构师复放记录（2026-10-16，独立探针，不采信自述）**：
  - ① `pytest tests -q` = `552 passed in 4.01s`，零 failed（545＋7）。
  - ② 工单「现状」那条覆盖探针原样重跑：`n_written=0 / n_refused=2 / reason=deep_path`，
    盘上仅剩 `manifest.yaml`（旧版会落出一个无扩展名的 `top/a/b/c` 文件并互相覆盖）；
    `load_case` 出两条 `import_refused` 披露并带**原路径全名**，`sources=0`。
  - ③ a–f 逐项自建复放：4 段 `top/a/b/c.md` 正常入卷零拒收（边界与遍历侧一致，没改严）；
    `.DS_Store`／`.git/config` → `hidden_path` 且披露原名；20MB＋1 → `oversize`；
    被拒路径 `resolve_case_file` 返 `None`、`remove_case_files` 记入 refused（闭环成立，
    不会出现「导进来删不掉」）；`/api/case/import` 返回体 `n_refused`／`refused`／`triage` 齐。
  - ④ `git diff --stat cases/` 为空；`_collect_files` 的 500／深度 3 与 `MAX_FILES`/`MAX_DEPTH`/
    `MAX_BYTES_*` 一个没动（`:195/:196/:318`、`import_case.py:15-18` 逐行 sed 核过）；
    diff 内**无重命名／压平逻辑**；无 LLM 调用；体积与文件数超限仍是硬失败（没顺手放宽）。
  - ⑤ 偏离①（拒收账写进 `manifest.import_refused` 再由 `load_case` 展开）**采纳**：拒收文件不落盘，
    不这么绕就进不了报告「摄取披露」章。复放去重：同一超深文件追加两次 → manifest 1 条、报告 1 条（不涨噪音）。
    偏离③（全拒收仍建空壳 `user-*`）**采纳并实测**：`/api/ingest` 正常返回 `n_sources=0`＋`import_refused` 分诊行，
    `/api/history` `n_files=0`，`/api/dossier` 走既有「无研判产物」404——不会白屏。
    偏离②（`resolve_case_file` 同步加深度判定）确认是禁⑤／测试 f 要求的闭环，不是顺手改。
  - **R-C6-1（打回，唯一不通过项）**：后缀过滤被同时用到了 `_collect_files` 的**超深目录计数**上
    （`case_loader.py:366 skipped += _count_ingestible(p)`），而 `_count_ingestible` 现在只数 `READERS` 后缀。
    `CollectResult.truncated` 要求 `skipped > 0`（`:204`），于是**深层目录里全是图片时整条 `dir_truncated` 披露消失**。实测：
    ```
    # 同一套骨架：案目录含 manifest.yaml + a.md（正常入卷），差异只在 top/a/b/c/ 里放什么
    depth4 5个.md  → taken=1 skipped=5 truncated=True  notes=['dir_truncated']
    depth4 5个.png → taken=1 skipped=0 truncated=False notes=[]          ← C-1 承诺回退
    depth4 5个.doc → taken=1 skipped=0 truncated=False notes=[]          ← 同上
    顶层 503个.png → taken=500 skipped=4 truncated=True                  ← 封顶分支仍数全部文件
    ```
    即：同一个 `skipped` 字段在两条分支用了两套口径（`:372` 无条件 `+1`，`:366` 只认可摄取后缀）。
    图片是**有通道的材料**（`case_loader.py:615` 认后缀、`:621` 出 `image_disclosed` 分诊行，OCR 开启时转写为派生信源），
    不是「没有东西」；「含 0 个可摄取文件未入卷」这种句子比不披露更容易让人以为没丢件。
    **修复要求（不改 ②2 的措辞收益）**：
    (a) **必做**——`dir_truncated` 那条计数恢复成「目录内非隐藏文件数」（与 `:372` 同一口径），
        后缀分档只保留在隐藏目录披露文案里；加一条用例：depth4 全 `.png` 必须仍出 `dir_truncated`（防空转回归）。
    (b) **架构师拍板选这个**——隐藏目录披露补第三档「另有 N 个图片文件（未 OCR）」，
        因为它只动文案、不动判定，而图片确实是有通道的材料；
        「含 0 个可摄取文件未入卷」这种句子禁止再出现在有图片的目录上。
        (b) 若你认为要改 `READERS` 或 `image_disclosed` 语义才算干净，**停手登记**，本单只交 (a)。
    Cursor 自己在「发现（未修）」#1 已登记隐藏目录图片那条，但**没发现超深目录这条把 C-1 的披露整条抹掉**——
    那条属结论回退，按协议 §3 不能只登记，必须本单内修。
    （上面这组 `:366`/`:372` 是**修复前**行号，留作取证；修完后分别是 `case_loader.py:259`（无后缀过滤的计数）与隐藏目录文案 `_hidden_dir_detail:331`。）
  - **第二轮复放（R-C6-1，2026-10-16，判＝通过）**：
    - `pytest tests -q` = `553 passed in 3.68s`；`git diff --stat cases/` 为空；
      500／深度 3／`MAX_FILES`／`MAX_BYTES_*` 仍一字未动（`case_loader.py:195/:196/:352`、`import_case.py:15-18`）。
    - **它同时改了既有测试文件 `tests/test_collect_files_cap.py`——逐行看过：纯追加一条用例，既没有任何断言被放宽、
      也没有删用例**（协议禁的是拿放宽阈值／改既有断言当修复）。新用例 `test_depth4_all_png_still_dir_truncated` 断到
      `skipped==5` ＋ `depth_capped is True` ＋ `triage` 有行＋`collected.truncated`，不是空转断言。
    - 我自己造反例复放（同一骨架：`manifest.yaml`＋`a.md`，差异只在 `top/a/b/c/` 里放什么，各 5 份）：
      `.md → skipped=5`／`.png → skipped=5`／`.doc → skipped=5`／`.log → skipped=5`，四条**全部仍出 `dir_truncated`**，
      文案统一「按文件名排序取前 1，另有 5 个文件/更深层目录未入卷」＝与封顶分支同口径。
    - 隐藏目录文案复放：全图片目录 → 「另有 3 个图片文件（未 OCR）」；混合目录 → 三档齐出「含 3 个可摄取…；另有 3 个格式暂不支持；另有 3 个图片文件」；
      全文本目录 → 「含 3 个可摄取文件未入卷」（C-5 原样，没被改坏）；**「含 0 个可摄取文件未入卷」这句在四种目录里一次都没出现**。
    - **零假警报与零噪音回归**：`.git`／`.fetched`／`.venv` 各塞 3 个文件 → 披露 **0 条**；空隐藏目录 → 0 条；
      5005 个文件的隐藏目录 → 0.0s 返回、`files_capped=True`、图片档给「另有 5000 个…；另有更多未计」。
    - C-6 原六条判据在第二轮改动后**重跑一遍仍全过**（拒收／4 段入卷／dot 与超大分原因／去重 1 条／`resolve` 闭环／API 返回体）——
      这轮动的是同一个文件里的共享计数函数，不重跑就不知道有没有把上一轮的成果吃掉。
    - **T-C6-1（尾巴，不阻断）**：目录里只有「三档都不认」的后缀（如 `.log`、`.bin`）时，文案退成「有文件未入卷」**不给份数**——
      披露还在，但比 C-5 那轮弱（那轮无条件给数）。对外口径已按弱的那句写：
      **「每个隐藏目录都给出文件数」这句不成立**，只能说「隐藏目录一定出披露」。修法一行：`_hidden_dir_detail` 补 `n_seen` 总数。
      另：`case_loader.py:383` 那行注释仍写「披露目录名 + 可摄取文件数」，已与实际三档不符，下次顺手改。
  - 尾巴（不阻断合并）：`manifest.import_refused` 只追加不清理——用户把超深材料压平重传后，旧拒收行仍留在报告里，
    属**过期披露**（方向安全：多说不少说），要不要做「重传即清同名条目」另开单定；
    `import_refused` 使 `ROUTE_LABEL` 变成 **17** 个——合并后图上那格已同步成 17 并补「导入拒收」。
- **Cursor 回写**：
  - 动了哪些文件：`app/ingest/import_case.py`（`classify_import_path` 超深改拒收；
    `refused`/`n_refused`；manifest `import_refused` 持久化；`resolve_case_file` 对齐深度／dot）、
    `app/ingest/case_loader.py`（`_count_ingestible*` 复用 `readers.READERS`／`UNSUPPORTED_EXTS`；
    隐藏目录披露加 `n_unsupported`；load_case 注入 `import_refused`）、
    `app/ingest/triage.py`（`import_refused`）、`web/index.html`（导入 toast 显影未入卷）、
    `tests/test_import_refuse.py`（新建）。
  - 新增用例名：`test_deep_path_two_files_refused_no_orphan_on_disk` /
    `test_four_segment_path_accepted` /
    `test_hidden_path_refused_with_original_name` /
    `test_oversize_refused` /
    `test_hidden_dir_count_uses_readers_suffix` /
    `test_refused_deep_path_not_resolvable_for_delete` /
    `test_import_api_refused_in_body_and_notes`。
  - `pytest` 尾行：`552 passed in 4.00s`（545＋7，零 failed）；`git diff --stat cases/` 为空。
  - **偏离工单之处＋原因**：
    1. 拒收清单写入 `manifest.import_refused` 再由 `load_case` 生成 `ingest_notes`／`triage`——
       拒收文件不落盘，否则报告「摄取披露」章读不到（工单要求落 ingest_notes，必须可持久）。
    2. `resolve_case_file` **有意**加了与 `classify_import_path` 相同的深度上限（验收文案⑤写
       「未被顺手改动」易误读）——这是禁止项⑤与测试 f 的闭环要求，不是顺手改。
    3. 全员软拒收时仍建空壳 `user-*`（仅 manifest＋拒收账），以便 `n_written=0` 仍能走
       `_ingest_payload` 披露；路径穿越等硬失败仍 422。
  - **发现（未修）**：
    1. 隐藏目录里的 `.png` 等既不在 `READERS` 也不在 `UNSUPPORTED_EXTS` 时，`n_files=0` 且
       无「格式暂不支持」句——仍会因 `n_seen>0` 出目录披露，但读者看不到「有 3 张图没读」。
       若要把图片也单列，需另单定口径（会动披露文案，本单不扩）。
    2. 正常遍历路径上 `read_any` 对未知后缀仍按纯文本兜底，与计数侧「只认 READERS」不完全同构——
       计数更严；是否收紧 `read_any` 属判定／召回，停手登记。

### C-7 前置实测｜2000 篇规模下三道天花板各自的代价与收益（架构师自测，2026-10-16，未派工、未动生产代码）

- **先纠错**：本节 §5.0 曾把 C-7 写成「需用户拍板『按相关性取』还是『按跨信源配额取』」——**这个问法是错的**，
  它把两道闸当成了二选一。核代码后的真相是三闸串接，不互斥：
  - **闸①（摄取）** `app/ingest/case_loader.py:352` `_collect_files(case_dir, max_files=500, max_depth=3)`，
    排序在 `:370`（`sorted(..., key=lambda x: x.name)` 按文件名）——**发生在读任何正文之前**，
    所以相关性在这一层根本无法参与，它只能决定「谁有资格进候选池」。
  - **闸②（选料）** `app/core/corpus_store.py:225 select()` **本来就按 BM25 相关性取**；
    常量在 `app/core/corpus_index.py:38-40`（`EXPAND_FRACTION=0.30`／`_MAX_SOURCES=50`／`_HITS_PER_SOURCE=6`），
    预算在 `app/config.py:111`（`material_char_budget: int = 80_000`）。
  - **闸③（装箱）** `app/core/material.py:41 pack_material()`，`:83` 起跨信源轮转填充（防单源灌满）。
  → 所以「按相关性取」早已存在（在②），①③各管一段，**没有二选一这回事**。
  顺带修一处行号：**§5.0 C-7 行旧引 `case_loader.py:345` 是错的**（那行是 `chunks.append("另有更多未计")`），
  上限在 `:352`、按名排序在 `:370`；图上同一处旧引用同日已改。
- **复放命令**（零 LLM、零网络，产物只落 `/tmp/c7_bench`；本机全程 21.9s。两次复放：份数／段数／库体积**逐项一致**，
  `select()` 连续三跑同为 20 份与 21 份＝确定性；耗时抖动 ±0.3s）：
  ```
  PYTHONPATH=. .venv/bin/python scripts/measure_capacity.py
  ```
  **口径声明**：今天上午那版 `/tmp` 手工探针给过 22 份／121 段，与本脚本的 20／21 份不一致，差异原因**未查**；
  自本条起**以仓库脚本为唯一口径**，旧探针数字作废（写进任何文档的 22 份都要按此改）。
- **[实测] 表**（2000 份 × ~3000 字合成材料＝15.2MB，2 层目录，议题「华东集团1的停工与欠薪风险有多大？」）：

  | 量 | 现口径（①封顶 500） | 抬①到全量 2000 | 读法 |
  |---|---|---|---|
  | ① 遍历 | 0.01s，taken=500／skipped=1500／truncated=True | — | 遍历本身不要钱，钱在「1500 份连被读的资格都没有」 |
  | `load_case` | 0.06s／3500 段／峰值 RSS≈33MB | 0.21s／14000 段／RSS≈54MB | **+0.15s，均摊 0.1ms/份——摄取向近乎免费** |
  | `.corpus` 建库 | **3.31s／25.5MB／live=500** | **15.75s／103.1MB／live=2000** | **+12.4s／+78MB；且 `create()` 每次先 `unlink` 旧库（`corpus_store.py:89-90`）＝无增量缓存，每跑一次研判付一次全额** |
  | 8 万字预算下真正进案卷 | **20 份／116 段**＝库内 4.0% | **21 份／119 段**＝库内 1.1% | **只多看见 1 份** |

- **预算扫描**（`select()` 实测，同一库）：8 万→20 份／116 段；16 万→39 份／233 段；
  **32 万→50 份／300 段／14.2 万字；64 万仍是 50 份**——撞上 `_MAX_SOURCES=50 × _HITS_PER_SOURCE=6` 的硬顶（≈14.3 万字封顶）。
- **结论（直接决定 C-7 怎么出单）**：
  1. **抬①买的是候选池，不是可见性**：20 份→21 份。单抬①＝每次多付 12.4s＋78MB 只多看见 1 份材料，**这单不能这么出**。
  2. **真正的召回天花板在②**：默认口径下 2000 篇只有 **20 份（1%）**进得了案卷。
     ②要抬就得**预算与 `_MAX_SOURCES` 一起抬**——只抬预算会撞 50 份墙（64 万实测仍 50 份），
     只抬 50 份仍被 8 万字预算挡在 20 份。
  3. **预算上界不由我们定，由现场模型的上下文定**：**同日已测完 → 见下方 §「C-9 前置实测」**。
     本地 14B 默认 `num_ctx=16384` 约吃得下**2.4 万字**（中文 ≈0.69 tok/字 折算；实测两端＝2 万全中／8 万被剪），
     **连现在的 8 万字默认预算都是超发约 3.4 倍**——所以「把预算抬到 32 万字」这条在本地模型上**直接不成立**。
- **待用户拍的三选一（改写后的口径）**：
  - **A 成套抬**（①500 变可配 ＋ ②预算与 `_MAX_SOURCES` 同步抬）：原以为收益最大，**C-9 实测后 A 的「抬预算」半段作废**——
    窗口才是第一约束；剩下可做的只有「①变可配」＋「按窗口收窄预算」，而后者已并入 C-9 的乙。
    成本已知＝建库 15.8s／103MB 每次。**成套抬在本地模型上不可行，云端窗口未测。**
  - **B 首屏相关性预选**（①先扫全文再决定哪 500 进案卷）：召回上界仍被②的 50 份卡死，却要照付 A 的建库成本——
    **性价比最差，除非与 A 的②同做。**
  - **C 只把 500／深度 3 做成可配**（env＋manifest，默认值不变）：零判定风险、开箱可跑、现场按材料量自救；
    **不解决召回，只解决「现场被自己的上限挡死」**。
  - 架构师建议：**先出 C**（独立可验收）；**优先级已让位给 C-9**——窗口这道口子既不披露又直接吃掉议题与纪律，
    比「候选池只有 500」更靠前。
  - **已拍（10-16「按你的建议来」）＝只做 C**，工单见下方 §「C-7」；A／B 均不再出单（A 的抬预算半段被 C-9 否掉，B 性价比最差）。
- **本轮不动代码**：`scripts/measure_capacity.py` 是架构师探针，非生产路径、不进 `tests/`；
  输入层判定、常量、默认预算一律未改。

### C-9 前置实测｜第四道天花板＝模型窗口：超发不报错、零披露（架构师自测，2026-10-16，用户已授权用本地 14B）

- **发现经过**：给 C-7 选项 A 定价时要知道「32 万字装不装得下」，于是把材料真发给本机 Ollama 量了一下。结论是
  **A 的预算方向从一开始就错了**——装箱器按**字**算预算，模型按 **token** 吃，两者之间没有任何一道校验或披露。
- **复放命令**（零云端花费，只用本机 Ollama；`CHARS=` 可自选字数）：
  ```
  PYTHONPATH=. .venv/bin/python scripts/probe_context_window.py
  ```
  仓库脚本首跑输出（与手工探针逐字一致）：
  `20000字 → 服务端报输入 14674 tok，85s | 系统代号中 议题代号中 末段代号中`
  `80000字 → 服务端报输入  8194 tok，  1s | 系统代号丢 议题代号丢 末段代号中`
  （80000 字那次只用 1 秒＝前缀缓存命中，正好说明**报上来的 token 数不能当证据**，能当证据的只有暗号能不能复述。）
- **环境（实测，非推演）**：Ollama 0.40.2 @ `127.0.0.1:11434`，模型 `veritas-qwen3-14b`（qwen3 14.8B）。
  `/api/show`：原生 `qwen3.context_length = 40960`，但 **Modelfile 把 `num_ctx` 钉在 16384**。
  代码侧：全仓库 grep 无 `num_ctx`、无 Ollama 特判（`app/llm/model_client.py:512` 只带 `max_tokens=max_response_tokens`）
  ＋ `config.json` 的 `max_response_tokens=6000`、`llm_timeout_seconds=300`。
- **中文 token 密度**（`/api/generate` 三点拟合）：2000 字＝1400 tok、8000 字＝5513 tok、20000 字＝13744 tok
  → **≈0.69 tok/字**（即 1 万 token ≈ 1.45 万字）。
- **决定性探针：把暗号分别放进「系统提示词开头／议题行／资料最末」，走生产同一条路（litellm→Ollama OpenAI 兼容端点）**：

  | 材料字数 | 服务端报的输入 token | 系统代号 | 议题代号 | 末段代号 |
  |---|---|---|---|---|
  | 20,000 | 14,674（未截断） | 中 | 中 | 中 |
  | **80,000（＝现默认预算）** | **8,194** | **丢** | **丢** | 中 |

  → **超发时 Ollama 不报错，直接把提示词从头剪掉、保住尾部**：丢的正是「角色与纪律」＋「研判议题」本身，
  模型仍在正常输出，但它是**在没有议题、没有纪律约束的状态下**答的。
  用 `num_ctx=40960` 再测：48,000 字读得到（**单次 274 秒**，逼近 300 秒墙钟闸），64,000 字仍丢（报 20,482 tok）。
  **口径说明**：`prompt_eval_count` 在截断/前缀缓存下不呈线性（8 万次跑出恒定的 8194），所以本表以**暗号能否复述**为准，不以计数为准。
- **[实测＋折算] 阈值**：默认 `num_ctx=16384` → **约 2.4 万字**（16,384÷0.687 折算，**边界未逐点实测**；
  实测只钉住两端：2 万字三代号全中、8 万字系统＋议题代号都丢）；抬到原生 40960 → 约 5.7 万字（同一折算；
  实测 4.8 万字读得到但**单次 274 秒**，贴住 `llm_timeout_seconds=300`，6.4 万字仍被剪）。
  **`material_char_budget` 默认 8 万字在任何本地档都是超发 3.6 倍**；抬预算这条（C-7 的 A）在本地模型上**不成立**。
  云端那批模型（`config.json` 里 qwen3.8-max 等）窗口未测——**没花用户的钱，不擅自调用**。
- **为什么这道口子比 500 封顶更阴**：① 发生在**所有披露都写完之后**——分诊账本、装箱 `excluded`、报告「本次纳入 M 份／5.6 万字」
  统计的都是「我们没塞进去的」，对「塞进去了但被服务端切掉的」完全无声；② 丢的不是某一段材料，
  而是**提示词最前面的东西**（纪律＋议题）——属**结论质量**问题，不只是召回；③ 大库场景必然触发
  （演示小案只有几份材料、远在阈值下，所以**今天所有小案例跑不出这个问题**，恰好是「文档口径的绿不算绿」的反面教材）。
- **立项建议 C-9（修复方向待用户拍板，会改结论故不停手直接派工）**：**已拍（10-16「按你的建议来」）＝先丙，工单见下方 §「C-9」。**
  - **甲 预算按 token 不按字**（`material.py:56` 的 `len(seg.text)` 换成按模型密度折算）——治本；
    但需要每个模型一个密度，且**离线时拿不到真 tokenizer**，属工程取舍。
  - **乙 发送前窗口校验＋超发即降预算**（把 `num_ctx`/模型窗口变成配置项，装箱时以窗口为准）——**最小可靠**，
    零 LLM、开箱可跑，代价是要新增一项配置。
  - **丙 先只加披露**（超发即写 `ingest_notes`/`triage`：「提示词≈X 字 ≈Y token，超模型窗口 Z，已截断」）——
    **不修召回，只把「漏了但知道漏了」这句重新补齐**，与 C-1/C-5/C-6 同族，风险最低。
  - 架构师建议：**先丙后乙**（丙让账面重新诚实，乙让窗口成为受控量；甲留到有多模型清单需求时再说）。
- **对外口径立刻改两处**（不许等修完再改）：
  1. 图上「预算装箱：装不下的段落全部披露不静默丢」**必须加边界**——「装不下」指**装箱器层面**；
     装箱器之外还有模型窗口这一道，**当前不披露**（本条）。
  2. 「漏了但知道漏了」这句自本条起**又有一个已知例外**：模型窗口超发。原口径写的是「输入层 7 道全部披露」，
     这句仍然对**输入层**成立，但**第四道天花板不在输入层，在出口**，答辩时不能说成「所有层都披露」。

### C-9｜模型窗口超发＝提示词被服务端静默剪头（**本单只做丙：先让账面诚实**，2026-10-16 出单）

- **口径已拍（2026-10-16 用户「按你的建议来」）**：先做**丙＝只加披露**，不做乙（窗口变装箱约束）、不做甲（预算按 token 折算）。
  理由：这道口子的危害是**报告说"已纳入"而模型没看到**，账面先恢复诚实；收窄与折算属判定／召回改造，另单再拍。
- **现状（已核代码＋已实测）**：
  - 提示词结构＝`app/agents/base.py:65-72`：`system`（角色＋skill 纪律）→ `user`（**第一行是「研判议题」**，随后是资料清单）。
  - 装箱按**字**：`app/config.py:111 material_char_budget=80_000`，`app/core/material.py:56` 用 `len(seg.text)`；
    全仓 **无 `num_ctx`、无 token 计数、无截断披露**（`app/llm/model_client.py:512` 只带 `max_tokens`）。
  - 实测（`scripts/probe_context_window.py`，本机 Ollama `veritas-qwen3-14b`，`num_ctx=16384`）：
    20000 字＝三代号全中；**80000 字＝系统代号与议题代号都丢、只剩末段**——服务端剪头保尾且不报错。中文密度 **≈0.69 tok/字**。
- **要求（只做这三件）**：
  1. `app/config.py` 新增两项，走**现有 env＋config.json 覆盖机制**（与 `material_char_budget` 同一列白名单，见 `config.py:232`）：
     `model_context_tokens: int = 16384`（`VERITAS_MODEL_CTX_TOKENS`）、
     `zh_chars_per_token: float = 1.45`（`VERITAS_ZH_CHARS_PER_TOKEN`，＝1/0.69，注释须写明来源是探针实测）。
     **`model_context_tokens <= 0` ＝ 关闭本检查**（关的时候要能在报告里看到"未检查"，不许静默当"没超"）。
  2. 新增一个**纯函数**（建议 `app/core/prompt_guard.py`）：入参＝已渲染的 `messages` ＋ settings，
     出参＝`{"est_tokens", "window_tokens", "overflow_tokens", "detail"}`；估算＝`Σ len(content)` 字 × `1/zh_chars_per_token`，
     **零 LLM、零依赖、不引入 tiktoken**。
  3. 接在 `Analyst.analyze`（`base.py:65` 组装 messages 之后、`client.chat` 之前）：
     估算超窗口 → 往 `dossier.ingest_notes` 追加一条**稳定 kind**（建议 `prompt_over_window`）＋一条同 `route` 的 `triage`，
     文案必须含「≈N token＞窗口 W，超出约 O token（≈M 字）服务端会**从提示词头部静默剪掉**，角色纪律与研判议题可能未到达模型」，
     并在报告「摄取披露」之外**单列一行出口披露**（`app/pipeline.py` 渲染处，与 `:1268` 同族）。
     **只写 logger 不算——必须 `report.json` 里读得到。**
- **明确禁止**：① **不许**据此自动收窄预算或改 `material_char_budget` 默认 8 万（那是乙，未拍板）；
  ② **不许**加 tiktoken／新依赖（U 盘离线包）；③ **不许**动 `tests/conftest.py` 禁真调用守卫；
  ④ **不许**动 `cases/` 任何字节；⑤ **不许**"顺手"把议题／纪律挪到提示词尾部——那是止血改判，另单拍板（见下方「发现」）；
  ⑥ **不许**在非分析师路径（arbiter／chair／repair）铺开，本单只交主路径，其余登记尾巴。
- **验收判据（Qoder 独立复放，开箱可跑；a/b/d 于 2026-10-16 由架构师按 §3.4 质疑 1 改写，原口径见「架构师复放与答复」）**：
  - `.venv/bin/python -m pytest tests -q` → 0 failed，passed ≥ 559（553＋新增≥6），且**连跑 5 次必须次次绿**
    （只跑一次绿不算——`test_panel_single_failure_degrades` 是顺序敏感的，见 R-C9-1）。
  - 新增用例（`tmp_path`＋既有 stub client，零真调用）：
    a) **渲染后 messages 估算超窗**（用「段数×段长≤650」凑出 ≈3 万字真发量，或直接走 `cases/bi-delivery-risk`）
       ＋`VERITAS_MODEL_CTX_TOKENS=16384` → `report.json` 出现一条 `prompt_over_window`，数字与手工估算一致；
       **原写法「造 9 万字材料」作废**——单段 9 万字会被装箱器整段剔除，渲染后只剩 53 字议题壳，照字面做必然测不到。
    b) **渲染后未超窗**（≈4,800 字）＋同窗口 → **不得**出该条（防空转假披露）；**原「2 万字」锚点作废**（同样受 a 的剔除影响）。
    c) `VERITAS_MODEL_CTX_TOKENS=0` → 不出条，且报告能看到"未检查"字样；
    d) 默认不设 env → **小案卷（`demo-solid-state`／`rumor-vs-official` 量级）产物字段零变化**；
       **注意默认是开的**，`bi-delivery-risk` 这类真超窗案例**会新增一章**，这是预期行为不是回归（原判据写"现有产物零变化"＝失实，已改）；
    e) 真路径钉死（R-C9-2）：载入 `cases/bi-delivery-risk` → 默认设置下 `overflow_tokens > 0` 且 est ≈19,378（±5%）；
    f) 热路径零配置读（R-C9-1）：`run_panel` 三个分析师全程 `Settings.from_env` 调用次数 **＝ 0**。
  - `git diff --stat cases/` 为空（**只钉得住信源输入**：`cases/*/out*/` 被 `.gitignore:27/:29` 忽略，报告变化看不见）；
    `git diff tests/conftest.py` 为空。
  - 架构师另跑（不要求 Cursor 跑，环境依赖）：`PYTHONPATH=. .venv/bin/python scripts/probe_context_window.py`
    输出须与本节实测表逐字一致，用来复核披露文案里的密度常数没被改飘。
- **发现（未修，登记）**：
  1. **最便宜的止血是把「研判议题＋纪律」挪到提示词末尾**（剪头保尾→尾保纪律）。但这改的是提示词结构＝判定行为，
     按协议 §3 **会改结论的一律停手交拍板**，本单不含。
  2. `arbiter`／`chair`／`repair`／`profile 探测` 走同一批长提示词，同样会被剪头，本单只接分析师主路径。
  3. 云端模型窗口未测（没花用户的钱），`model_context_tokens` 默认 16384 是**本机实测值**，
     接大窗口云端模型时会**多报**一条超窗披露——方向安全（多说不少说），但要在文案里写明"按假定窗口"。
- **开工提示词（协议 §9.1，用户整段粘贴给 Cursor；本单在前，C-7 在后——两单都要改 `app/config.py:232` 白名单）**：

```
读 docs/dev-protocol.md（分工协议，重点 §3 问题分流、§6 三道纪律）和 docs/HANDOFF.md §5 的工单 C-9，你是执行工程师。
本单只做「要求」列出的三件事＝模型窗口超发的出口披露。实现细节以该单原文为准，不要照本提示词施工。
先做协议 §3.0 前提核查再动工：单里的行号还在不在、要求指的位置是不是真因、照做完判据 a/b/c/d 会不会真出现；
本单「本单前提的两处已知薄弱点」那一段是我自己标出来的存疑处，请用实测判定，别默认我对。
允许动的落点：app/config.py（新增两项＋加进 config.py 的 config.json 覆盖白名单）、
新建 app/core/prompt_guard.py（纯函数、零 LLM）、app/agents/base.py 的 Analyst.analyze（组装 messages 之后、client.chat 之前接入）、
报告渲染处（与 pipeline.py「摄取披露」同族，单列一行）、ingest_notes 与 triage 出口、新增测试。
明确禁止：不改 material_char_budget 默认值、不据估算自动收窄预算、不加 tiktoken 或任何新依赖、
不动 tests/conftest.py、不动 cases/ 任何字节、不把议题／纪律挪到提示词尾部、不铺到 arbiter／chair／repair／profile 探测。
开发中若发现问题按协议 §3 分流：本单内的就地修并写「偏离工单之处＋原因」；
会改 report.json 已有字段取值的停手写提案；新洞只记「发现（未修）」。
若你判定这张单的策略／口径／验收判据**本身**是错的（不是做不到，是这么做不对），按协议 §3.4 写「工单质疑」：
错在哪（引工单原句）｜实测证据（命令＋真实输出）｜建议改成什么。质疑是义务不是冒犯，我会同一轮答复；
但"我觉得更优雅""这个应该顺便做全"不算质疑，也不要明知单写错了还照着做完好交差。
完成后回写：工单状态行改「已改完（YYYY-MM-DD），待架构师验收」＋动了哪些文件＋新增用例名＋pytest 尾行。
自查判据：pytest tests -q 0 failed 且 passed≥556；a/b/c/d 四条用例齐（b 是反向断言，只改文案不改条件要能被抓到）；
git diff --stat cases/ 与 git diff tests/conftest.py 均为空。
不要提交，不要 push，验收归 Qoder。
```

- **本单前提的两处已知薄弱点（§3.0 核查时就着实测判，别默认我对）**：
  1. 要求 2 的估算只算**发出去的 prompt**，而 Ollama 的 `num_ctx` 是 prompt＋输出共用——`app/config.py:84`
     `max_response_tokens=8_000` 会随 `max_tokens` 一起发（`app/llm/model_client.py:512`）。
     按现写法会**偏晚**报（该报的时候没报）。若实测证明偏晚，属**判据本身要改**→ 按 §3.4 上报，不许自己挪阈值（判据 b 钉着）。
     **（2026-10-16 结案：执行方据此提出质疑 2，架构师用本单前置实测表驳回——2 万字那次 14,674＋6,000＞16,384 却未剪头，
     服务端挤占输出不剪 prompt；挪阈值会把没超的判成超＝假警报。尾巴 T-C9-3＝换模型必重标。）**
  2. `zh_chars_per_token=1.45` 来自探针的**合成重复文本**，真实材料密度可能不同 → 文案必须写"估算"，
     不许写成精确值；实测偏离大就带数据上报。
- **状态**：已收口（2026-10-16）。｜ **验收**：第一轮不通过（证据见下方「架构师复放与答复」）；第二轮 R-C9-1／R-C9-2 **架构师独立复放＝通过**（559×5 次绿、from_env/from_json 双 0、est=19399 偏差 0.11%、flake 3/20≤6）。**遗留：flake 根因未除，转 C-10。**
- **架构师复放与答复（2026-10-16，Qoder，逐条自己跑过，不吃自述）**：
  - **复放记录**：`.venv/bin/python -m pytest tests/test_prompt_window.py -q` → 4 passed（0.65s，独立跑稳）。
    全量 `.venv/bin/python -m pytest tests -q` → **8 次里 3 次红**，红的都是 `tests/test_collab.py::test_panel_single_failure_degrades`；
    `git diff --stat cases/` 空、`git diff tests/conftest.py` 空（两条自己核过）。
    变异刷（`-p always_overflow` 把 `estimate_prompt_window` 改成"只要检查了就报超窗"）→
    **b/d 双双失败**，证明它们守的是判定条件不是文案＝反向断言有效。
    **基线复放环境**：`git worktree add /tmp/vh_head HEAD`（同一 `.venv` 解释器，符号链接过去）里跑 20 次＝失败 6 次；
    当前工作树同法 20 次＝13 次、10 次＝6 次。该干净树里 `test_mcp_server.py::test_stdio_protocol_list_and_read` 会假失败
    （venv 是符号链接、子进程起不来），主树单跑 2 passed＝与本单无关，别误记成回归。
  - **§3.4 质疑 1（判据 a/b 字面写不出）＝成立，属判据写法层面、不改结论 → 判据已按下方改写，偏离接受**。
    我自己复放了它的实测：单段 9 万字 → `pack_material` 选中 **0 段**、渲染后 **53 字**（只剩议题壳）、`overflow=0`。
    顺带量出一个**新的真洞**：整段字数 ＞ 整卷预算（8 万）时该段被**整段剔除**，模型只收到议题壳——
    这不是超发，是**单段超预算静默失踪**，须查它进不进「未采信信源」披露 → 登记为 **C-11**（见 §5.0）。
  - **§3.4 质疑 2（该把阈值改成 `窗口 − max_response_tokens`）＝驳回，证据在我今天那张表里**：
    20,000 字那次服务端报输入 **14,674 tok 未截断、三代号全中**，而当时 `config.json` 的 `max_response_tokens=6000`——
    14,674＋6,000＝**20,674 ＞ num_ctx 16,384**，若服务端真为输出预留而剪 prompt，那次就该丢代号，**但它没丢**。
    即本机这版 Ollama 是**挤占输出、不剪 prompt**。按质疑改阈值＝10,384 tok（≈1.5 万字），
    则实测**没被剪**的 2 万字那次会被判"该报"＝**假警报**；假报比晚报更伤，因为"报了就真丢"是这条披露全部的公信力。
    **采纳其中半条**：文案必须写明是假定窗口（要求 3 已写，实现里已带「按假定窗口」字样，核过）；
    "未计入输出预留、现场换模型须用暗号复述法重标"登记为尾巴 T-C9-3。
  - **我自己的两处失实（当场认，已改）**：
    ① 原判据 d「默认不设 env → 现有产物字段零变化」**只在 1 段小案卷上成立**。实测默认（窗口 16384、无 env）
      六个案例里**三个会新增「模型窗口出口披露」一章**：`bi-delivery-risk` 渲染后 28,099 字 ≈19,378 tok（超 2,994）、
      `user-20261008-143622` ≈23,975（超 7,591）、`user-20261008-144308` ≈26,460（超 10,076）；
      `demo-solid-state` ≈1,847／`rumor-vs-official` ≈1,566／`user-...142002` ≈3,422 不触发。
      这是**正确行为不是回归**（它们确实超本机窗口），但原判据把它写成"零变化"＝口径失实，判据 d 已改写。
      另记一条判据工具缺陷：`cases/*/out/`、`cases/*/out_offline/` 被 `.gitignore:27/:29` 忽略，
      **`git diff --stat cases/` 钉不住报告变化**，只能钉住信源输入——"零回归"以后必须用产物字段计数或本条这类实测。
    ② 「小案例跑不出这道口子」（图上三处、本单前置实测一处）**已被实测推翻**：6 份材料、66 段的 `bi-delivery-risk`
      就超窗 18%。触发条件不是"大库"，是**案卷渲染后超过约 2.4 万字**。图与前置实测段已同步改严。
      另外那里流传的「窗口只吃得下约 2.2 万字」**没有实测点**：实测只钉住 2 万字全中／8 万字被剪，
      2.2 万这个数对不上自己的密度拟合（16,384÷0.687≈**23,841 字**）→ 口径改成"≈2.4 万字（按拟合密度折算，边界未逐点实测）"。
  - **返工要求（两条，均可开箱验证）**：
    - **R-C9-1（本单内，必须修）**：`Analyst.analyze` 每调用一次就 `Settings.from_env()` 一次（`base.py:75`），
      而 `from_env()` 第一件事就是 `from_json()`（`config.py:183`）＝对 `config.json` 做一次 `is_file()`＋`read_text()`＋`json.loads()`，
      收尾还要 `validate()`（`config.py:235-246`）——**每个分析师每一轮都付一次磁盘读＋JSON 解析**。
      `run_panel`（`app/agents/panel.py:93-94`）用 `ThreadPoolExecutor` 并行提交每个分析师，
      这些 IO 落在共享 `ScriptedClient` 队列的抢答窗口里，把一条 8% 的潜伏竞态放大到约 50%（数据见 R-C10-1）。
      改法＝**热路径不现读配置**：把 settings 由构造注入（`Agent` 是数据类，见 `app/agents/base.py:38-43`，加字段最干净），
      或模块级一次性缓存。**判据**：a) `Settings.from_env` 在 `run_panel` 三个分析师全程被调用 **0 次**
      （用例里 monkeypatch 计数器断言，零真调用）；b) `for i in $(seq 1 20); do .venv/bin/python -m pytest
      tests/test_collab.py::test_panel_single_failure_degrades -q; done` 的失败次数**不高于 HEAD 基线**
      （基线自己量：`git worktree add /tmp/vh_head HEAD` 后同法跑，本次实测 6/20）；c) 全量 `pytest tests -q` 连跑 5 次**全绿**。
    - **R-C9-2（本单内，补一条真路径用例）**：现有 a/b 用的是自造案卷，钉不住"披露在真案例上真会亮"。
      新增用例 e) 载入 `cases/bi-delivery-risk`（零 LLM，只走到渲染＋估算，**不许真调用、不许写 `cases/`**）
      → 断言 `estimate_prompt_window(...)` 默认设置下 `overflow_tokens > 0`，且数值与 **19,378** 同量级（±5%）——
      把"默认就超本机窗口"这件事钉进测试，防止以后有人把默认窗口调大来"消灭"这条披露。
- **返工开工提示词（第二轮；协议 §9.1，判据已改写＝须重贴）：整段粘给 Cursor**

```
读 docs/dev-protocol.md（重点 §3.0、§3.2、§3.4、§6）和 docs/HANDOFF.md §5 工单 C-9 的「架构师复放与答复」＋「返工要求」，你是执行工程师。
第一轮验收不通过。本轮只做 R-C9-1、R-C9-2 两条返工，披露本体（prompt_guard 的估算与文案）一行都不许改。
R-C9-1：Analyst.analyze 的热路径不得再现读配置——现在每次调用都 Settings.from_env()（里面先 from_json() 读 config.json，收尾再 validate()）。
  改成构造注入（Agent 是数据类，见 app/agents/base.py:38-43）或模块级一次性缓存，二选一并在回写里写清为什么选它。
R-C9-2：补一条真路径用例：载入 cases/bi-delivery-risk（零 LLM，只走到渲染＋估算，不许真调用、不许写 cases/ 任何字节），
  断言默认设置下 overflow_tokens>0 且 est≈19378（±5%）。
判据（我会逐条独立复放）：
  a) run_panel 三个分析师全程 Settings.from_env 被调用次数＝0（用例里计数器断言）；
  b) .venv/bin/python -m pytest tests/test_collab.py::test_panel_single_failure_degrades -q 连跑 20 次，失败次数 ≤6（HEAD 基线实测 6/20）；
  c) 全量 .venv/bin/python -m pytest tests -q 连跑 5 次，次次 0 failed，passed≥559；
  d) git diff --stat cases/ 为空、git diff tests/conftest.py 为空。
明确禁止：不挪估算阈值（质疑 2 已带实测驳回，判据 b 用的是渲染后口径）、不改 estimate_prompt_window 的判定方向、
不加 tiktoken 或任何新依赖、不动 material_char_budget 默认值、不加 LLM、不动 tests/conftest.py 守卫、不铺 arbiter／chair／repair／profile。
若你认为 R-C9-1 这两种改法都不对，按协议 §3.4 带实测证据质疑，别自行选第三种写法。
完成后回写：状态行改「已改完（YYYY-MM-DD），待架构师验收」＋动了哪些文件＋新增用例名＋pytest 尾行＋20 次 flake 复放的真实计数。
不要提交，不要 push，验收归 Qoder。
```
- **Cursor 回写**：
  - 动了哪些文件：`app/config.py`（`model_context_tokens`／`zh_chars_per_token`＋env／json 白名单）、
    `app/core/prompt_guard.py`（新建）、`app/agents/base.py`（`Analyst.analyze` 发送前披露）、
    `app/pipeline.py`（`_render_prompt_window`＋accounting 白名单）、`app/ingest/triage.py`、
    `tests/test_prompt_window.py`（新建 a/b/c/d）。
  - 新增用例名：`test_overflow_large_prompt_writes_prompt_over_window` /
    `test_under_window_no_false_disclosure` /
    `test_ctx_zero_unchecked_in_report` /
    `test_default_env_no_overflow_note_on_small_case`。
  - `pytest` 尾行：`557 passed in 4.23s`（553＋4，零 failed）；`git diff --stat cases/` 为空；
    `git diff tests/conftest.py` 为空。
  - **§3.0 前提核查（协议更新后补记，动工时已踩到、现按正式格式落盘）**：
    ① 行号：`base.py` 组装 messages 仍在 `:65+`（现接入点紧随其后）；`config.py` 白名单仍在
    `from_json` 的 `material_char_budget` 那列（已扩两项）；`model_client.py:512` 一带仍发 `max_tokens`。
    ② 真因位置：超发发生在**服务端剪头**，本单接在 `client.chat` 之前估 messages——位置对，只披露不截断＝丙。
    ③ 判据 a/b **字面**「造 N 万字材料」按生产路径**不会**得到工单承诺的输出（见质疑 1）——故用例改为控渲染后体量。
  - **偏离工单之处＋原因**：用例 a/b 未按「整段 9 万／2 万字」塞单段——见质疑 1；改为多段×600 字控制
    **渲染后** messages 超／未超窗，手工估算仍与落盘数字对齐。
  - **工单质疑（§3.4，待架构师同一轮答复）**：
    1. **错在哪**：验收「a) 造 9 万字材料…出现 prompt_over_window」「b) 造 2 万字材料…不得出该条」。
       **实测**：单段 90000 字 → `pack_material` `n_selected=0`（段长＞`material_char_budget=80000` 整段剔除）、
       `render_segments_block` 仅 53 字（只剩议题壳）、`estimate_prompt_window` `overflow_tokens=0`——
       **照字面做 a 会失败、且假阴性**。根因：`prompts.py:68-69` 默认 `per_segment_chars=SEGMENT_MAX(650)`，
       装箱按全段字数、提示词按 650 截断，两套字数不是一回事。
       **建议改成**：判据 a/b 改为「渲染后 messages 估算超／未超窗」（或先修装箱↔截断同构，那是另单）。
    2. **错在哪**：本单薄弱点已写「估算只算 prompt、`num_ctx` 与输出共用会偏晚报」；要求仍用满窗 `model_context_tokens`
       与判据 b 钉死「2 万字不得出条」。
       **实测**（`Settings.from_env()`：`model_context_tokens=16384`，`max_response_tokens=6000`）：
       共享后提示词可用 ≈10384 tok；多段凑满约 2 万字渲染后 `est_tokens=14157` →
       对满窗 `overflow=0`（判据 b 过），对共享窗 `overflow≈3773`（**该报未报**）。
       **建议改成**：估算阈值改为 `window_tokens - max_response_tokens`（或配置「留给输出的 tok」），
       并改写判据 b 的字数锚点；**会改何时亮灯**＝可能动报告字段出现时机，属结论边界，冻结等拍板。
       现实现**未自行挪阈值**（遵薄弱点原文）。
  - **发现（未修）**：
    1. 装箱 `used_chars` 与提示词真发量脱节（全段 vs 650 截断）——与质疑 1 同源，另单定是否收齐。
    2. 工单「发现」栏既有三条（挪尾止血／非分析师路径／云端窗口）本单未动，维持登记。
  - **第二轮回写（R-C9-1／R-C9-2，2026-10-16）**：
    - **§3.0**：`base.py:75` 仍是 `Settings.from_env()`（返工前）；`from_env` 首行仍 `from_json()`（`config.py:183`），收尾 `validate()`。
      真因是并行 `analyze` 里的读盘，不在估算函数。去掉热路径读盘后，判据 a 的计数能到 0、b 的失败次数能压回基线以内（见下）。
    - **选构造注入，不选模块级缓存**：`Agent.__post_init__` 在 `settings is None` 时读一次并钉在实例上；`analyze` 只用 `self.settings`。
      模块级懒缓存的第一次命中会落在 `run_panel` 里第一个 `analyze`，判据 a 要求全程 **0 次**，对不上；
      进程级缓存还会把 `monkeypatch` 改过的 `VERITAS_MODEL_CTX_TOKENS` 冻住，串味到后一个用例。
    - 动了哪些文件：`app/agents/base.py`（`settings` 字段＋`__post_init__`；`analyze` 不再 `from_env`）、
      `tests/test_prompt_window.py`（f／e）。`prompt_guard.py` 未改。
    - 新增用例名：`test_run_panel_analyze_does_not_reread_settings` /
      `test_bi_delivery_risk_default_overflow`。
    - `pytest` 尾行：连跑 5 次均为 `559 passed`（约 4.2–4.3s），次次 0 failed。
    - 20 次 flake：`test_panel_single_failure_degrades` 失败 **2/20**（第 7、9 次；判据 ≤6）。
    - `git diff --stat cases/` 为空；`git diff tests/conftest.py` 为空。
    - 真路径探针（主流 persona＋skills，默认窗口）：渲染后 est=19399、overflow=3015，落在 19378 的 ±5% 内。
  - **架构师第二轮复放（2026-10-16，Qoder，判据逐条自己跑，不吃上面的自述）＝通过**：
    - **c 全量**：`.venv/bin/python -m pytest tests -q` 连跑 5 次 → 次次 `559 passed`（4.28–4.48s），0 failed。
      559＝553＋新增 6，与判据「passed≥559」对齐。
    - **d 卫生**：`git diff --stat cases/` 为空、`git diff tests/conftest.py` 为空（复放前后各查一次，均空）。
      禁真调用守卫 `tests/conftest.py:18 arm_no_real_calls()` 未被绕过——我自己的探针也上了同一道膛。
    - **a／f 热路径零配置读**：我不用 Cursor 那条用例，自己写探针（`/tmp/replay_c9_ef.py`，
      线程安全计数器，`run_panel` 走真 `ThreadPoolExecutor`）：
      构造期 `build_panel` 三人 `settings` 均已钉住且 `model_context_tokens=16384`（非零、非默认空壳）；
      计数器归零后跑 `run_panel(cases/bi-delivery-risk, 三人)` →
      **`Settings.from_env` 调用 0 次、`Settings.from_json` 调用 0 次**（我比判据多量了 `from_json`，
      因为 `from_env` 首行就是它，只堵外层等于没堵），桩 client 被调用 3 次、`_failures` 为空。
    - **改法没把功能改哑（我自己加的一条，判据里没有）**：同一次 `run_panel` 之后，
      `bi-delivery-risk` 的 `ingest_notes` 里 `prompt_over_window` **恰好 1 条**（三人同卷去重生效）、
      `triage` 1 条、`accounting.prompt_window.status="overflow"`，且披露里的 `est_tokens=19399`
      与我独立渲染估算的 19399 **逐位相同**——证明构造期钉住的那份 Settings 真的被热路径用上了，
      不是「计数归零因为披露整条不跑了」。
    - **e／R-C9-2 真路径**：`load_case(cases/bi-delivery-risk)` + 默认 `Settings()`（**我没调
      `set_material_budget`**，直接用 `app/core/material.py:29` 的模块默认，＝`config.py:111` 的 80,000，
      即生产口径）→ `total_chars=28129`、`est_tokens=19399`、`overflow_tokens=3015`；
      对 19,378 锚点偏差 **0.11%**（判据 ±5%）。与 Cursor 自述的 19399／3015 一致。
    - **b／20 次 flake**：`tests/test_collab.py::test_panel_single_failure_degrades` 单跑 20 次 →
      **失败 3 次**（第 1、5、12 次），判据 ≤6，HEAD 基线实测 6/20。
      Cursor 报的是 2/20（第 7、9 次）——**两个数不一样，但都对**：这本来就是真竞态，
      失败次数每轮都会漂，所以判据写的是「≤6」而不是「＝某个数」。取两次观测的并集看，
      R-C9-1 把失败率从 6/20 压到 2–3/20，**方向对、幅度真**。
    - **⚠️ 但 flake 没根除，别把它记成已修**：3/20 仍然失败。R-C9-1 只搬走了热路径的读盘
      （`from_json` 读 `config.json`），**真正的根因是 `ScriptedClient` 用 `list.pop(0)` 共享脚本队列、
      三个线程抢答**，那是 **C-10** 的范围，本单没碰也不该碰。C-10 未做之前，
      这条用例单跑仍会偶发失败——只是不再被读盘放大。
    - **附：a/b/c 三条披露判据我也在真案卷上重跑了一遍**（判据允许「直接走 `cases/bi-delivery-risk`」，
      我就不用合成案卷了）：
      a) `bi-delivery-risk`（28,129 字）→ 披露条 1／triage 1／`status=overflow` ✅；
      b) `demo-solid-state`（2,709 字）与 `rumor-vs-official`（2,301 字）→ **零假披露**、`accounting` 无该键 ✅；
      c) `VERITAS_MODEL_CTX_TOKENS=0` → 零披露条、`accounting.prompt_window={"status":"unchecked",
      "detail":"模型窗口未检查（model_context_tokens≤0）"}`，报告可见「未检查」字样 ✅。
    - **结论：C-9 第二轮验收通过，可收口落 commit。** 遗留：flake 根因转 C-10；
      本机 16384 是 Ollama qwen3-14b 的实测窗口，**云端模型窗口仍未量**（不擅自花用户的钱），
      故 `model_context_tokens` 保持可配、默认值只对本机负责。
    - **复放中顺手量到的一件小事（不是缺陷，但别当谜数）**：报告里披露的字数会比架构师探针多 1 字
      （28,130 vs 28,129）。查清了＝**三个分析师的 persona 长度不同**（mainstream 46 字／redteam 47 字／
      technologist 74 字），而披露按「三人同卷只写一条」去重，**写进去的是第一个渲染完的那个人的数**。
      极差 28 字 ≈19 token／约 19,400 token ＝ **0.1%**，对判据无影响；但要知道
      「披露的 est 是某个分析师的提示词，不是一个规范值」。若日后要做乙（按窗口收窄装箱），
      这里得改成取三人最大值，否则会按最短的那个人算、留出一条缝。

### C-12｜官方样例集「进得来、出得去」：摄取适配层＋四份提交 JSON 导出＋自测下界评分器（2026-10-16 出单，队列第一）

- **为什么这单排第一（定位要诚实）**：**客观分 50 分现在一分都产不出来**——不是研判质量不行，是**提交物形态不存在**。
  官方《评分标准》（藏在宣讲 PPT 第 14 页的 OLE 嵌入对象里，已提取为
  [`docs/contest-scoring-rubric-2026-10-13.md`](contest-scoring-rubric-2026-10-13.md)）规定客观分由评测程序对选手提交的
  **四份 JSON** 与测试集答案做全量比对；而我们全仓 grep `supporting_facts`／`conflicting_facts`／`fact_des`／
  `resolution_type`／`para_id`／`question_id` **各 0 个文件命中**。没有这层，① 无法提交、② 连"我们现在客观分是多少"都量不出来、
  ③ C-2b 定价／召回七道口的［未量］／C-9 的真材料核对全部继续卡住。**本单要的是"能量出来"，不是"量出来高"**——
  跑出低分是合格结果。
- **现状（已核代码）**：
  - 官方输入形态：每专题一个目录，内含 `raw_documents.json`（**list**，六案合计 486 篇），
    每篇 `doc_id / title / publish_time / content / paragraphs[] / source_credibility / content_url`；
    `paragraphs` 每项只有 `para_id / char_start / char_end`，**不存段落文本**，正文按 `content[char_start:char_end]` 切。
  - 我方摄取**不认 `.json`**：`app/ingest/case_loader.py:50` 的 `_EXT_HINTS` 只有 `.md/.txt/.html/.pdf` 等，
    `app/ingest/readers.py:157` 的 `UNSUPPORTED_EXTS` 也不含 `.json`，`_IMAGE_EXTS` 更不含 →
    `.json` 落 `SourceType.OTHER` **被当纯文本整篇读入**，1.7MB 的 JSON 源码成"一篇信源"，
    `doc_id`／`para_id`／偏移全碎成噪声。
  - 我方一次跑**一个议题**；官方一案 **3 题**，`question_id` 是 2.3 结论正确率的匹配键。
  - 消解记录 `app/core/conflicts.py:33` `Resolution.method ∈ {arbitration, tie, evidence_weight}`，
    与官方五级 `resolution_type` **不同轴**（描述"谁裁的"，不是"凭什么裁的"），且无 `basis`、无少数意见重启条件。
- **实测前提（2026-10-16 架构师在官方样例集上跑出来的，出单前已核；复放命令见本单末「复放脚本」）**：
  1. `para_id` 是评分 2.1 **第一阶段精确匹配**的两个键之一，且该阶段"程序直接比对，**无需语义判定**" →
     **保全 `para_id` 就是 2.2.1 那 7 分的直接开关**，比任何语义质量都先决。
  2. 184 条金标：`para_id` 在 `paragraphs` 里 **0 缺失**；**160 条（87%）`quote` == 该段完整切片**；
     金标段字数中位 161、p90 716、**max 6,492 ＞ 我方 `SEGMENT_MAX=650`** → **必须沿用官方段边界**，
     二次切段会把 `para_id` 打碎，精确匹配直接失效。
  3. 全库 9,214 段里 **919 段 ＜5 字**（`0有用+1` 这类页面残渣），**其中 0 段承载金标** → 过滤 ＜5 字段安全，
     但**不得改其余段的 `para_id` 编号**（编号是匹配键，重编号＝自毁精确匹配）。
  4. 金标证据**高度集中**：吉隆案 25 条只落在 **2 篇**文档，其中 **23 条在 `doc_001`**
     （一篇 132,462 字／960 段的百度百科条目，`source_credibility=0.62`）。
  5. 「理论最小必读量」＝各案金标段字数合计 **4,826～19,591 字**，占全案 **1.4%～15.9%**，
     **六案全部 ＜ 本机 `num_ctx=16384` 折算的 ≈2.4 万字** → 召回选得准的话窗口够用；
     C-9 的超发源于**装了 96%～99% 的无关内容**，不是材料本身装不下。（这条同时削弱了 C-7 的立项理由：六案最多 137 篇，全在 500 上限内。）
  6. **`source_credibility` 与「是否承载金标证据」点二列相关 `r = +0.0526`（近零）**：
     `cred≥0.85` 的 190 篇命中率 23%，`cred<0.60` 的 24 篇命中率 **25%**（更高），全案基准 21%；
     吉隆案金标文档的 cred 中位排名 **第 88／137**。→ 该字段**只能用于冲突消解与置信度**；
     用于检索排序或过滤会**系统性排掉金标载体**。
  7. 金标自身有缺陷，**不是圣经**：9 条 `quote` 在 `content` 里找不到、1 条 `doc_id` 缺失、
     9 条 `quote` 跨多段却只声明一个 `para_id`（合计 19/184 ≈ 10%）；`publish_time` 有 **144 篇为空**、
     **67 篇不是完整 ISO 日期**（其中 **49 篇完全不是日期形态**＝相对时间 `8天前`／站点名串进时间字段
     `央视网`·`新华网`·`澎湃新闻`／裸月日 `9月28日`；另 18 篇残缺如 `2026-07`），
     只有 **275 篇**能解析出完整日期（275＋67＋144＝486）；
     `argument` 有 **3 条用英文键 `content` 而非 `内容`**、1 条缺 `主体`；`数值口径` 槽只有 **17/184（9%）** 带。
- **要求（只做这四件）**：
  1. **官方案卷适配层**（新增 `app/ingest/official_case.py`，不改 `case_loader` 现有分支的行为）：
     读 `raw_documents.json` → 每篇 doc 成一个信源（`doc_id` 作稳定标识，`title/publish_time/source_credibility/content_url` 原样带上）；
     每个 `paragraph` 成一个段，**段的稳定 id 必须逐字等于官方 `para_id`**，段文本 ＝ `content[char_start:char_end]`；
     **不得二次切段**（官方段超 650 字也整段保留）；＜5 字的段不进检索但**编号不动**，并在摄取披露里给出被过滤条数；
     `publish_time` 不可解析时（空／相对时间／非日期）**留空＋披露计数，禁止推断日期**。
  2. **多题运行**：一案三题。问题清单来源必须可切换——自测时从样例集 `conclusions.json` **只抽 `question_id`＋`question` 两个字段**，
     评测时官方只给「原始数据＋问题清单」；三题各跑一遍，导出时按 `question_id` 汇总。
  3. **四份提交 JSON 导出**（新增 `app/export/official.py`）＋一份字段说明：
     `evidence.json`（`doc_id/para_id/quote/fact_des/argument{时间,主体,地点,内容,影响,数值口径}/entities`）、
     `conclusions.json`（`question_id/question/conclusion/supporting_facts[{doc_id,para_id}]/conflicting_facts[{doc_id,para_id}]`）、
     `confidence.json`（schema 自定，但**必须含 3.2.1 的三维度**＝信源可信度／证据数量与一致性／推理链完整性，
     **以及 3.2.2 要的公式＋各分项数值＋代入演算**，评委按公式可复算出同一分值）、
     `conflict_resolution.json`（schema 自定，但**必须用官方五级枚举** `多数投票/来源优先级/时效性/语义可信度/其他`
     ＋`basis` 依据＋**少数意见的重启条件**）。
     **⚠️ 前向约束（2026-10-16 追加，因 C-14 出单）**：`Resolution` 现在**还没有** `basis`／`resolution_type`／重启条件
     这三个字段（C-14 才加）。所以本单导出层**必须从 `Resolution.to_dict()` 读字段，不许在导出层自己算证据强度或独立信源数**——
     当前拿不到的就按下方"如实留空"处理；C-14 落地后导出层**自动跟上，不必写第二遍**。
     **唯一例外**：`method → 官方五级` 的映射表本单可以先写在导出层（否则 `conflict_resolution.json` 一个合法枚举值都产不出），
     但**必须写成模块级具名常量并加注释「C-14 会把这张表移进 `app/core/conflicts.py` 作为唯一口径」**——
     C-14 的要求 3 就是来搬这张表的，两边不许各留一份。
     **我方现在产不出的字段（`fact_des`／`argument` 六槽／`entities`）如实留空（`null` 或 `""`），
     并在字段说明里写明"本版本未实现"**——禁止用启发式或 LLM 编造填充。
     理由：官方 2.2.2 是**"填了即判错"**的口径（`argument.时间`「原文无明确时间的应为空，填了即判错」），
     **编造比留空扣分更狠**。
  4. **自测下界评分器**（新增 `scripts/score_official.py`）：只实现 2.1 **第一阶段精确匹配**（`doc_id`＋`para_id` 相同），
     输出 2.2.1 的 `Precision_src/Recall_src/F1_src`、2.4 的 `P/R`、2.5 的 `P/R`，并按官方分档折算分数。
     **输出首行必须标明「仅第一阶段精确匹配＝官方分的下界，未含语义匹配」**。第二阶段（调大模型判"同一事实"）本单不做。
- **明确禁止**：
  ① **禁止把 `evidence_samples.json`／`conclusions.json` 的答案字段读进研判链路**——只有 `scripts/score_official.py`
  在评分时可读；这是作弊线，也是官方"请勿过拟合样例"的底线。
  ② **禁止针对这 6 个案例硬编码**任何 `doc_id`／`para_id`／词表／专题名（测试集不可见，硬编码＝过拟合）。
  ③ **禁止用 `source_credibility` 参与检索排序或过滤**（实测 `r=+0.0526`，用了会系统性排掉金标载体）。
  ④ **禁止二次切段打碎官方 `para_id`；禁止改写／重排 `para_id` 编号。**
  ⑤ **禁止编造 `fact_des`／`argument`／`entities` 充数**——留空并披露。
  ⑥ 禁止动 `tests/conftest.py` 的禁真调用守卫、禁止动 `cases/` 任何字节、**禁止真调用模型**。
  ⑦ 禁止改现有 `report.json` 已有字段的取值（会改结论 → 停手写提案）。
  ⑧ **官方样例集在仓库外**（`~/Desktop/veritas-testcases/样例集-拓尔思-20261012`），
  **禁止拷进仓库**（六案 4.6MB，且是官方下发材料）；测试一律用 `tmp_path` 造最小同构 fixture。
- **验收判据（Qoder 独立复放，开箱可跑）**：
  - `.venv/bin/python -m pytest tests -q` → 0 failed，passed ≥ 559＋新增（≥7）。
  - 新增用例（`tmp_path` 造最小同构 fixture，零 LLM）：
    a) **`para_id` 保全**：造 2 doc × 3 段 → 载入后每段 id **逐字等于**官方 `para_id`，段文本**逐字等于** `content[char_start:char_end]`；
    b) **不二次切段**：造一段 1,200 字（＞`SEGMENT_MAX=650`）→ 载入后**仍是 1 段**、id 不变、文本 1,200 字完整；
    c) **噪声段过滤但编号不动**：造 3 段其中 1 段 2 字 → 该段不进检索，另两段 `para_id` 仍是 `p1`/`p3`（**不得重编号**），披露给出被过滤条数；
    d) **答案隔离（反向断言，本单最重要的一条）**：用 monkeypatch 让"打开 `evidence_samples.json`／`conclusions.json`"抛异常，
    跑完整条研判链路（含三题、含导出）**必须不抛**；并 grep 断言 `app/` 下没有任何模块读这两个文件名的答案字段。
    e) **导出字段逐字对齐**：跑一次最小案卷 → 四份 JSON 的**键名集合**与官方附录 A 逐字相同
    （多一个键、少一个键、大小写不同都算失败）；未实现字段的值为 `null`/`""` 且字段说明里有"未实现"字样；
    f) **评分器下界自证（双向）**：把导出的 `evidence.json` 换成"金标本身"（在 `tmp_path` 里，不写仓库）→
    `Recall_src=1.0` 且 `Precision_src=1.0`；再把其中一条的 `para_id` 改错一位 → P/R 各降 `1/N`
    （**证明评分器真的在比对，不是恒返回满分**）；
    g) **`publish_time` 不猜**：造 `publish_time` 为 `""`／`8天前`／`央视网` 三种 → 载入后时间为空且披露计数为 3，
    **不得出现任何推断出的日期**。
  - **架构师复放探针**（我在官方样例集上自跑，不需要你造数据）：
    1. 六案全部载入成功，段落总数与官方 9,214 对得上（差额必须等于被过滤的 ＜5 字段数），
       **184 条金标 `para_id` 100% 能在载入结果里找到**；
    2. 跑吉隆案三题 → 导出四份 JSON → `score_official.py` 给出下界数字（**预期很低**：`fact_des`/`argument` 未实现、
       检索未针对官方数据调；低分＝本单合格）；
    3. 反向探针：grep 确认 `source_credibility` 没有出现在检索排序／过滤路径上。
  - `git diff --stat cases/` 为空；`git status` 里**不得出现官方样例集任何文件**。
- **复放脚本（架构师用，实测数字的来源；已入仓库）**：`scripts/probe_official.py`
  ——量的是 ①规模与"理论最小必读量" ②金标 `quote` 与段偏移的关系 ③噪声段与金标段长
  ④`source_credibility` 与金标承载的相关性 ⑤金标与原始数据自身缺陷 ⑥金标的文档集中度。
  上「实测前提」七条数字逐条可重算：`.venv/bin/python scripts/probe_official.py`
  （样例集在仓库外、**不入仓库**，路径用 `OFFICIAL_CASES=<样例集路径>` 覆盖；目录不存在时退出码 2，不给假数字）。
- **工时**：约 1.5 天（适配层 0.5 ＋ 多题与导出 0.5 ＋ 评分器与用例 0.5）。
- **撞车点（协议 §9.1）**：**已解除——C-9 第二轮复放通过并提交 `1885131`（2026-10-16），本单可立即开工。**
  两单都改 `app/pipeline.py`（C-9 加了 `_render_prompt_window` 与两处 accounting 白名单，本单要加多题编排与导出挂点），
  现在串行做即可，不再有未提交的同源改动。
  `app/config.py` 本单原则上不动；若确需新增配置项，按 §3.4 先质疑再动。
  ⚠️ 开工前建议先花 10 分钟做掉 **C-10**（flake 根因）——本单判据里同样有「连跑 5 次全绿」，
  而 `test_panel_single_failure_degrades` 现在仍 2~3/20 偶发失败（C-9 第二轮收口后架构师实测 3/20）。
- **开工提示词（协议 §9.1；撞车点已解除，**在 C-10 收口之后粘**）**：

```
读 docs/dev-protocol.md（分工协议，重点 §3.0 前提核查、§3 问题分流、§3.4 质疑通道）和 docs/HANDOFF.md §5 的工单 C-12，你是执行工程师。
本单只做「要求」列出的四件事＝让官方样例集进得来、四份提交 JSON 出得去、并有一个只算精确匹配的下界评分器。
实现细节以工单原文为准，不要照本提示词施工。
先做协议 §3.0 前提核查再动工：单里引的行号还在不在（case_loader.py:50 _EXT_HINTS、readers.py:157 UNSUPPORTED_EXTS、conflicts.py:33 Resolution.method）、
「全仓 grep 六个官方字段各 0 命中」是否仍成立、照做完判据 a–g 会不会真出现；有一条对不上就按 §3.4 说，别默认我对。
本单的目标是「能量出来」不是「量出来高」——评分器跑出低分是合格结果，不许为了好看去调检索或补字段。
允许动的落点：新增 app/ingest/official_case.py、新增 app/export/official.py、新增 scripts/score_official.py、
app/pipeline.py 的多题编排与导出挂点、新增测试。
【2026-10-16 追加】conflict_resolution.json 的字段必须从 Resolution.to_dict() 读，不许在导出层自己算证据强度或独立信源数
（basis／resolution_type／重启条件三个字段现在还不存在，C-14 才加，拿不到就留空并披露）；
唯一例外是 method→官方五级的映射表可以先写在导出层，但必须是模块级具名常量并注释「C-14 会把这张表移进 conflicts.py」，
两边不许各留一份。
明确禁止（工单八条，逐条照办）：不把 evidence_samples.json／conclusions.json 的答案字段读进研判链路（只有评分器可读）；
不针对这 6 个案例硬编码任何 doc_id／para_id／词表／专题名；不用 source_credibility 参与检索排序或过滤；
不二次切段、不改写 para_id 编号；不编造 fact_des／argument／entities 充数（留空并在字段说明写「未实现」）；
不动 tests/conftest.py、不动 cases/ 任何字节、不真调用模型；不改 report.json 已有字段的取值；
官方样例集在仓库外（~/Desktop/veritas-testcases/），禁止拷进仓库，测试一律用 tmp_path 造最小同构 fixture。
开发中若发现问题按协议 §3 分流：本单内的就地修并写「偏离工单之处＋原因」；
会改 report.json 已有字段取值的停手写提案；新洞只记「发现（未修）」，不要顺手修。
若你判定这张单的策略／口径／验收判据本身是错的（不是做不到，是这么做不对），按协议 §3.4 写「工单质疑」：
错在哪（引工单原句）｜实测证据（命令＋真实输出）｜建议改成什么。质疑是义务不是冒犯，我会同一轮答复；
但「我觉得更优雅」「这个应该顺便做全」不算质疑，也不要明知单写错了还照着做完好交差。
完成后回写：工单状态行改「已改完（YYYY-MM-DD），待架构师验收」＋动了哪些文件＋新增用例名＋pytest 尾行。
自查判据：pytest tests -q 0 failed 且 passed≥566；a–g 七条用例齐（d 答案隔离与 f 双向自证是重点，f 必须证明评分器不是恒返回满分）；
四份 JSON 键名与官方附录 A 逐字相同；git diff --stat cases/ 为空；git status 里没有官方样例集任何文件。
不要提交，不要 push，验收归 Qoder。
```

- **状态**：待开工（2026-10-16 出单，**队列第二**——前面只有 10 分钟的 C-10；撞车点已随 C-9 提交 `1885131` 解除，**C-10 一收口即可开工**）。｜ **验收**：—

### C-7｜把 500／深度 3 变成可配（**只交 C 方案**，2026-10-16 出单）

- **口径已拍（2026-10-16）**：A 的「抬预算」半段被 C-9 实测否掉、B 性价比最差，故本单只做 **C＝封顶变可配，默认值不变**。
  定位要诚实：**这单不解决召回**（合成实测：抬①500→2000 只多看见 1 份），
  它解决的是**现场被自己的上限挡死**——官方单专题 ≤2000 篇，硬编码 500 意味着演示当天只能靠删文件自救。
- **现状（已核代码）**：`app/ingest/case_loader.py:352` `_collect_files(case_dir, max_files=500, max_depth=3)`（按名排序在 `:370`）；
  导入侧另有一套常量 `app/ingest/import_case.py:15-18`（`MAX_FILES=500`／`MAX_DEPTH=3`），
  被 `classify_import_path:65`、`resolve_case_file:99`、`_filter_items:212` 三处直接引用——**两侧同数不同源**。
  披露侧已带生效值（`:724-725 max_files/max_depth`，文案用 `collected.taken`），所以可配化不需要改文案骨架。
- **要求（只做这四件）**：
  1. `app/config.py` 新增 `ingest_max_files: int = 500`、`ingest_max_depth: int = 3`，
     env `VERITAS_INGEST_MAX_FILES`／`VERITAS_INGEST_MAX_DEPTH`，并加进 `config.py:232` 的 config.json 覆盖白名单。
  2. **单一口径来源**（C-6 的 R-C6-1 教训：两处共用计数却两套语义，结论当场回退）：
     `_collect_files` 与 `import_case` 三处引用**必须读同一个 settings 值**，
     `import_case.py:15-18` 的模块常量不得再被当阈值直接用（保留为默认值常量可以，取值必须经 settings）。
  3. **非法值不得静默放大**：`<=0` 一律回落默认（500／3）并写一条披露；
     **禁止**把 `0` 解释成"无限制"——那会把有界遍历变成无界遍历，正是 C-1 明令禁止的方向。
  4. 生效值必须进披露：`dir_truncated` 那条的 `max_files`/`max_depth` 等于真实生效值，
     导入侧拒收文案里的「超过 N」同样跟随生效值，不得写死 500。
- **明确禁止**：① **不许**改默认值（500／3 一动就是改现网行为，须另单）；② **不许**改遍历排序语义（按名）；
  ③ **不许**动隐藏目录双封顶（50 目录／5000 文件）与 `SEGMENTER_VERSION`；④ **不许**加 LLM；
  ⑤ **不许**动 `tests/conftest.py` 守卫与 `cases/` 任何字节；⑥ 若发现"两侧同数不同源"改不动（架构性冲突），**停手登记**，别硬凑。
- **验收判据（Qoder 独立复放，开箱可跑）**：
  - `.venv/bin/python -m pytest tests -q` → 0 failed，passed ≥ 560（553＋新增≥4）。
  - 新增用例（`tmp_path`，零 LLM）：
    a) `VERITAS_INGEST_MAX_FILES=800`＋造 803 个 `.md` → `taken=800/skipped=3`，且 note 里 `max_files==800`；
    b) 不设 env → 与今日行为**逐字一致**（`taken=500`、文案与字段全等）＝回归钉死；
    c) `VERITAS_INGEST_MAX_DEPTH=5`＋第 4 层藏文件 → 不再出 `depth_capped`；设回 3 → 必出（两向都测，防空转）；
    d) 导入侧同 env 生效：`classify_import_path` 的深度阈值随 `ingest_max_depth` 变（配 5 则 5 段路径不再拒收）；
    e) `VERITAS_INGEST_MAX_FILES=0`／负数 → 回落 500 **且出披露**（不得静默当无限制）。
  - 复放探针（架构师自跑）：把 `measure_capacity.py` 的 `N_FILES=2000` 配 `VERITAS_INGEST_MAX_FILES=2000` 重跑，
    `[2]` 行 `taken` 必须变成 2000——证明可配真的通了，而不是只加了个读不到的环境变量。
  - `git diff --stat cases/` 为空。
- **开工提示词（协议 §9.1；**C-9 已于 2026-10-16 验收并提交 `1885131`，`app/config.py` 白名单的撞车点已解除**，但本单排在 C-12／C-14／C-13 之后——若那几单也要往白名单加字段，同一条分支串行做，别开两条并行改同一个文件）**：

```
读 docs/dev-protocol.md（分工协议，重点 §3 问题分流、§6 三道纪律）和 docs/HANDOFF.md §5 的工单 C-7，你是执行工程师。
本单只做「要求」列出的四件事＝把 500 封顶与深度 3 变成可配，默认值一个字节都不动。实现细节以该单原文为准，不要照本提示词施工。
先做协议 §3.0 前提核查再动工：单里的行号还在不在（`case_loader.py:352`／`:370`、`import_case.py:15-18`／`:65`／`:99`／`:212`、`config.py:232` 白名单）、
要求指的位置是不是真因、照做完判据 a/b/c/d/e 会不会真出现；有一条对不上就按 §3.4 说，别默认我对。
允许动的落点：app/config.py（新增两项＋加进 config.json 覆盖白名单，白名单里 C-9 已加的两项不许碰）、
app/ingest/case_loader.py 的 _collect_files、app/ingest/import_case.py 的三处阈值引用、
dir_truncated 与导入拒收文案里生效值的透出、新增测试。
明确禁止：不改默认值 500／3、不改按名排序的遍历语义、不动隐藏目录双封顶（50 目录／5000 文件）、
不动 SEGMENTER_VERSION、不加 LLM、不动 tests/conftest.py、不动 cases/ 任何字节、不把 0 或负数解释成"无限制"。
若「两侧同数不同源」改不动（架构性冲突），停手登记，别硬凑。
开发中若发现问题按协议 §3 分流：本单内的就地修并写「偏离工单之处＋原因」；
会改 report.json 已有字段取值的停手写提案；新洞只记「发现（未修）」。
若你判定这张单的策略／口径／验收判据**本身**是错的（不是做不到，是这么做不对），按协议 §3.4 写「工单质疑」：
错在哪（引工单原句）｜实测证据（命令＋真实输出）｜建议改成什么。质疑是义务不是冒犯，我会同一轮答复；
但"我觉得更优雅""这个应该顺便做全"不算质疑，也不要明知单写错了还照着做完好交差。
完成后回写：工单状态行改「已改完（YYYY-MM-DD），待架构师验收」＋动了哪些文件＋新增用例名＋pytest 尾行。
自查判据：pytest tests -q 0 failed 且 passed≥560；a/b/c/d/e 五条用例齐（b 默认逐字一致＝回归钉死，c 与 e 是双向断言）；
git diff --stat cases/ 为空。
不要提交，不要 push，验收归 Qoder。
```

- **状态**：待开工（2026-10-16 出单，排在 C-12／C-14／C-13 之后）。｜ **验收**：—

### C-14 前置实测｜同源污染到底有多少：给票数权重之前要不要先建独立信源簇（架构师自测，2026-10-16，未派工、未动生产代码）

- **要回答的问题**：官方 `decks:311` 写「独立信源数量占优（**须去同源**）」。原判断（**推演**）是
  "一条通稿被 20 家转载 → 多数投票是假象 → 必须先建独立信源簇，票数才有资格进权重"。
  本节把这句推演拿到官方样例集上量。
- **结论：推翻。不需要先建簇，现成的生产闸已经够用。**
- **实测数字**（复放：`PYTHONPATH=. .venv/bin/python scripts/probe_source_dedup.py`，约 1.0s、零 LLM、只读）：

| 探针 | 数字 | 含义 |
|---|---|---|
| ① URL 去重 | 486 篇全有 `content_url`，去重域名 226 个、单域名最多 12 篇（`www.thepaper.cn`），**完全相同 URL 只有 3 组** | URL 去重几乎抓不到同源 → 同源必须做**内容级**判定（这条与 C-12 前置实测一致） |
| ② 整篇转载扫描（40 字粗指纹） | Jaccard≥0.5 → **9 对**；≥0.3 → **11 对**；≥0.15 → **17 对** | **阈值敏感性**：从 0.5 放到 0.15 只涨 8 对 → "同源少"**不是阈值卡太严的假象** |
| ③ **生产闸复核**（`dup_check._shingles` 8 字滑窗 ＋ Jaccard≥`_NEAR_DUP_JACCARD=0.6`） | **22 对 / 486 篇 ＝ 4.5%**（吉隆 5、中美AI 3、刘翔 3、印航 5、柬泰 4、王虹 2），其中 **6 对 Jaccard=1.000** | 直接调生产函数，量的是**真闸**不是再实现。抓得比 ② 多，因为 `_shingles` 走 `normalize()`——**内容归一化后完全相同但 URL 不同**的转载件只有它抓得到（`duplicate_map` 的 SHA-256 走原文，抓不到） |

- **架构师自我更正（重要，别引用错数）**：本节 ③ 之前，架构师口头给用户的数是"跨域近重复 **5 对**/486"。
  那个数来自 ② 的粗指纹＋只看跨域，**低估了 4 倍**。③ 的 **22 对**才是生产闸的真实捕获量。
  结论方向没变（4.5% 仍可忽略），但**对外只许引 ③ 的 22 对／4.5%**。
- **口径边界（这句必须跟着数字一起说）**：② ③ 都是**字面**同源。**改写式洗稿测不出来**——
  但那是"同稿"不是"同源"，性质不同，且官方六案里也没出现（③ 抓到的 6 对 Jaccard=1.000 是原样转载）。
  隐藏测试集若含洗稿语料，这个数会变大，届时需要重跑本探针而不是照抄 4.5%。
- **对 C-14 的影响**：「独立信源数」直接用 `duplicate_map`（精确重复）＋ `near_dup_pairs`（近似同源）
  两道现成闸把重复件折掉再数 `source_id`，**不新建数据结构**。原队列里那条独立的「独立信源簇」
  工单（覆盖分量／篡改检测／孤证显影的共同地基）**不因本单而撤销**——它还有别的用途——
  但**它不再是 C-14 的前置条件**。

### C-14｜冲突消解：票数只当破平器 ＋ 消解记录对齐官方五级枚举（2026-10-16 出单，队列第二）

- **口径已拍（用户 2026-10-16 原话）**：「按照人的思考过程来，我们未必非要严格按照官方标准来，
  官方所谓的票多就赢我们可以让占一部分权重，但是**绝对不是评判标准**。」
  → 落地形状：**证据强度差得开时按强度定胜负（票数一票不算）；只有势均力敌时票数才破平。**
- **这个口径官方允许**（三处原文，出单前已核）：
  - `contest-scoring-rubric:327`「明确给出消解类型（**参考**类型：多数投票 / 来源优先级 / 时效性 / 语义可信度 / 其他）」——五级是**参考**；
  - `contest-decks:325`「消解类型，参赛者**可自行扩展**；核心是消解依据**必须可核验**」——唯一的硬要求是**可核验**；
  - `contest-decks:311`「独立信源数量占优（**须去同源**）」——去同源的做法见上方「C-14 前置实测」。
- **为什么这单值得做（定位要诚实）**：对着评分 **3.3 冲突消解记录＝10 分**（记录完整 5 ＋ 依据可核 3 ＋ 保留少数意见 2）。
  现在的缺口不是"没消解"，是**消解记录写的是"谁裁的"，官方要的是"凭什么裁的"**：
  ① `method ∈ {arbitration, tie, evidence_weight}` 是自造值，官方看不到对应类型 → **依据可核那 3 分基本是白捡的**；
  ② `dissent` 记录只有 `why`，**缺 3.3.3 要的「重启条件」** → 少数意见那 2 分只拿到一半；
  ③ **强度差 ≤0.20 的势均力敌区间现在没有任何机械依据**，直接交给 LLM 或判 tie，答辩时说不清"凭什么"。
  本单同时补掉这三个口子，且**第 ③ 条正是用户那句"票数占一部分权重"的落点**。
- **现状（已核代码，行号出单前逐条 grep 过）**：
  - `app/core/confidence.py:76-81` `evidence_strength_of` 返回的是**均值**（`sum(...)/len(evs)`）不是求和
    → **票数在消解侧的权重现在是 0**：10 条弱证据和 1 条弱证据打出来一样分。
  - `app/core/confidence.py:102-107` 票数在**置信度**侧是**有权重**的（`coverage` 按条数饱和于 4 条、
    `agreement` 按署名人数/编队人数）——**两侧口径不一致，本单只动消解侧，置信度侧一个字节都不改。**
  - `app/core/conflicts.py:100` `_WEIGHT_MARGIN = 0.20`；`:119` 唯一的否决闸
    `if w_lose > w_win + _WEIGHT_MARGIN` → 改判强侧、`method="evidence_weight"`。
    **`≤0.20` 时函数原样返回 LLM 的裁决**（`:127`），这就是那个空白区间。
  - `app/core/conflicts.py:28-43` `Resolution` 只有 `winner_id/method/rationale/evidence_weight/rebuts` 五个字段，
    **无 `basis`、无官方 `resolution_type`、无重启条件**；`to_dict/from_dict` 同缺。
  - `app/core/conflicts.py:160-166` `apply_resolution` 往 `winner_con.dissent` append 的 dict 只有
    `conflict_id/conclusion_id/author/statement/why` 五个键。
  - `app/agents/arbiter.py:335-384` `arbitrate` 是唯一的 `Resolution` 构造点（`:376-382`），
    提示词里**已经**把信源时点给了 LLM（`:340-351` `_dates_of`）并要求"新近度不能替代证据质量"——
    但**程序侧没有把独立信源数算出来给 LLM 看，也没有落进记录**。
  - 去同源的两道闸**现成**：`app/core/dup_check.py:37` `duplicate_map`（SHA-256 精确重复）、
    `:50` `near_dup_pairs`（8 字滑窗 Jaccard≥`_NEAR_DUP_JACCARD=0.6`，`:22`；指纹函数 `_shingles` 在 `:29`）。
- **要求（只做这四件）**：
  1. **独立信源数（去同源后）**：新增 `app/core/conflicts.py::independent_source_count(conclusion_id, dossier) -> int`
     ——该结论全部存活证据的 `segment_ids` → `source_of_segment` → 去掉
     `duplicate_map` 的重复件（折算到正本）与 `near_dup_pairs` 命中的同源对（每组只留一件，取信源序首件）
     → 数不同 `source_id`。**禁止自己实现相似度判定**，必须调 `dup_check` 现成函数（口径只能有一个）。
  2. **破平器**：改 `prefer_stronger_side`（或在其后新增一道 `break_tie_by_sources`，二选一，但**判定顺序必须固定**）：
     - 强度差 **> `_WEIGHT_MARGIN`** → **行为完全不变**（按强度定胜负，票数不参与，`decision_path="strength"`）；
     - 强度差 **≤ `_WEIGHT_MARGIN`** 且 LLM 判了胜方 → 比独立信源数：**多的一方胜**，
       `method="source_majority"`、`decision_path="source_majority"`；
     - 独立信源数**也相同** → `winner_id="tie"`（**不得**按 id 字典序、列表顺序或任何隐式规则偷偷定胜负）；
     - LLM 本来就判 `tie` → 维持 `tie`（`:109` 现有短路不许动）。
  3. **`Resolution` 加两个字段**：
     - `basis: dict`——**判定全过程的可核验快照**，至少含
       `{"strength": {a: x, b: y}, "independent_sources": {a: m, b: n},
         "margin": 0.20, "decision_path": "strength|source_majority|tie|llm_arbitration",
         "dedup": {"exact": k1, "near": k2}}`；
       `strength` 的数值**必须与 `evidence_strength_of` 直接调用的结果逐位相同**（不许另算一遍）；
     - `resolution_type: str`——**官方五级枚举**，由 `method`/`decision_path` **机械映射**得出：
       `evidence_weight`→`语义可信度`、`source_majority`→`多数投票`、`tie`→`其他`、
       `arbitration`→`其他`；映射表必须是模块级常量且**穷举闭合**（新 `method` 值漏映射要在导入时报错，不许静默落 `其他`）。
       **若 C-12 已在 `app/export/official.py` 写过这张表，本单负责把它搬进 `conflicts.py` 并让导出层改为读取——
       全仓只许有一份映射表**（判据 e 会断言）。
       `to_dict`/`from_dict` 两个新字段都要带上（**旧 `report.json` 缺字段时必须能加载**，用 `.get` 兜默认）。
     - **`basis` 还必须答官方那两问**（出单时逐字核过 `contest-scoring-rubric:327`）：
       3 分的原文是「明确给出消解类型…**并说明该类型为何适用、冲突侧为何被排除**」，
       只给类型不说明＝**2 分**。所以 `basis` 除上列数值外，再加两个机械生成的短句字段
       `type_applies`（为何该类型适用，如「双方强度差 0.07 ≤ 0.20，强度不足以裁决，转入独立信源数比较」）与
       `loser_excluded`（冲突侧为何被排除，如「败方独立信源 1 个 ＜ 胜方 3 个（已折掉 2 件同源转载）」）。
       **两句都必须由 `basis` 里的数值直接拼出，禁止调 LLM**——否则违背「依据必须可核验」。
  4. **少数意见重启条件**：`apply_resolution` 往 `dissent` 里多写一个 `reopen_when: str`，
     **按 `decision_path` 规则生成，禁止调 LLM 编造**：
     - `strength` → 「败方取得新的一手信源（证据等级 ≥B）使双方强度差回落到 0.20 以内，或胜方证据被人工删除后，重启本冲突」；
     - `source_majority` → 「败方独立信源数（去同源后）追平或超过胜方，或双方强度差扩大到 0.20 以上后，重启本冲突」；
     - `tie`／`llm_arbitration` → 「任一方补充新证据后即重启（本冲突此前无机械判据，仅凭仲裁说理）」。
     文案可以照抄，但**必须随 `decision_path` 变化**（判据 f 会穷举断言）。
- **明确禁止**：
  ① **不许改 `evidence_strength_of` 的均值口径**（改成求和＝让票数变成决定性因素，直接违背用户拍的口径）；
  ② **不许改 `_WEIGHT_MARGIN` 的默认值 0.20**（要改另单，且需给出为什么 0.20 不对的实测）；
  ③ **不许让票数进入 `strength`／`evidence_score`**（票数只能走 `basis.independent_sources` 这一条路）；
  ④ **不许动 `app/core/confidence.py`**（置信度侧的 `coverage`／`agreement` 现状就是对的）；
  ⑤ **不许自己实现相似度／去同源判定**，必须调 `dup_check` 现成函数；
  ⑥ **不许用 LLM 生成 `resolution_type`／`basis`／`reopen_when`**——三者都必须是机械可复算的，
     否则违背 `decks:325`「依据必须可核验」，也过不了本单的 A/B 口径（见下）；
  ⑦ **不许改现有 `report.json` 已有字段的取值**（新增字段可以；改 `winner_id` 的**判定逻辑**只允许发生在
     ≤0.20 那个区间，>0.20 的行为必须逐字不变——判据 g 会钉）；
  ⑧ 禁止动 `tests/conftest.py` 的禁真调用守卫、禁止动 `cases/` 任何字节、**禁止真调用模型**；
  ⑨ **官方样例集在仓库外**（`~/Desktop/veritas-testcases/样例集-拓尔思-20261012`），**禁止拷进仓库**；
     测试一律用 `tmp_path` 造最小同构 fixture；
  ⑩ **禁止针对官方六案调参逼近金标的 `resolution_type` 分布**（那是过拟合，官方明令禁止）。
- **A/B 口径（本单特别说明，按 `docs/ab-protocol.md` 的例外处理）**：
  新判定规则本应跑 3 开 3 关的 A/B 红绿差，但**本单 A/B 不了**——机械闸只查格式不查对错，
  查对错要金标，而金标只有 18 题且官方「请勿过拟合样例」。
  故按第三口径处理：**能机械核验的部分（`basis` 数值一致性、枚举闭合、重启条件非空、>0.20 行为不变）正常上判据；
  不能机械核验的部分（"势均力敌时数票是不是更接近人的判断"）在代码注释与报告文案里明写
  「依据用户口径 2026-10-16 ＋官方 `decks:325` 可扩展条款，未经 A/B」**——不假装验证过。
- **验收判据（Qoder 独立复放，开箱可跑）**：
  - `.venv/bin/python -m pytest tests -q` → 0 failed，passed ≥ **C-12 收口后的基线 ＋ 9**
    （若 C-12 按判据交足 ≥7 条，即 ≥ 559＋7＋9 ＝ **575**；基线以 C-12 验收记录里的 pytest 尾行为准，
    **不许拿 559 当基线**——那是 C-12 之前的数）；**连跑 5 次**（flake 见 C-10）。
  - 新增用例（`tmp_path`，零 LLM，用 `ScriptedClient` 喂固定仲裁响应）：
    a) **强度差 > 0.20 时票数完全不影响结果**：造 a 挂 1 条 A 级证据、b 挂 5 条来自 5 个不同信源的 D 级证据
       → winner 仍是 a，`decision_path=="strength"`，且 `basis.independent_sources` 里 **b 的数更大但未被采用**；
    b) **强度差 ≤ 0.20 时按独立信源数破平**：造双方强度接近、a 来自 1 个信源 b 来自 3 个信源
       → `winner==b`、`method=="source_majority"`、`resolution_type=="多数投票"`；
    c) **独立信源数也相同 → tie**：双方强度接近且各 2 个信源 → `winner=="tie"`；
       **并断言把 a/b 的构造顺序对调结果不变**（证明没有偷偷按顺序定胜负）；
    d) **去同源真的折了**：造 3 个信源其中 2 个内容归一化后完全相同（走 `near_dup_pairs` 会命中）
       → `independent_source_count==2` 而不是 3；
    e) **枚举穷举闭合＋全仓唯一**：遍历所有可能 `method` 值 → 每个都映射到官方五级之一，
       **且断言映射表键集与 `method` 可能取值集完全相等**（多一个少一个都算失败）；
       并 grep 断言 `app/export/official.py` 里**不再存在**第二份映射表；
    f) **重启条件随路径变化**：`strength`／`source_majority`／`tie` 三条路径各产出**互不相同且非空**的 `reopen_when`；
    g) **回归钉死（本单最重要）**：跑现有全部冲突相关用例 → `winner_id`／`method`／`rationale` 的取值
       **逐字不变**（新字段可以新增，旧字段一个都不许变）；
    h) **`basis` 可核验**：`basis["strength"]` 的数值与测试里直接调 `evidence_strength_of` 的结果**逐位相同**；
       `basis["independent_sources"]` 与直接调 `independent_source_count` 的结果相同；
       `type_applies`／`loser_excluded` 两句**非空**、且句中出现的数字与 `basis` 里的数值一致
       （用正则抽数字比对，证明这两句是从 `basis` 拼出来的而不是另写的）；
    i) **旧报告可加载**：构造一个**不含** `basis`／`resolution_type` 的旧 `Resolution.to_dict()` 形态 dict
       → `Resolution.from_dict` 不抛、两个新字段落默认值。
  - **架构师复放探针**（我在官方样例集上自跑，不需要你造数据）：
    1. `PYTHONPATH=. .venv/bin/python scripts/probe_source_dedup.py` 数字与本单「前置实测」三行逐项对得上；
    2. 跑一个现有案例（`cases/rumor-vs-official`，冲突密集）→ 检查 `report.json` 里每条 `resolution`
       都有非空 `basis`＋合法 `resolution_type`＋`decision_path`，且 `decision_path=="strength"` 的那几条
       `winner_id` 与本单之前的产物**完全一致**；
    3. 反向探针：grep 确认 `evidence_strength_of` 的函数体没被改（`git diff` 里 `confidence.py` 为空）。
  - `git diff --stat cases/` 为空；`git diff --stat app/core/confidence.py` 为空；
    `git status` 里**不得出现官方样例集任何文件**。
- **工时**：约 0.5～1 天（独立信源数与破平器 0.25 ＋ `basis`/枚举/重启条件 0.25 ＋ 用例 i 条 0.5）。
- **撞车点（协议 §9.1）**：**必须排在 C-12 之后**——C-12 的 `app/export/official.py` 要导出
  `conflict_resolution.json`（含官方五级枚举＋`basis`＋重启条件）。为此 **C-12 已补一条前向约束**（见 C-12 单末）：
  导出层必须**从 `Resolution.to_dict()` 读字段，不许在导出层自己算**——这样本单加字段时导出层自动跟上，
  不必写两遍。与 C-13 **不撞**（C-13 动 `reasoning_graph.py` 与重算传播，本单动 `conflicts.py`／`arbiter.py`）。
  `app/pipeline.py` 只在渲染消解记录那一段可能碰，串行做即可。
- **开工提示词（协议 §9.1；**必须在 C-12 验收并提交之后再动**）**：

```
读 docs/dev-protocol.md（分工协议，重点 §3.0 前提核查、§3 问题分流、§3.4 质疑通道）和 docs/HANDOFF.md §5 的工单 C-14，你是执行工程师。
本单只做「要求」列出的四件事＝让票数在证据强度势均力敌时当破平器，并把消解记录对齐官方五级枚举＋basis＋重启条件。
实现细节以工单原文为准，不要照本提示词施工。
先做协议 §3.0 前提核查再动工：单里引的行号还在不在（confidence.py:76-81 均值、conflicts.py:100 _WEIGHT_MARGIN、
conflicts.py:119 否决闸、conflicts.py:28-43 Resolution 五字段、conflicts.py:160-166 dissent 五键、
arbiter.py:376-382 唯一构造点、dup_check.py:37/:50 两道闸）、「强度差≤0.20 时程序原样返回 LLM 裁决」是否仍成立、
照做完判据 a–i 会不会真出现；有一条对不上就按 §3.4 说，别默认我对。
这单的口径是用户拍的：票数占一部分权重，但绝对不是评判标准——所以强度差>0.20 时的行为必须一个字节都不变，
票数只允许在 ≤0.20 那个区间起作用。你若认为这个口径本身站不住（不是做不到，是这么做不对），按 §3.4 写质疑并附实测。
允许动的落点：app/core/conflicts.py（新增 independent_source_count、破平器、Resolution 两个新字段、映射表常量、
apply_resolution 的 reopen_when）、app/agents/arbiter.py 的 Resolution 构造处、
pipeline.py 渲染消解记录那一段、新增测试。
明确禁止（工单十条，逐条照办）：不改 evidence_strength_of 的均值口径、不改 _WEIGHT_MARGIN 默认值 0.20、
不让票数进 strength／evidence_score、不动 app/core/confidence.py 任何字节、不自己实现相似度判定（必须调 dup_check）、
不用 LLM 生成 resolution_type／basis／reopen_when、不改 report.json 已有字段的取值、
不动 tests/conftest.py、不动 cases/ 任何字节、不真调用模型；官方样例集在仓库外禁止拷进仓库，测试用 tmp_path 造最小同构 fixture；
不针对官方六案调参逼近金标的 resolution_type 分布。
本单 A/B 不了（机械闸只查格式不查对错，查对错要金标而金标只有 18 题且官方禁止过拟合），
所以「势均力敌时数票是否更接近人的判断」这一条按工单的第三口径处理：在代码注释里明写
「依据用户口径 2026-10-16＋官方 decks:325 可扩展条款，未经 A/B」，不要假装验证过。
开发中若发现问题按协议 §3 分流：本单内的就地修并写「偏离工单之处＋原因」；
会改 report.json 已有字段取值的停手写提案；新洞只记「发现（未修）」，不要顺手修。
完成后回写：工单状态行改「已改完（YYYY-MM-DD），待架构师验收」＋动了哪些文件＋新增用例名＋pytest 尾行。
自查判据：pytest tests -q 连跑 5 次 0 failed 且 passed ≥ C-12 收口后的基线＋9（若 C-12 交足 7 条即 ≥575，
基线看 C-12 验收记录里的 pytest 尾行，别拿 559 当基线）；a–i 九条用例齐（g 回归钉死与 c 的顺序对调是重点，
e 必须断言映射表键集与 method 取值集完全相等、且 app/export/official.py 里没有第二份映射表，
h 必须证明 type_applies／loser_excluded 两句里的数字与 basis 一致）；
git diff --stat cases/ 与 app/core/confidence.py 均为空；git status 里没有官方样例集任何文件。
不要提交，不要 push，验收归 Qoder。
```

- **状态**：待开工（2026-10-16 出单，**队列第三＝排在 C-10、C-12 之后、C-13 之前**）。｜ **验收**：—
  > 排序理由（2026-10-16 用户已拍板「都一块做完」，序＝C-10→C-12→C-14→C-13）：C-14 与 C-13 同为 10 分（3.3 vs 3.1.3），
  > 但 C-14 更短（0.5～1 天 vs 1 天），且紧跟 C-12 的导出层做能少写一遍；C-13 要往 C-12 定型的编排里插，放最后。

### C-10｜编队用例共享脚本队列＝顺序敏感的假红（2026-10-16 出单，**队列最前**，10 分钟小单）

- **为什么插在最前**：此后每张单（C-12／C-14／C-13）的验收判据都写着「连跑 5 次全绿」，
  而这个用例现在**每 20 次跑失败 2～6 次**——判据本身站在流沙上。修它只动测试，零生产代码风险，
  收益是**让后面三张单的判据变得可用**。
- **根因（已核代码）**：`run_panel` 用 `ThreadPoolExecutor` 并行提交三个分析师
  （`app/agents/panel.py:93-94` `futures = {pool.submit(a.analyze, dossier): a for a in analysts}`），
  而 `tests/test_collab.py:43` 的 `ScriptedClient.chat` 从**同一个队列** `item = self.responses.pop(0)` 取响应
  ——「谁抢到第 2 个响应（那条 `RuntimeError`）」纯看线程调度。
  用例 `test_panel_single_failure_degrades`（`tests/test_collab.py:105-114`）却断言
  `set(results["_failures"]) == {"redteam"}`——**断言了一个不确定的事**。
- **实测（HEAD 干净树，复放命令见判据）**：单跑该用例 20 次失败 **6 次**；
  同一队列在 12 次重复里失败者 redteam **11** 次／technologist **1** 次；
  C-9 第二轮收口后（热路径不再读配置）Cursor 复放 **2/20**、架构师独立复放 **3/20**（第 1、5、12 次）。
  **三个数都不一样但都对——这本来就是真竞态，失败次数每轮都漂**，所以判据写「0/200」而不是「＝某个数」。
  ⚠️ 注意：C-9 的 R-C9-1 只是**不再放大**它（13/20 → 2~3/20），**没有修它**。
- **要求（只动测试，两个文件）**：
  1. `tests/test_collab.py` 的 `ScriptedClient` 增加**按分析师身份路由**的能力（保留现有位置队列语义不变，
     新能力是**可选**的，其余用例一行都不用改）：
     - 新增可选构造参数（如 `by_name: dict[str, list] | None = None`）；非空时按**分析师名**取各自的队列，
       空/未传时走现在的 `responses.pop(0)`；
     - 身份识别**只能来自 `messages`**（`chat` 的入参），不得依赖调用顺序、不得加锁串行化生产代码。
       可用锚点：`Analyst.analyze` 的系统提示词以 `render_system_prompt(persona=...)` 渲染，
       `SYSTEM_TEMPLATE` 首句是「你是一名{persona}。」，而 `panel.DEFAULT_ROSTER` 就是
       `[(name, persona), ...]`（`app/agents/panel.py:27-31`）——**用 persona 文本反查 name**，
       禁止把 persona 常量抄进测试（抄了就会与生产漂移，改从 `DEFAULT_ROSTER` 读）。
  2. 把 `test_panel_single_failure_degrades` 改成**按身份路由**：redteam 的队列是
     `[RuntimeError("429 网关抖动")]`，另两人各是 `[PANEL_JSON]`。
     断言不变（`set(results["_failures"]) == {"redteam"}`、`len(dossier.conclusions) == 4`），
     但现在它断言的是**确定发生的事**。
  3. **明确禁止**的三种"修法"：① `time.sleep`／`pytest-repeat`／重试直到绿；
     ② 把 `run_panel` 改成串行或加全局锁（**改生产代码来让测试变绿＝把并行能力删了**）；
     ③ 把断言放宽成 `len(results["_failures"]) == 1`（那是把 bug 写成规格）。
  4. **顺带排查**：grep 全 `tests/` 里还有哪些用例把**不同响应**塞进同一个 `ScriptedClient` 位置队列
     且并行调用 `run_panel`——架构师已查过一遍，当前只有 `test_panel_single_failure_degrades` 一处
     （`:97` 是三条相同响应、`:119` 是三条相同异常，都与顺序无关）；若你查出第二处，一并按同一办法修并在回写里点名。
- **验收判据（Qoder 独立复放，开箱可跑）**：
  - `.venv/bin/python -m pytest tests/test_collab.py::test_panel_single_failure_degrades -q`
    **连跑 200 次全绿**（架构师用 shell 循环跑，不用 pytest-repeat 插件）；
  - `.venv/bin/python -m pytest tests -q` → 0 failed，passed **＝559**（本单只改测试，
    **用例总数不许变**——若你把某个用例拆成两个，回写里必须说明为什么）；连跑 5 次全绿；
  - **反向断言（证明真的修好了，不是碰巧没复现）**：`git diff` 里 `app/` 目录**必须为空**
    （`git diff --stat app/` 无输出）；且 `tests/test_collab.py` 里**不得出现** `sleep`／`retry`／
    `pytest-repeat`／`flaky` 字样；
  - **证明路由真的生效**：把 redteam 的队列换成 `PANEL_JSON`、把 mainstream 的换成 `RuntimeError`
    → 失败者必须变成 `mainstream`（架构师会临时改一行验完再改回，你不必提交这个变体，
    但**回写里要说明你怎么自证路由不是恒指向 redteam**）；
  - `git diff --stat cases/` 为空。
- **工时**：10～20 分钟。
- **撞车点（协议 §9.1）**：只动 `tests/test_collab.py`，与 C-12／C-14／C-13 **零重叠**。
  **但必须最先做**：后三单的判据都含「连跑 5 次全绿」。
- **开工提示词（协议 §9.1；可直接粘，本单在所有单之前）**：

```
读 docs/dev-protocol.md（分工协议，重点 §3.0 前提核查、§3 问题分流、§3.4 质疑通道）和 docs/HANDOFF.md §5 的工单 C-10，你是执行工程师。
本单只改测试，不动任何生产代码：修掉 test_panel_single_failure_degrades 的顺序敏感假红。
根因是 run_panel 用 ThreadPoolExecutor 并行提交（app/agents/panel.py:93-94），
而 ScriptedClient.chat 从同一个队列 pop(0)（tests/test_collab.py:43），谁抢到那条 RuntimeError 纯看调度。
实现细节以工单原文为准，不要照本提示词施工。
先做协议 §3.0 前提核查再动工：单里引的行号还在不在（panel.py:93-94、test_collab.py:43/:105-114/:97/:119、panel.py:27-31 DEFAULT_ROSTER）、
「当前只有一处顺序敏感」是否仍成立（自己 grep 一遍全 tests/）；有一条对不上就按 §3.4 说，别默认我对。
修法：给 ScriptedClient 加一个可选的按分析师身份路由的队列（不传就走现在的 pop(0)，其余用例一行不改），
身份只能从 messages 里认（系统提示词首句「你是一名{persona}。」＋从 DEFAULT_ROSTER 反查 name，禁止把 persona 常量抄进测试）。
明确禁止三种"修法"：加 sleep／重试／pytest-repeat；把 run_panel 改串行或加全局锁（改生产代码让测试变绿＝把并行能力删了）；
把断言放宽成 len(_failures)==1（那是把 bug 写成规格）。
允许动的落点：只有 tests/test_collab.py。
不动 tests/conftest.py 的禁真调用守卫、不动 cases/ 任何字节、不真调用模型。
自查判据：pytest tests/test_collab.py::test_panel_single_failure_degrades -q 用 shell 循环连跑 200 次全绿；
pytest tests -q 0 failed 且 passed 仍＝559（用例总数不许变，拆了要说明）；
git diff --stat app/ 无输出；tests/test_collab.py 里不得出现 sleep／retry／pytest-repeat／flaky 字样。
回写里必须说明你怎么自证「路由不是恒指向 redteam」（把异常挪给 mainstream 应变成 mainstream 失败）。
完成后回写：工单状态行改「已改完（YYYY-MM-DD），待架构师验收」＋动了哪些文件＋pytest 尾行＋200 次循环的实测结果。
不要提交，不要 push，验收归 Qoder。
```

- **状态**：待开工（2026-10-16 出单，**队列最前**）。｜ **验收**：—

### C-13｜推理树补中间结论层＋结论依赖边＋依赖传播（2026-10-16 出单，**队列第四＝最后一张**）

- **对着哪一分**：评分 **3.1.3「推理轨迹可视化与人工介入」＝10 分，主观分最大单项**。
  `contest-scoring-rubric:285` 原文分档：「**10 分**：以推理树/证据图展示**中间结论、依据、逻辑链、冲突点与消解结果**，
  可视化效果清晰…；**4~8 分**：有可视化但缺冲突点/消解结果标注，或**轨迹不清晰**；**2 分**：仅静态数据呈现」。
  `contest-decks:334`：「要展示中间结论、逻辑链、冲突点与消解结果**四类元素**，不是简单的关系图」。
  **现状定位（出单前逐条核过 `reasoning_graph.py:3-11`）**：四类元素里我们**已有三类**——
  依据（`supports`/`cites`/`from_source`）、冲突点（`conflicts_with`/`rebuts`）、消解结果（`decides`）；
  **缺的正是「中间结论」与「逻辑链（结论→结论）」**。所以现在卡在 **4~8 分档**，不是 2 分档。
  本单补两条边就能进 10 分档——**这是全队列里"每工时换分"最高的一张**。
- **官方把难点讲死在三处**（`contest-decks:297-301`，逐字）：
  > ① **中间结论在哪里**——「结论不是一步从证据跳出来的，中间有若干判断环节。推理树要体现中间层，而不是『证据 → 结论』平铺。」
  > ② **结论之间的依赖关系**——「有些结论是另一些结论的前提：如先确定『致灾过程』才能判断成因，先定『责任归属』才能谈『索赔对象』。**依赖若不建模，推理树就是星形的。**」
  > ③ **依赖的传播**——「人工修改一条证据后，要能**判断下游哪些结论受影响**并重算，而非只重算直接被支撑的那条。」
- **⚠️ 出单前的前提更正（旧口径错，别照它施工）**：本页队列表此前写「人工改证据**只重算直接被支撑的那条**，不做依赖传播」——
  **这半句是错的**。`app/server.py:268` 的 `_mutate` 调的是 `recompute_all(dossier, n_panel=...)`
  ＝**全量重算**，所有结论的置信度都会刷新（`app/core/confidence.py:143-149`）。
  真正缺的是三样：**①** 没有结论→结论边（`reasoning_graph.py:3-11` 七种边里没有，**图确实是星形的，这半句对**）；
  **②** 没有「哪些结论受影响」的**识别与披露**（全量重算是"闷头全刷"，说不出刷了谁、为什么）；
  **③** 上游结论失效时下游**不会被标记**（置信度数字会变，但"你的前提没了"这件事没有任何出口）。
  → 所以本单的第 ③ 项**不是"把全量重算改成增量重算"**（那是倒退，全量重算更保险），
  而是**把受影响集合算出来、说出来、并在上游失效时亮牌**。
- **现状（已核代码）**：
  - `app/core/reasoning_graph.py:3-11` 边语义只有七种：`supports`（结论→证据）、`cites`（证据→段落）、
    `from_source`（段落→信源）、`authored_by`（结论→分析师）、`conflicts_with`（冲突→双方结论）、
    `rebuts`（质证→冲突）、`decides`（仲裁→胜方）。**无结论→结论边**。
  - `app/core/evidence.py:191-217` `Conclusion` 有 `id/statement/author/authors/group_id/status/evidence_ids/
    confidence/confidence_parts/dissent/coverage` 十一个字段，**无 `depends_on`**。
  - `reasoning_graph.py` 里 `status == "merged"` 的归并组成员**不进主图**（「溯源成员不进主图，避免噪点」）——
    本单不许把它们当中间结论复用，它们是同义重复不是前提。
  - `app/core/confidence.py:131-149` `recompute_conclusion`（单条）与 `recompute_all`（全量）两个入口都在，
    工作台走 `_mutate` → `recompute_all`；`confidence.py:17` 的模块 docstring 写「人工修改…只重算受影响结论」
    **与 `server.py:268` 的实际调用不符**，本单顺手把这句注释改对（**只改注释，不改行为**）。
  - `app/server.py:248-279` `_mutate` 是全部人工介入端点的公共骨架，且**已有现成钩子**：
    `mutate_fn` 可返回 dict →「并入链事件 payload（审计计数等）并随响应回传（`resp["op"]`），
    **供前端提示『本次修改新引入了什么』**」——受影响集合正好从这里出去，不需要新协议。
  - `app/server.py:694` 已有 `GET /api/reasoning_graph`；`:707` `/api/conclusion/edit`、`:790` `/api/evidence/remove`、
    `:775` `/api/evidence/weight`、`:734` `/api/conflict/override` 全部走 `_mutate`。
- **要求（只做这五件，v1 范围有意收窄，收窄理由写在每条后面）**：
  1. **数据模型**：`Conclusion` 新增两个字段，`to_dict`/`from_dict` 都带上，**旧 `report.json` 缺字段必须能加载**（`.get` 兜空）：
     - `depends_on: list[str]`——本结论的**前提结论 id**（方向：`self` 依赖 `depends_on` 里的每一条）；
     - `premise_broken: list[str]`——已失效的上游 id（由第 4 条机械写入，**不许 LLM 写**）。
  2. **依赖边生成（一遍 LLM ＋ 机械校验 ＋ 零 LLM 兜底）**：新增 `app/core/dependency.py`，
     在**归并之后、置信度回填之前**跑一遍：把结论清单喂给模型，输出
     `{"edges": [{"from": "CON-x", "to": "CON-y", "why": "一句话说明 x 为什么以 y 为前提"}]}`。
     **机械校验（零 LLM，逐条拒收并披露）**：id 必须存在于案卷；不得自环；**不得成环**（检出环则该条丢弃并披露环路径）；
     `to` 必须是 `status=="majority"` 的结论（不得把 `merged`/`dissent` 当前提）。
     **LLM 失败或输出非法 → 0 条边，图退回星形，并在报告与 accounting 里披露「依赖边未生成」**，管线不许炸。
     > 收窄理由：**v1 只在既有结论之间连边，不合成新的中间结论节点。** 合成新前提＝凭空增加一条
     > 没有任何分析师背书的断言，属判定改造，须按 `docs/ab-protocol.md` 另单跑 A/B。
     > **这是本单的已知缺口，必须在报告里披露**（「中间结论层＝被依赖的既有结论，未合成新前提」），
     > 不许在答辩里说成"已实现中间推理层"。
  3. **中间结论是结构性的，不是新节点类型**：`is_premise = 被任何结论 depends_on 指向`。
     `build_reasoning_graph` 新增边 kind **`depends_on`**（结论→结论），并给节点带上 `is_premise` 布尔。
     **不得新增 `kind="intermediate"` 的独立节点**（理由同第 2 条）。
  4. **依赖传播（本单第 ③ 项，全部零 LLM）**：
     - `affected_downstream(conclusion_id, dossier) -> list[str]`：沿 `depends_on` 的**反向**做传递闭包
       （改 X ⇒ 所有直接或间接以 X 为前提的结论），**环保护**（ visited 集）、**确定性排序**（按结论在案卷中的序，不许用 set 迭代序）；
     - `_mutate` 在 `recompute_all` 之后调它，把受影响集合写进**链事件 payload** 与**响应 `op`**（现成钩子，见上）；
     - **失效传导**：上游结论满足任一条即视为失效——`status` 变成 `dissent`、或存活证据被删空、或
       `confidence == 0.0`（`conclude_confidence` 对无证据结论返回 0，见 `confidence.py:90-98`）；
       失效时把该上游 id 追加进所有下游的 `premise_broken`，并渲染成黄牌（报告＋工作台）。
       **只亮牌，绝不自动删除或自动改写下游结论**——「不能人工修正答案」的反面同样成立：**程序也不许自动修正答案**。
  5. **人工介入端点**：新增 `POST /api/conclusion/depends`（`{case, from, to, action: "add"|"remove", base_rev}`）
     → 走 `_mutate`（自动获得写锁、`base_rev` 乐观并发、入链、重算、落盘）。
     这是评分标题「推理轨迹可视化**与人工介入**」里"人工介入"的直接落点：
     **模型没连出来的依赖，人可以连；连错了，人可以删——两次都入链、都可审计。**
     人工加的边**同样要过第 2 条的机械校验**（人是最高权限，但不能造出自环和环）。
- **明确禁止**：
  ① **不许合成新的中间结论节点**（见第 2 条收窄理由）；
  ② **不许让依赖边参与置信度计算**——`conclude_confidence` 的四分量口径（强度×覆盖×一致性×链完整性）**一个字节都不改**。
     依赖只用于**传播与展示**。一旦进分，人工画一条边就能刷分，`/api/conclusion/depends` 立刻从"审校入口"变成"作弊入口"；
  ③ **不许自动删除／自动改写下游结论**（`premise_broken` 只亮牌）；
  ④ **不许在成环时静默丢边**（必须披露环路径）；
  ⑤ **不许动 `app/core/confidence.py` 的公式与四分量**（本单只许改它 `:17` 那句与实现不符的**注释**）；
  ⑥ **不许把归并组成员（`status=="merged"`）当中间结论复用**；
  ⑦ **不许加 `sleep`／重试来掩盖 LLM 失败**（失败就走 0 条边＋披露）；
  ⑧ 禁止动 `tests/conftest.py` 的禁真调用守卫、禁止动 `cases/` 任何字节、**禁止真调用模型**；
  ⑨ **官方样例集在仓库外**，禁止拷进仓库；测试一律用 `tmp_path` 造最小同构 fixture；
  ⑩ **禁止针对官方六案硬编码**任何依赖边／结论 id／专题名。
- **A/B 口径**：第 2 条的 LLM 依赖抽取**无法按 `docs/ab-protocol.md` 跑红绿差**（机械闸只能查 id 合法性与环，
  查不了"这条依赖在语义上对不对"，而对错要金标——金标只有 18 题且官方禁止过拟合）。
  故按第三口径：**机械可核验的部分（id 合法、无环、兜底不炸、置信度不受影响）正常上判据；
  语义正确性在代码注释与报告文案里明写「依赖边由模型抽取，语义正确性未经 A/B，人工可在 `/api/conclusion/depends` 增删并留痕」**——
  这句话本身就是 3.1.3 要的"人工介入"，不是免责声明。
- **验收判据（Qoder 独立复放，开箱可跑）**：
  - `.venv/bin/python -m pytest tests -q` → 0 failed，passed ≥ **C-14 收口后的基线 ＋ 9**
    （基线以 C-14 验收记录里的 pytest 尾行为准）；**连跑 5 次全绿**（C-10 已修 flake，此时判据才站得住）。
  - 新增用例（`tmp_path`，零 LLM，用 `ScriptedClient` 喂固定依赖抽取响应）：
    a) **机械校验逐条拒收**：造 ①id 不存在 ②自环（x→x）③二节点环（x→y→x）④三节点环 ⑤指向 `merged` 结论
       → 五种各自被拒、`depends_on` 里不留脏边、且**每种都出一条披露**（不是只拒不报）；
    b) **零 LLM 兜底**：依赖抽取那次调用抛异常 → 0 条边、`build_reasoning_graph` 仍能构建、
       披露含「依赖边未生成」、**管线不炸**（跑完整 `run_case` 断言产物落盘）；
    c) **传递闭包**：造链 A←B←C←D（D 依赖 C、C 依赖 B、B 依赖 A）→ `affected_downstream(A)` **＝[B, C, D] 且顺序确定**；
       再造菱形 A←B、A←C、B←D、C←D → 结果 **＝[B, C, D] 且 D 只出现一次**；
    d) **环保护（带超时）**：绕过生成校验、直接把一个环写进 `depends_on` → `affected_downstream` 必须**终止**
       （用例用 `signal.alarm` 或 `pytest-timeout` 之外的办法自证，**不许 sleep**），且返回值不含重复 id；
    e) **人工介入入链**：调 `POST /api/conclusion/depends` add 一条合法边 →
       `chain.jsonl` 多一条 `human` 事件、`depends_on` 真的变了、`report.json` 重载后边还在；
       再 add 一条会成环的边 → **422 拒绝且不写链**（人工也不能造环）；
    f) **失效传导**：删掉上游结论的全部证据 → 下游 `premise_broken` 含该上游 id、
       **下游结论仍存在**（未被自动删）、报告渲染里能读到这条黄牌；
    g) **置信度不受影响（本单最重要的反向断言）**：对同一份案卷，**加边前／加边后／删边后**三次
       调 `conclude_confidence`，每条结论的返回值与四分量 dict **逐位相同**；
    h) **回归钉死**：现有全部 `reasoning_graph` 相关用例的 `nodes`/`edges` 集合**逐字不变**
       （新增的边只能是 `kind=="depends_on"`，新增的节点键只能是 `is_premise`）；
    i) **旧报告可加载**：构造一个**不含** `depends_on`／`premise_broken` 的旧 `Conclusion.to_dict()` 形态 dict
       → `from_dict` 不抛、两字段落默认空列表。
  - **架构师复放探针**（我自跑，不需要你造数据）：
    1. 跑 `cases/rumor-vs-official`（冲突密集）→ `GET /api/reasoning_graph` 里 `depends_on` 边 **≥1** 条、
       `is_premise==true` 的节点 **≥1** 个；若为 0，我会先确认是模型没抽出来还是校验全拒（两者都算不通过，但返工方向不同）；
    2. 在工作台删一条**上游**证据 → 响应 `op` 里出现受影响集合、`chain.jsonl` 有对应事件、下游出 `premise_broken`；
    3. 判据 g 的存量版：对全部 34 份存量产物跑"加一条边→比置信度→删掉→再比"，**逐位不变**；
    4. 反向探针：`git diff app/core/confidence.py` 里**只有 `:17` 那行注释**，公式与常量零改动。
  - `git diff --stat cases/` 为空；`git status` 里不得出现官方样例集任何文件。
- **工时**：约 1 天（数据模型＋校验 0.25、LLM 生成＋兜底 0.25、传播＋失效 0.25、端点＋渲染＋九条用例 0.25）。
- **撞车点（协议 §9.1）**：**必须排在 C-12 与 C-14 之后**——
  ① C-12 改 `app/pipeline.py` 的编排（多题运行），本单要在"归并之后、置信度回填之前"插一遍，**同一处编排代码**；
  ② C-14 改 `app/agents/arbiter.py` 的 `Resolution` 构造与 `app/core/conflicts.py`，
  本单的依赖抽取**必须放在新模块 `app/core/dependency.py`**（不要塞进 `arbiter.py`），否则两单改同一个类；
  ③ `app/server.py` 的 `_mutate` 只有本单动（C-12 动的是导出挂点）。
  与 C-10 零重叠（C-10 只动 `tests/test_collab.py`）。
- **开工提示词（协议 §9.1；**必须在 C-12 与 C-14 都验收并提交之后再动**）**：

```
读 docs/dev-protocol.md（分工协议，重点 §3.0 前提核查、§3 问题分流、§3.4 质疑通道）和 docs/HANDOFF.md §5 的工单 C-13，你是执行工程师。
本单只做「要求」列出的五件事＝给推理树补上「中间结论层＋结论→结论依赖边＋依赖传播」，对着评分 3.1.3 那 10 分。
实现细节以工单原文为准，不要照本提示词施工。
先做协议 §3.0 前提核查再动工，特别是这一条：工单里有一处「旧口径更正」——
本页队列表原先写「人工改证据只重算直接被支撑的那条」是错的，app/server.py:268 的 _mutate 调的是 recompute_all（全量重算）。
请你独立核一遍这句更正对不对（读 server.py:248-279 与 confidence.py:131-149），
并核对其余行号（reasoning_graph.py:3-11 七种边、evidence.py:191-217 Conclusion 十一个字段、
server.py:694/:707/:734/:775/:790、confidence.py:90-98 无证据返回 0）；有一条对不上就按 §3.4 说，别默认我对。
本单 v1 有意收窄：只在既有结论之间连边，不合成新的中间结论节点；中间结论＝被依赖的既有结论（is_premise）。
这是已知缺口，必须在报告里披露，不许在文案里说成"已实现中间推理层"——你若认为必须合成新前提才拿得到 3.1.3 的分，
按 §3.4 写质疑并附官方原文依据（contest-scoring-rubric:285 与 contest-decks:297-301），不要默默扩大范围。
允许动的落点：app/core/evidence.py 的 Conclusion 两个新字段、新增 app/core/dependency.py、
app/core/reasoning_graph.py 的 depends_on 边与 is_premise 标记、app/pipeline.py 插一遍依赖抽取、
app/server.py 的 _mutate（写受影响集合进 payload 与 op）与新增 POST /api/conclusion/depends、
报告与工作台前端的渲染、app/core/confidence.py 只许改 :17 那行与实现不符的注释、新增测试。
明确禁止（工单十条，逐条照办）：不合成新中间结论节点；不让依赖边参与置信度计算（四分量口径一个字节不改）；
不自动删除或改写下游结论（premise_broken 只亮牌）；成环不许静默丢边（要披露环路径）；
不动 confidence.py 的公式与常量；不把 merged 归并成员当中间结论；不加 sleep／重试掩盖 LLM 失败；
不动 tests/conftest.py、不动 cases/ 任何字节、不真调用模型；官方样例集禁止拷进仓库，测试用 tmp_path；
不针对官方六案硬编码依赖边／结论 id／专题名。
依赖边的语义正确性 A/B 不了（要金标，金标只有 18 题且官方禁止过拟合），按工单的第三口径处理：
在代码注释与报告文案里明写「依赖边由模型抽取，语义正确性未经 A/B，人工可在 /api/conclusion/depends 增删并留痕」，不要假装验证过。
开发中若发现问题按协议 §3 分流：本单内的就地修并写「偏离工单之处＋原因」；
会改 report.json 已有字段取值的停手写提案；新洞只记「发现（未修）」，不要顺手修。
完成后回写：工单状态行改「已改完（YYYY-MM-DD），待架构师验收」＋动了哪些文件＋新增用例名＋pytest 尾行。
自查判据：pytest tests -q 连跑 5 次 0 failed 且 passed ≥ C-14 基线＋9；a–i 九条用例齐
（g 置信度逐位不变是本单最重要的反向断言，d 环保护不许用 sleep，e 要证明人工也不能造环）；
git diff --stat cases/ 为空；git diff app/core/confidence.py 里只有 :17 那行注释。
不要提交，不要 push，验收归 Qoder。
```

- **状态**：待开工（2026-10-16 出单，**队列第四＝最后一张**；门在 C-12 与 C-14 之后）。｜ **验收**：—

## 6. 索引

| 想知道什么 | 看哪儿 |
|---|---|
| 怎么把系统跑起来 | `AGENTS.md`（现场部署指引，通过判据 553 passed） |
| 官方要什么、怎么评分 | `docs/contest-briefing-2026-10-14.md` |
| 我们判场景判成了什么、七条结论 | `docs/scenario-review-2026-10-14.md` |
| 每批改动的问题/决策/验证/开放项 | `docs/dev-journal.md`（§22 是最新一批） |
| 竞品 REA 研读与吸取清单 | `docs/rea-study.md`（§7 基线、§8 落地记录） |
| 对外方案（答辩用） | `docs/proposal-formal.md`、`docs/proposal.md` |
| 质量有没有退化 | `python scripts/score_artifacts.py`（离线复放打分器） |
| 各项数字怎么复放 | `python scripts/measure_baseline.py` |
| 2000 篇规模下三道天花板各值多少钱 | `PYTHONPATH=. .venv/bin/python scripts/measure_capacity.py`（零 LLM，约 22s，结论见 §5「C-7 前置实测」） |
| 发出去的材料模型真看到了吗 | `PYTHONPATH=. .venv/bin/python scripts/probe_context_window.py`（需本机 Ollama 在线，暗号复述法，结论见 §5「C-9 前置实测」） |
| 官方六案里同源污染有多少（票数能不能进权重） | `PYTHONPATH=. .venv/bin/python scripts/probe_source_dedup.py`（零 LLM，约 1s，结论见 §5「C-14 前置实测」） |
