#!/usr/bin/env python3
"""C-47 件③：用配置化 roster 真加「反方质检员」，桩客户端零模型跑通一题。

入口＝app.agents.panel.load_roster(config/roster-devil-advocate.yaml)
     ＋ app.pipeline.run_case（不改 pipeline／core）。
产出＝out_dir/report.md 的「研判编队」行含 devil-advocate；
     另落 record.json（改动清单／耗时／n_calls／是否≤1人日）。

工作台默认入口未挂此编队（workbench_roster 只转 DEFAULT_ROSTER）——
该项如实记未达，不改 workbench 代码。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

GOOD_JSON = """```json
{"conclusions": [
  {"statement": "反方质检：主结论缺少对照证据，须降级为相关",
   "evidence": [{"quote": "能量密度显著高于液态锂离子电池",
                 "segment_id": "SRC1#s1",
                 "relation": "correlation", "level": "B",
                 "note": "反方质检：无对照试验，不作因果"}]}
]}
```"""


class FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls: list = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "messages": messages,
                           "json_mode": json_mode})
        return SimpleNamespace(content=self.content)


def _make_mini_case(case_dir: Path) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "manifest.yaml").write_text(
        "question: 固态电池 2030 能否规模上车？（C-47 反方质检员实测）\n"
        "sources:\n  - file: a.md\n    type: paper\n",
        encoding="utf-8",
    )
    (case_dir / "a.md").write_text(
        "# 摘要\n\n本次测评显示固态电池的能量密度显著高于液态锂离子电池，"
        "但成本仍高于预期。\n",
        encoding="utf-8",
    )


def main() -> int:
    import sys
    sys.path.insert(0, str(ROOT))
    from app.agents.base import Analyst
    from app.agents.panel import build_panel, load_roster
    from app.pipeline import RunDeps, RunSpec, run_case

    t0 = time.perf_counter()
    roster_path = ROOT / "config" / "roster-devil-advocate.yaml"
    roster = load_roster(roster_path)
    assert any(n == "devil-advocate" for n, _, _ in roster), roster

    out_root = Path("/tmp/c47_agent_demo")
    case_dir = out_root / "case"
    out_dir = out_root / "out"
    _make_mini_case(case_dir)

    fake = FakeClient(GOOD_JSON)
    analysts = build_panel(fake, "stub-model", roster=roster)
    # 全员同一桩回复＝只验证编队名进入报告，不测角色差异化产出
    result = run_case(
        RunSpec(case_dir=case_dir, out_dir=out_dir),
        RunDeps(client=fake, analysts=analysts),
    )
    elapsed_s = time.perf_counter() - t0
    md = result.report_md or (out_dir / "report.md").read_text(encoding="utf-8")
    panel_line = next((ln for ln in md.splitlines() if "研判编队" in ln), "")
    in_report = "devil-advocate" in panel_line
    n_calls = len(fake.calls)  # 桩调用次数；真模型＝0

    # 机械质检旁路（零 chat）：对同一案卷出质疑条目，作对照记录
    from app.agents.devil_advocate import critique_dossier
    mech_items = critique_dossier(result.dossier, question_id="c47-demo")

    # ≤1 人日：按官方口径＝本实测墙钟（配置＋脚本＋跑通）换算；
    # 配置路加角色本身 <1 小时；工作台默认未挂＝报告项达标、工作台项未达。
    person_day_ok_report = in_report and elapsed_s < 8 * 3600
    person_day_ok_workbench = False  # 默认入口未改

    record = {
        "agent": "devil-advocate（反方质检员）",
        "roster_path": str(roster_path.relative_to(ROOT)),
        "roster_names": [n for n, _, _ in roster],
        "change_list": [
            "config/roster-devil-advocate.yaml:1-（新文件，load_roster 配置路）",
            "scripts/demo_c47_agent.py:1-（新文件，桩跑通＋记时）",
            "app/agents/devil_advocate.py:1-（机械质检旁路，零 LLM；非编队主路径）",
            "app/agents/registry.py:agent_inventory(roster=…) 真绑 load_roster 结果（不改 _FIXED_AGENTS）",
        ],
        "question": result.dossier.question,
        "out_dir": str(out_dir),
        "report_md": str(out_dir / "report.md"),
        "panel_line": panel_line,
        "in_report": in_report,
        "in_workbench_default": False,
        "n_calls_real_model": 0,
        "n_calls_stub": n_calls,
        "n_mech_items": len(mech_items),
        "elapsed_s": round(elapsed_s, 3),
        "leq_1_person_day_report": person_day_ok_report,
        "leq_1_person_day_workbench": person_day_ok_workbench,
        "verdict": (
            "报告侧：配置路加角色＋桩跑通，产出出现在 report.md 编队行"
            " ⇒ 按官方 ≤1 人日口径＝达标（本实测耗时见 elapsed_s）。"
            "工作台默认入口未挂此编队（须改 workbench_llm.workbench_roster"
            " 或 UI，本单不改核心）⇒ 工作台项＝未达。"
        ),
    }
    from app.agents.registry import inventory_markdown
    inv_md = inventory_markdown(roster=roster)
    if "devil-advocate" not in inv_md:
        raise SystemExit("展示清单未绑到 roster")
    (out_root / "inventory.md").write_text(inv_md, encoding="utf-8")

    rec_path = out_root / "record.json"
    rec_path.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    # 仓库内可复跑摘要（不含 out* 大产物）
    deliver = ROOT / "docs" / "deliverables" / "智能体实测-C47.md"
    deliver.write_text(
        "# 新增智能体实测（C-47 件③）\n\n"
        f"- 角色：`{record['agent']}`\n"
        f"- 落点：`{record['roster_path']}`（`load_roster`，零改 pipeline／core）\n"
        f"- 改动清单：\n"
        + "".join(f"  - {x}\n" for x in record["change_list"])
        + f"- 议题：{record['question']}\n"
        f"- 编队行：{record['panel_line']}\n"
        f"- 出现在报告：{record['in_report']}\n"
        f"- 出现在工作台默认入口：{record['in_workbench_default']}（未达）\n"
        f"- 真模型调用：{record['n_calls_real_model']}；桩 chat 次数：{record['n_calls_stub']}\n"
        f"- 耗时：{record['elapsed_s']} s（Asia/Shanghai 本机墙钟，非断言）\n"
        f"- ≤1 人日（报告侧）：{record['leq_1_person_day_report']}\n"
        f"- ≤1 人日（工作台侧）：{record['leq_1_person_day_workbench']}＝**未达**\n"
        f"- 复跑：`PYTHONPATH=. .venv/bin/python scripts/demo_c47_agent.py`\n"
        f"- 完整 record：`/tmp/c47_agent_demo/record.json`\n\n"
        f"**结论**：{record['verdict']}\n",
        encoding="utf-8",
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"record => {rec_path}")
    print(f"deliverable note => {deliver}")
    return 0 if in_report else 1


if __name__ == "__main__":
    raise SystemExit(main())
