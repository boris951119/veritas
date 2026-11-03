# C-133 删旧修／清幻觉 交账

- 日期＝2026-11-03｜枝＝`qoder/c133-purge-legacy`（自 `444a91f`）｜tip＝`c119da4`（未合 main 未 push）
- Boyu 硬令：旧路上的修没用了都删掉、别留着诱发幻觉；测试树为唯一主线（C-132）。

## 件① 盘点（先列后删）

1. 调用图（`kg_density_bridge`／`ensure_kg_submit_from_density`／`density_submit_surface`）：
   - `app/`：仅模块本体一处——生产调用链零引用（pipeline 主路径 C-132 已断）。判定＝可删。
   - `tests/`：`test_c108_density_submit.py`（只为桥存在，6 格）＝删；`test_c109`／`test_c111`（借桥造面测一筛／回灌适配层）＝迁移（脚手架换测试树共用面）；`test_c132` 炸点桩＝改「模块不存在／import 必失败」断言。
   - `scripts/`：9 根旧线探针（probe_c108／c109／c110／c111／c114／c115／c116／c117／c118）＝删（仪器量的是旧线；读数档案在 artifacts/，C-130 已判旧线读数不可比）。
   - `artifacts/`：C125／C132 交付件与 c120 探针抄本提及桥＝点时快照，档案不改。
2. 禁枝清单（本地＋origin）：
   - 命中并已删＝`cursor/c113-tree17-focus-cite`（本地 tip `1e14cfc`；origin `1e14cfce`）。
   - `c121`／`c122`／`c123`／`c124`／`cite-check-stable`：本地与 origin 均**不存在**（C-121/123/124 的枝只活在仓外克隆，如 /tmp/c121/tree——不在本单范围）。
   - 边缘待拍（**未删**）＝`cursor/r28-tree17-cite-8338`（`9fe8bd6`）、`cursor/r41-tree17-cite-8338`（`904c337`）：旧 tree17 刀但属 R-series 实验线命名（cursor/*，非单面 qoder/*），整线已由 C-125 端口收编进 main；删不删等 Boyu。
   - 未动的保护枝＝`qoder/c132-*` 及其余已合 ticket 枝。
3. 未合禁刀在 main 的死代码／旗残留：`TREE17_FOCUS_CITE`／`TREE17_LIST_PRECISION`／`CITE_CHECK_STABLE` 在 app/ 零出现（只在 artifacts/ 档案里）；kept 白名单无 C-123/124 键。⇒ 禁刀零旗残留；唯一旧路残留就是 C-107/108 旧线本身（本单处置见下）。

## 件② 已删（git rm，全可回滚）

- 模块＝`app/core/kg_density_bridge.py`；测试＝`tests/test_c108_density_submit.py`（6 格）；探针＝9 根（见上）。合计 11 文件 −3,539 行。
- 禁枝＝`cursor/c113-tree17-focus-cite`：本地 `git branch -D` 成功、origin `git push origin --delete` 成功（tip sha 已录上＝可回滚）。
- 远端待删清单＝空（origin 上无剩余禁枝）。

## 迁移与改写（防「假装旧桥还是主路」）

- `tests/test_c109_stage1_pool.py`：去桥 import；删 2 格桥行为（stage1 关→BM25 回退、上游短盒信任）；「系数不进 pack」格迁测试树共用面（ensure_test_tree_submit→apply→pack，embed 打桩）。
- `tests/test_c111_rehydrate_box.py`：去桥 import；删 1 格桥行为；pack 格迁移并改名 `test_c111_pack_kwargs_no_coeff_tree_surface`。
- `tests/test_c132_default_on.py`：b2 腿由「炸点桩」收紧为「import 必 ModuleNotFoundError」（比炸点更硬）；docstring 同步。
- 适配层定位话术：`kg_stage1_pool.py`／`kg_rehydrate.py` docstring 加 C-133 注（适配层、生产消费方已随桥删）；`kg_test_tree_line.py` 旧句「关旗（默认）＝生产走 C-108 密度桥路径」改为 C-132/133 现实；`config.py` kg_stage1 注释、`test_c125` L212 注释同步；HANDOFF C-132 节与两处历史条目加「已随 C-133 删除」标记。
- 保留待拍：`app/core/kg_stage1_pool.py`／`kg_rehydrate.py`／`kg_rehydrate_seeds.json` 与 config 旗 `kg_stage1`／`kg_rehydrate_box`（默认 True）——票面「不删一筛二筛」字样在，故本单保留；但生产消费方已随桥消失＝生产孤岛，建议下一票拍去留。

## 验收（当场现跑）

- `grep -R ensure_kg_submit_from_density app/ --include='*.py'`＝**0**（`kg_density_bridge`／`density_submit_surface` 同 0；唯一命中曾是 gitignored 陈旧 .pyc，已清）。
- 无 env：`Settings.from_env().test_tree_line`＝True；`import app.pipeline`／两个适配层 import OK。
- 目标测试＝39 格全绿（c132 8＋c109 3＋c111 5＋c125/c127/c128）；被删旧桥格删除而非 skip。
- 全套＝**7 failed / 1231 passed / 1 skipped，53.26s**。逐名比对（在 `444a91f` 临时 worktree 上重跑同三文件）＝同 7 名：c19 test_m／c37 except_pass／c38／c37 zero_ref／c37 knife8／c37 knife9／c73 knife——零新增零消失。passed 1240→1231＝−9，全为被删格真账（c108 6＋c109 2＋c111 1；c108 格数经 `git show 444a91f` 数得，非凭记忆）。
- c37 zero_ref 红保持同名，缺失集 10→6（probe_c108~c111 退出 live 集；余 c86/c87c/c88/c92/c95/c107 未动）。
- 禁枝未合＝是（C-123/113/121/122/124 均不在 main）；未提交任何缓存（.kgcache／.kg_lab_vault 未碰）。
