# Skill 纪律 A/B 验证协议（预注册）

> 本协议在实验**开始前**写死指标与判据，防止事后挑数据。
> 纪律出处：**没有闸的 skill 是许愿，没有对照红绿差的 skill 是负债。**
> 每条 skill 先注册（`app/core/skills.py`）、跑本协议、红绿差成立才长期启用。

## 1. 假设

每条 skill 声称：注入其提示词纪律后，**对应配对闸的违规 flag 会减少，
且不引入新的红灯**。若该声称不成立，skill 不得启用（改写 rule 或停用）。

## 2. 设计

- **案例**：`cases/bi-delivery-risk`（真实冲突最丰富、6 信源 6 文类、
  数字与表格密度高——对全部 skill 的触发器都有区分度）。
- **两组**：A = `VERITAS_SKILLS=0`（只关注入，机械闸照跑）；B = 默认（注入）。
  同模型链、同 `llm_temperature: 0.2`、同信源，仅差提示词纪律块。
- **次数**：各 3 次（温度 0.2 下仍有语义抖动，3 次取中位数防单跑侥幸）。
- **预算**：单次 run ≤ `budget_tokens`（默认 80 万）；6 次合计预估 ≤ 300 万
  token，跑前向项目负责人确认网关配额。
- **运行**：
  ```bash
  # A 组（3 次，产物落 out_ab_a_1/2/3，避免覆盖演示产物）
  VERITAS_SKILLS=0
  for i in 1 2 3; do .venv/bin/python -m app.pipeline cases/bi-delivery-risk \
      --out cases/bi-delivery-risk/out_ab_a_$i; done
  # B 组（3 次）
  unset VERITAS_SKILLS
  for i in 1 2 3; do .venv/bin/python -m app.pipeline cases/bi-delivery-risk \
      --out cases/bi-delivery-risk/out_ab_b_$i; done
  ```
- **读取指标**：`report.json` 经 `app.core.audit.audit_all` 即时重算
  （警示为派生视图，对 6 份产物分别统计）。

## 3. 指标（预注册，逐 skill）

| skill | 配对闸 | 主指标（B 应显著低于 A） | 辅助指标 |
|---|---|---|---|
| calc_discipline | calc | calc 红灯数 | note 显式算式率（含「计算:」的证据占比） |
| number_provenance | provenance | provenance 黄牌数 | — |
| counting_discipline | counting | counting 黄牌数 | 「计数:M/N」格式出现率 |
| hedged_claim | hedge | hedge 黄牌数 | 转述语气词覆盖率 |
| level_tone | level_tone | level_tone 黄牌数 | — |
| table_citation | citation | 引文打回率（rejected/总证据） | — |

统计口径：每组 3 次的中位数；按 skill 的 trigger 是否命中分层
（未触发的 skill 不计入其指标）。

## 4. 判据（预注册）

一条 skill **判定有效**须同时满足：

1. 主指标中位数 B < A（严格小于，不允许并列）；
2. B 组**未新增任何 calc 红灯**（纪律不得诱发新的复算失败）；
3. B 组结论数与冲突数不低于 A 组的一半（纪律不得把模型吓到不产出）。

**修正案（2026-09-30，数据采集前修订）**：若 A 组某 skill 主指标中位数
已为 0（无下降空间），判据 1 对该 skill **无统计功效**——该 skill 判
「本案例无法检验」而非判负：维持启用，但标注「本案例未验证」，待对应
语料（低可信密集 / OCR 件 / 计数密集）就绪后重测；判据 2、3 仍然适用
（无功效不等于免检——诱发新红灯或压产出仍判负）。

三条全过 → 保持启用；判负 → 该 skill `enabled=False` 并在注册表
`disabled_reason` 记录实证数据，改写 rule 后重新走本协议。

## 5. 记录

结果追加到本文件末尾（日期 / 模型链 / 6 组产物目录 / 指标表 / 判定），
答辩时作为「skill 不是拍脑袋加的」的实证材料。

## 6. 结果

**2026-09-30 首轮执行**。模型链：`openai/deepseek-v4-flash`（阿里云百炼
compatible-mode，主）+ `deepseek-v4-pro`（备）；`llm_temperature: 0.2`；
案例 bi-delivery-risk；6 组产物在 `cases/bi-delivery-risk/out_ab_{a,b}_{1..3}`
（gitignore，不入库）。指标由 `scripts/ab_metrics.py` 即时重算得出。

### 6.1 组级数据

| 指标 | A 组（n=3，无注入） | B 组（n=3，全量注入） |
|---|---|---|
| 结论总数（中位） | 33 | **19**（收缩 ~42%，区间 15–23 与 A 的 29–36 无重叠） |
| 存活证据（中位） | 44 | 22 |
| 冲突对（中位） | 2 | **0**（A 自身即在 0–4 间波动） |
| 引文打回（绝对/率） | 11 / 0.239 | 7 / **0.318**（绝对降、比率升：分母缩得更快） |
| calc 红灯 | 0 | 0 |
| provenance 黄牌（中位） | 2 | 2 |

### 6.2 逐 skill 判定（预注册判据）

| skill | 主指标 A→B（中位） | 判据1 | 判据2 | 判据3 | 判定 |
|---|---|---|---|---|---|
| hedged_claim | hedge 黄 3→2 | ✓ | ✓ | ✗（冲突 0 < 1） | **判负，停用** |
| number_provenance | provenance 2→2 | ✗（并列） | ✓ | ✗ | **判负，停用** |
| table_citation | 打回率 0.239→0.318 | ✗（反向） | ✓ | ✗ | **判负，停用** |
| calc_discipline | calc 0→0 | — | ✓ | ✗ | 无功效可测（headroom=0），保留启用 |
| counting_discipline | counting 0→0 | — | ✓ | ✗ | 无功效可测，保留启用 |
| level_tone | level_tone 0→0 | — | ✓ | ✗ | 无功效可测，保留启用 |

### 6.3 解读（如实记录）

- **判据 3 的冲突塌缩是组级效应**：六条纪律整体注入后，模型措辞转软、
  产出收缩，冲突对在 B 组全部消失——而冲突消解正是本榜单的核心演示
  内容。该效应无法归因到单条 skill（A/B 全有全无设计 Limitation），
  因此判据 3 对每条 skill 同样触发。
- **两条规则未改变模型行为**：calc_discipline（要求 note 写算式）与
  number_provenance 注入后，provenance 黄牌稳定在 2 条/跑（同一模式：
  模型持续给出未写算式的推导数字 95%、15 等）——flash 级模型对
  建议性纪律的遵从度有限。
- **正面信号**：hedged_claim 主指标 3→2 有改善方向；全程零 calc 红灯；
  机械闸族在真实网关输出上全部正常工作（真实抓到来源外数字与引文
  未命中）。

### 6.4 执行动作

- `number_provenance`、`table_citation`、`hedged_claim` 置
  `enabled=False`，`disabled_reason` 记入上表实证；rule 改写后重测。
- `VERITAS_SKILLS_ONLY` 消融白名单机制（skills.py）随本次落地上线，
  供单条 skill 公平重测。

### 6.5 后续实验预注册（hedged_claim 逐条消融）

**动机**：hedged_claim 是唯一主指标有改善方向的判负 skill；其判据 3
失败大概率是组级效应连坐。单条注入重测以还其公平判定。

**设计**：`VERITAS_SKILLS_ONLY=hedged_claim`，其余同第 2 节；3 次，
产物 `out_ab_h_{1..3}`。**判据**（预注册）：hedge 黄牌中位数 < 3（A 组
中位）；结论中位数 ≥ 16.5；冲突中位数 ≥ 1；零 calc 红灯。全过 →
恢复启用（并在本节回填）；任一不过 → 维持停用。

### 6.6 消融结果（2026-09-30 回填）

| 指标 | H 组（仅 hedged_claim，n=3） | 判据 | 结果 |
|---|---|---|---|
| hedge 黄牌（中位） | 2/5/3 → **3** | < 3 | ✗（与 A 组持平） |
| 结论中位 | 18/26/14 → 18 | ≥ 16.5 | ✓ |
| 冲突中位 | 1/5/4 → 4 | ≥ 1 | ✓ |
| calc 红灯 | 0 | 0 | ✓ |

**判定：维持停用。** 单条注入下纪律同样未产生严格主指标改善
（flash 级模型对建议性转述纪律遵从有限）。但消融证实了两件事：
①B 组冲突塌缩确为**组级效应**（单条注入时冲突 1/5/4 完全正常），
连坐假设成立但救不了主指标；②产出收缩同样主要来自全量注入。

**结论**：判据执行完毕。默认注册表 = 3 条启用（calc_discipline /
counting_discipline / level_tone，headroom=0 无功效可测但无损害）+
5 条停用（各带实证理由）。**全部机械闸不受 skill 开关影响、照常运行**
——闸的效力已由 6 组真实产物验证（真实抓到来源外数字、引文未命中、
质证歪曲）。

### 6.7 最终注册表产线健康验证（2026-09-30）

停用落地时发现批量编辑把 `calc_discipline` 整条丢出了注册表（触发
核对时 incidental 发现）——已补回，并在测试里新增**注册表清单守护**
（`test_registry_completeness`，再误删直接红）。修复后以最终 3 条
启用配置重跑 3 次（`out_ab_f2_{1..3}`）：

| 指标 | 数值（3 跑） | 判读 |
|---|---|---|
| 结论中位 | 30（38/18/30） | ≥ A 组一半，产出健康 |
| 冲突中位 | **2**（3/2/0） | 与 A 组持平——协同/仲裁演示内容保留（全量注入时曾塌缩为 0） |
| calc 红灯 | 0 | 无算术复算失败 |
| 计数黄牌 | 1 | **真抓**：「计数:4/4」与案卷 6 信源不符 |
| 其余黄牌 | rebut_quote 2–5、hedge 3–5、premise 2、provenance 1 | 闸链全程工作 |

工程副产物：首跑抓到的唯一「红灯」
`1647.60-1188.00=459.60万` 经复核为**单位后缀误报**（输入裸写、
万只挂结果）——已修为双解释容忍（值或缩放值任一相符即通过）并加
回归测试；错杀诚实算术比漏杀更伤闸的信誉。
