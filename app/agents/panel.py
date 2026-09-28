"""分析师编队：≥2 个不同视角智能体并行独立研判（榜单硬需求 1）。

硬隔离由提示词构造保证：每个分析师只拿到「议题 + 资料清单 + 自己的
角色」，拿不到其他分析师的任何输出；编队执行用线程池（LLM 调用是
IO 密集），单个分析师失败只降级不炸全局（chain 留痕）。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from app.agents.base import Analyst
from app.core.evidence import Conclusion, Dossier
from app.llm.model_client import ModelClient

MAINSTREAM_PERSONA = ("严谨的主流评估派分析师：以同行评审证据为主要依据，"
                      "按主流学术共识的口径评估技术成熟度与可行性")
REDTEAM_PERSONA = ("红队怀疑派分析师：以证伪为默认立场，主动寻找反例、"
                   "证据缺口与过度承诺，对乐观叙事保持职业性怀疑")
TECHNOL_PERSONA = ("技术推进派分析师：关注技术路径、工程进展与产线现实；"
                   "当证据支持工程突破（中试进展、良率提升、设备到位）时，"
                   "应给出建设性的乐观判断并给出明确时间表预期")

DEFAULT_ROSTER: list[tuple[str, str]] = [
    ("mainstream", MAINSTREAM_PERSONA),
    ("redteam", REDTEAM_PERSONA),
    ("technologist", TECHNOL_PERSONA),
]


def build_panel(client: ModelClient, model: str,
                roster: list[tuple[str, str]] | None = None) -> list[Analyst]:
    """按编队名册构建分析师（默认三视角；测试可注入桩 client）。"""
    return [Analyst(name, persona, client, model)
            for name, persona in (roster or DEFAULT_ROSTER)]


def run_panel(dossier: Dossier, analysts: list[Analyst],
              on_done=None) -> dict[str, list[Conclusion]]:
    """并行独立研判：返回 {分析师名: 结论列表}。

    - 结论与证据在 Analyst 内部已物化进 dossier；
    - 单个分析师异常 → 记录失败、继续其余（隔离失败面）；
    - on_done(name, conclusions) 供管线逐个写 chain 留痕。
    """
    results: dict[str, list[Conclusion]] = {}
    failures: dict[str, str] = {}
    dossier.panel = [a.name for a in analysts]  # 编队名单入卷
    with ThreadPoolExecutor(max_workers=max(1, len(analysts))) as pool:
        futures = {pool.submit(a.analyze, dossier): a for a in analysts}
        for fut in as_completed(futures):
            analyst = futures[fut]
            try:
                results[analyst.name] = fut.result()
                if on_done:
                    on_done(analyst.name, results[analyst.name])
            except Exception as exc:  # 单点失败不炸编队
                failures[analyst.name] = f"{type(exc).__name__}: {exc}"
    results["_failures"] = failures  # 管线读取后转 chain 事件
    return results
