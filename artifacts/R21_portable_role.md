# R21 — 可迁移来源角色信号

## 结论先行

- 刘翔回归：@7 **12/14**（门槛 ≥11；R20=12）。
- jilong：池20 **4**（R20 4），@7 **2**（R20 2）。
- us_cn_ai：池20 **6**（R20 6），@7 **1**（R20 0）——冒烟 @7 相对 R20 上涨。
- 诊断误标率：liuxiang 43%→36%，jilong 69%→8%，us_cn_ai 92%→38%（三案均降，至少两案明显）。

墙钟约 56s。规则优先；未调线上大模型；无案名硬编码；无「保金标 id」线上规则。

## 诊断：金标误标（修后，portable_role 尺）

| 案 | 金标 | commentary/低权威 | 误标率 | Top portable_role |
|---|---:|---:|---:|---|
| liuxiang | 14 | 5 | 36% | official_primary:3, media_relay:3, official_reprint:2 |
| jilong | 13 | 1 | 8% | media_relay:12, commentary:1 |
| us_cn_ai | 13 | 5 | 38% | commentary:5, institution_def:4, media_relay:4 |

### 修前对照（同尺快照 `R21_diagnosis_before.json`）

| 案 | 误标率 | Top fine_role |
|---|---:|---|
| liuxiang | 43% | official_primary:3, official_reprint:2, party_relay:2 |
| jilong | 69% | commentary:9, media_relay:4 |
| us_cn_ai | 92% | commentary:12, media_relay:1 |

根因：跨案金标本质是可核验事实句，旧链路因文风像评论系统性落在 commentary／低权威桶，R20 权威注入抬不动。

## 评测 vs R19／R20

| 案 | 池20 | @4 | @5 | @7 | R20@7 | R19池20 | Δ@7 |
|---|---:|---:|---:|---:|---:|---:|---:|
| liuxiang | 8 | 9 | 11 | 12 | 12 | 8 | +0 |
| jilong | 4 | 1 | 1 | 2 | 2 | 4 | +0 |
| us_cn_ai | 6 | 1 | 1 | 1 | 0 | 6 | +1 |

## 改动要点

1. **`verifiable_fact_signals`**：时点／数额／通报模板／断言复合槽；禁止案专名。
2. **`portable_role` 与 `fine_role` 分流**：一筛仍吃 R20 `fine_role`（保刘翔 @7）；披露／权威带／二筛注入用 `portable_role`（可核验 commentary→media_relay）。
3. **`authority_band` + `verifiability_unit`** 吃可核验槽；媒体等级仍只作一维。
4. **二筛注入**：高可核验池内段插到 `head_keep` 之后（进 Top-k 前段），不再只置换弱尾。
5. **词表**：`GENERIC_BULLETIN`／`INSTITUTION`／`OFFICIAL_VOICE` 加法扩展跨案模板，保留原安置套话。
6. 保留 R19 pool／R20 conflict_pairs／裁决分流／二筛无问句相似度；未整套重拟合系数。

## 剩余局限

- 池外金标（pool>20）仍无法靠二筛注入进 @7；池20 与 R20 持平。
- `portable_role` 未回写一筛独热；跨案 @k 主要靠注入。再涨需轻量重拟合或池扩。
- 通稿近同文去重仍靠正文相似，不依赖金标标签。

## 路径

- `artifacts/R21_portable_role.json`
- `artifacts/R21_portable_role.md`
- `artifacts/R21_diagnosis_before.json`
- `scripts/kg_lab/run_r21_portable_role.py`
