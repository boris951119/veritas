# C-111 短盒回灌测量（rehydrate_box）

> 墙钟 16.2s；禁百炼；禁 R9／权重进 pack；过线 YES — {'leaks_zero': True, 'liuxiang_at7_ge_11': True, 'holdout_ge_c108': True}
> 对照：A＝外仓 R44 盒；B＝C-111 默认回灌；C＝回灌关（C-109）。
> C-108 holdout_on 门槛＝29

## 结论

- 刘翔@7：A=12／B=12／C=4（门槛 B≥11）
- holdout L2：A=29／B=29／C=25（分母 59；门槛 B≥29）
- 泄漏=0
- 合入建议：可建议合 main

## 三路对照（对齐 C-110 表）

slug/qid | role | denom | C_L2 | B_L2 | A_L2 | C@7 | B@7 | A@7 | B_seed | B_dens_k | C_dens_k | microB/R44
---|---|---|---|---|---|---|---|---|---|---|---|---
liuxiang/q_001 | regression | 4 | 4 | 4 | 4 | 1 | 4 | 4 | True | 7 | 3 | 0.5714/0.5714
liuxiang/q_002 | regression | 5 | 3 | 5 | 5 | 1 | 4 | 4 | True | 7 | 3 | 0.5714/0.5714
liuxiang/q_003 | regression | 5 | 2 | 4 | 4 | 2 | 4 | 4 | True | 7 | 3 | 0.5714/0.5714
wanghong/q_001 | holdout | 5 | 2 | 2 | 2 | 1 | 1 | 1 | True | 1 | 1 | 1.0/1.0
wanghong/q_002 | holdout | 5 | 2 | 2 | 2 | 1 | 2 | 2 | True | 3 | 3 | 0.6667/0.6667
wanghong/q_003 | holdout | 9 | 3 | 3 | 3 | 1 | 3 | 3 | True | 3 | 3 | 1.0/1.0
kh_th/q_001 | holdout | 5 | 1 | 1 | 1 | 0 | 1 | 1 | True | 1 | 3 | 1.0/1.0
kh_th/q_002 | holdout | 6 | 1 | 3 | 3 | 0 | 2 | 2 | True | 3 | 3 | 0.6667/0.6667
kh_th/q_003 | holdout | 5 | 5 | 5 | 5 | 1 | 2 | 2 | True | 1 | 3 | 1.0/1.0
ai171/q_001 | holdout | 7 | 3 | 4 | 4 | 0 | 2 | 2 | True | 3 | 3 | 0.6667/0.6667
ai171/q_002 | holdout | 11 | 4 | 5 | 5 | 1 | 1 | 1 | True | 1 | 1 | 1.0/1.0
ai171/q_003 | holdout | 6 | 4 | 4 | 4 | 0 | 1 | 1 | True | 1 | 3 | 1.0/1.0

## 回退

- `VERITAS_KG_REHYDRATE_BOX=0` → C-109（一筛池→短 dens_k，无冻结盒）
- 有上游短盒仍优先于种子／垫 k
- 系数仍隔离；交付只多短盒回灌窄面

