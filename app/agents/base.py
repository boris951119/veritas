"""分析师智能体基座：独立研判 → 结构化结论 + 证据节点。

独立研判硬隔离（榜单硬需求 1）：每个分析师只拿到「议题 + 资料清单 +
自己的角色」，拿不到其他分析师的任何输出——隔离由提示词构造保证，
不在模型侧依赖自觉。
"""

from __future__ import annotations

import json
import re

from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    RelationKind,
)
from app.llm.model_client import ModelClient


def extract_json(text: str) -> dict:
    """从模型回复提取 JSON（容忍 ```json 围栏与前后杂讯）。"""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"回复中找不到 JSON 对象: {text[:200]!r}")
    return json.loads(candidate[start:end + 1])


class Analyst:
    """一个分析师 = 角色 persona + 模型客户端 + 结构化输出契约。"""

    def __init__(self, name: str, persona: str, client: ModelClient, model: str):
        self.name = name
        self.persona = persona
        self.client = client
        self.model = model
        self.profile_tier = "standard"  # 模型画像档位（probe 后由管线回填）

    def analyze(self, dossier: Dossier) -> list[Conclusion]:
        from app.agents.prompts import render_segments_block, render_system_prompt
        from app.core.skills import render_skills_rules

        messages = [
            {"role": "system",
             "content": render_system_prompt(
                 self.persona,
                 skills_rules=render_skills_rules(dossier, self.profile_tier))},
            {"role": "user", "content": render_segments_block(dossier)},
        ]
        response = self.client.chat(self.model, messages, json_mode=True)
        data = extract_json(response.content)
        return self._materialize(data, dossier)

    # ------------------------------------------------------------------

    def _materialize(self, data: dict, dossier: Dossier) -> list[Conclusion]:
        """模型 JSON → Conclusion + EvidenceNode（登记进案卷）。

        证据所指段落存在性在这里做第一道软校验（不存在的段落直接丢弃，
        引文逐字核对留给 citation_check 机械闸）。
        """
        conclusions: list[Conclusion] = []
        for item in data.get("conclusions") or []:
            if not isinstance(item, dict) or not str(item.get("statement", "")).strip():
                continue
            con = Conclusion.create(statement=str(item["statement"]).strip(), author=self.name)
            dossier.conclusions.append(con)
            note_suffix = self._derived_note(item)
            for ev in item.get("evidence") or []:
                if not isinstance(ev, dict):
                    continue
                seg_ids = [str(ev.get("segment_id") or "").strip()]
                if not seg_ids[0] or dossier.segment(seg_ids[0]) is None:
                    continue
                try:
                    relation = RelationKind(str(ev.get("relation") or "correlation"))
                except ValueError:
                    relation = RelationKind.CORRELATION
                try:
                    level = EvidenceLevel(str(ev.get("level") or "C"))
                except ValueError:
                    level = EvidenceLevel.C
                note = str(ev.get("note") or "")
                if note_suffix:
                    note = f"{note}；{note_suffix}" if note else note_suffix
                node = EvidenceNode.create(
                    conclusion_id=con.id,
                    quote=str(ev.get("quote") or ""),
                    segment_ids=seg_ids,
                    relation=relation,
                    level=level,
                    note=note,
                    author=self.name,
                )
                dossier.add_evidence(node)
            conclusions.append(con)
        return conclusions

    @staticmethod
    def _derived_note(item: dict) -> str:
        """结构化 derived 数组 → note 里的机械可复核算式行。

        noncompliant 档把「写算式」从劝说变成输出 schema 字段；即便模型
        懒散，只要填了 derived，物化器就归一成与 calc 闸同一口径的
        「计算:…」格式，保证可复算。"""
        parts = []
        for d in item.get("derived") or []:
            if not isinstance(d, dict):
                continue
            formula = str(d.get("formula") or "").strip()
            if formula:
                parts.append(f"计算:{formula}")
        return "；".join(parts)
