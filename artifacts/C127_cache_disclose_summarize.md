# C-127 件② 缓存缺席披露＋摘要建库端口（交账）

- 结论：**YES**——A 披露键＋B 建库脚本端口落地；守护 5 格绿＋三把假腿刀全见红；关旗 off-face 字节逐位同；六案门控旁证与 main 基线逐位一致（唯一差异墙钟）；总旗仍出厂默认关。
- 基线：main `57e7687`（祖先含 `349156e`）；枝＝`qoder/c127-cache-disclose-summarize`（自 `57e7687` 开；本单不合 main）。

## 改动面（件②）

- `app/core/kg_test_tree_line.py`（+30 行）：`build_test_tree_surface` 算缓存态并入返回与 accounting；docstring 补披露说明。
- `scripts/kg_lab/batch_summarize_case.py`（新）：自实验仓端口；universe 逻辑自含在 scripts 侧（金标隔离闸合规，同 `probe_c125_six_case_gate` 法，不 import 已摘的 `slices.union_pack_ids`）；新增 `--dry-run`（零 LLM 只报 pending）。
- `tests/test_c127_cache_disclose.py`（新，5 格）：冷臂披露／暖臂不误报／热路径零自动建库／出厂默认关未动／脚本空跑（samples 缺失则 skip）。
- `tests/test_c37_engineering_gates.py`（+1 行）：新 skip 位点登记进 `REGISTERED_SKIP_SITES`（双向闸当场咬住未登记位点＝闸有牙，登记后转绿）。

## 披露键（A）

- 落点＝`accounting["kg_test_tree"]["cache"]`（嵌在既有白名单键内＝零新顶层键，规避 C-123「未登记被剥」教训；账面过禁键审计）。
- 键：`vault_dir_present`（bool）／`n_rows`／`n_with_summary`／`summary_missing`（缺席布尔）／`affected`（影响面清单，取值 summary|vault|embed）／`degraded_continue`（降级继续）。
- 现场读数：真实暖臂（刘翔、真 slug）＝`vault_present=true, n_rows=372, n_with_summary=362, summary_missing=false, affected=[], degraded_continue=false`（部分覆盖 362/372 可见）；默认 slug="case" 调法＝`summary_missing=true, affected=[summary,vault]`（见「现场发现」）。

## 建库端口（B）

- 选工单①（仅 CLI 菜谱）不选②（不加 env）：少一面开关、热路径天然零调用。
- 默认热路径零自动建库：`summarize_paras` 打成炸雷后整链照常跑（守护格）；`pipeline.py`／`kg_test_tree_line.py` 源码零 `batch_summarize_case` 引用（守护格）。
- 空跑证据：`DRY_RUN slug=liuxiang universe=362 pending=0`（零 LLM；并集与生产箱 362 对上）。
- `.kg_lab_vault`／`.kgcache` 保持 gitignore，未入库。

## 暖起菜谱（二选一）

- 菜谱A（脚本自建，本机 14B、零现金）：`.venv/bin/python scripts/kg_lab/batch_summarize_case.py --dry-run --case-filter 刘翔 --samples <样本根>` 先看 pending；去掉 `--dry-run` 即真建（`--workers 1 --batch 40` 可 nohup；六案逐个换 `--case-filter`）。
- 菜谱B（外拷）：整目录拷实验仓 `.kg_lab_vault`（summaries＋lexicon）；⚠ 向量缓存 `.kgcache` 换摘要时必须整份换——向量按 para_id 复用不校验文本（C-126② 口径，本单不改其语义）。

## 守护与刀

- 5 格全绿（含真实刘翔案 `--dry-run` 子进程腿）。
- 三把假腿刀全见红：K1 摘 return 的 cache 键→2 红；K2 缺席布尔恒 False→冷臂红；K3 热路径偷偷调 `summarize_paras`→热路径格红。下刀后字节还原（git diff 只剩本单改动）。

## 量尺读数

- 枝上整套：`7 failed, 1224 passed, 1 skipped`＝主仓同 commit 基线 7 红逐名不变＋本单 5 格绿（过程中见过的 3 笔额外红＝新 skip 位点未登记所致，登记后清零；另 2 笔＝实现未在场的预期红）。
- 关旗 off-face：sha16 `c6ff9d478007b287`／`be657d8db1e7dbde`、sel_n 362、kw 空——与改前逐位同。
- 六案门控复跑（枝、暖缓存）：刘翔 57%@7=12；冒烟各 67%@7=6；holdout 86/80/80%@7=6/4/5；金标→细读全 1.0；泄漏 0；门槛①②③ OK、READY=YES（墙钟 277.1s）——与 main 基线逐位一致。

## 现场发现（记帐，未改）

- pipeline 入口 `ensure_test_tree_submit(dossier)` 默认 `case_slug="case"`：生产开旗热路径的摘要／缓存键天然挂 "case" 案名（`summaries/case/` 不存在）⇒ 缺席本就存在，C-127 之前静默、现在被披露键点亮（现场读数 `summary_missing=true`）。真实案名接线属新票，本单禁改判定不动它。

## 禁项核对

- `VERITAS_TEST_TREE_LINE` 默认关：dataclass／from_env 双 False 现场核（守护格 d 钉死）。
- 未合 C-123／C-113／C-121／C-122／C-124；未动 para_id 复用校验语义；未接跳边臂；零官语料原文进产物；无 Markdown 表。

## 产物索引

- 件① 只量：`artifacts/C127_cache_gap_measure.md`／`.json`（主仓工作树，未 commit，/tmp 有备份）
- 件② 本件：`artifacts/C127_cache_disclose_summarize.md`／`.json`（随枝入库）
- 门控旁证：`artifacts/c125/C125_six_case_gate.md`（枝上复跑版，墙钟 277.1s）
