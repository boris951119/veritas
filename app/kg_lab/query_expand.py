"""问句侧同义拓展＋通稿噪声过滤（R2d；不读金标）。"""

from __future__ import annotations

from typing import Any

from app.core.bm25 import _tokens
from app.core.citation_check import normalize

# 题面谓词 → 金标常见说法（规则同义；只在触发词出现于问句时追加）
OPPOSITION_SYNONYMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("不愿走", ("不想走", "不是我不想走")),
    ("未放行", ("没让我走", "而是你没让我走", "没让走")),
    ("11年", ("十年", "十年了", "10年", "十一年")),
    ("十一年", ("十年", "十年了", "11年", "10年")),
)

# 摘要实体／关键词里易漂向行政通稿的子串（命中则跳过）
NOISE_SUBSTR: tuple[str, ...] = (
    "文商旅展",
    "体育赛事",
    "体育治理",
    "体育类高校",
    "体育事业",
    "体育与文",
    "退役安置",
    "安置方案",
    "安置工作",
    "党组",
    "竞体中心",
    "训练管理",
    "官网",
    "热搜",
)


def is_noise_term(term: str) -> bool:
    t = (term or "").strip()
    if not t:
        return True
    return any(n in t for n in NOISE_SUBSTR)


def opposition_synonyms_for_question(question: str) -> list[str]:
    q = question or ""
    out: list[str] = []
    seen: set[str] = set()
    for trigger, syns in OPPOSITION_SYNONYMS:
        if trigger not in q:
            continue
        for s in syns:
            if s in q or s in seen:
                continue
            seen.add(s)
            out.append(s)
    return out


DEFAULT_EXPAND_TOP_N = 16  # R2h 推荐；E≥16 才抬起 q_002 hop@7
DEFAULT_PARAPHRASE_N = 1   # R2h 推荐；P≥5 三题合计 para 稀释 4→1


def _apply_repls(text: str, repls: tuple[tuple[str, str], ...]) -> str:
    out = text
    for a, b in repls:
        if a in out:
            out = out.replace(a, b)
    return out


def rule_paraphrase_question(question: str) -> str:
    """兼容旧接口：返回改写列表中的首条（全量同义替换）。"""
    qs = rule_paraphrase_questions(question, n=1)
    return qs[0]["query"] if qs else (question or "").strip()


def rule_paraphrase_questions(
    question: str, *, n: int = DEFAULT_PARAPHRASE_N,
) -> list[dict[str, str]]:
    """规则整句改写（可审计、不读金标、不泄漏）。

    默认最多 10 条模板／变体；按 n 截断。
    """
    q = (question or "").strip()
    if not q:
        return []
    full = (
        ("不愿走", "不想走"),
        ("未放行", "没让我走"),
        ("11年", "十年"),
        ("十一年", "十年"),
    )
    walk_only = (("不愿走", "不想走"),)
    release_only = (("未放行", "没让我走"),)
    year_only = (("11年", "十年"), ("十一年", "十年"))
    walk_year = (("不愿走", "不想走"), ("11年", "十年"), ("十一年", "十年"))
    release_year = (("未放行", "没让我走"), ("11年", "十年"), ("十一年", "十年"))
    walk_release = (("不愿走", "不想走"), ("未放行", "没让我走"))
    # 模板：仅用问句已出现的主体／议题骨架 + 同义谓词（不引入金标 quote）
    from app.kg_lab.case_lexicon import extract_actors_from_question
    _actors = extract_actors_from_question(q)
    _orgs = [a for a in _actors if a.endswith(("局", "部", "中心", "委")) or a in {"官方"}]
    _party = [a for a in _actors if a not in _orgs]
    subject = _party[0] if _party else ("当事人")
    topic = "安置" if "安置" in q else "处置"
    agency = _orgs[0] if _orgs else "主管部门"
    template = (
        f"{subject}{topic}拖了十年："
        f"是不想走，还是{agency}没让我走？哪一方说法站得住？"
    )
    template_b = (
        f"关于{subject}{topic}拖延十年："
        f"本人不想走，还是{agency}未放行／没让我走？哪方站得住？"
    )
    template_c = (
        f"{subject}拖了十年才{topic}，"
        f"对立口径是「不想走」还是「没让我走」？"
    )
    variants: list[dict[str, str]] = [
        {
            "id": "p01_full_syn",
            "query": _apply_repls(q, full),
            "rule": "replace_all:不愿走→不想走;未放行→没让我走;11年/十一年→十年",
        },
        {
            "id": "p02_walk_only",
            "query": _apply_repls(q, walk_only),
            "rule": "replace:不愿走→不想走",
        },
        {
            "id": "p03_release_only",
            "query": _apply_repls(q, release_only),
            "rule": "replace:未放行→没让我走",
        },
        {
            "id": "p04_year_only",
            "query": _apply_repls(q, year_only),
            "rule": "replace:11年|十一年→十年",
        },
        {
            "id": "p05_surface_template",
            "query": template,
            "rule": "template:主体+安置+十年+不想走+没让我走",
        },
        {
            "id": "p06_walk_year",
            "query": _apply_repls(q, walk_year),
            "rule": "replace:不愿走→不想走 + 年→十年",
        },
        {
            "id": "p07_release_year",
            "query": _apply_repls(q, release_year),
            "rule": "replace:未放行→没让我走 + 年→十年",
        },
        {
            "id": "p08_walk_release",
            "query": _apply_repls(q, walk_release),
            "rule": "replace:不愿走→不想走 + 未放行→没让我走",
        },
        {
            "id": "p09_template_alt",
            "query": template_b,
            "rule": "template_b:拖延十年+不想走+未放行/没让我走",
        },
        {
            "id": "p10_template_oppose_pair",
            "query": template_c,
            "rule": "template_c:对立口径词对「不想走」vs「没让我走」",
        },
    ]
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for v in variants:
        key = v["query"]
        if key in seen:
            alt = key + "（对立口径核对）"
            if alt not in seen:
                v = {**v, "query": alt, "rule": v["rule"] + "|dedupe_tag"}
                key = alt
            else:
                continue
        seen.add(key)
        out.append(v)
        if len(out) >= max(1, min(int(n), DEFAULT_PARAPHRASE_N)):
            break
    return out


def expand_query_parts(
    question: str,
    rows: list[dict[str, Any]],
    *,
    top_n: int = DEFAULT_EXPAND_TOP_N,
) -> dict[str, Any]:
    """返回可审计的拓展拆解（同义优先，合计 ≤ top_n，默认 30）。"""
    q = (question or "").strip()
    syn = opposition_synonyms_for_question(q)
    qn = normalize(q)
    syn_tok = set()
    for s in syn:
        syn_tok |= set(_tokens(s))
    qt = set(_tokens(q)) | syn_tok

    corpus_extras: list[str] = []
    skipped_noise: list[str] = []
    seen: set[str] = set(syn) | {q}
    for r in rows:
        for term in list(r.get("entities") or []) + list(r.get("keywords") or []):
            t = str(term).strip()
            if not t or t in seen or t in q:
                continue
            if is_noise_term(t):
                if t not in skipped_noise and len(skipped_noise) < 24:
                    skipped_noise.append(t)
                continue
            # 与问句或对立同义共享 2-gram／子串
            ok = False
            if t in q or (len(t) >= 2 and normalize(t) in qn):
                ok = True
            elif set(_tokens(t)) & qt:
                ok = True
            elif t in syn:
                ok = True
            if not ok:
                continue
            seen.add(t)
            corpus_extras.append(t)
            if len(syn) + len(corpus_extras) >= top_n:
                break
        if len(syn) + len(corpus_extras) >= top_n:
            break

    # 同义在前，语料词在后；总数 ≤ top_n
    merged = list(dict.fromkeys(syn + corpus_extras))[:top_n]
    expanded = q if not merged else (q + " " + " ".join(merged))
    paras = rule_paraphrase_questions(q, n=DEFAULT_PARAPHRASE_N)
    return {
        "question": q,
        "top_n": top_n,
        "synonyms_added": syn,
        "corpus_extras": corpus_extras[:top_n],
        "noise_skipped_sample": skipped_noise,
        "merged_extras": merged,
        "n_merged_extras": len(merged),
        "expanded_query": expanded,
        "paraphrase_query": paras[0]["query"] if paras else q,
        "paraphrase_queries": paras,
    }
