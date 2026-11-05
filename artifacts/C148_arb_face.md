# C-148 仲裁路由＋轻裁——判定与读数（探针现抄）

判定：YES

## 闸（全 True 才 YES）

- g1_默认开仲裁留痕在场＝True
- g2_轻裁不叫模型_双方保位＝True
- g3_上下文片段在场＝True
- g4_路由与轻裁单元腿＝True
- g5_关旗与改前同形＝True
- g6_pytest红不扩＝True

## delta

- 默认开臂·真对立案：route＝llm_enriched、llm_called＝True、context_included＝True、提示词含程序侧片段＝True、仲裁调用 1 次、链校验＝True
- 默认开臂·误读案：route＝light_program、仲裁调用 0 次、终局 tie／tie、轻裁理由在场＝True、双方保 majority＝True
- 关旗臂：两案 accounting 键在场＝False／False（均应 False）、误读案仲裁调用 1 次（旧路照走）
- 基树臂（bf65d23 同码缺省）：两案链校验＝True／True
- 关旗 vs 基树：比较文件 5 个、差异文件 0 个（无）、两侧非空＝True、键集一致＝True
- 路由与轻裁腿：{"misread_routes_light": true, "true_oppose_routes_llm": true, "light_is_tie_no_false_inequality": true, "light_keeps_both_majority": true, "veto_face_hits": true, "context_carries_faces": true}
- pytest：7 failed, 1316 passed, 1 skipped in 57.42s

## 口径披露

- 两案合成夹具（真对立对＋误读对＋第三位空交付分析师），零网络零真实模型调用；ScriptedClient 脚本桩；误读对两侧证据等级错开（A/B）＝去并列，置信度并列不再吃线程调度噪声。
- 字节臂 id 匿名按**内容锚定**：CON 按 statement、EV 按（引文＋结论角色）、CFL 按（议题＋说明＋双方角色）排序赋 ANON 名——uuid 逐跑随机、面板三线程汇入序跨臂不定，首现序映射会被带偏；稳定面列表（conclusions／evidences／conflicts／synthesis／账本 pairs 等）映射后整项排序。文本面残留 id 折叠为 CON-X／EV-X／CFL-X（胜方翻面由 report.json 精确面看守）。
- 归一化只剥 elapsed／时戳类键与墙钟秒数；chain.jsonl／progress／逐跑日志不入比较面。
- 关旗同形臂两侧文件数均非空（不做空比空）。
