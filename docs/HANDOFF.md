# HANDOFF · 当前状态与交接页

> **这份文件是跨工具交接的唯一入口。**
> 换任何开发工具（Cursor / Claude Code / Codex / 另一个 Qoder 会话）时，新工具只要读到本文件
> 就能接上进度；`AGENTS.md` 与 `CLAUDE.md` 都指向这里。
> **纪律**：每次收工或换工具前，对当前工具说一句「更新 HANDOFF 并提交」——
> 记忆不会跨工具走，**只有进了 git 的文件才算同步**。

最后更新：2026-10-16 · 分支 `cursor/knife11-second-pass-and-gates` · C-4/C-5 待 Qoder 验收（未提交）

## 1. 现在在哪儿

- 最近提交：`56f1e7e feat(可信度): 推理链完整性进分`——置信度从三分量升为**四分量**
  （强度 × 覆盖 × 一致性 × **链完整性**），六环判定复用各道零 LLM 机械闸的输出，分数与警示同源。
- 测试：`pytest tests -q` = **545 passed**（C-1/C-2 已验；本轮 C-4＋3、C-5＋4），零失败零跳过，约 4 秒；
  测试期有禁真调用守卫（`tests/conftest.py` 上膛，忘塞桩的测试当场炸，不会偷花云端 key）。
- 实测净效应：34 份存量产物 294 条可计分结论，链中位 0.75、满分仅 40.1%；
  置信度中位 0.2133 → 0.1813（**−15.0%**）。复放命令：`python scripts/measure_baseline.py`。
- **主线仍「等官方材料」**；例外是 §5 工单（C-1/C-2/C-4/C-5 已通过验收，C-3/C-2b 不开工）。
  输入层「漏了但知道漏了」自 2026-10-16 起对 **7 道召回口子全部成立**（披露≠召回，口子本身仍在）。

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

## 4. 六个已知的坑（新工具必须先知道）

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

## 5. 待 Cursor 修复工单（Qoder 出验收，双方不口头交接）

> 用法：Cursor 按工单改，改完把「动了哪些文件 + 新增用例名 + `pytest` 尾行」写回本节该工单下面；
> Qoder 按「验收判据」复放，结果写在同一格（通过／打回＋原因）。**不通过不合并。**

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
