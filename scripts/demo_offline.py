"""离线演示：零网络、零 API key 跑通多智能体协同研判全流程。

现场断网/额度异常时的演示兜底：桩客户端按角色分流响应（并行也确定），
归并/冲突/质证/仲裁桩从提示文本动态解析结论 id，引文从案例文本动态
摘取——案例文案微调不会打桩。产物写到 out_offline/，与在线产物同构。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.evidence import Dossier
from app.ingest.case_loader import load_case
from app.pipeline import run_case

_CASE = Path(__file__).resolve().parent.parent / "cases" / "demo-solid-state"


def _quote_of(dossier: Dossier, keyword: str) -> tuple[str, str]:
    """从案例段落里摘一句含关键词的话（引文桩永远逐字命中）。"""
    for src in dossier.sources:
        for seg in src.segments:
            for sent in re.split(r"(?<=[。！？])", seg.text):
                sent = sent.strip()
                if keyword in sent and len(sent) >= 10:
                    return sent, seg.id
    raise SystemExit(f"离线桩初始化失败：案例文本缺少关键词「{keyword}」")


class OfflineStubClient:
    """按 system 提示角色分流的桩；协同段从提示文本动态解析 id。"""

    def __init__(self, dossier: Dossier):
        self.dossier = dossier
        self._rebut_i = 0
        pessimistic, optimistic = self._panel_payloads()
        self._pessimistic = pessimistic
        self._optimistic = optimistic

    def _panel_payloads(self):
        q_doom, seg_doom = _quote_of(self.dossier, "良率")
        q_wall, _ = _quote_of(self.dossier, "界面阻抗")
        q_prog, seg_prog = _quote_of(self.dossier, "工程化抑制")
        q_light, _ = _quote_of(self.dossier, "试点产线")

        def payload(conclusions):
            return json.dumps({"conclusions": conclusions}, ensure_ascii=False)

        mainstream = payload([
            {"statement": "固态电池2030年前规模量产存在较大不确定性",
             "evidence": [{"quote": q_doom, "segment_id": seg_doom,
                           "relation": "correlation", "level": "B",
                           "note": "良率瓶颈未破"}]},
            {"statement": "半固态电池能量密度优势已获装车验证",
             "evidence": [{"quote": _quote_of(self.dossier, "能量密度显著高于")[0],
                           "segment_id": _quote_of(self.dossier, "能量密度显著高于")[1],
                           "relation": "correlation", "level": "A",
                           "note": "装车实证"}]},
        ])
        redteam = payload([
            {"statement": "全固态电池2030年前难以规模量产，宣称的目标偏融资叙事",
             "evidence": [{"quote": q_wall, "segment_id": _quote_of(self.dossier, "界面阻抗")[1],
                           "relation": "expert_judgment", "level": "D",
                           "note": "工程团队悲观判断"}]},
        ])
        technologist = payload([
            {"statement": "界面阻抗已有工程化抑制手段，2027年装车路测后量产路径明确",
             "evidence": [{"quote": q_prog, "segment_id": seg_prog,
                           "relation": "causation", "level": "B",
                           "note": "中试连续运行实证"}]},
            {"statement": "试点产线点亮与设备国产化采购表明产线准备度持续上升",
             "evidence": [{"quote": q_light, "segment_id": _quote_of(self.dossier, "试点产线")[1],
                           "relation": "correlation", "level": "B",
                           "note": "产线进展"}]},
        ])
        return mainstream, {"红队": redteam, "怀疑": redteam,
                            "技术推进": technologist}

    # ------------------------------------------------------------------

    def chat(self, model, messages, json_mode=False):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if "独立研判" in system:
            for mark, payload in self._optimistic.items():
                if mark in system:
                    return _resp(payload)
            return _resp(self._pessimistic)
        if "协调员" in system:
            return _resp(self._merge_reply(user))
        if "分歧审查员" in system:
            return _resp(self._conflict_reply(user))
        if "质证" in system:
            self._rebut_i += 1
            return _resp(
                "对方证据只覆盖单点进展，回避了良率与成本的整体证据链。"
                if self._rebut_i % 2 else
                "对方引用的专家转述属于 D 级灰色信源，且与中试线客观数据相抵触。")
        if "仲裁者" in system:
            return _resp(self._arbitrate_reply(user))
        return _resp("{}")

    # -- 协同段动态桩 ---------------------------------------------------

    def _lines(self, user: str) -> list[tuple[str, str]]:
        out = []
        for line in user.split("\n"):
            m = re.match(r"\[(CON-[0-9a-f]+)\]（([^）]*)）(.+)", line)
            if m:
                out.append((m.group(1), m.group(3)))
        return out

    def _merge_reply(self, user: str) -> str:
        groups: dict[str, list[str]] = {}
        for cid, stmt in self._lines(user):
            key = "悲观" if re.search(r"不确定|难以|风险|叙事", stmt) else "进展"
            groups.setdefault(key, []).append(cid)
        payload = [{"statement": f"{k}方向结论", "member_ids": ids}
                   for k, ids in groups.items() if ids]
        return json.dumps({"groups": payload}, ensure_ascii=False)

    def _conflict_reply(self, user: str) -> str:
        lines = self._lines(user)
        doom = next((cid for cid, s in lines if "不确定" in s or "难以" in s), None)
        prog = next((cid for cid, s in lines if "进展" in s or "路径" in s), None)
        if not (doom and prog):
            return json.dumps({"conflicts": []}, ensure_ascii=False)
        return json.dumps({"conflicts": [{
            "a": doom, "b": prog, "topic": "2030年量产可行性",
            "description": "对量产时间表与工程瓶颈的判断对立",
        }]}, ensure_ascii=False)

    def _arbitrate_reply(self, user: str) -> str:
        lines = self._lines(user)
        prog = next((cid for cid, s in lines if "进展" in s or "路径" in s), None)
        winner = prog or (lines[0][0] if lines else "tie")
        return json.dumps({
            "winner": winner,
            "rationale": "乙方证据等级更高且与中试客观数据一致，甲方核心论据依赖 D 级转述",
        }, ensure_ascii=False)


def _resp(content: str):
    from types import SimpleNamespace
    return SimpleNamespace(content=content)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    dossier = load_case(_CASE)
    result = run_case(
        _CASE,
        out_dir=_CASE / "out_offline",
        client=OfflineStubClient(dossier),
    )
    print(result.report_md)
    print(f"[离线演示] 报告与日志已写入 {result.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
