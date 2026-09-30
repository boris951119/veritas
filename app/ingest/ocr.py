"""图片转码器：模型只当转码器——逐字转写、派生低可信信源、失败降级披露。

纪律（承自夹层设计讨论）：
- **只转写，不解读**：提示词强制逐字转写文字/数字/表格，读不清标
  [无法辨认]，禁止描述趋势/下判断——语义研判必须留在带证据链的
  主管线里，图片内容不得绕过机械闸获得任何判断权；
- **产物是派生信源**：可信度先验 0.3（转写数字可能错——OCR 把 512
  认成 52 时，低先验保证它在与原生文本冲突时输给仲裁加权），meta
  标注 ocr/from_file/model，证据等级由分析师标注定（通常 C/D）；
- **失败降级**：网关无视觉端点（1 次微型探测判定）或转写失败 →
  维持「未做 OCR」披露，绝不阻塞管线；
- 转码器输出与链接抓取同构：来源→派生信源→打标签→低先验→
  与本地文件同权过全套机械闸。

依赖：仅当研判用真实模型客户端时启用（生产路径）；桩/离线演示
不触发。探测 1 次 + 每图 1 次调用，温度 0。
"""

from __future__ import annotations

import base64
from pathlib import Path

from app.core.evidence import Segment, Source, SourceType
from app.ingest.segment import split_segments

# 1x1 灰 PNG：视觉能力探测用（最小合法图像，几乎零 token）
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNiAAAABgAD"
    "Njd8qAAAAABJRU5ErkJggg==")

_TRANSCRIBE_SYSTEM = (
    "你是 OCR 转写器。逐字转写图中全部文字、数字与表格（表格保持行列，"
    "用 | 分列）；看不清的部分写 [无法辨认]；禁止描述、判断、概括、"
    "补全或翻译。只输出转写文本，不要任何解释。")


def _vision_user(image_bytes: bytes, mime: str = "image/png") -> dict:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return {"role": "user", "content": [
        {"type": "text", "text": "请转写这张图片。"},
        {"type": "image_url",
         "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]}


def probe_vision(client, model: str) -> bool:
    """1 次微型调用探测网关有无图像输入能力（失败=无，不炸）。"""
    try:
        resp = client.chat(model, [
            {"role": "system", "content": _TRANSCRIBE_SYSTEM},
            _vision_user(_TINY_PNG)], json_mode=False)
        return bool(resp and getattr(resp, "content", "") is not None)
    except Exception:
        return False


def transcribe_image(client, model: str, image_bytes: bytes,
                     mime: str = "image/png") -> str:
    """单图 → 逐字转写文本；失败抛异常（调用方降级）。"""
    resp = client.chat(model, [
        {"role": "system", "content": _TRANSCRIBE_SYSTEM},
        _vision_user(image_bytes, mime)], json_mode=False)
    return (getattr(resp, "content", "") or "").strip()


def transcode_images(dossier, client, model: str) -> dict:
    """案卷内已披露的图片 → 派生低可信信源（逐张，失败逐张降级）。"""
    pending = [n for n in dossier.ingest_notes
               if n.get("kind") == "image_file" and n.get("path")]
    if not pending:
        return {"n_pending": 0, "n_transcoded": 0}
    if not probe_vision(client, model):
        dossier.ingest_notes.append({
            "file": "(图片转码)", "kind": "image_ocr_skipped",
            "detail": "网关不支持图像输入（或视觉端点不可用）——图片维持"
                      "「未转写」披露，请人工整理为文字材料",
        })
        return {"n_pending": len(pending), "n_transcoded": 0,
                "reason": "no_vision"}
    n_ok = 0
    for note in pending:
        path = Path(note["path"])
        try:
            image_bytes = path.read_bytes()
            text = transcribe_image(client, model, image_bytes)
        except Exception as exc:
            dossier.ingest_notes.append({
                "file": note["file"], "kind": "image_ocr_failed",
                "detail": f"转写失败（{type(exc).__name__}）——维持未转写披露",
            })
            continue
        if not text:
            continue
        source = Source.create(
            title=f"图片转写·{Path(note['file']).name}",
            source_type=SourceType.NOTE, credibility=0.3,
            meta={"ocr": True, "from_file": note["file"], "model": model})
        for i, seg in enumerate(split_segments(text)):
            source.segments.append(Segment(
                id=f"{source.id}#s{i + 1}", source_id=source.id, text=seg,
                locator=f"段 {i + 1}", index=i))
        dossier.add_source(source)
        n_ok += 1
        dossier.triage.append({
            "file": note["file"], "route": "image_transcoded",
            "reason": f"已转写为低可信派生信源（{len(source.segments)} 段，"
                      f"模型 {model}，数字建议人工核对）"})
        dossier.ingest_notes.append({
            "file": note["file"], "kind": "image_transcoded",
            "detail": f"已转写为派生信源 `{source.id}`（先验 0.3）——"
                      "转写文本经全套机械闸，数字建议人工核对原图"})
    return {"n_pending": len(pending), "n_transcoded": n_ok}
