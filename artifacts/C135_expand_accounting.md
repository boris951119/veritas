# C-135 交账 — 环2 扩写披露进 accounting

工单：C-134 环2 缺口①（扩写在 fuse_r19 内部跑但 accounting 零披露键）。
枝 `qoder/c135-expand-accounting`（基点 4e88b58＝C-134 探针枝 tip）。
**不自行合 main**；合并不合并口径见文末。

## 修了什么（只修缺口①）

`app/core/kg_test_tree_line.py`：

- `build_test_tree_surface` 出口新增 `expand` dict；`ensure_test_tree_submit`
  把它写进生产 accounting：`accounting["kg_test_tree"]["expand"]`。
- 披露键组（一条代码注释写明，键名可 grep）：
  - `enabled`＝扩写机制在跑（fuse_r19 经典臂无条件扩写）；
  - `terms_n`＝canonical 扩写**词数**（与经典臂同一调用
    `keyword_expand_query(question, sub.rows)`，只记词数、**不记词表原文**）；
  - `paraphrase_n`＝**复用** fuse_r19 既有键 `n_classic_paraphrase`
    （规则改写数，n=1 封顶）。
- 零 pipeline 改动：`kg_test_tree` 整键已在 kept 白名单（C-125 端口登记），
  内层新键随整键透传 report 面。

面卫生（禁止项守住）：surface／hints／pack kwargs 零 expand 键；
扩写全文不进窄面；`audit_forbidden_keys(accounting)`＝0；
`build_submit_surface` 的 ALLOWED_SUBMIT_TOP 与 FORBIDDEN_PACK_KEYS 均不碰。

## 验收一：单测（4 格新文件 `tests/test_c135_expand_accounting.py`）

a 三键在场（键集精确相等，少一键＝红）／b 计数与独立复算逐键一致
（对同一 sub.rows 重跑 expand＋`rule_paraphrase_questions(question, n=1)`）／
c 行为刀（打桩改扩写返回值 → terms_n 跟着变＝披露跟踪机制输出而非常量）／
d 无泄漏。定向 12 passed（c135 4＋c132 回归 8）。
整套 `7 failed, 1235 passed, 1 skipped`（+4＝本单新格；7 红与改前**同名同位**＝
c19×1、c37×5、c73×1，基线红名单见 json）。

## 验收二：C-134 探针环2 复跑（零 LLM；`--legs zero --no-artifact`，113.1s）

两案 × 3 题＝6 题**全部** `accounting_expand_keys` 非空且
`disclosure_matches_independent=True`（与独立复算逐键一致）；
镜像与生产入口等价断言全 True（环证据＝生产证据）：

```
liuxiang/q_001 terms_n=9  para_n=1 match=True equiv=True
liuxiang/q_002 terms_n=17 para_n=1 match=True equiv=True
liuxiang/q_003 terms_n=17 para_n=1 match=True equiv=True
wanghong /q_001 terms_n=22 para_n=1 match=True equiv=True
wanghong /q_002 terms_n=17 para_n=1 match=True equiv=True
wanghong /q_003 terms_n=17 para_n=1 match=True equiv=True
```

（口径注：旧环2 读数是**字符数**且用全库 rows；本轮起与生产同 sub.rows 同
**词数**口径，别拿两组数直减。）

## 验收三：三闸不掉（与 C-134 跑逐位 Δ0）

```
liuxiang: 微密度 0.5714→0.5714  @7 12→12  金标→close 1.0→1.0  泄漏 0→0  现场腿 0.4444→0.4444
wanghong: 微密度 0.8571→0.8571  @7 6→6   金标→close 1.0→1.0  泄漏 0→0  现场腿 0.8571→0.8571
```

本单只加 accounting 披露键，选料面（box／k／close／face）零改动；
零 LLM 复跑的等价断言＋三闸逐位相同即旁证。

## 不做（工单禁止项）

缺口②（D 面无标注维度）③（F 缺同臂参照）④（小盒密度）不动；
六案门控、tree17 刀、dens/k、判定面零改动。

## 探针顺手修（仪器卫生，与验收无关的洞）

`scripts/probe_c134_two_case_gate.py` 的 `--no-artifact` 原先**只解析未使用**——
分段跑会整片覆写 artifacts/C134 交付件。本轮起两处落盘按旗门控；
跑前已备份（/tmp/c134/*.c134backup.json＋/tmp/c135/），C-134 交付件未动。
环证据入口改走 `ensure_test_tree_submit`（＝生产 accounting 写入路径，
返回与 build_test_tree_surface 同一 dict）。

## 合并口径（等 Boyu 指令）

本枝＝C-134 探针枝（4e88b58）＋本单一 commit。FF 合入＝**两票一起带上**
（C-134 探针＋C-135 披露）；若只合生产修复（探针枝留下）须单拆
cherry-pick。两种走法都成立，拍哪种我执行哪种。
