"""检索问句拓展：原问保留；模型按规则补同义/近义问法；词表作兜底。

主路径：有模型时，按硬性约束生成最多 3 条检索变体（同义替换、语序、
指代补全），机械闸丢掉换主体 / 捏造数字日期 / 跑偏变体。
研判议题始终是用户原话，拓展只进 BM25。

`VERITAS_QUERY_REWRITE=0` 关闭模型拓展，词表 expand_query 仍在。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.bm25 import expand_query
from app.core.citation_check import normalize
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
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# 主体名：专名 2–4 字 + 组织后缀（避免「净利润呢南山铝业」整段粘连）
_ORG_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9\-]{1,}|"
    r"([\u4e00-\u9fff]{2,4})(公司|集团|银行|股份|铝业|新材|科技)"
)
_ORG_SCRAP = re.compile(
    r"^(?:别的|其他|其它|净利润|利润|营收|分红|比例|收入|股东)")
# 指标词不算被省略的主语
_METRIC_HINTS = (
    "净利润", "归母", "净利", "利润", "营收", "营业收入", "收入",
    "分红", "股利", "红利", "应收账款", "回款", "停工", "停产",
    "资金链", "流动性", "装机", "利用小时", "改性", "占比", "同比",
)

_EXPAND_SYSTEM = """你是检索问句拓展器。任务：为字面 BM25 生成同义/近义检索问法。
研判议题仍是用户原话；你输出的问句只用于检索，不代替原议题。

硬性限制（违反任一条即无效）：
1. 主体锁定：不得更换、新增、暗示其他公司名/人名/机构名；原问已有的主体必须出现在每条拓展里；
2. 禁止捏造：不得编造原问与上一句都未出现的数字、日期、金额、比例、事件或事实；
3. 禁止张冠李戴：不得把 A 主体的指标/事件安到 B；不得把分红问成营收、把中报改成年报等偷换主题；
4. 只允许：同义词/近义说法（如回款↔应收账款、停工↔停产、营收↔营业收入）、语序微调；
   若提供了上一句且最新句有指代或省略主语，只许用上一句里已有的主体把最新句补全；
5. 最多 3 条，每条不超过 80 字；不要解释、不要 Markdown。

只输出 JSON：{"queries":["拓展问句1","拓展问句2"]}"""


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


def _numbers(text: str) -> set[str]:
    return set(_NUM_RE.findall(text or ""))


def _orgs(text: str) -> list[str]:
    out: list[str] = []
    for m in _ORG_RE.finditer(text or ""):
        if m.lastindex:
            s = m.group(1) + m.group(2)
        else:
            s = m.group(0)
        if _ORG_SCRAP.match(s):
            continue
        if len(s) >= 3 and s not in out:
            out.append(s)
    return out


def _foreign_org(org: str, allowed_orgs: list[str], blob: str) -> bool:
    """候选里的主体是否为原问/上一句未出现的（张冠李戴）。"""
    if not org:
        return False
    if org in blob:
        return False
    for a in allowed_orgs:
        if a and (a in org or org in a):
            return False
    return True


def _overlap_ok(base: str, candidate: str) -> bool:
    a, b = normalize(base), normalize(candidate)
    sh = [a[i:i + 2] for i in range(max(0, len(a) - 1))]
    if not sh:
        return False
    return sum(1 for s in sh if s in b) / len(sh) >= 0.4


def sanitize_variants(original: str, candidates: list[str],
                      prior: str = "") -> list[str]:
    """去重、截断、丢掉换主体/捏造数字；保住主体时可放宽字面重叠。"""
    base = (original or "").strip()
    prev = (prior or "").strip()
    if not base:
        return []
    # 分句抽主体，避免「呢」+「南山铝业」粘成假公司名
    allowed_orgs = list(dict.fromkeys(_orgs(base) + _orgs(prev)))
    blob = f"{base}\n{prev}"
    allowed_nums = _numbers(blob)
    out: list[str] = []
    seen = {base, prev}
    for raw in candidates:
        q = " ".join(str(raw or "").split()).strip()
        if not q or q in seen:
            continue
        if len(q) > _MAX_CHARS:
            q = q[:_MAX_CHARS].rstrip()
        if not q or q in seen:
            continue
        # 捏造数字/日期碎片
        if any(n not in allowed_nums for n in _numbers(q)):
            continue
        # 张冠李戴：候选引入原问/上一句没有的公司/机构名
        if any(_foreign_org(o, allowed_orgs, blob) for o in _orgs(q)):
            continue
        if allowed_orgs:
            # 有主体：必须保住；同义替换不再强制高字面重叠
            if not any(o in q for o in allowed_orgs):
                continue
        else:
            if not _overlap_ok(base, q):
                continue
        seen.add(q)
        out.append(q)
        if len(out) >= _MAX_VARIANTS:
            break
    return out


def sanitize_standalone(latest: str, prior: str, candidate: str) -> str:
    """兼容旧单测：补全一条独立问句的闸。"""
    got = sanitize_variants(latest, [candidate], prior=prior)
    return got[0] if got else ""


def collect_search_queries(original: str,
                           variants: list[str] | None = None,
                           prior: str = "") -> list[str]:
    """BM25 用查询列表：原问（经词表）在前，模型拓展（再经词表）跟上。"""
    base = (original or "").strip()
    if not base:
        return [expand_query("")]
    queries = [expand_query(base)]
    for v in sanitize_variants(base, list(variants or []), prior=prior):
        item = expand_query(v)
        if item not in queries and item != base:
            queries.append(item)
    return queries


def parse_rewrite_payload(data: Any) -> list[str]:
    """从模型 JSON 抽问句列表；兼容旧 {"query":"..."}。"""
    if not isinstance(data, dict):
        return []
    raw = data.get("queries")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    one = data.get("query")
    if isinstance(one, str) and one.strip():
        return [one.strip()]
    return []


def expand_for_retrieval(latest: str, prior: str, client, model: str) -> list[str]:
    """调用模型生成检索拓展；失败返回 []。"""
    q = (latest or "").strip()
    prev = (prior or "").strip()
    if prev == q:
        prev = ""
    if not q or client is None or not (model or "").strip():
        return []
    user = f"最新问题：{q}"
    if prev:
        user = f"上一句：{prev}\n{user}"
        if needs_context(q):
            user += "\n（最新问题不完整：请先用上一句主体补全，再给同义检索问法）"
        else:
            user += "\n（最新问题已完整：只做同义/近义拓展，不要改主体与期间）"
    else:
        user += "\n（无上一句：只做同义/近义拓展；缺主语时不要猜测公司名）"
    try:
        from app.agents.base import extract_json

        resp = client.chat(
            model,
            [
                {"role": "system", "content": _EXPAND_SYSTEM},
                {"role": "user", "content": user},
            ],
            json_mode=True,
        )
        content = getattr(resp, "content", "") or ""
        data = extract_json(content)
        return parse_rewrite_payload(data)
    except Exception:
        return []


def rewrite_standalone(latest: str, prior: str, client, model: str) -> str:
    """兼容旧接口：不完整+上一句时，取第一条通过闸的拓展。"""
    q = (latest or "").strip()
    prev = (prior or "").strip()
    if not q or not prev or not needs_context(q):
        return ""
    got = sanitize_variants(
        q, expand_for_retrieval(q, prev, client, model), prior=prev)
    return got[0] if got else ""


def prepare_search_info(latest: str, *, prior: str = "", client=None,
                        model: str = "", enabled: bool = True) -> dict:
    """检索账本：模型同义拓展（有约束）+ 词表兜底；原议题不替换。"""
    original = (latest or "").strip()
    prev = (prior or "").strip()
    if prev == original:
        prev = ""
    variants: list[str] = []
    reason = ""
    if not enabled or not original:
        status = "disabled"
    elif client is None or not (model or "").strip():
        status = "fallback"
        reason = "no_model"
    else:
        raw = expand_for_retrieval(original, prev, client, model)
        variants = sanitize_variants(original, raw, prior=prev)
        if variants:
            status = "ok"
            reason = ("clarified_expand" if (prev and needs_context(original))
                      else "expand")
        else:
            status = "fallback"
            reason = "rejected" if raw else "empty"
    queries = collect_search_queries(original, variants, prior=prev)
    if variants:
        shown = "；".join(variants[:2])
        more = f" 等{len(variants)}条" if len(variants) > 2 else ""
        note = f"检索另用模型同义拓展「{shown}」{more}（未替换原议题；已过主体/数字闸）"
    elif status == "fallback":
        note = "模型拓展未采用，检索仍用原问加词表"
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
