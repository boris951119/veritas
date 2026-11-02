# C-114 证据定位稳（重构后再解析开／关对照）

> 零 LLM 主尺；旗默认关；`VERITAS_ANCHOR_STABLE=1` 开。墙钟 7.6s。
> 挂点：`app/core/anchor_stable.py`；`app/ingest/official_case.py`（加固切片／解包）；`app/export/official.py`（缺锚披露）；`app/config.py`（旗）。
> 过线建议：**YES** — 一致率 关 0.0019 → 开 1.0000；泄漏=0；增益应力行 18／持平 0。

## 结论

- 一致率（金标键×应力）：关 **1/528=0.0019** → 开 **528/528=1.0000**
- 泄漏（FORBIDDEN_PACK_KEYS）：**0**
- 旁证刘翔@7：关 12／开 12；holdout L2：关 29／开 29
- **合入建议：可建议合 main（仍默认关）**；本票不直接合；C-113 未并入。

## 分案应力表

### 刘翔编制“二选一”事件（金标键 34）

| stress | off_ok/n | off_rate | on_ok/n | on_rate | Δ |
|---|---:|---:|---:|---:|---:|
| bom | 0/34 | 0.000 | 34/34 | 1.000 | +1.000 |
| bom_env | 0/34 | 0.000 | 34/34 | 1.000 | +1.000 |
  - err off=`ValueError: raw_documents.json 须为文档数组` on=``
| crlf | 1/34 | 0.029 | 34/34 | 1.000 | +0.971 |
| crlf_env | 0/34 | 0.000 | 34/34 | 1.000 | +1.000 |
  - err off=`ValueError: raw_documents.json 须为文档数组` on=``
| bom_crlf | 0/34 | 0.000 | 34/34 | 1.000 | +1.000 |
| bom_crlf_env | 0/34 | 0.000 | 34/34 | 1.000 | +1.000 |
  - err off=`ValueError: raw_documents.json 须为文档数组` on=``

### 王虹“北大discouraged”事件（金标键 37）

| stress | off_ok/n | off_rate | on_ok/n | on_rate | Δ |
|---|---:|---:|---:|---:|---:|
| bom | 0/37 | 0.000 | 37/37 | 1.000 | +1.000 |
| bom_env | 0/37 | 0.000 | 37/37 | 1.000 | +1.000 |
  - err off=`ValueError: raw_documents.json 须为文档数组` on=``
| crlf | 0/37 | 0.000 | 37/37 | 1.000 | +1.000 |
| crlf_env | 0/37 | 0.000 | 37/37 | 1.000 | +1.000 |
  - err off=`ValueError: raw_documents.json 须为文档数组` on=``
| bom_crlf | 0/37 | 0.000 | 37/37 | 1.000 | +1.000 |
| bom_crlf_env | 0/37 | 0.000 | 37/37 | 1.000 | +1.000 |
  - err off=`ValueError: raw_documents.json 须为文档数组` on=``

### 柬泰边境争端（2025.12–2026.9）（金标键 17）

| stress | off_ok/n | off_rate | on_ok/n | on_rate | Δ |
|---|---:|---:|---:|---:|---:|
| bom | 0/17 | 0.000 | 17/17 | 1.000 | +1.000 |
| bom_env | 0/17 | 0.000 | 17/17 | 1.000 | +1.000 |
  - err off=`ValueError: raw_documents.json 须为文档数组` on=``
| crlf | 0/17 | 0.000 | 17/17 | 1.000 | +1.000 |
| crlf_env | 0/17 | 0.000 | 17/17 | 1.000 | +1.000 |
  - err off=`ValueError: raw_documents.json 须为文档数组` on=``
| bom_crlf | 0/17 | 0.000 | 17/17 | 1.000 | +1.000 |
| bom_crlf_env | 0/17 | 0.000 | 17/17 | 1.000 | +1.000 |
  - err off=`ValueError: raw_documents.json 须为文档数组` on=``

## 一行验收

过线建议 **YES**＋一致率 关0.0019/开1.0000＋泄漏0＋旁证@7=12/holdout=29

