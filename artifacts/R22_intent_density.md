# R22 — 轻量意图路由＋可变 k 冲盒内密度

## 结论先行

- 刘翔回归：@7 **12/14**（门槛 ≥11；R21=12）；盒内微平均密度 **57%**。
- jilong：盒内微平均密度 **11%**（1/9）；@7=2（R21 2）；池20=4。
- us_cn_ai：盒内微平均密度 **44%**（4/9）；@7=4（R21 1）；池20=6。

墙钟 44.2s。规则优先；未调线上大模型。

## 主指标：盒内金标密度（可变 k）

| 案 | Σ金标/Σk | 微平均密度 | 题均密度 | 达≥2/3 题数 |
|---|---:|---:|---:|---:|
| liuxiang | 12/21 | 57% | 57% | 0/3 |
| jilong | 1/9 | 11% | 11% | 0/3 |
| us_cn_ai | 4/9 | 44% | 44% | 2/3 |

### 分题

| 案 | qid | route | k | 金标 | 密度 | proxy核 |
|---|---|---|---:|---:|---:|---:|
| liuxiang | q_001 | adjudicate | 7 | 4 | 57% | None |
| liuxiang | q_002 | adjudicate | 7 | 4 | 57% | None |
| liuxiang | q_003 | adjudicate | 7 | 4 | 57% | None |
| jilong | q_001 | adjudicate | 3 | 0 | 0% | 3 |
| jilong | q_002 | adjudicate | 3 | 0 | 0% | 3 |
| jilong | q_003 | adjudicate | 3 | 1 | 33% | 3 |
| us_cn_ai | q_001 | adjudicate | 3 | 2 | 67% | 3 |
| us_cn_ai | q_002 | adjudicate | 3 | 2 | 67% | 2 |
| us_cn_ai | q_003 | adjudicate | 3 | 0 | 0% | 3 |

## 辅表 vs R21（固定切点累计命中）

| 案 | 池20 | @4 | @5 | @7 | R21@7 | Δ@7 |
|---|---:|---:|---:|---:|---:|---:|
| liuxiang | 8 | 9 | 11 | 12 | 12 | +0 |
| jilong | 4 | 1 | 1 | 2 | 2 | +0 |
| us_cn_ai | 6 | 4 | 4 | 4 | 1 | +3 |

## 改动要点

1. **意图三路由**：adjudicate／institutional／fact_check（规则优先）。
2. **路由→二筛权重偏置**：选项对齐／制度载体／可核验时点各一套小偏置。
3. **核心段近似金标**：可核验／权威／选项侧（不读金标 id）。
4. **可变 k（3～7）**：核心先装、补位有上限；优先密度≥2/3，宁少勿滥。
5. 保留 R19 pool／R20 conflict_pairs／R21 portable_role／verifiable_fact_signals。

## 剩余局限

- 池外金标仍进不了盒；密度上限受池20 召回约束。
- 核心近似≠金标；proxy 达标而金标密度不足时需收紧 is_core。

## 路径
- `artifacts/R22_intent_density.json`
- `artifacts/R22_intent_density.md`
