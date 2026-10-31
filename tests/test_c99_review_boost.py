# -*- coding: utf-8 -*-
"""C-99 审阅软保底：纯函数 + 开关／回退（零真模型）。"""

from __future__ import annotations

import json

from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.material import pack_material
from app.core.review_boost import (
    fuse_scores,
    pack_with_a0_boost,
    try_review_boost_pack,
)


def _dossier(question: str, segs: list[tuple[str, str]]) -> Dossier:
    src = Source.create(title="t", source_type=SourceType.REPORT, id="s1")
    src.segments = [
        Segment(id=sid, source_id="s1", text=text, index=i)
        for i, (sid, text) in enumerate(segs)
    ]
    return Dossier(question=question, sources=[src])


def test_c99_fuse_review_dominates_bm25():
    bm25 = {"a": 10.0, "b": 1.0}
    id_sc = {"a": 3.0, "b": 9.0}
    fused = fuse_scores(bm25, id_sc)
    assert fused["b"] > fused["a"]


def test_c99_boost_keeps_a0_when_B_huge():
    # 两段：a 短相关，b 长；A0 若装了 a，巨 B 应保住 a
    d = _dossier(
        "刘翔编制是否在岗",
        [
            ("s1#p1", "刘翔在编不在岗 人事档案 " * 20),
            ("s1#p2", "无关天气新闻 " * 80),
        ],
    )
    d.question = "刘翔退役至今是否真有编制与岗位"
    p0 = pack_material(d, budget_chars=400)
    sel_a0 = set(p0["selected"])
    assert sel_a0, "A0 应能装到段"
    # 人为给非 A0 段极高融合分，但 B 更大 → A0 仍优先
    fused = {sid: 0.0 for sid in ["s1#p1", "s1#p2"]}
    for sid in sel_a0:
        fused[sid] = 1.0
    for sid in fused:
        if sid not in sel_a0:
            fused[sid] = 5000.0
    sel = pack_with_a0_boost(d, 400, fused, sel_a0, B=7000)
    assert sel_a0 <= sel


def test_c99_flag_off_returns_a0():
    d = _dossier("议题", [("s1#p1", "正文一段够长用于装箱测试内容。")])
    base = pack_material(d, budget_chars=200)

    def boom(_p: str) -> str:
        raise RuntimeError("should not call")

    pack, disc = try_review_boost_pack(
        d, chat=boom, budget_chars=200, enabled=False)
    assert disc["applied"] is False
    assert disc["reason"] == "flag_off"
    assert set(pack["selected"]) == set(base["selected"])


def test_c99_chat_error_falls_back_a0():
    d = _dossier("议题", [("s1#p1", "正文一段够长用于装箱测试内容。")])
    base = pack_material(d, budget_chars=200)

    def boom(_p: str) -> str:
        raise RuntimeError("guarded")

    pack, disc = try_review_boost_pack(
        d, chat=boom, budget_chars=200, enabled=True)
    assert disc["applied"] is False
    assert disc["reason"] == "error_fallback_a0"
    assert set(pack["selected"]) == set(base["selected"])


def test_c99_stub_chat_applies_when_json_ok():
    d = _dossier(
        "公司净利润多少",
        [
            ("s1#p1", "归母净利润 1000 万元，同比增长。 " * 15),
            ("s1#p2", "今日股市行情综述无关内容。 " * 15),
        ],
    )
    calls = {"n": 0}

    def chat(prompt: str) -> str:
        calls["n"] += 1
        if "审查锚" in prompt or "抽出" in prompt:
            return json.dumps({
                "subject": "公司",
                "dispute": "净利润",
                "time_or_number": "",
                "must_hit": ["净利润"],
                "aliases": [],
                "reject_if": [],
            }, ensure_ascii=False)
        # 批审：按批内段数给分
        n = prompt.count("\n[")
        # 粗数：段落行以 [i] 开头
        import re
        idxs = re.findall(r"^\[(\d+)\]", prompt, flags=re.M)
        scores = [
            {"i": int(i), "score": 9 if int(i) == 0 else 2}
            for i in idxs
        ]
        return json.dumps({"scores": scores}, ensure_ascii=False)

    pack, disc = try_review_boost_pack(
        d, chat=chat, budget_chars=500, enabled=True,
        k=2, refill_n=0, do_refill=False, B=7000,
    )
    assert disc["applied"] is True
    assert calls["n"] >= 2
    assert pack["n_selected"] >= 1


def test_c99_settings_default_on_env_off():
    s = Settings()
    assert s.review_boost is True
    assert s.review_boost_b == 7000.0
    import os
    old = os.environ.get("VERITAS_REVIEW_BOOST")
    try:
        os.environ["VERITAS_REVIEW_BOOST"] = "0"
        s2 = Settings.from_env()
        assert s2.review_boost is False
    finally:
        if old is None:
            os.environ.pop("VERITAS_REVIEW_BOOST", None)
        else:
            os.environ["VERITAS_REVIEW_BOOST"] = old


def test_c99_prompts_honor_granted_selected(monkeypatch):
    d = _dossier("议题", [
        ("s1#p1", "AAA 应进箱的段落内容填充。 " * 10),
        ("s1#p2", "BBB 不应进箱的段落内容填充。 " * 10),
    ])
    d.accounting["material_pack_selected"] = ["s1#p1"]

    def boom(*_a, **_k):
        raise AssertionError("不应再调 pack_material")

    import app.core.material as mat
    monkeypatch.setattr(mat, "pack_material", boom)

    from app.agents.prompts import render_segments_block
    text = render_segments_block(d)
    assert "AAA" in text
    assert "BBB" not in text


def test_c99_pipeline_skips_under_test_guard(tmp_path):
    """默认开时，测试守卫／非 ModelClient 不得吃脚本应答。"""
    from app.pipeline import RunDeps, RunSpec, run_case

    (tmp_path / "manifest.yaml").write_text(
        "question: 议题\n"
        "sources:\n"
        "  - file: a.md\n    type: report\n",
        encoding="utf-8",
    )
    (tmp_path / "a.md").write_text(
        "# A\n\n本段正文足够长用于装箱，包含议题相关事实陈述若干字。\n",
        encoding="utf-8",
    )
    payload = (
        '{"conclusions":[{"statement":"结论一句",'
        '"evidence":[{"quote":"本段正文足够长用于装箱",'
        '"segment_id":"SRC1#s1","relation":"correlation",'
        '"level":"C","note":"n"}]}]}'
    )

    class _Script:
        def __init__(self) -> None:
            self.n = 0

        def chat(self, model, messages, json_mode=False):
            self.n += 1
            if self.n > 3:
                raise IndexError("list index out of range")
            return type("R", (), {"content": payload, "usage": None})()

    client = _Script()
    result = run_case(
        RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out"),
        RunDeps(client=client),
    )
    disc = (result.dossier.accounting or {}).get("review_boost") or {}
    assert disc.get("applied") is False
    assert disc.get("reason") in (
        "test_guard_fallback_a0", "non_model_client",
    )
    assert result.dossier.conclusions
