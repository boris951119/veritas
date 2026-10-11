"""议题槽位契约（零 LLM）：问的期间 × 指标，资料盖不盖得住。

主答案只允许两种：槽位被同期间同口径覆盖，或明确「资料不足」。
其他年份 / 半年度数字只能进「最近可得」副注，不能写进主答案。

期间口径：
- 全年 / 年度 / 只写年份 → fy
- 上半年 / 半年度 → h1
- 一至四季度 → q1–q4
披露日（「2025年4月28日」）不是会计期间，不计入覆盖。

口语不齐（回读确认、可早停，不瞎猜）：
- 会计期间未锁定
- 指标口径歧义（利润/收入/销售…）
- 时点类型未锁定（期间数 / 时点快照 / 异动事件窗）
- 多轮方案未消歧（回购等）
- 对象主体未锁定（多家股份公司未点名，或只说「子公司」未给全称）
"""

from __future__ import annotations

import re
from typing import Any

from app.core.evidence import Dossier

_GRAIN = {
    "全年": "fy", "年度": "fy",
    "上半年": "h1", "半年度": "h1",
    "一季度": "q1", "第一季度": "q1",
    "二季度": "q2", "三季度": "q3", "四季度": "q4",
}
_GRAIN_CN = {
    "fy": "全年", "h1": "半年度",
    "q1": "一季度", "q2": "二季度", "q3": "三季度", "q4": "四季度",
}

# aliases=资料侧匹配；ask_aliases=议题侧「口径已齐」才认（长的优先）
_METRICS: list[dict[str, Any]] = [
    {
        "id": "net_profit_parent",
        "label": "归属于上市公司股东的净利润",
        "aliases": (
            "归属于上市公司股东的净利润",
            "归母净利润",
            "归母净利",
            "净利润",
            "净利",
        ),
        "ask_aliases": (
            "归属于上市公司股东的净利润",
            "归母净利润",
            "归母净利",
        ),
    },
    {
        "id": "net_profit_deducted",
        "label": "扣非归母净利润",
        "aliases": (
            "扣除非经常性损益后的净利润",
            "扣非归母净利润",
            "扣非净利润",
            "扣非净利",
        ),
        "ask_aliases": (
            "扣除非经常性损益后的净利润",
            "扣非归母净利润",
            "扣非净利润",
            "扣非净利",
        ),
    },
    {
        "id": "revenue",
        "label": "营业收入",
        "aliases": ("营业收入", "营业总收入", "营收"),
        "ask_aliases": ("营业收入", "营业总收入", "营收"),
    },
    {
        "id": "sales_volume",
        "label": "销量",
        "aliases": ("销量", "销售量"),
        "ask_aliases": ("销量", "销售量"),
    },
    {
        "id": "sales_amount",
        "label": "销售金额",
        "aliases": ("销售金额", "销售额", "销售收入"),
        "ask_aliases": ("销售金额", "销售额", "销售收入"),
    },
    {
        "id": "dividend",
        "label": "现金红利",
        "aliases": ("现金红利", "派发现金股利", "每10股派", "派息", "分红"),
        "ask_aliases": ("现金红利", "派发现金股利", "每10股派"),
    },
]

_Q_PERIOD = re.compile(
    r"(20\d{2})\s*年\s*"
    r"(全年|上半年|半年度|一季度|第一季度|二季度|三季度|四季度|年度)?"
)
_OBS = re.compile(
    r"(20\d{2})\s*年\s*"
    r"(全年|上半年|半年度|一季度|第一季度|二季度|三季度|四季度)"
    r"|(20\d{2})\s*年度"
)


def slot_intent(question: str, dossier: Dossier | None = None) -> dict:
    """口语议题意图：指标口径 / 期间 / 时点类型 / 方案轮次 / 主体是否齐套。

    不齐只回读澄清，不瞎猜。多家股份公司的判定需要案卷，单看问句不猜。
    """
    q = question or ""
    cleaned = _strip_ratio_mentions(q)
    metrics = _match_ask_metrics(cleaned)
    ambiguous = _ambiguous_metric_tips(cleaned, metrics)
    period = _question_period(q)
    period_d = None
    if period is not None:
        year, grain = period
        period_d = {
            "year": year, "grain": grain, "grain_cn": _GRAIN_CN[grain],
        }
    time_kind, time_tips = _time_kind_check(q, metrics, period is not None)
    round_tips = _scheme_round_tips(q)
    subject_tips = _subject_tips(q, dossier)
    disclosures = _subject_disclosures(q, dossier)

    clarify: list[str] = []
    clarify.extend(subject_tips)
    clarify.extend(ambiguous)
    if metrics and period is None and time_kind in (None, "period"):
        labels = "、".join(m["label"] for m in metrics[:3])
        clarify.append(
            f"已识别指标「{labels}」，但未锁定会计期间："
            "请补年份与口径（全年/半年度/季度），勿默认最近一期")
    clarify.extend(time_tips)
    clarify.extend(round_tips)

    return {
        "metrics": [{"id": m["id"], "label": m["label"]} for m in metrics],
        "period": period_d,
        "time_kind": time_kind,
        "slots": parse_slots(q),
        "clarify": clarify,
        "disclosures": disclosures,
        "complete": not clarify,
    }


def parse_slots(question: str) -> list[dict]:
    """从议题抽出可机械验收的槽位（可多指标）。无年份或口径未齐 → 空。

    「占归母净利润比例」只是分母，不是在问该指标本身，先剥掉再匹配。
    有指标无期间 → 空槽位（见 slot_intent.clarify），不替用户假定年份。
    """
    q = question or ""
    cleaned = _strip_ratio_mentions(q)
    period = _question_period(q)
    if period is None:
        return []
    # 口径歧义时不生成可验收槽位，避免半齐半不齐硬跑覆盖
    if _ambiguous_metric_tips(cleaned, _match_ask_metrics(cleaned)):
        return []
    year, grain = period
    return [{
        "metric_id": m["id"],
        "label": m["label"],
        "year": year,
        "grain": grain,
        "grain_cn": _GRAIN_CN[grain],
    } for m in _match_ask_metrics(cleaned)]


def assess_slots(dossier: Dossier) -> list[dict]:
    """每个槽位 → covered / insufficient + 最近可得。

    覆盖来源：信源同期间观察，或已过闸多数结论已答出该指标数字。
    """
    out: list[dict] = []
    for slot in parse_slots(dossier.question):
        metric = next(m for m in _METRICS if m["id"] == slot["metric_id"])
        obs = _observations(dossier, metric)
        exact = [o for o in obs
                 if o["year"] == slot["year"] and o["grain"] == slot["grain"]]
        if exact:
            out.append({**slot, "status": "covered",
                        "segment_ids": _uniq([o["seg_id"] for o in exact]),
                        "nearest": None, "via": "source"})
            continue
        if _answered_by_conclusions(dossier, metric, slot):
            out.append({**slot, "status": "covered", "segment_ids": [],
                        "nearest": None, "via": "conclusion"})
            continue
        nearest = _nearest(obs, slot["year"], slot["grain"])
        out.append({
            **slot,
            "status": "insufficient",
            "segment_ids": [],
            "nearest": nearest,
            "via": None,
            "reason": (
                f"未披露{slot['year']}年{slot['grain_cn']}{slot['label']}"
            ),
        })
    return out


def priority_segment_ids(dossier: Dossier, limit: int = 6) -> list[str]:
    """与议题指标同段的期间观察优先装箱（含最近可得，便于声明缺口）。"""
    slots = parse_slots(dossier.question)
    if not slots:
        return []
    metric = next(m for m in _METRICS if m["id"] == slots[0]["metric_id"])
    obs = _observations(dossier, metric)
    # 问到的期间在前，其余按年近远
    year, grain = slots[0]["year"], slots[0]["grain"]
    obs.sort(key=lambda o: (
        0 if o["year"] == year and o["grain"] == grain else 1,
        abs(o["year"] - year),
        o["seg_id"],
    ))
    ids: list[str] = []
    for o in obs:
        if o["seg_id"] not in ids:
            ids.append(o["seg_id"])
        if len(ids) >= limit:
            break
    return ids


def insufficient_headline(slot: dict) -> str:
    """主答案：无数字，禁止用其他期间冒充。"""
    text = (f"资料不足：未披露{slot['year']}年{slot['grain_cn']}"
            f"{slot['label']}，不能用其他期间的数字代替。")
    return text if len(text) <= 80 else text[:79] + "…"


def period_clarify_headline(intent: dict) -> str:
    """兼容旧名 → clarify_headline。"""
    return clarify_headline(intent)


def clarify_headline(intent: dict) -> str:
    """槽位不齐：主答案只回读确认，不写金额、不假定口径/期间。"""
    tips = intent.get("clarify") or []
    if not tips:
        return "议题要素未确认，请补充后再答。"
    # 优先用第一条澄清（最关键缺口）；过长则收束
    head = tips[0]
    if len(tips) > 1:
        head = head.rstrip("。") + f"；另有 {len(tips) - 1} 项待确认。"
    prefix = "议题未齐："
    text = prefix + head
    return text if len(text) <= 80 else text[:79] + "…"


def apply_answer_contract(dossier: Dossier, synthesis: dict) -> dict:
    """未覆盖槽位时改写 headline；已覆盖却误报资料不足时按多数结论纠正。"""
    assessments = assess_slots(dossier)
    intent = slot_intent(dossier.question, dossier)
    synthesis = dict(synthesis)
    synthesis["slots"] = assessments
    synthesis["slot_intent"] = {
        "metrics": intent["metrics"],
        "period": intent["period"],
        "time_kind": intent.get("time_kind"),
        "complete": intent["complete"],
        "clarify": intent["clarify"],
    }
    notes = list(synthesis.get("gate_notes") or [])
    issues = list(synthesis.get("open_issues") or [])
    for tip in intent["clarify"]:
        if not any(i.get("kind") == "question" and tip[:12] in str(i.get("text"))
                   for i in issues):
            issues.insert(0, {"kind": "question", "ref": "议题",
                              "text": tip if len(tip) <= 60 else tip[:59] + "…"})
    synthesis["open_issues"] = issues
    headline = str(synthesis.get("headline") or "")

    # 任一槽位不齐：机械改写标题，禁止模型瞎填
    if intent["clarify"]:
        synthesis["headline"] = clarify_headline(intent)
        notes.append("议题槽位未齐 → 主答案改为回读确认，禁止假定")
        synthesis["gate_notes"] = notes
        return synthesis

    gaps = [a for a in assessments if a["status"] != "covered"]
    covered = [a for a in assessments if a["status"] == "covered"]

    # 槽位已齐：标题喊资料不足，或漏了所问指标的绝对值 → 按结论重拼
    if covered and not gaps:
        miss_amt = _headline_misses_covered_amounts(
            dossier, headline, covered)
        if "资料不足" in headline or miss_amt:
            fixed = _headline_from_majors(dossier, covered)
            if fixed:
                synthesis["headline"] = fixed
                notes.append(
                    "槽位已覆盖但标题误报资料不足 → 按多数结论重写"
                    if "资料不足" in headline
                    else "标题缺少所问指标绝对值 → 按槽位结论补全")
                synthesis["gate_notes"] = notes
                synthesis["open_issues"] = [
                    i for i in (synthesis.get("open_issues") or [])
                    if not (i.get("kind") == "gap"
                            and "资料缺失" in str(i.get("text") or ""))]
        return synthesis

    if not gaps:
        return synthesis
    # 一题多问 / 多槽位：不能用其中一个未覆盖槽位盖掉整句标题
    n_q = (dossier.question or "").count("？") + (dossier.question or "").count("?")
    if n_q >= 2 or len(assessments) >= 2:
        return synthesis
    slot = gaps[0]
    synthesis["headline"] = insufficient_headline(slot)
    notes.append("槽位未被同期间覆盖 → 主答案改为资料不足")
    synthesis["gate_notes"] = notes
    issues = list(synthesis.get("open_issues") or [])
    nearest = slot.get("nearest")
    extra = ""
    if nearest:
        extra = (f"；最近可得为{nearest['year']}年"
                 f"{_GRAIN_CN[nearest['grain']]}，不能冒充所问期间")
    text = f"{slot['reason']}{extra}"
    if len(text) > 60:
        text = text[:59] + "…"
    if not any(i.get("kind") == "gap" and "未披露" in str(i.get("text"))
               for i in issues):
        issues.insert(0, {"kind": "gap", "ref": "议题", "text": text})
    synthesis["open_issues"] = issues
    return synthesis


def slot_prompt(dossier: Dossier) -> str:
    """注入主席提示：未覆盖时禁止把其他期间写进 headline；缺期间禁止假定。"""
    intent = slot_intent(dossier.question, dossier)
    rows = assess_slots(dossier)
    if not rows and not intent["clarify"]:
        return ""
    lines = ["", "议题槽位（程序预检，headline 必须遵守）："]
    for tip in intent["clarify"]:
        lines.append(f"- {tip}")
        lines.append(
            "- 禁止自行假定「最近一期」或资料内任意年份；"
            "期间未确认前 headline 不得写具体金额。")
    for a in rows:
        if a["status"] == "covered":
            lines.append(
                f"- {a['year']}年{a['grain_cn']}{a['label']}：资料已覆盖，"
                "答案须挂已核结论。")
        else:
            lines.append(
                f"- {a['year']}年{a['grain_cn']}{a['label']}：资料不足。"
                "headline 只能写资料不足，禁止写入其他年份或半年度的数字。")
    return "\n".join(lines)


def _strip_ratio_mentions(question: str) -> str:
    """去掉「占某指标比例/比重」，避免比例题被当成在问该指标的绝对值。"""
    return re.sub(r"占[^，。？?\n]{0,40}?比例|占[^，。？?\n]{0,40}?比重",
                  " ", question or "")


def _match_ask_metrics(question: str) -> list[dict]:
    """议题侧：仅 ask_aliases 命中才算口径已齐。"""
    hits: list[tuple[int, dict]] = []
    for metric in _METRICS:
        pos = _alias_pos(question, metric, key="ask_aliases")
        if pos >= 0:
            hits.append((pos, metric))
    hits.sort(key=lambda x: x[0])
    return [m for _, m in hits]


def _match_metrics(question: str) -> list[dict]:
    """资料侧观察用：走全量 aliases。"""
    hits: list[tuple[int, dict]] = []
    for metric in _METRICS:
        pos = _alias_pos(question, metric, key="aliases")
        if pos >= 0:
            hits.append((pos, metric))
    hits.sort(key=lambda x: x[0])
    return [m for _, m in hits]


def _alias_pos(question: str, metric: dict, key: str = "aliases") -> int:
    best = -1
    for alias in metric.get(key) or metric.get("aliases") or ():
        p = question.find(alias)
        if p >= 0 and (best < 0 or p < best):
            best = p
    return best


def _ambiguous_metric_tips(question: str, clear: list[dict]) -> list[str]:
    """利润/收入/销售/分红等口语过宽 → 澄清口径。"""
    q = question or ""
    ids = {m["id"] for m in clear}
    tips: list[str] = []

    profit_clear = bool(ids & {"net_profit_parent", "net_profit_deducted"})
    # 「利润分配」是分红事项，不是在问利润金额
    profit_q = re.sub(r"利润分配|利润表", " ", q)
    if not profit_clear and re.search(r"净利润|净利|(?<![营净])利润", profit_q):
        tips.append(
            "指标口径未锁定「利润」：请明确归母净利润 / 扣非净利润 / 合并净利润")

    rev_clear = "revenue" in ids or "sales_amount" in ids
    if (not rev_clear and "收入" in q
            and "营业收入" not in q and "销售收入" not in q
            and "营收" not in q):
        tips.append(
            "指标口径未锁定「收入」：请明确营业收入或销售金额")

    sales_clear = bool(ids & {"sales_volume", "sales_amount"})
    if not sales_clear and re.search(r"销售(?!金额|收入|额|量)|卖了多少|卖得怎样", q):
        if "销量" not in q and "销售量" not in q:
            tips.append(
                "指标口径未锁定「销售」：请明确销量（吨/件）或销售金额")

    if "dividend" not in ids and re.search(r"派息|分红", q):
        if not re.search(r"每\s*10\s*股|现金红利|派发现金股利", q):
            tips.append(
                "指标口径未锁定「分红/派息」：请明确每股派息还是分红总额")

    return tips


def _time_kind_check(question: str, metrics: list[dict],
                     has_period: bool) -> tuple[str | None, list[str]]:
    """期间数 / 时点快照 / 事件窗：问法与时点类型要匹配。"""
    # 剥掉财务科目里的「股东」字样，避免「归属于上市公司股东的净利润」误触发股权时点
    q = re.sub(
        r"归属于上市公司股东的净利润|归属于上市公司股东|归母净利润|归母净利",
        " ", question or "")
    tips: list[str] = []
    as_of = bool(re.search(r"截至|报告期末|期末持股|持股比例|持股数量", q))
    shareholder = bool(re.search(
        r"第一大股东|控股股东|实际控制人|十大股东|股东是谁|股东持股",
        q))
    event = bool(re.search(r"异动|异常波动", q))
    event_window = bool(re.search(
        r"连续\s*\d+\s*个?交易日|连续\s*\d+\s*日|\d+\s*月\s*\d+\s*日", q))

    if event:
        if not event_window and not has_period:
            tips.append(
                "时点类型未锁定「异动事件窗」：请补连续几个交易日或起止日期，"
                "勿默认最近一次")
        return "event_window", tips

    if shareholder or as_of:
        if not as_of and not re.search(r"报告期末|期末", q):
            tips.append(
                "时点类型未锁定「时点快照」：请补截至哪一报告期期末"
                "（如截至2024年半年度报告期末）")
        return "as_of", tips

    if metrics:
        return ("period" if has_period else None), tips
    if has_period:
        return "period", tips
    return None, tips


def _scheme_round_tips(question: str) -> list[str]:
    """多轮回购/增发：未指明哪一次则澄清。"""
    q = question or ""
    if not re.search(r"回购", q):
        return []
    if re.search(r"第一|第二|两轮|多轮|几轮|分别|有何不同|有什么不同|"
                 r"按披露|对比|比较|前次|本次|上一轮|下一轮|"
                 r"3\s*月|10\s*月|2024\s*年\s*3|2024\s*年\s*10", q):
        return []
    return ["方案轮次未锁定：资料含多轮回购时请指明哪一次"
            "（如2024年3月或2024年10月方案），或说明要对比两轮"]


_ORG_SUFFIX = r"(?:股份有限公司|有限责任公司|有限公司)"
_NAMED_ORG = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]{2,30}?" + _ORG_SUFFIX)
_ISSUER = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]{4,40}?股份有限公司")
_SUBSIDIARY_ASK = re.compile(r"子公司|参股公司|合营公司|联营公司")
# 分配性量词：题面已要求「多家都看」，不再因案卷多主体逼用户点名一家。
# 不裸匹配「各/全部/所有」，避免「各方面」「各项指标」误放行。
_DISTRIBUTIVE_SUBJECT = re.compile(
    r"各(?:个)?客户|各(?:个)?项目|各家|每一家|每一客户|"
    r"每个客户|每个项目|分别|逐一|"
    r"(?:全部|所有)(?:客户|项目|主体)"
)


def _distributive_subject(question: str) -> bool:
    return bool(_DISTRIBUTIVE_SUBJECT.search(question or ""))


def _subject_tips(question: str, dossier: Dossier | None) -> list[str]:
    """主体未点名：只说「子公司」，或多家上市公司却只说「公司」。

    单一发行人公告里的「公司/本公司」不澄清——那就是这家上市公司。
    题面含分配性量词（各客户/分别/…）时，多家主体改为披露，不进澄清。
    """
    q = question or ""
    tips: list[str] = []
    named = _named_orgs(q)
    if _SUBSIDIARY_ASK.search(q) and not named:
        tips.append(
            "对象主体未锁定「子公司」：请写出子公司全称，"
            "勿默认合并报表或任意一家")
    issuers = _issuers_in_dossier(dossier)
    if (len(issuers) >= 2 and not _question_locks_issuer(q, issuers)
            and not _distributive_subject(q)):
        shown = "、".join(issuers[:3])
        tips.append(
            f"对象主体未锁定：资料中有多家股份公司（{shown}），"
            "请写明是哪一家，勿默认其中一家")
    return tips


def _subject_disclosures(question: str, dossier: Dossier | None) -> list[str]:
    """分配性多主体：不早退，只披露本次是整卷多主体研判。"""
    q = question or ""
    if not _distributive_subject(q):
        return []
    issuers = _issuers_in_dossier(dossier)
    if len(issuers) < 2 or _question_locks_issuer(q, issuers):
        return []
    return ["本次为多主体整卷研判，未逐一分卷"]


def _named_orgs(text: str) -> list[str]:
    return _collapse_orgs(_NAMED_ORG.findall(text or ""))


def _issuers_in_dossier(dossier: Dossier | None) -> list[str]:
    if dossier is None:
        return []
    blob = []
    for src in dossier.sources:
        blob.append(str(getattr(src, "title", "") or ""))
        blob.append(str((getattr(src, "meta", None) or {}).get("file") or ""))
        for seg in src.segments:
            blob.append(seg.text or "")
    return _collapse_orgs(_ISSUER.findall("\n".join(blob)))


def _collapse_orgs(names: list[str]) -> list[str]:
    """去掉被更长名称包含的短名，保序去重。"""
    raw: list[str] = []
    for name in names:
        name = re.sub(r"\s+", "", name)
        name = re.sub(r"^[与和及或、]", "", name)
        if name and name not in raw:
            raw.append(name)
    kept: list[str] = []
    for name in raw:
        if any(name != other and name in other for other in raw):
            continue
        kept.append(name)
    return kept


def _question_locks_issuer(question: str, issuers: list[str]) -> bool:
    """问句点到其中一家的全称，或点到其字号里连续 4 字。"""
    q = re.sub(r"\s+", "", question or "")
    hits = []
    for name in issuers:
        core = name.replace("股份有限公司", "")
        if name in q or (len(core) >= 4 and any(
                core[i:i + 4] in q for i in range(len(core) - 3))):
            hits.append(name)
    return len(hits) == 1


def _answered_by_conclusions(dossier: Dossier, metric: dict, slot: dict) -> bool:
    """多数结论是否已答出所问期间×指标（须含同年份，禁止跨年冒充）。"""
    from app.core.conflicts import majority_conclusions

    year = str(slot["year"])
    grain = slot["grain"]
    for con in majority_conclusions(dossier):
        st = con.statement or ""
        if year not in st or "资料不足" in st:
            continue
        if not any(a in st for a in metric["aliases"]):
            continue
        if not re.search(r"\d", st):
            continue
        compact = re.sub(r"\s+", "", st)
        if grain == "h1":
            if "半年度" not in compact and "上半年" not in compact:
                continue
        elif grain == "fy":
            # 同年仅半年度、无全年/年度 → 不算答了全年
            if (("半年度" in compact or "上半年" in compact)
                    and "全年" not in compact and "年度" not in compact):
                continue
        elif grain.startswith("q"):
            marker = {"q1": "一季度", "q2": "二季度",
                      "q3": "三季度", "q4": "四季度"}.get(grain, "")
            if marker and marker not in compact:
                continue
        return True
    return False


def _has_absolute_amount(text: str) -> bool:
    """是否含金额绝对值（元/千分位），而不是只报同比百分比。"""
    t = text or ""
    if "资料不足" in t:
        return False
    if re.search(r"\d[\d,]*\.?\d*\s*元", t):
        return True
    if re.search(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        return True
    return False


def _metric_absolute_in_text(text: str, metric: dict) -> bool:
    """指标别名附近是否出现金额绝对值（避免营收金额误算作净利已覆盖）。"""
    t = text or ""
    for alias in metric["aliases"]:
        start = 0
        while True:
            i = t.find(alias, start)
            if i < 0:
                break
            window = t[max(0, i - 8): i + len(alias) + 48]
            if _has_absolute_amount(window):
                return True
            start = i + len(alias)
    return False


def _headline_misses_covered_amounts(
        dossier: Dossier, headline: str, covered: list[dict]) -> bool:
    """标题是否漏掉已覆盖槽位的绝对值（有结论可补时才算漏）。"""
    for slot in covered:
        metric = next(m for m in _METRICS if m["id"] == slot["metric_id"])
        if _metric_absolute_in_text(headline, metric):
            continue
        if _best_absolute_conclusion(dossier, metric, slot) is not None:
            return True
    return False


def _best_absolute_conclusion(dossier: Dossier, metric: dict, slot: dict):
    """多数结论里最适合充当该槽位绝对值答案的一条。"""
    from app.core.conflicts import majority_conclusions

    year = str(slot["year"])
    grain = slot["grain"]
    grain_cn = slot.get("grain_cn") or _GRAIN_CN.get(grain, "")
    cands = []
    for con in majority_conclusions(dossier):
        st = con.statement or ""
        if year not in st or "资料不足" in st:
            continue
        if not any(a in st for a in metric["aliases"]):
            continue
        if not _has_absolute_amount(st):
            continue
        # 纯同比句（有%无金额）已在 _has_absolute_amount 排除
        if grain == "h1" and "半年度" not in st and "上半年" not in st:
            continue
        if grain == "fy" and "半年度" in re.sub(r"\s+", "", st) \
                and "全年" not in st and "年度" not in st:
            continue
        # 同比句即使带了金额也不优先（如「下降28.05%至x元」少见）
        yoy_only = bool(re.search(r"同比|较上年同期", st)) and not re.search(
            r"实现|为|达到", st)
        score = (
            0 if yoy_only else 1,
            1 if grain_cn and grain_cn in st else 0,
            con.confidence,
        )
        cands.append((score, con))
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0][0], x[0][1], x[0][2], x[1].id),
               reverse=True)
    return cands[0][1]


def _headline_from_majors(dossier: Dossier,
                          covered: list[dict] | None = None) -> str:
    from app.core.conflicts import majority_conclusions

    parts: list[str] = []
    used: set[str] = set()
    # 1) 每个已覆盖槽位优先抬一条绝对值结论
    for slot in covered or []:
        metric = next(m for m in _METRICS if m["id"] == slot["metric_id"])
        con = _best_absolute_conclusion(dossier, metric, slot)
        if con is None or con.id in used:
            continue
        st = _compact_for_headline(con.statement or "")
        if st:
            parts.append(st)
            used.add(con.id)
    # 2) 议题问了同比：再补一条同比句（若还没有）
    q = dossier.question or ""
    joined = "；".join(parts)
    if re.search(r"同比", q) and not re.search(r"同比|较上年", joined):
        for con in sorted(majority_conclusions(dossier),
                          key=lambda c: (-c.confidence, c.id)):
            if con.id in used:
                continue
            st = con.statement or ""
            if re.search(r"同比|较上年同期", st) and re.search(r"\d", st) \
                    and "资料不足" not in st:
                parts.append(_compact_for_headline(st))
                used.add(con.id)
                break
    if not parts:
        majors = sorted(majority_conclusions(dossier),
                        key=lambda c: (-c.confidence, c.id))
        for c in majors:
            st = _compact_for_headline(c.statement or "")
            if st and "资料不足" not in st:
                parts.append(st)
            if len("；".join(parts)) >= 70:
                break
        if not parts and majors:
            parts = [_compact_for_headline(majors[0].statement or "")]
    text = "；".join(p for p in parts if p)
    # 多槽位标题允许稍长；仍截断防撑破版式
    limit = 120 if len(parts) >= 2 else 80
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _compact_for_headline(statement: str) -> str:
    """压短结论句，便于多指标挤进标题。"""
    s = (statement or "").strip().rstrip("。；;")
    s = s.replace("归属于上市公司股东的净利润", "归母净利润")
    s = s.replace("，公司实现", "").replace("公司实现", "")
    s = re.sub(r"，公司", "", s)
    s = s.replace("较上年同期下降", "同比下降")
    s = s.replace("较上年同期增长", "同比增长")
    return s


def _question_period(question: str) -> tuple[int, str] | None:
    matches = list(_Q_PERIOD.finditer(question or ""))
    if not matches:
        return None
    chosen = next((m for m in matches if m.group(2)), matches[0])
    grain = _GRAIN.get(chosen.group(2) or "", "fy")
    return int(chosen.group(1)), grain


def _observations(dossier: Dossier, metric: dict) -> list[dict]:
    found: list[dict] = []
    for src in dossier.sources:
        for seg in src.segments:
            text = seg.text or ""
            for alias in metric["aliases"]:
                start = 0
                while True:
                    i = text.find(alias, start)
                    if i < 0:
                        break
                    window = text[max(0, i - 80): i + len(alias) + 40]
                    local: list[tuple[int, str]] = []
                    for m in _OBS.finditer(window):
                        if m.group(1):
                            local.append((int(m.group(1)), _GRAIN[m.group(2)]))
                        else:
                            local.append((int(m.group(3)), "fy"))
                    # 表内常只写「本报告期」：期间记在文件名/文首，数字紧跟指标
                    if not local and _number_follows(text, i + len(alias)):
                        local = _source_periods(src)
                    for year, grain in local:
                        found.append({
                            "year": year, "grain": grain,
                            "seg_id": seg.id, "source_id": src.id,
                        })
                    start = i + len(alias)
    return found


_NUM_AFTER = re.compile(r"^\s*-?\d[\d,]*")
_SRC_H1 = re.compile(r"(20\d{2})\s*年\s*半年度")
_SRC_FY = re.compile(r"(20\d{2})\s*年(?!\s*半年度)\s*年度")


def _number_follows(text: str, pos: int) -> bool:
    return bool(_NUM_AFTER.match(text[pos: pos + 24]))


def _source_periods(src) -> list[tuple[int, str]]:
    """文件名 + 文首声明的报告期（半年度优先于年度，避免「半年度」被看成年度）。"""
    blob = " ".join([
        str(getattr(src, "title", "") or ""),
        str((getattr(src, "meta", None) or {}).get("file") or ""),
        (src.segments[0].text[:240] if getattr(src, "segments", None) else ""),
    ])
    blob = re.sub(r"\s+", "", blob)
    out: list[tuple[int, str]] = []
    for m in _SRC_H1.finditer(blob):
        out.append((int(m.group(1)), "h1"))
    # 去掉半年度片段后再认年度，避免 2024年半年度 误记 fy
    rest = _SRC_H1.sub("", blob)
    for m in _SRC_FY.finditer(rest):
        out.append((int(m.group(1)), "fy"))
    # 去重保序
    seen: set[tuple[int, str]] = set()
    uniq: list[tuple[int, str]] = []
    for item in out:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def _nearest(obs: list[dict], year: int, grain: str) -> dict | None:
    if not obs:
        return None
    ranked = sorted(obs, key=lambda o: (
        0 if o["grain"] == grain else 1,
        abs(o["year"] - year),
        o["seg_id"],
    ))
    top = ranked[0]
    return {"year": top["year"], "grain": top["grain"], "seg_id": top["seg_id"]}


def _uniq(items: list[str]) -> list[str]:
    out: list[str] = []
    for x in items:
        if x not in out:
            out.append(x)
    return out
