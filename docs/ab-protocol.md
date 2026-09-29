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

三条全过 → 保持启用；任一不过 → 该 skill `enabled=False` 并在注册表
`disabled_reason` 记录实证数据，改写 rule 后重新走本协议。

## 5. 记录

结果追加到本文件末尾（日期 / 模型链 / 6 组产物目录 / 指标表 / 判定），
答辩时作为「skill 不是拍脑袋加的」的实证材料。

## 6. 结果

（待网关配额确认后回填）
