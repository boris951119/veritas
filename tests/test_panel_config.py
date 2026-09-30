"""契约 B1：可配置分析师编队 load_roster + 自定义 roster 进入 panel。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.pipeline import run_case
from app.pipeline import RunDeps, RunSpec

PANEL_JSON = """{"conclusions": [
  {"statement": "良率是瓶颈",
   "evidence": [{"quote": "全固态电芯的中试良率尚不足百分之四十",
                 "segment_id": "SRC1#s1", "relation": "correlation",
                 "level": "B", "note": "良率"}]}
]}"""


class FakeClient:
    def chat(self, model, messages, json_mode=False):
        return SimpleNamespace(content=PANEL_JSON)


def _case(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "question: 固态电池 2030 能否规模上车？\n"
        "sources:\n  - file: a.md\n    type: paper\n", encoding="utf-8")
    (tmp_path / "a.md").write_text(
        "# 摘要\n\n全固态电芯的中试良率尚不足百分之四十。\n", encoding="utf-8")


def test_load_roster_accepts_two_roles():
    """深化后：合法 ≥2 人 roster dict 解析为 (name, persona) 列表。"""
    from app.agents.panel import load_roster

    roster = load_roster({
        "roster": [
            {"name": "hawk", "persona": "鹰派"},
            {"name": "dove", "persona": "鸽派"},
        ],
    })
    assert roster == [("hawk", "鹰派", None), ("dove", "鸽派", None)]


def test_load_roster_rejects_fewer_than_two():
    """深化后：少于 2 个角色时抛 ValueError。"""
    from app.agents.panel import load_roster

    with pytest.raises(ValueError):
        load_roster({"roster": [{"name": "solo", "persona": "独自"}]})


def test_custom_roster_enters_dossier_panel(tmp_path):
    """深化后：自定义 2 人编队写入 dossier.panel，不被默认三人覆盖。"""
    from app.agents.panel import build_panel, load_roster

    _case(tmp_path)
    roster = load_roster({
        "roster": [
            {"name": "hawk", "persona": "鹰派"},
            {"name": "dove", "persona": "鸽派"},
        ],
    })
    client = FakeClient()
    analysts = build_panel(client, "m", roster=roster)
    assert [a.name for a in analysts] == ["hawk", "dove"]
    result = run_case(RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out"),
                      RunDeps(client=client, analysts=analysts))
    assert result.dossier.panel == ["hawk", "dove"]


def test_run_case_roster_param_and_yaml_path(tmp_path):
    """roster= 直通 run_case（CLI --roster 的路径）：YAML 文件 → 编队入卷。"""
    from app.agents.panel import load_roster

    _case(tmp_path)
    roster_yaml = tmp_path / "roster.yaml"
    roster_yaml.write_text(
        "roster:\n  - name: bull\n    persona: 乐观派\n"
        "  - name: bear\n    persona: 悲观派\n", encoding="utf-8")
    result = run_case(RunSpec(case_dir=tmp_path, out_dir=tmp_path / "out2",
                      roster=load_roster(roster_yaml)),
                      RunDeps(client=FakeClient()))
    assert result.dossier.panel == ["bull", "bear"]
    assert result.chain.verify_chain().ok


def test_roster_per_agent_model():
    """per-agent model：roster 声明模型的 analysts 用自己的模型，
    省略者用默认——多模型异构是配置项。"""
    from app.agents.panel import build_panel, load_roster

    roster = load_roster({"roster": [
        {"name": "hawk", "persona": "鹰派", "model": "openai/big-model"},
        {"name": "dove", "persona": "鸽派"},
    ]})
    client = FakeClient()
    analysts = build_panel(client, "openai/default", roster=roster)
    assert analysts[0].model == "openai/big-model"
    assert analysts[1].model == "openai/default"
