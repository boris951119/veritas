# C-139 树17 引用验收打回循环——两案×3 真跑交账

- tip／枝：`f6bc348`／`qoder/c139-tree17-cite-retry`
- 模型：openai/veritas-qwen3-14b（本机 14B；env 组同 C-134＋VERITAS_CITE_ACCEPT=1，上限默认 3）
- 墙钟：真跑合计 871.5s（assemble 汇总＝逐跑相加）

## 机制

- 挂点：`app/agents/base.py::Analyst.analyze`——分析师每轮产出在物化「前」过机器验收（`app/core/tree17_accept.py`）；只挂首轮形状（second_pass／multi_box 显式 focus 定向轮不在范围）。
- 启用条件：`VERITAS_CITE_ACCEPT=1`（默认关）＋交卷盒在场（`kg_submit_active`，测试树主线）；关旗＝生产行为与改前逐字相同。
- 失败码（零 LLM、可回放）：`empty_cite`／`out_of_box`／`anchor_miss`／`unverifiable`／`conflict_one_sided`（＋`unparsable`）。
- 打回：失败原因＋原约束追加进重写提示，资料清单不变（仍只喂盒内段）、禁金标 id；上限 attempts 默认 3（env/`cite_accept_attempts`，硬顶 5）。
- 到顶：机械剪枝丢盒外 evidence 后物化＋accounting`cite_accept[<analyst>]` 披露 `maxed_out`＋逐次失败码——不静默脏过、不死循环。
- 成对执行口径：只执行「两侧都在交卷盒内」的 conflict_pairs（与树17计划层 pair_required 同口径）；一侧不在盒＝引用面不可达，只计`unenforceable_pairs_n` 披露、不进失败码（否则必败打回循环）。

## 判定

- 总判：**YES**
- 三闸旁证：dens/leak 与 C-134 逐位同＝True；带外 0（真跑＋腿0）＝True；成对（都引或到顶披露）＝True；引用/L3 对 C-134 不掉＝True
- 打回真实发生：桩路（人造失败）＝True；真跑（真实失败）＝True；到顶披露齐全＝True

## 逐题（×3 遍）

| 案/题 | attempts（3 遍） | cited 均值(min..max) | Δcited | L3 均值 | ΔL3 | 带外 | 单边(全)/可执行/盒外披露 | 引文核对失败(3遍 vs C-134) | 到顶 |
|---|---|---|---|---|---|---|---|---|---|
| liuxiang/q_001 | [3, 3, 3] | 3.0(3..3) | 1.0 | 1.0 | 0.0 | 0 | [4, 4, 4]/[0, 0, 0]/[4, 4, 4] | [1, 1, 1] vs 0 | 是 |
| liuxiang/q_002 | [1, 1, 2] | 3.0(3..3) | 0.0 | 1.0 | 0.0 | 0 | [0, 0, 0]/[0, 0, 0]/[0, 0, 0] | [0, 0, 0] vs 0 | 否 |
| liuxiang/q_003 | [1, 1, 1] | 3.0(3..3) | 0.0 | 2.0 | 0.0 | 0 | [0, 0, 0]/[0, 0, 0]/[0, 0, 0] | [0, 0, 0] vs 0 | 否 |
| wanghong/q_001 | [1, 1, 1] | 1.0(1..1) | 0.0 | 1.0 | 0.0 | 0 | [0, 0, 0]/[0, 0, 0]/[0, 0, 0] | [0, 0, 0] vs 0 | 否 |
| wanghong/q_002 | [1, 1, 1] | 2.0(2..2) | 0.0 | 1.0 | 0.0 | 0 | [0, 0, 0]/[0, 0, 0]/[0, 0, 0] | [0, 0, 0] vs 0 | 否 |
| wanghong/q_003 | [1, 1, 1] | 1.0(1..1) | 0.0 | 1.0 | 0.0 | 0 | [0, 0, 0]/[0, 0, 0]/[0, 0, 0] | [0, 0, 0] vs 0 | 否 |

## 真实打回明细（attempts≥2 的跑次）

| 跑次 | attempts | 首轮码 | 终局码 | 过/到顶 |
|---|---|---|---|---|
| liuxiang/q_001 p1 | 3 | ['conflict_one_sided'] | ['unverifiable'] | 到顶披露 |
| liuxiang/q_001 p2 | 3 | ['conflict_one_sided'] | ['unverifiable'] | 到顶披露 |
| liuxiang/q_001 p3 | 3 | ['conflict_one_sided'] | ['unverifiable'] | 到顶披露 |
| liuxiang/q_002 p3 | 2 | ['unverifiable'] | [] | 过 |

## 腿0 零调用全路径（脚本桩）

| 案/题 | 桩1 attempts/带外 | 桩2 attempts/首码/带外 | 打回块在场 | 追加面 id 只含盒∪自错 |
|---|---|---|---|---|
| liuxiang/q_001 | 1/0 | 2/['out_of_box', 'anchor_miss']/0 | True | True |
| liuxiang/q_002 | 1/0 | 2/['out_of_box', 'anchor_miss']/0 | True | True |
| liuxiang/q_003 | 1/0 | 2/['out_of_box', 'anchor_miss']/0 | True | True |
| wanghong/q_001 | 1/0 | 2/['out_of_box', 'anchor_miss']/0 | True | True |
| wanghong/q_002 | 1/0 | 2/['out_of_box', 'anchor_miss']/0 | True | True |
| wanghong/q_003 | 1/0 | 2/['out_of_box', 'anchor_miss']/0 | True | True |

## 腿G 三闸对照 C-134（确定性面，应逐位同）

- liuxiang：equal=True deltas={'micro_gold_density': [0.5714, 0.5714], 'mean_gold_box_to_close': [1.0, 1.0], 'n_leaks': [0, 0], 'at7': [12, 12]}
- wanghong：equal=True deltas={'micro_gold_density': [0.8571, 0.8571], 'mean_gold_box_to_close': [1.0, 1.0], 'n_leaks': [0, 0]}

## 失败码（线上出现过的）

- conflict_one_sided、unverifiable

## 打回要点（现场发现）

- liuxiang/q_001 三遍全部走到顶：首轮＝可执行成对单边（support `doc_014#p1` 有、oppose `doc_002#p3` 无）→ 打回后模型补上对侧（成对修复生效）；随后两轮败于 `unverifiable`（引文非逐字）→ 到顶披露，带外仍 0。账上单边 4 条全部来自盒外成员对（`doc_012#p2/p3`，引用面不可达），与闸账 `unenforceable_pairs_n=4`分区恒等吻合（18/18 跑核对）。
- liuxiang/q_002 p3：`unverifiable` 打回 1 次 → 第 2 轮转绿（codes_final 空、final_ok=True）＝纯增益样本。
- 引文逐字核对失败（零 LLM 复算）：除 q_001 到顶披露的 1 条/遍外，其余 15 跑全 0；C-134 存档同尺对照＝全 0（其单遍本来未踩unverifiable，差异属逐跑随机，如实记）。
- 引用条数：q_001 均值 3.0 vs C-134 单遍 2（Δ+1，打回轮把对侧补进引用集的副作用）；其余 5 题 Δ0。L3 全部 Δ0（不掉、不涨）。
- dens／leak0：腿G 与 C-134 存档逐位同（0.5714/0.8571、金标→close 1.0、泄漏 0、刘翔@7=12）＝一筛／二筛／dens 公式零改动旁证。
