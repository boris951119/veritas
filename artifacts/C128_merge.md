# C-128 合 main 交账（case_slug 实名接线）

- 日期：2026-11-03（现场当笔）
- 合枝：qoder/c128-case-slug-wiring（枝 tip c2306e7）→ main（基线 1157723）
- 方式：git merge --ff-only，零冲突（6 文件 +320/−12）
- 合后 main tip：c2306e7；随后订正 5a2d736（见「更正记录（账记我）」）
- push：c2306e7..5a2d736 已 push origin main（无 force）

## 合后核（全部本机现场重跑，非抄枝上旧数）

- 旗双 False：Settings().test_tree_line=False；Settings.from_env().test_tree_line=False（工单默认关未动）
- resolve_case_slug 在 main：CASE_MARK_PAIRS 6 对；title 含「刘翔」→ liuxiang；空 title → case（回落）
- 披露键：ensure_test_tree_submit 入账 case_slug／case_slug_fallback（嵌在既有 kg_test_tree 白名单键内，不新增顶层键）
- 旗关旁证（off-face 逐位）：off_surface_sha c6ff9d478007b287｜off_sel_sha be657d8db1e7dbde｜sel_n 362｜kw {}＝与合前逐位相同

## 门控复跑（默认关旗、探针显式传 slug）

- 结果：READY=YES；墙钟 278.7s
- liuxiang（regression）：微密度 57%｜@7=12｜金标→细读 1.0｜泄漏=0
- wanghong（holdout）：86%｜@7=6｜泄漏=0
- us_cn_ai（smoke）：67%｜@7=6｜泄漏=0
- ai171（holdout）：80%｜@7=5｜泄漏=0
- kh_th（holdout）：80%｜@7=4｜泄漏=0
- jilong（smoke）：67%｜@7=6｜泄漏=0
- 与枝上读数逐位一致；仅两处披露差异＝案序（现随 CASE_MARK_PAIRS 公共表序）与墙钟
- 全套：7 failed, 1232 passed, 1 skipped（7 红＝既有基线同名格：c19 test_m_production_messages_bite、c37 except_pass_registry_bidirectional、c38_knife_blank_line、c37_script_zero_ref、c37_knife8、c37_knife9、c73 knife；C-128 相关格全绿）

## 更正记录（账记我）

合后门控复跑抓红：探针 CASE_MARKS 反推解包方向错（我的 C-128 重构引入；pytest 不 import 探针、枝上按工单免跑门控故漏网）→ KeyError「刘翔」。订正＝5a2d736（{s: m for m, s}＋方向守卫格 test_d4_probe_case_marks_direction）。复跑逐位一致。教训：probe 脚本改动必须当场跑一遍，不靠 pytest 兜底。

## 未合禁枝（工单点名，全程未动）

C-123（e1526a4+148c140）／C-113／C-121／C-122／C-124
