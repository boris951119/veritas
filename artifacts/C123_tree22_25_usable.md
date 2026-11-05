# C-123 — 树22 冲突溯源／树25 置信披露：开旗能不能真用上（旗默认仍关）

> 判定＝**YES（件② 已开工・两条窄修都在产物面闭合・旗仍出厂默认关）**。
> 枝＝`qoder/c123-tree22-25-usable`（自 main tip 开，不合 main、不 push）；两把旗 `VERITAS_CONFLICT_TRACE`／`VERITAS_CONF_CALIB` 出厂默认仍关。

## 0. 不带编号的说明（这段给不看代码的人）

系统里有两把实验开关：一把把「资料里数字打架」的每一条按同窗／跨日／时点不明三类记下来并写清怎么处置，另一把把置信度按五道闸降档并留下为什么降。这次先只问一个问题：开关打开之后，这些东西到底有没有出现在交出去的文件里。

实测＝没有。四臂在官方卷四案上量到留痕 35 条、覆盖率 1.0，但这些账在写产物前被管线里一张「保留白名单」整个吃掉，所以报告面和交卷回放面（conflict_trace.json）四臂全是空的——不是算不出，是算完被扔了。

修法是两处很小的改动：白名单登记这两个键（管线里两处都要登记）；交卷面在「一条冲突都没检出」时也写一份空态文件，并说明这是未检出、不等于资料无冲突。判定、打分、选段、装箱一行没动；开关默认仍关＝默认产物与改前逐字相同。

## 1. 件① 量到的缺口（tip 上、未修时）

- G1 留痕账被 kept 白名单剥掉：A 腿开臂算出 35 条（覆盖 1.0），但 E 腿四臂 `conflict_trace_json_written` 逐臂 False（「四臂全 False」复算＝True）、案卷键位逐臂 ['["NO", "NO"]']＝开旗＝对外零出口
- G2 空态静默：`export_official` 里 `if merged:` ⇒ 零对撞时连文件都没有，「没检出」和「没这块」在产物面上长得一样
- G3 第五道降档闸（冲突未决）离线快照测不到：B 腿只算得出台账对撞，案卷里没有结论级冲突对 ⇒ 这一道只能靠真跑面量

## 2. 件② 是否开工／diff 面（现抄 git）

- 开工＝是（单里「旗开仍不可用」这一条被实测命中，属允许的窄修范围）
- 改动文件＝['app/export/official.py', 'app/pipeline.py']
- `git diff --stat app/`＝`app/export/official.py | 36 +++++++++++++++++++++++-------------
 app/pipeline.py        |  9 ++++++++-
 2 files changed, 31 insertions(+), 14 deletions(-)`
- 只动出口面：`app/pipeline.py` 的 accounting kept 白名单两处登记两键；`app/export/official.py` 的空态写文件＋原因句。判定／打分／选段／装箱零改动；未合 C-113／C-121／C-122 任何一刀。

## 3. 零调用腿 E：交卷面闭合对照（同一夹具・tip vs 窄修后）

tip（未修）：
- arm0_双旗关＝生产默认｜五份齐=True｜trace.json 写出=False｜案卷留痕键=['NO', 'NO']｜回放条数=None｜confidence 字段={'band': 4, 'band_rel': 4}｜异常=None
- arm1_只开冲突留痕｜五份齐=True｜trace.json 写出=False｜案卷留痕键=['NO', 'NO']｜回放条数=None｜confidence 字段={'band': 4, 'band_rel': 4}｜异常=None
- arm2_只开置信校准｜五份齐=True｜trace.json 写出=False｜案卷留痕键=['NO', 'NO']｜回放条数=None｜confidence 字段={'band': 4, 'predicted_band': 4, 'demote_reasons': 4, 'band_rel': 4}｜异常=None
- arm3_双旗开｜五份齐=True｜trace.json 写出=False｜案卷留痕键=['NO', 'NO']｜回放条数=None｜confidence 字段={'band': 4, 'predicted_band': 4, 'demote_reasons': 4, 'band_rel': 4}｜异常=None

窄修后：
- arm0_双旗关＝生产默认｜五份齐=True｜trace.json 写出=False｜案卷留痕键=['NO', 'NO']｜回放条数=None｜confidence 字段={'band': 4, 'band_rel': 4}｜异常=None
- arm1_只开冲突留痕｜五份齐=True｜trace.json 写出=True｜案卷留痕键=['HAS', 'HAS']｜回放条数=8｜confidence 字段={'band': 4, 'band_rel': 4}｜异常=None
- arm2_只开置信校准｜五份齐=True｜trace.json 写出=False｜案卷留痕键=['NO', 'NO']｜回放条数=None｜confidence 字段={'band': 4, 'predicted_band': 4, 'demote_reasons': 4, 'band_rel': 4}｜异常=None
- arm3_双旗开｜五份齐=True｜trace.json 写出=True｜案卷留痕键=['HAS', 'HAS']｜回放条数=8｜confidence 字段={'band': 4, 'predicted_band': 4, 'demote_reasons': 4, 'band_rel': 4}｜异常=None

- 官方五份在两版四臂都齐全＝`official_five_complete` 全 True（新增的 conflict_trace.json 是第 6 份额外回放件，不占五份）

## 4. 真跑腿（刘翔 q_003・本机 Ollama 14B・零现金）

- 题＝刘翔编制“二选一”事件／q_003｜温度未钉（`llm_temperature=None`）＝逐遍波动里混采样噪声；每臂 1 遍＝只用于「出口在不在场」，不用于比大小
- tip（未修）｜arm0_双旗关｜墙钟 336.4s｜模型调用 9｜结论(majority) 5｜冲突对 0｜留痕条数 3｜覆盖 1.0｜unclassified 0｜三箱 {'unknown_time': 3, 'same_window': 0, 'cross_day': 0, 'unclassified': 0}｜键活到产物 False｜trace.json False｜band 字段 {'band': 5, 'band_rel': 5}｜降档码 {'min_evidence': 3, 'anchor_incomplete': 0, 'chain_incomplete': 0, 'panel_disagreement': 5, 'conflict_undecided': 0}｜未决闸命中 0｜高档行 ['中', '中', '中', '中', '中']｜泄漏 0
- tip（未修）｜arm1_只开冲突留痕｜墙钟 450.4s｜模型调用 24｜结论(majority) 2｜冲突对 5｜留痕条数 8｜覆盖 0.375｜unclassified 5｜三箱 {'unknown_time': 3, 'same_window': 0, 'cross_day': 0, 'unclassified': 5}｜键活到产物 False｜trace.json False｜band 字段 {'band': 2, 'band_rel': 2}｜降档码 {'min_evidence': 1, 'anchor_incomplete': 0, 'chain_incomplete': 0, 'panel_disagreement': 1, 'conflict_undecided': 0}｜未决闸命中 0｜高档行 ['中', '中']｜泄漏 0
- tip（未修）｜arm2_只开置信校准｜墙钟 405.0s｜模型调用 18｜结论(majority) 3｜冲突对 3｜留痕条数 6｜覆盖 0.5｜unclassified 3｜三箱 {'unknown_time': 3, 'same_window': 0, 'cross_day': 0, 'unclassified': 3}｜键活到产物 False｜trace.json False｜band 字段 {'band': 3, 'predicted_band': 3, 'band_rel': 3}｜降档码 {'min_evidence': 2, 'anchor_incomplete': 0, 'chain_incomplete': 2, 'panel_disagreement': 2, 'conflict_undecided': 2}｜未决闸命中 2｜高档行 ['中', '中', '中']｜泄漏 0
- tip（未修）｜arm3_双旗开｜墙钟 374.8s｜模型调用 12｜结论(majority) 4｜冲突对 1｜留痕条数 4｜覆盖 0.75｜unclassified 1｜三箱 {'unknown_time': 3, 'same_window': 0, 'cross_day': 0, 'unclassified': 1}｜键活到产物 False｜trace.json False｜band 字段 {'band': 4, 'predicted_band': 4, 'band_rel': 4}｜降档码 {'min_evidence': 1, 'anchor_incomplete': 0, 'chain_incomplete': 2, 'panel_disagreement': 4, 'conflict_undecided': 0}｜未决闸命中 0｜高档行 ['中', '中', '中', '中']｜泄漏 0
- 窄修后｜arm0_双旗关｜墙钟 350.2s｜模型调用 9｜结论(majority) 4｜冲突对 0｜留痕条数 3｜覆盖 1.0｜unclassified 0｜三箱 {'cross_day': 0, 'same_window': 0, 'unknown_time': 3, 'unclassified': 0}｜键活到产物 False｜trace.json False｜band 字段 {'band': 4, 'band_rel': 4}｜降档码 {'min_evidence': 3, 'anchor_incomplete': 0, 'chain_incomplete': 1, 'panel_disagreement': 3, 'conflict_undecided': 0}｜未决闸命中 0｜高档行 ['中', '中', '中', '中']｜泄漏 0
- 窄修后｜arm3_双旗开｜墙钟 286.6s｜模型调用 12｜结论(majority) 2｜冲突对 1｜留痕条数 4｜覆盖 0.75｜unclassified 1｜三箱 {'cross_day': 0, 'same_window': 0, 'unknown_time': 3, 'unclassified': 1}｜键活到产物 True｜trace.json True｜band 字段 {'band': 2, 'predicted_band': 2, 'band_rel': 2, 'demote_reasons': 1}｜降档码 {'min_evidence': 1, 'anchor_incomplete': 0, 'chain_incomplete': 0, 'panel_disagreement': 2, 'conflict_undecided': 0}｜未决闸命中 0｜高档行 ['中', '高']｜泄漏 0

## 5. 冲突面读数（A 腿＝官方卷四案台账对撞・零 LLM）

- 刘翔编制“二选一”事件｜对撞 3 条｜跨源 2｜时点档 {'unknown_time': 3}
- 王虹“北大discouraged”事件｜对撞 5 条｜跨源 5｜时点档 {'unknown_time': 5}
- 柬泰边境争端（2025.12–2026.9）｜对撞 15 条｜跨源 15｜时点档 {'unknown_time': 15}
- 印度航空 AI171 空难（2025.6–2026.5）｜对撞 12 条｜跨源 10｜时点档 {'cross_day': 9, 'same_window': 3}
- 池化（关臂）＝条数 0／覆盖 None｜池化（开臂・tip）＝条数 35／覆盖 1.0／三箱 {'same_window': 3, 'cross_day': 9, 'unknown_time': 23, 'unclassified': 0}
- 池化（开臂・窄修后）＝条数 35／覆盖 1.0／三箱 {'unknown_time': 23, 'cross_day': 9, 'same_window': 3, 'unclassified': 0}（尺没动＝与 tip 同数）
- 空态（B 腿・单源零对撞案卷）＝开臂 wrote_key True／summary True／覆盖 0.0／诚实披露 True｜关臂 wrote_key False（不写键＝旧行为）

## 6. 置信面读数（C 腿＝C-116 同尺・离线快照）

- 尺＝C-116 同尺＝calibration/face_v2_row_snapshot.jsonl（自标，非金标提示）｜行数 226
- 关臂：高档精确度 {'n_high': 29, 'n_hit': 6, 'precision': 0.20689655172413793, 'accuracy': 0.5172413793103449, 'strict': True}｜ECE 0.056505｜降档 0 条
- 开臂：高档精确度 {'n_high': 11, 'n_hit': 3, 'precision': 0.2727272727272727, 'accuracy': 0.6363636363636364, 'strict': True}｜ECE 0.054964｜降档 18 条｜原因分布 {'panel_disagreement': 13, 'chain_incomplete': 4, 'min_evidence': 2}
- 未能量（照实写）＝五道降档闸里 `conflict_undecided` 这一道在离线快照面永远测不到——它要案卷里有未决冲突对（`dossier.conflicts`），快照只有 parts＝没有冲突。这一道的真读数只看 E 腿（真走 pipeline 的案卷）。
- 真跑面上第五道闸有出数：见 §4 `demote_codes_on_real` 与`n_undecided_gate_hits`（tip arm2 命中 2／arm3 命中 0＝逐臂不同＝采样噪声，只证「这一道能触发」，不证幅度）

## 7. 旁证（D 腿・零 LLM 产物面・四臂）

- 关臂：@7 12｜刘翔 L2 13｜holdout L2 29｜泄漏 0
- 开臂（双旗）：@7 12｜刘翔 L2 13｜holdout L2 29｜泄漏 0
- 四臂逐字相同＝两把旗不碰装箱／判定／选段（波动只记不改尺）

## 8. 常驻守护格与源码变异刀

- 守护格＝`tests/test_c123_trace_survives.py` 收集 12 tests collected in 0.03s
- 整套现跑：施工树（窄修后）`7 failed, 1221 passed, 1 skipped in 28.59s`｜主仓（tip・无本票改动）`7 failed, 1209 passed, 1 skipped in 28.98s`＝同一批既有红名、零新增红；差出的条数＝本票新格
- 刀表＝11 把、11 把有牙；咬空＝（无）
- K1 两处 kept 白名单全摘掉这两键（＝回退件② 第一条窄修） → 8 failed, 4 passed in 0.38s｜红＝test_b_two_keys_survive_to_report_json|test_d_only_trace_key_survives|test_e_only_calib_key_survives|test_f_trace_summary_counts_match_records|test_g_three_boxes_all_populated_with_existing_caliber|test_h_export_face_writes_replay_file|test_i_both_whitelists_carry_both_keys|test_k_empty_state_is_honestly_disclosed
- K2 只摘早退路径那一处白名单（两处清单不一致） → 1 failed, 11 passed in 0.16s｜红＝test_i_both_whitelists_carry_both_keys
- K3 出厂默认把 CONFLICT_TRACE 翻成开 → 3 failed, 9 passed in 0.37s｜红＝test_a_factory_defaults_both_flags_off|test_c_flag_off_writes_neither_key|test_e_only_calib_key_survives
- K4 出厂默认把 CONF_CALIB 翻成开 → 3 failed, 9 passed in 0.16s｜红＝test_a_factory_defaults_both_flags_off|test_c_flag_off_writes_neither_key|test_d_only_trace_key_survives
- K5 留痕无视旗（关旗也写 accounting） → 1 failed, 11 passed in 0.16s｜红＝test_j_flag_off_returns_none_at_unit_level
- K6 置信校准无视旗（关旗也写 accounting） → 1 failed, 11 passed in 0.16s｜红＝test_j_flag_off_returns_none_at_unit_level
- K7 时点不明改判「保留」＝无日期＝非冲突回退 → 1 failed, 11 passed in 0.16s｜红＝test_g_three_boxes_all_populated_with_existing_caliber
- K8 交卷面回退成「有条才写」＝空态重新静默 → 1 failed, 11 passed in 0.16s｜红＝test_k_empty_state_is_honestly_disclosed
- K9 结论冲突对挂不上三档时改判 same_window（第四类当主路径） → 1 failed, 11 passed in 0.16s｜红＝test_l_pair_without_ledger_anchor_stays_unclassified
- K10 空态原因句里的题数计数写成 0（披露数字造假） → 1 failed, 11 passed in 0.16s｜红＝test_k_empty_state_is_honestly_disclosed
- K11 空时点直接归「时点不明」＝绕过三档枚举 → 1 failed, 11 passed in 0.16s｜红＝test_l_pair_without_ledger_anchor_stays_unclassified

## 9. 判据逐条（按单里过线口径）

- 件①缺口闭合＝True｜G1 闭（E 腿开臂 trace.json 写出／键 HAS；真跑 arm3 同）；G2 闭（空态写文件＋原因句・新格 k 钉）；G3 半闭（真跑面出数、离线快照仍测不到）
- 开臂相对关臂冲突覆盖／置信披露达标＝True｜覆盖关 None → 开 1.0；披露：predicted_band／demote_reasons 进 confidence.json、conflict_trace.json 进交卷目录
- 泄漏＝0＝True｜逐臂 0＋真跑各臂 0
- @7 不显著掉＝True｜12 → 12（相同）
- holdout 不显著掉＝True｜29 → 29（相同）
- 旗默认仍关（未经 Boyu 不改默认开）＝True｜出厂默认现读＝{'dataclass': {'conflict_trace': False, 'conf_calib': False}, 'from_env': {'conflict_trace': False, 'conf_calib': False}}；格 a 钉 `Settings().conflict_trace is False` 且 `conf_calib is False`；关臂产物面与 tip 行为一致（格 c／§3 arm0 行）
- 不并树17 三刀／不动树15／软化引文闸／pack 系数／金标进提示＝True｜diff 面只有 §2 两个文件；禁品键由 C-115 既有 `audit_forbidden_keys` 守着
- 未过线的一条＝无（本票不提议改默认开：@7／holdout 的相等只量了产物面四臂，真跑配对样本量不够支撑「默认开」这一决定，须 Boyu 另拍）

## 10. 局限（读数能撑到哪一句）

- 真跑＝一案一题（刘翔 q_003）× 每臂 1 遍、温度未钉：只够证明「出口在场／不在场」，不够比大小；§4 里各臂的条数差＝模型逐遍波动，不是旗的效果。
- 结论级冲突对的三档归类在真跑面上覆盖率低（arm1 覆盖 0.375）＝留痕里的 `unclassified` 主要来自「冲突对挂不上任何台账对撞段」，这是归类规则本身的射程，不是本票新引入的洞。
- C 腿＝自家历史快照（226 行、自标）＝尺的确定性效果，不是官方卷命中率。
- D 腿四臂相同只证明「旗不影响装箱／判定面」，不证明「开旗能涨分」。

## 11. 产物卫生（现扫・不是声明）

- 尺＝官方卷四案段落 3194 段抽出的 25 字窗 52122 个（比对时两侧都去空白）
- 票面文档（`artifacts/C123_*.md/.json`・10 份）＝命中 **0** 处｜明细 （无）｜二扫＝含本文件（终判看这一行）
- 树内桩件产物（`artifacts/c123/**`・50 份・目录在场＝True・不随票入库）＝命中 35620 处｜明细 {'c123/stub_export/arm0/evidence.json': 7, 'c123/stub_export/arm0/q_001/report.json': 4440, 'c123/stub_export/arm0/q_001/report.md': 9, 'c123/stub_export/arm0/q_002/report.json': 4440, 'c123/stub_export/arm0/q_002/report.md': 9, 'c123/stub_export/arm1/evidence.json': 7, 'c123/stub_export/arm1/q_001/report.json': 4440, 'c123/stub_export/arm1/q_001/report.md': 9, 'c123/stub_export/arm1/q_002/report.json': 4440, 'c123/stub_export/arm1/q_002/report.md': 9, 'c123/stub_export/arm2/evidence.json': 7, 'c123/stub_export/arm2/q_001/report.json': 4440, 'c123/stub_export/arm2/q_001/report.md': 9, 'c123/stub_export/arm2/q_002/report.json': 4440, 'c123/stub_export/arm2/q_002/report.md': 9, 'c123/stub_export/arm3/evidence.json': 7, 'c123/stub_export/arm3/q_001/report.json': 4440, 'c123/stub_export/arm3/q_001/report.md': 9, 'c123/stub_export/arm3/q_002/report.json': 4440, 'c123/stub_export/arm3/q_002/report.md': 9}
- 落盘面只有计数／长度／sha8／原因码／文件名＝票面文档里没有可逐字定位的官方原文。
- 桩件产物目录（`artifacts/c123/stub_export/**`）＝管线自己写的案卷、内含逐字引文属正常；本票只交 §11 第一行的票面文档，该目录**不复制进主仓**（C-121 那次的教训就在这）。

## 12. 仪器清单

- `scripts/probe_c123_four_arm.py`＝件① 四臂（A 台账／B 空态／C 置信尺／D 旁证／E 交卷面全路径零调用）
- `scripts/probe_c123_real.py`＝真跑腿（刘翔 q_003・本机 127.0.0.1 钉死・假密钥）
- `scripts/make_c123_baseline_artifact.py`＝件① 现状两件（含架构图红标逐条勾）
- `scripts/make_c123_usable_artifact.py`＝本文件生成器（数字全部现抄）
- `/tmp/c123/knives_c123.py`＝源码变异刀表（副本树下刀・跑完复位；本票不把它入库＝避开 C-37 「scripts/ 零引用」登记闸，读数已落 `artifacts/C123_knife_table.json`）
- `tests/test_c123_trace_survives.py`＝常驻守护格（收集 12 tests collected in 0.03s）

