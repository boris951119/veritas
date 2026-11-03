# C-135 合 main 交账

工单：把枝 `qoder/c135-expand-accounting`（tip 8b168c3，祖先含 C-134 探针
tip 4e88b58）合进 main；合前 main＝e6349e0（C-133 docs tip）符合。

## 合入记录

- `git merge --ff-only`：**e6349e0..8b168c3 零冲突 FF**。
- 随枝入库两票：
  1. **C-135 生产**＝`accounting.kg_test_tree.expand`（enabled／terms_n／
     paraphrase_n，只记计数、窄面／pack 零泄漏）＋守护格
     `tests/test_c135_expand_accounting.py` 4 格＋C-135 交账件；
  2. **C-134 探针**＝`scripts/probe_c134_two_case_gate.py`（4e88b58 整票）。
- push：`origin/main e6349e0..8b168c3` 成功（无 force）。

## 合后旁证（全部当场量）

- tip：main＝8b168c3＝枝 tip；
- expand 键（无 env 抽一题，零 LLM）：
  `expand={'enabled': True, 'terms_n': 1, 'paraphrase_n': 1}`，键集精确相等；
- 密度桥：`grep app/ ensure_kg_submit_from_density|kg_density_bridge`＝**0**；
- 旁证可读：`C135_expand_accounting.{md,json}`＋`C134_two_case_gate.{md,json}`；
- 禁枝：c113/c121/c122/c123/c124 分支名**不存在**（C-133 已删）；
  在库枝扫描——r28/r41 不在 main 祖先，其余在库枝均为已并线历史；
- 全程零 VERITAS_ 环境变量；测试已在同内容树上量过（commit 前
  7 failed／1235 passed，7 红同名同位），合并零内容变化未重复跑。

## 范围守卫

未合 C-113／121／122／123／124；旁路默认零开启；dens／k／一筛二筛
系数零改动；本交账件随后续 docs 票入 main（只含 C135_merge 两件）。
