# C-132 交账 — 测试树默认开＋删旧路（Boyu 硬令落地）

- 日期：2026-11-03；基线 tip＝9481f9e（祖先含 ae77b77／c2306e7／5a2d736，当场核过）；枝＝`qoder/c132-test-tree-default-on`（自 9481f9e，本地一笔 `70fd7f9`，**未合 main、未 push**，等贴合入指令）。

## 1. diff 面（8 文件 +242/−40）

- `app/config.py`：`test_tree_line: bool = True`（C-132 注释＝出厂开＝测试树主线；显式 0/false/off/no＝紧急停用）。
- `app/pipeline.py`：主路径 else 分支（`ensure_kg_submit_from_density`）整段删除；`kg_submit_surface` 开启时恒走 `ensure_test_tree_submit`＋窄面 apply＋pack kwargs；显式关＝跳过交卷面＋账面披露 `kg_submit_skipped`（reason=test_tree_line_off）；kept 白名单登记 `kg_submit_skipped`（report 面可见，C-123 教训）。
- `app/core/kg_test_tree_line.py`：`test_tree_line_enabled` env 兜底默认翻 True（显式关仍 False）——这是改动中发现的第一处「隐写死默认」，不翻则三态读点口径分裂。
- 守护翻转：`tests/test_c125_test_tree_line.py`（a/a2/a3 三格改默认开断言）、`tests/test_c127_cache_disclose.py`（d 格）、`tests/test_c128_case_slug.py`（d3 格改名 default_on_c132）。
- 新守护 `tests/test_c132_default_on.py`（8 格）：默认 True 三读点／显式关枚举／源码静态断言 pipeline 不含密度桥调用＋动态炸点腿（把 `ensure_kg_submit_from_density` 打成炸点后跑选料块不炸）／默认块账面三键＋case_slug 回落披露＋禁键审计／显式关跳过＋白名单登记／旁路刀仍出厂关（anchor_stable／conflict_trace／conf_calib／tree15_depress／claim_slots 全 False）。
- `docs/HANDOFF.md`：顶部一段 C-132 交账（含墙钟税与 c19 敏感性备注）。

## 2. 默认 True 证据

- 无 env：`Settings().test_tree_line is True`、`Settings.from_env().test_tree_line is True`（烟测当场打印）；config.json 无键、from_json 缺键 → True；`config.json` 磁盘文件未改。
- 显式 `VERITAS_TEST_TREE_LINE=0/false/off/no` → False（四值枚举格绿）。

## 3. 旧路已删／不可达证据

- 源码静态：`ensure_kg_submit_from_density` 在 `app/pipeline.py` 中零出现（守护格 test_b 钉死）。
- 动态：把密度桥入口 monkeypatch 成炸点后按默认跑选料块不炸＝主路径零调用（test_b2）。
- 模块保留：`app/core/kg_density_bridge.py` 不删——`tests/test_c108_density_submit.py` 与 `scripts/probe_c108_density_default.py` 直连引用仍在（11 格绿），只是主路径零调用（工单「他处仍引用，保留模块」条款）。

## 4. 两案烟测（零 LLM、真 loader、无 env）

- liuxiang/q_001：kg_test_tree.line=test_tree_full｜case_slug=liuxiang（fallback=False）｜kg_density.line=test_tree｜kg_submit.layer=submit｜summary_missing=False｜泄漏 0。
- wanghong/q_001：同上（case_slug=wanghong）。
- 合计禁键泄漏＝0；账面不存在「密度桥为唯一交卷源」形态（kg_test_tree 键在场＝测试树面已交）。

## 5. 套件与墙钟

- 默认开全套：`7 failed, 1240 passed, 1 skipped in 62.29s`＝7 红与基线（9481f9e）逐名相同（c19 test_m、c37 except_pass／script_zero_ref／knife8／knife9、c38 空行、c73 knife），零新增红；+8 passed 全来自 tests/test_c132_default_on.py。
- 对照（env=0 跳过路径）：`6 failed, 1241 passed, 36.00s`。⇒ 默认开的全套税≈+26s＝测试树面在流水线类测试里的嵌入/出面成本（有 ollama 机器付、.kgcache 逐轮吸收；无 ollama 机器 ensure_embeddings 快速炸→fallback_lexical）。
- ⚠ 新发现记名不盲修：c19 `test_m_production_messages_bite` 对选料面形状敏感——跳过路径下转绿、默认开（与旧密度桥路径）下红。它是基线同名红，本单未动。

## 6. 未合禁枝与旁路刀

- 未合／未 cherry：C-123／C-113／C-121／C-122／C-124（工单禁项全程未动）。
- 旁路刀仍出厂关：anchor_stable／conflict_trace／conf_calib／tree15_depress／claim_slots＝False（守护格 test_e 钉死）；C-123 两旗（conflict_trace/conf_calib）仍在、出厂关、未默认开。
- 未提交 `.kg_lab_vault`／`.kgcache`／逐题原始 json；产物零官方原文。

## 7. 交付件

- 本文件＋C132_test_tree_default_on.json；备份与烟测记录在 /tmp/c132/。枝上交付未合 main（工单：等 Boyu 贴合入指令再出合账粘贴单）。
