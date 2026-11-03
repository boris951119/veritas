# C-129 两案开旗烟测（树17红标）— 只量交账

- 日期：2026-11-03；tip＝ae77b77（祖先含 c2306e7＋5a2d736，当场核过）；零 LLM、暖缓存（.kg_lab_vault／.kgcache 六案齐）。
- 开旗方式：仅腿 D 运行时 env 临时 VERITAS_TEST_TREE_LINE=1＋pipeline 同款调用（ensure_test_tree_submit 零实参）；测完 env 摘除；磁盘出厂默认一行未动、零 commit。
- 案选择：liuxiang（必跑，regression 臂 prefer_gold 固定 k=7）＋wanghong（holdout，density_cut 臂）。选 wanghong 理由＝六案门控 EXPECT 本就把它归 holdout 且暖缓存读数最稳（86%），与门控同臂同尺可比。
- 方法：复用入库门控探针 scripts/probe_c125_six_case_gate.py 的腿 A／腿 C 原函数；腿 B′＝门控腿 B 同式自建循环、多捕获树17计划层读数；腿 D＝热路径披露读法。跑批副本 /tmp/c129/smoke_c129.py，原始逐题读数 /tmp/c129/C129_smoke_raw.json。

## 1. 树17 cite／list 可读红标（零 LLM 面，本单新量）

- liuxiang（3 题合计）：计划层名单（close_read，k≤7）21 条、其中金标 12＝准度 0.5714（逐题均 4/7）；金标→细读 1.0（3/3 题）；冲突成对违规 pair_violation＝False（3/3）；名单标签＝采信11／存疑10／对立0。
- wanghong（3 题合计）：名单 7 条、金标 6＝准度 0.8571（逐题 1/1、2/3、3/3）；金标→细读 1.0（3/3）；pair_violation＝False（3/3）。
- q_003（刘翔）行：名单 7 条含金标 4、金标→细读 1.0、pair_violation=False——计划层零新红。

## 2. delta 对照（逐条注来源）

- vs C-128 合后门控复跑（artifacts/c125/C125_six_case_gate.md，tip 5a2d736、同暖缓存）：liuxiang 57%／@7=12／金标→细读 1.0／泄漏 0，wanghong 86%／@7=6／1.0／0＝**逐位一致，持平**。本单腿 A 复量：liuxiang 微密度 0.5714、cut_hits @4=9／@5=11／@7=12；wanghong 微密度 0.8571、@7=6（q_002 0.6667≥期望 0.6667）。腿 C 生产链零金标微密度：liuxiang 0.4444、wanghong 0.8571＝门控行「生产链现场微密度」44%／86% 逐位同。
- vs C-120／C-121 真跑红标（q_003 金标被引 2.875→1.50，C-113 枝 1e14cfc 8+8 遍；C-121 枝三臂 5+5+5）：**不可比**——本单零 LLM，且那是实验枝（均未合 main），不是 main 线读数。真跑层 cite 红标要等树17刀前后的配对真跑才可量。
- 方向参考（口径不同，只列不判）：C-121 件①（四案 12 题）未滤 must 名单准度 0.2333、close_read 来源候选准度 0.7059；main 线名单本就是 close_read k≤7，本单实测刘翔 0.5714／王虹 0.8571。

## 3. 其余必量

- @7：liuxiang=12（期望 12）；wanghong holdout 微密度 86%（≥2/3 线之上）。
- gold→细读：两案 6/6 题全 1.0，无新红。
- 泄漏：腿 B′ 禁键审计 0（box_export＋hints 两处）；腿 D 热路径 accounting 禁键审计 0；关旗旁证顺手复读＝off-face sha c6ff9d478007b287／be657d8db1e7dbde／sel_n 362／kw {} 与合前逐位同。
- 缓存披露（腿 D，热路径零实参自动解析）：case_slug＝liuxiang／wanghong（不是 "case"）、case_slug_fallback=False（两案 6/6 题）；summary_missing=False、n_with_summary=362（刘翔）／533（王虹）、degraded_continue=False。

## 4. 测后复验

- env 已摘（post.env_popped=True）；Settings().test_tree_line=False；Settings.from_env().test_tree_line=False。
- 工作树 app/／config.json／tests/／scripts/ 零改动、零新 commit（tip 仍 ae77b77；仅既有 Boyu 的 docs/architecture-tree-2026-10-27.html 未入库改动在场，未碰）。

## 5. 边界与禁项

- 禁项遵守：未改出厂默认、未 commit 默认开、未合 C-123／C-113／C-121／C-122／C-124、未开树17／22／25 刀、金标只进量尺面、缓存未入库、产物零官方原文。
- 本单不回答：真跑层金标被引红标（需配对真跑，属树17刀票）；六案满跑／默认开复测（Boyu 已定序到刀后）。

## 6. 交账件

- 本文件＋C129_two_case_smoke.json；/tmp/c129/ 有脚本、日志、原始逐题 json 与两件备份。交付时未 commit（等 Boyu 一句话）。
