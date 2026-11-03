# C-125 测试树整线端口 — 交账（2026-11-03）

判定：**YES**。总旗 `VERITAS_TEST_TREE_LINE` 默认关（关＝今日生产字节路径零变），
开旗整链可跑、六案门控三门槛全过、泄漏 0、金标零进面。停在本枝，未合 main。
基线核对：`git rev-parse HEAD`＝`0e957fa…` ✓（首行核对通过后才动工）。

## 一、大白话：这事干了什么

把实验仓（veritas-obsidian-kg-exp）那棵测试树整棵搬进主仓产品线：过去只有
「字符预算＋BM25」的后半段，现在把前半段也接上了——KG 检索索引（原文∪摘要
BM25＋本机嵌入）→ 一筛多维加权池（R9/R21 系数，只活在一筛）→ 二筛密度盒
（可变 k∈[3,7]、通稿簇保一、冲突成对、密度条≥2/3）→ 交卷窄面（rank 序＋
洗净 pairs＋树17 细读信号，系数零过面）→ tree17 引用层（只读盒，不重装箱）。
一句话：C-124 证明「在旧盒上贴标签」没用；C-125 换掉的是盒本身。
默认全关——不开旗的主仓和今天逐字节一样。

## 二、基线与枝

- 基线：main tip `0e957fa`（核对通过）。
- 枝：`qoder/c125-test-tree-port`（自基线开枝），提交 `a7b8bcf`（35 文件）。
- 未合 main、未 push、未开 PR。

## 三、件① 盘点（四条，见 §七详表）

1. 主仓已有：C-107 窄面契约／C-108 密度桥后半段／C-109 BM25 池／C-111
   短盒回灌（缺 KG 前端、多维一筛、权威二筛、tree17 实体层）。
2. 实验仓独有、本次端口 27 模块：graph／index_build／ollama_client／
   recall_arms／inbox_rerank／stage1_pool／r8_fit／r9_buckets／r21_coeff／
   multidim_weight／stage1_claim_holes／stage2_authority／box_filter／
   slice_dims／slices／query_expand／query_views／portable_tags／
   channel_tier／opposition_patch／r14_stages／r15_stage2／summarize／
   summary_slots／eval_metrics／layer_boundary／tree17_cite；
   tag_schema／config 对齐实验 HEAD（config 只订正根路径）。
3. 旗与边界：总旗默认关＝C-108 密度桥路径零变；层闸三道审计
   （FORBIDDEN_PACK_KEYS 13 键）＋pipeline 侧 assert_clean_pack_kwargs。
4. C-124 失败面：生产提示是焦点面、盒内 top3 不在面上，annotate 无对象；
   整线补的正是上游换盒。

## 四、端口实施要点

- 27 模块零第三方依赖（stdlib＋app.core／app.ingest＋urllib 本机 ollama）。
- R9 拟合系数随仓数据文件 `app/kg_lab/r9_coeff.json`（27 键）——只进一筛
  打分，不进 pack kwargs／窄面。
- 运行时缓存（实验仓摘要 34M＋嵌入 90M）暖拷到主仓 `.kg_lab_vault`／
  `.kgcache`（gitignore，不进库；缺文件优雅回退）。
- 金标隔离闸不为端口开口：实验仓 slices.py 里读官方答案文件的
  questions_from_conclusions 等评测侧四函数迁到 scripts/ 评测侧，app 层
  零答案文件读（主仓既有隔离格保持咬合）。
- 嵌入不可达＝显式降级词面并披露（`kg_test_tree.embed.status=
  fallback_lexical`），不静默、不崩管线。

## 五、关旗不变证明

- 跨树字节等证：tip（`/tmp/c124/tip` @ `0e957fa`）vs 枝，同案同题关旗跑
  C-108 密度桥→pack：off_surface_sha16 `c6ff9d478007b287`、
  off_sel_sha16 `be657d8db1e7dbde`（362 段）两树逐位同。
- 整套测试：`7 failed / 1219 passed / 1 skipped`＝基线同 7 红
  （c19/c37×4/c38/c73）＋10 颗新格全绿
  （tests/test_c125_test_tree_line.py：默认关三读点／整链契约／确定性／
  降级披露／零金标／写账／系数文件）。

## 六、开旗六案门控（scripts/probe_c125_six_case_gate.py，零 LLM，墙钟 387.6s）

复刻腿（R44 同尺，R44 期望全命中，漂移零）：
- liuxiang（回归）微密度 57%｜@7=12（期望 12）
- jilong／us_cn_ai（冒烟）各 67%｜@7=6
- wanghong（holdout）86%｜kh_th 80%｜ai171 80%｜@7=6/4/5
- 金标→细读（计划层）六案全 1.0
- 交卷窄面泄漏＝0

生产链现场腿（零金标、density_cut=True）：
- 盒内金标密度 分子/分母＝30/44＝68.2%（微均）；案均 70.6%——≥2/3 达标
- liuxiang 单案 4/9＝44% 未达（k=3 小盒）——如实记录，不凑尺
- 三门槛：①holdout≥2/3＋不掉＋刘翔@7=12 ✓　②金标→细读全 1.0 ✓
  ③零泄漏 ✓ → READY=YES

旁证：刘翔@7 B＝12 ✓；leak＝0 ✓；「holdout L2=29」口径在 R40–R44 工件
定位不到该键（读数没量过）——以 R44 三门槛＋逐字复现为旁证尺，
holdout 宇宙内金标（可定位上界）＝19+11+24=54。

## 七、卫生与产物

- 产物零官方原文（只 id／计数／sha8）；金标只进量尺面。
- 交付：artifacts/C125_test_tree_port.md＋.json；
  artifacts/c125/C125_six_case_gate.md＋.json；scripts/probe_c125_six_case_gate.py。
- 参照工件：实验仓 artifacts/R44_six_case_gate.md（sha8 f940b00f）／.json
  （sha8 a40e26f8）。

## 八、未合 main 声明

本枝停在 `a7b8bcf`，不合 main、不 push、不开 PR（工单第八节停线令）。
11-4 中午可跑门控：达成（开旗整链可跑＋关旗逐字节不变）。
