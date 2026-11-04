# C-153 交卷 JSON／组包冒烟（盲测前夜）

结论：**YES**｜两腿都组包成功＝True（腿：A、B）

- 机械核：四核心文件齐＝True；JSON 可解析＝True；形状合规＝True；无禁品泄漏＝True；定位可回溯＝True
- 结构不过的原因：五条结构核全过
- 软条件（判 PARTIAL 的那一类）：无
- 墙钟记账（不降档，参考线官方已撤）：腿 A：6 案 × 18 题合计 19643.0 s＝多案批次，不对单案参考线判定；腿 B（单案）：逐题 elapsed_s 合计 8262.0 s｜参考线 1800 s（官方已撤，只记账不改算法）

## 腿 A｜包与四核心文件条数

- zip＝/tmp/c153_submit_from_c149/veritas-交件-c153腿A.zip（188325 字节，43 个成员，6 个专题夹）｜跑次根＝/tmp/s4runs/time-20261104-135401
- 包根文件：01-测试报告.md、02-使用说明.md、03-技术方案.md、DEMO_NOTE.txt、MANIFEST.txt、字段说明.md、部署文档.md｜MANIFEST 行数＝48｜禁品腿扫过的成员数＝43（对官方素材 20 个文件的散列面比；任一为 0 ＝空比空，该核算不过）
- 支撑／冲突事实形状合计：{"n_bad_type": 0, "n_empty_list": 4, "n_extra_key": 0, "n_items": 74, "n_key_only": 74, "n_missing_key": 0}
- 定位回溯合计（结论侧去重后的键）：{"n_support_keys": 21, "n_conflict_keys": 53, "in_volume": 67, "no_doc": 0, "no_para": 0, "empty_slice": 0, "quote_rows": 178, "quote_verbatim": 167, "quote_mismatch": 11, "quote_no_key": 0}
  - 2026·8·26 吉隆口岸泥石流灾害（官方侧现读 137 篇／字段说明在场＝1）：48／3／21／35 条（evidence／conclusions／confidence／conflict_resolution）｜包内另有 conflict_trace.json
    回溯：支撑键 3＋冲突键 24＝在卷 22／doc 缺 0／para 缺 0／空段 0；引文逐字腿 35 行＝逐字 32／不匹配 3／段取不到 0
    抽检 doc_019#p22（题 q_001）＝官方切片 106 字、包内引文 42 字、逐字命中＝True
    抽检 doc_229#p14（题 q_002）＝官方切片 118 字、包内引文 118 字、逐字命中＝True
    抽检 doc_031#p6（题 q_003）＝官方切片 91 字、包内引文 91 字、逐字命中＝True
  - 中美AI事故预警提议（2026.9）（官方侧现读 66 篇／字段说明在场＝1）：41／3／42／45 条（evidence／conclusions／confidence／conflict_resolution）｜包内另有 conflict_trace.json
    回溯：支撑键 3＋冲突键 6＝在卷 9／doc 缺 0／para 缺 0／空段 0；引文逐字腿 26 行＝逐字 22／不匹配 4／段取不到 0
    抽检 doc_047#p1（题 q_001）＝官方切片 153 字、包内引文 26 字、逐字命中＝True
    抽检 doc_023#p12（题 q_002）＝官方切片 1120 字、包内引文 89 字、逐字命中＝False
    抽检 doc_022#p9（题 q_003）＝官方切片 169 字、包内引文 105 字、逐字命中＝True
  - 刘翔编制“二选一”事件（官方侧现读 53 篇／字段说明在场＝1）：43／3／43／20 条（evidence／conclusions／confidence／conflict_resolution）｜包内另有 conflict_trace.json
    回溯：支撑键 3＋冲突键 5＝在卷 7／doc 缺 0／para 缺 0／空段 0；引文逐字腿 34 行＝逐字 33／不匹配 1／段取不到 0
    抽检 doc_002#p3（题 q_001）＝官方切片 66 字、包内引文 35 字、逐字命中＝True
    抽检 doc_005#p3（题 q_002）＝官方切片 188 字、包内引文 86 字、逐字命中＝True
    抽检 doc_012#p5（题 q_003）＝官方切片 114 字、包内引文 75 字、逐字命中＝True
  - 印度航空 AI171 空难（2025.6–2026.5）（官方侧现读 52 篇／字段说明在场＝1）：41／3／25／10 条（evidence／conclusions／confidence／conflict_resolution）｜包内另有 conflict_trace.json
    回溯：支撑键 3＋冲突键 4＝在卷 7／doc 缺 0／para 缺 0／空段 0；引文逐字腿 29 行＝逐字 27／不匹配 2／段取不到 0
    抽检 doc_003#p1（题 q_001）＝官方切片 205 字、包内引文 25 字、逐字命中＝True
    抽检 doc_012#p8（题 q_002）＝官方切片 757 字、包内引文 78 字、逐字命中＝True
    抽检 doc_004#p3（题 q_003）＝官方切片 36 字、包内引文 14 字、逐字命中＝True
  - 柬泰边境争端（2025.12–2026.9）（官方侧现读 105 篇／字段说明在场＝1）：39／3／33／37 条（evidence／conclusions／confidence／conflict_resolution）｜包内另有 conflict_trace.json
    回溯：支撑键 5＋冲突键 9＝在卷 14／doc 缺 0／para 缺 0／空段 0；引文逐字腿 31 行＝逐字 30／不匹配 1／段取不到 0
    抽检 doc_053#p1（题 q_001）＝官方切片 132 字、包内引文 51 字、逐字命中＝True
    抽检 doc_089#p9（题 q_001）＝官方切片 164 字、包内引文 143 字、逐字命中＝True
    抽检 doc_065#p10（题 q_001）＝官方切片 173 字、包内引文 47 字、逐字命中＝True
  - 王虹“北大discouraged”事件（官方侧现读 73 篇／字段说明在场＝1）：28／3／32／29 条（evidence／conclusions／confidence／conflict_resolution）｜包内另有 conflict_trace.json
    回溯：支撑键 4＋冲突键 5＝在卷 8／doc 缺 0／para 缺 0／空段 0；引文逐字腿 23 行＝逐字 23／不匹配 0／段取不到 0
    抽检 doc_003#p5（题 q_001）＝官方切片 118 字、包内引文 51 字、逐字命中＝True
    抽检 doc_010#p7（题 q_002）＝官方切片 149 字、包内引文 60 字、逐字命中＝True
    抽检 doc_007#p1（题 q_003）＝官方切片 142 字、包内引文 51 字、逐字命中＝True
- 跑次真数：逐题 elapsed_s 合计 19643.0 s、n_calls 合计 1058、tokens 合计 1703777
  - 2026·8·26 吉隆 q_001：elapsed 1340.2 s、calls 71、tokens 112936、结论 9 条
  - 2026·8·26 吉隆 q_002：elapsed 1094.4 s、calls 52、tokens 89236、结论 21 条
  - 2026·8·26 吉隆 q_003：elapsed 1271.6 s、calls 71、tokens 110478、结论 11 条
  - 中美AI事故预警提议（2 q_001：elapsed 1075.7 s、calls 59、tokens 96042、结论 19 条
  - 中美AI事故预警提议（2 q_002：elapsed 1708.6 s、calls 112、tokens 128321、结论 24 条
  - 中美AI事故预警提议（2 q_003：elapsed 1204.6 s、calls 49、tokens 79796、结论 26 条
  - 刘翔编制“二选一”事件 q_001：elapsed 969.8 s、calls 52、tokens 90492、结论 17 条
  - 刘翔编制“二选一”事件 q_002：elapsed 970.2 s、calls 46、tokens 86693、结论 23 条
  - 刘翔编制“二选一”事件 q_003：elapsed 1242.6 s、calls 56、tokens 102069、结论 24 条
  - 印度航空 AI171 空 q_001：elapsed 791.7 s、calls 40、tokens 75951、结论 9 条
  - 印度航空 AI171 空 q_002：elapsed 947.2 s、calls 28、tokens 74559、结论 15 条
  - 印度航空 AI171 空 q_003：elapsed 769.9 s、calls 46、tokens 73462、结论 12 条
  - 柬泰边境争端（2025. q_001：elapsed 1206.2 s、calls 85、tokens 109380、结论 15 条
  - 柬泰边境争端（2025. q_002：elapsed 1117.4 s、calls 84、tokens 109597、结论 13 条
  - 柬泰边境争端（2025. q_003：elapsed 1017.6 s、calls 28、tokens 80921、结论 18 条
  - 王虹“北大discour q_001：elapsed 743.8 s、calls 32、tokens 79982、结论 13 条
  - 王虹“北大discour q_002：elapsed 1511.5 s、calls 100、tokens 120447、结论 27 条
  - 王虹“北大discour q_003：elapsed 660.0 s、calls 47、tokens 83415、结论 6 条
- --with-causal 旁证（当场现数）：195433 字节包里 causal_evidence.json 6 份／24 行：四要素任一非空 0 行、四要素全非空 0 行、带降级原因句 24 行
- 外部条件披露：复用 C-149 那批六案跑次产物（旧批），本腿只读组包＋核查，不重跑模型

## 腿 B｜包与四核心文件条数

- zip＝/tmp/c153_submit_fresh_liuxiang/veritas-交件-c153腿B.zip（55943 字节，13 个成员，1 个专题夹）｜跑次根＝/tmp/c153runs/time-20261104-221631
- 包根文件：01-测试报告.md、02-使用说明.md、03-技术方案.md、DEMO_NOTE.txt、MANIFEST.txt、字段说明.md、部署文档.md｜MANIFEST 行数＝18｜禁品腿扫过的成员数＝13（对官方素材 20 个文件的散列面比；任一为 0 ＝空比空，该核算不过）
- 支撑／冲突事实形状合计：{"n_bad_type": 0, "n_empty_list": 0, "n_extra_key": 0, "n_items": 20, "n_key_only": 20, "n_missing_key": 0}
- 定位回溯合计（结论侧去重后的键）：{"n_support_keys": 9, "n_conflict_keys": 11, "in_volume": 19, "no_doc": 0, "no_para": 0, "empty_slice": 0, "quote_rows": 35, "quote_verbatim": 34, "quote_mismatch": 1, "quote_no_key": 0}
  - 刘翔编制“二选一”事件（官方侧现读 53 篇／字段说明在场＝1）：48／3／32／47 条（evidence／conclusions／confidence／conflict_resolution）｜包内另有 conflict_trace.json
    回溯：支撑键 9＋冲突键 11＝在卷 19／doc 缺 0／para 缺 0／空段 0；引文逐字腿 35 行＝逐字 34／不匹配 1／段取不到 0
    抽检 doc_002#p3（题 q_001）＝官方切片 66 字、包内引文 66 字、逐字命中＝True
    抽检 doc_012#p2（题 q_001）＝官方切片 131 字、包内引文 66 字、逐字命中＝True
    抽检 doc_037#p2（题 q_001）＝官方切片 152 字、包内引文 66 字、逐字命中＝True
- 跑次真数：逐题 elapsed_s 合计 8262.0 s、n_calls 合计 233、tokens 合计 324056
  - 刘翔编制“二选一”事件 q_001：elapsed 2270.9 s、calls 64、tokens 95348、结论 13 条
  - 刘翔编制“二选一”事件 q_002：elapsed 3834.3 s、calls 120、tokens 135574、结论 26 条
  - 刘翔编制“二选一”事件 q_003：elapsed 2156.8 s、calls 49、tokens 93134、结论 22 条
- 外部条件披露：本机 14B 新鲜单案端到端（三题全跑）；22:16–22:54 与 veritas-c151 的王虹跑批同机并发，墙钟被拖高＝方向保守（只会高估），空闲内存与 swap 的当场打印见跑批日志
- 外部条件披露：litellm 启动期远程 cost-map 三次读取超时后回落本地备份；模型请求全部走本机 Ollama＋假密钥（安全闸由跑批脚本钉），无付费外呼

## 明天盲测操作备忘（三行）

- 喂案＝盲测案整夹放仓库外一个只读根目录，每案目录必须有 raw_documents.json（官方形态）；跑批根用 OFFICIAL_CASES=<该根> 指过去（不给＝默认桌面样例集路径）。⚠ measure_s4_gates 是从该案 conclusions.json 里抽 question_id／question 的——盲测数据若不带结论样例，就另存一份 questions.json（只含 question_id 与 question）放案目录里，走下面第二条路
- 跑（二选一，都不花钱：①测量路＝仓库根 `S4_OUT=/tmp/blindruns PYTHONPATH=. .venv/bin/python -X utf8 -u scripts/measure_s4_gates.py time --case <专题关键词> --timeout-seconds 900`（安全闸自锁 Ollama＋假密钥、钉单模型链；不加 --case＝全跑）；②生产路＝`PYTHONPATH=. .venv/bin/python -m app.pipeline <案目录> --out <跑次根>/<案名>`，案目录里有 raw_documents.json 即自动走官方适配，题面取 <案目录>/questions.json 或 --questions 指定）
- 交＝`PYTHONPATH=. .venv/bin/python scripts/build_submission_zip.py --run-dir <跑次根> --out <zip 路径>`；--run-dir 要指到「跑次根」，其下每个专题夹得有 questions/q_*/report.json（生产路把 --out 写成 <跑次根>/<案名> 正好落成这个形状）；邮件附件＝这一个 zip，包内每专题四核心 JSON＋字段说明＋MANIFEST；causal_evidence 默认不装（四要素非空率不达标时 MANIFEST 里带当场原因句）

## 卫生与红线

- 本探针零模型调用；真跑腿（腿 B）的模型请求只走本机 Ollama＋假密钥（安全闸由跑批脚本钉），无付费外呼。⚠ 不写「零网络」：litellm 启动期尝试拉远程 cost-map，三次超时后回落本地备份（非模型请求，见跑批日志当场打印）。
- 工作树 `git diff app/` 为空；未合任何未合枝；未改任何默认旗（出厂默认当场读码＝submit_top7／conflict_trace／arb_context 开、cite_accept 关）。
- 本文件不含官方语料正文、不含结论原文：只有 doc_id／para_id／计数／字节数／题目号（切片只记字符数）。
