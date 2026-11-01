# C-110 一筛池 vs R44 手工盒落差（只读诊断）

> 墙钟 15.6s；禁百炼；禁 R9／权重进 pack；本枝不合 main。
> 三路：A＝C-108+R44短盒；B＝C-109一筛池；C＝旗关纯装箱。

## 结论

**明确下一刀＝先回灌短盒（或等价：把密度盒／priority 头拉回 k≈7 且保金），不是先修系数。**

全卷桶：miss_gold_pool=4／pool_dilute=10／density_squeeze=16／submit_narrow_drop=0／role_cluster_kill=13。  
B 路 dens_k 常缩到 1～3（R44 盒 k 多为 7），金标多数**已进 180 池**却进不了短密度盒，priority 用池序补到 7 时池头又不够金 → @7 塌。

- 刘翔@7：A=12／B=4／C≈1（门槛对照≥11）——**可复现**
- holdout L2：A=29／B=25／C=25（分母 59）——B≡C，A 多出的 +4 全靠 R44 短盒
- 泄漏合计=0
- **若坚持「不再依赖手工 R44 盒」**：必须先把一筛池头（金标@7／@15）抬上去，否则只改 dens 仍吃稀池；**系数／R9 仍禁止进 pack**
- **更快对齐 C-108 尺**：保底回灌短盒（kind=`rehydrate_box`）——本诊断默认荐这条作下一交付刀

## 三路对照

slug/qid | role | denom | C_L2 | B_L2 | A_L2 | ΔA−B | B_pool_n | gold∈pool | @50 | @7池 | B_dens_k | B_box金 | A@7 | B@7 | microB/R44
---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---
liuxiang/q_001 | regression | 4 | 4 | 4 | 4 | +0 | 180 | 4 | 4 | 1 | 3 | 0 | 4 | 1 | 0.0/0.5714
liuxiang/q_002 | regression | 5 | 3 | 3 | 5 | +2 | 180 | 4 | 2 | 1 | 3 | 0 | 4 | 1 | 0.0/0.5714
liuxiang/q_003 | regression | 5 | 2 | 2 | 4 | +2 | 180 | 5 | 2 | 2 | 3 | 1 | 4 | 2 | 0.3333/0.5714
wanghong/q_001 | holdout | 5 | 2 | 2 | 2 | +0 | 180 | 4 | 3 | 0 | 1 | 1 | 1 | 1 | 1.0/1.0
wanghong/q_002 | holdout | 5 | 2 | 2 | 2 | +0 | 180 | 5 | 3 | 1 | 3 | 1 | 2 | 1 | 0.3333/0.6667
wanghong/q_003 | holdout | 9 | 3 | 3 | 3 | +0 | 180 | 5 | 1 | 1 | 3 | 0 | 3 | 1 | 0.0/1.0
kh_th/q_001 | holdout | 5 | 1 | 1 | 1 | +0 | 180 | 1 | 0 | 0 | 3 | 0 | 1 | 0 | 0.0/1.0
kh_th/q_002 | holdout | 6 | 1 | 1 | 3 | +2 | 180 | 1 | 1 | 0 | 3 | 0 | 2 | 0 | 0.0/0.6667
kh_th/q_003 | holdout | 5 | 5 | 5 | 5 | +0 | 180 | 5 | 2 | 1 | 3 | 0 | 2 | 1 | 0.0/1.0
ai171/q_001 | holdout | 7 | 3 | 3 | 4 | +1 | 180 | 7 | 0 | 0 | 3 | 0 | 2 | 0 | 0.0/0.6667
ai171/q_002 | holdout | 11 | 4 | 4 | 5 | +1 | 180 | 5 | 3 | 1 | 1 | 0 | 1 | 1 | 0.0/1.0
ai171/q_003 | holdout | 6 | 4 | 4 | 4 | +0 | 180 | 6 | 3 | 1 | 3 | 0 | 1 | 0 | 0.0/1.0

## 刘翔专项（@7 从 ≥11→低的丢段）

### liuxiang/q_001  A@7=4 B@7=1 C≈1  denom=4
- 金标段：doc_002#p3, doc_024#p1, doc_025#p6, doc_035#p7
- R44 盒金标 4/4：doc_002#p3, doc_024#p1, doc_025#p6, doc_035#p7
- 一筛池 n=180；金标入池 4/4 （@50=4 @7=1）
- 金标池位次：doc_002#p3→18, doc_024#p1→5, doc_025#p6→25, doc_035#p7→22
- 密度盒 dens_k=3 盒内金标=∅；micro B=0.0 vs R44=0.5714
- A@7 金标：doc_002#p3, doc_024#p1, doc_025#p6, doc_035#p7
- B@7 金标：doc_024#p1
- A→B @7 丢失：doc_002#p3, doc_025#p6, doc_035#p7
  - `doc_002#p3`：入池=True rank=18 入密度盒=False 在R44盒=True 桶=density_squeeze
  - `doc_025#p6`：入池=True rank=25 入密度盒=False 在R44盒=True 桶=density_squeeze
  - `doc_035#p7`：入池=True rank=22 入密度盒=False 在R44盒=True 桶=density_squeeze

### liuxiang/q_002  A@7=4 B@7=1 C≈0  denom=5
- 金标段：doc_002#p3, doc_009#p5, doc_028#p1, doc_029#p7, doc_051#p3
- R44 盒金标 4/5：doc_002#p3, doc_009#p5, doc_029#p7, doc_051#p3
- 一筛池 n=180；金标入池 4/5 （@50=2 @7=1）
- 金标池位次：doc_002#p3→MISS, doc_009#p5→30, doc_028#p1→4, doc_029#p7→138, doc_051#p3→55
- 密度盒 dens_k=3 盒内金标=∅；micro B=0.0 vs R44=0.5714
- A@7 金标：doc_002#p3, doc_009#p5, doc_029#p7, doc_051#p3
- B@7 金标：doc_028#p1
- A→B @7 丢失：doc_002#p3, doc_009#p5, doc_029#p7, doc_051#p3
  - `doc_002#p3`：入池=False rank=None 入密度盒=False 在R44盒=True 桶=miss_gold_pool+role_cluster_kill
  - `doc_009#p5`：入池=True rank=30 入密度盒=False 在R44盒=True 桶=density_squeeze
  - `doc_029#p7`：入池=True rank=138 入密度盒=False 在R44盒=True 桶=pool_dilute+density_squeeze+role_cluster_kill
  - `doc_051#p3`：入池=True rank=55 入密度盒=False 在R44盒=True 桶=pool_dilute+density_squeeze+role_cluster_kill

### liuxiang/q_003  A@7=4 B@7=2 C≈0  denom=5
- 金标段：doc_002#p3, doc_006#p3, doc_012#p5, doc_033#p5, doc_033#p6
- R44 盒金标 4/5：doc_002#p3, doc_006#p3, doc_012#p5, doc_033#p5
- 一筛池 n=180；金标入池 5/5 （@50=2 @7=2）
- 金标池位次：doc_002#p3→139, doc_006#p3→1, doc_012#p5→7, doc_033#p5→141, doc_033#p6→145
- 密度盒 dens_k=3 盒内金标=doc_006#p3；micro B=0.3333 vs R44=0.5714
- A@7 金标：doc_002#p3, doc_006#p3, doc_012#p5, doc_033#p5
- B@7 金标：doc_006#p3, doc_012#p5
- A→B @7 丢失：doc_002#p3, doc_033#p5
  - `doc_002#p3`：入池=True rank=139 入密度盒=False 在R44盒=True 桶=pool_dilute+density_squeeze+role_cluster_kill
  - `doc_033#p5`：入池=True rank=141 入密度盒=False 在R44盒=True 桶=pool_dilute+density_squeeze+role_cluster_kill

## holdout 摘要（A 有而 B 丢的 @7 金标）

- wanghong/q_002: L2 A=2 B=2 C=2；池金标 5/5 dens_k=3；@7丢 doc_011#p1；未入池 ∅；入池未进盒 doc_011#p1, doc_011#p2, doc_011#p3, doc_011#p6
- wanghong/q_003: L2 A=3 B=3 C=3；池金标 5/9 dens_k=3；@7丢 doc_003#p5, doc_007#p2；未入池 doc_003#p7, doc_007#p3, doc_012#p7, doc_023#p2；入池未进盒 doc_003#p3, doc_003#p4, doc_003#p5, doc_007#p1, doc_007#p2
- kh_th/q_001: L2 A=1 B=1 C=1；池金标 1/5 dens_k=3；@7丢 doc_027#p2；未入池 doc_008#p11, doc_009#p10, doc_009#p11, doc_009#p12；入池未进盒 doc_027#p2
- kh_th/q_002: L2 A=3 B=1 C=1；池金标 1/6 dens_k=3；@7丢 doc_006#p4, doc_009#p10；未入池 doc_006#p4, doc_009#p10, doc_009#p12, doc_014#p3, doc_017#p4；入池未进盒 doc_021#p2
- kh_th/q_003: L2 A=5 B=5 C=5；池金标 5/5 dens_k=3；@7丢 doc_007#p7；未入池 ∅；入池未进盒 doc_007#p7, doc_023#p2, doc_023#p4, doc_024#p1, doc_024#p2
- ai171/q_001: L2 A=4 B=3 C=3；池金标 7/7 dens_k=3；@7丢 doc_001#p3, doc_015#p5；未入池 ∅；入池未进盒 doc_001#p3, doc_002#p8, doc_005#p3, doc_007#p3, doc_009#p14, doc_012#p8, doc_015#p5
- ai171/q_002: L2 A=5 B=4 C=4；池金标 5/11 dens_k=1；@7丢 doc_015#p6；未入池 doc_010#p9, doc_013#p3, doc_013#p8, doc_015#p1, doc_015#p6, doc_016#p19；入池未进盒 doc_006#p3, doc_007#p3, doc_011#p2, doc_012#p8, doc_020#p30
- ai171/q_003: L2 A=4 B=4 C=4；池金标 6/6 dens_k=3；@7丢 doc_004#p3；未入池 ∅；入池未进盒 doc_004#p3, doc_004#p6, doc_004#p8, doc_004#p9, doc_005#p4, doc_005#p7

## 桶说明

- `miss_gold_pool`：金标根本没进 stage1 pool_ids
- `pool_dilute`：进了池但位次很靠后（>50）
- `density_squeeze`：在池内却没进密度盒（短 dens_k 挤出）
- `submit_narrow_drop`：进了密度盒但没进 @7 priority 头
- `role_cluster_kill`：R44 盒里有、一筛却漏／很远（角色／通稿簇启发式）

