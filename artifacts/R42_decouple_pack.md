# R42 — 门槛③：低耦合拆装（禁整套系数进 pack_material）

> 接 R40／R41。stage1＝进池；stage2＝少而密＋conflict_pairs；交卷＝rank＋树17信号。

## 结论先行

- 门槛③：**过**（零系数泄漏；交卷只带 rank／pairs／树17；密度＋引用计划不回退）。
- 密度：王虹 71%／柬泰 80%／AI171 80%；刘翔@7=12。
- 引用：计划层金标→细读全 1.0；R41 holdout 可用密度均值冻结 37%（盒不变不重跑 14B）。
- 泄漏审计：0 次；submit 题级全过=True。

墙钟 90.5s。本机嵌入；禁百炼；系数未改（无需 ±0.08 重拟合）。
门槛③判定：**过**。

## 接口／模块边界

1. **stage1_pool**：`fuse_r19`＋`evaluate(coeff)` 只在层内；出口 `stage1_pool_export` → `pool_ids`。
2. **stage2_box**：`authority_rerank`＋`density_constrained_submit`；出口 `box_ids`／`k`／洗净的 `conflict_pairs`。
3. **submit**：`build_submit_surface` → `rank_order`＋`conflict_pairs`＋`tree17`（细读 id／成对／标签）。
4. **主线接法**：`pack_hints_from_submit` → `priority_segment_ids`／`focus_segment_ids`／`max_segments`；`pack_material` **不接受** coeff／feats／weights（见 `FORBIDDEN_PACK_KEYS`）。
5. 现有 `slices.pack_selected_for_question` 仍只拿主线 BM25 宇宙，与实验系数无关。

## 密度回归（门槛①）

| 案 | 角色 | R40微密度 | R42微密度 | Δ | R40@7 | R42@7 | ≥2/3 |
|---|---|---:|---:|---:|---:|---:|:---:|
| liuxiang | regression | 57% | 57% | +0% | 12 | 12 | — |
| jilong | smoke | 67% | 67% | +0% | 6 | 6 | — |
| us_cn_ai | smoke | 67% | 67% | +0% | 6 | 6 | — |
| wanghong | holdout | 71% | 71% | +0% | 5 | 5 | ✓ |
| kh_th | holdout | 80% | 80% | +0% | 4 | 4 | ✓ |
| ai171 | holdout | 80% | 80% | +0% | 5 | 5 | ✓ |

## 引用回归（门槛②）

本轮不重跑 14B 分析师；盒密度与 R40／R41 对齐 ⇒ 树17 输入面不变。
计划层 `gold_box_to_close` 现场复测；可用引用密度沿用 R41 冻结读数。

| 案 | 角色 | R41全合规 | R41可用密度 | R42计划金标→细读 | 盒密度守 |
|---|---|---:|---:|---:|:---:|
| liuxiang | regression | 3/3 | 29% | 100% | ✓ |
| jilong | smoke | 3/3 | 56% | 100% | ✓ |
| us_cn_ai | smoke | 3/3 | 33% | 100% | ✓ |
| wanghong | holdout | 3/3 | 0% | 100% | ✓ |
| kh_th | holdout | 3/3 | 67% | 100% | ✓ |
| ai171 | holdout | 3/3 | 44% | 100% | ✓ |

## 拆装审计

- 交卷／hints 系数泄漏次数：**0**
- 题级 submit 全过：✓
- pack_material 禁键集合：`coeff, coeffs, feats, feature_vector, features, multidim, names, portable_authority_weights, …`

## 可借鉴清单（挂层＋主线接法）

- **可变 k＋密度约束（TARGET≥2/3，k∈[3,7]）** — 层=`stage2／density_submit`；模块=`app/kg_lab/density_submit.py::density_constrained_submit`；主线：交卷只带 rank_order＋k；主线可用 max_segments=k 或 priority_segment_ids=rank_order；勿把密度扫描系数塞进 pack_material
- **conflict_pairs（support vs oppose 成对）** — 层=`stage2／authority_rerank 出口`；模块=`app/kg_lab/stage2_authority.py::build_conflict_pairs`；主线：SubmitSurface.conflict_pairs → 报告冲突节／质证；装箱只消费 id，不消费权威权重
- **通稿／近同文簇 keep-one（抗挤）** — 层=`stage2／density_submit 簇内代表`；模块=`app/kg_lab/density_submit.py::_cluster_wire_keep_one`；主线：留在二筛；主线 pack_material 已有 duplicate_map，勿再灌实验簇系数；接盒结果即可
- **繁简对照折叠（近同判定用，不改原文）** — 层=`stage2／density_submit 指纹归一`；模块=`app/kg_lab/density_submit.py::_TRAD_TO_SIMP`；主线：属二筛簇判据；主线若复用只进近同检测，不进 pack 参数面
- **树17 引用纪律（细读带宽／成对／采信·对立标签）** — 层=`submit／L3（盒后）`；模块=`app/kg_lab/tree17_cite.py::apply_tree17_cite / attach_tree17_plan`；主线：accounting['tree17_cite']＋focus_segment_ids=close_read；提示词注入，零改 pack_material 签名
- **一筛多维系数（R9／R21）** — 层=`stage1_pool 内部`；模块=`app/kg_lab/r8_fit.py::evaluate + r21_coeff`；主线：系数只活在一筛打分；出口仅 pool_ids。若动系数须整套重拟合 ±0.08；禁止整包进 pack_material
- **二筛权威权重（DEFAULT_WEIGHTS）** — 层=`stage2 内部 portable_authority_unit`；模块=`app/kg_lab/stage2_authority.py::DEFAULT_WEIGHTS`；主线：权重只服务盒内裁决；交卷只留 rank／pairs。主线接盒序，不接 weights dict

## 验收闸

- 门槛① holdout ≥2/3：✓（3/3）
- 密度相对 R40 不掉（≤2%）：✓
- 刘翔 @7≥11：✓（12）
- 引用计划层金标→细读全 1.0：✓
- R41 可用密度冻结可读：✓（holdout 均值 37%）
- 零系数泄漏进交卷／pack hints：✓
- 门槛③：✓ 过

## 路径
- `app/kg_lab/layer_boundary.py`
- `tests/test_r42_layer_boundary.py`
- `artifacts/R42_decouple_pack.json`
- `artifacts/R42_decouple_pack.md`
