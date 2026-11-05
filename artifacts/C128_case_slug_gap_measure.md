# C-128 件① case_slug 错挂只量（零 LLM）

- 结论：生产热路径开旗时 `case_slug` 恒为默认 `"case"`——title 含「刘翔」且本机暖 vault `summaries/liuxiang/` 在场也读成缺席（误报实锤）；实际使用的 slug 无任何披露键。
- 基线：HEAD＝`1157723`（祖先含 `9881dbb`）✓；`Settings.test_tree_line`／from_env＝False/False（出厂关，未动）✓。
- 方法：旗开（探针进程内 env）、手造 30 段夹具 dossier、`ensure_test_tree_submit(force=True)` 现场跑（探针 /tmp/c128/probe_slug.py，未入库）。

## 调用链（现状）

- `app/pipeline.py` L604-606：旗开 → `ensure_test_tree_submit(dossier)`（无 slug 实参）→ `build_test_tree_surface(dossier)` 走默认 `case_slug="case"`。
- 探针／评测侧已显式传实名：`scripts/probe_c125_six_case_gate.py` 腿C `build_test_tree_surface(d, case_slug=slug)`＝与生产不一致。
- title 事实：official loader `app/ingest/official_case.py` L78 `Dossier(title=Path(case_dir).name)`；常规卷 `app/ingest/case_loader.py` L478 `Dossier(title=manifest title or case_dir.name)`——两条入口的 title 都含案名标记，可供解析（本单件②的接线基础）。

## 默认态读数（件①两臂）

- 臂1 夹具 title 空：slug 落 `"case"`；`kg_test_tree.cache`＝`vault_dir_present=false, n_with_summary=0, summary_missing=true, affected=[summary,vault], degraded_continue=true`；accounting 里 **无任何 case_slug 披露键**（实际用的 slug 不可见）。
- 臂2 title 含「刘翔」＋本机暖 vault `summaries/liuxiang/` 存在（已核 is_dir=true）：**仍挂 `"case"`** → 读数与臂1 逐字同＝暖缓存被读成缺席（误报，回归对照基线）。
- 臂3 对照（探针腿C 同法，显式 `case_slug="liuxiang"`）：`vault_dir_present=true, summary_missing=false, affected=[]`——实名即正常。
- 注：夹具 doc_id 与真实缓存同命名空间（doc_001…），臂3 的 21/30 覆盖读数受夹具/真实 id 撞名影响，只用于说明接线差、不作覆盖率读数。

## 建库脚本／探针映射现状

- `scripts/kg_lab/batch_summarize_case.py` `_slug`：自含六对标记映射（刘翔→liuxiang／王虹→wanghong／中美AI→us_cn_ai／印度航空→ai171／柬泰→kh_th／吉隆→jilong）。
- `scripts/probe_c125_six_case_gate.py` `CASE_MARKS`：同六对、方向相反（slug→mark）。
- 两表目前各自维护＝第三套表漂移风险；件②抽公共表后两处同源。

## 复现步骤（一句）

`VERITAS_TEST_TREE_LINE=1 下 ensure_test_tree_submit(手造 title 含刘翔的 dossier, force=True) 看 accounting["kg_test_tree"]["cache"] summary_missing=true（暖 vault 在场）且无 case_slug 键`。
