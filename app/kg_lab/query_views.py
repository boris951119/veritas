"""R19：问句多视图改写——结论／原因／证据。默认规则；可选本地 14B。"""

from __future__ import annotations

from typing import Any

from app.kg_lab.event_frame import EventFrame, extract_event_frame, option_paraphrases


def rule_query_views(question: str, frame: EventFrame | None = None) -> list[dict[str, str]]:
    q = (question or "").strip()
    frame = frame or extract_event_frame(q)
    actors = " ".join(frame.actors[:3])
    opts = frame.options
    times = " ".join(frame.time_cues[:3])
    quals = " ".join(frame.qual_predicates[:4])
    terms = " ".join(frame.question_terms[:6])
    views: list[dict[str, str]] = [
        {"id": "raw", "view": "raw", "query": q},
    ]
    if opts:
        views.append({
            "id": "conclusion_or",
            "view": "conclusion",
            "query": f"{actors} {' 还是 '.join(opts[:2])} 哪方口径 认定".strip(),
        })
        for i, opt in enumerate(opts[:3]):
            paras = " ".join(option_paraphrases(opt)[:4])
            views.append({
                "id": f"conclusion_opt{i}",
                "view": "conclusion",
                "query": f"{actors} {paras} {quals}".strip(),
            })
            # 近义核心单独一臂，避免被 actors 稀释
            core = " ".join(option_paraphrases(opt)[:3])
            if core and core != opt:
                views.append({
                    "id": f"conclusion_core{i}",
                    "view": "conclusion",
                    "query": core,
                })
    else:
        views.append({
            "id": "conclusion_plain",
            "view": "conclusion",
            "query": f"{actors} {terms} {quals} 结论 认定".strip() or q,
        })
    views.append({
        "id": "cause",
        "view": "cause",
        "query": f"{actors} {times} {terms} 原因 为何 导致 {quals}".strip(),
    })
    views.append({
        "id": "evidence",
        "view": "evidence",
        "query": (
            f"{actors} {times} 通报 证实 证据 数据 调查 回应 "
            f"{' '.join(frame.evidence_cues[:3])} {terms}"
        ).strip(),
    })
    # 时点×主体键单独检索（灾害／时刻题）
    if frame.time_cues:
        views.append({
            "id": "frame_time_actor",
            "view": "evidence",
            "query": (
                f"{actors} {' '.join(frame.time_cues[:4])} "
                f"{opts[0] if opts else terms} 监控 通稿"
            ).strip(),
        })
    # 去掉空／过短／与原句完全相同的重复
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for v in views:
        qq = " ".join((v.get("query") or "").split())
        if len(qq) < 4:
            continue
        if qq in seen:
            continue
        seen.add(qq)
        out.append({"id": v["id"], "view": v["view"], "query": qq})
    return out


def llm_query_views(question: str, frame: EventFrame | None = None) -> list[dict[str, str]]:
    """本地 14B 补三条改写；失败则空列表。"""
    try:
        from app.kg_lab.ollama_client import generate_json
    except Exception:
        return []
    frame = frame or extract_event_frame(question)
    prompt = (
        "把研判问句改写成三个检索查询，JSON："
        '{"conclusion":"...","cause":"...","evidence":"..."}。'
        "conclusion＝对立结论／口径；cause＝原因／机制；evidence＝可核验证据线索。"
        "只用问句里出现的主体与概念，不要编造专名。\n"
        f"问句：{question}\n"
        f"已抽主体：{frame.actors}；选项：{frame.options}"
    )
    try:
        out = generate_json(prompt, num_predict=180, temperature=0.0)
    except Exception:
        return []
    parsed = out.get("parsed") or {}
    if not isinstance(parsed, dict):
        return []
    views = []
    for key in ("conclusion", "cause", "evidence"):
        qq = str(parsed.get(key) or "").strip()
        if len(qq) >= 4:
            views.append({"id": f"llm_{key}", "view": key, "query": qq})
    return views


def all_query_views(
    question: str,
    *,
    use_llm: bool = False,
    frame: EventFrame | None = None,
) -> list[dict[str, str]]:
    frame = frame or extract_event_frame(question)
    views = rule_query_views(question, frame)
    if use_llm:
        for v in llm_query_views(question, frame):
            if not any(v["query"] == x["query"] for x in views):
                views.append(v)
    return views
