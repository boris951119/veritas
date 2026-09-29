"""研判提示词：分析师角色契约与输出 schema。"""

from __future__ import annotations

from app.core.evidence import Dossier

SYSTEM_TEMPLATE = """你是一名{persona}。你的任务：针对给定研判议题，基于【仅限】提供的资料段落得出结构化结论。

铁律（违反任何一条即视为无效输出）：
1. 每条结论必须挂至少 1 条证据；证据的 quote 必须是对所指段落原文的【逐字摘录】，一个字都不能改写——原文里的 Markdown 记号（如 **、#）与全半角标点（如 ： vs :）也必须原样保留；不要从表格不同单元格拼接句子；
2. quote 里如需省略，用「……」占位，省略两端的文字必须仍与原文逐字一致；
3. segment_id 必须取自下方资料清单中列出的编号，不得编造；
4. 只依据资料说话；资料未覆盖的问题就下「资料不足」类结论并说明缺口；
5. relation 判定要诚实：只有资料给出了机制或因果论证才用 causation，共变现象用 correlation，专家观点用 expert_judgment；
6. level 按证据等级标注：A=同行评审/一手数据，B=单一正式研究或官方文件，C=预印本/灰色文献，D=自媒体/无出处转述。
{skills_rules}
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


def render_system_prompt(persona: str, isolated: bool = True,
                         skills_rules: str = "") -> str:
    """系统提示词：persona + 隔离声明 + 条件触发的 skill 纪律块。"""
    extra = REDACTION_NOTE if isolated else ""
    return SYSTEM_TEMPLATE.format(persona=persona, extra=extra,
                                  skills_rules=skills_rules)


def render_segments_block(dossier: Dossier, per_segment_chars: int = 900) -> str:
    """把案卷全部段落渲染为带编号的资料清单（提示词侧截断防爆上下文）。

    截断上限须与 ingest.segment 的切段上限（900）对齐——低了会造出
    「段落尾部对分析师不可见」的盲区，表格型信源尤甚（看不见的原文
    只能靠模型脑补，诱发编造引文被打回）。"""
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


# ---------------------------------------------------------------------------
# 协同研判（归并 → 冲突检测 → 质证 → 仲裁）提示词
# ---------------------------------------------------------------------------

MERGE_SYSTEM = """你是研判协调员。多个独立分析师对同一议题给出了结论，语义相同或高度相近的结论要归并为一组，由组代表统一陈述。

规则：
1. 只按语义归并，不新增结论、不改写证据归属；
2. 每组合并陈述要保留各成员结论的实质内容，一句可判定的话；
3. 所有结论 id 必须恰好出现在一个组里（单人组就是它自己）。

输出 JSON（不要输出任何其他文字）：
{
  "groups": [
    {"statement": "合并后的结论陈述", "member_ids": ["CON-x", "CON-y"]}
  ]
}"""

CONFLICT_SYSTEM = """你是分歧审查员。针对归并后的结论清单，找出彼此矛盾、互斥或显著对立的结论对。

规则：
1. 只报告真实对立：同一问题上不可能同时成立的结论才算冲突；泛泛的不同侧重不算；
2. 每对冲突给出共享主题与一句话对立说明；
3. 没有真实冲突就返回空列表，不要硬凑。

输出 JSON（不要输出任何其他文字）：
{
  "conflicts": [
    {"a": "CON-x", "b": "CON-y", "topic": "共享主题", "description": "对立说明"}
  ]
}"""

REBUTTAL_TEMPLATE = """你原本以「{persona}」立场参与研判，得出了结论：

  「{statement}」（编号 {conclusion_id}）

现在进入质证环节。对方结论是：

  「{opponent_statement}」（编号 {opponent_id}）
其证据：{opponent_evidence}

请用不超过 150 字，针对对方结论与证据中最薄弱的一点提出质证（事实与逻辑层面，不要客套）。直接输出质证文字，不要 JSON。"""

ARBITER_SYSTEM = """你是仲裁者。两个结论对同一问题给出对立判断，双方已各出一轮质证。请依据证据裁决。

裁决依据（按优先级）：
1. 证据强度对比（程序按等级×信源可信度×因果性计算，已给出）；
2. 质证是否击中对方证据的真实缺陷（如引文断章、来源可信度低、相关冒充因果）；
3. 证据是否下钻到可靠原文。

规则：winner 必须是双方 id 之一，或 "tie"（双方证据势均力敌无法裁决时才允许）；rationale 不超过 120 字，说清判给谁、为什么。

输出 JSON（不要输出任何其他文字）：
{
  "winner": "CON-x 或 CON-y 或 tie",
  "rationale": "裁决理由"
}"""


def render_conclusions_block(dossier: Dossier, conclusion_ids: list[str]) -> str:
    """渲染结论清单（归并与冲突检测共用）：编号 | 署名 | 陈述 | 证据摘要。"""
    lines = ["结论清单："]
    for cid in conclusion_ids:
        con = dossier.conclusion(cid)
        if con is None:
            continue
        evs = dossier.evidences_of(cid)
        ev_briefs = []
        for e in evs:
            quote = e.quote[:50] + ("…" if len(e.quote) > 50 else "")
            ev_briefs.append(f"『{quote}』({e.level.value},{e.relation.value})")
        ev_brief = "；".join(ev_briefs) or "（无证据）"
        authors = "、".join(con.author_names()) or "未知"
        lines.append(f"[{cid}]（{authors}）{con.statement}\n    证据：{ev_brief}")
    return "\n".join(lines)

