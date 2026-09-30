"""智能体注册表：系统全部智能体的清单（答辩「智能体架构」的数据源）。

回答「是不是单智能体」的数据版答案：本系统是 10+ 个角色智能体的
协同系统——各有独立上下文、输出契约与配对闸，通过归并→冲突→质证→
仲裁→主席汇总协议协同。多智能体 ≠ 多模型（角色/上下文/契约的隔离
才是定义要件，多智能体辩论范式的标准做法）；**模型异构是配置项**
（roster 的 per-agent model 字段），当前网关 plan 单模型下以角色
多样性保视角多样性，错误相关性由零 LLM 机械闸与人工复核对冲。
"""

from __future__ import annotations

from app.agents.panel import DEFAULT_ROSTER, load_roster
from app.config import Settings

# (名称, 职责, 独立性/契约, 输出过什么闸)
_FIXED_AGENTS = [
    ("归并者 merger", "同义结论归并成组，组代表继承证据与署名",
     "独立提示词；只按语义归并", "归并守恒闸（数字⊆成员并集）+member_ids 存在性"),
    ("冲突审查员 conflict-screener", "找出互斥对立的结论对",
     "独立提示词", "冲突对机械校验（id 存在/双方挂证）"),
    ("质证者 rebutters(甲/乙)", "各为立场出一轮书面质证",
     "各自以原 persona 回击", "质证引文逐字闸+引用存在性+二阶注入扫描"),
    ("仲裁者 arbiter", "裁决与说理（证据强度为程序算的机械输入）",
     "独立提示词；新近度只是 tie-break 提示", "winner 合法性+仲裁引用闸"),
    ("主席 chair", "把已过闸结论汇总为面向议题的答案",
     "输入封闭（无权接触原始资料）", "四道闸：引用存在/完整性/数字溯源/长度"),
    ("修复者 repair", "打回结论定向重写（变好才接受否则回滚）",
     "只回传该结论已引段落（围栏内）", "引文闸+数字闸；≤6 次/研判"),
    ("画像探测员 profiler", "1 次调用给接入模型打纪律遵从档",
     "微型案卷，机械判分", "分数由引文/算式/转述闸直接给出"),
    ("图片转码员 transcoder", "图片逐字转写为低可信派生信源",
     "只转写不解读（[无法辨认] 契约）", "先验 0.3+全套闸+失败降级披露"),
]


def agent_inventory(settings: Settings | None = None,
                    roster=None) -> list[dict]:
    """智能体清单（默认编队或自定义 roster）。"""
    entries = roster or DEFAULT_ROSTER
    analysts = [{
        "name": f"分析师 {e[0]}",
        "duty": e[1][:40] + ("…" if len(e[1]) > 40 else ""),
        "isolation": "硬隔离：议题+资料+自己 persona，互不可见对方输出",
        "gates": "引文逐字闸→数字闸（计算/溯源/计数）→话语闸；noncompliant "
                 "档强化契约+修复环",
        "model": (e[2] if len(e) > 2 and e[2]
                  else (settings.models[0] if settings else "（默认模型）")),
    } for e in entries]
    fixed = [{
        "name": name, "duty": duty, "isolation": iso, "gates": gates,
        "model": (settings.models[0] if settings else "（默认模型）"),
    } for name, duty, iso, gates in _FIXED_AGENTS]
    return analysts + fixed


def inventory_markdown(settings: Settings | None = None,
                       roster=None) -> str:
    """清单 → Markdown 表（报告/文档嵌入用）。"""
    rows = agent_inventory(settings, roster)
    lines = ["| 智能体 | 职责 | 独立性/契约 | 输出过闸 | 模型 |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['duty']} | {r['isolation']} "
                     f"| {r['gates']} | `{r['model']}` |")
    return "\n".join(lines)
