"""MCP 协议级测试：stdio 起真服务进程 + ClientSession 全握手，
调用零 LLM 工具（list_cases / get_report / verify_chain）。
run_* 工具的实现逻辑由直接函数调用覆盖（桩客户端，不起网关）。"""

import sys
from pathlib import Path

import pytest

from app.mcp_server import build_dossier_from_sources, _judgment_summary
from app.agents.base import Analyst
from app.core.hashchain import HashChain

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def test_stdio_protocol_list_and_read(tmp_path):
    pytest.importorskip("mcp")          # 现场包默认不装 mcp：跳过而非失败
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_server"],
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {"list_cases", "get_report", "verify_chain",
                    "run_analyst", "run_judgment"} <= names

            cases = await session.call_tool("list_cases", {})
            text = cases.content[0].text
            assert "demo-solid-state" in text

            report = await session.call_tool("get_report",
                                             {"case": "demo-solid-state"})
            assert "conclusions" in report.content[0].text

            verified = await session.call_tool("verify_chain",
                                               {"case": "demo-solid-state"})
            assert '"ok"' in verified.content[0].text

            missing = await session.call_tool("get_report", {"case": "nope"})
            assert "error" in missing.content[0].text   # 结构化错误，不炸服务


def test_build_dossier_and_judgment_summary_with_stubs(tmp_path):
    sources = [
        {"title": "研究A", "text": "量产良率尚不足四成，是当前最大瓶颈。",
         "type": "paper", "credibility": 0.85},
        {"title": "新闻B", "text": "中试线正式点亮，2027 年装车路测。",
         "type": "news"},
    ]
    dossier = build_dossier_from_sources("测试议题？", sources)
    assert len(dossier.sources) == 2
    assert dossier.sources[0].credibility == 0.85
    assert dossier.sources[1].credibility == \
        __import__("app.core.evidence", fromlist=["SOURCE_CREDIBILITY_PRIOR"]) \
        .SOURCE_CREDIBILITY_PRIOR[dossier.sources[1].source_type]
    assert dossier.segment("SRC1#s1") is not None

    # 桩分析师跑一遍单分析师管线逻辑
    from types import SimpleNamespace

    class FakeClient:
        def chat(self, model, messages, json_mode=False):
            return SimpleNamespace(content='{"conclusions": ['
                '{"statement": "良率是主要瓶颈", "evidence": ['
                '{"quote": "量产良率尚不足四成", "segment_id": "SRC1#s1",'
                '"relation": "correlation", "level": "A", "note": "n"}]}]}')

    from app.agents.panel import build_panel, run_panel
    from app.core.citation_check import audit_dossier
    from app.core.confidence import recompute_all

    panel = build_panel(FakeClient(), "test-model",
                        roster=[("solo", "测试角色")])
    run_panel(dossier, panel)
    audit_dossier(dossier)
    recompute_all(dossier, n_panel=1)
    chain = HashChain()
    chain.append("case_loaded", "test", {})
    summary = _judgment_summary(dossier, 1)
    summary["n_chain_records"] = len(chain.records)
    summary["chain_ok"] = chain.verify_chain().ok
    assert summary["conclusions"][0]["confidence"] > 0
    assert summary["conclusions"][0]["evidence"][0]["quote"] == "量产良率尚不足四成"
    assert summary["chain_ok"] is True
