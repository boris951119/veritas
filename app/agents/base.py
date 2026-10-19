"""智能体基座：Agent 抽象 + 分析师（独立研判 → 结构化结论 + 证据节点）。

独立研判硬隔离（榜单硬需求 1）：每个分析师只拿到「议题 + 资料清单 +
自己的角色」，拿不到其他分析师的任何输出——隔离由提示词构造保证，
不在模型侧依赖自觉。

Agent 基类是智能体的形式化锚点（答辩口径「每个智能体一个类、一个
职责」）：名字/角色/模型/客户端 + 画像档位。per-agent model：实例各
持自己的 model 字段（每次调用按实例传入）——多模型异构是配置项，
网关给几个模型就能异构几个。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.config import Settings
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    RelationKind,
    record_parse_drop,
)
from app.llm.model_client import ModelClient

AGENT_ROLE_ANALYST = "analyst"


@dataclass
class Agent:
    """智能体基类：身份（名字/角色设定）+ 执行资源（客户端/模型）。

    子类实现自己的职责方法（分析师=analyze，协调者=归并/冲突/质证/
    仲裁，主席=汇总…）——「按功能划分智能体」的类级形式化。"""

    name: str
    persona: str
    client: ModelClient
    model: str
    role: str = AGENT_ROLE_ANALYST
    profile_tier: str = "standard"  # 模型画像档位（probe 后由管线回填）
    # 构造时钉一份 Settings。analyze 热路径不得再 Settings.from_env()
    # （from_json 读盘会落进编队并行窗口，放大 ScriptedClient 抢答竞态）。
    settings: Settings | None = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = Settings.from_env()


def extract_json(text: str) -> dict:
    """从模型回复提取 JSON（容忍 ```json 围栏与前后杂讯）。"""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"回复中找不到 JSON 对象: {text[:200]!r}")
    return json.loads(candidate[start:end + 1])


_EMPTY_HEAD = 120
_EMPTY_TAIL = 80


def _empty_shape(raw: str, data: dict) -> str:
    """从真实响应归形态。不改 extract_json，也不改哪些结论入卷。"""
    text = (raw or "").lstrip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1:] if nl >= 0 else text
        text = text.lstrip()
    if text.startswith("["):
        return "conclusions 非列表"
    if not isinstance(data, dict) or "conclusions" not in data:
        return "缺 conclusions 键"
    cons = data.get("conclusions")
    if not isinstance(cons, list):
        return "conclusions 非列表"
    if not cons:
        return "conclusions 空列表"
    dicts = [x for x in cons if isinstance(x, dict)]
    if not dicts:
        return "元素全非对象"
    if all(not str(x.get("statement") or "").strip() for x in dicts):
        return "元素有对象但 statement 全空"
    return "其他"


def _empty_run(author: str, model: str, raw: str, data: dict) -> dict:
    text = raw or ""
    return {
        "author": author,
        "model": model,
        "content_chars": len(text),
        "top_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "shape": _empty_shape(text, data if isinstance(data, dict) else {}),
        "head": text[:_EMPTY_HEAD],
        "tail": text[-_EMPTY_TAIL:] if text else "",
    }


class Analyst(Agent):
    """分析师智能体：独立研判，产出结构化结论 + 逐字引文证据。"""

    def analyze(self, dossier: Dossier,
                focus_segment_ids: list[str] | None = None) -> list[Conclusion]:
        from app.agents.prompts import render_segments_block, render_system_prompt
        from app.core.skills import render_skills_rules

        messages = [
            {"role": "system",
             "content": render_system_prompt(
                 self.persona,
                 skills_rules=render_skills_rules(dossier, self.profile_tier))},
            {"role": "user", "content": render_segments_block(
                dossier, focus_segment_ids=focus_segment_ids)},
        ]
        # C-9 丙：发送前窗口估算披露（不截断、不收窄预算）。
        # settings 在构造时已钉死，这里不再读配置。
        self._disclose_prompt_window(dossier, messages, self.settings)
        response = self.client.chat(self.model, messages, json_mode=True)
        raw = response.content or ""
        self.last_raw = raw
        data = extract_json(raw)
        return self._materialize(data, dossier, raw=raw)

    @staticmethod
    def _disclose_prompt_window(dossier: Dossier, messages: list[dict],
                                settings) -> None:
        """超窗 → ingest_notes+triage；关闭检查 → accounting 记未检查。"""
        from app.core.prompt_guard import estimate_prompt_window

        rec = estimate_prompt_window(
            messages,
            window_tokens=int(settings.model_context_tokens),
            zh_chars_per_token=float(settings.zh_chars_per_token),
        )
        if not rec.get("checked"):
            dossier.accounting.setdefault("prompt_window", {
                "status": "unchecked",
                "detail": rec.get("detail") or "模型窗口未检查",
            })
            return
        if int(rec.get("overflow_tokens") or 0) <= 0:
            return
        # 多分析师同卷只写一条，避免三倍噪音
        if any(n.get("kind") == "prompt_over_window"
               for n in dossier.ingest_notes):
            return
        detail = str(rec["detail"])
        dossier.ingest_notes.append({
            "file": "",
            "kind": "prompt_over_window",
            "detail": detail,
            "est_tokens": rec["est_tokens"],
            "window_tokens": rec["window_tokens"],
            "overflow_tokens": rec["overflow_tokens"],
            "total_chars": rec["total_chars"],
        })
        dossier.triage.append({
            "file": "",
            "route": "prompt_over_window",
            "reason": detail,
        })
        dossier.accounting["prompt_window"] = {
            "status": "overflow",
            "est_tokens": rec["est_tokens"],
            "window_tokens": rec["window_tokens"],
            "overflow_tokens": rec["overflow_tokens"],
        }

    # ------------------------------------------------------------------

    def _materialize(self, data: dict, dossier: Dossier,
                     raw: str = "") -> list[Conclusion]:
        """模型 JSON → Conclusion + EvidenceNode（登记进案卷）。

        证据所指段落存在性在这里做第一道软校验（不存在的段落直接丢弃，
        引文逐字核对留给 citation_check 机械闸）。"""
        conclusions: list[Conclusion] = []
        for item in data.get("conclusions") or []:
            if not isinstance(item, dict):
                record_parse_drop(
                    dossier, conclusion_id="", author=self.name,
                    ev=item, kind="conclusion_not_object")
                continue
            if not str(item.get("statement", "")).strip():
                record_parse_drop(
                    dossier, conclusion_id="", author=self.name,
                    ev=item, kind="conclusion_empty_statement")
                continue
            try:
                con = Conclusion.create(statement=str(item["statement"]).strip(),
                                        author=self.name,
                                        coverage=item.get("coverage"))
            except ValueError:
                # 覆盖声明写歪了（partial 没写局限、unknown 没写理由、state 不是三态）：
                # 按「未声明」处理，让范围诚实闸把它亮出来——不许整轮研判因此崩掉，
                # 也不许悄悄替模型补一个 complete（那等于替它吹圆场）
                con = Conclusion.create(statement=str(item["statement"]).strip(),
                                        author=self.name)
            dossier.conclusions.append(con)
            note_suffix = self._derived_note(item)
            for ev in item.get("evidence") or []:
                if not isinstance(ev, dict):
                    record_parse_drop(
                        dossier, conclusion_id=con.id, author=self.name,
                        ev=ev, kind="not_object")
                    continue
                seg_ids = [str(ev.get("segment_id") or "").strip()]
                # 丢件必须可见（协议 §6 纪律 2）。两格分家，不许合成一条 reason。
                if not seg_ids[0]:
                    record_parse_drop(
                        dossier, conclusion_id=con.id, author=self.name,
                        ev=ev, kind="missing_id")
                    continue
                if dossier.segment(seg_ids[0]) is None:
                    record_parse_drop(
                        dossier, conclusion_id=con.id, author=self.name,
                        ev=ev, kind="missing_segment", segment_id=seg_ids[0])
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
        if not conclusions:
            dossier.empty_runs.append(
                _empty_run(self.name, self.model, raw, data))
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
