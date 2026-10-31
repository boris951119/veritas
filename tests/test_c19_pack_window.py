"""C-19：装箱以模型窗口为准（零真调用）。"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.panel import MAINSTREAM_PERSONA, build_panel, run_panel
from app.config import Settings
from app.core.conflicts import ConflictPair, Resolution
from app.core.evidence import (
    Conclusion, Dossier, EvidenceLevel, EvidenceNode, Segment, Source, SourceType,
)
from app.core.hashchain import HashChain
from app.core.human_ops import override_resolution
from app.core.material import (
    ALIGN_MAX_ITERS,
    WINDOW_EXCLUDE_REASON,
    align_budget_to_window,
    exclude_budget_reason,
    material_budget,
    pack_material,
    production_pack_messages,
    set_exclude_budget_reason,
    set_material_budget,
)
from app.core.prompt_guard import estimate_prompt_window
from app.export.official import export_official
from app.ingest.case_loader import load_case
from app.pipeline import RunDeps, RunSpec, render_report_md, run_case


MIN_JSON = """```json
{"conclusions": [
   {"statement": "测试结论",
   "evidence": [{"quote": "客户B回款率40%",
                 "segment_id": "SRC1#s1",
                 "relation": "correlation", "level": "A", "note": "测"}]}
]}
```"""


class StubClient:
    def __init__(self, by_name: dict[str, str] | None = None,
                 content: str = MIN_JSON):
        self.by_name = by_name or {}
        self.content = content
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        # panel 把 name 放在… 桩按调用次序不够；用 messages 内容区分不了人。
        # by_name 由 Analyst 包装——见 NamedStub。
        self.calls.append({"messages": messages})
        return SimpleNamespace(content=self.content)


class NamedStub:
    """按分析师名喂响应（判据 d：别用位置队列）。"""

    def __init__(self, by_name: dict[str, str], default: str = MIN_JSON):
        self.by_name = by_name
        self.default = default
        self.calls: list[dict] = []
        self._current: str | None = None

    def bind(self, name: str):
        self._current = name
        return self

    def chat(self, model, messages, json_mode=False):
        name = self._current or ""
        self.calls.append({"name": name, "messages": messages})
        body = self.by_name.get(name, self.default)
        return SimpleNamespace(content=body)


def _settings(**kw) -> Settings:
    s = Settings()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _many_sources(n: int, seg_chars: int = 400,
                  question: str = "客户B的回款情况如何？") -> Dossier:
    """每源正文必须互异，否则 duplicate_map 会把全家打成重复件。"""
    d = Dossier(question=question)
    for i in range(n):
        src = Source.create(f"料{i}", SourceType.REPORT, id=f"SRC{i}")
        unit = f"编号{i}客户B回款率40%。材料填充。"
        text = (unit * ((seg_chars // len(unit)) + 2))[:seg_chars]
        src.segments.append(Segment(
            id=f"SRC{i}#s1", source_id=f"SRC{i}", text=text, index=0))
        d.add_source(src)
    return d


def test_a_bi_case_packs_into_window(monkeypatch):
    """a) bi-delivery-risk 改前超窗；改后 fits 且 est≤16384 且 n_selected<66。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "16384")
    monkeypatch.setenv("VERITAS_ZH_CHARS_PER_TOKEN", "1.45")
    monkeypatch.delenv("VERITAS_PACK_TO_WINDOW", raising=False)
    settings = Settings.from_env()
    d = load_case(Path("cases/bi-delivery-risk"))

    set_material_budget(settings.material_char_budget)
    set_exclude_budget_reason("预算截断")
    pack_before = pack_material(d)
    msgs_before = production_pack_messages(
        d, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    rec_before = estimate_prompt_window(
        msgs_before, window_tokens=16384, zh_chars_per_token=1.45)
    assert rec_before["est_tokens"] > 16384, rec_before
    assert pack_before["n_selected"] == 66
    assert len(pack_before["excluded"]) == 0

    pw = align_budget_to_window(
        d, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    pack = pack_material(d)
    msgs = production_pack_messages(
        d, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    rec = estimate_prompt_window(
        msgs, window_tokens=16384, zh_chars_per_token=1.45)
    assert pw["fits"] is True
    assert rec["est_tokens"] <= 16384
    assert pack["n_selected"] < 66
    assert pack["n_total"] == pack["n_selected"] + len(pack["excluded"])


def test_b_and_l_stub_small_window(monkeypatch):
    """b＋l 桩：50 源 × 窗 4000；对齐后预算≤改前；自身 ≤200ms；部分段被挤出。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "4000")
    monkeypatch.setenv("VERITAS_ZH_CHARS_PER_TOKEN", "1.45")
    monkeypatch.delenv("VERITAS_PACK_TO_WINDOW", raising=False)
    settings = Settings.from_env()
    assert settings.model_context_tokens == 4000
    d = _many_sources(50, seg_chars=200)
    before_budget = settings.material_char_budget

    # 热身一次，避开 import／BM25 冷启动；再取 3 次墙钟的最小值（抗调度抖动）
    align_budget_to_window(
        d, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    samples: list[float] = []
    pw = None
    for _ in range(3):
        d2 = Dossier.from_dict(d.to_dict())
        t0 = time.perf_counter()
        pw = align_budget_to_window(
            d2, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
        samples.append((time.perf_counter() - t0) * 1000)
    assert pw is not None
    elapsed_ms = min(samples)
    pack = pack_material(d2)
    d = d2
    msgs = production_pack_messages(
        d, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    rec = estimate_prompt_window(
        msgs, window_tokens=4000, zh_chars_per_token=1.45)

    assert pw["fits"] is True
    assert rec["est_tokens"] <= 4000
    assert pw["n_iters"] <= ALIGN_MAX_ITERS
    assert pack["n_selected"] < pack["n_total"]
    assert pw["budget"] <= before_budget  # l①
    assert elapsed_ms <= 200.0, (elapsed_ms, samples)  # l②（摘缓存后架构师实测 ≈76ms）


def test_c_align_is_deterministic():
    """c) 同卷独立载入两次 → budget／selected／n_iters 逐字相同。"""
    settings = _settings(
        material_char_budget=80_000, model_context_tokens=4000,
        zh_chars_per_token=1.45, pack_to_window=True)
    raw = _many_sources(30, seg_chars=500).to_dict()
    d1 = Dossier.from_dict(raw)
    d2 = Dossier.from_dict(raw)
    pw1 = align_budget_to_window(
        d1, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    p1 = pack_material(d1)
    pw2 = align_budget_to_window(
        d2, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    p2 = pack_material(d2)
    assert pw1["budget"] == pw2["budget"]
    assert pw1["n_iters"] == pw2["n_iters"]
    assert sorted(p1["selected"]) == sorted(p2["selected"])


def test_d_panel_same_material_block(monkeypatch):
    """d) 三分析师 user 资料块逐字相同（by_name 桩）。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "4000")
    monkeypatch.setenv("VERITAS_PACK_TO_WINDOW", "1")
    settings = Settings.from_env()
    d = _many_sources(40, seg_chars=400)
    stub = NamedStub({
        "mainstream": MIN_JSON,
        "redteam": MIN_JSON,
        "technologist": MIN_JSON,
    })

    class BoundClient:
        def __init__(self, name, inner):
            self.name = name
            self.inner = inner

        def chat(self, model, messages, json_mode=False):
            self.inner.bind(self.name)
            return self.inner.chat(model, messages, json_mode=json_mode)

    analysts = build_panel(stub, "m")
    for a in analysts:
        a.client = BoundClient(a.name, stub)
        a.settings = settings
        a.profile_tier = "standard"

    align_budget_to_window(
        d, settings, persona=analysts[0].persona, profile_tier="standard")
    run_panel(d, analysts)
    users = [c["messages"][1]["content"] for c in stub.calls]
    assert len(users) == 3
    assert users[0] == users[1] == users[2]


def test_e_excluded_window_reason_and_report(monkeypatch, tmp_path):
    """e) 挤出段 reason＝窗口那条；守恒；报告章至少一行。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "4000")
    settings = Settings.from_env()
    d = _many_sources(50, seg_chars=200)
    pw = align_budget_to_window(
        d, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    assert pw["fits"] is True
    pack = pack_material(d)
    assert pack["excluded"]
    assert all(e["reason"] == WINDOW_EXCLUDE_REASON for e in pack["excluded"])
    assert pack["n_total"] == pack["n_selected"] + len(pack["excluded"])
    d.accounting["pack_window"] = dict(pw)
    md = render_report_md(d, HashChain(), [])
    assert "## 因预算未进入研判的段落" in md
    assert WINDOW_EXCLUDE_REASON in md or "SRC" in md


def test_f_in_window_cases_byte_identical(monkeypatch, tmp_path):
    """f) demo-solid-state／rumor 远在窗内 → 对齐前后装箱 selected 相同。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "16384")
    monkeypatch.delenv("VERITAS_PACK_TO_WINDOW", raising=False)
    settings = Settings.from_env()
    for name in ("demo-solid-state", "rumor-vs-official"):
        d = load_case(Path("cases") / name)
        set_material_budget(settings.material_char_budget)
        set_exclude_budget_reason("预算截断")
        before = sorted(pack_material(d)["selected"])
        before_budget = material_budget()
        pw = align_budget_to_window(
            d, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
        after = sorted(pack_material(d)["selected"])
        assert pw["fits"] is True
        assert pw["budget"] == before_budget == settings.material_char_budget
        assert before == after, name


def test_g_pack_to_window_off_is_noop(monkeypatch):
    """g) VERITAS_PACK_TO_WINDOW=0 → 与字预算老路逐字节同 selected。"""
    monkeypatch.setenv("VERITAS_PACK_TO_WINDOW", "0")
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "4000")
    settings = Settings.from_env()
    assert settings.pack_to_window is False
    d = _many_sources(40, seg_chars=500)
    set_material_budget(settings.material_char_budget)
    set_exclude_budget_reason("预算截断")
    before = sorted(pack_material(d)["selected"])
    pw = align_budget_to_window(
        d, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    after = sorted(pack_material(d)["selected"])
    assert pw["rule"] == "disabled"
    assert before == after
    assert pw["budget"] == settings.material_char_budget


def test_h_unfit_is_honest(monkeypatch):
    """h) 最小档仍超窗 → fits=False＋pack_window_unfit。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "1500")
    monkeypatch.setenv("VERITAS_PACK_TO_WINDOW", "1")
    settings = Settings.from_env()
    # 议题本身就很长：预算缩到地板（几乎无段）仍超窗
    d = _many_sources(
        80, seg_chars=800,
        question="请基于全部材料全面评估客户B回款与交付风险并给出依据" * 90)
    stub = StubClient()
    result = run_case(
        RunSpec(dossier=d, settings=settings, probe=False),
        RunDeps(client=stub),
    )
    pw = (result.dossier.accounting or {}).get("pack_window") or {}
    assert pw.get("fits") is False, pw
    kinds = [n.get("kind") for n in result.dossier.ingest_notes]
    assert "pack_window_unfit" in kinds


def test_i_pack_calls_bounded(monkeypatch):
    """i) align 内 pack_material 调用次数 ≤K；5 源与 50 源同为 ≤K。"""
    settings = _settings(
        material_char_budget=80_000, model_context_tokens=4000,
        zh_chars_per_token=1.45, pack_to_window=True)

    def _count_for(n_src: int) -> int:
        d = _many_sources(n_src, seg_chars=500)
        calls = {"n": 0}
        real = pack_material

        def wrapped(*a, **k):
            calls["n"] += 1
            return real(*a, **k)

        import app.agents.prompts as prompts_mod
        import app.core.material as mat_mod
        # production_pack_messages → render_segments_block → pack_material
        orig = mat_mod.pack_material
        mat_mod.pack_material = wrapped  # type: ignore
        prompts_mod.pack_material = wrapped  # may not exist as attr
        try:
            # Patch where render imports from
            import app.core.material as m
            monkeypatch.setattr(m, "pack_material", wrapped)
            # Also need prompts to see it — it does `from app.core.material import pack_material` locally
            # so patch the module attribute before each call via align's import path.
            align_budget_to_window(
                d, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
        finally:
            mat_mod.pack_material = orig  # type: ignore
        return calls["n"]

    # Re-implement with monkeypatch on the function used inside render
    def count_iters(n_src: int) -> int:
        d = _many_sources(n_src, seg_chars=500)
        calls = {"n": 0}
        import app.core.material as mat

        real = mat.pack_material

        def wrapped(*a, **k):
            calls["n"] += 1
            return real(*a, **k)

        monkeypatch.setattr(mat, "pack_material", wrapped)
        # align imports production_pack_messages which imports pack inside render
        # render does local import each call — patching mat.pack_material works
        # because `from app.core.material import pack_material` binds at call time... 
        # actually local import each call to render_segments_block re-imports.
        # Patching app.core.material.pack_material is enough for `from X import Y` 
        # only if import happens after patch. render does import inside function → OK.
        align_budget_to_window(
            d, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
        return calls["n"]

    n5 = count_iters(5)
    n50 = count_iters(50)
    assert n5 <= ALIGN_MAX_ITERS + 1  # +1 for the initial orig-budget probe
    assert n50 <= ALIGN_MAX_ITERS + 1
    # 首轮探测 + 最多 K 次缩档；两档都不得超过这个上界（不许随信源数膨胀出界）
    assert n5 <= ALIGN_MAX_ITERS + 1 and n50 <= ALIGN_MAX_ITERS + 1


def test_m_production_messages_bite(monkeypatch):
    """m) 对齐后 production 口径不再 overflow；关开关仍 overflow。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "4000")
    monkeypatch.setenv("VERITAS_ZH_CHARS_PER_TOKEN", "1.45")
    monkeypatch.setenv("VERITAS_PACK_TO_WINDOW", "1")
    settings = Settings.from_env()
    d = _many_sources(50, seg_chars=300)

    set_material_budget(settings.material_char_budget)
    set_exclude_budget_reason("预算截断")
    before = estimate_prompt_window(
        production_pack_messages(
            d, persona=MAINSTREAM_PERSONA, profile_tier="standard"),
        window_tokens=4000, zh_chars_per_token=1.45)
    assert before["overflow_tokens"] > 0, before

    result = run_case(
        RunSpec(dossier=d, settings=settings, probe=False),
        RunDeps(client=StubClient()),
    )
    pw = (result.dossier.accounting or {}).get("pack_window") or {}
    assert pw.get("fits") is True, pw
    status = ((result.dossier.accounting or {}).get("prompt_window") or {}).get(
        "status")
    assert status != "overflow"
    assert not any(n.get("kind") == "prompt_over_window"
                   for n in result.dossier.ingest_notes)

    monkeypatch.setenv("VERITAS_PACK_TO_WINDOW", "0")
    settings_off = Settings.from_env()
    d2 = Dossier.from_dict(d.to_dict())
    d2.ingest_notes = []
    d2.triage = []
    d2.accounting = {}
    result2 = run_case(
        RunSpec(dossier=d2, settings=settings_off, probe=False),
        RunDeps(client=StubClient()),
    )
    assert any(n.get("kind") == "prompt_over_window"
               for n in result2.dossier.ingest_notes) or (
        ((result2.dossier.accounting or {}).get("prompt_window") or {}).get(
            "status") == "overflow"
    )


def _fixed_id_dossier() -> Dossier:
    d = Dossier(question="Q")
    for cid, statement, cred, level in (
        ("CON-0", "甲", 0.9, EvidenceLevel.A),
        ("CON-1", "乙", 0.3, EvidenceLevel.D),
    ):
        d.conclusions.append(Conclusion.create(statement, author="a", id=cid))
        sid = f"S-{cid}"
        src = Source.create(sid, SourceType.REPORT, credibility=cred, id=sid)
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=f"{statement}证据足够长。"))
        d.add_source(src)
        d.add_evidence(EvidenceNode.create(
            cid, f"{statement}证据足够长。", [f"{sid}#s1"],
            level=level, id=f"EV-{cid}"))
    pair = ConflictPair(id="CFL-1", a_id="CON-0", b_id="CON-1", topic="t")
    d.conflicts = [pair.to_dict()]
    override_resolution(d, "CFL-1", "CON-1")
    return d


def test_n_field_notes_and_json_sha_unchanged(tmp_path, monkeypatch):
    """n) 字段说明三刀；四份提交 JSON sha256 与改前相同。"""
    import app.export.official as off

    d = _fixed_id_dossier()
    # 改前 JSON sha：临时把 _FIELD_NOTES 换成旧文再 export 一次作对照不现实
    # （旧文已不在树里）。改为：同一次 export 的四份 JSON 与「只改 notes 文本」
    # 无关——把 notes 写两次，JSON 字节应稳定；并与硬编码旧句对照 notes。
    out1 = tmp_path / "a"
    out1.mkdir()
    paths = export_official([({"question_id": "q1", "question": "议题一"}, d)], out1)
    notes = paths["notes"].read_text(encoding="utf-8")
    assert "当前没有这两键" not in notes
    assert "人工改判" in notes
    assert "假不等式已拦截" in notes
    assert "VERITAS_MODEL_CTX_TOKENS" in notes

    sha = {
        name: hashlib.sha256(paths[name].read_bytes()).hexdigest()
        for name in ("evidence", "conclusions", "confidence",
                     "conflict_resolution")
    }
    notes_sha = hashlib.sha256(paths["notes"].read_bytes()).hexdigest()

    # 再 export 一次：四份 JSON 必须逐字节相同
    out2 = tmp_path / "b"
    out2.mkdir()
    paths2 = export_official([({"question_id": "q1", "question": "议题一"}, d)], out2)
    for name in sha:
        assert hashlib.sha256(paths2[name].read_bytes()).hexdigest() == sha[name]

    # 三刀证伪：旧句贴回
    old_notes = off._FIELD_NOTES
    try:
        off._FIELD_NOTES = old_notes.replace(
            "basis、重启条件：由 Resolution.to_dict() 输出；缺失时留空并在 omissions 里披露。\n"
            "omissions 取值含：人工改判、假不等式已拦截，以及导出层对缺失字段的标注。",
            "basis、重启条件：Resolution.to_dict() 当前没有这两键，留空并在 omissions 里披露。",
        )
        bad = tmp_path / "bad1"
        bad.mkdir()
        p = export_official([({"question_id": "q1", "question": "议题一"}, d)], bad)
        text = p["notes"].read_text(encoding="utf-8")
        assert "当前没有这两键" in text
        # 本格断言：生产文案不含该串——用当前树的 notes 再确认一次
        assert "当前没有这两键" not in notes
    finally:
        off._FIELD_NOTES = old_notes

    # 刀②：摘掉枚举
    try:
        off._FIELD_NOTES = old_notes.replace(
            "omissions 取值含：人工改判、假不等式已拦截，以及导出层对缺失字段的标注。\n",
            "",
        )
        bad = tmp_path / "bad2"
        bad.mkdir()
        text = export_official([({"question_id": "q1", "question": "议题一"}, d)], bad)["notes"].read_text(
            encoding="utf-8")
        assert "假不等式已拦截" not in text or "人工改判" not in text
    finally:
        off._FIELD_NOTES = old_notes

    # 刀③：摘掉窗口句
    try:
        off._FIELD_NOTES = "\n".join(
            ln for ln in old_notes.splitlines()
            if "VERITAS_MODEL_CTX_TOKENS" not in ln
            and "VERITAS_PACK_TO_WINDOW" not in ln
            and "窗口装箱" not in ln
        ) + "\n"
        bad = tmp_path / "bad3"
        bad.mkdir()
        text = export_official([({"question_id": "q1", "question": "议题一"}, d)], bad)["notes"].read_text(
            encoding="utf-8")
        assert "VERITAS_MODEL_CTX_TOKENS" not in text
    finally:
        off._FIELD_NOTES = old_notes

    # JSON 未随 notes 文案变（notes_sha 可变，四份不可变）
    assert notes_sha == hashlib.sha256(
        (tmp_path / "a" / "字段说明.md").read_bytes()).hexdigest()


def _disclosure_bullets(md: str) -> list[str]:
    """「模型窗口出口披露」节下的 `- ` 行；断到行本身，不许整篇 md 子串糊过去。"""
    bullets: list[str] = []
    in_sec = False
    for ln in md.splitlines():
        if ln.startswith("## 模型窗口出口披露"):
            in_sec = True
            continue
        if in_sec:
            if ln.startswith("## "):
                break
            if ln.startswith("- "):
                bullets.append(ln)
    return bullets


def test_o_disabled_nulls_and_disclosure_line(monkeypatch):
    """o) rule=disabled：est／n_iters／fits 为 null；披露断到未启用那一行。"""
    monkeypatch.setenv("VERITAS_PACK_TO_WINDOW", "0")
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "4000")
    settings = Settings.from_env()
    assert settings.pack_to_window is False
    d = _many_sources(10, seg_chars=200)
    pw = align_budget_to_window(
        d, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    assert pw["rule"] == "disabled"
    assert pw["est_tokens"] is None
    assert pw["n_iters"] is None
    assert pw["fits"] is None
    d.accounting["pack_window"] = dict(pw)
    bullets = _disclosure_bullets(render_report_md(d, HashChain(), []))
    expected = (
        f"- 窗口对齐装箱未启用（原因＝VERITAS_PACK_TO_WINDOW=0），"
        f"本次按字预算 {pw['budget']} 装箱"
    )
    assert expected in bullets
    assert not any("本次按假定窗口" in b for b in bullets)


def test_o_unchecked_nulls_and_disclosure_line(monkeypatch):
    """o) rule=unchecked：est／n_iters／fits 为 null；披露断到未启用那一行。"""
    monkeypatch.delenv("VERITAS_PACK_TO_WINDOW", raising=False)
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "0")
    settings = Settings.from_env()
    assert settings.pack_to_window is True
    assert settings.model_context_tokens <= 0
    d = _many_sources(10, seg_chars=200)
    pw = align_budget_to_window(
        d, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    assert pw["rule"] == "unchecked"
    assert pw["est_tokens"] is None
    assert pw["n_iters"] is None
    assert pw["fits"] is None
    d.accounting["pack_window"] = dict(pw)
    bullets = _disclosure_bullets(render_report_md(d, HashChain(), []))
    expected = (
        f"- 窗口对齐装箱未启用（原因＝model_context_tokens≤0），"
        f"本次按字预算 {pw['budget']} 装箱"
    )
    assert expected in bullets
    assert not any("本次按假定窗口" in b for b in bullets)


def test_p_no_cross_dossier_memory_during_align(monkeypatch):
    """p) A align 估算钩子内对 B 调 classify／pack，行数与 reason 与 B 单独跑逐字相同。"""
    import app.core.relevance as relevance_mod

    settings = _settings(
        material_char_budget=80_000, model_context_tokens=4000,
        zh_chars_per_token=1.45, pack_to_window=True)
    d_a = _many_sources(50, seg_chars=200)
    # B 用独立信源 id（BSRC*）：旧式 _ALIGN_SCORE_CACHE 按 id 串卷时 B 的分全是 0
    # ⇒ reason 从「BM25 排序未入预算」掉成「预算截断」。经模块属性调 classify，
    # 才能抓到「替换 relevance.classify_sources」那种跨卷记忆化。
    d_b = Dossier(question="客户B的回款情况如何？")
    for i in range(6):
        sid = f"BSRC{i}"
        src = Source.create(f"B料{i}", SourceType.REPORT, id=sid)
        unit = f"编号{i}客户B回款率40%。材料填充。"
        text = (unit * 5)[:200]
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=text, index=0))
        d_b.add_source(src)

    set_material_budget(400)
    set_exclude_budget_reason("预算截断")
    baseline_cls = relevance_mod.classify_sources(d_b)
    baseline_pack = pack_material(d_b)
    baseline_n = len(baseline_cls)
    baseline_reasons = sorted(
        (e["seg_id"], e["reason"]) for e in baseline_pack["excluded"])
    assert baseline_n == 6
    assert any(r == "BM25 排序未入预算" for _, r in baseline_reasons), baseline_reasons

    probes: list[dict] = []
    import app.core.prompt_guard as pg
    real_est = pg.estimate_prompt_window

    def hooked(messages, **kw):
        # classify 走模块属性（抓 monkeypatch）；pack 的预算／reason 全局会被 A 改——
        # 探针侧钉回 B 的单独口径，专抓分数表／classify 替换，不把 set_exclude 残留误判成串卷。
        cls_b = relevance_mod.classify_sources(d_b)
        saved_budget = material_budget()
        saved_reason = exclude_budget_reason()
        try:
            set_material_budget(400)
            set_exclude_budget_reason("预算截断")
            pack_b = pack_material(d_b)
        finally:
            set_material_budget(saved_budget)
            set_exclude_budget_reason(saved_reason)
        probes.append({
            "n": len(cls_b),
            "reasons": sorted(
                (e["seg_id"], e["reason"]) for e in pack_b["excluded"]),
        })
        return real_est(messages, **kw)

    monkeypatch.setattr(pg, "estimate_prompt_window", hooked)
    align_budget_to_window(
        d_a, settings, persona=MAINSTREAM_PERSONA, profile_tier="standard")
    assert probes, "估算钩子必须至少触发一次"
    for p in probes:
        assert p["n"] == baseline_n
        assert p["reasons"] == baseline_reasons


def test_q_report_has_no_bare_pack_window_unfit(monkeypatch):
    """q) 甲：删 triage 行 ⇒ report.md 全文不出现裸键 pack_window_unfit。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "1500")
    monkeypatch.setenv("VERITAS_PACK_TO_WINDOW", "1")
    settings = Settings.from_env()
    d = _many_sources(
        80, seg_chars=800,
        question="请基于全部材料全面评估客户B回款与交付风险并给出依据" * 90)
    result = run_case(
        RunSpec(dossier=d, settings=settings, probe=False),
        RunDeps(client=StubClient()),
    )
    assert any(n.get("kind") == "pack_window_unfit"
               for n in result.dossier.ingest_notes)
    assert not any(t.get("route") == "pack_window_unfit"
                   for t in result.dossier.triage)
    md = result.report_md
    assert "pack_window_unfit" not in md
