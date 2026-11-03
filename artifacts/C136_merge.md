# C-136 合 main 交账

工单：把枝 `qoder/c136-arch-tree-sync`（tip a760882）合进 main；合前 main＝
c833ee2 符合。范围＝架构树 HTML＋C-136 交账文档（app/tests 零 diff，
c833ee2..a760882 当场核）。

## 合入记录
- `git merge --ff-only`：**c833ee2..a760882 零冲突 FF**（恰 1 票）。
- push：`origin/main c833ee2..a760882` 成功（无 force）。
- 披露：HTML 票内含 Boyu 此前未入库的树10／22 边界文案（随票入库，
  C-136 工单交账已写明）。

## 合后抽验（全部当场量）
- tip：main＝a760882＝枝 tip；
- 树17 红标＝「引用条数偏少」（data-pop="s17" 当场 grep 到）；
- 默认开写清＝「出厂默认开（无 env 即走）」在 legend 与主线步骤在场；
- 密度桥文案＝仅历史已删句「密度桥本体已删＝C-133」（全文 1 处）；
- 过时词＝双路／出厂默认关／未授权整套替换 grep 全 0；
- 禁枝＝范围票内零 C-113/121/122/123/124 内容，分支仍不合。
- 本交账件随后续 docs 票入 main（只含 C136_merge 两件）。
