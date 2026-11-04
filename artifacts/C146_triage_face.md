# C-146 分流读数（仪器现抄，非手打）

## 反事实比对（合成夹具）
- 改前码 ref＝`03bfd4a`；夹具行数＝14（快照同数＝14）
- 剥掉 triage 五键后与改前逐字节不同的行数＝**0**（0 ⇒ 分流没吃掉 conflict_class／disposition／reason／entry）
- 两轴正交（triage ∩ conflict_class 空）＝True
- 禁品面命中（gold／金标／coeff／weights／w_eff）＝[]

## 三案例真产物分流（开旗 demo_offline）
- demo 退出码＝0；四档合计＝{"date_offset": 0, "oral_misread": 3, "other": 3, "true_oppose": 1}（Σ＝7）

| 案例 | 行数 | by_class | by_disposition | by_triage |
|---|---|---|---|---|
| demo-solid-state | 1 | {"cross_day": 0, "unknown_time": 0, "same_window": 0, "unclassified": 1} | {"dissent": 1, "keep": 0, "undecided": 0} | {"date_offset": 0, "oral_misread": 0, "other": 1, "true_oppose": 0} |
| bi-delivery-risk | 5 | {"cross_day": 0, "unknown_time": 4, "same_window": 0, "unclassified": 1} | {"dissent": 1, "keep": 0, "undecided": 4} | {"date_offset": 0, "oral_misread": 3, "other": 1, "true_oppose": 1} |
| rumor-vs-official | 1 | {"cross_day": 0, "unknown_time": 0, "same_window": 0, "unclassified": 1} | {"dissent": 1, "keep": 0, "undecided": 0} | {"date_offset": 0, "oral_misread": 0, "other": 1, "true_oppose": 0} |

### 逐行（谁被判成哪档）

- demo-solid-state `CFL-22c098fc96`（conflict_pair／2030年量产可行性）class=unclassified disp=dissent → **triage=other**·pair_mechanically_undetermined
- bi-delivery-risk `LEDGER-0001`（fact_ledger／需求分析师）class=unknown_time disp=undecided → **triage=oral_misread**·metric_not_quantity
- bi-delivery-risk `LEDGER-0002`（fact_ledger／回款比约定时间晚）class=unknown_time disp=undecided → **triage=oral_misread**·single_segment_two_numbers
- bi-delivery-risk `LEDGER-0003`（fact_ledger／备份保留周期）class=unknown_time disp=undecided → **triage=oral_misread**·metric_not_quantity
- bi-delivery-risk `LEDGER-0004`（fact_ledger／非结构化数据）class=unknown_time disp=undecided → **triage=true_oppose**·distinct_values_unknown_time
- bi-delivery-risk `CFL-995d5ddf77`（conflict_pair／数据中台业务线交付健康度）class=unclassified disp=dissent → **triage=other**·pair_mechanically_undetermined
- rumor-vs-official `CFL-4da5a925c7`（conflict_pair／是否因资金链断裂停工）class=unclassified disp=dissent → **triage=other**·pair_mechanically_undetermined

## 跨树同形·旗＝off（改前树 /Users/liuboyu/Developer/veritas-c146-base vs 本枝）
- report.json 差异路径数＝0；其中落在 conflict_trace 面外的＝0
- report.md 规范化同形＝3/3
- 逐文件：{"demo-solid-state/report.json": {"n_diff_paths": 0, "all_inside_conflict_trace": true}, "demo-solid-state/report.md": {"same": true}, "demo-solid-state/chain.jsonl": {"n_lines": [24, 24], "same_multiset": true, "same_multiset_wo_trace_payload": true}, "bi-delivery-risk/report.json": {"n_diff_paths": 0, "all_inside_conflict_trace": true}, "bi-delivery-risk/report.md": {"same": true}, "bi-delivery-risk/chain.jsonl": {"n_lines": [24, 24], "same_multiset": true, "same_multiset_wo_trace_payload": true}, "rumor-vs-official/report.json": {"n_diff_paths": 0, "all_inside_conflict_trace": true}, "rumor-vs-official/report.md": {"same": true}, "rumor-vs-official/chain.jsonl": {"n_lines": [24, 24], "same_multiset": true, "same_multiset_wo_trace_payload": true}}

## 跨树同形·旗＝on（改前树 /Users/liuboyu/Developer/veritas-c146-base vs 本枝）
- report.json 差异路径数＝53；其中落在 conflict_trace 面外的＝0
- report.md 规范化同形＝3/3
- 逐文件：{"demo-solid-state/report.json": {"n_diff_paths": 11, "all_inside_conflict_trace": true}, "demo-solid-state/report.md": {"same": true}, "demo-solid-state/chain.jsonl": {"n_lines": [24, 24], "same_multiset": false, "same_multiset_wo_trace_payload": true}, "bi-delivery-risk/report.json": {"n_diff_paths": 31, "all_inside_conflict_trace": true}, "bi-delivery-risk/report.md": {"same": true}, "bi-delivery-risk/chain.jsonl": {"n_lines": [24, 24], "same_multiset": false, "same_multiset_wo_trace_payload": true}, "rumor-vs-official/report.json": {"n_diff_paths": 11, "all_inside_conflict_trace": true}, "rumor-vs-official/report.md": {"same": true}, "rumor-vs-official/chain.jsonl": {"n_lines": [24, 24], "same_multiset": false, "same_multiset_wo_trace_payload": true}}
