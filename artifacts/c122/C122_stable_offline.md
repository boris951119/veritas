# C-122 件②b — A＋B 零模型腿（自家产物面）

- 条数（能复原出 segment_ids 的）＝982
- 失败率：关 0.1904（187）→ 开 0.1487（146）＝降 0.0417
- 救回来：A 排版 10｜B 回贴 31｜仍失败 146｜两臂都过 795
- 反向腿（开旗反而更严）必须＝0，实测 0
- Σ 不变式 n_tot == pass_both + recovered_A + recovered_B + still_fail＝True
- 这面的构成（条数按案例目录）：{'bi-delivery-risk': 924, 'demo-solid-state': 23, 'rumor-vs-official': 18, 'user-20261008-144308': 17}｜最大一案占 0.941
- ⚠ 外部效度：这一面 **94% 来自 `bi-delivery-risk`**（自家脱敏演示案例）＝官方赛卷的产物不在 `cases/*/out*/` 里（跑批落 /tmp 与外部产物树），所以这一腿只证「机制在自家面上救回多少」，不等于官方题上的救回率；官方题上的真数只看件③ 真跑的 accounting。
