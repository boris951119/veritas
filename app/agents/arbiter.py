"""协同研判协调器：归并 → 冲突检测 → 质证辩论 → 仲裁。

语义判定（谁同义、谁冲突、谁有理）交给 LLM；机械侧（id 校验、证据
存在性、winner 合法性、证据加权对比）由 core/conflicts.py 程序把关。
每一步失败都降级不炸管线：归并失败→保留原结论；冲突检测失败→无冲突
清单；质证失败→跳过该侧直接仲裁；仲裁失败→冲突记为未消解。
全程由 pipeline 写 chain 留痕。
"""

from __future__ import annotations

from app.agents.base import extract_json
from app.agents.prompts import (
    ARBITER_SYSTEM,
    CONFLICT_SYSTEM,
    MERGE_SYSTEM,
    REBUTTAL_TEMPLATE,
    render_conclusions_block,
)
from app.core.conflicts import (
    ConflictPair,
    Resolution,
    compute_evidence_weight,
    validate_conflict,
)
from app.core.evidence import Conclusion, Dossier
from app.llm.model_client import ModelClient


class Coordinator:
    """归并/冲突/辩论/仲裁的 LLM 封装（client 可注入桩）。"""

    def __init__(self, client: ModelClient, model: str,
                 personas: dict[str, str] | None = None):
        self.client = client
        self.model = model
        self.personas = personas or {}

    # -- 归并 ------------------------------------------------------------

    def merge_conclusions(self, dossier: Dossier,
                          conclusion_ids: list[str]) -> list[str]:
        """同义结论归并成组；返回活跃结论 id（多数结论）清单。

        多人组物化：新建组结论继承成员全部证据（证据转挂）与全体署名，
        成员结论标 status="merged" 保留溯源。失败降级返回原清单。
        """
        active = [i for i in conclusion_ids if self._is_active(dossier, i)]
        if len(active) < 2:
            return active
        try:
            messages = [
                {"role": "system", "content": MERGE_SYSTEM},
                {"role": "user", "content": render_conclusions_block(dossier, active)},
            ]
            data = extract_json(
                self.client.chat(self.model, messages, json_mode=True).content)
            groups = [g for g in data.get("groups") or [] if isinstance(g, dict)]
        except Exception:
            return active  # 降级：不归并，全部保留

        merged_ids: list[str] = []
        seen: set[str] = set()
        for group in groups:
            member_ids = [str(m) for m in group.get("member_ids") or []
                          if str(m) in active and str(m) not in seen]
            if not member_ids:
                continue
            seen.update(member_ids)
            if len(member_ids) == 1:
                merged_ids.append(member_ids[0])  # 单人组：原结论即代表
                continue
            members = [dossier.conclusion(m) for m in member_ids]
            statement = str(group.get("statement") or "").strip() \
                or members[0].statement
            group_con = Conclusion.create(
                statement=statement,
                authors=sorted({a for m in members for a in m.author_names()}),
            )
            dossier.conclusions.append(group_con)
            # 证据转挂 + 同引文去重：不同分析师摘了同一段原话时只保留一条
            # （独立同证的"一致"信号由 confidence 的 agreement 分量体现，
            # 不该在证据计数里重复膨胀）
            seen_quote: set[tuple] = set()
            for member in members:
                for ev in dossier.evidences_of(member.id):
                    signature = (ev.quote.strip(), tuple(sorted(ev.segment_ids)),
                                 ev.relation, ev.level)
                    if signature in seen_quote:
                        continue  # 重复引文：留在成员上作溯源，不转挂
                    seen_quote.add(signature)
                    ev.conclusion_id = group_con.id
                    group_con.evidence_ids.append(ev.id)
                member.status = "merged"
            merged_ids.append(group_con.id)
        # LLM 漏掉的结论兜底收回（不允许任何结论无组丢失）
        merged_ids.extend(i for i in active if i not in seen)
        return merged_ids

    # -- 冲突检测 ----------------------------------------------------------

    def detect_conflicts(self, dossier: Dossier,
                         conclusion_ids: list[str]) -> list[ConflictPair]:
        """LLM 找冲突对 → 机械校验（id 存在、双方挂证）→ 只留合法对。"""
        active = [i for i in conclusion_ids if self._is_active(dossier, i)]
        if len(active) < 2:
            return []
        try:
            messages = [
                {"role": "system", "content": CONFLICT_SYSTEM},
                {"role": "user", "content": render_conclusions_block(dossier, active)},
            ]
            data = extract_json(
                self.client.chat(self.model, messages, json_mode=True).content)
            raw = data.get("conflicts") or []
        except Exception:
            return []
        pairs: list[ConflictPair] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            pair = ConflictPair(
                a_id=str(item.get("a", "")), b_id=str(item.get("b", "")),
                topic=str(item.get("topic", "")),
                description=str(item.get("description", "")),
            )
            if not validate_conflict(pair, dossier):
                pairs.append(pair)
        return pairs

    # -- 辩论（质证一轮，轮数护栏=1）---------------------------------------

    def run_rebuttals(self, dossier: Dossier, pair: ConflictPair) -> dict:
        """双方各一轮书面质证；单侧失败降级为空（另一侧仍可质证）。"""
        rebuts: dict[str, str] = {}
        for side, cid in (("a", pair.a_id), ("b", pair.b_id)):
            con = dossier.conclusion(cid)
            opponent_id = pair.b_id if side == "a" else pair.a_id
            opponent = dossier.conclusion(opponent_id)
            persona = self.personas.get(con.author, "独立分析师")
            opponent_evs = dossier.evidences_of(opponent_id)
            opponent_evidence = "；".join(
                f"『{e.quote[:60]}』({e.level.value})"
                for e in opponent_evs) or "（对方未挂证据）"
            try:
                text = self.client.chat(self.model, [
                    {"role": "system", "content":
                        REBUTTAL_TEMPLATE.format(
                            persona=persona, statement=con.statement,
                            conclusion_id=cid,
                            opponent_statement=opponent.statement,
                            opponent_id=opponent_id,
                            opponent_evidence=opponent_evidence)},
                ]).content.strip()
                if text:
                    rebuts[side] = text[:600]  # 质证长度护栏
            except Exception:
                continue  # 单侧质证失败降级
        return rebuts

    # -- 仲裁 ---------------------------------------------------------------

    def arbitrate(self, dossier: Dossier, pair: ConflictPair,
                  rebuts: dict | None = None) -> Resolution | None:
        """程序证据加权 + LLM 说理 → 裁决；失败返回 None（冲突未消解）。"""
        weight = compute_evidence_weight(pair, dossier)
        try:
            user = (
                f"{render_conclusions_block(dossier, [pair.a_id, pair.b_id])}\n\n"
                f"程序证据强度对比：{weight}\n"
                f"双方质证：\n- 甲方({pair.a_id})：{(rebuts or {}).get('a') or '（未质证）'}\n"
                f"- 乙方({pair.b_id})：{(rebuts or {}).get('b') or '（未质证）'}\n\n"
                f"冲突说明：{pair.description or pair.topic or '结论对立'}"
            )
            data = extract_json(self.client.chat(self.model, [
                {"role": "system", "content": ARBITER_SYSTEM},
                {"role": "user", "content": user},
            ], json_mode=True).content)
            winner = str(data.get("winner", "")).strip()
            if winner not in (pair.a_id, pair.b_id, "tie"):
                return None  # winner 非法 → 不消解
            return Resolution(
                winner_id=winner,
                method=("tie" if winner == "tie" else "arbitration"),
                rationale=str(data.get("rationale", "")),
                evidence_weight=weight,
                rebuts=dict(rebuts or {}),
            )
        except Exception:
            return None

    # ------------------------------------------------------------------

    @staticmethod
    def _is_active(dossier: Dossier, conclusion_id: str) -> bool:
        con = dossier.conclusion(conclusion_id)
        return con is not None and con.status == "majority" \
            and bool(dossier.evidences_of(conclusion_id))
