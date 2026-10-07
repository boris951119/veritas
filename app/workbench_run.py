"""工作台「开始研判」：有密钥走真模型，否则秒级桩演示。"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.ingest.case_loader import load_case
from app.llm.yaml_robust import load_yaml_robust
from app.pipeline import RunDeps, RunSpec, run_case
from app.workbench_llm import (
    apply_to_environ,
    is_live_mode,
    llm_status,
    workbench_roster,
)


def case_question(case_dir: Path) -> str:
    man = case_dir / "manifest.yaml"
    if not man.is_file():
        return case_dir.name
    data = load_yaml_robust(man) or {}
    return str(data.get("question") or case_dir.name)


def _client_for(name: str, dossier):
    from scripts.demo_offline import (
        BatteryStubClient,
        DeliveryRiskStubClient,
        OfflineStubClient,
        RumorVsOfficialStubClient,
    )

    mapping = {
        "demo-solid-state": BatteryStubClient,
        "bi-delivery-risk": DeliveryRiskStubClient,
        "rumor-vs-official": RumorVsOfficialStubClient,
    }
    cls = mapping.get(name)
    if cls is not None:
        return cls(dossier)

    class GenericStubClient(OfflineStubClient):  # type: ignore[misc]
        TOPIC = "议题判断"
        CONFLICT_DESC = "材料口径不一致"
        PESSIM_RE = r"不足|风险|不确定|停工"
        PROG_RE = r"可行|属实|明确|运转"
        POLARITY: dict = {}

        def _panel_payloads(self):
            import json
            if not self.dossier.sources:
                payload = json.dumps({"conclusions": [{
                    "statement": self.dossier.question
                    or "入卷资料中没有可抽取的文本",
                    "evidence": [],
                }]}, ensure_ascii=False)
                return payload, {"红队": payload, "怀疑": payload, "技术推进": payload}
            src = self.dossier.sources[0]
            seg = src.segments[0]
            q = seg.text.strip().replace("\n", " ")[:110]
            payload = json.dumps({"conclusions": [{
                "statement": self.dossier.question or "已阅读全部入卷资料",
                "evidence": [{"quote": q, "segment_id": seg.id,
                              "relation": "correlation", "level": "B",
                              "note": "入卷摘录"}],
            }]}, ensure_ascii=False)
            return payload, {"红队": payload, "怀疑": payload, "技术推进": payload}

    return GenericStubClient(dossier)


def archive_run(case_dir: Path, out_dir: Path) -> Path:
    """把本次产物另存一份，供历史记录浏览（不覆盖 out_offline 当前位）。"""
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    dest = case_dir / "history" / stamp
    n = 2
    while dest.exists():
        dest = case_dir / "history" / f"{stamp}_{n}"
        n += 1
    dest.mkdir(parents=True, exist_ok=False)
    for name in ("report.json", "chain.jsonl", "report.md", "progress.json"):
        src = out_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    return dest


def run_workbench_case(case_dir: Path, question: str | None = None) -> Path:
    """写入 out_offline 并归档。有 key 且未强制演示 → 真模型；否则桩。"""
    apply_to_environ()
    dossier = load_case(case_dir)
    if question and str(question).strip():
        dossier.question = str(question).strip()
    out = case_dir / "out_offline"
    live = is_live_mode()
    if live:
        settings = Settings.from_env()
        status = llm_status()
        models = list(status.get("models") or [])
        if models:
            settings.models = models
        run_case(
            RunSpec(case_dir=case_dir, out_dir=out, dossier=dossier,
                    settings=settings, roster=workbench_roster()),
            RunDeps(),  # client=None → 工厂建真实 ModelClient
        )
    else:
        run_case(
            RunSpec(case_dir=case_dir, out_dir=out, dossier=dossier),
            RunDeps(client=_client_for(case_dir.name, dossier)),
        )
    archive_run(case_dir, out)
    return out
