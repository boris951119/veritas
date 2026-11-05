# C-121 — 树17 点名名单「准度预滤＋名额硬帽」（实验旗默认关・不合 main）

> 枝 `qoder/c121-list-precision`（从 main `0e957fa` 开枝，**未**合 C-113 那套）。
> 旗＝`VERITAS_TREE17_LIST_PRECISION`，默认关；关旗＝零写入、零插入块。
> 读数全部现量：件①④ 零模型调用；件③ 走本机 Ollama 14B（`openai/veritas-qwen3-14b`、假密钥、零现金、不出公网业务接口）。
> 金标只在测量侧读，未进提示词／查询词表／生产判定；三项泄漏审计＝0（见下）。
> 判定＝**弱 YES・不合 main**（理由见 §5）。

## 1. 为什么做（只采 C-120 读数，不采它的说法）

C-113 开旗后 q_003 金标段 2.875 → 1.50（每臂 8 遍、置换 p＝0.007）＝可复现，不是抖动；机制＝模型照名单逐条交，而名单 10 段里只有 4 段是金标，名额总数没变、金标配比被非金标段换走。
本票只治这一件事：让进提示的名单更准（＋收紧名额），不动装箱、不动排序权重、不碰引文转写。

## 2. 主路径＝C（A 预滤＋B 硬帽的窄组合），规则与选它的数

规则（`app/core/tree17_list_precision.py` 顶部常量，出厂值）：

- 保留来源＝`conflict_pair`（冲突成对两端）＋`close_read`（细读段／既有 kg_focus）；
- 丢掉来源＝`role_official`（"看着像官方声部"）、`role_party`、`claim_alt`、`priority_head`、`in_box`；
- 名额硬帽＝5（候选上限仍是 10，但进提示只留前 5）；
- 分数门槛 `min_score=0.0`＝**今天不咬合**（12 题 0/120 触发），留着只作为后续收紧的挂钩，不为它编造判别力；
- 禁为凑满回填：合格候选不足 5 就交不足，绝不拿弱段补位。

选它用的数（件①＝四案 × 三题离线审计，`artifacts/C121_list_audit.md`／`.json`）：

- 按来源看金标准度：`close_read` 24/34＝0.706、`conflict_pair` 2/4＝0.5、`claim_alt` 1/4＝0.25、`role_party` 0/4＝0.0、**`role_official` 1/74＝0.0135**。
- 名单整体：未滤 120 条里金标 28 条＝准度 **0.233** → 滤后 32 条里金标 24 条＝准度 **0.75**（C-113 形状＝`all_with_role` cap10＝同一条 0.233，因它本来每人只点 10 段）。
- 代价（写清不藏）：盒内金标被名单盖到的比例 **0.667 → 0.571**（12 题共 42 段盒内金标，全名单点到 28 段、滤后名单点到 24 段＝少盖 4 段）。这条代价可接受是因为块里明写「未点名的段落仍可正常引用」＝丢的是"提醒"，不是"可见性"；而名单里的弱段丢的是真名额。
- `claim_alt` 虽然带题面词（听起来最该留），实测 4 条只 1 条金标＝拉低准度，本轮**丢**。

## 3. 实现落点（路径名）

- 新增 `app/core/tree17_list_precision.py`：`build_focus_candidates`（生成候选＋来源理由）／`filter_focus_list`（预滤＋硬帽，逐条记丢弃原因）／`apply_tree17_list_precision`（写 accounting）／`list_precision_prompt_block`（点名块）。
- `app/config.py`：`tree17_list_precision: bool = False`＋env `VERITAS_TREE17_LIST_PRECISION`＋config.json 同名键。
- `app/pipeline.py`：进盒后（`material_pack_selected` 写定之后）调 `apply_*`；accounting 白名单加 `tree17_list_precision`／`_active`／`tree17_list_must` 三键（旗关不写＝不进产物）。键名带 `tree17_list_` 前缀，避免与 C-113 的 `must_consider` 同名互踩。
- `app/agents/prompts.py`：`render_segments_block` 里在「资料清单」之前插入那块文字。名单段全部 ⊆ 已选盒，所以**不改 selected 集合＝纯插入**（这点和 C-113 的 `| must` 并集不同）。
- 新增 `tests/test_c121_list_precision.py`（7 颗格）与四个探针 `scripts/probe_c121_list_audit.py`／`probe_c121_q003_three_arm.py`／`probe_c121_pack_guard.py`／`probe_c121_face_bytes.py`。

## 4. 开／关（三臂）表・q_003・每臂 5 遍

`artifacts/C121_three_arm_stats.md`／`.json`（逐遍原始产物＝`artifacts/c121/three_arm.md`／`.json`；`stats_c121.py` 与 JSON 生成器 `make_c121_json.py` 同目录，重跑即可复现统计）：

- off（旗关）：L3 [2,2,3,3,4] 均值 **2.80**｜非金标被引均值 2.80｜名单非金标 0（无名单）｜doc_002#p3 5/5｜doc_012#p5 3/5｜逐字核对失败 12/31
- raw（开旗＋规则关掉＝C-113 形状的 10 段名单）：L3 [1,2,2,3,3] 均值 **2.20**｜非金标被引均值 2.80｜名单非金标均值 **2.80**｜doc_002#p3 2/5｜doc_012#p5 2/5｜逐字核对失败 20/27
- filt（开旗＋出厂规则＝5 段名单，其中金标 4 段）：L3 [2,2,3,3,4] 均值 **2.80**｜非金标被引均值 **2.20**｜名单非金标均值 **1.00**｜doc_002#p3 3/5｜doc_012#p5 **5/5**｜逐字核对失败 14/26
- 统计：off vs filt Δ＝0.0（分布逐遍相同，置换双侧 p＝1.0）；raw vs filt Δ＝0.6（p＝0.484＝n=5 判不动）；名单非金标 raw 2.8 → filt 1.0（Δ1.8，p＝0.0079）。
- 一条机制读数（比 p 值更有用）：模型是**按比例照名单交**的——raw 名单里 6 段非金标、每遍被引 2.8 段（≈47%）；filt 名单里只剩 1 段非金标、每遍被引恰好 1 段（100%）。所以浪费下降不是模型变乖，是我们把弱段从名单里拿掉了＝准度那条腿真的在承重。

与 C-120 对照一句：C-120 的「关／开」＝无名单 vs 10 段弱名单（Δ −1.375，p＝0.007），本票把同一棵树上"10 段弱名单"重跑成 raw 臂（Δ −0.6，p＝0.484），方向一致但**没复现出那个量级**＝n=5 不够，且 filt 与 off 打平这件事因此只能算「未亏」，不能算「追回」。

## 5. 判定＝弱 YES・不合 main

按票面门槛逐条对：

- 金标均值 ≥ 关臂：**过（等号 2.80＝2.80）**，但没有任何增益。
- 非金标浪费明显下降：**过**（名单内非金标 2.80 → 1.00 每遍，p＝0.0079；总非金标 2.80 → 2.20，未达显著）。
- leak＝0：**过**（三项：禁用键 0、块内金标原文 0、名单出盒 id 0；12 题离线＋5 遍真跑两侧都算过）。
- 旁证不掉：**部分未定**——装箱面（件④，零模型、两侧都取到数）L2 关 42 → 开 42、@7 关 27 → 开 27、12/12 题盒段数与盒内金标逐题相同＝这一条稳；刘翔分题 L3 只抽了一遍（q_002 平 2/5＝2/5，q_001 少 1 段 3/4→2/4）＝与 C-120 量过的 ±1 噪声同量级，**既未证实也未证伪**；doc_002#p3 开臂 3/5 vs 关臂 5/5，方向不利、未达显著。

不合 main 的理由（写死，别让下一轮顺手合）：① 主读数对 off 是持平不是增益；② raw 臂这轮没复现 C-120 的效应量级，说明 n=5 在这个尺度上判不动，要判「追回多少」得每臂 ≥8 遍；③ 旁证腿里"刘翔分题 L3／seen_not"只有 1 遍；④ 单题＋单模型＋温度未钉。

## 6. 复现

```
git clone -q /Users/liuboyu/Developer/veritas /tmp/c121/tree && cd /tmp/c121/tree
git checkout qoder/c121-list-precision
ln -s /Users/liuboyu/Developer/veritas/.venv .venv
PYTHONPATH=. .venv/bin/python scripts/probe_c121_list_audit.py           # 件① 零模型
PYTHONPATH=. .venv/bin/python scripts/probe_c121_pack_guard.py           # 件④ 零模型
PYTHONPATH=. .venv/bin/python scripts/probe_c121_face_bytes.py          # §8 反向腿 零模型
PYTHONPATH=. .venv/bin/python scripts/probe_c121_q003_three_arm.py --passes 5 --qid q_003
PYTHONPATH=. .venv/bin/python -m pytest tests/test_c121_list_precision.py -q
```

题面与预算来自 `/tmp/c85_k180/score_input.json`（四案 × 三题＝12 条；不在仓里，缺文件时探针直接退出并说明原因）；官方金标在仓外 `~/Desktop/veritas-testcases/样例集-拓尔思-20261012/`。

枝＝`qoder/c121-list-precision`（从 main `0e957fa` 开枝，未合 main、未 push）。**本产物里不写自己的 commit sha**＝那种自比字段永远慢盖章它的那一笔；tip 看交账那一行，或当场 `git -C /tmp/c121/tree rev-parse --short HEAD`。

## 7. 仪器坑与尾巴（本票这条测量线）

1. **件④ 第一版把 L2 全量成 0/0**＝我把 `l2_hits(gold, sel)` 的第二个参数传成了段 id 集合，而它要的是 `(doc_id, para_id)` 定位集——两侧都是 0 时"关＝开"这句照样成立，但那是一条空比空的假旁证。抓它的正是 @7 那列（同一个 gold、非 0）⇒ **写"不变／相同"类判据时，必须同时报一个已知非 0 的同源量做参照**。已改回 `selected_locs(d, sel)`，改后 L2 合计 42（＝件① 的盒内金标数 42，两把尺对得上）。
2. 「名单非金标被引」这一列在 off 臂恒为 0＝结构性（没名单），不能拿去算 off vs filt 的"浪费下降"显著性；有意义的对照只有 raw vs filt。我在统计产物里把它原样列出并注明。
3. 守护格差点写成自比断言（`len(kept) <= CAP`、`set(kept) <= KEPT_REASONS`——拿模块常量比常量，放宽即绿）。第一版刀电池里 K2 就是 0 红暴露的，已改成钉字面量（`CAP == 5`、`KEPT_REASONS == {close_read, conflict_pair}`）。重下后 8 把刀全见红：K1 翻默认值／K2 放宽来源／K3 抬硬帽／K4 丢弃明细清空／K5 over_cap 不记名／K6b 把真实段落正文塞进块／K7 给名单生成加 gold 形参／K9 n_dropped 写死 0。
4. 一把**死刀**（不算格子有牙）：「关旗仍然出块」——我改成"不检查 active 键"仍全绿，因为 `tree17_list_must` 只有开旗时才被写，关旗臂那块键不存在＝名单为空＝块为空串。这一风险面目前的真证据是跨树 sha（§8），不是常驻测试格。尾巴＝合入票若要一条行为腿，得让 pipeline 在关旗路径上也带上 accounting 检查。
5. 零引用闸这条我先写错、后当场量正（账记我）：原话"四个新探针没进豁免表＝合入前要补"。**实测**＝本枝 `test_c37_script_zero_ref_equals_exemption_registry` 的 live 清单 **17 条＝与主线逐字同数**，四颗 `probe_c121_*` 都不在其中。机制＝那颗闸扫的是「tracked 文件里有没有提到这个脚本名」，而本票 md 自己写了它们（md 已随枝入库＝被引用）。⇒ 真正的尾巴是反过来的：**若合入时不带 `artifacts/C121_*.md`，这四颗就变成零引用、必须补 `SCRIPT_ZERO_REF_EXEMPTIONS`**；带 md 一起合就不用补。
6. 温度口径冲突已按"与 C-120 同"执行＝**不钉**（票面写"温度钉死与 C-120 同"，而 C-120 实际未钉）。若要钉（例如全臂 temperature=0），那是改口径、会破坏与 C-120 的可比性，需单独拍。
7. **§8 那段原来只活在 stdout 里**＝本次把它做成探针时，第一版探针"旗开但名单 0 段、净插入 0 字"——因为我照着 C-120 的夹具只渲染资料面，忘了 `apply_tree17_list_precision` 是 `app/pipeline.py` 调的、探针这条路上没人调。差点产出一份"开旗也没动资料面"的假产物。修法＝探针里复刻 pipeline 那个 `if settings.tree17_list_precision` 分支，并加一颗 `leg_bit`（旗开且名单非空）当自检，`leg_bit=False` 或跨树 sha 不同就直接非零退出。**凡是"开旗 vs 关旗没差别"这类否定式读数，先证明开旗腿真的咬上了。**
8. 交付件里两处手打数字被机械核抓出来并订正（账记我）：盒内金标覆盖写成 `0.690→0.571（29→24）`，真数＝`0.667→0.571（28→24）`；`all_with_role` cap10 准度写成 `0.242`，真数＝`0.233`（与未滤同值，因 C-113 本来每人只点 10 段）。两份都是复算 `per_question` 求和对上的。**教训＝md 里的数字要么脚本现生成、要么当场求和复核，手打一遍就多一处可能编造。** 本次起的配套 `.json` 由 `artifacts/c121/make_c121_json.py` 从四份源 json 现抄生成，不手打。
9. 三臂 runner 的产物标题把题号硬写成了「q_003」，所以 q_001／q_002 那两份抽测件的标题也写着 q_003（正文与文件名是对的）。＝自家那条「仪器标题别硬写读数」的老规矩又踩了一次；本轮只跑了一次抽测所以没造成误读，**若下轮要批量跑题，先把标题改成从参数取题号**（否则两份同名不同题的产物摆在一起就会读错）。
10. 差点把 commit sha 写进本产物当"枝名／tip"字段＝自比型字段（盖章它的那一笔永远在后面，越补越慢）。已改成产物只写枝名＋「tip 当场读」，sha 只出现在交账那一行。同 §7 第 3 条那颗自比洞是一个病。

## 8. 关旗反向腿（字节不变＝跨两棵树自己量）

同一份夹具（刘翔 q_003、预算 12824、旗关）在两棵树上各渲染一次资料面并比 sha256 —— 本票把它做成了可重跑产物 `scripts/probe_c121_face_bytes.py` → `artifacts/C121_face_bytes.md`／`.json`（下面这些数就是它当场出的，不是旧 stdout）：

- 主线树 `/Users/liuboyu/Developer/veritas`（app/ 未动＝`0e957fa`）：22172 字、`b4ec07f862b3956e12295e29f13795bf12d54374d349fff999123414a3ac243b`
- 本枝树 `/tmp/c121/tree`：22172 字、同一个 sha ＝ **逐字相同**
- 关旗两棵树 accounting 里 `tree17_list*` 键都是空集（既有的 `tree17_cite` 两臂都在场＝不是本票写的）；开旗腿 `leg_bit=True`（名单 5 段真进了块），所以"净插入"那句不是空比空。
- 开旗臂同夹具资料面＝22336 字／公共前缀 42 字／公共后缀 22130 字／**净插入 164 字／被删原文 0 字**＝纯插入；名单 5 段全在盒内（出盒 id 0）。
- 开旗名单＝`doc_012#p5`、`doc_046#p3`、`doc_006#p3`、`doc_002#p3`、`doc_033#p5`（4 金标＋1 非金标＝与件① 的 q_003 行一致）。
- 参照 C-120 件① 的 22172 字（旧关臂面）＝三处数一致。

## 9. 全套回归

- 本枝 `pytest tests -q`＝**7 failed, 1216 passed, 1 skipped**（提交前 31.28s／提交后复跑 28.63s＝两次同数）。
- 主线同一命令（本轮实测对照）＝**7 failed, 1209 passed, 1 skipped in 31.77s**。
- 红名逐条相同（`test_c19_pack_window::test_m_production_messages_bite`、`test_c37_engineering_gates` 里那 5 颗、`test_c73_window_ledger::test_c73_knife_kept_drops_window_ledger_must_red`）＝本轮**没有新增红**；＋7 全来自 `tests/test_c121_list_precision.py`。
- 零引用闸那条红的 live 清单：本枝 17 条＝主线 17 条（同数），本票四颗探针没进这个清单（机制见 §7 第 5 条）。
- ⚠ 主线入库基线不是"零 failed"＝已知 7 红（State 2026-11-03 那格），本票没修它也没扩大它。
