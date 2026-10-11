"""检索问句：原问 + 词表同义词始终在。

模型只做一件事：最新一句不完整（指代、省略主语或宾语），并且有上一句可对照时，
补成一条独立问句，追加进检索。研判议题仍是用户原话。
完整问句、或没有上一句时，不调用模型，也不猜主语。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.bm25 import expand_query
from app.core.premise_check import extract_entities

_MAX_CHARS = 80
_MAX_VARIANTS = 3

# 指代：避开「其他 / 其它 / 应该」里的字
_PRONOUN_RE = re.compile(
    r"这个|那个|这些|那些|此处|它们|他们|她们|"
    r"(?<!其)[他她它]|(?<!应)该|"
    r"其(?!他|它|中|实|余|次|后|间)"
)
_FOLLOWUP_RE = re.compile(r"^(那|还有|再|同样|继续)")
# 指标词不算被省略的主语
_METRIC_HINTS = (
    "净利润", "归母", "净利", "利润", "营收", "营业收入", "收入",
    "分红", "股利", "红利", "应收账款", "回款", "停工", "停产",
    "资金链", "流动性", "装机", "利用小时", "改性", "占比", "同比",
)

_REWRITE_SYSTEM = """你是检索问句补全器。根据「上一句」，把「最新问题」改写成一条独立、完整、明确的中文问句，只用于检索。
硬性限制：
1. 只补充上一句里已经出现、而最新问题省略的主语或宾语；解开「它/这个/该/其」等指代；
2. 保持最新问题的意图，不把上一句的指标换成别的指标；
3. 不编造上一句和最新问题都没有的公司名、人名、数字或日期；
4. 只输出一条，不超过 80 字，不要解释。
只输出 JSON：{"query":"补全后的问句"}"""


def needs_context(question: str) -> bool:
    """最新一句是否还不完整：指代、追问省略，或只有指标没有对象。"""
    q = (question or "").strip()
    if not q:
        return False
    if _PRONOUN_RE.search(q):
        return True
    if q.endswith("呢") or q.endswith("呢？") or q.endswith("呢?"):
        return True
    if _FOLLOWUP_RE.match(q):
        return True
    return not _named_entities(q)


def _named_entities(question: str) -> list[str]:
    """去掉指标词后还剩下的对象。没有就视为省略了主语。"""
    out: list[str] = []
    for ent in extract_entities(question):
        if any(hint in ent for hint in _METRIC_HINTS):
            continue
        if ent not in out:
            out.append(ent)
    return out


def sanitize_variants(original: str, candidates: list[str],
                      prior: str = "") -> list[str]:
    """去重、截断、丢掉跑偏的改写；绝不替换原问。

    有上一句时按补全规则：不新增两边都没有的对象，并保留上一句里的对象。
    没有上一句时仍按与原问的实体或二元重叠过滤（评测用的确定性变体）。
    """
    base = (original or "").strip()
    prev = (prior or "").strip()
    if not base:
        return []
    if prev:
        one = sanitize_standalone(base, prev, candidates[0] if candidates else "")
        return [one] if one else []
    ents = [e for e in extract_entities(base) if e]
    out: list[str] = []
    seen = {base}
    for raw in candidates:
        q = " ".join(str(raw or "").split()).strip()
        if not q or q in seen:
            continue
        if len(q) > _MAX_CHARS:
            q = q[:_MAX_CHARS].rstrip()
        if not q or q in seen:
            continue
        if ents and not any(e in q for e in ents):
            from app.core.citation_check import normalize

            a, b = normalize(base), normalize(q)
            sh = [a[i:i + 2] for i in range(max(0, len(a) - 1))]
            if not sh or sum(1 for s in sh if s in b) / len(sh) < 0.5:
                continue
        seen.add(q)
        out.append(q)
        if len(out) >= _MAX_VARIANTS:
            break
    return out


def _novel_entity(ent: str, allowed: list[str], blob: str) -> bool:
    """连写的「公司+指标」不算新造；剩下的新名字才算跑偏。"""
    if ent in allowed or ent in blob:
        return False
    rest = ent
    for known in sorted(allowed, key=len, reverse=True):
        if known and known in rest:
            rest = rest.replace(known, "")
    rest = rest.strip()
    return len(rest) >= 2 and rest not in blob


def sanitize_standalone(latest: str, prior: str, candidate: str) -> str:
    """补全问句必须能对上上一句的对象，且不新造两边都没有的名字。"""
    q = " ".join(str(candidate or "").split()).strip()
    base = (latest or "").strip()
    prev = (prior or "").strip()
    if not q or not base or not prev:
        return ""
    if len(q) > _MAX_CHARS:
        q = q[:_MAX_CHARS].rstrip()
    if not q or q in (base, prev):
        return ""
    blob = base + prev
    allowed = [e for e in extract_entities(base) + extract_entities(prev) if e]
    for ent in extract_entities(q):
        if _novel_entity(ent, allowed, blob):
            return ""
    prior_ents = [e for e in extract_entities(prev) if e]
    if prior_ents and not any(e in q for e in prior_ents):
        return ""
    latest_ents = [e for e in extract_entities(base)
                   if e and not _PRONOUN_RE.fullmatch(e)]
    if latest_ents and not any(e in q for e in latest_ents):
        return ""
    return q


def collect_search_queries(original: str,
                           variants: list[str] | None = None,
                           prior: str = "") -> list[str]:
    """BM25 用查询列表：原问（经词表扩展）在前，补全问句跟上。"""
    base = (original or "").strip()
    if not base:
        return [expand_query("")]
    queries = [expand_query(base)]
    for v in sanitize_variants(base, list(variants or []), prior=prior):
        # 补全问句同样走词表；评测用的确定性变体保持原样
        item = expand_query(v) if prior else v
        if item not in queries and item != base:
            queries.append(item)
    return queries


def parse_rewrite_payload(data: Any) -> list[str]:
    """从模型 JSON 抽问句。补全格式是 {"query":"..."}，兼容旧的 queries 列表。"""
    if not isinstance(data, dict):
        return []
    one = data.get("query")
    if isinstance(one, str) and one.strip():
        return [one.strip()]
    raw = data.get("queries")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if str(x).strip()]


def rewrite_standalone(latest: str, prior: str, client, model: str) -> str:
    """把最新一句补成独立问句。失败或不该改时返回空串。"""
    q = (latest or "").strip()
    prev = (prior or "").strip()
    if not q or not prev or prev == q or client is None or not (model or "").strip():
        return ""
    if not needs_context(q):
        return ""
    try:
        from app.agents.base import extract_json

        resp = client.chat(
            model,
            [
                {"role": "system", "content": _REWRITE_SYSTEM},
                {"role": "user", "content": f"上一句：{prev}\n最新问题：{q}"},
            ],
            json_mode=True,
        )
        content = getattr(resp, "content", "") or ""
        data = extract_json(content)
        got = parse_rewrite_payload(data)
        return sanitize_standalone(q, prev, got[0] if got else "")
    except Exception:
        return ""


def prepare_search_info(latest: str, *, prior: str = "", client=None,
                        model: str = "", enabled: bool = True) -> dict:
    """检索账本。不完整且有上一句才调用模型；否则只用原问加词表。"""
    original = (latest or "").strip()
    prev = (prior or "").strip()
    if prev == original:
        prev = ""
    variants: list[str] = []
    reason = ""
    if not enabled or not original:
        status = "disabled"
    elif not needs_context(original):
        status = "skipped"
        reason = "complete"
    elif not prev:
        status = "skipped"
        reason = "no_prior"
    elif client is None or not (model or "").strip():
        status = "fallback"
        reason = "no_model"
    else:
        clarified = rewrite_standalone(original, prev, client, model)
        if clarified:
            variants = [clarified]
            status = "ok"
            reason = "clarified"
        else:
            status = "fallback"
            reason = "rejected"
    queries = collect_search_queries(original, variants, prior=prev)
    if variants:
        note = f"检索另用补全问句「{variants[0]}」（未替换原议题）"
    elif status == "fallback":
        note = "问句不完整，补全未采用，检索仍用原问加词表"
    else:
        note = ""
    return {
        "kind": "query_rewrite",
        "status": status,
        "reason": reason,
        "original": original,
        "prior": prev,
        "variants": variants,
        "queries": queries,
        "n_queries": len(queries),
        "note": note,
    }


def prior_question(latest: str, case_dir: Path | None, *,
                   skip_dir: Path | None = None) -> str:
    """上一句：最近一次不同的历史议题，否则用案例清单里的原议题。"""
    latest_q = (latest or "").strip()
    if case_dir is None:
        return ""
    case_dir = Path(case_dir)
    for old in _history_questions(case_dir, skip_dir):
        if old and old != latest_q:
            return old
    manifest = case_dir / "manifest.yaml"
    if not manifest.is_file():
        return ""
    from app.ingest.case_loader import peek_case_question

    stored = peek_case_question(case_dir).strip()
    if stored and stored != latest_q and stored != case_dir.name:
        return stored
    return ""


def _history_questions(case_dir: Path, skip_dir: Path | None) -> list[str]:
    hist = case_dir / "history"
    if not hist.is_dir():
        return []
    skip = _resolve(skip_dir) if skip_dir is not None else None
    reports: list[Path] = []
    for slot in hist.iterdir():
        if not slot.is_dir():
            continue
        if skip is not None and _resolve(slot) == skip:
            continue
        report = slot / "report.json"
        if report.is_file():
            reports.append(report)
    reports.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[str] = []
    for report in reports[:8]:
        q = _peek_question_head(report)
        if q:
            out.append(q)
    return out


def _resolve(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def _peek_question_head(report: Path) -> str:
    try:
        head = report.read_text(encoding="utf-8")[:4096]
    except OSError:
        return ""
    match = re.search(r'"question"\s*:\s*"(.*?)"', head)
    if not match:
        return ""
    try:
        return json.loads(f'"{match.group(1)}"').strip()
    except json.JSONDecodeError:
        return ""


def apply_query_rewrite(dossier, client, model: str, *,
                        enabled: bool = True, prior: str = "") -> dict:
    """写入 dossier.accounting['query_rewrite']，返回同一字典。"""
    info = prepare_search_info(
        dossier.question, prior=prior, client=client, model=model,
        enabled=enabled,
    )
    dossier.accounting["query_rewrite"] = info
    return info
