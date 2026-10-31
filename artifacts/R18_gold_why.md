# R18 — 跨案金标「为何是金标」

## 结论先行

- 六案共 **105** 条严格金标。跨案真正共性不是「官方原文载体」，而是**可核验事实句**：时点钉 36/105（34.3%）、问句主体落段 26/105、full_support 61.9%（其余 partial）。
- 当前 `infer_fine_role` **过拟合刘翔案**：刘翔金标里 official_primary/reprint/party_* 仍多样；其余五案金标被标成 commentary 的占绝大多数（rest top=commentary 79.1%）。肉眼看这些段常是新闻发布／通稿／一手访谈，角色先验在跨案失效。
- 预置主张族 leave/money/post 只盖住约 14/105（13.3%）金标；**77/105（73.3%）完全落在族外**——灾害成因、空难调查、外交声明、教育争议都不进现有一筛 claim 维。
- 摘句形态跨案以 near_full_para 为主（95.2%）：拓尔思选的 para 往往整段就是金句，问题更在「一筛能不能把该段抬进池」，而非段内再切。
- 一筛已覆盖：角色独热、渠道层级、主体匹配、粗主张族、数额／时间槽。缺口优先：①跨域主张族／问句对齐；②通稿／一手来源的跨案角色信号（勿只用就业安置套话）；③时点＋主体＋事件框架的组合键；④近邻段差分（同文相邻为何落选）。

六案严格金标合计 **105** 条（supporting_facts 含 partial，经 evidence_samples 对齐）。
规则打标全量；本地 `veritas-qwen3-14b` 按题归纳（use_llm=True）。**未改加权、未重拟合。**

## 跨案共性

| 信号 | 金标占比 | 读法 |
|---|---:|---|
| 带明确时点钉（月日／时刻） | 34.3% | 跨案最稳的可核验线索 |
| 问句抽出的主体落在段内 | 24.8% | 主体对齐仍有用，但不够 |
| full_support | 61.9% | 其余 38.1% 为 partial |
| 命中预置主张族 leave/money/post | 13.3% | **族外是主流** |
| 规则标成 official_primary | 2.9% | 跨案官方原文标签极稀 |
| 带金额 | 3.8% | 基本是刘翔案特产 |

共性一句话：拓尔思选的是**能直接支撑结论判断的事实承载句**（时点／定性／一手出处／权威复述），不是「渠道档最高的整篇综述」。

## 分类器失真（重要）

现用 `infer_fine_role` 在刘翔上可用，换案后把大量「通稿事实句／声明条款／一手访谈」打成 `commentary`：

| 范围 | Top fine_role |
|---|---|
| 仅刘翔（n=14） | `official_primary` 21.4%, `official_reprint` 14.3%, `party_relay` 14.3%, `opposition_framing` 14.3%, `commentary` 14.3% |
| 其余五案（n=91） | `commentary` 79.1%, `media_relay` 20.9% |

因此下表「细角色／渠道」是**当前流水线眼睛里的金标**，不能直接当成拓尔思标注意图。

### 流水线视角的细角色

| fine_role | n | % |
|---|---:|---:|
| `commentary` | 74 | 70.5 |
| `media_relay` | 21 | 20.0 |
| `official_primary` | 3 | 2.9 |
| `official_reprint` | 2 | 1.9 |
| `party_relay` | 2 | 1.9 |
| `opposition_framing` | 2 | 1.9 |
| `institution_def` | 1 | 1.0 |

### 渠道层级

| channel_tier | n | % |
|---|---:|---:|
| `other` | 57 | 54.3 |
| `market_media` | 24 | 22.9 |
| `central_official` | 17 | 16.2 |
| `foreign_media` | 5 | 4.8 |
| `local_official` | 2 | 1.9 |

### 主张关系 / 摘句 / 支撑类型

| 维 | 分布 |
|---|---|
| claim_relation | `no_catalog_family` 73.3%, `question_terms_weak_hit` 13.3%, `family_money_surface` 3.8%, `family_leave_frame_only` 2.9%, `family_post_frame_only` 2.9%, `family_leave_surface` 1.9% |
| span_vs_quote | `near_full_para` 95.2%, `quote_not_in_para` 2.9%, `excerpt_inside_para` 1.0%, `loose_overlap` 1.0% |
| verdict_label | `full_support` 61.9%, `partial_support` 38.1% |

## 案别差异

| 案 | 金标 | Top 流水线角色 | Top 渠道 |
|---|---:|---|---|
| liuxiang | 14 | official_primary:3, official_reprint:2, party_relay:2 | market_media:6, central_official:4, local_official:2 |
| jilong | 18 | commentary:12, media_relay:6 | other:18 |
| us_cn_ai | 14 | commentary:13, media_relay:1 | other:8, central_official:5, foreign_media:1 |
| ai171 | 24 | commentary:18, media_relay:6 | other:13, central_official:7, market_media:4 |
| kh_th | 16 | commentary:15, media_relay:1 | other:11, market_media:4, central_official:1 |
| wanghong | 19 | commentary:14, media_relay:5 | market_media:10, other:7, foreign_media:2 |

### 分案要点

- **liuxiang**：唯一角色分类器「对味」的案：官方操作句、当事人原话、制度说明三分。主张族 money/leave/post 基本够用。
- **jilong**：金标几乎全是灾害时点／成因／口岸冲击的科学与政务叙述；URL 档全落 other。角色器几乎全判 commentary，但内容是权威事实复述。
- **us_cn_ai**：金标多为联合声明条款（建对话／沟通渠道）；与 leave/money/post 无关。媒体转载同一声明多条近同文。
- **ai171**：金标含航司证实伤亡、调查进展、技术原因分析；转述「据…报道／证实」多，media_relay 略高于他案但仍大量被标 commentary。
- **kh_th**：金标偏双方外交／军情表态与事件定性；对立选项问句下 stance 规则几乎抽不动。
- **wanghong**：金标含 IMU 一手视频访谈英文 discouraged 出处＋后续教育系统解读；市场媒体档更高，主张族完全不对题。

## 对照非金标（抽样）

同题「问句词命中」非金标 + 金标同文档相邻段。流水线角色分布：

| fine_role | n | % |
|---|---:|---:|
| `commentary` | 74 | 82.2 |
| `official_primary` | 5 | 5.6 |
| `media_relay` | 5 | 5.6 |
| `official_reprint` | 2 | 2.2 |
| `opposition_framing` | 2 | 2.2 |
| `institution_def` | 1 | 1.1 |
| `mixed_summary` | 1 | 1.1 |

对照段同样大量 commentary——**角色维几乎分不开金／非金**；差在内容是否承载题面所需的时点／定性／一手出处（见 14B 与人工读段）。

## 14B 归纳（过滤掉整段复读后）

### 金标共性（抽象短句）

- (1) 金标段多次明确提及灾害发生时间为8月26日上午10时52分左右
- (1) 金标段引用权威来源，如西藏自治区人民政府新闻发布会和中科院成都山地所的分析
- (1) 金标段详细描述了灾害的起因、过程和影响，具有较高的可信度
- (1) 跨段共性，短句
- (1) 官方与中科院均认定灾害原因为冰川断裂引发的冰岩崩
- (1) 金标段多次提到中美双方同意建立人工智能事件的沟通渠道
- (1) 金标段明确提到下次对话将于今年11月举行
- (1) 金标段提到建立沟通渠道是为AI风险事件做准备的重要一步
- (1) 提及联合国主渠道作用
- (1) 金标段多次明确提及机上241人遇难，仅1人生还
- (1) 金标段来源包括印度航空公司官方确认和权威媒体报道

### 相对对照段多出的信号

- (1) 金标段引用了《自主择业退役运动员经济补偿办法》
- (1) 金标段提到‘买断’与‘自主择业’的对应关系
- (1) 金标段指出刘翔的处境不同，制度设计的逻辑前提
- (1) 金标段提供了具体时间点（10时52分），而对照非金标段未提及灾害发生的具体时间
- (1) 金标段引用了权威机构的分析结果，而对照非金标段未涉及相关权威信息
- (1) 金标段包含联合国和中方对灾害的官方回应
- (1) 金标段提及灾害的科学分析和成因
- (1) 金标段包含多方对灾害性质的描述（泥石流、洪灾、山崩）
- (1) 金标段提到冰川断裂引发的碎屑流链式灾害
- (1) 金标段明确指出灾害与冰湖溃决无关
- (1) 金标段引用了中科院和自然资源部的权威分析
- (1) 金标段提到中美同意建立人工智能事件的沟通渠道
- (1) 金标段提到需要建立事件报告机制
- (1) 金标段提到AI安全机构参与相关讨论
- (1) 金标段明确指出机上241人遇难，仅1人生还

完整按题 JSON 见 `R18_gold_why.json` → `questions[].llm`。

## 一筛覆盖 vs 缺口

### 已覆盖

- fine_role / role_* 独热（但跨案标签分布失真）
- channel_tier 独热（大量 other＝URL 规则不够）
- subject_match / subject_x_channel
- claim_full / claim_keyword（仅 leave/money/post）
- amount_status / time_anchor（问句触发＋摘要槽；规则面 has_time 更稳）
- 二筛挡路：标题党／小节蹭分／偏题转载／近同文／拼段

### 缺口（只分析，不改加权）

- 角色先验依赖就业安置／微博套话 → 五案金标大面积误标 commentary
- 主张族目录过窄 → 73% 金标 claim_relation=no_catalog_family
- 渠道层级对政府站点／无 URL 案（吉隆）失效 → other 占 54%
- 缺少「事件框架键」：灾害时点、空难调查结论、外交条款编号、一手访谈出处
- 缺少近邻差分：同声明多切片、同文相邻段为何落选未建模
- 对立选项显式对齐（lean_option_*）几乎未触发（1.9%）

## 方法

- 严格金标：`conclusions.supporting_facts` → `evidence_samples.para_id`
- 规则：`infer_fine_role` / `channel_tier` / `case_lexicon` / 时点／金额／摘句比／对立选项粗对齐
- 对照：问句词命中非金标抽样 + 同文档相邻段
- 14B：每题一条 JSON；默认本地 `veritas-qwen3-14b`

## 路径
- `artifacts/R18_gold_why.json`
- `artifacts/R18_gold_why.md`

## 附录：每题金标表

### liuxiang · 刘翔编制“二选一”事件

**q_001** 这笔49.4万元应认定为买断费还是自主择业经济补偿金，以哪方口径为准？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_002#p3` | full_support | official_primary | central_official | family_money_surface | Y |  | neutral_or_unclear |
| `doc_024#p1` | partial_support | official_reprint | central_official | family_money_surface | Y |  | affirm_or_confirm |
| `doc_025#p6` | full_support | institution_def | local_official | family_money_surface |  |  | neutral_or_unclear |
| `doc_035#p7` | full_support | official_reprint | local_official | family_money_surface | Y |  | neutral_or_unclear |

**q_002** 拖了11年才安置，是刘翔不愿走还是体育局未放行，哪一方说法站得住？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_002#p3` | partial_support | official_primary | central_official | family_leave_frame_only | Y |  | neutral_or_unclear |
| `doc_009#p5` | full_support | party_relay | market_media | family_leave_surface |  |  | neutral_or_unclear |
| `doc_028#p1` | full_support | opposition_framing | market_media | family_leave_surface | Y |  | neutral_or_unclear |
| `doc_029#p7` | partial_support | commentary | market_media | family_leave_frame_only | Y | Y | neutral_or_unclear |
| `doc_051#p3` | partial_support | media_relay | market_media | family_leave_frame_only | Y |  | neutral_or_unclear |

**q_003** 刘翔退役至今是否真有编制与岗位，官方称其在编不在岗能否以人事档案证实？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_002#p3` | full_support | official_primary | central_official | family_post_frame_only | Y |  | neutral_or_unclear |
| `doc_006#p3` | full_support | opposition_framing | market_media | family_post_surface |  |  | neutral_or_unclear |
| `doc_012#p5` | partial_support | media_relay | market_media | family_post_surface |  |  | neutral_or_unclear |
| `doc_033#p5` | partial_support | party_relay | foreign_media | family_post_frame_only |  |  | neutral_or_unclear |
| `doc_033#p6` | partial_support | commentary | foreign_media | family_post_frame_only |  |  | neutral_or_unclear |

### jilong · 2026·8·26 吉隆口岸泥石流灾害

**q_001** 吉隆口岸泥石流灾害的起始时刻，应以官方通稿的8月26日10时30分许为准，还是以监控记录的10时52分至59分为准？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_001#p2` | full_support | commentary | other | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_001#p21` | partial_support | commentary | other | no_catalog_family | Y |  | affirm_or_confirm |
| `doc_001#p237` | full_support | commentary | other | no_catalog_family | Y |  | affirm_or_confirm |

**q_002** 中方称泥石流、联合国与尼泊尔称洪灾或山崩，评估伤亡与受灾统计时应采用哪一口径？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_001#p139` | partial_support | commentary | other | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_001#p2` | partial_support | commentary | other | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_001#p235` | partial_support | commentary | other | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_001#p291` | partial_support | media_relay | other | no_catalog_family | Y |  | affirm_or_confirm |
| `doc_001#p306` | full_support | media_relay | other | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_001#p422` | full_support | commentary | other | no_catalog_family |  | Y | affirm_or_confirm |
| `doc_001#p424` | partial_support | media_relay | other | no_catalog_family | Y |  | affirm_or_confirm |
| `doc_001#p430` | full_support | media_relay | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_001#p45` | partial_support | commentary | other | no_catalog_family | Y |  | neutral_or_unclear |

**q_003** 官方与中科院认定的海拔约5200米冰川断裂冰岩崩，与媒体所称上游冰湖溃决，哪一说法成立？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_001#p2` | full_support | commentary | other | question_terms_weak_hit | Y |  | neutral_or_unclear |
| `doc_001#p233` | full_support | media_relay | other | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_001#p237` | full_support | commentary | other | question_terms_weak_hit | Y |  | affirm_or_confirm |
| `doc_001#p419` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_001#p422` | full_support | commentary | other | no_catalog_family |  | Y | affirm_or_confirm |
| `doc_001#p85` | partial_support | media_relay | other | no_catalog_family | Y |  | neutral_or_unclear |

### us_cn_ai · 中美AI事故预警提议（2026.9）

**q_001** AI事故通报热线到底能否在2026年11月的中美对话后就绪启用，还是如WIRED所称短期不会就绪？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_004#p4` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_007#p10` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_009#p12` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_016#p5` | full_support | commentary | central_official | no_catalog_family |  |  | neutral_or_unclear |
| `doc_023#p4` | full_support | commentary | central_official | no_catalog_family |  |  | affirm_or_confirm |
| `doc_047#p4` | partial_support | commentary | foreign_media | no_catalog_family |  |  | affirm_or_confirm |

**q_002** 中美AI对话机制应定性为危机管理安排，还是联合国主渠道下的全球AI治理安排？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_005#p3` | full_support | commentary | other | question_terms_weak_hit |  |  | neutral_or_unclear |
| `doc_009#p12` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_011#p3` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_018#p12` | full_support | commentary | other | question_terms_weak_hit | Y |  | affirm_or_confirm |

**q_003** AI失控责任该由OpenAI管理层等企业承担，还是如Anthropic、奥尔特曼所主张由政府介入承担？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_017#p10` | partial_support | commentary | central_official | no_catalog_family |  |  | neutral_or_unclear |
| `doc_017#p12` | full_support | media_relay | central_official | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_017#p9` | partial_support | commentary | central_official | no_catalog_family |  |  | neutral_or_unclear |
| `doc_058#p2` | full_support | commentary | other | question_terms_weak_hit |  |  | neutral_or_unclear |

### ai171 · 印度航空 AI171 空难（2025.6–2026.5）

**q_001** 截至2026年5月，AI171空难死亡人数应以机上241人、全部242人还是含地面共274人为准？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_001#p3` | full_support | media_relay | other | question_terms_weak_hit | Y |  | affirm_or_confirm |
| `doc_002#p8` | full_support | commentary | other | no_catalog_family | Y |  | affirm_or_confirm |
| `doc_005#p3` | full_support | commentary | market_media | no_catalog_family | Y |  | affirm_or_confirm |
| `doc_007#p3` | partial_support | commentary | other | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_009#p14` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_012#p8` | partial_support | media_relay | central_official | no_catalog_family | Y |  | affirm_or_confirm |
| `doc_015#p5` | full_support | commentary | central_official | no_catalog_family |  |  | neutral_or_unclear |

**q_002** 官方调查是否已认定AI171坠机系机组关闭燃油开关所致，而非波音燃油开关设计缺陷？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_006#p3` | full_support | commentary | other | no_catalog_family | Y |  | affirm_or_confirm |
| `doc_007#p3` | full_support | commentary | other | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_010#p9` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_011#p2` | full_support | media_relay | other | no_catalog_family | Y |  | refute_or_clarify |
| `doc_012#p8` | partial_support | media_relay | central_official | no_catalog_family | Y |  | affirm_or_confirm |
| `doc_013#p3` | partial_support | commentary | central_official | no_catalog_family |  |  | affirm_or_confirm |
| `doc_013#p8` | full_support | commentary | central_official | no_catalog_family |  |  | neutral_or_unclear |
| `doc_015#p1` | full_support | commentary | central_official | no_catalog_family |  |  | neutral_or_unclear |
| `doc_015#p6` | full_support | commentary | central_official | no_catalog_family |  |  | affirm_or_confirm |
| `doc_016#p19` | partial_support | media_relay | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_020#p30` | full_support | commentary | market_media | no_catalog_family |  |  | neutral_or_unclear |

**q_003** 11A座位靠近紧急出口是否真的提高了AI171幸存者的生还概率，还是纯属侥幸？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_004#p3` | full_support | commentary | other | no_catalog_family |  |  | lean_option_b |
| `doc_004#p6` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_004#p8` | full_support | commentary | other | no_catalog_family |  |  | lean_option_b |
| `doc_004#p9` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_005#p4` | full_support | commentary | market_media | no_catalog_family |  |  | neutral_or_unclear |
| `doc_005#p7` | partial_support | media_relay | market_media | no_catalog_family |  |  | neutral_or_unclear |

### kh_th · 柬泰边境争端（2025.12–2026.9）

**q_001** 泰方称两次出动F-16打击柬军事目标，柬方称境内军事设施未遭空袭，哪一方有可核查证据支持？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_008#p11` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_009#p10` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_009#p11` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_009#p12` | partial_support | commentary | other | no_catalog_family |  |  | affirm_or_confirm |
| `doc_027#p2` | partial_support | commentary | other | no_catalog_family |  |  | affirm_or_confirm |

**q_002** 泰方称柬方率先开火、柬方称泰军率先开火，现有记录能否判定2025年12月边境冲突谁先动武？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_006#p4` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_009#p10` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_009#p12` | partial_support | commentary | other | no_catalog_family |  |  | affirm_or_confirm |
| `doc_014#p3` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_017#p4` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_021#p2` | full_support | commentary | central_official | question_terms_weak_hit |  | Y | neutral_or_unclear |

**q_003** 西方媒体称中国向柬埔寨提供大量武器援助偏帮一方，这一说法是否有可证实的证据支撑？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_007#p7` | full_support | commentary | other | no_catalog_family |  |  | refute_or_clarify |
| `doc_023#p2` | full_support | commentary | market_media | question_terms_weak_hit |  |  | neutral_or_unclear |
| `doc_023#p4` | full_support | media_relay | market_media | no_catalog_family |  |  | neutral_or_unclear |
| `doc_024#p1` | full_support | commentary | market_media | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_024#p2` | full_support | commentary | market_media | no_catalog_family |  |  | neutral_or_unclear |

### wanghong · 王虹“北大discouraged”事件

**q_001** 王虹说的 discouraged 原意指什么？是北大的教学环境/特定教师让她气馁？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_001#p1` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_004#p4` | partial_support | commentary | market_media | no_catalog_family |  |  | neutral_or_unclear |
| `doc_004#p5` | full_support | commentary | market_media | no_catalog_family |  |  | neutral_or_unclear |
| `doc_008#p12` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_010#p4` | full_support | commentary | foreign_media | question_terms_weak_hit |  |  | neutral_or_unclear |

**q_002** 流传的「北大无人肯写推荐信」「因绩点不足未保研」「缺席毕业合照」等是否属实？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_010#p7` | full_support | commentary | foreign_media | question_terms_weak_hit |  |  | neutral_or_unclear |
| `doc_011#p1` | full_support | media_relay | market_media | question_terms_weak_hit |  |  | refute_or_clarify |
| `doc_011#p2` | full_support | media_relay | market_media | question_terms_weak_hit |  |  | refute_or_clarify |
| `doc_011#p3` | full_support | commentary | market_media | question_terms_weak_hit |  |  | neutral_or_unclear |
| `doc_011#p6` | full_support | commentary | market_media | question_terms_weak_hit | Y |  | neutral_or_unclear |

**q_003** 王虹本人对北大的评价是正面还是负面？

| para | verdict | fine_role | tier | claim | time | amt | stance |
|---|---|---|---|---|---|---|---|
| `doc_003#p3` | full_support | commentary | market_media | no_catalog_family |  |  | neutral_or_unclear |
| `doc_003#p4` | full_support | media_relay | market_media | no_catalog_family |  |  | neutral_or_unclear |
| `doc_003#p5` | full_support | media_relay | market_media | no_catalog_family |  |  | neutral_or_unclear |
| `doc_003#p7` | full_support | commentary | market_media | no_catalog_family |  |  | neutral_or_unclear |
| `doc_007#p1` | full_support | commentary | other | no_catalog_family | Y |  | neutral_or_unclear |
| `doc_007#p2` | full_support | media_relay | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_007#p3` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_012#p7` | partial_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
| `doc_023#p2` | full_support | commentary | other | no_catalog_family |  |  | neutral_or_unclear |
