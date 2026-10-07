#!/usr/bin/env python3
"""生成两套比赛 PPT：交件方案版 + 现场演示讲解版。"""

from __future__ import annotations

import shutil
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

_REPO = Path(__file__).resolve().parent.parent
_OUT = _REPO / "dist"
_SHOTS = _REPO / "docs" / "ppt-shots"
_DESKTOP = Path.home() / "Desktop"

# 深色科技风（避免紫）
BG = RGBColor(0x09, 0x09, 0x0B)
FG = RGBColor(0xEA, 0xF2, 0xFF)
DIM = RGBColor(0x8A, 0xA0, 0xB8)
ACCENT = RGBColor(0x3D, 0xD6, 0xFF)


def _set_run(run, size=18, bold=False, color=FG, font="Microsoft YaHei"):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font
    try:
        run._r.get_or_add_rPr().set(  # type: ignore[attr-defined]
            "{http://schemas.openxmlformats.org/officeDocument/2006/main}eastAsia",
            font,
        )
    except Exception:
        pass


def _fill_bg(slide, prs):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG


def _title(slide, text, top=0.35, size=28):
    box = slide.shapes.add_textbox(Inches(0.6), Inches(top), Inches(12.1), Inches(0.7))
    tf = box.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = text
    _set_run(run, size=size, bold=True, color=ACCENT)
    return box


def _body(slide, lines, top=1.2, size=16, width=12.1):
    box = slide.shapes.add_textbox(Inches(0.6), Inches(top), Inches(width), Inches(5.8))
    tf = box.text_frame
    tf.word_wrap = True
    tf.clear()
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(8)
        run = p.add_run()
        run.text = line
        _set_run(run, size=size, color=FG if not line.startswith("·") else DIM)
    return box


def _notes(slide, text: str):
    slide.notes_slide.notes_text_frame.text = text


def _new(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _fill_bg(slide, prs)
    return slide


def _shot_slide(prs, title: str, filename: str, caption: str):
    """交件版产品截图页：标题 + 大图 + 一句说明。"""
    s = _new(prs)
    _title(s, title, top=0.25, size=24)
    path = _SHOTS / filename
    if path.is_file():
        # 16:9 工作台截图，尽量铺满
        s.shapes.add_picture(str(path), Inches(0.55), Inches(1.0),
                             width=Inches(12.2))
    else:
        _body(s, [f"（缺少截图 {filename}，请先抓取 docs/ppt-shots/）"],
              top=2.5)
    cap = s.shapes.add_textbox(Inches(0.6), Inches(6.95), Inches(12.1), Inches(0.4))
    tf = cap.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = caption
    _set_run(r, size=13, color=DIM)
    _notes(s, caption)
    return s


def build_submission() -> Path:
    """交件用：方案讲解，偏完整。"""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    s = _new(prs)
    box = s.shapes.add_textbox(Inches(0.8), Inches(2.2), Inches(11.5), Inches(2.5))
    tf = box.text_frame
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = "veritas"
    _set_run(r, size=48, bold=True, color=ACCENT)
    p = tf.add_paragraph()
    r = p.add_run()
    r.text = "多智能体可信研判与证据链溯源"
    _set_run(r, size=28, bold=True, color=FG)
    p = tf.add_paragraph()
    r = p.add_run()
    r.text = "OPC 2026 · AI for Science · 方案说明（交件版）"
    _set_run(r, size=16, color=DIM)
    _notes(s, "交件方案 PPT。现场演示请用另一套《现场讲解版》。")

    s = _new(prs)
    _title(s, "1. 我们解决什么问题")
    _body(s, [
        "痛点：AI 能写结论，却很难让人信结论。",
        "· 结论很自信，但说不清依据出自哪段原文",
        "· 多智能体只是简单投票，冲突被抹平",
        "· 报告生成后改了也不留痕，事后无法审计",
        "",
        "产品目标一句话：",
        "多视角独立判断 → 结论挂证据 → 证据接到原文 → 冲突能处理 → 人能改、改能查",
    ])

    s = _new(prs)
    _title(s, "2. 对照赛题五条硬需求")
    _body(s, [
        "① 多智能体协同：三视角硬隔离独立研判 → 归并 / 质证 / 仲裁 → 少数意见保留",
        "② 证据链自动构建：结论 → 逐字引文 → 原文段落；引文不过关就打回（零 LLM）",
        "③ 置信度量化：强度 × 覆盖 × 一致性，可解释、改完可重算（规则分，非概率）",
        "④ 冲突识别与消解：列冲突、质证、按证据强度裁决，落败意见不删",
        "⑤ 轨迹可视化 + 人改重算：工作台下钻 / 推理图；删证据改权重即时重算并入账本",
        "",
        "加分项：相关 vs 因果标注 · 哈希链防篡改 · MCP 标准接口",
    ], size=15)

    s = _new(prs)
    _title(s, "3. 产品形态：工作台怎么用")
    _body(s, [
        "用户路径：写下议题 → 添加资料（文件夹/文件）→ 开始研判 → 核对",
        "",
        "工作台里能做的事：",
        "· 三级下钻：结论 → 引文 → 原文",
        "· 看冲突、质证、裁决与少数意见",
        "· 改结论 / 调权重 / 删证据 → 置信度与综合意见重算",
        "· 核验账本；「改一字即红」篡改演示",
        "· 接入模型（Base URL + Key + 多模型 ID）；无 Key 可走演示桩",
        "",
        "三个案例同一引擎：固态电池 · 数据中台交付风险 · 谣言 vs 官方通报",
    ], size=15)

    # 交件无视频时，截图是评委「看见产品」的主通道——对齐演示三动作
    _shot_slide(
        prs, "产品演示① 工作台总览",
        "01-overview.png",
        "议题 → 资料 → 研判结果；右上角账本状态可核验",
    )
    _shot_slide(
        prs, "产品演示② 结论 → 引文 → 原文",
        "02-drilldown.png",
        "点「查看原文」：引文对得上资料段落，不是模型转述",
    )
    _shot_slide(
        prs, "产品演示③ 编数字亮黄牌",
        "03-yellow-flags.png",
        "结论里写入资料没有的「99%」→ 程序复核黄牌（来源外数字）",
    )
    _shot_slide(
        prs, "产品演示④ 改一字即红",
        "04-tamper-red.png",
        "篡改演示：诚实账本绿，内存改一处立刻红（磁盘不动）",
    )

    s = _new(prs)
    _title(s, "4. 为什么可信：模型主张，程序复算")
    _body(s, [
        "零 LLM 机械闸（可复现、可测试）：",
        "· 引文逐字核对 · 数字复算 / 溯源 · 归并守恒 · 质证与仲裁引用核对",
        "· 议题前提 · 时序 / as-of · 事实对撞台账 · 注入扫描",
        "",
        "协调不是投票：独立写 → 对立就吵 → 程序算证据强度 → 少数意见保留",
        "人是最高权限：改动进哈希链，可审计，也可一键重置",
        "",
        "诚实边界（答辩必讲）：",
        "· 置信度是规则融合分，不是校准概率",
        "· 因果是标注加权，不是完整因果推断引擎",
        "· 哈希链是过程账本，不是数字证书 PKI",
    ], size=15)

    s = _new(prs)
    _title(s, "4b. 评测三数（主张有实测）")
    _body(s, [
        "标注集 eval/benchmark.jsonl（≥30 条）· 脚本 scripts/run_eval.py",
        "",
        "· BM25 Recall@K —— 金标段落是否进 Top-K（含同义盲区探针）",
        "· 冲突召回率 —— 标注对立对的机械对立召回（可复现）",
        "· 编造检出率 —— 假引文必拒、真引文必过（主轴可信抓手）",
        "",
        "已知短板不藏：BM25 无语义（应收账款↔回款）；语义 rerank 是演进口子",
        "安全硬化（认证 / 签名密钥）属产品化，赛内讲清本机边界即可",
        "数字以现场重跑 eval-report.json 为准，不背死分数",
    ], size=15)

    s = _new(prs)
    _title(s, "5. 可复用与可对接（答辩重点）")
    _body(s, [
        "① 编队可配置：换 roster YAML 即换角色，协调流水线不变",
        "② 模型可替换：同一网关 / 多模型轮转；单模型也能跑完全流程",
        "③ 标准接口：MCP 六工具——读报告、验链、跑研判、外部结论入卷",
        "",
        "我们卖的是可信研判中枢，不是又一个封闭聊天机器人。",
        "第三方按同一证据契约接入；假引文仍过机械闸。",
    ])

    s = _new(prs)
    _title(s, "6. 交付与验证")
    _body(s, [
        "· 源码 + 一键部署（Windows / macOS），断网可用离线演示兜底",
        "· 自动化测试全桩零密钥全绿（持续回归）",
        "· 工作台可现场实测：下钻 / 改数字亮灯 / 篡改变红",
        "· 方案文档：docs/proposal.md 与正式版材料",
        "",
        "收束三句话：",
        "挂得住原文 · 吵得清并保留少数意见 · 改得明且入账本",
    ])

    s = _new(prs)
    box = s.shapes.add_textbox(Inches(0.8), Inches(2.8), Inches(11.5), Inches(2))
    tf = box.text_frame
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = "谢谢各位老师"
    _set_run(r, size=36, bold=True, color=ACCENT)
    p = tf.add_paragraph()
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = "veritas · 可信不是说得更像，而是当场能查"
    _set_run(r, size=16, color=DIM)

    _OUT.mkdir(parents=True, exist_ok=True)
    path = _OUT / "veritas-交件方案.pptx"
    prs.save(path)
    return path


def build_onsite() -> Path:
    """现场讲解用：短、跟演示动作对齐，备注里写口播。"""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    s = _new(prs)
    box = s.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.5), Inches(3))
    tf = box.text_frame
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = "veritas 现场演示"
    _set_run(r, size=40, bold=True, color=ACCENT)
    p = tf.add_paragraph()
    r = p.add_run()
    r.text = "只做三下：摸回原文 · 编数字亮灯 · 改一字即红"
    _set_run(r, size=22, color=FG)
    p = tf.add_paragraph()
    r = p.add_run()
    r.text = "工作台 http://127.0.0.1:8765/  ·  建议案例：固态电池 / 谣言vs官方"
    _set_run(r, size=14, color=DIM)
    _notes(s, "开场 25 秒。背一句：可信不是模型说得更像，而是三件事当场能查。")

    s = _new(prs)
    _title(s, "开场：我们不比谁写得更长")
    _body(s, [
        "多个角色先各自独立写结论，互相看不见。",
        "意见对立 → 质证 → 裁决；落败意见保留，不删。",
        "最后有一份综合意见，正面回答议题。",
        "",
        "今天只演示三个动作。",
        "（屏幕切到工作台，不要停在 PPT 上讲架构。）",
    ])
    _notes(s, "切工作台。案例用固态电池或谣言案。勿主动念闸族名单。")

    s = _new(prs)
    _title(s, "动作一：点开原文（约 70 秒）")
    _body(s, [
        "屏幕：证据与原文 → 点一条引文 → 「查看原文」",
        "",
        "口播要点：",
        "· 这不是模型转述，是从来源段落逐字摘出来的",
        "· 对不上原文的引文，进不了正式报告，会被打回",
        "· 这一步靠程序比对，不靠模型感觉像不像",
        "",
        "可选：指一下「少数意见」——吵输了还在，方便人再看一眼",
    ], size=16)
    _notes(s, "对照 docs/demo-script.md 动作一。综合意见每一点能点回结论。")

    s = _new(prs)
    _title(s, "动作二：改一个资料里没有的数字（约 80 秒）")
    _body(s, [
        "屏幕：在结论里加上「良率已达 99%」→ 保存改写",
        "",
        "同时发生两件事：",
        "1. 机械核对亮黄灯——原文里找不到这个数",
        "2. 顶部综合意见跟着改后的结论重写",
        "",
        "人可以改；编出来的数字不会假装没发生；操作记进日志。",
        "演示完可点「撤销改动」（也入链）。",
    ], size=16)
    _notes(s, "被施压改结论时：第一句说「可以，我们走修改流程」，不要偷改文件。")

    s = _new(prs)
    _title(s, "动作三：改一字即红（约 50 秒）")
    _body(s, [
        "屏幕：核验账本（绿）→ 演示篡改（红）",
        "",
        "口播要点：",
        "· 只在内存副本里改一处，磁盘文件不动",
        "· 诚实的是绿，改过的立刻红",
        "· 研判日志是账本，不是随便能改的文本",
        "",
        "收束三句：挂得住原文 · 人改得明 · 账本改一字就红",
    ], size=16)
    _notes(s, "收束后停。编队/MCP/置信度定义等评委问再答。")

    s = _new(prs)
    _title(s, "评委常问（备答，不要主动展开）")
    _body(s, [
        "和群聊 Agent 有何不同？→ 独立写、再裁决、输的留着、假引文打回",
        "0.73 是什么？→ 规则分不是概率；能拆开看、改完能重算",
        "断网 / 无 Key？→ 离线演示桩仍可完整跑通流程",
        "图片没读？→ 披露「没读」，假装读过比漏掉更贵",
        "怎么接到现有系统？→ MCP：读报告、验链、结论按契约入卷",
        "换题目还灵吗？→ 换资料夹 + 换议题；编队可用 roster 配置",
    ], size=15)
    _notes(s, "本页仅自己看。现场以工作台 live 为主，PPT 翻到动作页提醒节奏即可。")

    s = _new(prs)
    box = s.shapes.add_textbox(Inches(0.8), Inches(2.6), Inches(11.5), Inches(2.2))
    tf = box.text_frame
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = "现场主画面 = 工作台"
    _set_run(r, size=32, bold=True, color=ACCENT)
    p = tf.add_paragraph()
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = "PPT 只负责节奏；证据在屏幕上，不在幻灯片里"
    _set_run(r, size=16, color=DIM)

    path = _OUT / "veritas-现场讲解.pptx"
    prs.save(path)
    return path


def main():
    a = build_submission()
    b = build_onsite()
    _DESKTOP.mkdir(parents=True, exist_ok=True)
    for p in (a, b):
        dest = _DESKTOP / p.name
        shutil.copy2(p, dest)
        print(f"OK {p} -> {dest}")


if __name__ == "__main__":
    main()
