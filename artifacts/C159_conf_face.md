# C-159 置信面收据读数（脚本现抄，非手打）

- 判定＝YES｜改前树＝/private/tmp/w156｜门槛 G1..G7 跑前写死（见本尺文件头）
- 一句话：本票不改档，只让「这条凭什么算高置信」在交卷面上可核。

## 高档覆盖（分布事实，本票不动它）
- /tmp/s4runs/time-20261104-135401（18 题）：改前 高 3/196＝0.0153 → 开旗 高 3/196＝0.0153（关旗同改前＝0.0153）
  档分布 开旗＝{'高': 3, '中': 183, '低': 10}｜分位档 开旗＝{'高': 65, '中': 71, '低': 60}
- /tmp/c153runs/time-20261104-221631（3 题）：改前 高 0/32＝0.0 → 开旗 高 0/32＝0.0（关旗同改前＝0.0）
  档分布 开旗＝{'中': 31, '低': 1}｜分位档 开旗＝{'高': 11, '中': 10, '低': 11}

## 理由句与收据面
- /tmp/s4runs/time-20261104-135401：理由句在场 改前 0／关旗 0／开旗 196 行（在场率 1.0，空 0 行）
  字数 最小 222／最大 272／均值 236.8；「未披露」子句 0 行
  高档收据 3 个（高档行 3）
  G4 数字溯源：查 196 行，越界数字 0 个
  改前树连导 3 次→逐字节稳定件 6／飘件 1（飘件＝['conflict_trace.json']，降级内容级比）
- /tmp/c153runs/time-20261104-221631：理由句在场 改前 0／关旗 0／开旗 32 行（在场率 1.0，空 0 行）
  字数 最小 225／最大 261／均值 239.7；「未披露」子句 0 行
  高档收据 0 个（高档行 0）
  G4 数字溯源：查 32 行，越界数字 0 个
  改前树连导 3 次→逐字节稳定件 6／飘件 1（飘件＝['conflict_trace.json']，降级内容级比）

## 判尺腿逐条
- time-20261104-135401｜G1 不抬档（band 逐档计数相等）＝True
- time-20261104-135401｜G1 不抬档（分位档 band_rel 逐档计数相等）＝True
- time-20261104-135401｜G1 不抬档（逐行 score 相等）＝True
- time-20261104-135401｜G2 关旗理由句＝0＝True
- time-20261104-135401｜G2 开旗理由句全覆盖＝True
- time-20261104-135401｜G2 改前理由句＝0＝True
- time-20261104-135401｜G3 空理由率＝0＝True
- time-20261104-135401｜G4 数字溯源零越界＝True
- time-20261104-135401｜G5 关旗＝改前同形（confidence＋字段说明）＝True
- time-20261104-135401｜G5 比较件两侧都在场＝True
- time-20261104-135401｜G5 稳定集真覆盖比较件（不许全飘当通过）＝True
- time-20261104-135401｜G6 收据分数与本行一致＝True
- time-20261104-135401｜G6 高档收据行数＝高档行数＝True
- time-20261104-135401｜G7 别动别的件（四件等）＝True
- time-20261104-135401｜三臂都取到行（空比空禁）＝True
- time-20261104-221631｜G1 不抬档（band 逐档计数相等）＝True
- time-20261104-221631｜G1 不抬档（分位档 band_rel 逐档计数相等）＝True
- time-20261104-221631｜G1 不抬档（逐行 score 相等）＝True
- time-20261104-221631｜G2 关旗理由句＝0＝True
- time-20261104-221631｜G2 开旗理由句全覆盖＝True
- time-20261104-221631｜G2 改前理由句＝0＝True
- time-20261104-221631｜G3 空理由率＝0＝True
- time-20261104-221631｜G4 数字溯源零越界＝True
- time-20261104-221631｜G5 关旗＝改前同形（confidence＋字段说明）＝True
- time-20261104-221631｜G5 比较件两侧都在场＝True
- time-20261104-221631｜G5 稳定集真覆盖比较件（不许全飘当通过）＝True
- time-20261104-221631｜G6 收据分数与本行一致＝True
- time-20261104-221631｜G6 高档收据行数＝高档行数＝True
- time-20261104-221631｜G7 别动别的件（四件等）＝True
- time-20261104-221631｜三臂都取到行（空比空禁）＝True

## 关旗 vs 改前 逐件比对
- /tmp/s4runs/time-20261104-135401：比较 7 件｜单边缺件 []｜字节等 {'causal_evidence.json': True, 'conclusions.json': True, 'confidence.json': True, 'conflict_resolution.json': True, 'evidence.json': True, '字段说明.md': True}｜内容等 {'causal_evidence.json': True, 'conclusions.json': True, 'confidence.json': True, 'conflict_resolution.json': True, 'conflict_trace.json': True, 'evidence.json': True, '字段说明.md': True}
- /tmp/c153runs/time-20261104-221631：比较 7 件｜单边缺件 []｜字节等 {'causal_evidence.json': True, 'conclusions.json': True, 'confidence.json': True, 'conflict_resolution.json': True, 'evidence.json': True, '字段说明.md': True}｜内容等 {'causal_evidence.json': True, 'conclusions.json': True, 'confidence.json': True, 'conflict_resolution.json': True, 'conflict_trace.json': True, 'evidence.json': True, '字段说明.md': True}

## 开旗 vs 关旗 逐件比对
- /tmp/s4runs/time-20261104-135401：比较 7 件｜单边缺件 []｜字节等 {'causal_evidence.json': True, 'conclusions.json': True, 'confidence.json': False, 'conflict_resolution.json': True, 'evidence.json': True, '字段说明.md': False}｜内容等 {'causal_evidence.json': True, 'conclusions.json': True, 'confidence.json': False, 'conflict_resolution.json': True, 'conflict_trace.json': True, 'evidence.json': True, '字段说明.md': False}
- /tmp/c153runs/time-20261104-221631：比较 7 件｜单边缺件 []｜字节等 {'causal_evidence.json': True, 'conclusions.json': True, 'confidence.json': False, 'conflict_resolution.json': True, 'evidence.json': True, '字段说明.md': False}｜内容等 {'causal_evidence.json': True, 'conclusions.json': True, 'confidence.json': False, 'conflict_resolution.json': True, 'conflict_trace.json': True, 'evidence.json': True, '字段说明.md': False}

## 样例（脚本从开旗臂产物现抄，非手打；取 conclusion_id 排序后的首条）
- 高档：档＝高：score 0.8125≥高阈值 0.8，高出 0.0125；分位档＝高。贡献最大＝推理链完整性 0.3×1＝0.3（chain_for_aggregate）；最低分量＝证据一致性 0.15×0.6666＝0.1（agreement_factor）。证据等级 A 1 条（等级权进 strength）；支撑证据 1 条、署名 1 人（编队 3 人）；六环适用 3 项、断 0 项（无断环）；三道硬门均未触发；按印出数复算可复现（差 0）。
- 中档：档＝中：score 0.63＜高阈值 0.8（差 0.17），≥中阈值 0.5；分位档＝中。贡献最大＝信源可信度 0.25×0.72＝0.18（strength）；最低分量＝证据一致性 0.15×0.6666＝0.1（agreement_factor）。证据等级 B 1 条（等级权进 strength）；支撑证据 1 条、署名 1 人（编队 3 人）；六环适用 4 项、断 2 项（断＝number_traceable、causation_mechanism）；三道硬门均未触发；按印出数复算可复现（差 0）。

## 外部条件与口径
- 三臂吃同一份输入：现跑次 questions/q_*/report.json 反序列化案卷，导出为纯函数、零模型、零网络；env 里 VERITAS_* 先清空再按臂设旗＝出厂旗一致。
- 本尺把一个跑次的各案**合并成一份** confidence.json 再量（分位档切点＝合并面）；生产跑次是逐案各出一份（切点＝本案面），两个面的分位档计数本就不同——本件报的是合并面，不与逐案相加的读数混读。绝对档与 score 不受此影响。
- 逐字节比较集不是手挑的：由改前树同一输入连导 3 次、sha 唯一者才进字节面；不唯一者点名披露＋降级内容级（解析后 sort_keys 再 sha），仍要求全等。
- 分数面＝score／band／band_rel／terms；本票只加两个解释键，任何档分布变化都必须能归因到「行数变了」而不是「分变了」。

## 越界数字明细（应为空）＝无
## 收据分数不一致明细（应为空）＝无

产物卫生：本件只含 id／计数／比率／档名／键名与本票生成的理由句文本，零案卷原文、零模型输出原文。
