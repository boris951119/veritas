"""结论的覆盖声明三态：把「我审了多全」钉成结论自带的属性。

为什么需要（2026-10-13 实测）：存量 304 条结论里有 17 条用了全称量词
（全部/所有/无一/均…），**17 条的引用覆盖全部低于 25%**，最低 1.8%。
例如「所有客户项目中未发现已发生的人员流失风险」只引了 7% 的段落。
现有九道闸查的是「引文真不真、数字对不对」，没有任何一道问过
**「你说『全部』，你看的真是全部吗」**——那 17 条里只有 6 条被别的闸顺手撞亮，
其余静默通过，而且是甲方会拿去做决定的那种话。

口径学 REA 的 `relationshipCoverage`（`src/domain/relationshipCoverage.ts:1-22`）：
三态各自的必填项不一样，**非法状态在构造阶段就造不出来**——
`partial` 必须至少带一条局限，`unknown` 必须带一句理由，
而不是靠 lint、靠警告、靠测试去拦一个已经写坏的结论。

与闸的分工：本模块只管「声明本身合不合法」；
「声称了范围却没声明」由 `app.core.scope_check.audit_scope` 亮黄牌。
"""

from __future__ import annotations

from dataclasses import dataclass

STATES = ("complete", "partial", "unknown")

STATE_CN = {
    "complete": "已覆盖全部",
    "partial": "部分覆盖",
    "unknown": "覆盖情况未知",
    "": "未声明",
}


def _as_list(value: object) -> list[str]:
    """局限清单允许字符串或字符串列表，但清空不许。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    raise ValueError(f"limitations 只能是字符串或字符串列表，收到 {type(value).__name__}")


@dataclass(frozen=True)
class Coverage:
    """结论的覆盖声明。构造即校验：非法组合根本造不出来。"""

    state: str
    limitations: tuple[str, ...] = ()
    reason: str = ""
    scope: str = ""          # 声明覆盖的对象，如「本次纳入的 12 份信源」

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", str(self.state or "").strip())
        if self.state not in STATES:
            raise ValueError(
                f"coverage.state 只能是 {STATES} 之一，收到 {self.state!r}")
        lims = tuple(_as_list(list(self.limitations) if self.limitations else None))
        object.__setattr__(self, "limitations", lims)
        object.__setattr__(self, "reason", str(self.reason or "").strip())
        object.__setattr__(self, "scope", str(self.scope or "").strip())
        if self.state == "partial" and not lims:
            raise ValueError("partial 覆盖必须至少写明一条局限——否则等于没说")
        if self.state == "unknown" and not self.reason:
            raise ValueError("unknown 必须写明为什么未知，否则不许用这个词")

    # ---------------------------------------------------------------- 构造入口

    @classmethod
    def parse(cls, value: "Coverage | dict | str | None") -> "Coverage | None":
        """模型给的 JSON、dict、字符串或 None → Coverage；不合法就抛，不猜。"""
        if value is None or isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, Coverage):
            return value
        if isinstance(value, str):
            # 允许简写："complete"
            return cls(state=value.strip())
        if isinstance(value, dict):
            return cls(state=str(value.get("state") or value.get("status") or ""),
                       limitations=tuple(value.get("limitations") or ()),
                       reason=str(value.get("reason") or ""),
                       scope=str(value.get("scope") or ""))
        raise ValueError(f"coverage 只能是 dict/字符串/None，收到 {type(value).__name__}")

    # ---------------------------------------------------------------- 序列化

    def to_dict(self) -> dict:
        return {"state": self.state, "limitations": list(self.limitations),
                "reason": self.reason, "scope": self.scope}

    def note(self) -> str:
        """一句人话，供报告与工作台直接摆出来。"""
        if self.state == "complete":
            return f"覆盖声明：{self.scope or '本题所依据的全部材料'}（已覆盖全部）"
        if self.state == "partial":
            return (f"覆盖声明：部分覆盖——{'；'.join(self.limitations)}"
                    + (f"（范围：{self.scope}）" if self.scope else ""))
        return (f"覆盖声明：未知——{self.reason}"
                + (f"（范围：{self.scope}）" if self.scope else ""))

    @classmethod
    def merge_declarations(cls, declarations: "object") -> "Coverage | None":
        """归并时取**最保守**的一份声明，局限合并去重。

        组结论是成员的上位概括：成员里有人声明「部分覆盖·仅纳入 12/200 份」，
        组结论绝不能因为归并就变成「无声明」甚至「已覆盖全部」——
        那等于让局限在归并这一步蒸发掉。顺序 unknown > partial > complete。
        """
        parsed: list["Coverage"] = []
        for raw in declarations or ():
            cov = cls.parse(raw)
            if cov is not None:
                parsed.append(cov)
        if not parsed:
            return None
        rank = {"unknown": 0, "partial": 1, "complete": 2}
        weakest = min(parsed, key=lambda c: rank[c.state])
        limitations: list[str] = []
        for cov in parsed:                      # 所有成员的局限都要留下痕迹
            for item in cov.limitations:
                if item not in limitations:
                    limitations.append(item)
            if cov.reason and f"未知：{cov.reason}" not in limitations:
                limitations.append(f"未知：{cov.reason}")
        scope = weakest.scope or next(
            (c.scope for c in parsed if c.scope), "")
        if weakest.state == "complete":
            return cls(state="complete", scope=scope)
        if weakest.state == "partial":
            return cls(state="partial", limitations=tuple(limitations) or
                       ("归并成员中存在部分覆盖声明，未列明具体局限",),
                       scope=scope)
        return cls(state="unknown",
                   reason=weakest.reason or "；".join(limitations) or "成员未说明为何未知",
                   scope=scope)
