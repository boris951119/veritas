# HANDOFF · 当前状态与交接页

> **这份文件是跨工具交接的唯一入口。**
> 换任何开发工具（Cursor / Claude Code / Codex / 另一个 Qoder 会话）时，新工具只要读到本文件
> 就能接上进度；`AGENTS.md` 与 `CLAUDE.md` 都指向这里。
> **纪律**：每次收工或换工具前，对当前工具说一句「更新 HANDOFF 并提交」——
> 记忆不会跨工具走，**只有进了 git 的文件才算同步**。

最后更新：2026-10-16 · 分支 `cursor/knife11-second-pass-and-gates` · **C-6 架构师已复放：判据①–⑥全过、打回一条 R-C6-1，未合并**（工作树有未提交改动）

> **分工与协作规则已单独成文**：[`docs/dev-protocol.md`](dev-protocol.md)——Qoder＝架构师/规划（出单、独立复放验收、review、同步图与本页、提 commit），
> Cursor＝执行工程师（按单实现、按 §3 处理开发中发现的问题、回写状态行）。**给 Cursor 的开工指令模板在该文件 §9，直接粘贴即可。**

## 1. 现在在哪儿

- 最近提交：`e7a5170 docs(协作规则)`；最近**代码**提交 `56f1e7e feat(可信度): 推理链完整性进分`——
  置信度从三分量升为**四分量**（强度 × 覆盖 × 一致性 × **链完整性**），六环判定复用各道零 LLM 机械闸的输出，分数与警示同源。
- 测试：`pytest tests -q` = **552 passed**（C-6 ＋7），零失败零跳过，约 4 秒；
  测试期有禁真调用守卫（`tests/conftest.py` 上膛，忘塞桩的测试当场炸，不会偷花云端 key）。
- 实测净效应：34 份存量产物 294 条可计分结论，链中位 0.75、满分仅 40.1%；
  置信度中位 0.2133 → 0.1813（**−15.0%**）。复放命令：`python scripts/measure_baseline.py`。
- **主线仍「等官方材料」**；例外是 §5 工单（C-1～C-5 已通过验收并已提交；C-6 已改完、**架构师复放打回一条 R-C6-1 未合并**；C-3/C-2b 不开工）。
  输入层「漏了但知道漏了」自 2026-10-16 起对 **7 道召回口子全部成立**（披露≠召回，口子本身仍在）；
  这句**只覆盖遍历/摄取侧**；上传链路要等 C-6 收口才轮得到它（R-C6-1 未修完前对外别提）。
  另：拿到「单专题 ≤2000 篇」后，500 封顶那道口子的量级已从［未量］变成
  **「最多 3/4 的材料进不了案卷」**——这是 C-7 立项依据，也是材料当天第一个要实量的数。

## 2. 在等什么

官方邮件（接榜确认函已于 2026-10-14 提交）：① 榜单**验收标准**（硬指标，未达即废榜）；
② **评分标准细则**（每项给几分）；③ **样例集**（含人工抽取的证据/结论字段，结构未知）。
宣讲会情报与原文转写已存盘：`docs/contest-briefing-2026-10-14.md`、`docs/contest-transcript-2026-10-14.txt`。

## 3. 材料到手后的动作顺序（已与用户对齐）

1. 先花半小时**读样例集 JSON 字段结构**——它决定要不要做「逐题答题纸」改造
   （`Dossier.question` 现在是单个字符串，官方评测却是「原始数据 + 问题清单，逐题交证据与结论」）。
2. 按 `docs/scenario-review-2026-10-14.md` 的七条结论，往「人的研判十格对照表」上**贴分值**，
   产出三样：数据流图、评分项×环节对照表、环节缺陷表。颗粒度硬边界＝能回答「扣分能不能落到这个环节」为止。
3. 优先级最高的动手项（若结论成立）：**把「独立信源簇」做成数据结构**（约 1 天、零 token）——
   覆盖分量、冲突判定、篡改检测、孤证显影四件事都踩在它上面。

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
7. **工作台「添加文件夹」会静默覆盖材料**（2026-10-16 实测发现；工单 C-6 已实现，**架构师复放打回 R-C6-1，尚未合并**）。
   修复前：`import_case.py:41` 对 >4 段相对路径**截掉最后一段＝文件名**，两份深层文件塌成同一路径后
   `write_bytes` 后者覆盖前者，而接口照样返回 `n_written=2`、`skipped=[]`。探针实证：
   上传 `top/a/b/c/一月报告.txt`＋`二月报告.txt` → 磁盘只剩一份 `top/a/b/c`，内容是一月的对手，**零报错零披露**。
   工作树现状：超深路径改为一律拒收＋分原因披露（`deep_path`/`hidden_path`/`oversize`），复放确认零残留、
   报告「摄取披露」章可读、删除环同源。遍历侧（`_collect_files`）的深度洞已由 C-1/C-5 收口；
   **但 C-6 把后缀过滤同时用到超深目录计数上，导致「深层目录全是图片」时 `dir_truncated` 整条披露消失＝C-1 回退**——
   所以这句仍不成立：**「全部丢件都有披露」现在既没覆盖上传链路，也在图片目录这条分支上重新漏了**。

## 5. 待 Cursor 修复工单（Qoder 出验收，双方不口头交接）

> 用法：执行工程师（Cursor）按工单改，改完把「动了哪些文件 + 新增用例名 + `pytest` 尾行」写回本节该工单下面；
> 架构师（Qoder）按「验收判据」独立复放，记录写在同一格（通过／打回＋原因）。**不通过不合并。**
> 规则全文见 [`docs/dev-protocol.md`](dev-protocol.md)；开发中发现的问题按该文件 §3 分流，不许顺手改结论。

### 5.0 队列与门禁（谁动、什么条件下才动）

| 单号 | 事项 | 依赖官方材料？ | 状态 | 工时 |
|---|---|---|---|---|
| **C-6** | 导入侧深层路径静默覆盖（拒收＋分原因披露）＋「可摄取文件数」按后缀对齐 | **不依赖** | 已实现；架构师复放判据 ①–⑥ 全过，**打回一条 R-C6-1（图片目录使 C-1 披露消失）** | 回归约 20 分钟 |
| **C-7** | 超 500 文件时**取哪 500**：现按文件名排序（`case_loader.py:345`），相关性不参与；且 500／深度 3 无 env、无 manifest 可配 | **数已到手：单专题 ≤2000 篇 > 500** → 大赛题必有 1500 篇根本不进案卷，这是当前最大的一阶召回口子 | **立项，C-6 收口后开工**（出单前需拍板「按相关性取」还是「按配额取」） | 待架构师出单 |
| ~~C-8~~ | 两侧深度一起抬到 5（真收深层目录） | **数已到手：官方材料最深 3 级** → 现上限（遍历 3 层／导入 4 段）本就够 | **撤销**（C-6 的 `deep_path` 拒收不会误伤真实材料，只会挡住人工塞进来的超深目录） | — |
| C-3 | 切段定长退化切（`segment.py:121`） | 需先量发生率 | 只记录 | 待定 |
| C-2b | 指标归一化／词表（治措辞分裂的真漏检） | **依赖样例集**，且先做独立信源簇 | 不开工 | 约 1 天 |
| — | 独立信源簇做成数据结构（覆盖分量、冲突判定、篡改检测、孤证显影的共同地基） | 不依赖材料，但**会改结论** → 需拍板 | 待用户 go | 约 1 天 |
| — | `docs/proposal-formal.md:147/:151` 对外数字同步（旧口径 13,700 行／415 测；现值待 C-6 收口后用 `scripts/measure_baseline.py` 一次测齐） | 不依赖 | 待用户点头，架构师改文档 | 10 分钟 |

**材料到手当天的固定动作**（不排工期，来了就做）：① 读样例集 JSON 字段结构（决定要不要做「逐题答题纸」改造）；
② 跑一次台账六桶分类统计＋畸形指标密度，用数据决定 C-2b 值不值得占用簇改造那一天；
③ 拿真数据跑分诊账本，把「7 道召回口子」＋C-6 这条导入侧口子的丢件率从［未量］变成有数——
   **按 ≤2000 篇这个数，500 封顶那道口子的实际丢件率会远超其余各条，是当天第一个要量的。**

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
- **状态**：已改完（2026-10-16），架构师已复放。｜ **验收**：**判据 ①–⑥ 全过，但打回一条 R-C6-1——不通过不合并**。
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
  - 尾巴（不阻断合并）：`manifest.import_refused` 只追加不清理——用户把超深材料压平重传后，旧拒收行仍留在报告里，
    属**过期披露**（方向安全：多说不少说），要不要做「重传即清同名条目」另开单定；
    `import_refused` 使 `ROUTE_LABEL` 变成 **17** 个——**图上仍写 16 是对的**，那格反映已合并状态，
    本单合并后再同步（文档口径的绿不算绿，反向也一样：提前写的绿更不算）。
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

## 6. 索引

| 想知道什么 | 看哪儿 |
|---|---|
| 怎么把系统跑起来 | `AGENTS.md`（现场部署指引，通过判据 532 passed） |
| 官方要什么、怎么评分 | `docs/contest-briefing-2026-10-14.md` |
| 我们判场景判成了什么、七条结论 | `docs/scenario-review-2026-10-14.md` |
| 每批改动的问题/决策/验证/开放项 | `docs/dev-journal.md`（§22 是最新一批） |
| 竞品 REA 研读与吸取清单 | `docs/rea-study.md`（§7 基线、§8 落地记录） |
| 对外方案（答辩用） | `docs/proposal-formal.md`、`docs/proposal.md` |
| 质量有没有退化 | `python scripts/score_artifacts.py`（离线复放打分器） |
| 各项数字怎么复放 | `python scripts/measure_baseline.py` |
