"""R17：标签 schema／词表解耦。规则代码不出现案情专名。"""

from __future__ import annotations

from pathlib import Path

from app.kg_lab.case_lexicon import (
    FAMILY_CATALOG,
    extract_actors_from_question,
    lexicon_for_question,
)
from app.kg_lab.tag_schema import STAGE1_FEATURES, STAGE2_FEATURES, schema_table


def test_schema_splits_stage1_and_stage2():
    assert "subject_match" in STAGE1_FEATURES
    assert "claim_full" in STAGE1_FEATURES
    assert "title_bait" in STAGE2_FEATURES
    assert "offtopic_cross_claim" in STAGE2_FEATURES
    # 挡路惩罚不进一筛系数名
    assert "title_bait" not in STAGE1_FEATURES
    assert schema_table()


def test_family_catalog_has_no_person_names():
    blob = " ".join(
        " ".join(v) for spec in FAMILY_CATALOG.values() for v in spec.values()
    )
    assert "刘翔" not in blob
    assert "王虹" not in blob


def test_actors_come_from_question_not_hardcode():
    q = "拖了11年才安置，是刘翔不愿走还是体育局未放行，哪一方说法站得住？"
    actors = extract_actors_from_question(q)
    assert "刘翔" in actors
    assert "体育局" in actors
    assert all(not a.startswith("是") for a in actors)


def test_lexicon_activates_leave_family_from_question():
    q = "是刘翔不愿走还是体育局未放行？"
    lex = lexicon_for_question(q)
    assert "leave" in lex.active_families
    assert "不愿走" in lex.surfaces_for_family("leave")
    assert lex.family_of_question(q) == "leave"


def test_case_file_optional_aliases_only():
    path = Path("vaults/kg-lab/lexicon/liuxiang.json")
    assert path.is_file()
    raw = path.read_text(encoding="utf-8")
    # 配置里可以有别名；规则模块本身不该依赖写死专名
    assert "actor_aliases" in raw
    lex = lexicon_for_question(
        "体育局未放行？",
        case_slug="liuxiang",
    )
    assert "竞体中心" in (lex.actor_aliases.get("体育局") or [])
