"""输入分诊路由表：每个文件一条路由记录，账本全量可审计。

路由taxonomy（load 期落账本 dossier.triage；零相关/重复为派生视图，
报告渲染期另行合并）：
- native             直接入卷研判
- archive_expanded   压缩包拆封（条目另行逐条分诊）
- archive_unsupported 不支持的压缩格式（7z/RAR）
- fetched            链接清单抓取为派生信源（web，先验 0.3）
- links_disclosed    链接清单未抓取（默认关，披露）
- image_disclosed    图片未转码（披露，OCR 关闭/不支持时终态）
- image_transcoded   图片转写为派生信源（低可信，meta.ocr）
- layout_parsed      版式引擎入卷（Docling 等，派生低可信，meta.parser）
- empty              空文件/扫描件（零段落不入卷）
- invalid_parse      解析失败（披露，不炸 run）

分诊是确定性代码不是 skill：skill 注册表只放「教模型的提示词纪律」，
守门判定永远归代码（可复现、可审计、不可被注入）。
"""

from __future__ import annotations

ROUTE_LABEL: dict[str, str] = {
    "native": "入卷研判",
    "archive_expanded": "压缩包拆封",
    "archive_unsupported": "不支持格式",
    "fetched": "链接抓取",
    "links_disclosed": "链接未抓取",
    "image_disclosed": "图片披露",
    "image_transcoded": "图片转写",
    "layout_parsed": "版式解析入卷",
    "empty": "空文件",
    "invalid_parse": "解析失败",
    "unsupported_format": "格式暂不支持",
    # 派生路由（零相关/重复在渲染期出现，同表统一标签）
    "zero": "零相关排除",
    "dup": "重复排除",
    "promoted_low": "兜底升档",
}

ROUTE_ORDER: dict[str, int] = {
    "native": 0, "fetched": 1, "image_transcoded": 2, "layout_parsed": 3,
    "archive_expanded": 4, "promoted_low": 5,
    "links_disclosed": 6, "image_disclosed": 7,
    "zero": 8, "dup": 9, "empty": 10,
    "invalid_parse": 11, "archive_unsupported": 12, "unsupported_format": 13,
}
