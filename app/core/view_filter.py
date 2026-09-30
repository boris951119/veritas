"""权限视图（输出夹层）：密级挂信源，可见性是派生物，审计链全量保真。

顺序不可颠倒：LLM → 物化进案卷 → 哈希链记录**全量真相** → 权限
过滤视图 → 用户。链在前、过滤在后——过滤后的视图只是展示层，链上
永远有完整记录（否则链本身成了泄密证据）。

过滤规则（密级 public < internal < confidential，查看者 clearance
能看到一切 ≤ 自身级别的信源）：
- 无权限信源整体隐藏；
- 引用了无权限信源的**证据行**隐藏；
- 支持**全部**来自无权限信源的结论 → statement 置为占位（结论文本
  本身带数字，只藏证据等于没藏）；混合支撑的结论保留但涉密证据行
  显示红章占位——**红章必须可见**，静默过滤比不过滤更糟。
"""

from __future__ import annotations

import copy

from app.core.evidence import Dossier

_CLEARANCE_LEVEL = {"public": 0, "internal": 1, "confidential": 2}

REDACTED_EVIDENCE_TEXT = "（该证据涉密，您无权限查阅）"
REDACTED_CONCLUSION_TEXT = "（涉密结论已隐藏：其全部证据来自您无权限的信源）"


def normalize_clearance(clearance: str | None) -> str:
    c = (clearance or "confidential").strip().lower()
    return c if c in _CLEARANCE_LEVEL else "confidential"


def redact_dossier(dossier: Dossier, clearance: str | None) -> tuple[Dossier, dict]:
    """按查看者级别产出过滤视图（深拷贝，不改原案卷与链）。"""
    level = _CLEARANCE_LEVEL[normalize_clearance(clearance)]
    view = copy.deepcopy(dossier)
    hidden_sources: list[str] = []
    for src in view.sources:
        src_level = _CLEARANCE_LEVEL.get(
            normalize_clearance(src.classification), 1)
        if src_level > level:
            hidden_sources.append(src.id)
    for src in view.sources:
        if src.id in hidden_sources:
            src.segments = []
            src.meta["redacted"] = True

    def _visible(sid: str) -> bool:
        return sid.split("#", 1)[0] not in hidden_sources

    hidden_evidences = 0
    for ev in list(view.evidences):
        if ev.segment_ids and not all(_visible(sid) for sid in ev.segment_ids):
            view.evidences.remove(ev)
            for con in view.conclusions:
                con.evidence_ids = [i for i in con.evidence_ids if i != ev.id]
            hidden_evidences += 1

    hidden_conclusions = 0
    for con in view.conclusions:
        if con.status == "merged":
            continue
        if con.evidence_ids or not dossier.evidences_of(con.id):
            continue
        # 原本挂证、视图中证据全被过滤 → 整条结论对低权限者隐藏
        con.statement = REDACTED_CONCLUSION_TEXT
        con.confidence = 0.0
        con.confidence_parts = {}
        hidden_conclusions += 1

    # 冲突记录与 dissent 簿记脱敏：涉密侧参与的冲突，其主题/说明/
    # 仲裁理由/质证文本一律红章（理由与质证可能复述涉密数字）；
    # 胜方结论上挂的 dissent 记录若指向隐藏结论，statement/why 同样
    # 红章（此前是泄露漏洞——记录挂在可见结论上但抄录了败方原文）。
    hidden_ids = {c.id for c in view.conclusions
                  if c.statement == REDACTED_CONCLUSION_TEXT}
    hidden_conflicts = 0
    for raw in view.conflicts or []:
        if not isinstance(raw, dict):
            continue
        res = raw.get("resolution") or {}
        involves_hidden = raw.get("a_id") in hidden_ids \
            or raw.get("b_id") in hidden_ids
        if involves_hidden:
            hidden_conflicts += 1
            raw["topic"] = "（涉密冲突）"
            raw["description"] = "（冲突详情涉密，您无权限查阅）"
            if res:
                res["rationale"] = "（仲裁理由涉密，您无权限查阅）"
                res["rebuts"] = {k: "（质证文本涉密，您无权限查阅）"
                                 for k in (res.get("rebuts") or {})}
        elif res:
            res["rebuts"] = {k: v for k, v in (res.get("rebuts") or {}).items()}
    for con in view.conclusions:
        for rec in con.dissent or []:
            if rec.get("conclusion_id") in hidden_ids:
                rec["statement"] = "（少数意见涉密，您无权限查阅）"
                rec["why"] = "（仲裁记录涉密，您无权限查阅）"

    stats = {"hidden_sources": hidden_sources,
             "hidden_evidences": hidden_evidences,
             "hidden_conclusions": hidden_conclusions,
             "hidden_conflicts": hidden_conflicts,
             "clearance": normalize_clearance(clearance)}
    return view, stats
