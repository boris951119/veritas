"""C-115：冲突三类覆盖＋处置留痕（Q5）。

``VERITAS_CONFLICT_TRACE``（C-145a 起出厂默认开；关＝``=0``）。
开：事实对撞／结论冲突对强制落在树10 既有三档之一
（``same_window``／``cross_day``／``unknown_time``）；无法归类 →
``unclassified`` 披露，不静默丢。每条写清单条目＋处置
（保留／落败转少数／未决）＋理由码／短理由 → accounting，供回放。

C-146：审查后再分流（第二根轴，只贴标签、不改判）。把「像冲突」分成
``oral_misread``（口语／约数／量级读错）｜``date_offset``（日期差，
默认倾向时间档并披露理由）｜``true_oppose``（真对立，进既有 disposition
留痕）｜``other``（判不出，披露不硬塞）。写在同一条留痕行的
``triage_*`` 键与 summary.by_triage 上。

禁：第四类当主路径；「无日期＝非冲突」回退；金标泄漏；pack 系数。
禁（C-146）：分流轴不许吃掉 ``conflict_class`` 三档枚举，也不许改写
``disposition``／置信／归并／采信——数值冲突线仍 STOP。
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys

_ENV = "VERITAS_CONFLICT_TRACE"
ACCOUNTING_KEY = "conflict_trace"

# 树10／C-69 既有硬枚举（勿另发明第四类当主路径）
CONFLICT_CLASSES = frozenset({
    "same_window", "cross_day", "unknown_time",
})
CONFLICT_CLASS_CN = {
    "same_window": "同窗对撞",
    "cross_day": "跨日时序",
    "unknown_time": "时点不明",
    "unclassified": "未归类",
}

# 处置结果硬枚举
DISPOSITIONS = frozenset({"keep", "dissent", "undecided"})
DISPOSITION_CN = {
    "keep": "保留",
    "dissent": "落败转少数",
    "undecided": "未决",
}

# 留痕必填键（齐全率量尺）
TRACE_REQUIRED_KEYS = frozenset({
    "id", "source", "conflict_class", "conflict_class_cn",
    "entry", "disposition", "disposition_cn",
    "reason_code", "reason_short",
})

# ---- C-146：分流轴（第二根轴，只贴标签；不吃 conflict_class／disposition）----
# 四档封闭枚举。与 conflict_class 正交：conflict_class 答「时间上怎么摆」，
# triage_class 答「这到底像不像一次真对立」。
TRIAGE_CLASSES = frozenset({
    "oral_misread", "date_offset", "true_oppose", "other",
})
TRIAGE_CLASS_CN = {
    "oral_misread": "口语／约数误读",
    "date_offset": "日期差（按时间档）",
    "true_oppose": "真对立",
    "other": "判不出（其他）",
}
# 分流必填键（与 TRACE_REQUIRED_KEYS 分开钉：旧行缺 triage 只算「未分流」，
# 不许把既有齐全率拉低＝既有 test_c115_summarize_coverage 的读法不变）
TRIAGE_REQUIRED_KEYS = frozenset({
    "triage_class", "triage_class_cn",
    "triage_reason_code", "triage_reason_short", "triage_evidence",
})
# 口语约数词：写在数字前／后的软化词（台账按数值比，看不出「约」）
_HEDGE_BEFORE = ("约", "近", "超", "逾", "达", "至", "突破", "不到", "低于", "高于", "大约", "大概", "差不多")
_HEDGE_AFTER = ("多", "余", "来", "左右", "上下", "以上", "以下")
_HEDGE_WINDOW_BEFORE = 4   # 数字切片前最多看 4 字
_HEDGE_WINDOW_AFTER = 2    # 数字切片后最多看 2 字
# 约数误读上限：带软化词且极差占比 ≤ 此值才敢判「口语误读」，超了＝真对立
_HEDGE_MAX_REL_GAP = 0.25
# 量级／小数点错位：两值之比≈10^k（k=1..4）且数字串逐字相同
_SCALE_MAX_EXPONENT = 4
_SCALE_TOLERANCE = 0.01
# C-80 已有的「这不是量名」判定：canon 缺＝关键词被当成了指标
_NOT_QUANTITY_REASONS = frozenset({"not_quantity", "no_quantity_hint", "empty"})

_DIGITS_RE = re.compile(r"\D+")


def _triage_row(
    cls: str, reason_code: str, reason_short: str, evidence: dict[str, Any],
) -> dict[str, Any]:
    """分流四键＋证据一次成型（cls 必在封闭枚举内，越界当场抛）。"""
    if cls not in TRIAGE_CLASSES:
        raise ValueError(f"triage class out of enum: {cls!r}")
    return {
        "triage_class": cls,
        "triage_class_cn": TRIAGE_CLASS_CN[cls],
        "triage_reason_code": reason_code,
        "triage_reason_short": reason_short,
        "triage_evidence": evidence,
    }


def _day_key(raw: Any) -> str:
    """与 fact_ledger.Collision.time_class 同口径：只取归一 8 位日。"""
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits[:8] if len(digits) >= 8 else ""


def _digit_string(raw: Any) -> str:
    return _DIGITS_RE.sub("", str(raw or ""))


def _rel_gap(values: list[float]) -> float:
    """组内极差÷较大绝对值（0 或单值→0.0）。分流专用，不进任何打分。"""
    if len(values) < 2:
        return 0.0
    hi = max(abs(v) for v in values)
    if hi <= 0:
        return 0.0
    return (max(values) - min(values)) / hi


def _hedge_hit(fact: Any, seg_texts: dict[str, str] | None) -> str:
    """原文里这个数字切片邻域是否带约数词（台账只看数值，看不见「约」）。"""
    if not seg_texts:
        return ""
    text = seg_texts.get(str(getattr(fact, "seg_id", "") or "")) or ""
    raw = str(getattr(fact, "raw", "") or "").strip()
    if not text or not raw:
        return ""
    at = text.find(raw)
    if at < 0:
        return ""
    before = text[max(0, at - _HEDGE_WINDOW_BEFORE): at]
    after = text[at + len(raw): at + len(raw) + _HEDGE_WINDOW_AFTER]
    for token in _HEDGE_BEFORE:
        if before.endswith(token):
            return f"before:{token}"
    for token in _HEDGE_AFTER:
        if after.startswith(token):
            return f"after:{token}"
    return ""


def _scale_misread(values: list[float]) -> tuple[int, float] | None:
    """存在两值之比≈10^k（k=1..4）→ 返回 (k, 相对误差)；否则 None。

    只判整数级倍率＝单位／小数点读错的指纹（万↔元、%↔倍数）。比值不是
    整数倍率的差异一律不当误读——宁放不错杀。
    """
    uniq = sorted({abs(float(v)) for v in values if float(v) != 0.0})
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            lo, hi = uniq[i], uniq[j]
            if lo <= 0.0:
                continue
            ratio = hi / lo
            for k in range(1, _SCALE_MAX_EXPONENT + 1):
                target = float(10 ** k)
                err = abs(ratio - target) / target
                if err <= _SCALE_TOLERANCE:
                    return (k, round(err, 6))
    return None


def triage_ledger_collision(
    collision: Any,
    conflict_class: str,
    *,
    seg_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """事实对撞行 → 分流（阶梯：日期差 → 约数 → 量级 → 真对立 → 其他）。"""
    facts = list(getattr(collision, "facts", None) or [])
    values = [float(getattr(f, "value", 0.0) or 0.0) for f in facts]
    days = sorted({_day_key(getattr(f, "date", "")) for f in facts} - {""})
    ev: dict[str, Any] = {
        "n_facts": len(facts),
        "values": [round(v, 6) for v in values],
        "rel_gap": round(_rel_gap(values), 6),
    }
    # ① 日期差默认倾向时间档：跨日＝两侧保留为演变，不判谁错（C-115 同句）
    if conflict_class == "cross_day":
        ev["days"] = days
        return _triage_row(
            "date_offset", "cross_day_time_band",
            "两侧时点不同＝按时间档（旧值→新值）处理，不判谁错；"
            "归入时间档不等于资料无冲突",
            ev,
        )
    # ② 口语／约数：数字邻域带软化词，且极差占比在闸内
    hedges = sorted({h for h in (_hedge_hit(f, seg_texts) for f in facts) if h})
    if hedges and ev["rel_gap"] <= _HEDGE_MAX_REL_GAP:
        ev["hedge_tokens"] = hedges
        ev["hedge_max_rel_gap"] = _HEDGE_MAX_REL_GAP
        return _triage_row(
            "oral_misread", "hedge_number",
            "至少一侧原文带约数词（约／近／多／左右…），数值差在约数容差内"
            "＝疑似口语取整，非同一口径的真对立",
            ev,
        )
    # ③ 量级／小数点错位：整数级 10^k 倍率＋数字串同形
    scale = _scale_misread(values)
    if scale is not None and len({_digit_string(getattr(f, "raw", ""))
                                  for f in facts}) <= 1:
        ev["scale_exponent"], ev["scale_rel_err"] = scale
        return _triage_row(
            "oral_misread", "scale_misread",
            "两值成 10 的整数倍率且数字串逐字相同＝疑似单位／小数点读错",
            ev,
        )
    # ④ 关键词串位：C-80 判过「这不是量名」，却仍被当指标配了对撞
    not_quantity = sorted({
        str(getattr(f, "canon_reason", "") or "")
        for f in facts
        if str(getattr(f, "metric_canon", "") or "") == ""
        and str(getattr(f, "canon_reason", "") or "") in _NOT_QUANTITY_REASONS
    })
    if not_quantity:
        ev["canon_missing_reasons"] = not_quantity
        return _triage_row(
            "oral_misread", "metric_not_quantity",
            "量名规范闸判该指标不是量名（no_quantity_hint／not_quantity）"
            "＝关键词被当成指标后配出的对撞，非同一口径的真对立",
            ev,
        )
    # ⑤ 同段两数：两个数出自同一段落＝更像抽取口径串位，而不是两份资料打架
    seg_ids = [str(getattr(f, "seg_id", "") or "") for f in facts]
    if len(facts) >= 2 and len(set(seg_ids)) == 1:
        ev["seg_ids"] = sorted(set(seg_ids))
        return _triage_row(
            "oral_misread", "single_segment_two_numbers",
            "两侧数值同出一段＝疑似指标／口径串位造成的假对撞"
            "（不改检出，只把这一行从真对立里分出来讲）",
            ev,
        )
    # ⑥ 归不了档的时间档（unclassified）＝信息不足，不硬塞真对立
    if conflict_class == "unclassified":
        return _triage_row(
            "other", "unclassified_row",
            "时点档未归类，分流依据不足＝记其他（披露，不静默丢）",
            ev,
        )
    # ⑦ 其余＝同窗／时点不明下的不同数值 → 真对立（disposition 仍按 C-115）
    code = ("distinct_values_same_window" if conflict_class == "same_window"
            else "distinct_values_unknown_time")
    return _triage_row(
        "true_oppose", code,
        "同一口径下的不同数值＝真对立，进既有处置留痕"
        "（未决或按裁决落败转少数）",
        ev,
    )


def _statement_numbers(a_text: str, b_text: str) -> tuple[list[str], list[str]]:
    """两侧结论的数字切片（缩放后字符串，跨写法可比：49.4万 == 494000）。"""
    from app.core.numeric_check import extract_nums

    def _keyed(text: str) -> list[str]:
        out: list[str] = []
        for num in extract_nums(text):
            k = f"{float(num.scaled):.6g}"
            if k not in out:
                out.append(k)
        return out

    return (_keyed(a_text), _keyed(b_text))


def _statement_pair_texts(
    raw: dict, dossier: Any,
) -> tuple[str, str]:
    if dossier is None or not hasattr(dossier, "conclusion"):
        return ("", "")

    def _text(cid: Any) -> str:
        con = dossier.conclusion(str(cid or "")) if cid else None
        return str(getattr(con, "statement", "") or "") if con is not None else ""

    return (_text(raw.get("a_id")), _text(raw.get("b_id")))


def triage_conflict_pair(
    raw: dict,
    conflict_class: str,
    *,
    dossier: Any | None = None,
) -> dict[str, Any]:
    """结论冲突对行 → 分流。

    只用机械可得的事实（两侧原文／主体标签／极性／数值集合），不叫模型、
    不装语义判定：判不出就记 ``other``，既不塞进真对立也不塞进误读。
    """
    a_text, b_text = _statement_pair_texts(raw, dossier)
    ev: dict[str, Any] = {
        "has_a_text": bool(a_text),
        "has_b_text": bool(b_text),
    }
    if conflict_class == "cross_day":
        return _triage_row(
            "date_offset", "pair_cross_day",
            "所挂对撞行是跨日时序＝按时间档处理，不判谁错；"
            "归入时间档不等于资料无冲突",
            ev,
        )
    if not a_text or not b_text:
        return _triage_row(
            "other", "pair_statement_unreadable",
            "取不到两侧结论原文＝分流依据不足，记其他（不猜）",
            ev,
        )
    from app.core.citation_check import normalize
    from app.core.conflict_pairing import (
        extract_subject, extract_topics, polarity_of,
    )

    na, nb = normalize(a_text), normalize(b_text)
    sa, sb = extract_subject(a_text), extract_subject(b_text)
    ev["subject_a"], ev["subject_b"] = sa or "", sb or ""
    pa, pb = polarity_of(a_text), polarity_of(b_text)
    ev["polarity_a"], ev["polarity_b"] = pa or "", pb or ""
    ta, tb = sorted(extract_topics(a_text)), sorted(extract_topics(b_text))
    ev["topics_a"], ev["topics_b"] = ta, tb
    nums = _statement_numbers(a_text, b_text)
    ev["numbers_a"] = nums[0]
    ev["numbers_b"] = nums[1]
    # ① 逐字同句（归一化后）＝同义表述被当成对立
    if na and na == nb:
        return _triage_row(
            "oral_misread", "pair_statement_identical",
            "两侧结论归一化后逐字相同＝同义表述被当成对立",
            ev,
        )
    # ② 主体标签都在且不同＝跨主体误配（配对闸本该拦下，漏到这里就亮出来）
    if sa and sb and sa != sb:
        return _triage_row(
            "oral_misread", "pair_subject_mismatch",
            f"两侧主体标签不同（{sa}／{sb}）＝关键词或主体串位，不是同一事实的对立",
            ev,
        )
    # ③ 议题维都抽到且不相交＝两条结论压根不在问同一件事（沿用配对闸同一组词表）
    if ta and tb and not (set(ta) & set(tb)):
        return _triage_row(
            "oral_misread", "pair_topic_disjoint",
            f"两侧议题维不相交（{ '、'.join(ta) } ↔ { '、'.join(tb) }）"
            "＝配错了题，不是同一议题的对立",
            ev,
        )
    # ④ 极性相反＝机械可认证的对立
    if {pa, pb} == {"pos", "neg"}:
        return _triage_row(
            "true_oppose", "pair_polarity_opposite",
            "两侧极性一正一负（沿用配对闸同一张极性表）＝真对立，进处置留痕",
            ev,
        )
    # ⑤ 两侧都带数且数值集合不相交＝口径不同的数值对立
    if nums[0] and nums[1] and not (set(nums[0]) & set(nums[1])):
        return _triage_row(
            "true_oppose", "pair_disjoint_numbers",
            "两侧结论各自的数值集合不相交＝数值层面的真对立，进处置留痕",
            ev,
        )
    # ⑥ 机械判不出（定性议题／极性不明／数值共用）→ 其他，不硬塞
    return _triage_row(
        "other", "pair_mechanically_undetermined",
        "定性分歧或机械信号不足＝记其他（需人看；既不计入真对立也不计入口语误读）",
        ev,
    )


def triage_fields_complete(row: dict) -> bool:
    """分流四键齐全且档在封闭枚举内（与 trace_fields_complete 互不吃掉）。"""
    if not isinstance(row, dict):
        return False
    if not TRIAGE_REQUIRED_KEYS <= set(row.keys()):
        return False
    if row.get("triage_class") not in TRIAGE_CLASSES:
        return False
    if not str(row.get("triage_reason_code") or "").strip():
        return False
    if not str(row.get("triage_reason_short") or "").strip():
        return False
    return isinstance(row.get("triage_evidence"), dict)



def conflict_trace_enabled(settings: Any | None = None) -> bool:
    """默认随出厂（C-145a 起 True）。``VERITAS_CONFLICT_TRACE=0`` 关。

    settings 为 None 时走 ``Settings.from_env()``（出厂默认＋env 叠加），
    不许在无参路径里绕开出厂默认——否则翻默认后仲裁／导出挂点静默不走。
    """
    if settings is None:
        from app.config import Settings
        settings = Settings.from_env()
    if hasattr(settings, "conflict_trace"):
        return bool(getattr(settings, "conflict_trace"))
    v = (os.environ.get(_ENV) or "").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return False


def normalize_conflict_class(raw: Any) -> str:
    """强制三档；其它 → unclassified（披露，不丢条目）。"""
    key = str(raw or "").strip()
    if key in CONFLICT_CLASSES:
        return key
    return "unclassified"


def _reason_for_ledger(conflict_class: str) -> tuple[str, str]:
    if conflict_class == "same_window":
        return "pick_side", "同窗对撞：待采信一方或声明资料不足"
    if conflict_class == "cross_day":
        return "timeline_keep", "跨日时序：两侧保留为演变，不判谁错"
    if conflict_class == "unknown_time":
        return "time_unknown", "时点不明：未据此排序，不强制采信"
    return "unclassified", "无法归入同窗／跨日／时点不明三档"


def _disposition_for_ledger(conflict_class: str) -> str:
    # 跨日＝程序侧两侧保留；同窗／时点不明／未归类＝未决（禁「无日期＝非冲突」）
    if conflict_class == "cross_day":
        return "keep"
    return "undecided"


def trace_ledger_collision(
    collision: Any,
    *,
    index: int,
    seg_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """事实对撞台账一条 → 留痕记录（含 C-146 分流轴）。"""
    raw_tc = getattr(collision, "time_class", None)
    if callable(raw_tc):
        raw_tc = collision.time_class
    conflict_class = normalize_conflict_class(raw_tc)
    disposition = _disposition_for_ledger(conflict_class)
    reason_code, reason_short = _reason_for_ledger(conflict_class)
    facts = list(getattr(collision, "facts", None) or [])
    entry = {
        "entity": str(getattr(collision, "entity", "") or ""),
        "metric": str(getattr(collision, "metric", "") or ""),
        "n_facts": len(facts),
        "source_ids": sorted({
            str(getattr(f, "source_id", "") or "") for f in facts
        }),
        "seg_ids": [
            str(getattr(f, "seg_id", "") or "") for f in facts
        ],
        "cross_source": bool(getattr(collision, "cross_source", False)),
    }
    row = {
        "id": f"LEDGER-{index:04d}",
        "source": "fact_ledger",
        "conflict_class": conflict_class,
        "conflict_class_cn": CONFLICT_CLASS_CN.get(
            conflict_class, CONFLICT_CLASS_CN["unclassified"]),
        "entry": entry,
        "disposition": disposition,
        "disposition_cn": DISPOSITION_CN[disposition],
        "reason_code": reason_code,
        "reason_short": reason_short,
    }
    row.update(triage_ledger_collision(
        collision, conflict_class, seg_texts=seg_texts))
    return row


def _pair_as_dict(pair: Any) -> dict:
    if isinstance(pair, dict):
        return pair
    if hasattr(pair, "to_dict"):
        return pair.to_dict()
    return {
        "id": str(getattr(pair, "id", "") or ""),
        "a_id": str(getattr(pair, "a_id", "") or ""),
        "b_id": str(getattr(pair, "b_id", "") or ""),
        "topic": str(getattr(pair, "topic", "") or ""),
        "description": str(getattr(pair, "description", "") or ""),
        "resolution": (
            pair.resolution.to_dict()
            if getattr(pair, "resolution", None) is not None
            and hasattr(pair.resolution, "to_dict")
            else getattr(pair, "resolution", None)
        ),
    }


def disposition_of_pair(pair: Any) -> tuple[str, str, str]:
    """结论冲突对 → (disposition, reason_code, reason_short)。

    有胜负：整对记 dissent（败方转少数；胜方保留体现在 entry.winner）。
    平局／无裁决：undecided。
    """
    raw = _pair_as_dict(pair)
    res = raw.get("resolution") if isinstance(raw.get("resolution"), dict) else None
    if not res:
        return "undecided", "no_resolution", "尚未裁决或仲裁失败"
    winner = str(res.get("winner_id") or "")
    a_id, b_id = str(raw.get("a_id") or ""), str(raw.get("b_id") or "")
    method = str(res.get("method") or res.get("decision_path") or "")
    if winner in (a_id, b_id) and a_id and b_id:
        return (
            "dissent",
            f"resolved:{method or 'arbitration'}",
            f"胜方 {winner}；败方转少数意见保留",
        )
    if winner == "tie" or method == "tie":
        return "undecided", "tie", "证据加权后无法裁决，双方保留 majority"
    return "undecided", "unresolved", "裁决未形成合法胜负"


def trace_conflict_pair(
    pair: Any,
    *,
    index: int,
    collisions: list[Any] | None = None,
    dossier: Any | None = None,
) -> dict[str, Any]:
    """结论级冲突对 → 留痕；class 能挂对撞则挂，否则 unclassified。"""
    raw = _pair_as_dict(pair)
    conflict_class = "unclassified"
    if dossier is not None and collisions:
        conflict_class = _classify_pair_via_dossier(raw, dossier, collisions)
    disposition, reason_code, reason_short = disposition_of_pair(raw)
    res = raw.get("resolution") if isinstance(raw.get("resolution"), dict) else {}
    entry = {
        "pair_id": str(raw.get("id") or f"PAIR-{index:04d}"),
        "a_id": str(raw.get("a_id") or ""),
        "b_id": str(raw.get("b_id") or ""),
        "topic": str(raw.get("topic") or ""),
        "winner_id": str((res or {}).get("winner_id") or ""),
        "method": str((res or {}).get("method") or ""),
        "decision_path": str((res or {}).get("decision_path") or ""),
    }
    row = {
        "id": str(raw.get("id") or f"PAIR-{index:04d}"),
        "source": "conflict_pair",
        "conflict_class": conflict_class,
        "conflict_class_cn": CONFLICT_CLASS_CN.get(
            conflict_class, CONFLICT_CLASS_CN["unclassified"]),
        "entry": entry,
        "disposition": disposition,
        "disposition_cn": DISPOSITION_CN.get(
            disposition, DISPOSITION_CN["undecided"]),
        "reason_code": reason_code,
        "reason_short": reason_short,
    }
    row.update(triage_conflict_pair(
        raw, conflict_class, dossier=dossier))
    return row


def _classify_pair_via_dossier(
    raw: dict, dossier: Any, collisions: list[Any],
) -> str:
    seg_class: dict[str, str] = {}
    for c in collisions:
        tc = normalize_conflict_class(
            c.time_class if not callable(getattr(c, "time_class", None))
            else c.time_class
        )
        for f in getattr(c, "facts", None) or []:
            sid = str(getattr(f, "seg_id", "") or "")
            if sid and tc in CONFLICT_CLASSES:
                seg_class[sid] = tc
    hit: set[str] = set()
    for cid in (raw.get("a_id"), raw.get("b_id")):
        con = dossier.conclusion(str(cid or "")) if hasattr(dossier, "conclusion") else None
        if con is None:
            continue
        ev_ids = list(getattr(con, "evidence_ids", None) or [])
        for eid in ev_ids:
            ev = None
            if hasattr(dossier, "evidence"):
                ev = dossier.evidence(eid)
            if ev is None:
                for e in getattr(dossier, "evidences", None) or []:
                    if str(getattr(e, "id", "")) == str(eid):
                        ev = e
                        break
            if ev is None:
                continue
            for sid in getattr(ev, "segment_ids", None) or []:
                tc = seg_class.get(str(sid))
                if tc:
                    hit.add(tc)
    if len(hit) == 1:
        return next(iter(hit))
    # 0 或多档冲突 → 不发明第四类
    return "unclassified"


def trace_fields_complete(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    if not TRACE_REQUIRED_KEYS <= set(row.keys()):
        return False
    if row.get("conflict_class") not in CONFLICT_CLASSES | {"unclassified"}:
        return False
    if row.get("disposition") not in DISPOSITIONS:
        return False
    if not str(row.get("reason_code") or "").strip():
        return False
    if not str(row.get("reason_short") or "").strip():
        return False
    if not isinstance(row.get("entry"), dict):
        return False
    return True


def summarize_trace(records: list[dict]) -> dict[str, Any]:
    n = len(records)
    by_class = {k: 0 for k in list(CONFLICT_CLASSES) + ["unclassified"]}
    by_disp = {k: 0 for k in DISPOSITIONS}
    # C-146：分流计数（固定四键序＝跨进程可比，不随 set 迭代序漂）
    by_triage = {k: 0 for k in sorted(TRIAGE_CLASSES)}
    n_untriaged = 0
    complete = 0
    triaged_complete = 0
    for r in records:
        cc = str(r.get("conflict_class") or "unclassified")
        by_class[cc] = by_class.get(cc, 0) + 1
        dd = str(r.get("disposition") or "")
        if dd in by_disp:
            by_disp[dd] += 1
        tc = str(r.get("triage_class") or "")
        if tc in by_triage:
            by_triage[tc] += 1
        else:
            n_untriaged += 1
        if trace_fields_complete(r):
            complete += 1
        if triage_fields_complete(r):
            triaged_complete += 1
    classified = n - by_class.get("unclassified", 0)
    return {
        "n": n,
        "classified": classified,
        "unclassified": by_class.get("unclassified", 0),
        "coverage_rate": (classified / n) if n else 0.0,
        "trace_complete": complete,
        "trace_complete_rate": (complete / n) if n else 0.0,
        "by_class": by_class,
        "by_disposition": by_disp,
        "by_triage": by_triage,
        "triaged": n - n_untriaged,
        "untriaged": n_untriaged,
        "triage_complete_rate": (triaged_complete / n) if n else 0.0,
    }


def _segment_text_map(dossier: Any) -> dict[str, str]:
    """C-146：分流要看数字邻域（「约50万」的「约」不在数值切片里）。

    只读段文本，不改任何检出／判定；案卷取不到段落时返回空表＝约数腿自动不生效。
    """
    out: dict[str, str] = {}
    for src in getattr(dossier, "sources", None) or []:
        for seg in getattr(src, "segments", None) or []:
            sid = str(getattr(seg, "id", "") or "")
            if sid and sid not in out:
                out[sid] = str(getattr(seg, "text", "") or "")
    return out


def build_conflict_trace(
    dossier: Any,
    *,
    collisions: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """汇编事实对撞＋结论冲突对留痕（不去重丢弃；unclassified 保留）。"""
    records: list[dict[str, Any]] = []
    cols = list(collisions) if collisions is not None else []
    if collisions is None:
        try:
            from app.core.fact_ledger import find_collisions
            cols = list(find_collisions(dossier))
        except Exception:  # noqa: BLE001 — 留痕失败不吞冲突本体
            cols = []
    seg_texts = _segment_text_map(dossier)
    for i, c in enumerate(cols, 1):
        records.append(trace_ledger_collision(
            c, index=i, seg_texts=seg_texts))
    pairs = list(getattr(dossier, "conflicts", None) or [])
    for i, p in enumerate(pairs, 1):
        records.append(
            trace_conflict_pair(
                p, index=i, collisions=cols, dossier=dossier,
            )
        )
    return records


def apply_conflict_trace(
    dossier: Any,
    *,
    collisions: list[Any] | None = None,
    enabled: bool | None = None,
    settings: Any | None = None,
) -> dict[str, Any] | None:
    """旗开写入 accounting[conflict_trace]；旗关＝None、不写键。"""
    if enabled is None:
        enabled = conflict_trace_enabled(settings)
    if not enabled:
        return None
    records = build_conflict_trace(dossier, collisions=collisions)
    summary = summarize_trace(records)
    payload = {
        "enabled": True,
        "records": records,
        "summary": summary,
        "classes": sorted(CONFLICT_CLASSES),
        "dispositions": sorted(DISPOSITIONS),
        # C-146：分流轴自成四档，conflict_class 三档枚举一字未动
        "triage_classes": sorted(TRIAGE_CLASSES),
        "triage_axes": "triage_class 与 conflict_class 正交；只贴标签，"
                       "不改 disposition／置信／归并／采信",
    }
    # C-145：归并硬约束闸否决事件随面走（独立节，不冒充第四类冲突）
    from app.core.merge_gate import fold_into_trace_payload
    fold_into_trace_payload(
        payload, getattr(dossier, "accounting", None))
    bad = audit_forbidden_keys(payload)
    if bad:
        raise ValueError(f"conflict_trace hits forbidden: {bad}")
    for k in FORBIDDEN_PACK_KEYS:
        if k in payload:
            raise ValueError(f"forbidden pack key in conflict_trace: {k}")
    acc = getattr(dossier, "accounting", None)
    if acc is None:
        dossier.accounting = {}
        acc = dossier.accounting
    acc[ACCOUNTING_KEY] = payload
    return payload
