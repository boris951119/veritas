"""端到端研判管线（veritas）。

案例目录 → 摄取切段 → 分析师独立研判 → 零 LLM 引文核对（不合格打回，
全程哈希链留痕）→ 置信度量化 → 报告（JSON + Markdown 双出口）+
研判日志 chain.jsonl。

第 1 周为单分析师最小闭环；第 2 周在此接入多分析师并行独立研判、
冲突检测/辩论/仲裁与完整置信度融合。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.base import Analyst
from app.config import Settings
from app.core.citation_check import audit_dossier
from app.core.confidence import conclude_confidence
from app.core.evidence import Dossier
from app.core.hashchain import HashChain
from app.ingest.case_loader import load_case
from app.llm.budget import BudgetGuard, set_active_budget_guard
from app.llm.model_client import ModelClient, ModelClientFactory


def touch_progress() -> None:
    """进展心跳钩子（model_client 每次成功响应后调用；当前 no-op，
    预留给工作台的看门狗与 SSE 流）。"""
    return None


DEFAULT_PERSONA = ("严谨的主流评估派分析师：以同行评审证据为主要依据，"
                   "按主流学术共识的口径评估技术成熟度与可行性")


@dataclass
class PipelineResult:
    dossier: Dossier
    chain: HashChain
    rejected: list[dict] = field(default_factory=list)
    out_dir: Path | None = None

    @property
    def report_md(self) -> str:
        return render_report_md(self.dossier, self.chain, self.rejected)


def run_case(
    case_dir: Path,
    out_dir: Path | None = None,
    client: ModelClient | None = None,
    settings: Settings | None = None,
    analysts: list[Analyst] | None = None,
) -> PipelineResult:
    """跑一次完整研判。client/analysts 可注入桩（测试零 key 全绿）。"""
    settings = settings or Settings.from_env()
    dossier = load_case(Path(case_dir))
    chain = HashChain()
    chain.append("case_loaded", "pipeline", {
        "question": dossier.question,
        "n_sources": len(dossier.sources),
        "n_segments": sum(len(s.segments) for s in dossier.sources),
    })

    guard = BudgetGuard(settings.budget_tokens, settings.budget_throttle_threshold)
    set_active_budget_guard(guard)

    if client is None:
        client = ModelClientFactory(settings).create()
    if analysts is None:
        analysts = [Analyst("mainstream", DEFAULT_PERSONA, client, settings.models[0])]

    for analyst in analysts:
        conclusions = analyst.analyze(dossier)
        chain.append("analyst_done", analyst.name, {
            "n_conclusions": len(conclusions),
            "model": analyst.model,
        })

    # 引文机械核对：不合格证据打回（保留痕迹，不静默丢弃）
    failures = audit_dossier(dossier)
    rejected: list[dict] = []
    for f in failures:
        ev = dossier.evidence(f.evidence_id)
        rejected.append({
            "evidence_id": f.evidence_id,
            "conclusion_id": f.conclusion_id,
            "quote": ev.quote if ev else "",
            "problems": f.problems,
        })
        dossier.remove_evidence(f.evidence_id)
    chain.append("citation_audit", "pipeline", {
        "n_total": len(failures) + sum(1 for e in dossier.evidences if e.verified),
        "n_rejected": len(rejected),
    })

    # 置信度回填
    for con in dossier.conclusions:
        con.confidence, con.confidence_parts = conclude_confidence(con.id, dossier)
    chain.append("confidence_computed", "pipeline", {
        "n_conclusions": len(dossier.conclusions),
    })
    chain.append("report_finalized", "pipeline", {"question": dossier.question})

    result = PipelineResult(dossier=dossier, chain=chain, rejected=rejected)

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        dossier.to_json(out_dir / "report.json")
        (out_dir / "report.md").write_text(result.report_md, encoding="utf-8")
        chain.to_jsonl(out_dir / "chain.jsonl")
        result.out_dir = out_dir
    return result


# ----------------------------------------------------------------------


def render_report_md(dossier: Dossier, chain: HashChain, rejected: list[dict]) -> str:
    """研判报告 Markdown 渲染（工作台之前的纸质出口）。"""
    verify = chain.verify_chain()
    lines: list[str] = [
        f"# 研判报告：{dossier.title or dossier.question}",
        "",
        f"**议题**：{dossier.question}",
        "",
        f"**资料**：{len(dossier.sources)} 份信源 / "
        f"{sum(len(s.segments) for s in dossier.sources)} 个段落",
        "",
        "## 结论",
        "",
    ]
    if not dossier.conclusions:
        lines.append("（无结论——检查资料覆盖或分析师输出）")
    for con in dossier.conclusions:
        lines.append(f"### {con.statement}")
        lines.append("")
        lines.append(f"- 置信度：**{con.confidence:.2f}**（{con.confidence_parts}）")
        lines.append(f"- 研判方：{con.author or 'N/A'}")
        evs = dossier.evidences_of(con.id)
        if evs:
            lines.append("")
            lines.append("| 逐字引文 | 出处 | 等级 | 关系 | 说明 |")
            lines.append("|---|---|---|---|---|")
            for ev in evs:
                seg = dossier.segment(ev.segment_ids[0]) if ev.segment_ids else None
                where = f"{ev.segment_ids[0]}" + (f"（{seg.locator}）" if seg else "")
                quote = ev.quote.replace("|", "\\|").replace("\n", " ")
                note = ev.note.replace("|", "\\|")
                lines.append(f"| {quote} | {where} | {ev.level.value} | {ev.relation.value} | {note} |")
        lines.append("")

    if rejected:
        lines += ["## 被打回的证据（引文核对未通过）", ""]
        for r in rejected:
            lines.append(f"- `{r['evidence_id']}`：{'; '.join(r['problems'])}"
                         f"（引文：{r['quote'][:60]}…）")
        lines.append("")

    lines += [
        "## 防篡改校验",
        "",
        f"- 研判日志 {len(chain.records)} 条，哈希链校验："
        f"{'✅ 通过' if verify else f'❌ 失败（#{verify.bad_index}: {verify.reason}）'}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="veritas 研判管线")
    parser.add_argument("case_dir", help="案例目录（含 manifest.yaml 与资料文件）")
    parser.add_argument("--out", default=None, help="报告输出目录（默认 cases/<case>/out）")
    parser.add_argument("--model", default=None, help="覆盖主分析模型")
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.model:
        settings.models = [args.model, *settings.models]

    result = run_case(Path(args.case_dir), Path(args.out or (Path(args.case_dir) / "out")))
    print(result.report_md)
    print(f"报告与日志已写入 {result.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
