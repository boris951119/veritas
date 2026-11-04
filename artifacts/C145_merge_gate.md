# C-145 — 树22 归并硬约束闸（同主体×同指标×可核验才合）

> 判定＝**YES**（闸随 VERITAS_CONFLICT_TRACE，C-145a 起出厂默认开；env=0 全关＝改前归并行为逐字节一致）。
> 只看 LLM 语义归并段；机械归并键已含三腿零改动；数值冲突加权／打分零改动（STOP 线）。

## 判据逐条

- g1_闸在场_默认开零调用＝True
- g2_误并例等于0＝True
- g3_该合的合＝True
- g4_关旗与改前同形＝True
- g5_改前错并在场_夹具有判别力＝True

## delta（default 臂・branch vs base 03bfd4a）

- 改前错并成员数 6 → 改后 2（差 4）
- 误并成员 ids：改前 ['CON-2', 'CON-3', 'CON-4', 'CON-5'] → 改后 []
- 多数结论数：改前 3 → 改后 5

- pytest：7 failed, 1275 passed, 1 skipped（61.3s；7 红与基线 03bfd4a 同名单逐个一致：test_c19_pack_window m_production_messages_bite、test_c37 五颗、test_c73 kept 刀；本票新增 10 颗全绿，test_collab 夹具适配一处＝结论带主体/议题词，断言零改动）

## 行为说明（关／开 CONFLICT_TRACE）

- 关（VERITAS_CONFLICT_TRACE=0）：闸全关＝改前归并行为（错组照并、无闸键、无回放节）＝腿③字节等证。
- 开（默认）：LLM ≥2 人组过四腿（同主体／同指标／极性不反／可核验）；不过→整组否决成员保独立＋accounting[merge_gate]＋conflict_trace.json merge_gate 节。

## 产物卫生

- 夹具全部合成（客户B/客户C/项目…占位句），无官方语料原文；闸行只记 id 与腿读数，不落结论文本。
- 字节面归一：归并组结论 id＝uuid4 逐进程随机（既有行为，非本票引入）⇒ 量尺面把生成 id 按各文件首现序匿名化（CONX-NN）；chain.jsonl／progress.json 逐跑日志面不计入；report.json／report.md 剥 elapsed 时戳。
- 主席头条并列破平键＝结论 id（uuid 生成）＝置信度精确并列时逐跑可非确定（预存在行为，与本票无关；夹具用 A/B/C 分层证据避开并列）。正式修它＝动 chair 破平键，超出本票范围。
