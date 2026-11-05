"""C-159：置信面「档位依据＋高档收据」——只读本行已印出的数，不新造判定、不抬档。

工单边界（三条都做成硬约束，不只是注释）：
1. **零新判定**：本模块不调模型、不读案卷原文、不碰 `dossier`，输入只有
   ``confidence.json`` 已经成行的那些键（score／terms／gates／band／band_rel／
   C-156 的 component_basis 与 recompute）。
2. **零改分**：不写 ``score``／``band``／``band_rel``／``terms``，也不新增任何
   参与计算的系数；合式常量与阈值一律从 :func:`app.core.confidence.aggregate_constants`
   当场取（同一份对象，不存在手抄漂移），本模块只格式化。
3. **无据不硬编**：等级／署名／六环／复算这些来源，字段不在场就写「未披露」，
   不猜、不留空壳假装有依据（``VERITAS_CONF_FACE_DETAIL=0`` 时 ``component_basis``
   整个缺席，此时理由句里等级子句自动降级为「未披露」）。

只加两个键：
- ``档位依据``：每行一句人话——为什么这行落这一档（阈值关系＋贡献最大项＋最低分量＋
  硬门状态＋等级与支撑＋分位档）。
- ``高档收据``：仅 ``band == "高"`` 的行——把「这条凭什么叫高置信」摊成可核字段
  （阈值原样值、高出量、五项贡献、等级构成与等级权、支撑条数、六环、复算可复现）。

数字纪律：理由句里出现的每个数字，都必须能在这行自己的数值、合式常量表、或由这两者
现算出的乘积／差值里找到；``scripts/probe_c159_conf_receipt.py`` 逐行独立复算这套
允许集（不在本模块盖章）。
"""
from __future__ import annotations

from app.core.confidence import aggregate_constants
from app.core.evidence import EvidenceLevel, LEVEL_WEIGHT

RECEIPT_KEY = "档位依据"
HIGH_KEY = "高档收据"

# terms 键 → 对外可读的分量名（对齐官方 3.2.1 三维度；只改名不重算）
_DIM_CN = {
    "b": "截距",
    "s": "信源可信度",
    "c": "证据覆盖",
    "a": "证据一致性",
    "h": "推理链完整性",
}
# 合式权重键 → 行内取数键
_TERM_OF_W = {"s": "strength", "c": "coverage", "a": "agreement_factor",
              "h": "chain_for_aggregate"}
_GATE_CN = {
    "G1_citation": "G1 引文命中",
    "G2_no_evidence": "G2 无证据",
    "G3_premise_broken": "G3 前提破坏",
}
_NOT_DISCLOSED = "未披露（置信面细节旗关）"


def _fmt(v: float) -> str:
    """四位小数、去掉无意义尾零；只格式化，不改变数值。"""
    s = f"{float(v):.4f}".rstrip("0").rstrip(".")
    return s or "0"


def _level_weight(level: object) -> float | None:
    """等级权原样读出（LEVEL_WEIGHT 数值一字不动，这里只取来展示）。"""
    key = str(level or "")
    try:
        return float(LEVEL_WEIGHT[EvidenceLevel(key)])
    except (ValueError, KeyError):
        return None


def _contributions(row: dict) -> tuple[dict[str, float], list[str]]:
    """五项贡献＝印出的权重 × 印出的分量（round4），不新算法。"""
    w = aggregate_constants()["weights"]
    terms = row.get("terms") or {}
    contrib: dict[str, float] = {}
    parts: list[str] = []
    base = round(float(w["b"]), 4)
    contrib[_DIM_CN["b"]] = base
    for wk in ("s", "c", "a", "h"):
        v = float(terms.get(_TERM_OF_W[wk]) or 0.0)
        c = round(float(w[wk]) * v, 4)
        tk = _TERM_OF_W[wk]
        contrib[_DIM_CN[wk]] = c
        parts.append(f"{_DIM_CN[wk]} {_fmt(w[wk])}×{_fmt(v)}＝{_fmt(c)}（{tk}）")
    return contrib, parts


def _gate_clause(row: dict) -> str:
    g = (row.get("terms") or {}).get("gates") or {}
    fired: list[str] = []
    for k, cn in _GATE_CN.items():
        v = g.get(k)
        if isinstance(v, dict) and v.get("fired"):
            cap = v.get("cap")
            fired.append(f"{cn}（封顶 {_fmt(cap)}）" if cap is not None else cn)
    if fired:
        return "触发硬门＝" + "、".join(fired)
    return "三道硬门均未触发"


def _level_clause(row: dict, *, official_name_of=None) -> tuple[str, dict]:
    """证据等级子句＋（供高档收据用的）等级明细；来源不在场就写未披露。"""
    cb = row.get("component_basis")
    if not isinstance(cb, dict):
        return f"证据等级{_NOT_DISCLOSED}", {}
    levels = [str(x) for x in (cb.get("levels") or [])]
    counts: dict[str, int] = {}
    for lv in levels:
        counts[lv] = counts.get(lv, 0) + 1
    if not counts:
        return "证据等级＝本案卷该结论无带等级证据", {}
    detail: dict[str, dict] = {}
    bits: list[str] = []
    for lv in sorted(counts):
        lw = _level_weight(lv)
        official = ""
        if official_name_of is not None:
            try:
                official = str(official_name_of(lv))
            except Exception:
                official = ""
        detail[lv] = {"条数": counts[lv],
                      "等级权": (lw if lw is not None else _NOT_DISCLOSED),
                      "官方名": official or "映射取不到"}
        bits.append(f"{lv} {counts[lv]} 条")
    clause = "证据等级 " + "／".join(bits) + "（等级权进 strength）"
    return clause, detail


def reason_sentence(row: dict, *, official_name_of=None) -> tuple[str, dict]:
    """(理由句, 高档收据) 两个只读披露；高档收据只在 band=="高" 时非空。"""
    score = float(row.get("score") or 0.0)
    band = str(row.get("band") or "")
    thr = aggregate_constants()["band_thresholds"]
    hi, mid = float(thr["high"]), float(thr["mid"])
    contrib, parts = _contributions(row)
    cb = row.get("component_basis") if isinstance(row.get("component_basis"), dict) else {}
    rc = row.get("recompute") if isinstance(row.get("recompute"), dict) else {}
    terms = row.get("terms") or {}

    if band == "高":
        rel = f"score {_fmt(score)}≥高阈值 {_fmt(hi)}"
        over = round(score - hi, 4)
        rel += f"，高出 {_fmt(over)}" if over > 0 else ""
    elif band == "中":
        rel = (f"score {_fmt(score)}＜高阈值 {_fmt(hi)}（差 "
               f"{_fmt(round(hi - score, 4))}），≥中阈值 {_fmt(mid)}")
    else:
        rel = f"score {_fmt(score)}＜中阈值 {_fmt(mid)}（未达高阈值 {_fmt(hi)}）"

    # 最大／最低只在四个可变分量里挑（截距是常数，挑它没信息量）
    variable = {k: v for k, v in contrib.items() if k != _DIM_CN["b"]}
    order = sorted(variable.items(), key=lambda kv: kv[1], reverse=True)
    top_cn, top_v = order[0]
    low_cn, low_v = order[-1]
    top_part = next((p for p in parts if p.startswith(top_cn + " ")), "")
    low_part = next((p for p in parts if p.startswith(low_cn + " ")), "")
    if not top_part:  # 理论上不触发（四个分量都有 w×v 式子）；兜底给现值
        top_part = f"{top_cn} {_fmt(top_v)}"
    if not low_part:
        low_part = f"{low_cn} {_fmt(low_v)}"

    lv_clause, lv_detail = _level_clause(row, official_name_of=official_name_of)
    support = (f"支撑证据 {int(cb.get('n_evidence') or 0)} 条、署名 "
               f"{int(cb.get('n_authors') or 0)} 人（编队 {int(cb.get('n_panel') or 0)} 人）"
               if cb else f"支撑与署名{_NOT_DISCLOSED}")
    rings = ""
    if cb:
        broken = list(cb.get("chain_rings_broken") or [])
        applic = list(cb.get("chain_rings_applicable") or [])
        rings = (f"；六环适用 {len(applic)} 项、断 {len(broken)} 项"
                 + (f"（断＝{'、'.join(broken)}）" if broken else "（无断环）"))
    repro = (f"；按印出数复算可复现（差 {_fmt(float(rc.get('delta') or 0.0))}）"
             if rc.get("reproducible") is True else
             (f"；按印出数复算超出容差（差 {_fmt(float(rc.get('delta') or 0.0))}）"
              if rc.get("reproducible") is False else f"；复算{_NOT_DISCLOSED}"))

    sent = (f"档＝{band}：{rel}；分位档＝{row.get('band_rel') or '—'}。"
            f"贡献最大＝{top_part}；最低分量＝{low_part}。"
            f"{lv_clause}；{support}{rings}；{_gate_clause(row)}{repro}。")

    high: dict = {}
    if band == "高":
        gates = (row.get("terms") or {}).get("gates") or {}
        high = {
            "阈值原样值": {"高": hi, "中": mid,
                          "高阈值来源": "官方达标行原文（confidence.py 常量，非手抄）"},
            "本行分数": round(score, 4),
            "高出阈值": round(score - hi, 4),
            "五项贡献": contrib,
            "分量取数": {k: terms.get(k) for k in
                        ("strength", "coverage", "agreement", "agreement_factor",
                         "chain", "chain_for_aggregate")},
            "证据等级构成": lv_detail or _NOT_DISCLOSED,
            "支撑证据条数": int(cb.get("n_evidence") or 0) if cb else _NOT_DISCLOSED,
            "署名分析师数": int(cb.get("n_authors") or 0) if cb else _NOT_DISCLOSED,
            "编队人数": int(cb.get("n_panel") or 0) if cb else _NOT_DISCLOSED,
            "六环适用": list(cb.get("chain_rings_applicable") or []) if cb else _NOT_DISCLOSED,
            "六环断": list(cb.get("chain_rings_broken") or []) if cb else _NOT_DISCLOSED,
            "硬门状态": {k: bool(isinstance(v, dict) and v.get("fired"))
                        for k, v in gates.items()},
            "按印出数复算": (rc or _NOT_DISCLOSED),
            "分位档": str(row.get("band_rel") or ""),
            "本键性质": "只解释，不参与计算；score 与 band 一律由合式与阈值现判",
        }
    return sent, high


def attach_receipts(rows: list[dict], *, official_name_of=None) -> dict:
    """就地给每行贴 ``档位依据``（高档行另贴 ``高档收据``）。返回摘要计数。

    不变式：贴键前后的 ``score``／``band``／``band_rel``／``terms`` 必须一字不动，
    本函数只新增上面两个键。
    """
    n_rows = 0
    n_sentence = 0
    n_high = 0
    empty = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        n_rows += 1
        sent, high = reason_sentence(row, official_name_of=official_name_of)
        row[RECEIPT_KEY] = sent
        if high:
            row[HIGH_KEY] = high
            n_high += 1
        if sent.strip():
            n_sentence += 1
        else:
            empty += 1
    return {"n_rows": n_rows, "n_sentence": n_sentence,
            "n_high_receipt": n_high, "n_empty_sentence": empty}
