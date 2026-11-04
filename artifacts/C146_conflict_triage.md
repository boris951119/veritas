# C-146｜树22 冲突分流（口语误读／日期档 vs 真打架）交账

会话2（执行工程师2号）· 基 tip `03bfd4a`（含 C-145a）· 枝 `qoder/c146-conflict-triage`
读数全部由 `scripts/probe_c146_triage_face.py` 现抄，见 `artifacts/C146_triage_face.json`／`.md`；本文件只写解释与边界，不重复手打数字。

## 1. 现 tip 冲突出口盘点（步骤 1）

三处出口，全在 `VERITAS_CONFLICT_TRACE`（C-145a 起出厂开）这一根旗下面：

| 出口 | 位置 | 现在写什么 |
|---|---|---|
| 事实对撞台账 | `app/core/fact_ledger.py` `find_collisions` → `Collision.time_class` | 三档 `same_window`／`cross_day`／`unknown_time`；同 (实体, 量名) 下 >1% 容差的异值；量名规范闸（C-80）给 `metric_canon`／`canon_reason` |
| 结论冲突对 | `app/agents/arbiter.py` → `dossier.conflicts`（`ConflictPair`＋`Resolution`） | 谁与谁矛盾由 LLM 判，机械侧只校验合法性与簿记（胜方／落败转少数／平局） |
| 留痕与导出 | `app/core/conflict_trace.py`（pipeline 两处挂点：摄取后带 collisions、仲裁后刷新）＋ `app/export/official.py` 的 `conflict_trace.json` | 行＝`conflict_class`＋`disposition`＋`reason_code`＋`reason_short`＋`entry`；summary＝`n`／`coverage_rate`／`trace_complete_rate`／`by_class`／`by_disposition` |

提示词注入那条腿（`facts_block`）读 `time_class` 换文案，本刀未动。

## 2. 分流为什么是第二根轴，不是「第四类」

C-115 把三档钉成硬枚举，`tests/test_c115_conflict_trace.py` 里三颗守护格当场咬（`CONFLICT_CLASSES == {…}`、越界→`unclassified`、禁「无日期＝非冲突」）。把 `oral_misread`／`date_offset` 塞进 `conflict_class` ⇒ 既有格立刻红＝违「红不扩」。

所以本刀加**正交的第二轴**，写在同一行的 `triage_*` 五键上：

- `conflict_class` 答「时间上怎么摆」；
- `triage_class` ∈ {`oral_misread`, `date_offset`, `true_oppose`, `other`} 答「这到底像不像一次真对立」。

两轴交集为空（仪器 `axes_orthogonal=true` 现量）。齐全率两套分开钉：`TRACE_REQUIRED_KEYS` 一字未动，新增 `TRIAGE_REQUIRED_KEYS`＋`triage_fields_complete()`——旧产物行（无分流键）只算「未分流」，不被判成「留痕不齐」（`test_c146_legacy_rows_…` 钉住，同时保护既有 C-115 读数）。

`disposition` 规则表（跨日→keep、其余→undecided／按裁决 dissent）原样保留：真对立照旧进既有处置留痕，日期差照旧落时间档。分流不进任何判定、加权、置信、归并、采信（数值冲突线仍 STOP）。

## 3. 分流阶梯（全机械、零 LLM）

事实对撞行（`triage_ledger_collision`）：

1. `cross_day` → `date_offset`（默认倾向时间档，理由句写明「按时间档处理、不等于资料无冲突」）；
2. 数字邻域带约数词（约／近／超／多／左右…，段文本现取）且组内极差占比 ≤ 0.25 → `oral_misread·hedge_number`；
3. 两值成 10 的整数倍率（k=1..4，容差 1%）且数字串逐字相同 → `oral_misread·scale_misread`（单位／小数点读错）；
4. C-80 量名闸已判「不是量名」（`metric_canon` 空＋`canon_reason` ∈ not_quantity／no_quantity_hint／empty）→ `oral_misread·metric_not_quantity`；
5. 两个数出自同一段落 → `oral_misread·single_segment_two_numbers`；
6. `unclassified` → `other`（依据不足不硬塞）；
7. 其余（同窗／时点不明的异值）→ `true_oppose`。

结论冲突对行（`triage_conflict_pair`）：`cross_day`→`date_offset`；原文取不到→`other`；归一化后逐字相同→`oral_misread·pair_statement_identical`；主体标签都在且不同→`oral_misread·pair_subject_mismatch`；议题维都抽到且不相交→`oral_misread·pair_topic_disjoint`；极性一正一负（沿用配对闸同一张表）→`true_oppose·pair_polarity_opposite`；两侧数值集合不相交→`true_oppose·pair_disjoint_numbers`；否则 `other·pair_mechanically_undetermined`。

每行的判据数字（极差、倍率、议题维、极性、数值集合）随行走 `triage_evidence`，可当场复算。

## 4. 读数（仪器现抄）

- 夹具反事实：14 行输入，改前 tip（`03bfd4a`）码与改后码各跑一遍，**剥掉 `triage_*` 五键后差异行数 = 0**；快照入仓 `tests/c146_pre_triage_snapshot.json`（测试读快照，不读代码自证）。
- 三类各 ≥1 例：14 条腿全部按设计落档（`test_c146_*` 16 颗格，含降级腿）。
- 三案例离线 demo（开旗）留痕 7 行：`oral_misread` 3／`other` 3／`true_oppose` 1／`date_offset` 0。
- 开旗跨树：`report.json` 差异路径 53 条，**全部在 `conflict_trace` 面内（面外 0）**；`report.md` 3/3 规范化同形；`chain.jsonl` 摘掉 `conflict_trace` 载荷后行多重集 3/3 相同 ⇒ 开旗唯一变化就是分流载荷本身。
- 关旗跨树（`VERITAS_CONFLICT_TRACE=0`）：`report.json` 差异路径 0 条；`report.md` 3/3 同形；`chain.jsonl` 3/3 多重集相同（缓存已对齐主检出后背靠背重跑）。
- pytest：改前 `7 failed, 1265 passed, 1 skipped` → 改后 `7 failed, 1281 passed, 1 skipped`；FAILED 名单逐名相同（**红不扩**，+16 全来自本刀新格）。
- 禁品面：`audit_forbidden_keys(payload)` 空；序列化面零 `gold`／`金标`／`coeff`／`weights`。

## 5. 变异刀（七把，全有牙）

在枝上临时改码跑测、跑完按 sha 复位（复位前后 sha 相同）：

| 刀 | 咬住的红格 |
|---|---|
| K1 分流改写 disposition | 反事实格＋处置表格 |
| K2 把分流档写进 `conflict_class`（发明第四时间档） | 9 颗（含 3 颗既有 C-115 格） |
| K3 摘掉日期差优先腿 | 3 颗 |
| K4 摘掉段文本接线（约数腿失效） | 1 颗（出口真接线格） |
| K5 summary 不写分流计数 | 6 颗 |
| K6 「判不出」塞进真对立 | 1 颗 |
| K7 把分流键并进 `TRACE_REQUIRED_KEYS`（吃掉旧行齐全率） | 2 颗（含既有 C-115 覆盖格） |

## 6. 边界与待拍（这三个我不自己拍）

1. **`date_offset` 在 demo 里 0 行**＝三案例的对撞行没有跨日样本（多为时点缺失→`unknown_time`）。要量到这一档得跑官方案例（花钱、另令），不能对外说「日期档已验过真产物」。
2. **`other` 占 3/7**：定性结论冲突（「是否停工」这类）机械判不出，全部落 `other`。我实测过 8 字滑窗 Jaccard 想抓「同义改述」——六组改述里五组＝0.0、只有近乎逐字重合才 >0.7，分不开，所以**没用**这条腿。要吃掉 `other` 只能上语义判（属树22 语义侧／另票）。
3. **分流要不要进报告叙事面**：现在只进 accounting＋`conflict_trace.json`，`report.md` 一字未动（正是这条让跨树同形成立）。路演要在报告里看见三档分布，得单开出面＋重跑同形判据。

## 7. 按单未做

未碰归并硬约束（C-145 并行线，其 worktree／未提交面一字未动）；未做质证／仲裁全套；未动 24／25／27；未开 `cite_accept`；禁合 C-123 整枝；未改冲突数值加权／打分。独立 worktree（`~/Developer/veritas-c146`），不自行合 main。

## 8. 交付面

- `app/core/conflict_trace.py`（分流轴＋两套齐全率＋summary 分流计数）
- `app/export/official.py`（回放面 `detail` 声明四档）
- `tests/c146_triage_fixtures.py`（合成夹具，测试与仪器共用）
- `tests/c146_pre_triage_snapshot.json`（改前码输出快照，入仓）
- `tests/test_c146_conflict_triage.py`（16 颗）
- `scripts/probe_c146_triage_face.py`（--stage export|demo|crossface|assemble）
- `artifacts/C146_triage_face.json`／`.md`＋本文件
- `docs/dev-journal.md` 〔C-146〕一条（仪器真引用落点）
