# C-137 树17 排名加权细读＋硬约束（交账）

- tip／枝：`f6bc348`／`qoder/c137-tree17-rank-weight`
- 模型：openai/veritas-qwen3-14b；温度未钉（与 C-120/C-130/C-134 同口径）；嵌入＝本机 bge-m3 暖缓存（.kgcache，按 para_id 复用）
- env：不设 VERITAS_TEST_TREE_LINE（出厂开）；REVIEW_BOOST 显式 0（门控基线同组）；VERITAS_TREE17_RANK_WEIGHT 出厂开；VERITAS_TREE17_HEAD_TIER∈{3,5}

## 一行结论

**NO｜安全四闸全过（盒 identity／带外0／成对计划层 both_close／dens·leak 逐位持平）｜L3 合计 7→7（引用 12→13，逐题零动）｜病因＝六题盒长全≤H，注意力分层无梯度可作用（12/12 形状全盒 close）｜tip f6bc348／qoder/c137-tree17-rank-weight**

## 四闸

- 闸0 盒 identity／focus 序／关旗 face 字节等证：过（box True、focus True、face_off True；六题全查）
- 闸1 带外引用＝0：过（12 跑次、非零 0）
- 闸2 成对两边进细读：过（计划层形状全 both_close；真跑 one_sided 回归＝True）
- 闸3 L3／引用（H=3）：合计 L3 7→7；引用条数 12→13（逐题旧→新见下表；未明显抬＝闸③不过）
- 闸3 L3／引用（H=5）：合计 L3 7→7；引用条数 12→13（逐题旧→新见下表；未明显抬＝闸③不过）
- 病因读数：盒长≤H 的题＝全盒 close、n_scan=0：分层无梯度可作用（权重面退化为装饰，只剩硬约束文字面）（本批 12/12 形状全盒 close；H=3 与 H=5 两臂读数逐位相同即此故）
- 闸4 dens／@7／leak0：过 liuxiang @7 12→12 micro 0.5714→0.5714 leak 0； wanghong @7 6→6 micro 0.8571→0.8571 leak 0

## 逐题 L3／引用（旧＝C-134 → 新＝本单真跑）

- H=3｜liuxiang/q_001｜L3 1→1/4｜引用 2→3｜核对失败 0→1｜墙钟 54.2s
- H=3｜liuxiang/q_002｜L3 1→1/5｜引用 3→3｜核对失败 0→0｜墙钟 35.5s
- H=3｜liuxiang/q_003｜L3 2→2/5｜引用 3→3｜核对失败 0→0｜墙钟 36.5s
- H=3｜wanghong/q_001｜L3 1→1/5｜引用 1→1｜核对失败 0→0｜墙钟 20.5s
- H=3｜wanghong/q_002｜L3 1→1/5｜引用 2→2｜核对失败 0→0｜墙钟 37.0s
- H=3｜wanghong/q_003｜L3 1→1/9｜引用 1→1｜核对失败 0→0｜墙钟 19.2s
- H=5｜liuxiang/q_001｜L3 1→1/4｜引用 2→3｜核对失败 0→1｜墙钟 33.5s
- H=5｜liuxiang/q_002｜L3 1→1/5｜引用 3→3｜核对失败 0→0｜墙钟 32.4s
- H=5｜liuxiang/q_003｜L3 2→2/5｜引用 3→3｜核对失败 0→0｜墙钟 33.3s
- H=5｜wanghong/q_001｜L3 1→1/5｜引用 1→1｜核对失败 0→0｜墙钟 21.1s
- H=5｜wanghong/q_002｜L3 1→1/5｜引用 2→2｜核对失败 0→0｜墙钟 37.5s
- H=5｜wanghong/q_003｜L3 1→1/9｜引用 1→1｜核对失败 0→0｜墙钟 19.2s

## 注意力面形状（腿0，H=3／H=5）

- liuxiang/q_001 H=3：close 3／scan 0；成对 4/4 both_close；强制升级 0 段
- liuxiang/q_001 H=5：close 3／scan 0；成对 4/4 both_close；强制升级 0 段
- liuxiang/q_002 H=3：close 3／scan 0；成对 0/0 both_close；强制升级 0 段
- liuxiang/q_002 H=5：close 3／scan 0；成对 0/0 both_close；强制升级 0 段
- liuxiang/q_003 H=3：close 3／scan 0；成对 0/0 both_close；强制升级 0 段
- liuxiang/q_003 H=5：close 3／scan 0；成对 0/0 both_close；强制升级 0 段
- wanghong/q_001 H=3：close 1／scan 0；成对 0/0 both_close；强制升级 0 段
- wanghong/q_001 H=5：close 1／scan 0；成对 0/0 both_close；强制升级 0 段
- wanghong/q_002 H=3：close 3／scan 0；成对 0/0 both_close；强制升级 0 段
- wanghong/q_002 H=5：close 3／scan 0；成对 0/0 both_close；强制升级 0 段
- wanghong/q_003 H=3：close 3／scan 0；成对 0/0 both_close；强制升级 0 段
- wanghong/q_003 H=5：close 3／scan 0；成对 0/0 both_close；强制升级 0 段

## 权重键（可迁移）

- rank 档（细读=前 H 名，权重 1.0−0.15×(rank−1)，地板 0.2）；
- 是否冲突边（成对强制进细读，留痕 pair_forced_ids）；
- 是否可核验钉（时间／数额钉 +0.05，封顶 1.0）；
- 权重只进 surface.tree17.attention 与分析师提示词；整面过 audit_forbidden_keys；盒／一筛／二筛系数零改动。

