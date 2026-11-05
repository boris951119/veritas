# C-122 件① — 引文核对失败成因（自家产物面・零模型调用）

- 面＝/Users/liuboyu/Developer/veritas/cases/*/out*/report.json｜坏文件跳过 0 份（跳过≠没失败，计数在场）
- 尺＝`check_evidence`（生产同一把）｜份数 34｜证条 982（在盒 792／已打回 190）｜判失败 187＝失败率 0.1904
- 打回清单里抠不到 segment_ids 的条数＝0（抠不到＝该条按 missing_seg 归类，桶名如实记，不当「通过」）
- 桶分布（全量）：pass_current_check 795｜fuzzy_close 106｜real_hallucination 70｜fmt_recoverable 10｜other_seg_hit 1
- 桶分布（在盒 kept＝真会进下一次打回的那批）：pass_current_check 792
- 桶分布（已打回 rejected）：fuzzy_close 106｜real_hallucination 70｜fmt_recoverable 10｜pass_current_check 3｜other_seg_hit 1
- 差异字符类直方图（失败引文里没对上的字）：other 875｜punct_ascii 801｜digit 137｜entity 24｜punct_cjk 19｜dash_wave 4
- 读数：失败 187/982＝0.1904｜A 面（排版归一化可救）＝10 条＝占失败 0.053｜B 面（近似转写可回贴）＝106 条＝占失败 0.567｜救不了（真胡编／挂错段／空引文）＝71 条
- 阈值＝ratio≥0.85 或 最长公共块≥max(8, 0.6×引文长)

