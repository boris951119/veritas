# C-143 — 树22 冲突留痕可用化（借 C-123 窄修，不合旧枝）

> 判定＝**YES**（旗 VERITAS_CONFLICT_TRACE 出厂默认仍关）。
> 本刀只动出口面：app/pipeline.py 两处 kept 白名单登记 conflict_trace ＋ app/export/official.py 旗开必写回放面（空态也写）。判定／打分／选段／装箱零改动；未合 C-123 整枝、未带回旧主线选料。

## 0. 不带编号的说明（这段给不看代码的人）

系统里有一把实验开关，打开后会把「资料里数字打架」的每一条按同窗／跨日／时点不明三类记下来，并写清处置（保留／少数意见／未决）。此前实测：开关打开后这些东西算得出来，却在写产物前被管线里一张「保留白名单」整个吃掉，交出去的文件里看不到——不是算不出，是算完被扔了。
修法沿用 C-123 的两处窄修：白名单登记这个键（两处都登记）；交卷面在「一条冲突都没检出」时也写一份空态文件并写明这是未检出、不等于资料无冲突。归并硬约束（同主体×同指标×可核验才合）＝有把握才动，本轮只记账不动判定（冲突数值线 Boyu 已拍 STOP）。

## 1. 腿A 出口面（零 LLM・确定性夹具・改前 vs 改后）

- 关旗臂字节等证（剥 elapsed 时戳后 report.json／report.md 与其余产物逐文件 sha8）：True
- 改前缺口复现：开旗臂 trace 文件写出＝False（键被白名单剥掉＝True）；零对撞臂文件写出＝False（空态静默＝True）
- 改后闭合：开旗臂键活过白名单＝True；空态文件＋真实题数原因句＝True
- 留痕行形状（处置行）：conflict_class＝unknown_time｜disposition＝undecided（未决）
- 旗出厂默认两棵树都关：True

## 2. 腿B 门控复刻（C-134 同尺・零 LLM・两旗臂）

- liuxiang：两旗臂逐位同＝True｜对 C-134 基线同＝True｜@7 12｜micro 0.5714｜g2c 1.0｜leak 0
- wanghong：两旗臂逐位同＝True｜对 C-134 基线同＝True｜@7 6｜micro 0.8571｜g2c 1.0｜leak 0

## 3. 腿C 真跑（本机 14B・零现金・生产入口 run_official_case）

- liuxiang/q_003｜墙钟 399.0s｜模型调用 12｜键活到产物＝True｜conflict_trace.json 写出＝True
- 留痕条数 5（台账对撞 3＋结论冲突对 2）｜三类分布 {'unknown_time': 3, 'same_window': 0, 'cross_day': 0, 'unclassified': 2}｜处置分布 {'keep': 0, 'undecided': 3, 'dissent': 2}｜覆盖 0.6｜结论 16 条

## 4. 判据逐条（按单里过线口径）

- g1_关旗与改前一致＝True
- g2_开旗出口在场_零调用＝True
- g3_旁证不掉＝True
- g4_旗默认仍关＝True
- g5_真跑出口在场＝True

## 5. 诚实披露

- 真跑＝一案一题、温度未钉、每臂 1 遍：只证「出口在场／不在场」，不比大小；留痕条数逐跑波动属模型采样，不是旗的效果。
- 关旗字节等证剥掉了 accounting.elapsed_s／steps 时戳与 report.md 那一行耗时数字（逐跑必变，与本次改动无关）。
- report.md／工作台未新增冲突留痕渲染（超出「最小借用」范围，报告面＝report.json accounting＋conflict_trace.json 回放面）。
- 归并硬约束最小闸未动＝只记账：动判定面须另开票（冲突数值线 STOP）。
- pytest：7 failed, 1262 passed, 1 skipped（7 红与基线 90a0608 同名单逐个一致：test_c19_pack_window m_production_messages_bite、test_c37 五颗、test_c73 kept 刀；本票新增 5 颗全绿）

## 6. 产物卫生

- 夹具文本全部合成（客户B回款率等占位句），无官方语料原文；真跑腿只记条数／分布／档位码，不落原文。
