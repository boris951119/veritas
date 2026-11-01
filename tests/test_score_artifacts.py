"""离线复放打分器（scripts/score_artifacts.py）的单测。

它治的是「测试全绿但产品不能用」：451 项测试量输入侧，这份量的是
**产物级失败**——报告交得出来、却一条可用判断都没有，必须显影。

四条判据：可复现（同份产物两次结果一致）、零结论要亮旗、复放失败不许静默、
基线比对的方向不能反。
"""

from pathlib import Path

from app.core.evidence import (
    Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType)
from scripts.score_artifacts import diff_vs_baseline, score_all, score_artifact


def _dossier(*, with_conclusion: bool) -> Dossier:
    d = Dossier(question="各客户项目是否存在人员流失风险？回款风险呢？")
    src = Source.create("账目", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="项目账目统计截止日为2025年3月31日，应收应付开票回款全量往来已覆盖。"))
    src.segments.append(Segment(
        id="SRC1#s2", source_id="SRC1",
        text="风险台账：核心开发人员离职20%，2026年3月5日另有6人合同到期。"))
    d.add_source(src)
    d.panel = ["mainstream", "redteam"]
    if with_conclusion:
        d.conclusions.append(Conclusion.create(
            "不存在人员流失风险，因为项目账目统计截止日为2025年3月31日",
            author="mainstream", id="CON1", confidence=0.2333,
            confidence_parts={"n_authors": 1, "n_evidence": 1}))
        d.add_evidence(EvidenceNode.create(
            "CON1", "项目账目统计截止日为2025年3月31日", ["SRC1#s1"],
            author="mainstream"))
    else:                       # 全「资料不足」：报告能出，判断一条没有
        d.conclusions.append(Conclusion.create(
            "资料不足，无法判断人员流失风险", author="mainstream",
            id="CON1", status="insufficient"))
    return d


def _write(tmp_path: Path, d: Dossier) -> Path:
    out = tmp_path / "report.json"
    d.to_json(out)
    return out


def test_replay_is_reproducible(tmp_path):
    """同一份产物跑两次必须一字不差——否则基线比对没有意义。"""
    path = _write(tmp_path, _dossier(with_conclusion=True))
    first, second = score_artifact(path), score_artifact(path)
    assert first == second
    assert first["no_answer"] is False
    assert first["n_majority"] == 1
    assert first["flags_high"] == 0            # 桩案卷不该出红灯
    assert first["warrant_flags"] == 1         # 理由与主张脱节要亮
    assert first["single_author"] == 1         # 单人署名要数出来
    assert first["multi_author"] == 0          # 会签条数（协同是否发生）
    assert first["mech_groups"] is None        # 旧产物没这字段，不得瞎猜 0


def test_zero_usable_conclusion_is_shown(tmp_path):
    """全「资料不足」= 产品级失败，必须在结论列亮旗而不是显示成 0 号红灯。"""
    path = _write(tmp_path, _dossier(with_conclusion=False))
    row = score_artifact(path)
    assert row["no_answer"] is True
    assert row["n_majority"] == 0
    assert row["n_insufficient"] == 1
    assert row["conf_max"] == 0.0


def test_replay_failure_is_not_silent(tmp_path):
    """坏产物（JSON 残缺）要成为一行显式失败，不能整批崩，也不能被跳过。"""
    broken_dir = tmp_path / "broken"
    broken_dir.mkdir()
    (broken_dir / "report.json").write_text('{"question": "缺字段',
                                            encoding="utf-8")
    good = _write(tmp_path, _dossier(with_conclusion=True))
    rows = score_all([broken_dir / "report.json", good])
    assert len(rows) == 2
    failed = [r for r in rows if r.get("error")]
    assert len(failed) == 1 and "broken" in failed[0]["artifact"]
    assert "JSONDecodeError" in failed[0]["error"]


def test_baseline_diff_direction(tmp_path):
    """退化判据方向不能反：灯变多/置信变低=退化，反之不算。"""
    path = _write(tmp_path, _dossier(with_conclusion=True))
    row = score_artifact(path)

    worse_baseline = dict(row, flags_medium=row["flags_medium"] - 2,
                          conf_max=row["conf_max"] + 0.5,
                          cited_share=row["cited_share"] + 0.2)
    problems = diff_vs_baseline([row], {row["artifact"]: worse_baseline})
    assert any("flags_medium" in p for p in problems)
    assert any("conf_max" in p for p in problems)
    assert any("cited_share" in p for p in problems)

    better_baseline = dict(row, flags_medium=row["flags_medium"] + 3,
                           conf_max=0.0, unused_topic=row["unused_topic"] + 5)
    assert diff_vs_baseline([row], {row["artifact"]: better_baseline}) == []

    # 基线有可用结论、这版没有 → 必须报退化（方向反了就是自欺）
    regress = diff_vs_baseline([dict(row, no_answer=True)],
                               {row["artifact"]: row})
    assert any("零结论" in p for p in regress)
