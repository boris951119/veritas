"""离线演示：零网络、零 API key 跑通多智能体协同研判全流程。

现场断网/额度异常时的演示兜底：桩客户端按角色分流响应（并行也确定），
归并/冲突/质证/仲裁桩从提示文本动态解析结论 id，引文从案例文本动态
摘取——案例文案微调不会打桩。产物写到 out_offline/，与在线产物同构。

覆盖两个案例：
- demo-solid-state（固态电池科研情报）
- bi-delivery-risk（数据中台交付风险企业情报）

注意：冲突桩必须匹配【归并后】的组代表语句（「悲观方向结论」等），
因此正则里要含「悲观/进展」；仅匹配原始结论措辞会让冲突检测永远为空
（曾有此回归：离线报告 0 冲突）。
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
from app.pipeline import RunDeps, RunSpec

_REPO = Path(__file__).resolve().parent.parent


def _quote_of(dossier: Dossier, keyword: str, cap: int = 110) -> tuple[str, str]:
    """从案例段落里摘含关键词的原文（引文桩永远逐字命中）。

    表格行没有句号、按句切会带出整段表格——先按「表格行整行」提取；
    散文按句切；兜底取关键词所在行。超长一律截逐字前缀（仍是合法引文）。"""
    for src in dossier.sources:
        for seg in src.segments:
            if keyword not in seg.text:
                continue
            for line in seg.text.split("\n"):
                if keyword in line and line.strip().startswith("|"):
                    return line.strip()[:cap], seg.id
            for sent in re.split(r"(?<=[。！？])", seg.text):
                sent = sent.strip()
                if keyword in sent and len(sent) >= 10:
                    return sent[:cap], seg.id
            for line in seg.text.split("\n"):
                if keyword in line:
                    return line.strip()[:cap], seg.id
    raise SystemExit(f"离线桩初始化失败：案例文本缺少关键词「{keyword}」")


class OfflineStubClient:
    """按 system 提示角色分流的桩；协同段从提示文本动态解析 id。

    子类通过类属性适配案例：PESSIM_RE/PROG_RE（兜底正则）、POLARITY
    （语句→「悲观/进展」精确映射，归并分组以此为准——正则会被「无…风险」
    这类正向措辞骗到，把健康结论误入悲观组）、TOPIC/CONFLICT_DESC/
    RATIONALE（冲突与仲裁文案）、_panel_payloads()。
    """

    PESSIM_RE = r"悲观|不确定|难以|风险|叙事|纠纷|延期"
    PROG_RE = r"进展|路径|正常|健康|提前"
    POLARITY: dict[str, str] = {}
    TOPIC = ""
    CONFLICT_DESC = ""
    RATIONALE = ""

    def __init__(self, dossier: Dossier):
        self.dossier = dossier
        self._rebut_i = 0
        pessimistic, optimistic = self._panel_payloads()
        self._pessimistic = pessimistic
        self._optimistic = optimistic

    def _panel_payloads(self):
        raise NotImplementedError

    # ------------------------------------------------------------------

    def chat(self, model, messages, json_mode=False):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        # 派发顺序敏感：仲裁者提示词里含「质证」二字（「双方已各出一轮
        # 质证」），必须先判「仲裁者」再判「质证」，否则仲裁收到质证文案、
        # extract_json 失败 → 冲突永远未消解。
        if "仲裁者" in system:
            return _resp(self._arbitrate_reply(user))
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
            return _resp(self._rebuttal())
        return _resp("{}")

    def _rebuttal(self) -> str:
        return ("对方证据只覆盖单点进展，回避了风险与成本的整体证据链。"
                if self._rebut_i % 2 else
                "对方引用的乐观指标来自厂商自述文件，且与客观账目数据相抵触。")

    # -- 协同段动态桩 ---------------------------------------------------

    def _lines(self, user: str) -> list[tuple[str, str]]:
        out = []
        for line in user.split("\n"):
            m = re.match(r"\[(CON-[0-9a-f]+)\]（([^）]*)）(.+)", line)
            if m:
                out.append((m.group(1), m.group(3)))
        return out

    def _group_of(self, stmt: str) -> str:
        """归并定向：精确映射优先，正则兜底（未登记的新语句）。"""
        return self.POLARITY.get(stmt) or (
            "悲观" if re.search(self.PESSIM_RE, stmt) else "进展")

    def _merge_reply(self, user: str) -> str:
        groups: dict[str, list[str]] = {}
        for cid, stmt in self._lines(user):
            groups.setdefault(self._group_of(stmt), []).append(cid)
        payload = [{"statement": f"{k}方向结论", "member_ids": ids}
                   for k, ids in groups.items() if ids]
        return json.dumps({"groups": payload}, ensure_ascii=False)

    def _conflict_reply(self, user: str) -> str:
        lines = self._lines(user)
        doom = next((cid for cid, s in lines
                     if re.search(self.PESSIM_RE, s)), None)
        prog = next((cid for cid, s in lines
                     if re.search(self.PROG_RE, s)), None)
        if not (doom and prog) or doom == prog:
            return json.dumps({"conflicts": []}, ensure_ascii=False)
        return json.dumps({"conflicts": [{
            "a": doom, "b": prog, "topic": self.TOPIC,
            "description": self.CONFLICT_DESC,
        }]}, ensure_ascii=False)

    def _arbitrate_reply(self, user: str) -> str:
        lines = self._lines(user)
        prog = next((cid for cid, s in lines
                     if re.search(self.PROG_RE, s)), None)
        winner = prog or (lines[0][0] if lines else "tie")
        return json.dumps({"winner": winner, "rationale": self.RATIONALE},
                          ensure_ascii=False)


class BatteryStubClient(OfflineStubClient):
    """固态电池案例桩：乐观/悲观双结论 + 装车实证。"""

    TOPIC = "2030年量产可行性"
    CONFLICT_DESC = "对量产时间表与工程瓶颈的判断对立"
    RATIONALE = ("乙方证据等级更高且与中试客观数据一致，甲方核心论据依赖 D 级转述")
    POLARITY = {
        "固态电池2030年前规模量产存在较大不确定性": "悲观",
        "全固态电池2030年前难以规模量产，宣称的目标偏融资叙事": "悲观",
        "半固态电池能量密度优势已获装车验证": "进展",
        "界面阻抗已有工程化抑制手段，2027年装车路测后量产路径明确": "进展",
        "试点产线点亮与设备国产化采购表明产线准备度持续上升": "进展",
    }

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


class DeliveryRiskStubClient(OfflineStubClient):
    """企业情报案例桩：交付健康（多数） vs 回款/延期风险（少数保留）。"""

    TOPIC = "数据中台业务线交付健康度"
    CONFLICT_DESC = "对交付进度与回款/结算风险的判断对立"
    RATIONALE = ("乙方有账目与进度双重客观证据支撑；甲方的纠纷与延期信号"
                 "来自单一条目，未构成系统性风险证据，列为少数意见保留")
    POLARITY = {
        # 主流派两句都是正向陈述——含「风险」字样也必须归进展组
        "数据中台业务线整体交付进度正常，各项目按计划推进": "进展",
        "财务回款整体健康，无逾期与坏账风险": "进展",
        "技术选型经POC对比验证，实时链路满足业务实时性要求": "进展",
        "项目已预留应急预算并建立风险登记机制，交付韧性有制度保障": "进展",
        "回款与结算已出现实际纠纷信号，交付健康度被内部汇报美化": "悲观",
        "客户B项目高风险项未闭环，存在验收延期与回款延迟风险": "悲观",
    }

    def _panel_payloads(self):
        q_rate, seg_rate = _quote_of(self.dossier, "整体完成率")
        q_pay, seg_pay = _quote_of(self.dossier, "无逾期应付账款")
        q_invoice, seg_inv = _quote_of(self.dossier, "重开发票")
        q_delay, seg_delay = _quote_of(self.dossier, "接口文档缺失")
        q_poc, seg_poc = _quote_of(self.dossier, "POC测试验证")
        q_fund, seg_fund = _quote_of(self.dossier, "应急资金")

        def payload(conclusions):
            return json.dumps({"conclusions": conclusions}, ensure_ascii=False)

        mainstream = payload([
            {"statement": "数据中台业务线整体交付进度正常，各项目按计划推进",
             "evidence": [{"quote": q_rate, "segment_id": seg_rate,
                           "relation": "correlation", "level": "B",
                           "note": "进度汇报实证：完成率提前于计划"}]},
            {"statement": "财务回款整体健康，无逾期与坏账风险",
             "evidence": [{"quote": q_pay, "segment_id": seg_pay,
                           "relation": "correlation", "level": "A",
                           "note": "来往账目一手数据"}]},
        ])
        redteam = payload([
            {"statement": "回款与结算已出现实际纠纷信号，交付健康度被内部汇报美化",
             "evidence": [{"quote": q_invoice, "segment_id": seg_inv,
                           "relation": "correlation", "level": "A",
                           "note": "账目应付差异实录：发票退回重开"}]},
            {"statement": "客户B项目高风险项未闭环，存在验收延期与回款延迟风险",
             "evidence": [{"quote": q_delay, "segment_id": seg_delay,
                           "relation": "correlation", "level": "B",
                           "note": "进度汇报自认高风险项"}]},
        ])
        technologist = payload([
            {"statement": "技术选型经POC对比验证，实时链路满足业务实时性要求",
             "evidence": [{"quote": q_poc, "segment_id": seg_poc,
                           "relation": "correlation", "level": "B",
                           "note": "厂商POC对比数据（自述口径）"}]},
            {"statement": "项目已预留应急预算并建立风险登记机制，交付韧性有制度保障",
             "evidence": [{"quote": q_fund, "segment_id": seg_fund,
                           "relation": "correlation", "level": "B",
                           "note": "管理计划风险条款"}]},
        ])
        return mainstream, {"红队": redteam, "怀疑": redteam,
                            "技术推进": technologist}


def _resp(content: str):
    from types import SimpleNamespace
    return SimpleNamespace(content=content)


def _run_offline(case_dir: Path, stub_cls) -> None:
    dossier = load_case(case_dir)
    result = run_case(RunSpec(case_dir=case_dir, out_dir=case_dir / "out_offline"),
                      RunDeps(client=stub_cls(dossier)))
    print(result.report_md)
    print(f"[离线演示] {case_dir.name} 报告与日志已写入 {result.out_dir}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _run_offline(_REPO / "cases" / "demo-solid-state", BatteryStubClient)
    print("\n" + "=" * 60 + "\n")
    _run_offline(_REPO / "cases" / "bi-delivery-risk", DeliveryRiskStubClient)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
