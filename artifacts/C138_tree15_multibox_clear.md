# C-138 树15 满箱 → 续盒验通收红标（交账）

- tip／枝：`f6bc348`／`qoder/c138-tree15-multibox-clear`
- 出厂：test_tree_line=True、multi_box=True、multi_box_max=3；零密度桥；本机 14B（真跑腿）；零现金

## 一行结论

**YES｜lost(窄面)=0、lost(溢出)=20269｜满箱样本=有 18 题｜续盒触发=6/6 题（墙钟 ≈6-8×＝续盒税真数）｜C-134 旁证 dens/leak 逐位、带外0｜tip f6bc348／qoder/c138-tree15-multibox-clear**

## 四闸

- 闸① 满箱/构造：production_fullbox 过（）
- 闸② 构造超窗 lost=0：过（lost=0；边界题（宇宙>三箱）lost=92＝诚实披露，续盒只承诺到 max_boxes）
- 闸③ C-134 旁证不掉：过（dens/leak 逐位等证=True；先箱 L3 合计 7→5（披露，不硬闸）；带外非零 0）
- 闸④ 关旗回退可测：过（VERITAS_MULTI_BOX=0 ⇒ 无 multi_box 账、lost=全部 excluded）

## 逐题生产镜像（腿0；A_on＝出厂主线）

- liuxiang/q_001：预算=11763 总=362 装箱=87 excluded=275 箱数=3 并集=223 lost(溢出)=139 lost(窄面)=0
- liuxiang/q_002：预算=11460 总=362 装箱=88 excluded=274 箱数=3 并集=237 lost(溢出)=125 lost(窄面)=0
- liuxiang/q_003：预算=12066 总=362 装箱=90 excluded=272 箱数=3 并集=246 lost(溢出)=116 lost(窄面)=0
- wanghong/q_001：预算=11617 总=614 装箱=71 excluded=543 箱数=3 并集=194 lost(溢出)=420 lost(窄面)=0
- wanghong/q_002：预算=12783 总=614 装箱=91 excluded=523 箱数=3 并集=229 lost(溢出)=385 lost(窄面)=0
- wanghong/q_003：预算=12842 总=614 装箱=78 excluded=536 箱数=3 并集=221 lost(溢出)=393 lost(窄面)=0
- us_cn_ai/q_001：预算=14318 总=582 装箱=75 excluded=507 箱数=3 并集=227 lost(溢出)=355 lost(窄面)=0
- us_cn_ai/q_002：预算=14897 总=582 装箱=83 excluded=499 箱数=3 并集=256 lost(溢出)=326 lost(窄面)=0
- us_cn_ai/q_003：预算=14960 总=582 装箱=59 excluded=523 箱数=3 并集=187 lost(溢出)=395 lost(窄面)=0
- ai171/q_001：预算=9237 总=1386 装箱=104 excluded=1282 箱数=3 并集=280 lost(溢出)=1106 lost(窄面)=0
- ai171/q_002：预算=10321 总=1386 装箱=99 excluded=1287 箱数=3 并集=298 lost(溢出)=1088 lost(窄面)=0
- ai171/q_003：预算=9192 总=1386 装箱=140 excluded=1246 箱数=3 并集=296 lost(溢出)=1090 lost(窄面)=0
- kh_th/q_001：预算=10499 总=743 装箱=72 excluded=671 箱数=3 并集=200 lost(溢出)=543 lost(窄面)=0
- kh_th/q_002：预算=11110 总=743 装箱=66 excluded=677 箱数=3 并集=196 lost(溢出)=547 lost(窄面)=0
- kh_th/q_003：预算=11273 总=743 装箱=75 excluded=668 箱数=3 并集=212 lost(溢出)=531 lost(窄面)=0
- jilong/q_001：预算=9161 总=4507 装箱=115 excluded=4392 箱数=3 并集=289 lost(溢出)=4218 lost(窄面)=0
- jilong/q_002：预算=8031 总=4507 装箱=128 excluded=4379 箱数=3 并集=289 lost(溢出)=4218 lost(窄面)=0
- jilong/q_003：预算=10935 总=4507 装箱=87 excluded=4420 箱数=3 并集=233 lost(溢出)=4274 lost(窄面)=0

## 续盒轨迹（真跑腿 multibox 形状）

- liuxiang/q_001：mb=ok（None）箱数=3 L3 先箱=1/4→续盒后=1 墙钟=247.5s
- liuxiang/q_002：mb=ok（None）箱数=3 L3 先箱=0/5→续盒后=1 墙钟=316.8s
- liuxiang/q_003：mb=ok（None）箱数=3 L3 先箱=1/5→续盒后=2 墙钟=271.7s
- wanghong/q_001：mb=ok（None）箱数=3 L3 先箱=1/5→续盒后=2 墙钟=229.1s
- wanghong/q_002：mb=ok（None）箱数=3 L3 先箱=1/5→续盒后=4 墙钟=306.3s
- wanghong/q_003：mb=ok（None）箱数=3 L3 先箱=1/9→续盒后=4 墙钟=245.2s

## 诚实披露

- 续盒税＝每箱非正文开销（人设/议题/纪律块重复发送）＋续盒自身研判墙钟；C-66 历史旁证＝三盒 ≈2.87×；本批真跑 6/6 题触发续盒（3 箱），单题墙钟 229～317s ≈ C-134 同题 6～8×＝续盒税现场真数。
- L2 并集到达 ≠ 官方涨分；末箱归并未接（树上已标）；宇宙 > max_boxes×预算的溢出段仍不可达（边界题实测，账内披露）。
- 交卷窄面段经由焦点强制入选（render_segments_block 绕过装箱）到达，与续盒机制正交；lost(窄面) 恒 0 由构造保证并逐题复核。

