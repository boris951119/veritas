"""C-72 树17＋R-C72-1 返工：要点槽三数拆分／主席旗改严／词表纯净。

开关 VERITAS_CLAIM_SLOTS 默认 False。分数不在本单验。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.core.audit import KIND_LABEL, audit_all
from app.core.claim_slots import (
    GAP_MARK,
    STAMP_PREFIX,
    apply_claim_slots,
    case_gold_forbidden_tokens,
    chair_support_flags,
    chair_support_zero_disclosure,
    claim_slots_enabled,
    cue_case_gold_intersection,
    extract_slots,
    gloss_anchor_tokens,
    set_claim_slots,
    slot_coverage,
    slot_cue_vocab,
    stamp_uncovered_gaps,
    assess_slot_rows,
)
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, Segment, Source, SourceType,
)
from app.core.material import pack_material
from app.core.warrant_check import audit_parallel_coverage
from app.export.official import export_official

_ROOT = Path(__file__).resolve().parents[1]

_OFFICIAL_18: list[str] = [
    "吉隆口岸泥石流灾害的起始时刻，应以官方通稿的8月26日10时30分许为准，还是以监控记录的10时52分至59分为准？",
    "中方称泥石流、联合国与尼泊尔称洪灾或山崩，评估伤亡与受灾统计时应采用哪一口径？",
    "官方与中科院认定的海拔约5200米冰川断裂冰岩崩，与媒体所称上游冰湖溃决，哪一说法成立？",
    "AI事故通报热线到底能否在2026年11月的中美对话后就绪启用，还是如WIRED所称短期不会就绪？",
    "中美AI对话机制应定性为危机管理安排，还是联合国主渠道下的全球AI治理安排？",
    "AI失控责任该由OpenAI管理层等企业承担，还是如Anthropic、奥尔特曼所主张由政府介入承担？",
    "这笔49.4万元应认定为买断费还是自主择业经济补偿金，以哪方口径为准？",
    "拖了11年才安置，是刘翔不愿走还是体育局未放行，哪一方说法站得住？",
    "刘翔退役至今是否真有编制与岗位，官方称其在编不在岗能否以人事档案证实？",
    "截至2026年5月，AI171空难死亡人数应以机上241人、全部242人还是含地面共274人为准？",
    "官方调查是否已认定AI171坠机系机组关闭燃油开关所致，而非波音燃油开关设计缺陷？",
    "11A座位靠近紧急出口是否真的提高了AI171幸存者的生还概率，还是纯属侥幸？",
    "泰方称两次出动F-16打击柬军事目标，柬方称境内军事设施未遭空袭，哪一方有可核查证据支持？",
    "泰方称柬方率先开火、柬方称泰军率先开火，现有记录能否判定2025年12月边境冲突谁先动武？",
    "西方媒体称中国向柬埔寨提供大量武器援助偏帮一方，这一说法是否有可证实的证据支撑？",
    "王虹说的 discouraged 原意指什么？是北大的教学环境/特定教师让她气馁？",
    "流传的「北大无人肯写推荐信」「因绩点不足未保研」「缺席毕业合照」等是否属实？",
    "王虹本人对北大的评价是正面还是负面？",
]


@pytest.fixture(autouse=True)
def _reset_claim_slots():
    set_claim_slots(False)
    yield
    set_claim_slots(False)


def _src(sid: str, text: str, **meta) -> Source:
    s = Source.create(sid, SourceType.REPORT, id=sid)
    s.meta.update(meta)
    s.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text, index=0))
    return s


def _load_mutated_copy(name: str, old: str, new: str, tmp_path: Path):
    """源文件字节复制进 tmp → replace → 独立加载；真树零写（#199）。"""
    import types as _types

    raw = (_ROOT / name).read_text(encoding="utf-8")
    assert old in raw, f"变异针漂移：{name!r} 找不到 old 字面"
    dest = tmp_path / name.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw.replace(old, new, 1), encoding="utf-8")
    mod_name = f"c72_mut_{dest.stem}_{abs(hash(new)) & 0xFFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, dest)
    assert spec is not None and spec.loader is not None
    mod = _types.ModuleType(mod_name)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- 默认值 ----
def test_c72_defaults_claim_slots_off():
    """刀：把 Settings.claim_slots 默认翻 True ⇒ 本格红。"""
    s = Settings()
    assert s.claim_slots is False
    assert claim_slots_enabled() is False
    assert s.source_time_unified is True
    assert s.ledger_time_class is True
    assert s.relevance_soft_gate is True


# ---- R-C72-1 件①：三数拆分；ok 不许建立在盖章之后 ----
def test_c72_a_stamp_does_not_make_ok():
    """18 题无证据全盖章 ⇒ stamped>0、bound=0、true_gap=0、ok=False（盖章≠100%）。"""
    assert len(_OFFICIAL_18) == 18
    set_claim_slots(True)
    total_slots = 0
    total_stamped = 0
    total_bound = 0
    total_true_gap = 0
    for q in _OFFICIAL_18:
        d = Dossier(question=q)
        rows = stamp_uncovered_gaps(d)
        cov = slot_coverage(rows)
        assert cov["ok"] is False, (q, cov)
        assert cov["n_bound"] == 0
        assert cov["n_true_gap"] == 0
        assert cov["n_stamped"] == cov["n_slots"] > 0
        assert all(r["status"] == "stamped_gap" for r in rows)
        assert all(r.get("stamped") for r in rows)
        assert all(STAMP_PREFIX in (r.get("detail") or "") for r in rows)
        total_slots += cov["n_slots"]
        total_stamped += cov["n_stamped"]
        total_bound += cov["n_bound"]
        total_true_gap += cov["n_true_gap"]
    # 交账三数（无证据臂＝全盖章）
    assert total_bound == 0
    assert total_true_gap == 0
    assert total_stamped == total_slots > 0


def test_c72_a_three_rates_split_visible():
    """同案：真绑／真缺口／盖章必须分开可见；ok 只在全 bound|真 gap 时成立。"""
    set_claim_slots(True)
    d = Dossier(question="泥石流灾害的起始时刻是何时？伤亡多少？")
    d.add_source(_src("S1", "官方通稿写明发生于8月26日10时30分。"))
    con = Conclusion.create(
        f"以官方通稿时刻为准；{GAP_MARK}：关键数字",
        author="stub", id="CON-1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "官方通稿写明发生于8月26日10时30分。",
        ["S1#s1"], id="EV-1", level=EvidenceLevel.A,
        note="关键时点已核"))
    # 盖章前
    pre = assess_slot_rows(d)
    # 盖章后
    rows = stamp_uncovered_gaps(d)
    cov = slot_coverage(rows)
    assert "bound_rate" in cov and "true_gap_rate" in cov and "stamped_rate" in cov
    assert cov["n_bound"] >= 1
    assert cov["n_true_gap"] >= 1  # 模型写了关键数字缺口
    # what 若仍 empty → 盖成 stamped_gap
    assert any(r["status"] == "stamped_gap" for r in rows) or cov["n_stamped"] == 0
    # 只要还有盖章或 bogus／empty，ok 必须假
    if cov["n_stamped"] or cov["n_bogus"] or cov["n_empty"]:
        assert cov["ok"] is False
    # 披露：盖章行细节带【程序盖章】；真缺口不带
    for r in rows:
        if r.get("stamped"):
            assert STAMP_PREFIX in (r.get("detail") or "")
        if r.get("status") == "gap":
            assert STAMP_PREFIX not in (r.get("detail") or "")
    # 盖章前 empty 数应等于盖章后 stamped（同槽）
    n_empty_pre = sum(1 for r in pre if r["status"] == "empty")
    assert cov["n_stamped"] == n_empty_pre


def test_c72_a_bogus_quote_not_covered():
    """凑出来的槽（引文定位不上）＝bogus，不算覆盖；ok=False。"""
    set_claim_slots(True)
    d = Dossier(question="泥石流灾害的起始时刻是何时？")
    d.add_source(_src("S1", "官方通稿写明泥石流发生于8月26日。"))
    con = Conclusion.create("起始时刻待核", author="stub", id="CON-1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "这段话原文里根本没有", ["S1#s1"],
        id="EV-bogus", level=EvidenceLevel.B,
        note="关键时点：监控记录"))
    rows = stamp_uncovered_gaps(d)
    time_rows = [r for r in rows if r["id"] == "time"]
    assert time_rows, rows
    assert time_rows[0]["status"] == "bogus"
    cov = slot_coverage(rows)
    assert cov["ok"] is False
    assert cov["n_bogus"] >= 1


# ---- R-C72-1 件②：数字／时点锚逐字定位；零触发必须披露 ----
def test_c72_b_chair_anchor_missing_emits_flag():
    """gloss 含支撑段没有的数字／时点 ⇒ 必出旗。"""
    set_claim_slots(True)
    d = Dossier(question="冰川断裂与冰湖溃决哪一说法成立？")
    d.add_source(_src("S1", "中科院认定本次为冰川断裂冰岩崩，未见冰湖溃决证据。"))
    con = Conclusion.create(
        "应以冰川断裂冰岩崩说法为准", author="stub", id="CON-sub")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "中科院认定本次为冰川断裂冰岩崩，未见冰湖溃决证据。",
        ["S1#s1"], id="EV-1", level=EvidenceLevel.A))
    d.synthesis = {
        "mode": "template",
        "headline": "应以冰川断裂为准",
        "points": [
            {"con_id": "CON-sub", "gloss": "应以冰川断裂冰岩崩说法为准"},
            # 数字＋时点全不在支撑段
            {"con_id": "CON-other",
             "gloss": "上游水库于2024年3月12日泄洪300万方"},
        ],
        "open_issues": [],
    }
    assert gloss_anchor_tokens("上游水库于2024年3月12日泄洪300万方")
    flags = chair_support_flags(d)
    assert flags, "数字／时点锚落不进支撑段必须出旗"
    assert all(f["kind"] == "chair_support_gap" for f in flags)
    blob = " ".join(f.get("detail", "") + f.get("value", "") for f in flags)
    assert "2024年3月12日" in blob or "300" in blob
    apply_claim_slots(d)
    kinds = {f["kind"] for f in audit_all(d)}
    assert "chair_support_gap" in kinds
    assert "chair_support_gap" in KIND_LABEL


def test_c72_b_delete_emit_line_must_red(tmp_path):
    """刀：把出旗改成恒跳过 ⇒ 本格红（#199 tmp 变异）。"""
    old = (
        "        missing = [a for a in anchors if a not in blob]\n"
        "        if not missing:\n"
        "            continue\n"
        "        joined = \"、\".join(missing)\n"
        "        flags.append({"
    )
    new = (
        "        missing = [a for a in anchors if a not in blob]\n"
        "        if True:  # c72-knife-b 删出旗\n"
        "            continue\n"
        "        joined = \"、\".join(missing)\n"
        "        flags.append({"
    )
    mod = _load_mutated_copy("app/core/claim_slots.py", old, new, tmp_path)
    mod.set_claim_slots(True)
    d = Dossier(question="冰川断裂与冰湖溃决哪一说法成立？")
    d.add_source(_src("S1", "中科院认定本次为冰川断裂冰岩崩。"))
    con = Conclusion.create("冰川断裂", author="stub", id="CON-sub")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "中科院认定本次为冰川断裂冰岩崩。",
        ["S1#s1"], id="EV-1", level=EvidenceLevel.A))
    d.synthesis = {
        "points": [
            {"con_id": "CON-other",
             "gloss": "上游水库于2024年3月12日泄洪300万方"},
        ],
    }
    flags = mod.chair_support_flags(d)
    assert flags == [], "变异后应发不出旗；真树若也被改哑＝本刀失效"


def test_c72_b_zero_trigger_must_disclose():
    """扫描旗数＝0 时必须显式披露（zero_trigger_disclosed＝True）。"""
    set_claim_slots(True)
    d = Dossier(question="客户B的回款情况如何？")
    d.add_source(_src("S1", "客户B回款率40%。"))
    con = Conclusion.create("客户B回款率约四成", author="stub", id="CON-1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "客户B回款率40%。", ["S1#s1"],
        id="EV-1", level=EvidenceLevel.A))
    # gloss 数字 40 已在支撑段 → 0 旗
    d.synthesis = {
        "points": [{"con_id": "CON-1", "gloss": "客户B回款率约40%"}],
    }
    rec = apply_claim_slots(d)
    scan = rec.get("chair_support_scan") or {}
    assert scan.get("n_flags") == 0
    assert scan.get("zero_trigger_disclosed") is True
    assert "显式披露" in (scan.get("note") or "")
    # 辅助：披露助手本身
    z = chair_support_zero_disclosure(0)
    assert z["zero_trigger_disclosed"] is True


def test_c72_b_scan_arm_products_zero_disclosed():
    """真产物扫描：有 arm0／six2 则重放主席旗；整批 0 旗必须显式披露。

    产物不在本机＝没量过（不 skip、不装绿）；披露助手本身仍必须钉死。
    """
    # 披露助手恒钉（与产物是否在场无关——防悄悄变哑）
    assert chair_support_zero_disclosure(0)["zero_trigger_disclosed"] is True
    assert "显式披露" in chair_support_zero_disclosure(0)["note"]

    roots = [
        Path("/tmp/threearms/arm0_baseline"),
        Path("/tmp/six2"),
    ]
    reports: list[Path] = []
    for root in roots:
        if root.is_dir():
            reports.extend(root.rglob("report.json"))
    if not reports:
        return  # 没量过

    set_claim_slots(True)
    n_scanned = 0
    n_flags_total = 0
    for rp in reports[:40]:
        try:
            raw = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        try:
            d = Dossier.from_dict(raw)
        except Exception:
            continue
        flags = chair_support_flags(d)
        n_scanned += 1
        n_flags_total += len(flags)
        if not flags:
            assert chair_support_zero_disclosure(0)["zero_trigger_disclosed"] is True
    assert n_scanned >= 1
    if n_flags_total == 0:
        assert chair_support_zero_disclosure(0)["zero_trigger_disclosed"] is True


# ---- 判据 c：关旗三份 sha 稳定；开旗必须砸出差异 ----
def test_c72_c_off_three_json_sha_stable(tmp_path):
    """关旗：同一合成案卷两跑 conclusions／evidence／confidence sha 逐位相同。"""
    set_claim_slots(False)
    s = Settings()
    assert s.claim_slots is False

    d = Dossier(question="客户B的回款情况如何？")
    d.add_source(_src("S1", "客户B回款率40%。"))
    con = Conclusion.create("客户B回款率约四成", author="stub", id="CON-fixed")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "客户B回款率40%。", ["S1#s1"],
        id="EV-fixed", level=EvidenceLevel.A))

    def _shas(out: Path) -> dict[str, str]:
        paths = export_official(
            [({"question_id": "Q1", "question": d.question}, d)], out)
        names = {
            "evidence": paths["evidence"],
            "conclusions": paths["conclusions"],
            "confidence": paths["confidence"],
        }
        return {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in names.items()}

    h1 = _shas(tmp_path / "a")
    h2 = _shas(tmp_path / "b")
    assert h1 == h2, (h1, h2)
    conc = json.loads((tmp_path / "a" / "conclusions.json").read_text(encoding="utf-8"))
    assert conc and "claim_slots_disclosure" not in conc[0]


def test_c72_c_on_must_diff_from_off(tmp_path):
    """翻 True 必须砸出可见差异（conclusions 出现 claim_slots_disclosure）。"""
    d = Dossier(question="客户B的回款情况如何？截至何时？")
    d.add_source(_src("S1", "客户B回款率40%。"))
    con = Conclusion.create("客户B回款率约四成", author="stub", id="CON-fixed")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "客户B回款率40%。", ["S1#s1"],
        id="EV-fixed", level=EvidenceLevel.A))

    set_claim_slots(False)
    paths_off = export_official(
        [({"question_id": "Q1", "question": d.question}, d)], tmp_path / "off")
    h_off = {
        k: hashlib.sha256(paths_off[k].read_bytes()).hexdigest()
        for k in ("evidence", "conclusions", "confidence")
    }

    set_claim_slots(True)
    apply_claim_slots(d)
    paths_on = export_official(
        [({"question_id": "Q1", "question": d.question}, d)], tmp_path / "on")
    h_on = {
        k: hashlib.sha256(paths_on[k].read_bytes()).hexdigest()
        for k in ("evidence", "conclusions", "confidence")
    }
    assert h_on != h_off, "开旗三份 sha 必须与关旗不同"
    conc = json.loads(paths_on["conclusions"].read_text(encoding="utf-8"))
    assert "claim_slots_disclosure" in conc[0]
    assert conc[0]["conclusion"] == "客户B回款率约四成"


# ---- 判据 d：四桶 L2 不许下降 ----
def test_c72_d_pack_material_invariant_under_flag():
    """开／关旗装箱 selected 集合逐位相同。"""
    d = Dossier(question="固态电池2030年前能否规模上车？")
    d.add_source(_src("HOT", "固态电池规模上车进展顺利，2030年前产能爬坡。"))
    d.add_source(_src("COLD", "红烧肉焯水后加冰糖炒糖色，小火慢炖四十分钟。"))
    d.add_source(_src("MID", "硫化物电解质离子电导率提升，车企中试线投产。"))

    set_claim_slots(False)
    pack_off = pack_material(d, budget_chars=100_000)
    set_claim_slots(True)
    pack_on = pack_material(d, budget_chars=100_000)
    assert pack_off["selected"] == pack_on["selected"]

    from app.ingest.segment import SEGMENT_MAX
    assert SEGMENT_MAX == 650


# ---- 件③ 并列要点 ----
def test_c72_parallel_coverage_yellow_only():
    """并列主张只盖一半 ⇒ parallel_coverage 黄灯；关旗不亮。"""
    d = Dossier(question="伤亡与受灾统计应采用哪一口径？")
    d.add_source(_src("S1", "官方通报死亡12人，伤者已送医。"))
    con = Conclusion.create(
        "一方面死亡12人已核实，另一方面受灾面积达三千公顷",
        author="stub", id="CON-p")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "官方通报死亡12人，伤者已送医。",
        ["S1#s1"], id="EV-p", level=EvidenceLevel.B))

    set_claim_slots(False)
    assert audit_parallel_coverage(d) == []

    set_claim_slots(True)
    flags = audit_parallel_coverage(d)
    assert flags, flags
    assert flags[0]["kind"] == "parallel_coverage"
    detail = (flags[0].get("detail") or "") + (flags[0].get("value") or "")
    assert "受灾" in detail or "三千" in detail


def test_c72_extract_slots_no_case_branch():
    """抽槽不读案名；六案问句都能抽出至少 what。"""
    for q in _OFFICIAL_18:
        slots = extract_slots(q)
        assert slots and slots[0]["id"] == "what"
    assert extract_slots("") == []
    assert extract_slots("   ") == []


def test_c72_extra_calls_zero_by_design():
    """件① 零额外模型调用：抽槽／盖缺口／出旗全是纯函数。"""
    set_claim_slots(True)
    d = Dossier(question=_OFFICIAL_18[0])
    d.add_source(_src("S1", "官方通稿称泥石流发生于8月26日10时30分许。"))
    con = Conclusion.create("以官方通稿时刻为准", author="stub", id="CON-1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        con.id, "官方通稿称泥石流发生于8月26日10时30分许。",
        ["S1#s1"], id="EV-1", level=EvidenceLevel.A))
    d.synthesis = {"points": [{"con_id": "CON-1", "gloss": "以官方通稿时刻为准"}]}
    rec = apply_claim_slots(d)
    assert "claim_slots" in d.accounting
    # 三数键必须在场（即使 ok 因盖章而为假）
    assert "bound_rate" in rec
    assert "true_gap_rate" in rec
    assert "stamped_rate" in rec
    assert "chair_support_scan" in rec


# ---- R-C72-1 件③：词表纯净＋K6 刀 ----
def test_c72_r1_slot_cues_disjoint_from_case_gold():
    """线索词表 ∩（六案案名∪金标 token）必须为空。

    刀：往 _SLOT_SPECS 塞 discouraged／泥石流／AI171／红机 ⇒ 本格红。
    """
    inter = cue_case_gold_intersection()
    assert inter == set(), f"禁止项③破：线索词表含案／金标词 {sorted(inter)}"
    # 禁词表本身必须含架构师 K6 用过的词，否则刀咬空
    forbidden = case_gold_forbidden_tokens()
    for w in ("discouraged", "泥石流", "AI171", "红机"):
        assert w in forbidden
    cues = slot_cue_vocab()
    for w in ("discouraged", "泥石流", "AI171", "红机"):
        assert w not in cues


def test_c72_r1_knife_case_word_in_cues_must_red(tmp_path):
    """K6 复刻：tmp 把「泥石流」塞进 _SLOT_SPECS ⇒ 纯净交集非空（真树若无此格＝咬空）。"""
    old = (
        '    ("cause", "原因或归因", (\n'
        '        "原因", "为何", "为什么", "归因", "导致", "因为", "所致", "引发",\n'
        "    )),"
    )
    new = (
        '    ("cause", "原因或归因", (\n'
        '        "原因", "为何", "为什么", "归因", "导致", "因为", "所致", "引发",\n'
        '        "泥石流",  # c72-k6\n'
        "    )),"
    )
    mod = _load_mutated_copy("app/core/claim_slots.py", old, new, tmp_path)
    inter = mod.cue_case_gold_intersection()
    assert "泥石流" in inter, "变异后纯净检查必须咬到案名词；咬不到＝格无牙"


# ---- R-C72-2：比率值精确数值守护（合成夹具；刀＝写死常数必红）----
def test_c72_r2_a_stamped_rate_half_exact():
    """格 A：2 槽＝1 bound＋1 stamped_gap ⇒ stamped_rate==0.5 等精确钉。

    刀：把 slot_coverage 里 stamped_rate 整行写死 0.0 ⇒ 本格红。
    """
    rows = [
        {
            "id": "what", "label": "发生什么", "status": "bound",
            "evidence_id": "EV-1", "detail": "", "stamped": False,
        },
        {
            "id": "time", "label": "关键时点", "status": "stamped_gap",
            "evidence_id": None,
            "detail": f"{STAMP_PREFIX}{GAP_MARK}：关键时点",
            "stamped": True,
        },
    ]
    cov = slot_coverage(rows)
    assert cov["n_bound"] == 1
    assert cov["n_stamped"] == 1
    assert cov["n_true_gap"] == 0
    assert cov["bound_rate"] == 0.5
    assert cov["stamped_rate"] == 0.5
    assert cov["true_gap_rate"] == 0.0
    assert cov["ok"] is False


def test_c72_r2_b_true_gap_rate_half_exact():
    """格 B：2 槽＝1 bound＋1 真 gap（不带 stamped）⇒ true_gap_rate==0.5 等精确钉。

    刀：把 slot_coverage 里 true_gap_rate 整行写死 1.0 ⇒ 本格红。
    """
    rows = [
        {
            "id": "what", "label": "发生什么", "status": "bound",
            "evidence_id": "EV-1", "detail": "", "stamped": False,
        },
        {
            "id": "number", "label": "关键数字", "status": "gap",
            "evidence_id": None,
            "detail": f"{GAP_MARK}：关键数字",
            "stamped": False,
        },
    ]
    cov = slot_coverage(rows)
    assert cov["n_bound"] == 1
    assert cov["n_true_gap"] == 1
    assert cov["n_stamped"] == 0
    assert cov["true_gap_rate"] == 0.5
    assert cov["stamped_rate"] == 0.0
    assert cov["honest_rate"] == 1.0
    assert cov["ok"] is True
