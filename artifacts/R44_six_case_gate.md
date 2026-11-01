# R44 — 本地六案全测核对＋并主线交付包

> 接 R43／R42。金标＝supporting_facts（含 partial）。本机嵌入＋树17读数复用注明；禁百炼。

## 结论先行

- 六案现场密度：王虹 **86%**（q_002 **67%**）／柬泰 80%／AI171 80%；刘翔@7=**12**；冒烟各 67%。
- 树17：计划层金标→细读全 1.0；可用密度复用 R41／R43（王虹 0%）。
- 窄面泄漏：**0**；门槛①②③＝✓✓✓。
- 并主线：可借鉴接入（勿整包灌系数）。

墙钟 185.7s。复测基线 tip `9743fbd`（R43）；本提交追加 R44 报告／脚本。
门槛① `✓`　门槛② `✓`　门槛③ `✓`　并主线建议：`可借鉴接入`.

## 六案盒密度（现场复测）

| 案 | 角色 | 期望微密度 | R44微密度 | Δ | @7 | 期望@7 | 分题密度 | 闸 |
|---|---|---:|---:|---:|---:|---:|---|:---:|
| liuxiang | regression | 57% | 57% | +0% | 12 | 12 | q_001=57%,q_002=57%,q_003=57% | ✓ |
| jilong | smoke | 67% | 67% | +0% | 6 | 6 | q_001=67%,q_002=67%,q_003=67% | ✓ |
| us_cn_ai | smoke | 67% | 67% | +0% | 6 | 6 | q_001=67%,q_002=67%,q_003=67% | ✓ |
| wanghong | holdout | 86% | 86% | +0% | 6 | 6 | q_001=100%,q_002=67%,q_003=100% | ✓ |
| kh_th | holdout | 80% | 80% | +0% | 4 | 4 | q_001=100%,q_002=67%,q_003=100% | ✓ |
| ai171 | holdout | 80% | 80% | +0% | 5 | 5 | q_001=67%,q_002=100%,q_003=100% | ✓ |

王虹 q_002：期望≥67%，实测 **67%**（2/3） ✓。

## 树17 引用合规／可用密度

分析师可用密度：重叠案复用 **R41**；王虹复用 **R43**（盒已相对 R41 变，但 R43 已重跑 14B＝0%）。
本轮另做计划层 `gold_box_to_close` 现场复测（无 LLM）。

| 案 | 角色 | 合规读数来源 | 全合规 | 可用密度 | 计划金标→细读 | 注 |
|---|---|---|---:|---:|---:|---|
| liuxiang | regression | R41 | 3/3 | 29% | 100% | 复用 |
| jilong | smoke | R41 | 3/3 | 56% | 100% | 复用 |
| us_cn_ai | smoke | R41 | 3/3 | 33% | 100% | 复用 |
| wanghong | holdout | R43 | 3/3 | 0% | 100% | R43 重跑 14B |
| kh_th | holdout | R41 | 3/3 | 67% | 100% | 复用 |
| ai171 | holdout | R41 | 3/3 | 44% | 100% | 复用 |

## 交卷窄面零系数泄漏抽检

- 六案合计泄漏路径数：**0** ✓
- submit／pack_hints 题级全过：✓
- 禁键：`coeff, coeffs, feats, feature_vector, features, multidim, names, portable_authority_weights, …`

## 门槛①②③结论

- 门槛①（holdout≥2/3＋回归／冒烟不掉＋刘翔@7=12）：✓
- 门槛②（树17合规可读＋计划层金标→细读全 1.0；可用密度不强制抬）：✓
- 门槛③（交卷窄面零系数泄漏；禁整套系数进 pack_material）：✓

## 可借鉴清单终稿（并主线：只借鉴、先不整包）

> 据 `artifacts/R42_decouple_pack.md`＋R43 澄清分流。**禁止**把一／二筛整套系数塞进 `pack_material`。

1. **可变 k＋密度约束（TARGET≥2/3，k∈[3,7]）**  挂层=`stage2／density_submit`；模块=`app/kg_lab/density_submit.py::density_constrained_submit`；  主线接法：交卷只带 rank_order＋k；主线可用 max_segments=k 或 priority_segment_ids=rank_order；勿把密度扫描系数塞进 pack_material
2. **conflict_pairs（support vs oppose 成对）**  挂层=`stage2／authority_rerank 出口`；模块=`app/kg_lab/stage2_authority.py::build_conflict_pairs`；  主线接法：SubmitSurface.conflict_pairs → 报告冲突节／质证；装箱只消费 id，不消费权威权重
3. **通稿／近同文簇 keep-one（抗挤）**  挂层=`stage2／density_submit 簇内代表`；模块=`app/kg_lab/density_submit.py::_cluster_wire_keep_one`；  主线接法：留在二筛；主线 pack_material 已有 duplicate_map，勿再灌实验簇系数；接盒结果即可
4. **繁简对照折叠（近同判定用，不改原文）**  挂层=`stage2／density_submit 指纹归一`；模块=`app/kg_lab/density_submit.py::_TRAD_TO_SIMP`；  主线接法：属二筛簇判据；主线若复用只进近同检测，不进 pack 参数面
5. **树17 引用纪律（细读带宽／成对／采信·对立标签）**  挂层=`submit／L3（盒后）`；模块=`app/kg_lab/tree17_cite.py::apply_tree17_cite / attach_tree17_plan`；  主线接法：accounting['tree17_cite']＋focus_segment_ids=close_read；提示词注入，零改 pack_material 签名
6. **一筛多维系数（R9／R21）**  挂层=`stage1_pool 内部`；模块=`app/kg_lab/r8_fit.py::evaluate + r21_coeff`；  主线接法：系数只活在一筛打分；出口仅 pool_ids。若动系数须整套重拟合 ±0.08；禁止整包进 pack_material
7. **二筛权威权重（DEFAULT_WEIGHTS）**  挂层=`stage2 内部 portable_authority_unit`；模块=`app/kg_lab/stage2_authority.py::DEFAULT_WEIGHTS`；  主线接法：权重只服务盒内裁决；交卷只留 rank／pairs。主线接盒序，不接 weights dict
8. **造谣核对：具体澄清／谣言壳分流（R43）**  挂层=`stage2／intent_routes＋density_submit`；模块=`is_clarify_substance`／`is_clarify_rumor_shell`；  主线接法：只进二筛核心排序；勿案专名；勿把分流规则塞进 pack_material 参数

### 层边界（必须守）

| 层 | 出口窄面 | 禁止外泄 |
|---|---|---|
| stage1_pool | `pool_ids`／`pool_ranked` | coeff／feats／weights |
| stage2_box | `box_ids`／`k`／洗净 `conflict_pairs` | 权威浮点／多维系数 |
| submit | `rank_order`＋pairs＋树17细读信号 | 整套召回系数 |
| 主线 pack | `priority_segment_ids`／`focus_segment_ids`／`max_segments` | **禁整套系数进 pack_material** |

### 主线接入建议（先不整包）

1. **先接交付面**：`conflict_pairs`→报告冲突节；树17 `attach_tree17_plan`→分析师 focus；可变 k 盒序→`priority_segment_ids`。
2. **密度／通稿／繁简／澄清分流**：整段迁 `density_submit`／`intent_routes` 澄清助手，经实验旗默认关，跨树量换分后再默认开。
3. **一筛多维系数**：继续留在 exp；若并，必须整套重拟合 ±0.08，且出口只留 pool_ids。
4. **不要**把 `r9`／`r21`／`DEFAULT_WEIGHTS` dict 传进 `pack_material(...)`。

## 分支／产物索引

- 复测 tip：`9743fbd`（R43）；交付分支：`cursor/r44-six-case-gate-8338`
- 关键 artifacts：`R40_holdout_gate`／`R41_tree17_gain`／`R42_decouple_pack`／`R43_wanghong_q002`／`R44_six_case_gate`
- 边界模块：`app/kg_lab/layer_boundary.py`
- 本报告：`artifacts/R44_six_case_gate.md`／`.json`

## 异常清单

- （无）数字均落在期望带内。
