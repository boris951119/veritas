"""C-66／树16：续盒（多箱）——装箱并集＋定向补答＋accounting kept。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.base import Analyst
from app.agents.multi_box import run_multi_box_passes
from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.material import (
    multi_box_accounting,
    pack_continuation_boxes,
    pack_material,
)
from app.llm.model_client import ModelClient
from app.pipeline import RunDeps, RunSpec, _render_excluded_sources, run_case

_ROOT = Path(__file__).resolve().parents[1]

_RUN_CASE_JSON = """```json
{"conclusions": [
  {"statement": "固态电池能量密度占优",
   "evidence": [{"quote": "能量密度显著高于液态锂离子电池",
                 "segment_id": "SRC1#s1",
                 "relation": "correlation", "level": "A", "note": "直接引证"}]}
]}
```"""


def _fat_dossier(n_segs: int = 12, seg_chars: int = 40) -> Dossier:
    """同议题多段，预算压小后必多箱。"""
    d = Dossier(question="客户B的回款率是多少？")
    for i in range(1, n_segs + 1):
        sid = f"SRC{i}"
        text = (
            f"客户B回款率相关材料第{i}段。"
            + ("回款" * 4)
            + ("X" * max(0, seg_chars - 20))
        )
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.segments.append(Segment(
            id=f"{sid}#s1", source_id=sid, text=text, index=0))
        d.add_source(src)
    return d


def test_c66_defaults_multi_box_on():
    """Boyu 拍开：默认 True；刀＝翻 False ⇒ 本格红。"""
    s = Settings()
    assert s.multi_box is True
    assert s.multi_box_max == 3


def test_c66_env_off(monkeypatch):
    monkeypatch.setenv("VERITAS_MULTI_BOX", "0")
    assert Settings.from_env().multi_box is False


def test_c66_env_max(monkeypatch):
    monkeypatch.setenv("VERITAS_MULTI_BOX_MAX", "2")
    assert Settings.from_env().multi_box_max == 2


def test_c66_exclude_seg_ids_skips_prior():
    d = _fat_dossier(6, 30)
    first = pack_material(d, budget_chars=50)
    assert first["selected"]
    second = pack_material(
        d, budget_chars=50, exclude_seg_ids=first["selected"])
    assert not (second["selected"] & first["selected"])


def test_c66_pack_continuation_boxes_union_superset():
    d = _fat_dossier(10, 40)
    plan = pack_continuation_boxes(d, budget_chars=45, max_boxes=3)
    assert plan["n_boxes"] >= 2
    boxes = plan["boxes"]
    assert set(boxes[0]["selected"]) <= plan["union_selected"]
    seen: set[str] = set()
    for b in boxes:
        sel = set(b["selected"])
        assert not (sel & seen), "箱间不得重叠"
        seen |= sel
    assert seen == plan["union_selected"]


def test_c66_pack_continuation_respects_max_boxes():
    d = _fat_dossier(20, 40)
    plan = pack_continuation_boxes(d, budget_chars=40, max_boxes=2)
    assert plan["n_boxes"] <= 2
    assert plan["max_boxes"] == 2


def test_c66_accounting_shape():
    d = _fat_dossier(8, 40)
    plan = pack_continuation_boxes(d, budget_chars=45, max_boxes=3)
    acc = multi_box_accounting(plan)
    assert acc["enabled"] is True
    assert acc["n_boxes"] == plan["n_boxes"]
    assert acc["n_union"] == len(plan["union_selected"])
    assert sorted(acc["union_selected"]) == sorted(plan["union_selected"])
    assert len(acc["per_box"]) == plan["n_boxes"]


def test_c66_run_passes_focus_only_box2():
    d = _fat_dossier(10, 40)
    plan = pack_continuation_boxes(d, budget_chars=45, max_boxes=3)
    assert plan["n_boxes"] >= 2
    box2 = set(plan["boxes"][1]["selected"])

    class Stub:
        def chat(self, model, messages, **kwargs):
            user = messages[-1]["content"]
            # focus 块只含本箱
            for sid in box2:
                assert sid in user
            for b0 in plan["boxes"][0]["selected"]:
                assert b0 not in user or b0 in box2
            quote = d.segment(next(iter(box2))).text[:30]
            return SimpleNamespace(content=json.dumps({
                "conclusions": [{
                    "statement": "续盒补到回款要点",
                    "evidence": [{
                        "quote": quote,
                        "segment_id": next(iter(box2)),
                        "relation": "correlation",
                        "level": "B",
                        "note": "续盒",
                    }],
                }],
            }, ensure_ascii=False))

    a = Analyst("mainstream", "主流", Stub(), "m")
    out = run_multi_box_passes(
        d, [a], max_boxes=3, budget_chars=45)
    assert out["status"] in ("ok", "partial")
    assert out["n_boxes"] >= 2
    assert out["n_conclusions"] >= 1
    assert out["passes"]


def test_c66_run_skipped_single_box():
    d = _fat_dossier(2, 20)
    a = Analyst("mainstream", "主流", SimpleNamespace(
        chat=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("不应调用"))), "m")
    out = run_multi_box_passes(
        d, [a], max_boxes=3, budget_chars=10_000)
    assert out["status"] == "skipped"
    assert out["reason"] == "single_box"


def test_c66_render_section_when_multi_box():
    d = _fat_dossier(10, 40)
    plan = pack_continuation_boxes(d, budget_chars=45, max_boxes=3)
    d.accounting["multi_box"] = {
        **multi_box_accounting(plan),
        "status": "skipped",
    }
    lines: list[str] = []
    _render_excluded_sources(lines, d)
    text = "\n".join(lines)
    assert "## 续盒（多箱）" in text
    assert f"共 {plan['n_boxes']} 箱" in text
    assert "并集装入" in text


def test_c66_multi_box_survives_kept_via_run_case(tmp_path, monkeypatch):
    """桩 client 注入路径只写装箱账（跳过真调用）；kept 必须放行 multi_box。"""
    monkeypatch.setenv("VERITAS_MULTI_BOX", "1")
    case = tmp_path / "case"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "question: 客户B的回款率是多少？\n"
        "sources:\n",
        encoding="utf-8",
    )
    # 多文件短段 → 小预算下多箱（pack_to_window 关、预算钉死）
    man_lines = ["question: 客户B的回款率是多少？\n", "sources:\n"]
    for i in range(1, 9):
        name = f"s{i}.md"
        man_lines.append(f"  - file: {name}\n    type: report\n")
        # 每段 ~28 字；预算 50 ⇒ 首箱约 1 段、必出续盒
        (case / name).write_text(
            f"客户B回款率材料{i}，回款相关。\n",
            encoding="utf-8",
        )
    (case / "manifest.yaml").write_text("".join(man_lines), encoding="utf-8")
    out = tmp_path / "out"

    def completion(**kw):
        return {
            "choices": [{"message": {"content": _RUN_CASE_JSON},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 20},
        }

    settings = Settings(
        models=["test-model"],
        llm_max_retries=1,
        retry_backoff_base=0.0,
        multi_box=True,
        multi_box_max=3,
        pack_to_window=False,
        material_char_budget=50,
        second_pass_enabled=False,
        model_probe_enabled=False,
    )
    client = ModelClient(settings, completion_fn=completion)
    single = [Analyst("mainstream", "测试角色", client, "test-model")]
    run_case(
        RunSpec(case_dir=case, out_dir=out, settings=settings),
        RunDeps(client=client, analysts=single),
    )
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    mb = (report.get("accounting") or {}).get("multi_box")
    assert isinstance(mb, dict), report.get("accounting")
    assert mb.get("enabled") is True
    assert int(mb.get("n_boxes") or 0) >= 2, mb
    assert int(mb.get("n_union") or 0) >= int(mb["n_boxes"])
