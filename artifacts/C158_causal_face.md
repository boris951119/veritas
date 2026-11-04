# C-158 因果面读数（脚本现抄，非手打）

- 跑产物根＝`/tmp/s4runs/time-20261104-135401`｜判据（跑前写死）＝{'verdict_cover': 1.0, 'reason_cover': 1.0, 'no_invention': True}
- 改前（stored 已落盘件）＝{'n_rows': 24, '四要素任一非空': 0, '四要素全非空': 0, '因果判定在场': 0, '判定理由非空': 0, '升档条件非空': 0, '三档分布': {'直接因果': 0, '间接传导': 0, '仅相关': 0}, '三档之外': {}, '证据等级在场': 0, '证据等级_官方在场': 0, '等级参与加权句在场': 0, 'degraded_reason 非空': 24}
- 改后（同产物真重导出，零模型调用）＝{'n_rows': 24, '四要素任一非空': 0, '四要素全非空': 0, '因果判定在场': 24, '判定理由非空': 24, '升档条件非空': 24, '三档分布': {'直接因果': 0, '间接传导': 0, '仅相关': 24}, '三档之外': {}, '证据等级在场': 24, '证据等级_官方在场': 24, '等级参与加权句在场': 24, 'degraded_reason 非空': 24}
- 闸：判定逐行在场？True｜理由逐行非空？True｜四要素非空率是否被本刀推动？False（必须为否＝不硬编）
- 三档覆盖：0.0 → 1.0｜理由覆盖：0.0 → 1.0
- 4.1.2 等级面（evidence.json，改前就已在场）＝{'n_rows': 240, 'files': 6, '等级与官方名同时在场': 240, '覆盖率': 1.0, '分布': {'D（自媒体转述）': 118, 'B（官方表态）': 97, 'A（官方程序记录）': 17, 'C（主流媒体）': 8}}

## 样例三行（判定＋理由＋升档条件＋等级）
- CON-e14fb41fb17b（q_001）＝仅相关｜等级 B（官方表态）｜理由 原声明因果，已按闸降级：缺主张卡要素：intervention、outcome、population、counterfa…｜升档 补齐主张卡缺项：intervention、outcome、population、counterfactual；补齐后由 …
- CON-c83c253b5507（q_001）＝仅相关｜等级 A（官方程序记录）｜理由 原声明因果，已按闸降级：缺主张卡要素：intervention、outcome、population、counterfa…｜升档 补齐主张卡缺项：intervention、outcome、population、counterfactual；补齐后由 …
- CON-bde35e819bb9（q_002）＝仅相关｜等级 A（官方程序记录）｜理由 原声明因果，已按闸降级：缺主张卡要素：intervention、outcome、population、counterfa…｜升档 补齐主张卡缺项：intervention、outcome、population、counterfactual；补齐后由 …

**裁决＝PARTIAL**
- 三档判定＋理由逐行在场（4.1.1 的「区分＋说明理由」面补齐）
- 但四要素非空率未变＝没有生产者填卡，本刀不硬编 ⇒ 4.1.1 拿不满
- 4.1.2 等级：evidence.json 早已在场（level＋level_official，且 LEVEL_WEIGHT 进 evidence_score），本刀把它带到 causal_evidence 面

产物卫生：本件只含 id／计数／比率与截断到 60 字的字段样例，不抄案卷原文。
