"""R14 切片维。身份／履历词来自 case_lexicon，不写案情专名。

编制身份：问句激活 post 族时，正文命中身份同义。
履历噪声：案情配置里的履历强词（可选；无配置则为 0）。
"""

from __future__ import annotations

from typing import Any

from app.kg_lab.case_lexicon import CaseLexicon, lexicon_for_question

SLICE_DIMS: tuple[str, ...] = ("identity_synonym", "resume_noise", "identity_resume")


def _body(text: str) -> str:
    lines = []
    for line in (text or "").replace("\r", "").split("\n"):
        raw = line.strip()
        if not raw or "原标题" in raw:
            continue
        lines.append(raw)
    return "\n".join(lines)


def identity_synonym(question: str, text: str, lex: CaseLexicon | None = None) -> float:
    if lex is None:
        lex = lexicon_for_question(question)
    if "post" not in lex.active_families:
        return 0.0
    body = _body(text)
    terms = lex.identity_synonyms or lex.family_frames.get("post") or ()
    return 1.0 if any(t in body for t in terms) else 0.0


def resume_noise(text: str, lex: CaseLexicon | None = None) -> float:
    """履历噪声只来自案情配置；没有配置就不打。"""
    if lex is None or not lex.resume_noise:
        return 0.0
    body = _body(text)
    return 1.0 if any(t in body for t in lex.resume_noise) else 0.0


def identity_resume(question: str, text: str, lex: CaseLexicon | None = None) -> float:
    if identity_synonym(question, text, lex) and resume_noise(text, lex):
        return 1.0
    return 0.0


def apply_slice_dims(
    feats: dict[str, dict[str, float]],
    metas: dict[str, dict[str, Any]],
    question: str,
    lex: CaseLexicon | None = None,
) -> None:
    if lex is None:
        lex = lexicon_for_question(question)
    for pid, meta in metas.items():
        text = str(meta.get("text") or "")
        feat = feats.setdefault(pid, {})
        feat["identity_synonym"] = identity_synonym(question, text, lex)
        feat["resume_noise"] = resume_noise(text, lex)
        feat["identity_resume"] = identity_resume(question, text, lex)
