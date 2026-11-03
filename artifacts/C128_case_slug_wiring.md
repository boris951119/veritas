# C-128 件② case_slug 实名接线（交账）

- 结论：**YES**——公共解析表＋ensure 接线＋披露键落地；守护 7 格绿＋两把假腿刀见红；关旗 off-face 字节逐位同（按工单免跑满六案）；总旗仍出厂默认关。
- 基线：main `1157723`（祖先含 `9881dbb`）；枝＝`qoder/c128-case-slug-wiring`（本单不合 main）。

## 改动面

- `app/core/kg_test_tree_line.py`（+40/−2）：公共表 `CASE_MARK_PAIRS`（六对标记→slug）＋`resolve_case_slug(dossier)`（读 `dossier.title`，未命中回落 `"case"`，不臆造案名）；`ensure_test_tree_submit` 加 `case_slug=` 可选实参（缺省走解析），解析后传入 `build_test_tree_surface`；披露键写账。
- `scripts/kg_lab/batch_summarize_case.py`：`_slug` 改为从公共表取对（禁第三套表漂移）。
- `scripts/probe_c125_six_case_gate.py`：`CASE_MARKS` 改为从公共表反推（slug→mark）。
- `tests/test_c128_case_slug.py`（新，7 格）。

## 接线与披露（B）

- pipeline 开旗调用**零改动**：`ensure_test_tree_submit(dossier)` 无实参即经解析拿实名——official loader（`Dossier(title=Path(case_dir).name)`）与常规 loader（`title=manifest title or case_dir.name`）的 title 都含案名标记，两条入口天然可解析。
- 披露：`accounting["kg_test_tree"]["case_slug"]`（实际使用的 slug）＋`["case_slug_fallback"]`（是否回落 `"case"`）——嵌在既有白名单键内＝零新顶层键，账面过禁键审计；`build_test_tree_surface` 返回也带 `case_slug`。

## 现场读数

- 真实刘翔案（official loader、title＝中文目录名）经 `ensure_test_tree_submit(dossier, force=True)`：`case_slug="liuxiang"`、`case_slug_fallback=false`、`cache=vault_present true / n_rows 372 / n_with_summary 362 / summary_missing false / affected [] / degraded_continue false`——生产路径实名、暖臂不再误报缺席（C-127 件②的误报现场已消除）。
- 无标记卷名：`case_slug="case"`、`case_slug_fallback=true`、回落可读。

## 守护与刀（C）

- 7 格全绿：解析六标记全中＋同表断言／暖臂实名（tmp vault 证 `summary_missing=False`）／回落披露／显式 `case_slug=` 覆盖 title／建库脚本与探针同源（含 `_slug` 功能腿）／pipeline 调用点零实参即拿实名／出厂默认关未动。
- 两把假腿刀见红：K1 解析恒返回 `"case"`→暖臂刘翔格红；K2 摘披露键→暖臂格 KeyError 红。下刀后字节还原（diff 只剩本单改动）。
- 账记我：第一版在 `kg_test_tree_line` 注释里写了建库脚本模块名，被 C-127 的「生产面零建库脚本引用」内容守卫咬红（守卫有牙、判据正确）——改措辞、守卫一字未动。

## 量尺读数

- 枝上整套：`7 failed, 1231 passed, 1 skipped`＝主仓同 commit 基线 7 红逐名不变＋本单 7 格绿（过程中 1 笔额外红即上述守卫咬注释，改措辞后清零）。
- 关旗 off-face：sha16 `c6ff9d478007b287`／`be657d8db1e7dbde`、sel_n 362、kw 空——与改前逐位同（按工单：off-face 字节同＝免跑满六案；@7／holdout 沿用 C-127 合后基线读数 12／86%80%80%，未重跑）。
- 六案门控腿C 直接显式传 slug、不经过本单改的 ensure 解析路径＝读数不受影响。

## 禁项核对

- `VERITAS_TEST_TREE_LINE` 默认关：dataclass／from_env 双 False（守护格钉死）。
- 未合 C-123／C-113／C-121／C-122／C-124；未做默认开＋六案复测（属下一票）；未动 para_id 复用语义；未接跳边臂；热路径零自动 summarize；零官语料原文进产物；无 Markdown 表。

## 产物索引

- 件① 只量：`artifacts/C128_case_slug_gap_measure.md`／`.json`（主仓工作树，未 commit，/tmp 有备份）
- 件② 本件：`artifacts/C128_case_slug_wiring.md`／`.json`（随枝入库）
