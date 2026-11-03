# C-133 合 main 交账 — 删旧修／清幻觉

- 日期＝2026-11-03｜执行单＝Boyu「C-133｜合入 main」｜模型＝glm5.3flash
- 枝＝`qoder/c133-purge-legacy`（tip `c119da4`）→ main（合前 `444a91f`＝C-132 docs tip）

## 合入过程

- 合前预检：origin/main＝`444a91f`（✓）；祖先含 `70fd7f9`（✓）；`444a91f` 是 `c119da4` 祖先＝FF 可行 ✓。
- `git merge --ff-only` ＝ `444a91f..c119da4` **零冲突**，20 文件 +72/−3,611（删密度桥模块 424 行＋test_c108 106 行＋9 根旧线探针 3,023 行；test_c109/c111 迁测试树共用面；test_c132 b2 收紧为 import 必失败；话术与 HANDOFF 订正）。
- push ＝ `444a91f..c119da4 main -> main` **成功**，远端 tip＝`c119da4`。

## 合后核对（当场现跑）

- `grep -R ensure_kg_submit_from_density app/ --include='*.py'`＝**0**（`kg_density_bridge`／`density_submit_surface` 源码同 0）。
- 无 env：`Settings.from_env().test_tree_line`＝**True**；`import app.pipeline` OK。
- 旁证可复读＝`artifacts/C133_purge_legacy.md`＋`.json`（交付件随本合账入库）。
- 禁枝仍不合＝是：C-123 两笔 `e1526a4`／`148c140` 不在 main；`cursor/c113-*` 本地与 origin 均已不存在（C-133 件② 已删）。
- r28／r41（`cursor/r28-tree17-cite-8338`／`cursor/r41-tree17-cite-8338`）＝**未删**，按本单范围保留待拍。注：两枝 commit 不在 main 祖先链——其内容是经 C-125 端口（文件复刻）进 main，枝本身保留。

## 基线改记

- 合后全套＝**7 failed / 1231 passed / 1 skipped**（红名与合前逐名一致：c19 test_m／c37 except_pass／c38／c37 zero_ref／c37 knife8／c37 knife9／c73 knife；passed 1240→1231＝−9 全为被删格真账：c108 6＋c109 2＋c111 1）。
- c37 zero_ref 红保持同名，live 缺失集 10→6（probe_c108~c111 随删退出）。

## 本件落痕

- 本合账（md＋json）随 docs commit 入库（sha 见 git log，不写入本件）；已备份 /tmp/c133/。
