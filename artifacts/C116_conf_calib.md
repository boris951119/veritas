# C-116 置信档校准闸（开／关对照）

> 零 LLM；旗默认关；`VERITAS_CONF_CALIB=1` 开。墙钟 7.1s。
> 挂点：`app/core/conf_calib.py`；`pipeline` finalize；`export/official` 交卷档；`config` 旗。尺源：`calibration/face_v2_row_snapshot.jsonl`（自标，非金标提示）。
> 过线建议：**YES** — 高档精确度 关 0.2069 → 开 0.2727；ECE 关 0.056505 → 开 0.054964；泄漏=0。

## 结论

- 高档精确度（strict 对）：关 **6/29=0.2069** → 开 **3/11=0.2727**
- 高档加权准确率（对=1／部分=0.5／错=0）：关 **0.5172** → 开 **0.6364**
- ECE：关 **0.056505** → 开 **0.054964**（降档行呈现分钳到 <0.8；库存 score 不变）
- 高档覆盖：关 29 → 开 11；降档条数=18
- 泄漏：**0**
- 旁证刘翔@7：关 12／开 12；holdout L2：关 29／开 29
- **合入建议：可建议末批统一合（仍默认关）**；本票／C-113～115 均不直接合 main。

## 门槛（开旗）

- min_evidence：n_evidence ≥ 2
- anchor_incomplete：引文命中率 ＜ 1 或段不可定位
- chain_incomplete：chain ＜ 1
- panel_disagreement：agreement ＜ 1
- conflict_undecided：落入平局／无裁决冲突对

## 一行验收

过线建议 **YES**＋高档精确度0.2727／ECE0.054964／泄漏0／旁证@7=12/holdout=29

