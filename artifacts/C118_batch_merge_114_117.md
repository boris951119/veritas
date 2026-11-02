# C-118 末批合入 C-114～117（合后旁证）

> 零 LLM；四旗默认关；墙钟 3.6s。
> 禁合 C-113；禁改默认为开；禁 pack 多维系数；未宣称树15 红标已灭。

## 合入摘要

- 基线 main：`7c3d24e6c60f569ce9ed1158badddcf3e8b0f7ee`
- 源 tip：C-114 `af7fff78165db983c1f99be26fa4cf7dfe167d46`；C-115 `f08b64e9901963e46e5ba8b579090d666cc92f95`；C-116 `2fa0e71ca6c051932282429f08e3a400c76473b3`；C-117 `2c5e50d7f5babf809ea46790fc32b202918a5ef4`
- 合序：C-114 → C-115 → C-116 → C-117（非 squash）；**未合 C-113**
- 冲突：仅 `app/config.py`／`docs/HANDOFF.md`（三轮），机械保留四旗默认关与各条目；**未改逻辑／未改默认旗／未塞 pack 系数**
- 逐旗＝1 烟雾：四模块 import＋Settings.from_env 均可挂上（见 json `smoke`）

## 结论

- 刘翔@7：**12**（门槛≥11）
- holdout L2：**29**（刘翔 L2=13；合计 L2=42）
- 泄漏：**0**
- 四旗默认：{'anchor_stable': False, 'conflict_trace': False, 'conf_calib': False, 'tree15_depress': False}
- 过线建议：**YES**

## 分题（默认旗关）

| slug/qid | role | L2 | @7 | leaks |
|---|---|---:|---:|---:|
| liuxiang/q_001 | regression | 4 | 4 | 0 |
| liuxiang/q_002 | regression | 5 | 4 | 0 |
| liuxiang/q_003 | regression | 4 | 4 | 0 |
| wanghong/q_001 | holdout | 2 | 1 | 0 |
| wanghong/q_002 | holdout | 2 | 2 | 0 |
| wanghong/q_003 | holdout | 3 | 3 | 0 |
| kh_th/q_001 | holdout | 1 | 1 | 0 |
| kh_th/q_002 | holdout | 3 | 2 | 0 |
| kh_th/q_003 | holdout | 5 | 2 | 0 |
| ai171/q_001 | holdout | 4 | 2 | 0 |
| ai171/q_002 | holdout | 5 | 1 | 0 |
| ai171/q_003 | holdout | 4 | 1 | 0 |

## 一行验收

过线建议 **YES**＋@7=12／holdout=29／leak=0／四旗默认关=True

