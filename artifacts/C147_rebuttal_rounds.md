# C-147 多轮质证——判定与读数（探针现抄）

判定：YES

## 闸（全 True 才 YES）

- g1_多轮在场_默认开＝True
- g2_真对立强制进＝True
- g3_逐轮闸在场＝True
- g4_语义吃other＝True
- g5_关旗与改前同形＝True
- g6_pytest红不扩＝True

## delta

- 默认开臂：n_pairs＝1、n_escalated＝1、rounds_used＝2、逐轮行 4 条全过闸、Resolution.rebuts 带第1轮/第2轮＝True、采信倾向 resolved＝True
- 关旗臂：accounting 键在场＝False（应为 False）、链校验＝True
- 基树臂（f9509a2 关旗同码）：链校验＝True
- 关旗 vs 基树：比较文件 3 个、差异文件 0 个（无）、两侧非空＝True、键集一致＝True
- 分流四腿：{"true_oppose_forced": true, "oral_misread_not_in": true, "other_same_subject_eaten": true, "other_no_subject_kept_out": true}
- pytest：7 failed, 1303 passed, 1 skipped in 57.56s

## 口径披露

- 合成夹具（客户B 极性对立对＋第三位空交付分析师），零网络零真实模型调用；ScriptedClient 脚本桩。
- 字节臂把逐次 uuid 生成 id（CON-12hex／CFL-10hex）按各文件首现序匿名化；归一化只剥 elapsed／时戳类键；chain.jsonl／progress／逐跑日志不入比较面。
- 关旗同形臂两侧文件数均非空（不做空比空）。
