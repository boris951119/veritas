# C-132 合 main 交账 — 测试树出厂默认开＋删旧路

- 日期＝2026-11-03｜执行单＝Boyu「C-132｜合入 main」｜模型＝glm5.3flash
- 枝＝`qoder/c132-test-tree-default-on`（tip `70fd7f9`）→ main（合前 `9481f9e`＝C-129 docs tip）

## 合入过程

- 合前预检：origin/main＝`9481f9e`（✓）；祖先含 `ae77b77`（C-128 docs）／`c2306e7`（C-128 代码）／`5a2d736`（C-125 交账）全 ✓；`9481f9e` 是 `70fd7f9` 祖先＝FF 可行 ✓；C-123 两笔 `e1526a4`／`148c140` 不在 main ✓。
- `git merge --ff-only` ＝ `9481f9e..70fd7f9` **零冲突**，8 文件 +242/−40（config.py＋kg_test_tree_line.py＋pipeline.py＋HANDOFF.md＋test_c125/127/128 三文件翻默认＋新增 tests/test_c132_default_on.py 8 格）。
- push ＝ `9481f9e..70fd7f9 main -> main` **成功**，远端 tip＝`70fd7f9`。

## 合后核对（当场现跑）

- **无 env 默认开＝True 三读点**：`Settings()` dataclass 默认 True；`Settings.from_env()`（弹出 VERITAS_TEST_TREE_LINE 后）True；`Settings.from_json()` 缺键 True。
- **旧路主路径已删**：`grep -c ensure_kg_submit_from_density app/pipeline.py`＝**0**（模块本身保留，直连测试 test_c108 11 格与 probe_c108 仍引用）。
- **显式关行为**＝跳过交卷面＋`kg_submit_skipped` 披露键（入 kept 白名单），不回密度桥。
- **旁刀旗仍出厂关**：`claim_slots`／`anchor_stable`／`conflict_trace`／`conf_calib`／`tree15_depress` 全 False。
- **禁枝未合**：C-123／C-113／C-121／C-122／C-124 均未进 main（C-123 两笔 sha 当场查证不在祖先链）。
- **旁证可复读**：`artifacts/C132_test_tree_default_on.md`＋`.json`（枝上交付件，随本仓入库）。

## 旁证现抄（自 C132 交付件 json）

- 零模型烟测两案：liuxiang q_001＋wanghong q_001，`kg_test_tree_line=test_tree_full`、`case_slug` 实名（liuxiang／wanghong）、fallback=false、`kg_density_line=test_tree`、`kg_submit_layer=submit`、summary_missing=false、**leak 0**（两案同）。
- 整套默认开＝**7 failed / 1240 passed / 1 skipped，62.29s**（红名全为基线同名：c19 test_m／c37×4／c38 空行／c73 knife，零新增；＋8 全来自新格）；显式 0 对照臂＝6 failed / 1241 passed / 36.00s（c19 对交卷面形状敏感、关旗读绿，记名不修）。
- 墙钟税＝默认开 62.3s vs 对照 36.0s＝+26s（建库面），已记 HANDOFF 注意项。

## 本件落痕

- 本合账（md＋json）随 docs commit 入库（sha 见 git log，不写入本件——自比字段永远慢一笔）；已备份 /tmp/c132/。
