# C-156 置信面（3.2）：换分＝0 等证＋开旗新披露面现量

结论：**YES**｜判据见 scripts/probe_c156_confidence_face.py 文件头（跑前写死＋更正记录）

## 判定核

- 腿①三臂每案卷都取到件（空比空禁）[time-20261104-135401]＝True
- 腿①确定件跨树逐字节等[time-20261104-135401]＝True
- 腿①飘件内容级仍等[time-20261104-135401]＝True
- 腿①比较集当场量过（改前树重复导出≥3）[time-20261104-135401]＝True
- 腿③开旗行数>0[time-20261104-135401]＝True
- 腿③两类键全覆盖[time-20261104-135401]＝True
- 腿③开旗不改档分布[time-20261104-135401]＝True
- 腿③开旗＝关旗同一批行[time-20261104-135401]＝True
- 腿③档计数与行数自洽（两臂各档之和＝行数）[time-20261104-135401]＝True
- 字段说明关旗也在＝True
- 字段说明开旗多两块＝True
- 腿①三臂每案卷都取到件（空比空禁）[time-20261104-221631]＝True
- 腿①确定件跨树逐字节等[time-20261104-221631]＝True
- 腿①飘件内容级仍等[time-20261104-221631]＝True
- 腿①比较集当场量过（改前树重复导出≥3）[time-20261104-221631]＝True
- 腿③开旗行数>0[time-20261104-221631]＝True
- 腿③两类键全覆盖[time-20261104-221631]＝True
- 腿③开旗不改档分布[time-20261104-221631]＝True
- 腿③开旗＝关旗同一批行[time-20261104-221631]＝True
- 腿③档计数与行数自洽（两臂各档之和＝行数）[time-20261104-221631]＝True
- 基线量尺产物在场＝True
- 零导出失败臂＝True
- 卫生新增面零散文命中＝True
- 卫生命中全为同一处脚手架＝True

## 腿① 逐件分类（改前树自量 3 次重复导出定出比较集）

- time-20261104-135401：案 6 份／题 18 道｜导出件 7 类
  - 改前树连导 3 次后每件不同 sha 个数＝{"causal_evidence.json": 1, "conclusions.json": 1, "confidence.json": 1, "conflict_resolution.json": 1, "conflict_trace.json": 3, "evidence.json": 1, "字段说明.md": 1}
  - 逐字节比较集（确定件）＝["causal_evidence.json", "conclusions.json", "confidence.json", "conflict_resolution.json", "evidence.json", "字段说明.md"]｜跨树逐字节全等＝True
  - 飘件（改前树自己就飘 ⇒ 降级内容级比，仍须全等＝True）＝["conflict_trace.json"]
  - 导出失败臂＝0
  - 逐案（字节等／内容等｜进字节面的件数）＝{"2026·8·26 吉隆口岸泥石流灾害": [true, true, 6], "中美AI事故预警提议（2026.9）": [true, true, 6], "刘翔编制“二选一”事件": [true, true, 6], "印度航空 AI171 空难（2025.6–2026.5）": [true, true, 6], "柬泰边境争端（2025.12–2026.9）": [true, true, 6], "王虹“北大discouraged”事件": [true, true, 6]}
- time-20261104-221631：案 1 份／题 3 道｜导出件 7 类
  - 改前树连导 3 次后每件不同 sha 个数＝{"causal_evidence.json": 1, "conclusions.json": 1, "confidence.json": 1, "conflict_resolution.json": 1, "conflict_trace.json": 3, "evidence.json": 1, "字段说明.md": 1}
  - 逐字节比较集（确定件）＝["causal_evidence.json", "conclusions.json", "confidence.json", "conflict_resolution.json", "evidence.json", "字段说明.md"]｜跨树逐字节全等＝True
  - 飘件（改前树自己就飘 ⇒ 降级内容级比，仍须全等＝True）＝["conflict_trace.json"]
  - 导出失败臂＝0
  - 逐案（字节等／内容等｜进字节面的件数）＝{"刘翔编制“二选一”事件": [true, true, 6]}

## 腿②③ 现量

- time-20261104-135401：行数 开旗 196＝关旗 196｜两类披露键 196 行｜按印出数复现成功 196 行｜最差差 0.0001
  - 绝对档（开旗）＝{"中": 183, "低": 10, "高": 3}｜（关旗）＝{"中": 183, "低": 10, "高": 3}｜分位档（开旗）＝{"高": 69, "低": 60, "中": 67}
  - 分量在单案内不同取值数（取各案最大）＝{"strength": 16, "coverage": 5, "agreement": 1, "chain": 6}｜署名≥2 的行 0｜n_panel 取值 ['3']
  - 腿② 与跑次历史产物逐字节等＝{"2026·8·26 吉隆口岸泥石流灾害": true, "中美AI事故预警提议（2026.9）": true, "刘翔编制“二选一”事件": true, "印度航空 AI171 空难（2025.6–2026.5）": true, "柬泰边境争端（2025.12–2026.9）": true, "王虹“北大discouraged”事件": true}
- time-20261104-221631：行数 开旗 32＝关旗 32｜两类披露键 32 行｜按印出数复现成功 32 行｜最差差 0.0001
  - 绝对档（开旗）＝{"中": 31, "低": 1}｜（关旗）＝{"中": 31, "低": 1}｜分位档（开旗）＝{"中": 10, "低": 11, "高": 11}
  - 分量在单案内不同取值数（取各案最大）＝{"strength": 15, "coverage": 5, "agreement": 1, "chain": 4}｜署名≥2 的行 0｜n_panel 取值 ['3']
  - 腿② 与跑次历史产物逐字节等＝{"刘翔编制“二选一”事件": true}

## 外部条件与口径

- 改前树＝/tmp/w156base（detached，基 tip 见工单）；本树＝当前工作树；两边吃同一份 manifest（现跑次 questions/q_*/report.json 反序列化的案卷），导出为纯函数、零模型、零网络；env 里 VERITAS_* 先清空再按腿设旗＝出厂旗一致。
- 逐字节比较集不是手挑的：由改前树同一输入连导 3 次、sha 唯一者才进逐字节面；不唯一者点名披露＋降级到内容级（解析后 sort_keys 再 sha），仍要求全等。
- 分数面＝score／band／band_rel／terms；本票只加披露键，任何档分布变化都必须能归因到「行数变了」而不是「分变了」。
- 旧缺口按工单先量后改：基线读数见 artifacts/C156_baseline.md（件①）。
- 仪表更正文见脚本文件头（四条：空比空／conflict_trace 跨进程键序飘／飘件被当假红／分位档计数漏加一）。

## 卫生与红线

- 零 LLM、零网络；仲裁公式／冲突数值 STOP／cite_accept／24-25-27 主路径未动；比赛三旗出厂开未改；新旗 VERITAS_CONF_FACE_DETAIL 出厂默认开＝只加披露，关＝逐字节回改前。
- 产物不含官方语料正文：只有计数、档名、sha 前缀与键名。
- 卫生（新增／改动面）：261 个面条目归一化 66177 字 → 66153 个 25 字窗对官方 6 案 raw_documents 全文（归一化 2053325 字）：总命中 17 窗＝1 处连续片段，其中含散文（≥4 连续中日韩字）＝0 窗＝判定看散文面
- 那批命中全是 JSON 脚手架（`"content":…"source_credibility":…`）——本仓测试夹具写的官方输入格式与官方语料里的字段名同串，不是语料正文进图；对照面（本票未碰的两份已入库夹具）＝{"tests/test_c33_submission_side.py": {"windows": 10135, "hits": 51, "prose_hits": 0, "prose_runs": 0, "hit_runs": 3}, "tests/test_official_roundtrip.py": {"windows": 28924, "hits": 98, "prose_hits": 0, "prose_runs": 0, "hit_runs": 10}}⇒ 同款串在既有文件里也命中且同样零散文，分类口径不是为本票现调的。
排除面＝本产物 md 自身（扫描后才写）＝不自比；官方语料正文不读进产物。
