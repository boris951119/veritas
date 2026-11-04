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
    CONFLICT_JUDGE_SYSTEM,
    CONFLICT_SYSTEM,
    MERGE_SYSTEM,
    REBUTTAL_REPLY_TEMPLATE,
    REBUTTAL_TEMPLATE,
    render_conclusions_block,
)
from app.core.conflict_pairing import (
    build_candidate_pairs,
    drops_record,
    subject_mismatch_reason,
)
from app.core.conflicts import (
    ConflictPair,
    Resolution,
    compute_evidence_weight,
    prefer_stronger_side,
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

        两段：① LLM 语义归并（判「语义相同或高度相近」）；② 机械归并补一轮
        （core/merge_mechanical：同主体×同议题×同极性，零 LLM）。第②段专治
        模型判得保守时「24 条结论归并 0 组」——客户拿到没去重的清单、
        一致性分量被单署名压死。多人组物化：新建组结论继承成员全部证据
        （证据转挂、同引文去重）与全体署名，成员标 status="merged" 保留溯源。
        LLM 段失败只降级掉①，②照常。
        C-145：①的每个 ≥2 人组先过归并硬约束闸（同主体×同指标×可核验，
        随 VERITAS_CONFLICT_TRACE；否决组成员保持独立并留痕），
        ②的分组键本来就含这三条，不重复过闸。
        """
        active = [i for i in conclusion_ids if self._is_active(dossier, i)]
        if len(active) < 2:
            # 早退也必须记账：否则「没有归并记录」与「没跑归并」在产物里长一样
            dossier.accounting["mechanical_merge"] = {
                "n_llm_groups": 0, "n_mech_groups": 0, "n_members_absorbed": 0,
                "n_cross_author_groups": 0,
                "note": f"活跃结论仅 {len(active)} 条，未进入归并环节",
            }
            # C-145：旗开留「闸在场」账（无组可查＝核查 0 组）
            from app.core.merge_gate import write_accounting
            write_accounting(
                dossier, n_checked=0, blocked=[],
                note=f"活跃结论仅 {len(active)} 条，未进入归并环节")
            return active
        groups: list = []
        try:
            messages = [
                {"role": "system", "content": MERGE_SYSTEM},
                {"role": "user", "content": render_conclusions_block(dossier, active)},
            ]
            data = extract_json(
                self.client.chat(self.model, messages, json_mode=True).content)
            groups = [g for g in data.get("groups") or [] if isinstance(g, dict)]
        except Exception:
            groups = []           # 降级：只掉语义归并，机械闸仍补

        merged_ids: list[str] = []
        llm_group_ids: list[str] = []
        seen: set[str] = set()
        # C-145：归并硬约束闸（随 VERITAS_CONFLICT_TRACE；旗关＝改前行为）
        from app.core.merge_gate import (
            block_row, check_group, gate_active, write_accounting,
        )
        gate_on = gate_active()
        n_checked = 0
        blocked_rows: list[dict] = []
        for group in groups:
            member_ids = [str(m) for m in group.get("member_ids") or []
                          if str(m) in active and str(m) not in seen]
            if not member_ids:
                continue
            seen.update(member_ids)
            if len(member_ids) == 1:
                merged_ids.append(member_ids[0])  # 单人组：原结论即代表
                continue
            n_checked += 1
            if gate_on:
                check = check_group(dossier, member_ids)
                if not check["ok"]:
                    # 整组否决：成员保持独立（宁可留重复，不可错并），
                    # 正反判断随后由冲突配对接住（同主体极性对立→强制候选）
                    blocked_rows.append(
                        block_row(member_ids, check,
                                  index=len(blocked_rows) + 1))
                    merged_ids.extend(member_ids)
                    continue
            members = [dossier.conclusion(m) for m in member_ids]
            statement = str(group.get("statement") or "").strip() \
                or members[0].statement
            group_con = self._materialize(dossier, members, statement)
            merged_ids.append(group_con.id)
            llm_group_ids.append(group_con.id)
        # LLM 漏掉的结论兜底收回（不允许任何结论无组丢失）
        merged_ids.extend(i for i in active if i not in seen)
        if gate_on:
            write_accounting(dossier, n_checked=n_checked,
                             blocked=blocked_rows)
        return self._mechanical_pass(dossier, merged_ids, llm_group_ids)

    @staticmethod
    def _materialize(dossier: Dossier, members: list[Conclusion],
                     statement: str) -> Conclusion:
        """成员结论 → 组结论：新建代表、证据转挂 + 同引文去重、成员标 merged。"""
        from app.core.scope_state import Coverage

        group_con = Conclusion.create(
            statement=statement,
            authors=sorted({a for m in members for a in m.author_names()}),
            # 覆盖声明不许在归并这一步蒸发：成员里最保守的那份往上并
            coverage=Coverage.merge_declarations([m.coverage for m in members]),
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
            member.group_id = group_con.id  # 守恒闸按此回溯成员
        return group_con

    @staticmethod
    def _mechanical_pass(dossier: Dossier, active_ids: list[str],
                         llm_group_ids: list[str]) -> list[str]:
        """机械归并补一轮；组结论用成员原句做代表（不造新句，防概括漂移）。"""
        from app.core.merge_mechanical import (
            enabled, mechanical_groups, merge_stats)

        if not enabled():
            dossier.accounting["mechanical_merge"] = {
                "n_llm_groups": len(llm_group_ids), "n_mech_groups": 0,
                "n_members_absorbed": 0, "n_cross_author_groups": 0,
                "note": "机械归并已停用（VERITAS_MECH_MERGE=0，A/B 对照组）"}
            return active_ids
        groups = mechanical_groups(dossier, active_ids)
        absorbed: set[str] = set()
        new_groups: list[str] = []
        for member_ids in groups:
            members = [dossier.conclusion(m) for m in member_ids
                       if dossier.conclusion(m) is not None]
            if len(members) < 2:
                continue
            group_con = Coordinator._materialize(dossier, members,
                                                 members[0].statement)
            absorbed.update(m.id for m in members)
            new_groups.append(group_con.id)
        dossier.accounting["mechanical_merge"] = merge_stats(
            dossier, groups, llm_group_ids)
        if not absorbed:
            return active_ids
        return [i for i in active_ids if i not in absorbed] + new_groups

    # -- 冲突检测 ----------------------------------------------------------

    def detect_conflicts(self, dossier: Dossier,
                         conclusion_ids: list[str]) -> list[ConflictPair]:
        """程序候选（主体×议题）→ LLM 判真对立 → 主体闸；丢弃入账。"""
        active = [i for i in conclusion_ids if self._is_active(dossier, i)]
        if len(active) < 2:
            dossier.accounting["conflict_drops"] = drops_record(
                [], n_candidates=0, n_accepted=0)
            return []

        candidates = build_candidate_pairs(dossier, active)
        cand_keys = {
            tuple(sorted((c["a"], c["b"]))) for c in candidates
        }
        forced_keys = {
            tuple(sorted((c["a"], c["b"])))
            for c in candidates if c.get("forced_polarity")
        }
        drops: list[dict] = []
        raw: list = []
        used_judge = False

        if candidates:
            used_judge = True
            try:
                lines = ["候选冲突对（只许从中挑选）：", ""]
                for i, c in enumerate(candidates, 1):
                    ca = dossier.conclusion(c["a"])
                    cb = dossier.conclusion(c["b"])
                    lines.append(
                        f"{i}. a={c['a']}「{(ca.statement if ca else '')[:60]}」"
                        f" vs b={c['b']}「{(cb.statement if cb else '')[:60]}」"
                        f" · {c.get('topic')}"
                        + (" · 极性对立补召" if c.get("forced_polarity") else "")
                    )
                lines.append("")
                lines.append(render_conclusions_block(dossier, active))
                data = extract_json(self.client.chat(self.model, [
                    {"role": "system", "content": CONFLICT_JUDGE_SYSTEM},
                    {"role": "user", "content": "\n".join(lines)},
                ], json_mode=True).content)
                raw = data.get("conflicts") or []
            except Exception:
                raw = []
                # 判读失败：极性对立候选机械补召，保证漏检有底
                for c in candidates:
                    if c.get("forced_polarity"):
                        raw.append({
                            "a": c["a"], "b": c["b"],
                            "topic": c.get("topic") or "同主体极性对立",
                            "description": "同主体自相矛盾（程序补召，判读失败兜底）",
                        })
        else:
            # 无程序候选（多为无主体标签）→ 自由检出，事后主体闸
            try:
                data = extract_json(self.client.chat(self.model, [
                    {"role": "system", "content": CONFLICT_SYSTEM},
                    {"role": "user",
                     "content": render_conclusions_block(dossier, active)},
                ], json_mode=True).content)
                raw = data.get("conflicts") or []
            except Exception:
                raw = []

        pairs: list[ConflictPair] = []
        accepted_keys: set[tuple[str, str]] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            a_id = str(item.get("a", ""))
            b_id = str(item.get("b", ""))
            key = tuple(sorted((a_id, b_id)))
            if used_judge and key not in cand_keys:
                drops.append({
                    "a": a_id, "b": b_id,
                    "reason": "非候选对（禁止新增/跨主体）",
                })
                continue
            mismatch = subject_mismatch_reason(dossier, a_id, b_id)
            if mismatch:
                drops.append({"a": a_id, "b": b_id, "reason": mismatch})
                continue
            pair = ConflictPair(
                a_id=a_id, b_id=b_id,
                topic=str(item.get("topic", "")),
                description=str(item.get("description", "")),
            )
            problems = validate_conflict(pair, dossier)
            if problems:
                drops.append({
                    "a": a_id, "b": b_id,
                    "reason": "非法对：" + "；".join(problems),
                })
                continue
            if key in accepted_keys:
                continue
            accepted_keys.add(key)
            pairs.append(pair)

        # 判读成功但漏掉极性对立：补召进场（丢弃必披露的对偶：补召也记账）
        if used_judge:
            for c in candidates:
                if not c.get("forced_polarity"):
                    continue
                key = tuple(sorted((c["a"], c["b"])))
                if key in accepted_keys:
                    continue
                pair = ConflictPair(
                    a_id=c["a"], b_id=c["b"],
                    topic=str(c.get("topic") or "同主体极性对立"),
                    description="同主体自相矛盾（程序补召）",
                )
                problems = validate_conflict(pair, dossier)
                if problems:
                    drops.append({
                        "a": c["a"], "b": c["b"],
                        "reason": "非法对：" + "；".join(problems),
                    })
                    continue
                accepted_keys.add(key)
                pairs.append(pair)

        # 候选中未被采纳且非补召进场的 → 记非真对立（披露）
        if used_judge:
            for c in candidates:
                key = tuple(sorted((c["a"], c["b"])))
                if key in accepted_keys:
                    continue
                if c.get("forced_polarity"):
                    continue  # 已补召或非法
                drops.append({
                    "a": c["a"], "b": c["b"],
                    "reason": "非真对立（模型未选且非极性强制）",
                })

        dossier.accounting["conflict_drops"] = drops_record(
            drops, n_candidates=len(candidates), n_accepted=len(pairs))
        return pairs

    # -- 辩论（质证一轮，轮数护栏=1；C-147 多轮路见 run_rebuttals_multiround）

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

    def run_rebuttals_multiround(
        self, dossier: Dossier, pair: ConflictPair, *, rounds: int,
    ) -> tuple[dict, list[dict]]:
        """C-147：2..N 轮书面质证（甲→乙→甲→乙…）；逐轮过闸＋一轮打回。

        第 1 轮沿用 REBUTTAL_TEMPLATE（与旧单轮同一提示词）；第 r≥2 轮用
        REBUTTAL_REPLY_TEMPLATE（看得到对方上一轮）。闸＝引文逐字＋引用
        存在性（与事后 audit_discourse 同一实现、同一文案）；未过 → 打回
        一稿，仍不过＝收下但逐轮披露。单侧失败降级空（与旧单轮同口径）；
        双方整轮无产出＝提前收对打。返回 (Resolution.rebuts 形状, 逐轮行)。
        """
        from app.core.discourse_check import rebuttal_text_flags
        from app.core.rebuttal_rounds import joined_rebuts

        def _system_for(side: str, cid: str, rnd: int) -> str:
            con = dossier.conclusion(cid)
            opponent_id = pair.b_id if side == "a" else pair.a_id
            opponent = dossier.conclusion(opponent_id)
            persona = self.personas.get(con.author, "独立分析师")
            opponent_evs = dossier.evidences_of(opponent_id)
            opponent_evidence = "；".join(
                f"『{e.quote[:60]}』({e.level.value})"
                for e in opponent_evs) or "（对方未挂证据）"
            if rnd == 1:
                return REBUTTAL_TEMPLATE.format(
                    persona=persona, statement=con.statement,
                    conclusion_id=cid,
                    opponent_statement=opponent.statement,
                    opponent_id=opponent_id,
                    opponent_evidence=opponent_evidence)
            opponent_side = "b" if side == "a" else "a"
            return REBUTTAL_REPLY_TEMPLATE.format(
                persona=persona, statement=con.statement,
                conclusion_id=cid, round_no=rnd,
                opponent_statement=opponent.statement,
                opponent_id=opponent_id,
                opponent_evidence=opponent_evidence,
                opponent_rebuttal=last.get(opponent_side) or "（对方暂无质证）")

        last: dict[str, str] = {}
        rows: list[dict] = []
        for rnd in range(1, max(2, int(rounds)) + 1):
            produced = 0
            for side, cid in (("a", pair.a_id), ("b", pair.b_id)):
                if dossier.conclusion(cid) is None:
                    continue
                text = ""
                gate_ok, repaired = True, False
                quote_n, ref_n = 0, 0
                try:
                    system = _system_for(side, cid, rnd)
                    text = self.client.chat(self.model, [
                        {"role": "system", "content": system},
                    ]).content.strip()[:600]  # 质证长度护栏（与旧单轮同值）
                    if text:
                        flags = rebuttal_text_flags(
                            dossier, text, conflict_id=pair.id, side=side)
                        if flags:
                            # 打回一稿：把未过的旗原文递回去
                            repair = system + "\n\n上一稿未过机械闸：" \
                                + "；".join(str(f.get("detail") or "")
                                           for f in flags[:3]) \
                                + "。请重新输出一稿。"
                            text2 = self.client.chat(self.model, [
                                {"role": "system", "content": repair},
                            ]).content.strip()[:600]
                            flags2 = rebuttal_text_flags(
                                dossier, text2, conflict_id=pair.id,
                                side=side) if text2 else []
                            if text2:
                                text, flags, repaired = text2, flags2, True
                        quote_n = sum(
                            1 for f in flags
                            if f.get("kind") == "rebut_quote")
                        ref_n = sum(
                            1 for f in flags
                            if f.get("kind") == "rebut_ref")
                        gate_ok = not flags
                except Exception:
                    text = ""  # 单侧质证失败降级
                if text:
                    last[side] = text
                    rows.append({
                        "round": rnd, "side": side, "conclusion_id": cid,
                        "text": text, "chars": len(text),
                        "gate_ok": gate_ok, "repaired": repaired,
                        "quote_flags": quote_n, "ref_flags": ref_n,
                    })
                    produced += 1
            if produced == 0:
                break  # 双方本轮都无产出＝对打提前收
        return joined_rebuts(rows), rows

    # -- 仲裁 ---------------------------------------------------------------

    def arbitrate(self, dossier: Dossier, pair: ConflictPair,
                  rebuts: dict | None = None) -> Resolution | None:
        """程序证据加权 + LLM 说理 → 裁决；失败返回 None（冲突未消解）。"""
        weight = compute_evidence_weight(pair, dossier)

        def _dates_of(cid: str) -> str:
            seen: dict[str, str] = {}
            for ev in dossier.evidences_of(cid):
                for sid in ev.segment_ids:
                    src = dossier.source_of_segment(sid)
                    if src is None or src.id in seen:
                        continue
                    # C-69／R-C69-1：开关开→统一读点；关→改前内联（只动这一处）
                    # 不许 try/except 静默退回（与 skills／fact_ledger 一致）
                    from app.core.temporal_check import (
                        source_date, source_time_unified,
                    )
                    if source_time_unified():
                        date = source_date(src)
                    else:
                        date = (str(src.meta.get("published_at") or "")
                                or str(src.meta.get("year") or ""))
                    if date:
                        seen[src.id] = f"{src.id}({date})"
            return "、".join(seen.values()) or "（信源未声明时点）"

        try:
            from app.core.untrusted import wrap_agent_output

            user = (
                f"{render_conclusions_block(dossier, [pair.a_id, pair.b_id])}\n\n"
                f"程序证据强度对比：{weight}\n"
                f"信源时点对比（证据强度打平时请把新近度纳入考量，"
                f"但注意新近度不能替代证据质量）：\n"
                f"- 甲方：{_dates_of(pair.a_id)}\n"
                f"- 乙方：{_dates_of(pair.b_id)}\n"
                f"双方质证：\n- 甲方({pair.a_id})："
                f"{wrap_agent_output((rebuts or {}).get('a') or '（未质证）')}\n"
                f"- 乙方({pair.b_id})："
                f"{wrap_agent_output((rebuts or {}).get('b') or '（未质证）')}\n\n"
                f"冲突说明：{pair.description or pair.topic or '结论对立'}"
            )
            data = extract_json(self.client.chat(self.model, [
                {"role": "system", "content": ARBITER_SYSTEM},
                {"role": "user", "content": user},
            ], json_mode=True).content)
            winner = str(data.get("winner", "")).strip()
            if winner not in (pair.a_id, pair.b_id, "tie"):
                return None  # winner 非法 → 不消解
            return prefer_stronger_side(pair, dossier, Resolution(
                winner_id=winner,
                method=("tie" if winner == "tie" else "arbitration"),
                rationale=str(data.get("rationale", "")),
                evidence_weight=weight,
                rebuts=dict(rebuts or {}),
            ))
        except Exception:
            return None

    # ------------------------------------------------------------------

    @staticmethod
    def _is_active(dossier: Dossier, conclusion_id: str) -> bool:
        con = dossier.conclusion(conclusion_id)
        return con is not None and con.status == "majority" \
            and bool(dossier.evidences_of(conclusion_id))
