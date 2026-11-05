# C-146 合 main 交账（冲突分流）

工单：合 `qoder/c146-conflict-triage` @ `e8f6392` → `main`（合前 tip `8e4a817`，含 C-145 归并闸）。
硬规矩：独立 worktree；FF 或 rebase 干净合；禁碰 C-141；合后 pytest 红不扩；不做 cite_accept／报告面改写。

## 1. FF 还是 rebase
- FF 不成立：`e8f6392 的父＝03bfd4a，而 main 已到 8e4a817（C-145）⇒ 非直系祖先，FF 不成立`。
- 独立 worktree（veritas-merge-c146）cherry-pick e8f6392 到 8e4a817 ⇒ 新 tip f9509a2；合入面＝10 files changed, 2014 insertions(+), 7 deletions(-)。
- 冲突：仅 docs/dev-journal.md 一处（两票同栈尾追加）；解法＝C-145 在前、C-146 在后，两条都在。两处生产码自动合并干净（app/core/conflict_trace.py, app/export/official.py），
  合后重读＝两轴共存：载荷里 triage 两键在前、C-145 的 `fold_into_trace_payload` 紧随其后；
  导出面 detail 同时声明 conflict_class 三档与 triage_class 四档，merge_gate 否决句仍只在确有否决时追加。

## 2. pytest（三棵树当场跑，日志在 /tmp/c146m_*.txt、/tmp/c146_final_main_pytest.txt）
| 树 | 读数 |
|---|---|
| 合前 main `8e4a817` | `7 failed, 1275 passed, 1 skipped in 57.54s` |
| 合入树 `f9509a2` | `7 failed, 1291 passed, 1 skipped in 63.17s (0:01:03)` |
| **合后 main `f9509a2`** | `7 failed, 1291 passed, 1 skipped in 61.71s (0:01:01)` |

- 红名单：合前 7 名 → 合后 7 名，**新增 0 颗＝不扩**（同名链 c19 1＋c37 5＋c73 1）。
- passed 差 = **+16**＝C-146 新格 16 颗。
- 判绿前 `env | grep VERITAS_` 已查＝本壳零旗。

## 3. 抽查：开旗 triage_* 在场（合后 main 现量）
- 三份 report.json 的留痕行 **五键齐全＝3/3**（demo-solid-state n=1, bi-delivery-risk n=4, rumor-vs-official n=1）。
- 四档合计 `{"date_offset": 0, "oral_misread": 3, "other": 1, "true_oppose": 2}`（Σ=6）。
- `merge_gate` 节与分流载荷共存＝3/3（C-145 与 C-146 同面不打架）。
- 合后读数与枝上单独跑不同＝C-145 归并闸已在场（行集变化），分流轴本身 3/3 齐全；merge_gate 节与 triage 载荷共存。
- 导出面：records 带 triage、summary.by_triage 在场；空态仍带真实题数原因句；
  detail 同时点名两轴（`conflict_class 三档＋triage_class 四档；merge_gate 否决句仅在确有否决时追加（C-145 既有断言未破）`）。

## 4. 关旗同形（8e4a817 树 vs 合入树，VERITAS_CONFLICT_TRACE=0）
- 两棵树三案例 `report.json` 差异路径 **0**（缓存符号链接对齐主检出＋背靠背重跑）。
- `report.md`：原始文本各差 10／7／8 行，但剥掉墙钟秒数与随机 CON·CFL id 后**差 0 行**（3/3 案例）。
- `chain.jsonl`：剥 hash／mac／payload_hash／prev_hash／index＋到达序＋墙钟后，行多重集相同 **3/3**。
- 口径披露：committed 探针的 crossface 段在文本面未剥「N.N 秒」与随机 id，故 md／chain 这两项用当场对照脚本复算（判据面 report.json 用的是同一套规范化键表），差异均为易变量、无内容差。

## 5. push 与收尾
- push：8e4a817..f9509a2 main -> main（无 force）；本地 main＝origin.main＝`f9509a24644dca2bdbbecb08e3bf03e915a28268`。
- 未开 cite_accept；未改报告叙事面；未碰 C-141 枝与其 worktree；未碰 C-145 线与其 worktree；禁枝未合。
- 摘掉临时 merge 树与 8e4a817 对照树、删 tmp/c146-rebase；veritas-c146（枝树）与 C-140／C-141／C-143／C-144／C-145 各树未动。
- 本交账件（artifacts/C146_merge.md／.json）现**未 commit**——按「不 commit 除非你说」的规矩等令。
