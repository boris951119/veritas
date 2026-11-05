# C-143 合 main 交账（冲突留痕可用化）

工单：把枝 `qoder/c143-tree22-conflict-usable` @ `610c6c0`
合进 main（合前 tip `d0c062a`）。合入面＝conflict_trace 键活过白名单＋空态必写（C-115 消费者接线）。
禁合 C-123 整枝／禁枝；勿碰 C-141；合前复核关旗与 tip 产物一致；合后红名单不扩。

## 1. FF 还是 rebase
- 610c6c0 的父 = 90a0608，main 已到 d0c062a ⇒ **FF 不成立**（枝 tip 非 main 的直系祖先）。
- 独立 worktree（`~/Developer/veritas-merge-c143`，不动任何既有 worktree）建 `tmp/c143-rebase`，
  `git rebase d0c062a` ⇒ **零冲突**，新 tip **f157b71**。
- 内容未走样的证据：两票 **patch-id 完全相同** = `691d556eb6061c6595d60e1ac64e97643d44609c`
  （rebase 前 610c6c0 / rebase 后 f157b71）；`610c6c0..f157b71` 的差异只有 C-144 自家 4 个文件
  （4 项：C144_arch_tree_resync.md、C144_dom_tree15_green.png、C144_dom_tree17_retry_pop.png、architecture-tree-2026-10-27.html）。

## 2. 合入面（d0c062a..f157b71 实际进了什么）
```
app/export/official.py               |  23 +-
 app/pipeline.py                      |   9 +-
 artifacts/C143_trace_face.json       | 218 ++++++++++++++
 artifacts/C143_trace_face.md         |  47 +++
 docs/dev-journal.md                  |   4 +
 scripts/probe_c143_trace_face.py     | 545 +++++++++++++++++++++++++++++++++++
 tests/test_c143_trace_report_face.py | 145 ++++++++++
 7 files changed, 985 insertions(+), 6 deletions(-)
```
生产码只有两文件、26 加 6 删（`git diff --numstat d0c062a..f157b71 -- app/` 现抄）：
- `app/pipeline.py`：两处 kept 白名单各加 `"conflict_trace"`（早退路径登记只为两份清单不漂移）。
- `app/export/official.py`：旗开时**必写** `conflict_trace.json`——有留痕走原形，零留痕走
  `records=[] + empty_state=true + detail 末句原因`；旗关分支不写文件（六份官方提交件面一字不变）。
- 其余 = 5 颗新守护格 + 探针 545 行 + 交账件 + dev-journal 4 行。
- **未动**：归并／消解判定、装箱、续盒、Top-7、树15；C-141 枝与其 worktree 未碰。

## 3. pytest（三棵树当场跑，日志在 /tmp/c143_*.txt）
| 树 | 读数 |
|---|---|
| 合前 base d0c062a | `7 failed, 1257 passed, 1 skipped in 52.89s` |
| rebase 后 worktree f157b71 | `7 failed, 1262 passed, 1 skipped in 50.27s` |
| **合后 main f157b71** | `7 failed, 1262 passed, 1 skipped in 58.73s` |

- 红名单逐名比对：合前 7 名、合后 7 名，**新增 0 颗＝不扩**（同名链＝c19 1＋c37 5＋c73 1，既有已知红）。
- passed 差 = **+5**，正好＝C-143 新格 5 颗。
- 判绿前 `env | grep VERITAS_` 已查＝本壳零 `VERITAS_*`（未带旗污染）。

## 4. 合前复核：关旗与 tip 产物一致
- 两树各跑 `scripts/demo_offline.py`（三案例）；**先对齐 `.kgcache`／`.kg_lab_vault` 到主检出**
  （首跑 9 份全差＝每树自建向量缓存的漂移，不是代码差；对齐后重跑）。
- 归一化（剥时间戳、CON/EV/CFL 自增 id 换序贯占位、绝对路径、`accounting.steps`）后
  **3 份 report.json 内容面差异 = 0**；
  report.md 只差一行墙钟（0.4 秒 vs 0.3 秒）。⇒ 关旗＝与 d0c062a 逐字节同形，成立。

## 5. 抽查：开旗键在 report／conflict_trace.json
- 产物面（**合后 main 现量**，`VERITAS_CONFLICT_TRACE=1` 跑 `scripts/demo_offline.py`）：三份 report.json 均含 `accounting.conflict_trace`——
  demo-solid-state n=1／coverage_rate 0.0；bi-delivery-risk n=5／coverage_rate 0.8；rumor-vs-official n=1／coverage_rate 0.0（三案 trace_complete_rate 均 1.0；unclassified 各 1／1／1）。
- 导出面·空态：合成零对撞案卷走 `export_official` ⇒ 仍写 `conflict_trace.json`，`records=[]`、`empty_state=true`，detail 末句原文
  「本次 1 题均未检出冲突对或事实对撞（未检出＝本次研判没有碰到，不等于资料无冲突）。」
- 导出面·命中态：同键写入 `records n=1`、summary n=1／coverage_rate=1.0／trace_complete_rate=1.0／by_class.same_window=1，此态无 `empty_state` 键。
- 导出面·关旗：`export_official` 返回 paths 无 `conflict_trace` 键，out_dir 只有 5 份 JSON＋`字段说明.md`＝官方提交件面不变。

## 6. 默认没被翻
- `app/config.py`：`conflict_trace: bool = False`（未改）。
- `.env`／`config.json` 里 conflict_trace：(零命中)
  ⇒ 出厂仍默认关，路演要看得 `VERITAS_CONFLICT_TRACE=1`。

## 7. push 与收尾
- push：d0c062a..f157b71 main -> main（无 force）；本地 main = origin/main = `f157b71ed186f8afad11f65ce73225de06f61c23`（一致 True）。
- git worktree remove --force 掉 veritas-merge-c143／veritas-c143-base，删 tmp/c143-rebase；未动 veritas-c141／w140／w142／w143／veritas-c144；主检出 .venv／.kgcache／.kg_lab_vault 仍在（摘的是符号链接，实体未删）
- 禁枝：未合 C-123 整枝／禁枝；未开 VERITAS_CONFLICT_TRACE 默认；未动归并判定。
