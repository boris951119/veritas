"""C-9：模型窗口超发出口披露（零真调用）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.agents.base import Analyst
from app.agents.panel import MAINSTREAM_PERSONA, build_panel, run_panel
from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.hashchain import HashChain
from app.core.prompt_guard import estimate_prompt_window
from app.pipeline import render_report_md


MIN_JSON = """```json
{"conclusions": [
   {"statement": "测试结论",
   "evidence": [{"quote": "客户B回款率40%",
                 "segment_id": "SRC1#s1",
                 "relation": "correlation", "level": "A", "note": "测"}]}
]}
```"""


class StubClient:
    def __init__(self, content: str = MIN_JSON):
        self.content = content
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"messages": messages})
        return SimpleNamespace(content=self.content)


def _dossier_with_n_segments(n_segs: int, seg_chars: int = 600) -> Dossier:
    """多段短文案卷：段长 ≤ SEGMENT_MAX，避免提示词侧截断后字数对不上。

    工单 a/b 的「9 万／2 万字」按探针口径是进模型的材料量；生产路径
    ``render_segments_block`` 每段只放前 650 字，故测试用「段数×段长」
    控制**渲染后**提示词体量，使超窗／未超窗可复现。
    """
    d = Dossier(question="客户B的回款情况如何？")
    src = Source.create("料", SourceType.REPORT, id="SRC1")
    unit = "客户B回款率40%。材料填充字。"
    for i in range(n_segs):
        text = (unit * ((seg_chars // len(unit)) + 2))[:seg_chars]
        src.segments.append(Segment(
            id=f"SRC1#s{i + 1}", source_id="SRC1", text=text, index=i))
    d.add_source(src)
    return d


def test_overflow_large_prompt_writes_prompt_over_window(monkeypatch, tmp_path):
    """a) 渲染后提示词远超 16384 tok → report.json 有 prompt_over_window，数字对齐手工估算。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "16384")
    monkeypatch.setenv("VERITAS_ZH_CHARS_PER_TOKEN", "1.45")
    # 50×600≈3 万字进入提示词 → ≈2 万 tok＞16384
    d = _dossier_with_n_segments(50, 600)
    analyst = Analyst("m", "测", StubClient(), "mod")
    analyst.analyze(d)
    notes = [n for n in d.ingest_notes if n.get("kind") == "prompt_over_window"]
    assert len(notes) == 1
    note = notes[0]
    msgs = analyst.client.calls[0]["messages"]
    hand = estimate_prompt_window(
        msgs, window_tokens=16384, zh_chars_per_token=1.45)
    assert hand["overflow_tokens"] > 0
    assert note["est_tokens"] == hand["est_tokens"]
    assert note["window_tokens"] == 16384
    assert note["overflow_tokens"] == hand["overflow_tokens"]
    assert "从提示词头部静默剪掉" in note["detail"]
    assert "研判议题" in note["detail"]
    assert any(t["route"] == "prompt_over_window" for t in d.triage)
    out = tmp_path / "report.json"
    out.write_text(json.dumps(d.to_dict(), ensure_ascii=False), encoding="utf-8")
    saved = json.loads(out.read_text(encoding="utf-8"))
    kinds = [n.get("kind") for n in saved.get("ingest_notes") or []]
    assert "prompt_over_window" in kinds
    md = render_report_md(d, HashChain(), [])
    assert "模型窗口出口披露" in md
    assert "从提示词头部静默剪掉" in md


def test_under_window_no_false_disclosure(monkeypatch):
    """b) 渲染后未超窗 → 不得出 prompt_over_window（反向：只改文案不改条件要挂）。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "16384")
    monkeypatch.setenv("VERITAS_ZH_CHARS_PER_TOKEN", "1.45")
    # 8×600≈4800 字进入提示词 → 远低于 16384 tok
    d = _dossier_with_n_segments(8, 600)
    Analyst("m", "测", StubClient(), "mod").analyze(d)
    assert not any(n.get("kind") == "prompt_over_window" for n in d.ingest_notes)
    assert not any(t.get("route") == "prompt_over_window" for t in d.triage)
    md = render_report_md(d, HashChain(), [])
    assert "模型窗口出口披露" not in md
    assert "从提示词头部静默剪掉" not in md


def test_ctx_zero_unchecked_in_report(monkeypatch):
    """c) VERITAS_MODEL_CTX_TOKENS=0 → 不出超窗条，报告可见「未检查」。"""
    monkeypatch.setenv("VERITAS_MODEL_CTX_TOKENS", "0")
    d = _dossier_with_n_segments(50, 600)
    Analyst("m", "测", StubClient(), "mod").analyze(d)
    assert not any(n.get("kind") == "prompt_over_window" for n in d.ingest_notes)
    assert (d.accounting.get("prompt_window") or {}).get("status") == "unchecked"
    md = render_report_md(d, HashChain(), [])
    assert "未检查" in md
    assert "模型窗口出口披露" in md


def test_run_panel_analyze_does_not_reread_settings(monkeypatch):
    """f / R-C9-1：run_panel 三个分析师全程不再 Settings.from_env。"""
    calls = {"n": 0}
    real = Settings.from_env.__func__

    def _counting(cls):
        calls["n"] += 1
        return real(cls)

    monkeypatch.setattr(Settings, "from_env", classmethod(_counting))
    client = StubClient()
    analysts = build_panel(client, "mod")
    assert len(analysts) == 3
    calls["n"] = 0
    d = _dossier_with_n_segments(1, 80)
    out = run_panel(d, analysts)
    assert calls["n"] == 0
    assert set(out) >= {"mainstream", "redteam", "technologist"}
    assert len(client.calls) == 3


def test_bi_delivery_risk_default_overflow(monkeypatch):
    """e / R-C9-2：真案例渲染后默认窗口超发，est 与 19378 同量级（±5%）。

    只 load + 渲染 + 估算，不 chat、不写 cases/。
    """
    from app.agents.prompts import render_segments_block, render_system_prompt
    from app.core.material import set_material_budget
    from app.core.skills import render_skills_rules
    from app.ingest.case_loader import load_case

    monkeypatch.delenv("VERITAS_MODEL_CTX_TOKENS", raising=False)
    monkeypatch.delenv("VERITAS_ZH_CHARS_PER_TOKEN", raising=False)
    set_material_budget(80_000)
    case = Path(__file__).resolve().parents[1] / "cases" / "bi-delivery-risk"
    dossier = load_case(case)
    settings = Settings()
    messages = [
        {"role": "system", "content": render_system_prompt(
            MAINSTREAM_PERSONA,
            skills_rules=render_skills_rules(dossier, "standard"))},
        {"role": "user", "content": render_segments_block(dossier)},
    ]
    rec = estimate_prompt_window(
        messages,
        window_tokens=settings.model_context_tokens,
        zh_chars_per_token=settings.zh_chars_per_token,
    )
    assert rec["overflow_tokens"] > 0
    assert abs(rec["est_tokens"] - 19378) / 19378 <= 0.05


def test_default_env_no_overflow_note_on_small_case(monkeypatch):
    """d) 默认不设 env → 小案不出超窗条（回归：不空转假披露）。"""
    monkeypatch.delenv("VERITAS_MODEL_CTX_TOKENS", raising=False)
    monkeypatch.delenv("VERITAS_ZH_CHARS_PER_TOKEN", raising=False)
    d = _dossier_with_n_segments(1, 400)
    Analyst("m", "测", StubClient(), "mod").analyze(d)
    assert not any(n.get("kind") == "prompt_over_window" for n in d.ingest_notes)
    assert "prompt_window" not in (d.accounting or {})
