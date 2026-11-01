"""C-29：案卷内同类事件对照台账（零真调用）。含第二轮 R1 展示双上限。"""

from __future__ import annotations

import subprocess

from app.core.citation_check import check_quote
from app.core.confidence import conclude_confidence
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, Segment, Source, SourceType,
)
from app.core.gate_applicability import GATE_SPECS, not_evaluated
from app.core.hashchain import HashChain
from app.core.precedent import (
    EMPTY_LEDGER_LINE,
    EXTERNAL_PRIOR_KIND,
    EXTERNAL_PRIOR_LINE,
    OUT_OF_WINDOW_NOTE,
    PRECEDENT_RENDER_CAP,
    TIME_UNSORTABLE_REASON,
    WINDOW_UNKNOWN_NOTE,
    _seg_by_id,
    audit_external_prior,
    build_precedent_ledger,
    render_precedent_lines,
)
from app.pipeline import render_report_md


def _two_wave(*, dated: bool = True, prior_in_window: bool | None = True) -> Dossier:
    """同一主体两波不同数字；dated=False 时对照端无 published_at。"""
    d = Dossier(question="客户B的回款情况如何？")
    s1 = Source.create("早报", SourceType.REPORT, id="SRC1")
    if dated:
        s1.meta["published_at"] = "2024-01-15"
    s1.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="2024年1月客户B回款率40%。项目进展正常。", index=0))
    d.add_source(s1)
    s2 = Source.create("晚报", SourceType.REPORT, id="SRC2")
    s2.meta["published_at"] = "2025-06-01"
    s2.segments.append(Segment(
        id="SRC2#s1", source_id="SRC2",
        text="2025年6月客户B回款率25%。回款明显恶化。", index=0))
    d.add_source(s2)
    if prior_in_window is True:
        d.accounting["material_pack_selected"] = ["SRC1#s1", "SRC2#s1"]
    elif prior_in_window is False:
        d.accounting["material_pack_selected"] = ["SRC2#s1"]
    return d


def _single_wave() -> Dossier:
    d = Dossier(question="客户B的回款情况如何？")
    s1 = Source.create("早报", SourceType.REPORT, id="SRC1")
    s1.meta["published_at"] = "2024-01-15"
    s1.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="2024年1月客户B回款率40%。项目进展正常。", index=0))
    d.add_source(s1)
    d.accounting["material_pack_selected"] = ["SRC1#s1"]
    return d


def _many_pairs(n: int = 40) -> Dossier:
    """造 n 组同指标对照（n+1 个信源、相邻波次成对）。"""
    d = Dossier(question="客户B的回款情况如何？")
    selected: list[str] = []
    for i in range(n + 1):
        sid = f"SRC{i}"
        src = Source.create(f"波次{i}", SourceType.REPORT, id=sid)
        src.meta["published_at"] = f"2024-{(i % 12) + 1:02d}-15"
        rate = 10 + i  # 互异
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid,
            text=f"2024年客户B回款率{rate}%。材料填充编号{i}。", index=0))
        d.add_source(src)
        selected.append(f"{sid}#s1")
    d.accounting["material_pack_selected"] = selected
    return d


def _section_bullets(md: str) -> list[str]:
    bullets: list[str] = []
    in_sec = False
    for ln in md.splitlines():
        if ln.startswith("## 同类事件对照（案卷内）"):
            in_sec = True
            continue
        if in_sec:
            if ln.startswith("## "):
                break
            if ln.startswith("- "):
                bullets.append(ln)
    return bullets


def test_a_two_wave_ledger_locatable():
    """a) 两波事件 ⇒ 台账≥1 行且两端可定位；报告节存在。"""
    d = _two_wave()
    led = build_precedent_ledger(d)
    assert len(led.rows) >= 1
    for r in led.rows:
        _, seg_c = _seg_by_id(d, r.current_para_id)
        _, seg_p = _seg_by_id(d, r.prior_para_id)
        assert seg_c is not None and seg_p is not None
        assert check_quote(r.current_quote, seg_c.text).ok
        assert check_quote(r.prior_quote, seg_p.text).ok
    d.accounting["precedent"] = led.to_dict()
    md = render_report_md(d, HashChain(), [])
    assert "## 同类事件对照（案卷内）" in md
    bullets = _section_bullets(md)
    assert any("40%" in b and "25%" in b for b in bullets)


def test_a_section_title_present_in_pipeline():
    """a 改后锚点：pipeline 出现「同类事件对照」。"""
    n = int(subprocess.check_output(
        ["grep", "-c", "同类事件对照", "app/pipeline.py"], text=True).strip())
    assert n >= 1


def test_b_single_wave_no_fabricated():
    """b) 单波 ⇒ 0 行＋无可对照句；不许编造对照数字。"""
    d = _single_wave()
    led = build_precedent_ledger(d)
    assert len(led.rows) == 0
    d.accounting["precedent"] = led.to_dict()
    bullets = _section_bullets(render_report_md(d, HashChain(), []))
    assert any(EMPTY_LEDGER_LINE in b for b in bullets)
    body = "\n".join(bullets)
    assert "25%" not in body
    assert "↔" not in body


def test_c_rows_always_locatable():
    """c 正向：生成的每一行两端都能 citation_check。"""
    d = _two_wave()
    for r in build_precedent_ledger(d).rows:
        _, seg_c = _seg_by_id(d, r.current_para_id)
        _, seg_p = _seg_by_id(d, r.prior_para_id)
        assert check_quote(r.current_quote, seg_c.text).ok
        assert check_quote(r.prior_quote, seg_p.text).ok
        assert _seg_by_id(d, r.prior_para_id)[1] is not None


def test_c2_belt_and_braces_filter(monkeypatch):
    """c② 订正后：人造故障让 _quote_around 返回段外串 ⇒ 台账 0 行。

    这道闸今天是 belt-and-braces（官方卷实测触发≈0），不许写成已验证过滤能力。
    变异「摘掉过滤」由回写整套红数证明，不在本格内自红。
    """
    import app.core.precedent as prec

    d = _two_wave()
    monkeypatch.setattr(
        prec, "_quote_around",
        lambda text, raw, radius=24: "这段文字绝不在原文出现的哨兵999%")
    led = prec.build_precedent_ledger(d)
    assert len(led.rows) == 0


def test_d_confidence_invariant():
    """d) 台账前后 confidence_parts 五项＋conf 本身逐字相同。"""
    d = _two_wave()
    con = Conclusion.create("客户B回款率下降", author="a", id="CON-1")
    d.conclusions.append(con)
    d.add_evidence(EvidenceNode.create(
        "CON-1", "客户B回款率25%", ["SRC2#s1"],
        level=EvidenceLevel.B, id="EV-1"))
    conf1, parts1 = conclude_confidence("CON-1", d)
    d.accounting["precedent"] = build_precedent_ledger(d).to_dict()
    conf2, parts2 = conclude_confidence("CON-1", d)
    for k in ("strength", "coverage", "agreement", "chain", "n_evidence"):
        assert parts1.get(k) == parts2.get(k), (k, parts1.get(k), parts2.get(k))
    assert conf1 == conf2


def test_e_external_prior_flag():
    """e) 黄灯 flag kind＝external_prior 在场。"""
    d = _two_wave()
    d.conclusions.append(Conclusion.create(
        "上次同类事件死了850人，本次应低于该数",
        author="a", id="CON-X"))
    flags = audit_external_prior(d)
    assert any(f.get("kind") == EXTERNAL_PRIOR_KIND for f in flags)


def test_e_external_prior_section_line():
    """e) 本节渲染出的整行含「不计入置信度」。"""
    d = _two_wave()
    d.conclusions.append(Conclusion.create(
        "上次同类事件死了850人，本次应低于该数",
        author="a", id="CON-X"))
    d.accounting["precedent"] = build_precedent_ledger(d).to_dict()
    bullets = _section_bullets(render_report_md(d, HashChain(), []))
    assert f"- {EXTERNAL_PRIOR_LINE}" in bullets


def test_e_strength_unchanged_by_external_prior():
    """e) strength 与不注入外部比较句时逐字相同（plain vs injected 轴）。"""
    d_plain = _two_wave()
    d_plain.conclusions.append(Conclusion.create(
        "客户B回款率下降", author="a", id="CON-P"))
    d_plain.add_evidence(EvidenceNode.create(
        "CON-P", "客户B回款率25%", ["SRC2#s1"],
        level=EvidenceLevel.B, id="EV-P"))
    d_ext = _two_wave()
    d_ext.conclusions.append(Conclusion.create(
        "上次同类事件死了850人，客户B回款率下降",
        author="a", id="CON-E"))
    d_ext.add_evidence(EvidenceNode.create(
        "CON-E", "客户B回款率25%", ["SRC2#s1"],
        level=EvidenceLevel.B, id="EV-E"))
    _, p0 = conclude_confidence("CON-P", d_plain)
    _, p1 = conclude_confidence("CON-E", d_ext)
    assert p0["strength"] == p1["strength"]


def test_e_strength_and_conf_unchanged_by_external_prior():
    """e) 亮黄灯／落台账不改 strength 与 conf（同案卷台账前后轴）。"""
    d = _two_wave()
    d.conclusions.append(Conclusion.create(
        "上次同类事件死了850人，客户B回款率下降",
        author="a", id="CON-E"))
    d.add_evidence(EvidenceNode.create(
        "CON-E", "客户B回款率25%", ["SRC2#s1"],
        level=EvidenceLevel.B, id="EV-E"))
    conf0, p0 = conclude_confidence("CON-E", d)
    assert audit_external_prior(d)  # 黄灯在场
    d.accounting["precedent"] = build_precedent_ledger(d).to_dict()
    conf1, p1 = conclude_confidence("CON-E", d)
    assert p0["strength"] == p1["strength"]
    assert conf0 == conf1


def test_f_undated_prior_uses_gate_channel():
    """f) 对照端无 published_at ⇒ 不按时点排；理由走 GateSpec。"""
    d = _two_wave(dated=False)
    led = build_precedent_ledger(d)
    assert led.rows
    assert led.time_sortable is False
    d.accounting["precedent"] = led.to_dict()
    notes = not_evaluated(d)
    assert any(
        n.get("kind") == "precedent_time"
        and TIME_UNSORTABLE_REASON in (n.get("reason") or "")
        for n in notes
    ), notes
    assert any(s.kind == "precedent_time" for s in GATE_SPECS)


def test_g_out_of_window_note():
    """g) 对照端被挤出窗 ⇒ 该行写「该段本次未进入模型视野」。"""
    d = _two_wave(prior_in_window=False)
    led = build_precedent_ledger(d)
    assert any(r.prior_window == OUT_OF_WINDOW_NOTE for r in led.rows)
    d.accounting["precedent"] = led.to_dict()
    bullets = _section_bullets(render_report_md(d, HashChain(), []))
    assert any(OUT_OF_WINDOW_NOTE in b for b in bullets)


def test_g_unknown_window_when_accounting_missing():
    """g) accounting 缺 material_pack_selected ⇒「未核对是否进窗」。"""
    d = _two_wave(prior_in_window=None)
    d.accounting.pop("material_pack_selected", None)
    led = build_precedent_ledger(d)
    assert any(r.prior_window == WINDOW_UNKNOWN_NOTE for r in led.rows)
    d.accounting["precedent"] = led.to_dict()
    bullets = _section_bullets(render_report_md(d, HashChain(), []))
    assert any(WINDOW_UNKNOWN_NOTE in b for b in bullets)


def test_g_pack_material_call_sites_still_two():
    """g) grep -c pack_material( app/pipeline.py 仍＝2。"""
    n = int(subprocess.check_output(
        ["grep", "-c", "pack_material(", "app/pipeline.py"], text=True).strip())
    assert n == 2


# ----- 第二轮 R1：h1 / h2 / h3 -----

def test_h1_render_cap_keeps_full_n_rows():
    """h1) >24 组 ⇒ 本节 - 行 ≤25；accounting n_rows 仍＝真数。"""
    d = _many_pairs(40)
    led = build_precedent_ledger(d)
    assert led.to_dict()["n_rows"] == len(led.rows) >= 25
    d.accounting["precedent"] = led.to_dict()
    # 给一个很小的 rest，迫使字数闸也参与；仍不得超行数帽+披露
    bullets = _section_bullets(
        "\n".join(render_precedent_lines(d, rest_chars=3_000)))
    # 对照行（含指标：）＋可选披露／外部先验
    pair_lines = [b for b in bullets if b.startswith("- 指标：")]
    assert len(pair_lines) <= PRECEDENT_RENDER_CAP
    assert len(bullets) <= PRECEDENT_RENDER_CAP + 2  # 披露＋可能的外部先验
    assert d.accounting["precedent"]["n_rows"] == len(led.rows)
    assert any("另有" in b and "未展示" in b for b in bullets)


def test_h2_row_has_metric_and_entities():
    """h2) 本节整行含「指标：」＋主体标签（断到 bullets）。"""
    d = _two_wave()
    d.accounting["precedent"] = build_precedent_ledger(d).to_dict()
    bullets = _section_bullets(render_report_md(d, HashChain(), []))
    hit = [b for b in bullets if b.startswith("- 指标：")]
    assert hit, bullets
    line = hit[0]
    assert "指标：回款率" in line
    assert "主体：" in line or "本案主体：" in line
    n = int(subprocess.check_output(
        ["grep", "-c", "pack_material(", "app/pipeline.py"], text=True).strip())
    assert n == 2


def test_h3_truncation_disclosure_present():
    """h3 截断态：披露行数字来自计数。"""
    d = _many_pairs(40)
    led = build_precedent_ledger(d)
    d.accounting["precedent"] = led.to_dict()
    bullets = _section_bullets(
        "\n".join(render_precedent_lines(d, rest_chars=50_000)))
    disc = [b for b in bullets if "另有" in b and "未展示" in b]
    assert len(disc) == 1
    # 数字必须来自计数
    shown = len([b for b in bullets if b.startswith("- 指标：")])
    hidden = led.to_dict()["n_rows"] - shown
    assert f"另有 {hidden} 组" in disc[0]
    assert f"本次展示 {shown} 组" in disc[0]
    assert "若干" not in disc[0]


def test_h3_no_disclosure_when_uncapped():
    """h3 不截断态：不许渲披露行。"""
    d = _two_wave()
    led = build_precedent_ledger(d)
    assert len(led.rows) <= PRECEDENT_RENDER_CAP
    d.accounting["precedent"] = led.to_dict()
    bullets = _section_bullets(
        "\n".join(render_precedent_lines(d, rest_chars=10**9)))
    assert not any("未展示" in b for b in bullets)
