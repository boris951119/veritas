"""MCP 标准接口（榜单加分项 3：通过标准接口接入第三方智能体）。

把 veritas 的研判能力暴露为 MCP（Model Context Protocol）工具，任何
MCP 客户端（Claude/其他智能体）都能直接调用：
- 零 LLM 工具：list_cases / get_report / verify_chain（读产物、验哈希链）
- 研判工具：run_analyst（单个分析师视角研判）、run_judgment（多智能体
  全流程：独立研判→引文核对→归并→冲突→仲裁→置信度）

LLM 工具需要 .env 网关配置；无 key 时调用返回明确错误（不炸服务）。
启动：pip install mcp（1.x/2.x 均可）&& python -m app.mcp_server（stdio）。
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.core.evidence import (
    Dossier,
    Source,
    SourceType,
    SOURCE_CREDIBILITY_PRIOR,
)
from app.ingest.segment import split_segments

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _cases_root() -> Path:
    return _REPO_ROOT / "cases"


def _out_dir_of(case: str) -> Path:
    base = _cases_root() / case
    for sub in ("out", "out_offline"):
        if (base / sub / "report.json").is_file():
            return base / sub
    raise KeyError(f"案例 {case} 无研判产物")


def build_dossier_from_sources(question: str, sources: list[dict]) -> Dossier:
    """外部传入的信源列表 → Dossier（MCP 工具与测试共用）。

    sources 项：{"title": str, "text": str, "type"?: paper|patent|report|
    news|note|web, "credibility"?: 0-1}。type 缺省按 note（低可信保守）。
    """
    dossier = Dossier(question=question, title=question)
    for i, item in enumerate(sources):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            stype = SourceType(str(item.get("type") or "note"))
        except ValueError:
            stype = SourceType.NOTE
        cred = item.get("credibility")
        src = Source.create(
            title=str(item.get("title") or f"信源{i + 1}"),
            source_type=stype,
            credibility=float(cred) if cred is not None else None,
            id=f"SRC{i + 1}",
        )
        for j, seg_text in enumerate(split_segments(text)):
            from app.core.evidence import Segment

            src.segments.append(Segment(
                id=f"SRC{i + 1}#s{j + 1}", source_id=src.id,
                text=seg_text, locator=f"段 {j + 1}", index=j))
        dossier.add_source(src)
    return dossier


def _judgment_summary(dossier: Dossier, n_panel: int) -> dict:
    """研判结果压缩为 MCP 友好的摘要（含证据链与防篡改状态）。"""
    conclusions = []
    for con in dossier.conclusions:
        if con.status == "merged":
            continue
        conclusions.append({
            "statement": con.statement,
            "confidence": con.confidence,
            "confidence_parts": con.confidence_parts,
            "authors": con.author_names(),
            "status": con.status,
            "dissent_records": con.dissent,
            "evidence": [{
                "quote": ev.quote,
                "segment_id": ev.segment_ids[0] if ev.segment_ids else "",
                "level": ev.level.value,
                "relation": ev.relation.value,
                "note": ev.note,
            } for ev in dossier.evidences_of(con.id)],
        })
    return {
        "question": dossier.question,
        "n_sources": len(dossier.sources),
        "panel": dossier.panel,
        "conclusions": conclusions,
        "conflicts": dossier.conflicts,
        "rejected_evidence": dossier.rejected,
        "n_chain_records": None,  # 由调用方（run 工具）回填
    }


def _make_server():
    try:
        try:
            from mcp.server.fastmcp import FastMCP  # mcp 1.x
        except ImportError:  # mcp 2.x 起 FastMCP 改名 MCPServer
            from mcp.server.mcpserver import MCPServer as FastMCP
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "MCP 接口需要官方 SDK：pip install mcp"
        ) from exc

    mcp = FastMCP(
        "veritas",
        instructions=(
            "veritas 多智能体可信研判与证据链溯源。"
            "零 LLM 工具可随时调用；run_* 工具发起真实研判（需已配置模型网关）。"
        ),
    )

    @mcp.tool()
    def list_cases() -> dict:
        """列出已有研判产物案例（零 LLM）。"""
        cases = []
        for d in sorted(_cases_root().iterdir()):
            if not d.is_dir():
                continue
            for sub in ("out", "out_offline"):
                if (d / sub / "report.json").is_file():
                    cases.append({"name": d.name, "out_dir": sub})
                    break
        return {"cases": cases}

    @mcp.tool()
    def get_report(case: str, clearance: str = "confidential") -> dict:
        """读取某案例的完整研判产物（dossier：信源/证据/结论/冲突/打回），
        并附零 LLM 机械核对审计。clearance ∈ public/internal/confidential
        ——低权限视图自动隐藏无权信源及其证据/结论（涉密处留红章占位）。"""
        try:
            dossier = Dossier.from_json(_out_dir_of(case) / "report.json")
        except KeyError:
            return {"error": f"案例 {case} 无研判产物"}
        from app.core.audit import audit_all, summarize
        from app.core.view_filter import redact_dossier

        view, _stats = redact_dossier(dossier, clearance)
        flags = audit_all(view)
        return {**view.to_dict(), "audit": {"flags": flags,
                                            **summarize(flags)}}

    @mcp.tool()
    def verify_chain(case: str) -> dict:
        """校验某案例研判日志的哈希链完整性（防篡改，零 LLM）。"""
        from app.core.hashchain import HashChain

        try:
            chain_path = _out_dir_of(case) / "chain.jsonl"
        except KeyError:
            return {"ok": False, "reason": f"案例 {case} 无研判产物"}
        chain = (HashChain.from_jsonl(chain_path)
                 if chain_path.is_file() else HashChain())
        result = chain.verify_chain()
        return {"ok": result.ok, "bad_index": result.bad_index,
                "reason": result.reason, "n_records": len(chain.records)}

    def _run_pipeline(question: str, sources: list[dict],
                      roster: list[tuple[str, str]] | None) -> dict:
        """外部信源 → 复用主管线 run_case（审计/出清/归并/冲突/仲裁/置信度
        与 CLI 完全同一条代码路径——曾因手抄副本漂移过：MCP 侧零证据结论
        不出清、打回记录丢引文、分析师失败不入链）。"""
        from app.llm.model_client import ModelClientFactory
        from app.pipeline import run_case

        settings = Settings.from_env()
        client = ModelClientFactory(settings).create()
        dossier = build_dossier_from_sources(question, sources)
        result = run_case(None, out_dir=None, client=client, settings=settings,
                          dossier=dossier, roster=roster)
        summary = _judgment_summary(result.dossier, len(result.dossier.panel))
        summary["n_chain_records"] = len(result.chain.records)
        summary["chain_ok"] = result.chain.verify_chain().ok
        return summary

    @mcp.tool()
    def ingest_external(question: str, sources: list[dict],
                        agent: str, conclusions: list[dict]) -> dict:
        """把第三方智能体的结论+证据入卷并做引文机械核对（零 LLM）。

        sources: [{"title","text","type"?,"credibility"?}]
        conclusions: [{"statement","evidence":[{"quote","segment_id",...}]}]
        返回入卷后的摘要（含 rejected）。
        """
        from app.agents.ingress import ingest_external_judgment
        from app.core.confidence import recompute_all

        dossier = build_dossier_from_sources(question, sources)
        ids = ingest_external_judgment(dossier, {
            "agent": agent, "conclusions": conclusions,
        })
        recompute_all(dossier, n_panel=1)
        summary = _judgment_summary(dossier, 1)
        summary["ingested_ids"] = ids
        return summary

    @mcp.tool()
    def run_analyst(question: str, sources: list[dict],
                    persona: str = "严谨的主流评估派分析师：以同行评审证据为主要依据给出独立研判") -> dict:
        """以指定角色视角做一次独立研判（单分析师；需模型网关）。

        sources: [{"title","text","type"?,"credibility"?}]，text 为信源全文。
        返回该角色的结论+逐字引文证据链（引文已经机械核对）。
        """
        return _run_pipeline(question, sources,
                             roster=[("analyst1", persona)])

    @mcp.tool()
    def run_judgment(question: str, sources: list[dict]) -> dict:
        """多智能体全流程研判（需模型网关）。

        sources: [{"title","text","type"?,"credibility"?}]。
        流程：3 视角独立研判（互不可见）→ 逐字引文机械核对 → 同义归并
        → 冲突检测 → 质证 → 仲裁（保留少数意见）→ 置信度。
        """
        return _run_pipeline(question, sources, roster=None)

    return mcp


def main() -> int:
    mcp = _make_server()
    mcp.run()  # stdio
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
