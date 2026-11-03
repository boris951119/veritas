"""C-137：树17 细读注意力分层＋硬约束（权重只进树17计划／分析师提示）。

Boyu 工单件①：按交卷 ``rank_order``（唯一线上序）给「看／引」强度分层——
前段＝细读重看（高注意），后段＝轻扫；冲突成对任一侧进细读 ⇒ 对立侧
强制进细读（优先于「排名靠后少看」）；可核验钉（时间／数额）加权封顶。

边界（工单钉死）：
- 权重**只**活在树17 计划面（``surface.tree17.attention``）与分析师提示；
  禁止进 pack_material／一筛二筛系数面（键名避开 FORBIDDEN_PACK_KEYS，
  整体过 ``audit_forbidden_keys``）；
- 不改一筛／二筛／盒 dens 公式；盒与 rank_order 逐位不动；
- 权重键可迁移＝rank 档／是否冲突边／是否可核验钉；零案名、零案专属词表；
- 金标不读本模块任何输入。

开关：``VERITAS_TREE17_RANK_WEIGHT``（默认开＝出厂；显式 0/false/off/no
回退＝注意力面整层缺席、提示词与改前逐字相同）。
扫参：``VERITAS_TREE17_HEAD_TIER``（细读档大小，默认 3；评测臂倒推用）。
"""

from __future__ import annotations

import os
from typing import Any

_ENV = "VERITAS_TREE17_RANK_WEIGHT"
_ENV_HEAD = "VERITAS_TREE17_HEAD_TIER"

DEFAULT_HEAD_TIER = 3
DEFAULT_STEP = 0.15      # 名次衰减步长（可扫初值；倒推后如改须记录）
WEIGHT_FLOOR = 0.2       # 轻扫档地板＝封顶的另一半（防单维扭曲）
WEIGHT_CAP = 1.0
NAIL_BONUS = 0.05        # 可核验钉加成（封顶内）

TIER_CLOSE = "close"     # 细读重看（高注意）
TIER_SCAN = "scan"       # 轻扫


def rank_weight_enabled() -> bool:
    """默认开。显式 0/false/off/no ＝回退（注意力面整层缺席）。"""
    v = (os.environ.get(_ENV) or "").strip().lower()
    return v not in ("0", "false", "off", "no")


def head_tier_from_env() -> int:
    raw = (os.environ.get(_ENV_HEAD) or "").strip()
    try:
        n = int(raw) if raw else DEFAULT_HEAD_TIER
    except ValueError:
        n = DEFAULT_HEAD_TIER
    return max(1, n)


def build_attention(
    rank_order: list[str],
    plan: dict[str, Any] | None,
    conflict_pairs: Any,
    *,
    head_tier: int | None = None,
    step: float = DEFAULT_STEP,
) -> dict[str, Any] | None:
    """按 rank_order 构建注意力分层（盒序不动；零金标）。

    rank_order＝交卷序（唯一线上序）；plan＝tree17 计划（items 提供
    side／可核验分项）；conflict_pairs＝surface 冲突对（support/oppose 行）。
    """
    order = [str(x) for x in (rank_order or []) if str(x).strip()]
    if not order:
        return None
    h = max(1, int(head_tier or head_tier_from_env()))
    h = min(h, len(order))
    items = {
        str(it.get("para_id")): it
        for it in ((plan or {}).get("items") or [])
        if isinstance(it, dict)
    }

    def _nail(pid: str) -> bool:
        vv = (items.get(pid) or {}).get("verifiability") or {}
        try:
            return bool(int(vv.get("time_n") or 0) or int(vv.get("amount_n") or 0))
        except (TypeError, ValueError):
            return False

    def _side(pid: str) -> str:
        return str((items.get(pid) or {}).get("side") or "none")

    # 1) 名次档：前 h 段细读，其余轻扫
    tier_of: dict[str, str] = {}
    for i, pid in enumerate(order, 1):
        tier_of[pid] = TIER_CLOSE if i <= h else TIER_SCAN

    # 2) 冲突成对强制：任一侧细读 ⇒ 对立侧强制细读（优先于名次）
    pair_rows: list[dict[str, str]] = []
    if isinstance(conflict_pairs, dict):
        raw = conflict_pairs.get("conflicts") or []
    elif isinstance(conflict_pairs, list):
        raw = conflict_pairs
    else:
        raw = []
    pair_forced: list[str] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        s_id = str(row.get("support_id") or "").strip()
        o_id = str(row.get("oppose_id") or "").strip()
        if not s_id or not o_id:
            continue
        if s_id not in tier_of or o_id not in tier_of:
            continue  # 成对行只对盒内 id 生效
        s_close = tier_of[s_id] == TIER_CLOSE
        o_close = tier_of[o_id] == TIER_CLOSE
        forced_here: list[str] = []
        if s_close and not o_close:
            tier_of[o_id] = TIER_CLOSE
            forced_here.append(o_id)
        elif o_close and not s_close:
            tier_of[s_id] = TIER_CLOSE
            forced_here.append(s_id)
        pair_forced.extend(forced_here)
        pair_rows.append({
            "support_id": s_id, "oppose_id": o_id,
            "support_close": tier_of[s_id] == TIER_CLOSE,
            "oppose_close": tier_of[o_id] == TIER_CLOSE,
            "forced": bool(forced_here),
        })

    # 3) 权重：名次衰减（rank1 最强）＋钉加成；地板／封顶防单维扭曲
    tiers: list[dict[str, Any]] = []
    for i, pid in enumerate(order, 1):
        close = tier_of[pid] == TIER_CLOSE
        if close:
            w = WEIGHT_CAP - step * (i - 1)
            w = max(WEIGHT_FLOOR, w)
        else:
            w = WEIGHT_FLOOR
        nail = _nail(pid)
        if nail and close:
            w = min(WEIGHT_CAP, w + NAIL_BONUS)
        tiers.append({
            "id": pid,
            "rank": i,
            "tier": tier_of[pid],
            "weight": round(float(w), 4),
            "in_pair": any(pid in (r["support_id"], r["oppose_id"])
                           for r in pair_rows),
            "pair_forced": pid in pair_forced,
            "nail": nail,
            "side": _side(pid),
        })

    n_close = sum(1 for t in tiers if t["tier"] == TIER_CLOSE)
    n_scan = len(tiers) - n_close
    n_pair_both = sum(
        1 for r in pair_rows if r["support_close"] and r["oppose_close"])
    return {
        "enabled": True,
        "head_tier": h,
        "step": float(step),
        "weight_floor": WEIGHT_FLOOR,
        "weight_cap": WEIGHT_CAP,
        "nail_bonus": NAIL_BONUS,
        "n_close": n_close,
        "n_scan": n_scan,
        "pair_rows": pair_rows,
        "n_pair_both_close": n_pair_both,
        "pair_forced_ids": pair_forced,
        "tiers": tiers,
    }


def render_attention_block(att: dict[str, Any] | None) -> str:
    """渲染分析师可见的注意力＋硬约束块（可迁移槽位，零案名）。"""
    if not att:
        return ""
    tiers = [t for t in (att.get("tiers") or []) if isinstance(t, dict)]
    close = [t for t in tiers if t.get("tier") == TIER_CLOSE]
    close_sorted = sorted(
        close, key=lambda t: (-float(t.get("weight") or 0.0),
                              int(t.get("rank") or 10**9)))
    lines = [
        "",
        "【细读注意力（按交卷排名加权）】",
        f"- 细读重看（高注意）＝下列 {len(close_sorted)} 段：逐段精读，"
        "优先从中取证据；引用优先度＝列表顺序（rank1 最强，逐名次递减）；",
        "- 其余段＝轻扫：快速通读，可引用但非优先；除非属成对必读或带"
        "可核验钉（时间／数额／声明）。",
    ]
    pair_rows = [r for r in (att.get("pair_rows") or [])
                 if isinstance(r, dict) and r.get("support_id")
                 and r.get("oppose_id")]
    if pair_rows:
        lines.append(
            "- 成对冲突（须两边都看、两边都尽量各引至少一条）："
            + "；".join(
                f"{r['support_id']} vs {r['oppose_id']}"
                for r in pair_rows))
    if att.get("pair_forced_ids"):
        lines.append("- 已自动升级进细读的对立侧："
                     + "、".join(str(x) for x in att["pair_forced_ids"]))
    if close_sorted:
        lines.append("细读名单（按引用优先序）：")
        for t in close_sorted:
            tag = []
            if t.get("pair_forced"):
                tag.append("成对强制")
            if t.get("nail"):
                tag.append("可核验钉")
            side = str(t.get("side") or "none")
            if side in ("option_a", "option_b", "both"):
                tag.append(f"side={side}")
            suffix = ("｜" + "｜".join(tag)) if tag else ""
            lines.append(f"- {t['id']}{suffix}")
    lines += [
        "硬约束：",
        "1. 结论句尽量引用细读名单内段落；",
        "2. 禁止引用资料清单编号以外的 segment_id；",
        "3. 有成对冲突的题，两边都看、两边都尽量各引至少一条；",
        "4. 可核验钉（时间／数额／声明）优先于通稿壳（综述／评论）；",
        "5. 若资料支持，标明该证据是采信还是对立。",
        "",
    ]
    return "\n".join(lines)


def attention_prompt_from_dossier(dossier: Any) -> str:
    """从 accounting 取注意力面渲染；关旗／缺席 → 空串（与改前逐字相同）。"""
    if not rank_weight_enabled():
        return ""
    acc = getattr(dossier, "accounting", None) or {}
    t17 = acc.get("tree17_cite")
    if not isinstance(t17, dict):
        return ""
    att = t17.get("attention")
    if not isinstance(att, dict) or not att:
        return ""
    return render_attention_block(att)
