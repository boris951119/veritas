# R17 — 标签解耦（schema + lexicon）

规则只规定标签**类别**；主体／主张表面词从问句抽取，可选 `vaults/kg-lab/lexicon/<slug>.json` 覆盖。
一筛系数仍冻结 R9／R12；二筛规则不变，但词表改为注入。
墙钟 42.2s。use_llm_lexicon=False（默认本地规则，不调 14B 抽词）。

## schema：类别 → 用途

| 类别 | 标签 | 阶段 |
|---|---|---|
| speaker_role | `official_primary` | stage1 |
| speaker_role | `official_reprint` | stage1 |
| speaker_role | `institution_def` | stage1 |
| speaker_role | `party_primary` | stage1 |
| speaker_role | `party_relay` | stage1 |
| speaker_role | `opposition_framing` | stage1 |
| speaker_role | `mixed_summary` | stage1,stage2 |
| speaker_role | `media_relay` | stage1 |
| speaker_role | `commentary` | stage1,stage2 |
| source_fine_comment | `party_comment` | stage1 |
| source_fine_comment | `institutional_gloss` | stage1 |
| source_fine_comment | `mixed_roundup` | stage1,stage2 |
| source_fine_comment | `pure_opinion` | stage1,stage2 |
| source_fine_relay | `relay_official_bulletin` | stage1 |
| source_fine_relay | `relay_party_primary` | stage1 |
| source_fine_relay | `relay_secondary` | stage1 |
| channel_tier | `central_official` | stage1 |
| channel_tier | `local_official` | stage1 |
| channel_tier | `market_media` | stage1 |
| channel_tier | `foreign_media` | stage1 |
| channel_tier | `self_media` | stage1 |
| channel_tier | `other` | stage1 |
| claim_grain | `claim_full` | stage1 |
| claim_grain | `claim_keyword` | stage1 |
| amount_attr | `amount_status` | stage1 |
| time_attr | `time_anchor` | stage1 |
| subject_attr | `subject_match` | stage1 |
| subject_attr | `subject_x_channel` | stage1 |
| bait_signals | `title_bait` | stage2 |
| bait_signals | `section_bait` | stage2 |
| bait_signals | `offtopic_cross_claim` | stage2 |
| bait_signals | `fake_gloss` | stage2 |
| dedup_signals | `stitch` | stage2 |
| dedup_signals | `near_dup` | stage2 |
| dedup_signals | `same_quote_cluster` | stage2 |
| slice_extra | `identity_synonym` | stage1 |
| slice_extra | `resume_noise` | stage1 |
| slice_extra | `identity_resume` | stage1 |
| claim_family | `leave` | stage1,stage2 |
| claim_family | `money` | stage1,stage2 |
| … | 共 41 行 | … |

### 一筛特征（排序）

```
subject_match, subject_x_channel, claim_full, claim_keyword, amount_status, time_anchor, credibility, channel_self, identity_synonym, resume_noise, identity_resume, role_official_primary, role_official_reprint, role_institution_def, role_party_primary, role_party_relay, role_opposition_framing, role_mixed_summary, role_media_relay, role_commentary, tier_central_official, tier_local_official, tier_market_media, tier_foreign_media, …
```

### 二筛特征（去重／挡路）

```
title_bait, section_bait, offtopic_cross_claim, fake_gloss, mixed_roundup, mixed_summary, pure_opinion, commentary, stitch, near_dup, same_quote_cluster, r9_comment, r9_relay, fine_role, channel_tier
```

## 刘翔回归（对照 R12 池20 @7＝13/14）

| k | 金标命中 | 金标总数 | 非金标 |
|---:|---:|---:|---:|
| 4 | 9 | 14 | 3 |
| 5 | 11 | 14 | 4 |
| 7 | 12 | 14 | 9 |

池 20 内金标 14/14；一筛 sum@7=10。

## holdout 冒烟

| 案 | 池内金标 | @4 | @5 | @7 |
|---|---:|---:|---:|---:|
| jilong | 2/13 | 1/13 | 2/13 | 2/13 |
| us_cn_ai | 3/13 | 0/13 | 0/13 | 0/13 |

冒烟合计 @7 **2/26**（R16 同两案 @7 为吉隆 2/13 + 中美AI 0/13＝2/26）。

## 改动文件

- `app/kg_lab/tag_schema.py`
- `app/kg_lab/case_lexicon.py`
- `app/kg_lab/multidim_weight.py`
- `app/kg_lab/r9_buckets.py`
- `app/kg_lab/inbox_rerank.py`
- `app/kg_lab/source_role.py`
- `app/kg_lab/slice_dims.py`
- `app/kg_lab/query_expand.py`
- `vaults/kg-lab/lexicon/liuxiang.json`
- `scripts/kg_lab/run_r17_tag_decouple.py`
- `tests/test_kg_lab_r17_tag_decouple.py`

## 读法

刘翔池20 @7＝12/14（目标 ≥12/14，R12 为 13/14）。冒烟两案 @7＝2/26；池内金标 5/26。

## 剩余风险

- 主张族目录仍含就业／安置类通用词（买断／编制等），不是人名，但跨域案可能误激族。
- 主体抽取是浅规则，复杂问句可能漏机构别名；可用 case_lexicon 或 use_llm=True（本地14B）补。
- 本跑关闭了金标 prefer_ids，通稿簇代表与 R12 训练跑不完全同分布。
- 一筛系数仍在刘翔上拟合；解耦词表不等于跨案重拟合。

## 路径
- `/Users/liuboyu/Developer/veritas-obsidian-kg-exp/artifacts/R17_tag_decouple.json`
- `/Users/liuboyu/Developer/veritas-obsidian-kg-exp/artifacts/R17_tag_decouple.md`
