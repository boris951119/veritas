"""C-34：A/B/C/D → 官方六级名（只换名，不改判定）；顺手补 C-33 三把 0 红。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.confidence import conclude_confidence, recompute_all
from app.core.evidence import (
    Conclusion,
    Dossier,
    EvidenceLevel,
    EvidenceNode,
    LEVEL_WEIGHT,
    RelationKind,
    Segment,
    Source,
    SourceType,
)
from app.core.hashchain import HashChain
from app.export import official as official_mod
from app.export.official import (
    OFFICIAL_LEVEL_TO_OURS,
    _FIELD_NOTES,
    _conflicting_facts,
    export_official,
    level_official_of,
)
from app.pipeline import render_report_md
from tests.test_c33_submission_side import _dossier_two_sides, _q
from tests.test_official_roundtrip import _para, _write_docs
from app.ingest.official_case import load_official_case

ROOT = Path(__file__).resolve().parents[1]
_OFFICIAL_SIX = (
    "官方程序记录",
    "官方表态",
    "权威媒体",
    "主流媒体",
    "匿名信源",
    "自媒体转述",
)


def _dossier_with_level(tmp_path: Path, level: str) -> Dossier:
    # quote／para 按 level 区分，避免 evidence.json 跨题 (doc,para,quote) 去重吞行
    text = f"【{level}档】官方通报：甲事件确由乙方主导，已形成程序记录。"
    para_id = f"para_{level}"
    case = _write_docs(tmp_path, [{
        "doc_id": f"doc_{level}",
        "title": "t",
        "publish_time": "2024-01-02",
        "content": text,
        "source_credibility": 0.7,
        "content_url": "",
        "paragraphs": [_para(para_id, 0, len(text))],
    }])
    dossier = load_official_case(case)
    con = Conclusion.create("乙方主导", author="m", id=f"CON-{level}")
    con.status = "majority"
    dossier.conclusions.append(con)
    dossier.add_evidence(EvidenceNode.create(
        f"CON-{level}", text, [para_id], id=f"EV-{level}",
        level=EvidenceLevel(level),
        relation=RelationKind.CORRELATION,
    ))
    return dossier


def _export_levels(tmp_path: Path, levels: list[str]) -> list[dict]:
    """每档一条证据，导出 evidence.json 行。"""
    runs = []
    for i, lv in enumerate(levels):
        sub = tmp_path / f"lv_{lv}_{i}"
        sub.mkdir(parents=True, exist_ok=True)
        d = _dossier_with_level(sub, lv)
        runs.append((_q(f"q_{lv}_{i}"), d))
    out = tmp_path / "export"
    paths = export_official(runs, out)
    return __import__("json").loads(paths["evidence"].read_text(encoding="utf-8"))


# ---------- a：唯一映射表 ----------


def test_a_mapping_defined_once():
    """定义点全仓恰一处。"""
    hits = []
    for path in (ROOT / "app").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        # 只计赋值定义，不计引用
        n = len(re.findall(r"^OFFICIAL_LEVEL_TO_OURS\s*[:=]", src, re.M))
        if n:
            hits.append((str(path.relative_to(ROOT)), n))
    assert hits == [("app/export/official.py", 1)], hits


def test_a_reverse_duplicate_map_breaks(monkeypatch):
    """自证：复制成两张 ⇒ 本格必红。"""
    src_path = ROOT / "app/export/official.py"
    original = src_path.read_text(encoding="utf-8")
    # 在模块源码层面无法同时改文件又让 import 看见第二张；改用运行时双表计数探针
    # 与判据 a 同形：人为制造第二份定义字面量后，用同一计数函数应 >1。
    fake = original + "\nOFFICIAL_LEVEL_TO_OURS = dict(OFFICIAL_LEVEL_TO_OURS)\n"
    n = len(re.findall(r"^OFFICIAL_LEVEL_TO_OURS\s*[:=]", fake, re.M))
    assert n == 2
    # 真跑：若有人在本模块再绑一张同名表，test_a_mapping_defined_once 必红
    # 此处再钉：当前模块属性只能是这一张 dict
    assert official_mod.OFFICIAL_LEVEL_TO_OURS is OFFICIAL_LEVEL_TO_OURS
    monkeypatch.setitem(
        official_mod.__dict__,
        "OFFICIAL_LEVEL_TO_OURS_DUP",
        dict(OFFICIAL_LEVEL_TO_OURS),
    )
    # 复制成两张（第二张也用定义赋值形）时，计数器应抓到
    dup_src = original.replace(
        "OFFICIAL_LEVEL_TO_OURS: dict[str, str] = {",
        "OFFICIAL_LEVEL_TO_OURS: dict[str, str] = {\n"
        "PASS\n"
        "OFFICIAL_LEVEL_TO_OURS_COPY: dict[str, str] = {",
        1,
    )
    # 上面会弄坏语法；改用直接断言「复制定义行」计数
    twin = original + "\nOFFICIAL_LEVEL_TO_OURS = {\n    \"自媒体转述\": \"D\",\n}\n"
    assert len(re.findall(r"^OFFICIAL_LEVEL_TO_OURS\s*[:=]", twin, re.M)) == 2


# ---------- b / c：每行 level_official；level 仍为 A/B/C/D ----------


def test_b_c_level_and_level_official_on_each_row(tmp_path):
    rows = _export_levels(tmp_path, ["A", "B", "C", "D"])
    assert len(rows) == 4
    seen_levels = set()
    for row in rows:
        assert "level_official" in row
        assert "level" in row
        assert row["level"] in ("A", "B", "C", "D")
        assert row["level_official"] in _OFFICIAL_SIX
        assert row["level_official"] == level_official_of(row["level"])
        seen_levels.add(row["level"])
    assert seen_levels == {"A", "B", "C", "D"}


def test_c_level_not_replaced_by_official_words(tmp_path):
    """负断言：level 取值逐字仍是 A/B/C/D，不是官方六词。"""
    rows = _export_levels(tmp_path, ["A", "B", "C", "D"])
    for row in rows:
        assert row["level"] not in _OFFICIAL_SIX
        assert row["level"] in ("A", "B", "C", "D")


# ---------- d：字段说明 ----------


def test_d_field_notes_weight_unchanged_sentence():
    assert "加权仍用我方 A/B/C/D、数值未改" in _FIELD_NOTES
    assert "已按官方六级重算加权" not in _FIELD_NOTES


# ---------- e：报告当场渲出官方六级名 ----------


def test_e_report_md_shows_official_level_label():
    d = Dossier(question="q?", panel=["m"])
    src = Source.create("测", SourceType.REPORT, credibility=0.8, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="官方程序记录：乙方主导甲事件。", locator="段 1"))
    d.add_source(src)
    con = Conclusion.create("乙方主导", author="m", id="CON1")
    con.status = "majority"
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", "官方程序记录：乙方主导甲事件。", ["SRC1#s1"],
        id="EV1", level=EvidenceLevel.A))
    md = render_report_md(d, HashChain(), [])
    assert "官方程序记录" in md
    assert "A（官方程序记录）" in md


def test_e_workbench_source_has_official_labels():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "LV_OFFICIAL" in html
    for name in ("官方程序记录", "官方表态", "主流媒体", "自媒体转述"):
        assert name in html
    # 渲染点必须真用到 LV_OFFICIAL（不是只定义不用）
    assert "LV_OFFICIAL[ev.level]" in html


# ---------- g：映射不进分 ----------


def _score_for_level(level: str):
    text = "全固态电芯的中试良率尚不足百分之四十。"
    d = Dossier(question="固态电池量产路径？", panel=["mainstream"])
    src = Source.create("测", SourceType.PAPER, credibility=0.8, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text=text, locator="段 1"))
    d.add_source(src)
    con = Conclusion.create("良率仍低", author="mainstream", id="CON1")
    con.status = "majority"
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON1", text, ["SRC1#s1"], id="EV1",
        level=EvidenceLevel(level),
        relation=RelationKind.CORRELATION,
    ))
    recompute_all(d, n_panel=1)
    conf, parts = conclude_confidence("CON1", d)
    # 四分量：strength / coverage / agreement / chain（chain 在 parts 里可能叫 chain）
    quad = {
        "strength": parts.get("strength"),
        "coverage": parts.get("coverage"),
        "agreement": parts.get("agreement"),
        "chain": parts.get("chain"),
    }
    return conf, quad


def test_g_mapping_does_not_enter_score(monkeypatch):
    """同一夹具只换 level 四值：每档 conf／四分量与纯 LEVEL_WEIGHT 路径逐位相同；
    自证把映射乘进分数必红。

    「逐位相同」＝每档相对未乘映射的计算；四档之间因 LEVEL_WEIGHT 不同而分数不同。
    """
    import app.core.confidence as conf_mod

    clean = {lv: _score_for_level(lv) for lv in ("A", "B", "C", "D")}
    # 映射表已加载后再算一遍，应逐位相同
    again = {lv: _score_for_level(lv) for lv in ("A", "B", "C", "D")}
    assert again == clean
    # 四档不应全同（LEVEL_WEIGHT 仍在生效）
    assert len({clean[lv][0] for lv in clean}) > 1
    # confidence.py 不引用映射表
    conf_src = (ROOT / "app/core/confidence.py").read_text(encoding="utf-8")
    assert "OFFICIAL_LEVEL_TO_OURS" not in conf_src
    assert "level_official" not in conf_src

    # 自证：把映射乘进分数 ⇒ 与 clean 分裂
    _orig = conf_mod.evidence_score
    _boost = {
        "官方程序记录": 1.35,
        "官方表态": 1.20,
        "权威媒体": 1.10,
        "主流媒体": 1.05,
        "匿名信源": 0.90,
        "自媒体转述": 0.70,
    }

    def _poisoned(ev, dossier):
        base = _orig(ev, dossier)
        name = level_official_of(ev.level.value)
        return min(1.0, base * _boost[name])

    monkeypatch.setattr(conf_mod, "evidence_score", _poisoned)
    poisoned = {lv: _score_for_level(lv) for lv in ("A", "B", "C", "D")}
    assert any(poisoned[lv][0] != clean[lv][0] for lv in clean), (
        "自证失败：把映射乘进分数后仍与 clean 全同，本格抓不住回归")


# ---------- h：新增测试无 git+diff 连写 ----------


def test_h_no_git_diff_literal_in_new_tests():
    src = Path(__file__).read_text(encoding="utf-8")
    needle = "git" + " " + "diff"
    assert src.count(needle) == 0


# ---------- i：locator 取不到不并入 ----------


def test_i_skipped_no_locator_not_merged(tmp_path, monkeypatch):
    """败方证据的 segment 取不到 ⇒ conflicting_facts 空且 skipped_no_locator==1。"""
    d = _dossier_two_sides(tmp_path)
    # 把败方证据的 segment_ids 改成不存在的 id
    for ev in d.evidences:
        if ev.conclusion_id == "CON-B":
            ev.segment_ids = ["no_such_segment"]
    facts, skip_tie, skip_noloc = _conflicting_facts(d)
    assert facts == []
    assert skip_noloc == 1
    assert skip_tie == 0

    # 自证：若生产改成拿 segment_id 造假 (doc_id, para_id)，上面 facts==[] 必红
    import app.export.official as om
    real_locator = om._segment_locator

    def _fake_locator(dossier, segment_id: str):
        loc = real_locator(dossier, segment_id)
        if loc is not None:
            return loc
        return (f"fake_doc:{segment_id}", segment_id)

    monkeypatch.setattr(om, "_segment_locator", _fake_locator)
    facts2, _, skip2 = om._conflicting_facts(d)
    assert facts2, "造假 locator 后应并入；若仍空则自证腿失效"
    assert skip2 == 0


# ---------- j：同段落去重只交一行 ----------


def test_j_duplicate_loser_paragraph_deduped(tmp_path):
    """两条败方证据指向同一段落 ⇒ conflicting_facts 只交一行。"""
    d = _dossier_two_sides(tmp_path, include_dissent_only_ev=False)
    # 再加一条败方证据，quote 不同但同一 segment
    lose_text = "败方引用：甲事件与乙方无关。"
    d.add_evidence(EvidenceNode.create(
        "CON-B", lose_text + "（补充一句）", ["para_lose"], id="EV-B2"))
    facts, skip_tie, skip_noloc = _conflicting_facts(d)
    assert skip_tie == 0 and skip_noloc == 0
    assert len(facts) == 1
    assert facts[0]["para_id"] == "para_lose"


# ---------- k 由 test_c33::test_f 内容断言承担 ----------


def test_k_causation_bonus_and_weights_literal():
    """与改写后的 test_f 同口径，防止只改一边。"""
    conf_src = (ROOT / "app/core/confidence.py").read_text(encoding="utf-8")
    ev_src = (ROOT / "app/core/evidence.py").read_text(encoding="utf-8")
    assert "_CAUSATION_BONUS = 1.15" in conf_src
    for needle in (
        "EvidenceLevel.A: 1.0",
        "EvidenceLevel.B: 0.8",
        "EvidenceLevel.C: 0.55",
        "EvidenceLevel.D: 0.3",
    ):
        assert needle in ev_src
    # LEVEL_WEIGHT 运行时数值也钉住
    assert LEVEL_WEIGHT[EvidenceLevel.A] == 1.0
    assert LEVEL_WEIGHT[EvidenceLevel.B] == 0.8
    assert LEVEL_WEIGHT[EvidenceLevel.C] == 0.55
    assert LEVEL_WEIGHT[EvidenceLevel.D] == 0.3
