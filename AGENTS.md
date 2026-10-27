# AGENTS.md — veritas 现场环境部署指引（供 AI 智能体执行）

> **换工具接手先读 `docs/HANDOFF.md`**——当前进度、未决问题、下一步顺序、八个已知的坑都在那里；
> 本文件只讲怎么把系统跑起来。收工或换工具前，让当前工具「更新 HANDOFF 并提交」。
> **多工具协作规则在 `docs/dev-protocol.md`**：Qoder＝架构师（出单、独立复放验收、review、同步图与 HANDOFF、提 commit），
> Cursor＝执行工程师（按单实现、发现问题按该文件 §3 分流）。开工指令模板在该文件 §9，直接粘贴给 Cursor。

目标：在一台**没有开发环境**的电脑上（主场景 Windows 10/11，次场景
macOS/Linux），从零把 veritas 跑起来。按步骤执行，每步都有明确的
通过判据；失败按「故障排查」处理。本目录即仓库根（含 `app/`、`tests/`、
`requirements.txt`）。

## 第 0 步：环境自检

1. 找 Python（需 **3.10+**，3.12 最佳）：
   - Windows：依次尝试 `py -3 --version`、`python --version`；
   - macOS/Linux：`python3 --version`。
2. 都没有或版本 < 3.10：
   - Windows：`winget install Python.Python.3.12`（无 winget 则用
     安装包，装时勾选 *Add python.exe to PATH*），装完**重开终端**；
   - macOS：`brew install python@3.12`。
3. 建议把仓库放在**纯英文路径**下（如 `C:\veritas`），避免个别第三方
   库对非 ASCII 路径的兼容问题。

## 第 1 步：建环境装依赖

优先直接跑一键脚本（等价于下面的手工命令）：

- Windows：`setup-windows.bat`（双击或终端执行）
- macOS/Linux：`bash setup-mac.sh`

手工命令（与脚本等价，智能体可任选）：

```bat
:: Windows（cmd）
py -3 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -r requirements.txt litellm
```

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt litellm
```

网络慢或不通时，pip 命令追加国内镜像：
`-i https://pypi.tuna.tsinghua.edu.cn/simple`

**注意**：不要拷贝或迁移旧机器上的 `.venv/` 目录——venv 不可跨机移植，
必须现场重建。

## 第 2 步：验证安装（不需要任何 API key、不需要网络）

```bat
:: Windows
.venv\Scripts\python -m pytest tests -q
```

```bash
# macOS / Linux
.venv/bin/python -m pytest tests -q
```

**通过判据**：未装 mcp 时零 failed，1 条 skip 属正常，只来自 `tests/test_mcp_server.py` 的 `importorskip("mcp")`。装完 mcp 再跑必须零 failed 且零 skipped。**入库基线 `1044 passed`**（本机装了 mcp 的全绿数＝10-28 零时在 **C-69 树10-① 收码包（日期键名统一读点＋对撞三档归类＋两个默认关的开关＋20 颗守护格）** 上量到 `1044 passed, 1 skipped in 36.58s`＝零 failed；`--collect-only 1045`／`def_test_count 1027`；跳格＝`tests/test_c23_corpus_max.py:117`（a-out 产物树不在本机，只附报）；两个新开关默认 False＝生产行为与改前逐字相同（架构师跨树字节等证）；⚠ 上一档 1024＝10-27 晚晚七在 **架构图换面收编包（新步骤树进仓成唯一架构面＋旧全景图退役＋零引用闸叙事面 stem 放宽＋一颗行为格）** 上量到 `1024 passed, 1 skipped in 37.57s`＝零 failed；`--collect-only 1025`／`def_test_count 1007`；跳格 `-rs` 当场点名＝`tests/test_c23_corpus_max.py:117`（a-out 产物树不在本机，只附报）；本笔生产代码零 diff＝`git diff --stat app/ config.json` 为空；⚠ **上一档 `1023 passed`**（10-27 晚晚六在 **C-67 件②＋R-C67-1 返工包（每模窗口解析＋探窗三态＋编队最小窗接进装箱＋5 颗守护格）** 上量到 `1023 passed, 1 skipped in 36.46s`＝零 failed；`--collect-only 1024`／`def_test_count 1006`；跳格 `-rs` 当场点名＝`tests/test_c23_corpus_max.py:117`（a-out 产物树不在本机，只附报）；**架构师六把刀全见红＝K1 取最大窗 1 红／K2 乘 0.8 三红／K3 把「端点不可探」当「无 num_ctx」2 红（＝云端那步有牙）／K4 摘 env 兼容层 1 红／K5 忽略裸名 1 红／K6 拆掉 pipeline 传窗 1 红**；⚠ **上一档 `1011 passed`**（10-27 晚在 **C-65 守护收尾包（#198 夹具判别力＋#199 三颗下刀格改 tmp 副本＋#201 评判提示词逐字钉）** 上量到 `1011 passed, 1 skipped in 32.08s`＝零 failed；`--collect-only 1012`／`def_test_count 994`；跳格 `-rs` 当场点名＝`tests/test_c23_corpus_max.py:117`（a-out 产物树不在本机，只附报）；**架构师独立复放四把刀＝改前 K1／K3 咬不到正向格（＝#198 那个洞在场）、改后四把全咬到**；⚠ **上一档 `1009 passed`**（本机装了 mcp 的全绿数＝10-26 夜在 **C-58 终验（small→big 逃逸票＝件① 只量＝A 臂 L2 48/105 复现、B 臂 46/105、lost=7、gained=5⇒门槛不过⇒生产打分面零 diff；件③ 守护＝R-C58-1 撤销我的错误判据（交叉表证伪）＋R-C58-2 假腿换源码变异刀＋#194 暗开关默认值格）** 上量到 `1009 passed in 32.18s`＝零 failed；`--collect-only 1009`／`def_test_count 991`；`-k "not c49 and not c53 and not c55 and not c57 and not c58"`＝`980 passed, 29 deselected`＝既有用例零变；＋7 全来自 `tests/test_c58_small_to_big.py`；⚠ **上一档 `1002 passed`**＝C-57 那格、其账原文保留在下面；本机装了 mcp 的全绿数＝10-26 上午在 **C-57 终验（L2→L3 引用层＝`second_pass` 主题词空时 BM25×装箱回退、配对真跑四臂、可归因 +3 段）** 上量到 `1002 passed in 32.69s`＝零 failed；`--collect-only 1002`／`def_test_count 984`；`-k "not c49 and not c53 and not c55 and not c57"`＝`980 passed, 22 deselected`＝既有用例零变；＋3 全来自 `tests/test_second_pass.py`；⚠ **上一档 `999 passed`**＝C-55 那格、其账原文保留在下面；本机装了 mcp 的全绿数＝10-25 夜在 **C-55 复放收码（资格线票＝件① 只量＋逃逸口走披露＋件③ 三颗兜底格）** 上量到 `999 passed in 32.52s`＝零 failed；`--collect-only 999`／`def_test_count 981`；`-k "not c49 and not c53 and not c55"`＝`980 passed, 19 deselected`＝既有用例零变；＋3 全来自 `tests/test_c55_relevance_gate.py`；⚠ **上一档 `996 passed`**＝C-54 第二轮那格、其账原文保留在下面；本机装了 mcp 的全绿数＝10-25 夜在 **C-54 第二轮（真跑换分终局＝第二笔合入＝计费口径改 `min(len, SEGMENT_MAX)`）＋发单 C-55** 上量到 `996 passed in 33.20s`＝零 failed；`--collect-only 996`／`def_test_count 978`；`-k "not c49 and not c53"`＝`980 passed, 16 deselected`＝既有用例零变；＋5 全来自 `tests/test_c54_render_budget.py`；⚠ **上一档 `991 passed`**＝C-53 那格、其账原文保留在下面；本机装了 mcp 的全绿数＝10-25 午在 **C-53 第一轮复放（件① 量尺＋件② 披露＋件③ 摘瞬时格；一颗假腿另打回 R-C53-1）** 上量到 `991 passed in 31.81s`＝零 failed；`-k "not c49 and not c53"`＝`975 passed, 16 deselected`＝既有用例零变；＋5 全来自 `tests/test_c53_budget_window.py`；⚠ **上一档 `986 passed`**＝C-52 第二轮那格、其账原文保留在下面；⚠ 上一档 `974 passed`＝C-51＋C-52 第一轮那格、其账原文保留在下面；`-k "not c51 and not c52"`＝`958 passed, 16 deselected`＝既有用例零变；＋16＝`tests/test_c51_recall_funnel.py` 6 颗＋`tests/test_c52_l2_packing.py` 10 颗；⚠ **未装 mcp／无 `.venv` 裸克隆这两格本轮未实测**＝按上一档同一跳过集推算 `973 passed, 1 skipped`／`972 passed, 2 skipped`（标推算、下轮实测）；⚠ 本笔 base clone（`dc37862`）实测 `1 failed, 957 passed`＝红因＝`scripts/check_markdown_tables.py` 的 docstring 附报上一笔漏提交、随本轮一起入库后转绿；⚠ 上一档 `958 passed`＝C-49 收口那格、其账原文保留在下面；三格 10-24 上午在 **C-49 收口（守护缺口补齐包＝交件 zip 的禁品闸补反向腿／`MANIFEST.txt` 那句原因改成当场从探针取数／消解记录探针把 `present` 收到"说法文本在场"＝本轮 `app/` 零 diff）** 上复放＝改前 `947 passed in 31.57s` ⇒ 改后 **`958 passed in 33.17s`＝零 failed**（贴齐 6 个文件＋**先 `git add -A` 再建 `.venv` 符号链接**那棵与交付态 clone 都是 `958`＝三棵树全绿；**摘掉 C-49 那 11 颗新格（`-k "not c49"`）＝`947 passed, 11 deselected`＝既有用例零变**；＋11 全来自 `tests/test_c49_instrument_gaps.py`；⚠ 上一档 `947 passed`＝C-48 抬的那格、其账原文保留在下面）三格 10-24 凌晨在 **C-48 收口（因果主张卡完善包·件① 量尺＋件③ 打包口径＝本轮 `app/` 零 diff）** 上复放＝改前 `945 passed in 34.80s` ⇒ 改后 **`947 passed in 35.08s`＝零 failed**（贴齐 6 个文件＋`git add -A` 那棵与交付态 clone 都是 `947`＝三棵树全绿；**摘掉 C-48 那 2 颗新格仍 `945 passed`＝既有用例零变**；＋2 全来自 `tests/test_c48_packaging.py`；⚠ 上一档 `945 passed`＝C-47 抬的那格、其账原文保留在下面）三格 10-24 凌晨在 **C-47 收口（交付包补齐包＝件① 交付版《部署文档》／件② 第五份提交物 `causal_evidence.json`＋字段全披露／件③ `devil-advocate` 走 `load_roster` 配置路真绑／件④ `scripts/build_submission_zip.py`；`app/core/` 与 `app/agents/registry.py` 零 diff）** 上复放＝改前 `932 passed in 33.16s` ⇒ 改后 **`945 passed in 33.25s`＝零 failed**（贴齐 11 个文件＋`git add -A` 那棵与交付态 clone 都是 `945`＝三棵树全绿；**摘掉 C-47 那 13 颗新格仍 `932 passed in 33.67s`＝既有用例零变**；＋13 全来自 `tests/test_c47_deliverables.py`（10 个 def＋`test_c` 参数化 3）；⚠ 上一档 `932 passed`＝C-46 抬的那格，其账原文保留在下面）三格 10-24 凌晨在 **C-46 收口（交付面「冲突清单＋结果」，`app/core/` 零 diff）** 上复放＝改前 `916 passed in 30.44s` ⇒ 改后 **`932 passed in 30.24s`＝零 failed**（贴文件＋`git add -A` 那棵与交付态 clone 都是 `932`＝两棵树都绿；**摘掉 C-46 那 16 颗新格仍 `916 passed, 16 deselected`＝既有用例零变**；＋16 全来自 `tests/test_c46_record_shape.py`；⚠ 上一档 `916 passed`＝C-38 抬上来的那格，其账原文保留在下面；两格 10-23 午后在 **C-38（面卫生包，一轮收口 `bcb091f`）** 上复放＝改前 `911 passed in 28.93s` ⇒ 改后 **`916 passed in 30.74s`＝零 failed**（贴文件＋`git add -A` 那棵也是 `916`＝两棵树都绿＝dev-protocol §5 第 18 条）；**摘掉 C-38 那五颗新格仍 `911 passed, 5 deselected in 28.94s`＝既有用例零变慢**；⚠ 墙钟口径（10-23 下午重锚）＝**别拿绝对秒数当闸**：C-39 已把腿④ 那两次 `--collect-only` 摘掉（单跑 `0.63～0.70 s`⇒`0.01 s`、c37 文件 `8.0 s`⇒`7.5 s`），剩下的 7.5 s 里 **4.65 s 是既有零引用扫描族**（单格 0.5～1.5 s）＝与新旧单都无关；整套 29.5～30.7 s 属正常波动（要分清是谁的税就加 `--durations=12`，见 `docs/HANDOFF.md` §0〔82〕）。**上一档 `911 passed`**＝C-37（工程闸补齐包，三轮收口 `cb4eb1e`）复放＝改前 `909 passed`（`86133fb` 那棵树＝`3 failed, 906 passed`，由 R-C37-5 修复）⇒ 改后 `911 passed in 29.18s`＝零 failed；＋26 条来自 `tests/test_c37_engineering_gates.py`（26 颗，含三张「绕过面」登记表与零引用豁免表——豁免表现在住在纯数据模块 `tests/c37_zero_ref_registry.py` 并从引用面排除）＋`docs/dev-journal.md` 给 `scripts/check_doc_anchors.py` 落的四条真跑法；**摘掉 C-37 两颗新文件仍 `885 passed in 22.44s`＝既有用例零变慢**；⚠ 整套 29 s＝＋3.4 s 全在这 26 颗（subprocess 预算 3／3）＝这轮的税）。**上一档 `885 passed`**（＝C-35（守护格补齐包·扩版，两轮收口 `d5b0117`）复放＝改前 `869 passed in 23.22s` ⇒ 改后 `885 passed in 22.43s`＝零 failed；＋16 条＝新文件 `tests/test_c35_batch2_teeth.py` 8 颗＋c24 4＋c33 2＋c34 2；**摘掉本轮三颗新格仍 `882 passed, 3 deselected`＝既有用例零变慢**；C-35 还的是三轮验收＋C-36 两轮里我账上那 16 把「0 红」，**第二轮 9 把刀 9 把有牙＝每颗新格都被我当场下刀验过红名**）。**再上一档 `869 passed`**（＝C-36（合式改造）收口；未装 mcp `868 passed, 1 skipped`；两格 10-22 傍晚复放＝改前 `859 in 22.81s` ⇒ 改后 `869 passed in 22.83s`＝零 failed；＋10 条来自新测试 `tests/test_c36_aggregate.py`＝加权和＋三道硬门＋温度不变性的第一批格子；⚠ 这批格第一版踩过「依赖未入库产物」的坑＝第一轮干净克隆读成 `1 failed`，返工改成合成腿＋入仓快照 `calibration/face_v2_row_snapshot.jsonl`；**摘掉新增文件仍 `859 in 22.18s`＝既有用例零变慢**。**C-36＝本仓库第一次改掉置信度合式**（连乘⇒人定权重加权和＋硬门；同码两版 v1 ECE 0.4212／AUC 0.4301／高档 0 ⇒ v2 0.0565／0.6010／高档 29、该箱 0.517＜基准 0.637＝**达标行仍未回答**）。**上一档 `859 passed`**（＝C-24 第二轮收口；未装 mcp `858 passed, 1 skipped`；两格 10-22 下午在 **C-24 第二轮（真数）收口** 上复放＝改前 `848 passed` ⇒ 改后 **`859 passed`**（＋11 条来自新测试 `tests/test_c38_assist_label.py`＝给 #38 辅助标注件补的第一批离线桩格；⚠ 那批格踩过一次环境污染＝`lock_local()` 直写 `os.environ`、monkeypatch 不回滚 ⇒ 测试里自己存还，见 `docs/dev-protocol.md` §5 第 14 条）。**C-24 已全部收口＝自标定真数 ECE 0.406688、高档覆盖率 0.0（0/226）**，第二轮只动标定数据与两份提案、`app/` 零字节。**上一档 `848 passed`**（＝C-34 收口；未装 mcp `847 passed, 1 skipped`；两格 10-22 深夜在 **C-34 收口**（第一轮直接通过）的两份新克隆上各复放＝改前 `836 in 22.60s` ⇒ 改后 **`848 passed`**（×5 无 flake 22.19～22.35 s）、`--collect-only` 整套 848、新文件 `tests/test_c34_level_official.py` collect **12**＝**＋12−0**（**C-34 只加展示字段＝`confidence.py`／`evidence.py` 双零 diff、跨树 `confidence.json` 逐位相同＝换分 0**）。**上一档 `836 passed`**（＝C-33 收口；未装 mcp `835 passed, 1 skipped`；两格当时在两份新克隆上各复放＝改前 `822 in 26.43s` ⇒ 改后 `836 passed`（×5 无 flake 26.69～27.44 s）、`--collect-only` 整套 836、新文件 `tests/test_c33_submission_side.py` collect **14**＝**＋14−0**（**C-33 只动提交导出层＝`confidence.py`／`evidence.py` 双零 diff，跨树量到 `confidence.json` 逐位相同＝换分 0**）。**上一档 `822 passed`**（＝C-24 收口；未装 mcp `821 passed, 1 skipped`；两格当时在两份新克隆上各复放＝改前 `808 in 22.56s` ⇒ 改后 `822 passed`（×5 无 flake 21.98～22.22 s）、`--collect-only` 整套 822、新文件 `tests/test_c24_calibration.py` collect **14**＝**＋14−0**；**C-24 零生产代码改动＝`git diff --stat app/` 为空**；⚠ **#99 已摘**＝`tests/test_c25_errors_sensitivity.py` 那条 CLI 用例现带 `.venv` skip 守卫，没建 venv 的裸克隆读到的是 skip 而不是 `1 failed`。**上一档 `808 passed`**（＝C-32 收口；未装 mcp `807 passed, 1 skipped`；两格当时在两份新克隆上各复放＝改前 `791 in 22.17s` ⇒ 改后 `808 passed`（×5 无 flake 21.66～21.99 s）、`--collect-only` 整套 808、新文件 `tests/test_c32_causal_claim.py` collect **17**＝**＋17−0**）。**上一档 `791 passed`**（＝C-7 收口；未装 mcp `790 passed, 1 skipped`；两格当时在两份新克隆上各复放＝改前 `765 in 22.05s` ⇒ 改后 `791 passed`（×5 无 flake 21.50～21.79 s）、`--collect-only` 整套 791、新文件 `tests/test_c7_ingest_max.py` collect **26**＝**＋26−0**）。**上一档 `765 passed`**（＝C-23 收口；干净 `git clone` 上实测复现；未装 mcp 那格＝`764 passed, 1 skipped`；⚠ **裸 `git clone` 要先有 `.venv` 才测得出这两个数**——`tests/test_c25_errors_sensitivity.py` 里那条 CLI 用例硬用 `<repo>/.venv/bin/python` 起子进程且没有 skip 守卫，而 venv 不入库 ⇒ 没建就按第 1 步建（或临时 `ln -s` 指过来），否则读成 `1 failed, 746 passed` 不是代码坏。两格 2026-10-22 夜在 **C-23 收口**（两轮通过）的两份新克隆上各复放＝改前 `747 in 21.22s` ⇒ 改后 **`765 passed`**（连跑 6 次无 flake，21.4～21.8 s）、`--collect-only` 整套 765、新文件 `tests/test_c23_corpus_max.py` collect **18**＝**＋18−0**。**上一档 `747 passed`**（＝C-13 收口；未装 mcp 那格＝`746 passed, 1 skipped`；两格 2026-10-22 傍晚在 **C-13 收口**（一轮通过）的两份新克隆上各复放＝改前 `732 in 21.44s` ⇒ 改后 `747 passed`，`--collect-only` 整套 747、**＋15−0**＝新文件 `tests/test_c13_dependency.py` 15 条（⚠ 数用例数以 `--collect-only` 为准：`grep -c "^def test_"` 会被测试里那句字面量 `"^def test_"` 污染成 16）。**以下＝上一档 `732`（C-25 收口）的条数账**＝未装 mcp `731 passed, 1 skipped`；两格 2026-10-22 下午在 **C-25 收口**（第一轮直接通过）的两份新克隆上各复放＝改前 `720 in 21.37s` ⇒ 改后 `732 passed`（架构师 ×3＋执行方 ×5 无 flake，20.99～21.66 秒），`--collect-only` 整套 732、条数账＝新文件 `tests/test_c25_errors_sensitivity.py` **＋13**、`tests/test_c21_sample_face.py` **−1**（摘掉"断言别人不改 `score_official.py`"那颗 `git diff` 型常驻用例＝常驻用例不许依赖工作树瞬时状态，见 `docs/dev-protocol.md` §5）。以下括号内＝**上一档 `720`（C-21 收口）当时的原始读数**，保留作条数账＝本机装了 mcp 的全绿数；干净 `git clone` 上实测复现，不依赖任何本机未入库产物；未装 mcp 那格＝`719 passed, 1 skipped`，两格 2026-10-22 中午在 **C-21 收口**（第二轮通过）的两份新克隆上各复放＝改前 `699 in 21.41s` ⇒ 改后 `720 passed`，架构师 ×3＋执行方 ×5 无 flake（20.7～21.7 秒），`--collect-only` 整套 720 条、**新增 21 条只来自 `tests/test_c21_sample_face.py`**（样本面披露＋`conclusion_face` 唯一实现＋两道闸反向格＋R1 两格）；模拟「未装 mcp」请用 `sys.meta_path` 插 finder 抛 **`ModuleNotFoundError`**——pytest 9.1.1 的 `importorskip` 只吞它，抛父类 `ImportError` 会读成 `1 failed`（finder 骨架＝`def find_spec(self, name, path=None, target=None)` 里比 `name == "mcp" or name.startswith("mcp.")` 再抛；另一条等价路＝临时移走 `site-packages/mcp`，两法读数相同——10-22 下午 C-25 复放各量过一次＝`731 passed, 1 skipped`）。**上一档 `699 passed`／未装 mcp `698 passed, 1 skipped`＝C-20 收口（10-22 凌晨，新增 21 条、连跑 8 次无 flake 20.8～21.6 秒）。****这 21 条新用例几乎不花时间**（699 in 21.41s ⇒ 720 in 20.7～21.7s＝纯函数与文本断言，既有用例零变慢）。上一档 678（C-29 收口）比 C-19 那版慢约 1.8 秒，**而且那次慢在既有用例上**（摘掉新增的 `tests/test_c29_precedent.py` 仍是 `660 passed in 21.03s`，C-19 收口时是 19.3 秒）＝同类事件对照台账在 `accounting` 缺键时会全量重算，已登记待办（`docs/HANDOFF.md` task #65），不影响判绿。测试全 stub，无需密钥、不产生任何真实模型调用（测试期有守卫）。

## 第 3 步：离线演示（断网/无 key 时的完整演示兜底）

```bat
:: Windows
.venv\Scripts\python scripts\demo_offline.py
```

**通过判据**：先后打印**三个案例**的完整研判报告（含多分析师归并、
冲突消解、少数意见、防篡改校验 ✅），产物分别写入
`cases/demo-solid-state/out_offline/`（固态电池科研情报）、
`cases/bi-delivery-risk/out_offline/`（数据中台交付风险企业情报）与
`cases/rumor-vs-official/out_offline/`（自媒体票数 vs 官方通报，
程序按证据强度翻案），各含 `report.json` / `report.md` / `chain.jsonl`。
桩客户端离线模拟了三分析师协同全流程，演示「系统长什么样」足够用。
（2026-10-19 在干净 `git clone` 上实测：`grep -c '^# 研判报告'` ＝ **3**，
三个 `out_offline/` 目录齐全，跑完 `git status` 仍干净——产物全在 `.gitignore` 内。）

## 第 4 步：在线真实研判（需要 API key）

1. 复制 `.env.example` 为 `.env`，填入 `OPENAI_API_KEY` 与
   `OPENAI_BASE_URL`（key 向项目负责人索取，**不在仓库里、不在 U 盘
   明文里**）。可选 `config.json` 覆盖模型清单（参考 `config.example.json`）。
2. 运行：

```bat
:: Windows（案例一：固态电池科研情报）
.venv\Scripts\python -m app.pipeline cases\demo-solid-state

:: 案例二：数据中台交付风险企业情报（可选，工作台多一个案例可切）
.venv\Scripts\python -m app.pipeline cases\bi-delivery-risk
```

**通过判据**：打印真实研判报告，产物写入 `cases/<案例>/out/`；
`chain.jsonl` 为全程哈希链研判日志。案例二由
`scripts/build_bi_case.py` 从脱敏语料构建（机构名已匿名化，可直接对外演示）。

### 大库选料（默认阈值 50，自动）

不配环境变量时，阈值默认 **50**：这个案例信源数达到 50 才选料；
演示小案例（几份到十几份）整卷研判，不会出现「选料范围」，也不建
`.corpus/`。达到阈值后，材料写入 `cases/<案例>/.corpus/` 本机 SQLite，
再按议题收成小案卷；报告开头、工作台判断区固定写出
「库内 N 份 / 本次纳入 M 份」，并注明未入选不等于已审完全库。

要强制关掉：`.env` 写 `VERITAS_CORPUS_SELECT_MIN=0`。
要改阈值：写其他正整数。这是本机索引，不是外接业务库或搜索集群。

检索默认：有模型时按规则做同义/近义拓展（主体锁定、禁捏造数字与换主体，
机械闸过滤后追加进 BM25）；词表（停工/停产等）作兜底。研判议题仍是用户原话。
指代不完整且有上一句时，允许用上一句主体补全后再拓展。失败则退回「原问+词表」。
`VERITAS_QUERY_REWRITE=0` 只关模型拓展，词表仍在。

## 第 5 步：可视化工作台（演示主入口）

```bat
:: Windows
.venv\Scripts\python -m app.server --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`（默认只读本机）。工作台读取
`cases/*/out*/report.json`：证据链三级下钻（结论→逐字引文→原文段落）、
置信度分量面板、冲突消解与少数意见视图、信源可信度调整、删证据/改权重
即时重算、哈希链校验与「篡改演示（改一字即红）」。新增**机械核对警示**
面板（计算复算/数字溯源/计数/归并守恒/质证引用/议题前提，零 LLM 即时
重算——人工改结论引入未溯源数字会当场亮黄灯）与 **skill 注册表**状态
（触发才注入提示词，每条纪律配一道机械闸）。人工修改会以 human
事件追加进 chain.jsonl（修改可审计，链仍自洽）。若 8765 被占用换端口
即可；依赖 fastapi/uvicorn（已在 requirements.txt，一键脚本会装）。

## 第 6 步：MCP 标准接口（可选，接第三方智能体）

```bat
:: Windows
.venv\Scripts\python -m pip install mcp
.venv\Scripts\python -m app.mcp_server
```

以 MCP（Model Context Protocol）stdio 服务把研判能力暴露为 6 个标准
工具：`list_cases` / `get_report` / `verify_chain`（零 LLM，离线可验，
任何 MCP 客户端如 Claude/其他智能体可直连）+ `ingest_external`
（第三方结论按契约入卷并过引文机械闸，零 LLM）+ `run_analyst` /
`run_judgment`（发起真实研判，需第 4 步的网关配置；与 CLI 同一条
管线代码路径）。mcp 1.x/2.x 均兼容；不装 mcp 不影响前 5 步与测试。

## 故障排查

| 症状 | 处理 |
|---|---|
| pytest 中文报 `UnicodeEncodeError` / GBK | 用 `python -X utf8 -m pytest tests -q`；本仓库 IO 已全钉 UTF-8，该错只会来自第三方输出 |
| 控制台中文乱码 | `chcp 65001` 后重跑 |
| pip 装不上 litellm | 加镜像参数重试；仍失败可暂时跳过——`pytest` 与 `demo_offline` 不依赖 litellm（懒加载），仅第 4 步在线研判需要 |
| PDF 信源摄取报 pypdf 缺失 | `pip install pypdf`（PDF 是可选格式，demo 案例不含 PDF 不影响演示） |
| 要开源版式增强（跨页表等） | `pip install -r requirements-docling.txt` 后设 `VERITAS_PDF_BACKEND=docling`；失败自动回退 pypdf；默认 U 盘包不装 Docling |
| venv 激活后命令找不到 | 直接用绝对路径调 python：`.venv\Scripts\python`（Win）/ `.venv/bin/python`（Mac） |
| 测试出现 failed | 把失败摘要原样反馈给开发者；在修好前用第 3 步离线演示兜底。未装 mcp 时零 failed，1 条 skip 属正常，只来自 `tests/test_mcp_server.py` 的 `importorskip("mcp")`；装完 mcp 再跑必须零 failed 且零 skipped |

## 仓库速览（供智能体理解上下文）

- 入口：`python -m app.pipeline <case_dir>`；编排：`app/pipeline.py`
- 三级证据链与判分：`app/core/`（evidence / citation_check / confidence / conflicts / hashchain）；
  置信度对外交**两套档、永不合并**（`confidence.py`）＝`band` 绝对档（0.8＝官方达标行原文「高置信（≥0.8）」、0.5＝我方设定）
  与 `band_rel` 同跑次分位档（`quantiles(n=100, inclusive)` 的 34%/67% 切点、按**整份提交物 pooled**、样本<2 记「低」）；
  退化分布两条规则＝`score<=0 ⇒ 低`、切点重合（`hi-lo < 1e-9`）时并列在切点上的记第四档「**不可分**」（不是缺数据、也不是低），
  规则串当场披露切点原样值与并列真数
- 零 LLM 机械闸族：`app/core/audit.py` 汇总（numeric_check 计算/溯源/计数、
  discourse_check 质证/仲裁/措辞、premise_check 前提）；skill 注册表
  `app/core/skills.py`（触发才注入，无闸的 skill 不注册）
- 模型自适应：用户接什么模型未知——生产路径先 1 次探测给模型打
  「纪律遵从」档（`app/llm/profile.py`，机械判分），noncompliant 档
  自动改注强化规则 + derived 结构化契约并启用打回修复环
  （`app/agents/repair.py`，变好才接受）；VERITAS_PROBE=0 可关
- 输入生命周期：事实对撞台账（`app/core/fact_ledger.py`，信源数字
  打架机械检出，注入提示词+报告兜底）、时序核对（`app/core/
  temporal_check.py` 时效闸/as-of 闸，manifest 可声明 published_at）、
  相关性分层（`app/core/relevance.py`，零相关不进提示词但报告披露）、
  案卷内同类事件对照台账（`app/core/precedent.py`，零 LLM：按同一指标＋
  同一主体把「早期同类事件 ↔ 本案」配成行，两端引文必须在原文段落里
  逐字可定位（定位不到就不生成）、缺时点走 `gate_applicability` 通道披露
  「时点不明，未据此排序」；报告新增「## 同类事件对照（案卷内）」一节，
  展示双上限＝24 行且本节字数 ≤ 其余各节合计的 1/3，被截断时节内披露
  「还有 N 行未展示」而台账本体仍全量、`accounting["precedent"]["n_rows"]`
  记真数；外部先验句只出黄灯旗＋标「不计入置信度」，
  **不加权重、不注入提示词**）
- 检索与预算：纯 Python BM25 段级精排（`app/core/bm25.py`）+ 跨信源
  轮转装箱（`app/core/material.py`，`material_char_budget` 默认 8 万字，
  装不下全披露）；ES/向量不进默认链（方案文档「规模化路径」）
- 复合输入：压缩包安全拆封（`app/ingest/archive.py`，zip-slip/炸弹/
  数量/嵌套四道边界，7z/rar 明确不支持并披露）；链接清单检测与显式
  抓取（`app/ingest/links.py`，默认只披露，`--fetch-links`/
  `VERITAS_FETCH_LINKS=1` 开启，结果缓存 `cases/*/.fetched/` 可离线
  重放）；子目录有界遍历；**输入分诊账本**（`app/ingest/triage.py`，
  每个文件一条路由记录，报告渲染）；图片 OCR 转码（`app/ingest/ocr.py`，
  网关视觉探测通过时逐字转写为低可信派生信源，VERITAS_OCR=0 关）；
  相关性人工裁决（`POST /api/source/relevance`，入链）
- 开发日志：`docs/dev-journal.md` ——全部批次的问题来源/方案决策/
  改动/验证/**已知开放问题**，供外部 AI 审查代码用（附攻击面清单）
- 智能体：`app/agents/`（base=Agent 基类+Analyst、panel 三视角编队
  **支持 roster per-agent model（多模型异构是配置项）**、arbiter
  归并/冲突/质证/仲裁、chair 主席汇总层——正面回答议题，四道闸+零
  LLM 模板兜底、repair 修复环、registry 智能体清单——答辩架构图
  数据源，见 docs/agents-overview.md）
- 演示案例：`cases/demo-solid-state/`（固态电池科研情报）与
  `cases/bi-delivery-risk/`（数据中台交付风险企业情报，信源已脱敏；
  由 `scripts/build_bi_case.py` 从外部语料构建）；manifest.yaml 声明信源类型与可信度
- 路线图：`ROADMAP.md`；架构说明：`README.md`
- **跨工具交接**：`docs/HANDOFF.md`（当前进度／未决／下一步／坑）＋`docs/handoff-archive.md`（§0 历史条目 ①…〔53〕，2026-10-22 深夜整段搬出、编号不变、一字未改；读到「§0〔52〕」这类旧引用而 HANDOFF 里没这个号，就去归档文件按同号查，别整份重读）；官方评分口径与场景重判七条见
  `docs/contest-briefing-2026-10-14.md`、`docs/scenario-review-2026-10-14.md`，宣讲会长文转写在 `docs/contest-transcript-2026-10-14.txt`
