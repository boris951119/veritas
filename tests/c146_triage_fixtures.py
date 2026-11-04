"""C-146 分流夹具（纯数据构造，零断言）。

测试与仪器共用同一批合成腿，避免「测试里造一遍、探针里造另一遍」的口径漂。
改前快照 ``c146_pre_triage_snapshot.json`` 必须由本文件构造输入——
否则快照与现算用的不是同一批数据，比对就成了空比空。
"""

from __future__ import annotations

from typing import Any

from app.core.conflict_trace import trace_conflict_pair, trace_ledger_collision
from app.core.evidence import Conclusion, Dossier, Segment, Source, SourceType
from app.core.fact_ledger import Collision, Fact

# 假段正文：raw 切片必须能在正文里找到，约数词才咬得住
SEG_TEXTS = {
    "doc_001#p1": "甲案经济补偿金约50万元，已于当年发放。",
    "doc_002#p1": "甲案经济补偿金49.4万元，凭单发放完毕。",
    "doc_003#p1": "甲案经济补偿金494元，明细见附表。",
    "doc_004#p1": "乙项目伤亡人数10人。",
    "doc_005#p1": "乙项目伤亡人数20人。",
    "doc_006#p1": "在岗需求分析师12名，另有外包需求分析师35名。",
}


def _collision(entity: str, metric: str, facts: list[Fact]) -> Collision:
    return Collision(entity=entity, metric=metric, facts=facts)


def ledger_cases() -> list[tuple[str, Any, dict[str, str] | None]]:
    """(用例名, Collision, seg_texts)：覆盖分流四档的每一条腿。"""
    date_offset = _collision("甲", "补偿金", [
        Fact("甲", "补偿金", 494000.0, "49.4万", "doc_002", "doc_002#p1",
             "2024-01-05", metric_canon="补偿金", canon_reason="ok"),
        Fact("甲", "补偿金", 600000.0, "60万", "doc_004", "doc_004#p1",
             "2024-06-05", metric_canon="补偿金", canon_reason="ok"),
    ])
    hedge = _collision("甲", "补偿金", [
        Fact("甲", "补偿金", 500000.0, "50万", "doc_001", "doc_001#p1",
             "2024-03-12", metric_canon="补偿金", canon_reason="ok"),
        Fact("甲", "补偿金", 494000.0, "49.4万", "doc_002", "doc_002#p1",
             "2024-03-12", metric_canon="补偿金", canon_reason="ok"),
    ])
    scale = _collision("甲", "补偿金", [
        Fact("甲", "补偿金", 494000.0, "49.4万", "doc_002", "doc_002#p1",
             "2024-03-12", metric_canon="补偿金", canon_reason="ok"),
        Fact("甲", "补偿金", 494.0, "494", "doc_003", "doc_003#p1",
             "2024-03-12", metric_canon="补偿金", canon_reason="ok"),
    ])
    true_oppose = _collision("乙", "伤亡", [
        Fact("乙", "伤亡", 10.0, "10人", "doc_004", "doc_004#p1",
             "2024-03-12T10:00:00", metric_canon="伤亡", canon_reason="ok"),
        Fact("乙", "伤亡", 20.0, "20人", "doc_005", "doc_005#p1",
             "2024-03-12T18:00:00", metric_canon="伤亡", canon_reason="ok"),
    ])
    unknown = _collision("乙", "伤亡", [
        Fact("乙", "伤亡", 10.0, "10人", "doc_004", "doc_004#p1", "",
             metric_canon="伤亡", canon_reason="ok"),
        Fact("乙", "伤亡", 20.0, "20人", "doc_005", "doc_005#p1", "",
             metric_canon="伤亡", canon_reason="ok"),
    ])
    # 关键词被当指标：C-80 量名闸已判「不是量名」
    not_quantity = _collision("", "需求分析师", [
        Fact("", "需求分析师", 12.0, "12名", "doc_006", "doc_006#p1",
             "2024-03-12", canon_reason="no_quantity_hint"),
        Fact("", "需求分析师", 35.0, "35名", "doc_007", "doc_007#p1",
             "2024-03-12", canon_reason="no_quantity_hint"),
    ])
    # 同段两数：两个数出自同一段
    single_seg = _collision("丙", "产能", [
        Fact("丙", "产能", 10.0, "10万吨", "doc_008", "doc_008#p1",
             "2024-03-12", metric_canon="产能", canon_reason="ok"),
        Fact("丙", "产能", 20.0, "20万吨", "doc_008", "doc_008#p1",
             "2024-03-12", metric_canon="产能", canon_reason="ok"),
    ])
    return [
        ("date_offset", date_offset, dict(SEG_TEXTS)),
        ("oral_hedge", hedge, dict(SEG_TEXTS)),
        ("oral_scale", scale, dict(SEG_TEXTS)),
        ("oral_not_quantity", not_quantity, dict(SEG_TEXTS)),
        ("oral_single_segment", single_seg, dict(SEG_TEXTS)),
        ("true_oppose", true_oppose, dict(SEG_TEXTS)),
        ("true_oppose_unknown_time", unknown, dict(SEG_TEXTS)),
    ]


def pair_cases() -> list[tuple[str, dict, Any | None]]:
    """(用例名, pair dict, dossier)：结论级分流的每一条腿。"""

    def _pair(pid: str, winner: str) -> dict:
        """a_id=CON-A／b_id=CON-B 固定；winner 只影响 disposition，不影响分流。"""
        if winner == "none":
            res = None
        elif winner == "a":
            res = {"winner_id": "CON-A", "method": "evidence_weight"}
        else:
            res = {"winner_id": "tie", "method": "tie"}
        return {"id": pid, "a_id": "CON-A", "b_id": "CON-B",
                "topic": pid, "resolution": res}

    def _dossier(a: str, b: str) -> Dossier:
        d = Dossier(question="C-146 夹具")
        ca = Conclusion.create(a, author="mainstream")
        ca.id = "CON-A"
        cb = Conclusion.create(b, author="devil")
        cb.id = "CON-B"
        d.conclusions.extend([ca, cb])
        return d

    same_a = "甲方已按49.4万元标准足额发放经济补偿金，程序合规且无拖欠。"
    polar_a = "客户B不存在回款风险，质保金已全部收回。"
    polar_b = "客户B存在大额回款风险，坏账计提尚未完成。"
    num_a = "本期回款率降至34%，验收延后是主因。"
    num_b = "本期回款率为91%，回款情况处于三年最好水平。"
    qual_a = "项目现场已全面停工，无施工迹象。"
    qual_b = "项目仍在正常施工，主体已封顶。"
    subj_a = "客户B的回款进度慢于合同约定。"
    subj_b = "客户C的回款进度符合合同约定。"
    topic_a = "客户B的回款率下滑至34%。"
    topic_b = "客户B的核心人员流失加剧，交付组已换过两茬。"

    return [
        ("pair_identical", _pair("CFL-same", "a"),
         _dossier(same_a, same_a)),
        ("pair_subject_mismatch", _pair("CFL-subject", "a"),
         _dossier(subj_a, subj_b)),
        ("pair_topic_disjoint", _pair("CFL-topic", "tie"),
         _dossier(topic_a, topic_b)),
        ("pair_polarity_opposite", _pair("CFL-polar", "none"),
         _dossier(polar_a, polar_b)),
        ("pair_disjoint_numbers", _pair("CFL-num", "tie"),
         _dossier(num_a, num_b)),
        ("pair_undetermined", _pair("CFL-qual", "tie"),
         _dossier(qual_a, qual_b)),
        ("pair_unreadable", _pair("CFL-orphan", "tie"),
         Dossier(question="空卷")),
    ]


def build_rows() -> list[dict]:
    """全批夹具 → 留痕行（本分支实现；测试与快照生成共用同一条构造路）。"""
    rows: list[dict] = []
    for i, (_name, col, segs) in enumerate(ledger_cases(), 1):
        rows.append(trace_ledger_collision(col, index=i, seg_texts=segs))
    for i, (_name, pair, dossier) in enumerate(pair_cases(), 1):
        rows.append(trace_conflict_pair(pair, index=i, dossier=dossier))
    return rows


def dossier_with_segments() -> Dossier:
    """把 SEG_TEXTS 装成案卷：走 build_conflict_trace 真接线（含段文本腿）。

    约数档只有在这条路上才咬得住——生产路径的段文本来自 dossier，
    裸 Dossier ＋外部 collisions 会让约数腿自动失效（那是降级，不是通过）。
    """
    d = Dossier(question="C-146 分流夹具案卷")
    for doc_id, text in SEG_TEXTS.items():
        seg_id, para = doc_id.split("#", 1)
        src = Source.create(seg_id, SourceType.REPORT, id=seg_id)
        src.segments.append(
            Segment(id=f"{seg_id}#{para}", source_id=seg_id, text=text))
        d.add_source(src)
    return d
