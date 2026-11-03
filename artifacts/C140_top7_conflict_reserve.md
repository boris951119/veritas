# C-140 交卷硬 Top-7＋冲突成对保位——交账

- tip／枝：`e2ff20e85f57852f52f847dc9af474ad696aa0a9`／`qoder/c140-top7-conflict-reserve`
- 一行：YES｜final_n=li001:9/li002:7/li003:7/wa001:7/wa002:7/wa003:7（保位合计2）｜dens/leak=逐位｜带外face=0｜金标face 10→14(cut_gold=8)｜L3 8 vs 7｜tip e2ff20e／qoder/c140-top7-conflict-reserve

## 判表（件② 五闸）

- 闸① final_n 回放（无对≤7、有对保位可回放）：True
- 闸② dens／leak 逐位对 C-134＋真跑带外(face)=0：True
- 闸③ 金标评测臂 face 金标 after≥before（锚逐题True）：True
- 闸④ 关旗回退（focus 序逐位＋face sha 逐位＋无 submit_top7 键）：True
- 旁证：盒 rank_order／tree17_cite 逐位不动＝True
- 闸⑤ pytest 不新增红：见交付行（探针外独立跑）

## 腿0 镜像（六题；id／计数／sha8；零表格）

- liuxiang/q_001：候选 27｜k_top 7｜保位 2｜final_n 9｜off面 BYTE_IDENTICAL｜金标 before 1 → after 3｜裁掉含金标 1｜盒内被裁 0（含金标 0）｜replay True
- liuxiang/q_002：候选 23｜k_top 7｜保位 0｜final_n 7｜off面 BYTE_IDENTICAL｜金标 before 1 → after 2｜裁掉含金标 1｜盒内被裁 0（含金标 0）｜replay True
- liuxiang/q_003：候选 27｜k_top 7｜保位 0｜final_n 7｜off面 BYTE_IDENTICAL｜金标 before 2 → after 3｜裁掉含金标 2｜盒内被裁 0（含金标 0）｜replay True
- wanghong/q_001：候选 25｜k_top 7｜保位 0｜final_n 7｜off面 BYTE_IDENTICAL｜金标 before 1 → after 1｜裁掉含金标 1｜盒内被裁 0（含金标 0）｜replay True
- wanghong/q_002：候选 28｜k_top 7｜保位 0｜final_n 7｜off面 BYTE_IDENTICAL｜金标 before 2 → after 2｜裁掉含金标 1｜盒内被裁 0（含金标 0）｜replay True
- wanghong/q_003：候选 25｜k_top 7｜保位 0｜final_n 7｜off面 BYTE_IDENTICAL｜金标 before 3 → after 3｜裁掉含金标 2｜盒内被裁 0（含金标 0）｜replay True

- 金标 face 合计：before 10 → after 14；裁掉段含金标 8 条（逐题 cut_gold_ids 在 json 回放）

## 腿1 14B 真跑（六题；门控 env 组同 C-134）

- liuxiang/q_001：L3 1/4｜cited 3｜final_n 9(+2)｜带外face 0｜带外box 0｜核对失败 2｜墙钟 52.9s
- liuxiang/q_002：L3 1/5｜cited 5｜final_n 7(+0)｜带外face 0｜带外box 3｜核对失败 3｜墙钟 62.4s
- liuxiang/q_003：L3 3/5｜cited 5｜final_n 7(+0)｜带外face 0｜带外box 3｜核对失败 4｜墙钟 62.2s
- wanghong/q_001：L3 0/5｜cited 3｜final_n 7(+0)｜带外face 0｜带外box 3｜核对失败 0｜墙钟 40.8s
- wanghong/q_002：L3 2/5｜cited 3｜final_n 7(+0)｜带外face 0｜带外box 0｜核对失败 0｜墙钟 62.3s
- wanghong/q_003：L3 1/9｜cited 2｜final_n 7(+0)｜带外face 0｜带外box 1｜核对失败 0｜墙钟 27.3s

- L3 合计：新 8 vs C-134 基线 7（单跑单臂，逐跑噪声未量——按 10-28 纪律不据此说涨分；交叉读数看离线 face 金标）

## 诚实披露

- final_n 上限：保位不设硬顶（工单「可变成 8／9…」按字面实现），逐题真数见 final_n_rows；超 9 的题在此注明——
- 超 9 题：无
- dens 公式／pack 系数／MULTI_BOX 默认零改动；盒 rank_order 与 tree17_cite 逐位不动（旁证闸）
- 真跑带外按两个口径记：对 final face（提示词只许名单内，应为 0）与对盒 rank_order（保位段引用会落在盒外，逐题披露）
- 金标只活在量尺（本探针与 artifact），生产 submit_top7 accounting 零金标、过 audit_forbidden_keys
- 候选池＝kg_test_tree.rerank_order（C-140 起随 ensure_test_tree_submit 落账；序尾补盒内缺员）；缺席回退 rank_order（candidates_source 披露）
