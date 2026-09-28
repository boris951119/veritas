"""研判提示词：分析师角色契约与输出 schema。"""

from __future__ import annotations

from app.core.evidence import Dossier

SYSTEM_TEMPLATE = """你是一名{persona}。你的任务：针对给定研判议题，基于【仅限】提供的资料段落得出结构化结论。

铁律（违反任何一条即视为无效输出）：
1. 每条结论必须挂至少 1 条证据；证据的 quote 必须是对所指段落原文的【逐字摘录】，一个字都不能改写；
2. quote 里如需省略，用「……」占位，省略两端的文字必须仍与原文逐字一致；
3. segment_id 必须取自下方资料清单中列出的编号，不得编造；
4. 只依据资料说话；资料未覆盖的问题就下「资料不足」类结论并说明缺口；
5. relation 判定要诚实：只有资料给出了机制或因果论证才用 causation，共变现象用 correlation，专家观点用 expert_judgment；
6. level 按证据等级标注：A=同行评审/一手数据，B=单一正式研究或官方文件，C=预印本/灰色文献，D=自媒体/无出处转述。

输出 JSON（不要输出任何 JSON 以外的文字）：
{{
  "conclusions": [
    {{
      "statement": "一句可判定的结论",
      "evidence": [
        {{"quote": "逐字引文", "segment_id": "SRC1#s2", "relation": "causation|correlation|expert_judgment", "level": "A|B|C|D", "note": "一句话说明该证据支撑什么"}}
      ]
    }}
  ]
}}
{extra}
"""

REDACTION_NOTE = """\n注意：本轮研判为独立研判，你不知道也无法参考其他分析师的结论；请独立给出你自己的判断。"""


def render_system_prompt(persona: str, isolated: bool = True) -> str:
    extra = REDACTION_NOTE if isolated else ""
    return SYSTEM_TEMPLATE.format(persona=persona, extra=extra)


def render_segments_block(dossier: Dossier, per_segment_chars: int = 700) -> str:
    """把案卷全部段落渲染为带编号的资料清单（提示词侧截断防爆上下文）。"""
    lines: list[str] = [f"研判议题：{dossier.question}", "", "资料清单："]
    for src in dossier.sources:
        lines.append(f"◆ 来源 {src.id}《{src.title}》（类型 {src.source_type.value}）")
        for seg in src.segments:
            text = seg.text
            if len(text) > per_segment_chars:
                text = text[:per_segment_chars] + "……"
            lines.append(f"[{seg.id}] ({seg.locator}) {text}")
        lines.append("")
    return "\n".join(lines)
