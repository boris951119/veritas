"""案卷内同类事件对照台账（零 LLM，C-29 甲形状）。

只做横向对照：同一主体／指标在本案卷里出现两波及以上不同数值／时点时，
产出可逐字定位的对照行。不加权重、不注入提示词、不接外部案例库。

与 fact_ledger 的分家：那张只管「同期数字打架」；本模块管「跨波次对照」。
与置信度的分家：外部先验只亮黄灯＋节内标注「不计入置信度」，不进四分量。

展示层（C-29 第二轮 R1）：台账全量生成；报告节双上限取更严者
（PRECEDENT_RENDER_CAP 行 ＋ 本节字数 ≤ 其余节合计的 1/3），截断走
build_precedent_ledger 末尾既有确定性排序的前缀。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.core.bm25 import rank_segments
from app.core.citation_check import check_quote
from app.core.evidence import Dossier
from app.core.fact_ledger import Fact, extract_facts
from app.core.numeric_check import extract_nums
from app.core.temporal_check import source_date

# 比较性措辞：结论里带着这些词 + 案卷外数字 ⇒ 外部先验黄灯
_COMPARE_HINTS = (
    "上次", "上一波", "上一轮", "同类", "此前", "往年", "历史",
    "类似事件", "对照", "先例", "那次", "上一次",
)

EXTERNAL_PRIOR_KIND = "external_prior"
EXTERNAL_PRIOR_LINE = (
    "外部先验，未与本案卷核对，不计入置信度"
)
EMPTY_LEDGER_LINE = "案卷内无可对照的早期同类事件"
OUT_OF_WINDOW_NOTE = "该段本次未进入模型视野"
WINDOW_UNKNOWN_NOTE = "未核对是否进窗"
TIME_UNSORTABLE_REASON = "时点不明，未据此排序"

# 展示双上限（两闸取更严者）；台账全量不受此限
PRECEDENT_RENDER_CAP = 24


@dataclass
class PrecedentRow:
    """一行对照：两端都必须能被 citation_check 逐字定位。"""

    current_doc_id: str
    current_para_id: str
    current_quote: str
    prior_doc_id: str
    prior_para_id: str
    prior_quote: str
    diff_kind: str          # 数字 / 时点 / 持续时长 / 收场
    diff_desc: str
    metric: str = ""
    current_entity: str = ""
    prior_entity: str = ""
    prior_window: str = WINDOW_UNKNOWN_NOTE  # 进窗标注文案
    time_sorted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PrecedentLedger:
    rows: list[PrecedentRow] = field(default_factory=list)
    time_sortable: bool = True   # False ⇒ 有对照但缺时点，未按时间排
    n_external_prior: int = 0

    def to_dict(self) -> dict:
        return {
            "rows": [r.to_dict() for r in self.rows],
            "time_sortable": self.time_sortable,
            "n_external_prior": self.n_external_prior,
            "n_rows": len(self.rows),
        }


def _seg_by_id(dossier: Dossier, seg_id: str):
    for src in dossier.sources:
        for seg in src.segments:
            if seg.id == seg_id:
                return src, seg
    return None, None


def _quote_around(text: str, raw: str, radius: int = 24) -> str:
    """从段落里切一段含 raw 的短引文；切不到就退回含 raw 的整句切片。"""
    idx = text.find(raw)
    if idx < 0:
        # 容错：去空白后再找原始切片
        return (text.strip()[:80] if raw in text.replace(" ", "") else raw)
    start = max(0, idx - radius)
    end = min(len(text), idx + len(raw) + radius)
    quote = text[start:end].strip()
    return quote or raw


def _locatable(quote: str, seg_text: str) -> bool:
    return bool(quote) and check_quote(quote, seg_text).ok


def _window_note(dossier: Dossier, para_id: str) -> str:
    acc = dossier.accounting or {}
    if "material_pack_selected" not in acc:
        return WINDOW_UNKNOWN_NOTE
    selected = set(acc.get("material_pack_selected") or [])
    if para_id not in selected:
        return OUT_OF_WINDOW_NOTE
    return ""


def _diff_kind(a: Fact, b: Fact) -> tuple[str, str]:
    """差异类型与描述（确定性：只看数值／时点）。"""
    if a.date and b.date and a.date != b.date and abs(a.value - b.value) <= 1e-9:
        return "时点", f"同值 {a.raw}，时点 {a.date} ↔ {b.date}"
    if abs(a.value - b.value) > 1e-9:
        return "数字", f"{a.raw} ↔ {b.raw}"
    if a.date != b.date:
        return "时点", f"时点 {a.date or '（缺）'} ↔ {b.date or '（缺）'}"
    return "收场", f"表述对照 {a.raw}／{b.raw}"


def _order_pair(fa: Fact, fb: Fact) -> tuple[Fact, Fact, bool]:
    """返回 (current=较新, prior=较早, time_sorted)。缺任一时点 ⇒ 不按时点排。"""
    if fa.date and fb.date:
        if fa.date >= fb.date:
            return fa, fb, True
        return fb, fa, True
    # 时点不明：按 seg_id 稳序钉死，显式标记未按时点排
    if fa.seg_id <= fb.seg_id:
        return fa, fb, False
    return fb, fa, False


def _question_anchors(question: str) -> list[str]:
    """议题里 ≥2 字的词片，用作「同一主体／主题」过滤。"""
    stop = {"如何", "怎样", "是否", "什么", "多少", "情况", "评估", "分析", "请问"}
    parts = re.split(r"[的了吗呢吧啊么？?]+", question or "")
    out: list[str] = []
    for part in parts:
        for t in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", part):
            # 剥疑问尾巴
            for s in ("如何", "怎样", "是否", "什么", "多少"):
                if t.endswith(s) and len(t) > len(s):
                    t = t[: -len(s)]
            if t and t not in stop and t not in out:
                out.append(t)
    return out


def _seg_text(dossier: Dossier, seg_id: str) -> str:
    _, seg = _seg_by_id(dossier, seg_id)
    return seg.text if seg else ""


def _shares_anchor(text: str, anchors: list[str]) -> bool:
    if not anchors:
        return True
    return any(a in text for a in anchors)


def _candidate_pairs(dossier: Dossier) -> list[tuple[Fact, Fact, bool]]:
    """同指标、且段落都咬住议题锚的跨波次事实对。

    fact_ledger 的 entity 常被日期前缀拆开（「2024年1月客户B」≠「2025年6月客户B」），
    所以这里按 metric 归并，再用议题锚过滤——不改 fact_ledger 本身。
    BM25 作保底召回（确定性排序），不引入新依赖。
    """
    facts = extract_facts(dossier)
    anchors = _question_anchors(dossier.question or "")
    by_metric: dict[str, list[Fact]] = {}
    for f in facts:
        if not f.metric:
            continue
        blob = (f.entity or "") + _seg_text(dossier, f.seg_id)
        if not _shares_anchor(blob, anchors):
            continue
        by_metric.setdefault(f.metric, []).append(f)

    # BM25 保底：议题高分段若含同指标数字、且尚未进 by_metric，补进来
    if dossier.question:
        ranked = rank_segments(dossier, query=dossier.question)
        top_ids = {sid for sid, score in ranked[:12] if score > 0}
        for f in facts:
            if f.seg_id in top_ids and f.metric:
                by_metric.setdefault(f.metric, [])
                if f not in by_metric[f.metric]:
                    blob = (f.entity or "") + _seg_text(dossier, f.seg_id)
                    if _shares_anchor(blob, anchors):
                        by_metric[f.metric].append(f)

    pairs: list[tuple[Fact, Fact, bool]] = []
    seen: set[tuple[str, str]] = set()
    for group in by_metric.values():
        by_seg: dict[str, Fact] = {}
        for f in group:
            by_seg.setdefault(f.seg_id, f)
        items = list(by_seg.values())
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if abs(a.value - b.value) <= 1e-9 and (a.date or "") == (b.date or ""):
                    continue
                cur, prior, timed = _order_pair(a, b)
                key = (cur.seg_id, prior.seg_id)
                if key in seen or (prior.seg_id, cur.seg_id) in seen:
                    continue
                seen.add(key)
                pairs.append((cur, prior, timed))
    return pairs


def _entity_label(raw: str) -> str:
    text = (raw or "").strip()
    return text if text else "（未指明主体）"


def build_precedent_ledger(dossier: Dossier) -> PrecedentLedger:
    """产台账：定位不到的行不生成（过滤在生成期，不是生成后再罚）。

    ⚠ 定位过滤今日是 belt-and-braces：官方卷上实测触发率≈0（候选对里被摘 0 行）。
    不许对外写成「已验证的过滤能力」；人造故障格见 tests。
    """
    rows: list[PrecedentRow] = []
    any_unsortable = False
    for cur, prior, timed in _candidate_pairs(dossier):
        if not timed:
            any_unsortable = True
        src_c, seg_c = _seg_by_id(dossier, cur.seg_id)
        src_p, seg_p = _seg_by_id(dossier, prior.seg_id)
        if seg_c is None or seg_p is None or src_c is None or src_p is None:
            continue
        q_c = _quote_around(seg_c.text, cur.raw)
        q_p = _quote_around(seg_p.text, prior.raw)
        # 定位不到就不生成（belt-and-braces；生产路径实测几乎不开火）
        if not _locatable(q_c, seg_c.text) or not _locatable(q_p, seg_p.text):
            continue
        kind, desc = _diff_kind(cur, prior)
        rows.append(PrecedentRow(
            current_doc_id=src_c.id,
            current_para_id=seg_c.id,
            current_quote=q_c,
            prior_doc_id=src_p.id,
            prior_para_id=seg_p.id,
            prior_quote=q_p,
            diff_kind=kind,
            diff_desc=desc,
            metric=cur.metric or prior.metric or "",
            current_entity=cur.entity or "",
            prior_entity=prior.entity or "",
            prior_window=_window_note(dossier, seg_p.id),
            time_sorted=timed,
        ))

    # 稳定排序：有时点的按 prior 时点再 current；无时点按 para_id
    def _sort_key(r: PrecedentRow):
        src_p, _ = _seg_by_id(dossier, r.prior_para_id)
        src_c, _ = _seg_by_id(dossier, r.current_para_id)
        d_p = source_date(src_p) if src_p else ""
        d_c = source_date(src_c) if src_c else ""
        if r.time_sorted and d_p and d_c:
            return (0, d_p, d_c, r.prior_para_id, r.current_para_id)
        return (1, r.prior_para_id, r.current_para_id, "", "")

    # 仅当全部行都 time_sorted 才按时点键排；否则保持 id 稳序（不许假装按时间）
    if rows and all(r.time_sorted for r in rows):
        rows.sort(key=_sort_key)
    else:
        rows.sort(key=lambda r: (r.prior_para_id, r.current_para_id))
        if rows:
            any_unsortable = any_unsortable or any(not r.time_sorted for r in rows)

    ext = audit_external_prior(dossier)
    return PrecedentLedger(
        rows=rows,
        time_sortable=not any_unsortable if rows else True,
        n_external_prior=len(ext),
    )


def audit_external_prior(dossier: Dossier) -> list[dict]:
    """结论含比较措辞 + 案卷内无出处的数字 ⇒ 黄灯（不进置信度）。"""
    corpus = " ".join(
        seg.text for src in dossier.sources for seg in src.segments)
    corpus += " " + (dossier.question or "")
    corpus_nums = extract_nums(corpus)
    flags: list[dict] = []
    for con in dossier.conclusions:
        if con.status == "merged":
            continue
        stmt = con.statement or ""
        if not any(h in stmt for h in _COMPARE_HINTS):
            continue
        seen: set[float] = set()
        for n in extract_nums(stmt):
            if n.value in seen:
                continue
            seen.add(n.value)
            if any(abs(c.value - n.value) <= 1e-9 for c in corpus_nums):
                continue
            flags.append({
                "kind": EXTERNAL_PRIOR_KIND,
                "severity": "medium",
                "conclusion_id": con.id,
                "value": n.raw,
                "detail": (
                    f"结论比较句中的数字 {n.raw} 在案卷内无出处"
                    f"（{EXTERNAL_PRIOR_LINE}）"
                ),
            })
    return flags


def precedent_time_sortable(dossier: Dossier) -> bool:
    """GateSpec.has_work：有对照行且两端均可定时点才算「排过」。

    无对照行 ⇒ True（无对象，不宣称未执行时点排序）。
    有对照但任一行缺时点 ⇒ False ⇒ not_evaluated 带 TIME_UNSORTABLE_REASON。
    """
    acc = (dossier.accounting or {}).get("precedent")
    if isinstance(acc, dict) and "time_sortable" in acc:
        if int(acc.get("n_rows") or 0) == 0:
            return True
        return bool(acc.get("time_sortable"))
    ledger = build_precedent_ledger(dossier)
    if not ledger.rows:
        return True
    return ledger.time_sortable


def _format_row_bullet(r: dict | PrecedentRow) -> str:
    """单行展示文案（含指标＋两端主体标签）。"""
    if isinstance(r, PrecedentRow):
        r = r.to_dict()
    metric = (r.get("metric") or "").strip() or "（未指明指标）"
    ent_c = _entity_label(str(r.get("current_entity") or ""))
    ent_p = _entity_label(str(r.get("prior_entity") or ""))
    if ent_c == ent_p:
        subj = f"主体：{ent_c}"
    else:
        subj = f"本案主体：{ent_c}／对照主体：{ent_p}"
    win = (r.get("prior_window") or "").strip()
    win_bit = f"；{win}" if win else ""
    return (
        f"- 指标：{metric}；{subj}；"
        f"本案 `{r.get('current_doc_id')}`/`{r.get('current_para_id')}`"
        f"「{r.get('current_quote')}」"
        f" ↔ 对照 `{r.get('prior_doc_id')}`/`{r.get('prior_para_id')}`"
        f"「{r.get('prior_quote')}」"
        f"——{r.get('diff_kind')}：{r.get('diff_desc')}{win_bit}"
    )


def _truncation_note(n_hidden: int, n_shown: int) -> str:
    """截断披露行；数字来自计数，不许固定串。"""
    return (
        f"- 另有 {n_hidden} 组同类对照未展示"
        f"（本次展示 {n_shown} 组；上限＝{PRECEDENT_RENDER_CAP} 行／其余节字数的 1/3）"
    )


def _select_display_rows(
    rows: list[dict],
    *,
    rest_chars: int,
) -> tuple[list[dict], bool]:
    """双上限取更严者，一次算清：前缀截断（rows 已按台账确定性序排好）。

    返回 (展示行, 是否截断)。至少保 1 行（有行可展时）。
    """
    if not rows:
        return [], False
    max_chars = max(1, int(rest_chars) // 3)
    selected: list[dict] = []
    for r in rows:
        if len(selected) >= PRECEDENT_RENDER_CAP:
            break
        trial = selected + [r]
        # 预估本节：标题＋空行＋各 bullet（截断披露先按「会加」估上界，避免超闸）
        body = ["## 同类事件对照（案卷内）", ""]
        body += [_format_row_bullet(x) for x in trial]
        # 若还会截断，披露行也占字数——用最坏情况估（真实未展示数）
        n_left = len(rows) - len(trial)
        if n_left > 0:
            body.append(_truncation_note(n_left, len(trial)))
        body.append("")
        sec_len = len("\n".join(body))
        if sec_len > max_chars and selected:
            break
        if sec_len > max_chars and not selected:
            selected = [r]  # 至少保 1 行
            break
        selected.append(r)
    truncated = len(selected) < len(rows)
    return selected, truncated


def render_precedent_lines(
    dossier: Dossier,
    *,
    rest_chars: int | None = None,
) -> list[str]:
    """报告「同类事件对照（案卷内）」节的正文行（含标题）。

    rest_chars＝其余各节合计字数（不含本节）；缺省时按「无其余节」退化，
    只走行数上限（夹具／单测常用）。台账 n_rows 仍是全量，本函数只削展示。
    """
    acc = (dossier.accounting or {}).get("precedent")
    if isinstance(acc, dict) and "rows" in acc:
        rows = list(acc.get("rows") or [])
        n_ext = int(acc.get("n_external_prior") or 0)
        n_total = int(acc.get("n_rows") or len(rows))
    else:
        ledger = build_precedent_ledger(dossier)
        rows = [r.to_dict() for r in ledger.rows]
        n_ext = ledger.n_external_prior
        n_total = len(ledger.rows)

    lines = ["## 同类事件对照（案卷内）", ""]
    if not rows:
        lines.append(f"- {EMPTY_LEDGER_LINE}")
    else:
        # rest 缺省：只按行数帽；传入时双闸
        if rest_chars is None:
            rest_chars = 10 ** 12  # 字数闸不起作用
        shown, truncated = _select_display_rows(rows, rest_chars=rest_chars)
        for r in shown:
            lines.append(_format_row_bullet(r))
        if truncated:
            n_hidden = n_total - len(shown)
            lines.append(_truncation_note(n_hidden, len(shown)))
    if n_ext > 0 or any(
        f.get("kind") == EXTERNAL_PRIOR_KIND
        for f in (dossier.accounting or {}).get("audit_flags") or []
    ):
        lines.append(f"- {EXTERNAL_PRIOR_LINE}")
    elif audit_external_prior(dossier):
        lines.append(f"- {EXTERNAL_PRIOR_LINE}")
    lines.append("")
    return lines
