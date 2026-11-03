# C-145a — VERITAS_CONFLICT_TRACE 出厂默认开

> 判定＝**YES**（默认 True；关＝env VERITAS_CONFLICT_TRACE=0）。
> 本刀只翻默认＋改文档／图面「默认关」表述＋守护格翻向；判定／打分／选段／装箱零改动。附带一个真修：conflict_trace_enabled() 无参回退原先不读出厂默认（env 未设恒 False）＝翻默认后仲裁／导出挂点会静默不走——改为走 Settings.from_env()（默认＋env 叠加），本票新格当场咬住。

## 1. 出口面四臂（零 LLM・对撞夹具・改前 vs 改后）

- 显式关臂字节等证（与改前关旗臂逐文件 sha8）：True
- 旗开臂字节等证（与改前旗开臂逐文件 sha8）：True
- 改前默认臂静默（文件不出）＝True｜改后默认臂活（键活＋处置行）＝True

## 2. demo 冒烟（cases/demo-solid-state・零 LLM 全路径）

- 改后默认（未设 env）：conflict_trace.json 在场＝True｜detail 在场＝True
- 显式关：文件不在场（两棵树都＝True）
- 默认翻转由旗造成（改前 demo 静默→改后在场）＝True

## 3. 门控复刻（C-134 同尺・零 LLM・保险腿）

- liuxiang：两旗臂逐位同＝True｜对 C-134 基线同＝True
- wanghong：两旗臂逐位同＝True｜对 C-134 基线同＝True

## 4. 判据逐条

- g1_出厂默认True＝True
- g2_默认开出口在场＝True
- g3_显式关与改前同形＝True
- g4_旗开与改前同形＝True
- g5_默认翻转由旗造成＝True
- g6_旁证不掉＝True

## 5. 诚实披露

- demo 冒烟＝桩客户端零 LLM 全路径（与 demo_offline 同形状），不是 14B 真跑；真跑出口在 C-143 已证（留痕 5 条）。
- 关旗／旗开字节等证面剥 elapsed 时戳（逐跑必变）并排除 chain.jsonl／progress.json（逐跑日志面）。
- 架构图 s22b 弹窗＋树22 徽标同步改「默认开」；HANDOFF 里 C-118／C-115 历史条目的「默认关」是史实不改。
- pytest：7 failed, 1265 passed, 1 skipped（7 红与基线 f157b71 同名单逐个一致：test_c19_pack_window m_production_messages_bite、test_c37 五颗、test_c73 kept 刀；本票新增 3 颗全绿，另翻向 3 颗默认值守护格）

## 6. 产物卫生

- 夹具全合成；demo 腿只记文件在场／条数／空态布尔，不落原文。
