# C-122 — 引文逐字核对的漏桶与转写稳定性（实验旗默认关）

> 判定＝**NO**（六条判据 4/6 过；门槛在开臂真跑出数之前写死）。
> 枝＝`qoder/c122-cite-check-stable`（从 main 开，不合 main）；旗＝`VERITAS_CITE_CHECK_STABLE`，出厂默认关。

## 0. 不带编号的说明（这段给不看代码的人）

系统在交卷前会做一件事：把模型写的每一条引文拿去和它说自己摘自的那段原文逐字比对，对不上就把这条证据整条删掉。这次要修的就是这台「比对机」误杀好料的地方。
实测下来，判失败的证据里占大头的是**转写差一点**（fuzzy_close 106 条＝占失败 0.567），纯排版差 10 条，而真胡编／挂错段（必须一直判失败）＝71 条＝占失败 0.38——所以这台机器确实在误杀可用证据，但不能靠放宽来救。
改法是两道窄闸：第一道只宽容排版差异（内容一个字都不许变）；第二道在原文里找到那句话真正对应的连续片段、把模型写歪的引文换成原文，而且必须同时过数字守恒、相似度、覆盖率、长度上限四道闸，换完还要再过一次原来的严格尺。任何一道不过就照旧判失败。
效果：自家历史产物面上失败率 0.1904→0.1487（其中排版道救 10 条、换原文道救 31 条）；刘翔 q_003 真跑两臂各 5 遍的结果见 §4。

## 1. 成因归因（件①·零模型调用·自家产物面）

- 面＝/Users/liuboyu/Developer/veritas/cases/*/out*/report.json｜份数 34｜坏文件跳过 0 份（跳过≠没失败，计数在场）｜证条 982（在盒 792／已打回 190）｜抠不到 segment_ids 的 0 条
- 判失败 187/982＝**0.1904**（尺＝app/core.citation_check.check_evidence（生产同一把尺））
- 桶：{'pass_current_check': 795, 'fuzzy_close': 106, 'real_hallucination': 70, 'fmt_recoverable': 10, 'other_seg_hit': 1}
- 桶（已打回那一批里）：{'fuzzy_close': 106, 'real_hallucination': 70, 'fmt_recoverable': 10, 'pass_current_check': 3, 'other_seg_hit': 1}
- 读数（脚本现抄）：失败 187/982＝0.1904｜A 面（排版归一化可救）＝10 条＝占失败 0.053｜B 面（近似转写可回贴）＝106 条＝占失败 0.567｜救不了（真胡编／挂错段／空引文）＝71 条
- 差异字符类直方图：{'other': 875, 'punct_ascii': 801, 'digit': 137, 'entity': 24, 'punct_cjk': 19, 'dash_wave': 4}
- 阈值：{'fuzzy_ratio': 0.85, 'fuzzy_lcs_share': 0.6, 'min_lcs': 8}

## 1b. 官方卷真跑的打回原因（件①b·零 LLM 之外唯一一条真模型面·脱敏）

- 面＝刘翔编制“二选一”事件／q_003｜真跑 3 遍（旗**关**＝只诊断，不救）｜模型 openai/veritas-qwen3-14b｜温度 None
- 桶：{'fuzzy_close': 9, 'pass_current_check': 4, 'real_hallucination': 4}｜打回 13 条（`pass_current_check`＝核对过的通过条，不在失败里）
- B 四道闸的拒因分布：{'ratio_below_gate': 6, 'coverage_below_gate': 7}＝这就是「官方卷上 B 一次没 fire」的直接原因（不是没试，是试了被挡）
- 未尝试原因（段根本不在盒里之类）：无
- 泄漏＝0｜落盘面＝长度＋sha8＋原因码，官方原文一字不落
- 读数与件①（自家产物面）对照：那边 fuzzy_close 106 条候选、B 真救回 31 条；这边 fuzzy_close 的 best_ratio／coverage 大多卡在闸下＝**两面的「转写不稳」不是同一种不稳**，件②b 救回的条数不能算到官方卷头上。

## 2. 选的路径（单里三选一，这里选了 A＋B 窄组合，未做大重构）

- A＝`normalize_stable`（NFKC＋引号族／破折号族／HTML 标签与实体／零宽／数字千分位逗号），仍要求实质子串依次命中＝不删字、不换词、不做同义归一。
- B＝`reanchor`：只在**声明段**内找对齐窗口，四道闸（锚≥8 字／相似度≥0.92／覆盖≥0.90／长度≤1.6×／数字守恒）＋第五道总闸＝回贴后的证条必须再过一次现行严格尺。
- C（提示侧短约束）没选＝它改的是模型行为而非尺，量不到「误杀率」这一层。
- 写入面只有一个：`audit_dossier`→`materialize`（读侧 `check_evidence` 保持纯函数）；失效即从严＝回贴没落笔就判失败，不留 `verified=True` 的未核验引文。

## 3. 零模型 A/B 腿（件②b·同一把尺两侧都取到数）

- 条数 982｜失败率 关 **0.1904**（187）→ 开 **0.1487**（146）＝降 0.0417
- 救回：A 10 条｜B 31 条｜仍失败 146｜两臂都过 795
- 反向腿（开旗反而更严）＝0（必须 0）｜Σ 不变式 n_tot == pass_both + recovered_A + recovered_B + still_fail＝True
- 件① 的 fuzzy_close＝106 条候选，B 真救回 31 条＝四道闸把大头挡在外面（这就是「不放宽」的代价，也是它的证据）

## 4. 真跑两臂（件③·q_003·本机 Ollama 14B·零现金）

- 每臂 5 遍｜模型 openai/veritas-qwen3-14b｜温度＝**None**（未钉＝`llm_temperature=None`，与 C-120／C-121 本机近期实跑一致）
- 剪证尺＝pipeline._reject_failed_citations（生产剪证那一步＝打回后口径）
- 证条级失败率：关 [0.625, 0.8333, 0.7778, 0.75, 0.6667] 均值 0.7306 → 开 [0.8, 1.0, 0.6667, 0.0, 0.8] 均值 0.6533｜单侧置换检验 p＝0.43493
- 打回后保留证条数：关 [3, 1, 2, 1, 2] 均值 1.8 → 开 [1, 0, 2, 4, 1] 均值 1.6｜p＝0.68997
- 打回后金标被引段数：关 [2, 0, 2, 1, 1] 均值 1.2 → 开 [1, 0, 1, 1, 0] 均值 0.6｜p＝0.95995
- L3（金标段被引到）打回后口径：关 [2, 0, 2, 1, 1] → 开 [1, 0, 1, 1, 0]（分母 5）；打回**前**口径均值 关 2.6 → 开 1.8＝两口径不许混
- 开臂 accounting：核对 27 条｜A 记名 3｜B 回贴 0
- 泄漏合计＝**0**（假绿／不可归因合计＝0）
- A 宽容面（开臂剪后仍过不了旧严格尺的条数）均值＝0.6＝这就是买到的宽容，非空比空

## 4b. 三题合起来看（证条级池化＝把每题每遍的条数加在一起算比率）

- 用了哪几题：['q_003', 'q_001', 'q_002']（主测 q_003 每臂 5 遍＋旁证每题每臂 [3, 3] 遍）
- 关臂：核对 58 条／打回 30 条＝失败率 **0.5172**；开臂：核对 54 条／打回 20 条＝失败率 **0.3704**
- 单侧 Fisher 精确检验（开臂失败数更少）p＝**0.084839**
- 打回后被引段里金标占比（分母＝被引到的段 id 全集，与分子同单位）：关 0.75（21/28）→ 开 0.6129（19/31）｜单侧 Fisher（开臂占比更高）p＝0.920553
- 打回后保留证条数合计：关 28 → 开 34＝可用证上升；金标段被引条数合计：关 21 → 开 19＝金标侧没升（这正是「弱 YES」那一条）
- 池化只解决「n＝5 太小」这一层，不解决「同案同模型」这一层＝两臂分母各自是模型当遍产出的条数，所以比率可加、条数不可比。

## 5. 桩腿（零调用全路径）15 条判据

- 两臂盒指纹相同＝True
- 两臂提示字节相同＝True
- 五条桩都进了剪证前清单＝True
- 关臂至少打回 3 条（排版脏＋漏字＋凭空编）＝True
- 开臂打回严格少于关臂＝True
- A 刀真救回过＝True
- B 刀真救回过（案卷里落了原文回贴）＝True
- 凭空编那条两臂都被打掉＝True
- 两臂剪完都没有假绿（当期尺全过）＝True
- 两臂幸存条目活路全可归因（严格尺／A 子串／B 留痕）＝True
- 开臂确有 A 宽容面（strict_fail 非空比空的正数）＝True
- 开臂 accounting 写数且 Σ 闭合＝True
- 关臂不写 accounting 键＝True
- 泄漏＝0（越界 id／禁品键）＝True
- 金标被引剪后开臂≥关臂＝True

## 6. 假阳性防护（单里点名要的「故意脏转写仍应失败」＋源码变异刀）

- 常驻格 13 颗＝`tests/test_c122_cite_stable.py`（含参数化的「改数字／翻转事实／原文根本没有」三类脏转写仍判失败＋「回贴没落笔即判失败」＋总闸反向腿）
- 刀表：10 只有牙／1 把咬空＝['K11 把键从 pipeline kept 白名单摘掉']

- K1 旗出厂默认翻成开 → 1 failed：['test_a_default_off_both_by_env_and_settings']
- K2 三道阈值放宽 → 1 failed：['test_g_thresholds_are_pinned_literals']
- K3 摘掉数字守恒闸 → 1 failed：['test_e_dirty_transcription_still_fails']
- K4 摘掉「回贴后还要过现行尺」总闸 → 1 failed：['test_k_master_gate_rejects_when_declared_segment_missing']
- K5 让 materialize 写进非原文 → 2 failed：['test_d_flag_on_reanchor_writes_verbatim_from_declared_segment', 'test_j_production_prune_consumes_the_same_failure_list']
- K6 摘掉 B 刀（只留 A） → 2 failed：['test_d_flag_on_reanchor_writes_verbatim_from_declared_segment', 'test_j_production_prune_consumes_the_same_failure_list']
- K7 摘掉 A 刀（只留 B） → 1 failed：['test_c_flag_on_formatting_only_quote_recovers']
- K8 对外入口无视旗（永远走严格尺） → 2 failed：['test_c_flag_on_formatting_only_quote_recovers', 'test_d_flag_on_reanchor_writes_verbatim_from_declared_segment']
- K9 回贴没落笔时改成放行（假绿） → 3 failed：['test_d_flag_on_reanchor_writes_verbatim_from_declared_segment', 'test_i_materialize_failure_fails_closed', 'test_j_production_prune_consumes_the_same_failure_list']
- K10 不写 accounting 账 → 5 failed：['test_c_flag_on_formatting_only_quote_recovers', 'test_d_flag_on_reanchor_writes_verbatim_from_declared_segment', 'test_i_materialize_failure_fails_closed', 'test_j_production_prune_consumes_the_same_failure_list']
- K11 把键从 pipeline kept 白名单摘掉 → 0 failed：[]（**咬空＝该处零守护**）

## 7. 旁证

- q_001（每臂 3 遍）：失败率 关 0.1111 → 开 0.0833；打回后保留证 关 3.0 → 开 3.6667；打回后金标被引 关 3.0 → 开 3.0；泄漏 0；假绿 0／不可归因 0
- q_002（每臂 3 遍）：失败率 关 0.3 → 开 0.0；打回后保留证 关 3.3333 → 开 5.0；打回后金标被引 关 2.0 → 开 2.3333；泄漏 0；假绿 0／不可归因 0

## 8. 判据逐条（门槛先写死后照判）

- 1_fail_rate_down_p_le_0.05＝False
- 2_gold_after_not_down＝False
- 3_leak_zero＝True
- 4_no_false_green＝True
- 5_dirty_transcription_still_fails＝True
- 6_side_legs_no_drop＝True

## 9. 局限（读数能撑到哪一句）

- 一案一题（刘翔 q_003）＋两题旁证；单模型 14B；温度未钉＝逐遍波动里混着采样噪声，n＝5 的置换检验只到「这一题上分得开」，不到「全队列都这样」。
- 桩腿的 A／B 夹具是**人为造的脏转写**，它证明机制通路在场，不证明真模型会那样写；真跑里 A／B 各fire 多少只看 §4 那两行 accounting。
- 件②b 用的是自家产物（历史跑批）面＝尺的确定性效果；真跑的失败率分母是模型当遍产出的条数，两臂分母不同（证条数本身随遍浮动），所以失败率只能按「证条级比率」比，不能按条数比。
- K11（把 `cite_check_stable` 从 pipeline 的 accounting kept 白名单摘掉）咬空＝零守护，与 #95 那一类同洞；本票只登记、不另开守护单。
- 单里的「@7 抽测」我按「另题抽测」执行（刘翔 q_001／q_002）＝若另有所指（某份 7 题清单），这一条待确认。

## 10. 一句话结论

- NO：失败率关 0.7306→开 0.6533（p＝0.43493），打回后金标被引 关 1.2→开 0.6，泄漏 0，假绿 0；开臂核对 27 条里 A 记名 3／B 回贴 0。
- 两个口径并列，不改刀口：①**开工前写死的数值门槛**＝NO（4/6 条腿过；腿 1 差在 p＝0.43493＞0.05、腿 2 差在打回后金标 关 1.2→开 0.6）；②**单里的文字口径**（「只降失败率但打回后金标不升」＝弱 YES／不合）＝弱 YES。两口径对「合不合 main」的答案一致＝**不合**；差别只在对外怎么写这一行，我按①报 NO、并在交账里同时给出②那句原文，不挑对自己好听的那个。
- 池化三题（§4b）另给一票：失败率 关 0.5172→开 0.3704（Fisher p＝0.084839，仍未过 0.05）、可用证 关 28→开 34、金标被引 关 21→开 19＝方向一致但不显著。
- 机制侧结论（站得住的那半）：漏桶成因已量死（fuzzy_close 占失败 0.5668），A 刀在真跑里确实 fire（记名 3 条）且零假绿／零不可归因；B 刀在官方卷上一次没 fire，拒因全是 `ratio_below_gate`／`coverage_below_gate`＝闸在咬，不是刀钝。
- 旗保持出厂默认关；是否并主线等 Boyu／grok 按这份判。

## 11. 仪器清单（本票四腿各跑一次才出这些数）

- `scripts/probe_c122_fail_taxonomy.py`＝件① 成因归因（零模型调用・生产同一把尺）
- `scripts/probe_c122_stable_offline.py`＝件②b 零模型 A/B 腿（关臂 `_check_strict`／开臂 `check_stable`）
- `scripts/probe_c122_two_arm.py`＝件③ 开关配对（`--stub` 走零调用全路径、默认真跑）
- `scripts/probe_c122_official_face_reasons.py`＝件①b 官方卷真输出的打回原因（脱敏：长度＋sha8＋原因码）
- `scripts/make_c122_artifacts.py`＝本文件的生成器（数字全部现抄，不手打）
- `tests/test_c122_cite_stable.py`＝常驻守护格 13 颗
- 脱敏自检＝扫官方卷原文片段是否出现在任何 `artifacts/C122_*` 里（本轮实测 0 命中）

