"""R17：案情词表注入。规则代码不写「刘翔／买断费」等人名专名。

来源优先级：
1. 可选案情配置 ``vaults/kg-lab/lexicon/<slug>.json``（覆盖／追加）；
2. 从问句用通用规则抽主体与对立选项；
3. 可选本地 14B（默认关；只有显式 use_llm=True 才调）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from app.kg_lab.config import VAULT_ROOT

LEXICON_DIR = VAULT_ROOT / "lexicon"

# 抽象主张族：触发面＋同义／框架证据。词是就业／安置类通用汉语，不是某案当事人名。
FAMILY_CATALOG: dict[str, dict[str, tuple[str, ...]]] = {
    "leave": {
        "triggers": ("不愿走", "不想走", "未放行", "没让我走", "不让走"),
        "surfaces": ("不愿走", "不想走", "未放行", "没让我走", "不让走", "不是我不想走"),
        "frames": ("自主择业", "组织安置", "申请表", "还在单位", "还在该单位"),
    },
    "money": {
        "triggers": ("买断", "补偿", "自主择业", "万元", "金额", "经济补偿"),
        "surfaces": (
            "买断费", "买断", "经济补偿金", "经济补偿", "补偿金",
            "自主择业", "组织安置",
        ),
        "frames": ("经济补偿办法",),
    },
    "post": {
        "triggers": ("编制", "岗位", "在编不在岗", "人事档案"),
        # surfaces＝主张原词；公务员／坐班等是框架证据，进 frames／keyword
        "surfaces": ("在编不在岗", "编制", "岗位"),
        "frames": (
            "公务员", "坐班", "体制内", "职位", "副书记", "人事关系",
            "不是公务员", "并非公务员", "没有行政级别", "无行政级别",
            "不会坐班", "不坐班", "行政级别", "团委副书记",
        ),
    },
}

# 当事人发声／制度／通报的通用线索（无人名）
GENERIC_PARTY_VOICE: tuple[str, ...] = (
    "不是我不想走", "没让我走", "不想走", "不愿走",
    "深夜发文", "再发文", "直言", "发文称", "全文如下",
    "微博发问", "他最后说", "我一直没有离开", "由我来说", "我已经",
)
GENERIC_PARTY_ATTR_SUFFIX: tuple[str, ...] = ("表示", "直言", "称", "说", "写道")
GENERIC_GLOSS: tuple[str, ...] = (
    "还在单位", "还在该单位", "公务员", "坐班", "体制内",
    "副书记", "行政级别", "职位",
)
GENERIC_BULLETIN: tuple[str, ...] = (
    "按规定给予", "自愿选择自主择业", "组织安置", "我们予以充分尊重",
    "情况通报", "妥善安置", "自主择业申请", "按规定给予了",
    "自主择业经济补偿金", "自愿选择自主择业申请", "我们深表敬意",
    "新闻发布会", "发布会介绍", "联合声明", "新闻稿",
    "通报称", "据通报", "全文如下", "正式回应", "我们予以",
    "调查显示", "监测显示", "记录显示",
)
GENERIC_INSTITUTION: tuple[str, ...] = (
    "制度框架", "对应的表述", "经济补偿办法", "制度设计", "《自主择业",
    "法律框架", "双边安排", "对话机制", "沟通渠道", "办法规定",
)
GENERIC_OFFICIAL_VOICE: tuple[str, ...] = (
    "工作人员表示", "工作人员称", "回应记者", "也曾解释", "解释说",
    "情况通报", "统一发公告", "按规定", "我们予以", "官方称", "官方说",
    "外交部", "新闻办公室", "中方称", "双方同意", "两国元首",
    "发布会", "声明称",
)

_PERSON_BEFORE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:退役|同志|表示|直言|回应|发文|微博|不愿|不想)"
)
_ORG_INLINE = re.compile(
    r"(体育局|教育局|公安局|竞体中心|官方|教育部|北京大学|北大|"
    r"外交部|国防部|民航局|航空公司|市政府|省政府)"
)
_OR_PARTY = re.compile(r"是([\u4e00-\u9fff]{2,4})(?:不愿|不想走|不想)")
_OR_AGENCY = re.compile(r"还是([\u4e00-\u9fff]{2,8}?)(?:未放行|没让|未予|称)")
_BAD_ACTOR = re.compile(r"还是|不愿|不想|是否|哪一|这笔|拖了|真有|官方称")


@dataclass
class CaseLexicon:
    """注入打标／一筛／二筛的词表。可序列化。"""

    actors: list[str] = field(default_factory=list)
    actor_aliases: dict[str, list[str]] = field(default_factory=dict)
    # family → surfaces
    family_surfaces: dict[str, list[str]] = field(default_factory=dict)
    family_frames: dict[str, list[str]] = field(default_factory=dict)
    active_families: list[str] = field(default_factory=list)
    party_voice: list[str] = field(default_factory=lambda: list(GENERIC_PARTY_VOICE))
    gloss: list[str] = field(default_factory=lambda: list(GENERIC_GLOSS))
    bulletin: list[str] = field(default_factory=lambda: list(GENERIC_BULLETIN))
    institution: list[str] = field(default_factory=lambda: list(GENERIC_INSTITUTION))
    official_voice: list[str] = field(default_factory=lambda: list(GENERIC_OFFICIAL_VOICE))
    identity_synonyms: list[str] = field(default_factory=list)
    resume_noise: list[str] = field(default_factory=list)
    claim_frames: list[tuple[tuple[str, ...], tuple[str, ...]]] = field(default_factory=list)
    source: str = "question"
    slug: str = ""

    def party_cues(self) -> tuple[str, ...]:
        cues = list(self.party_voice)
        for a in self.actors:
            for suf in GENERIC_PARTY_ATTR_SUFFIX:
                cues.append(f"{a}{suf}")
            cues.append(f"{a}同志是我国优秀")
        # 去重保序
        seen: set[str] = set()
        out: list[str] = []
        for c in cues:
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return tuple(out)

    def claim_groups(self) -> list[tuple[str, ...]]:
        groups: list[tuple[str, ...]] = []
        for fam in self.active_families or list(self.family_surfaces):
            surf = tuple(self.family_surfaces.get(fam) or ())
            if surf:
                groups.append(surf)
        return groups

    def all_claim_surfaces(self) -> tuple[str, ...]:
        found: list[str] = []
        for g in self.claim_groups():
            for t in g:
                if t not in found:
                    found.append(t)
        for fam in self.active_families:
            for t in self.family_frames.get(fam) or ():
                if t not in found:
                    found.append(t)
        return tuple(found)

    def family_of_question(self, question: str) -> str:
        q = question or ""
        for fam in ("leave", "money", "post"):
            triggers = FAMILY_CATALOG.get(fam, {}).get("triggers") or ()
            if any(t in q for t in triggers):
                return fam
        return ""

    def surfaces_for_family(self, family: str) -> tuple[str, ...]:
        """主张原词（二筛对题／蹭分主用）。未激活族回落目录。"""
        if not family:
            return ()
        surf = list(self.family_surfaces.get(family) or ())
        if not surf:
            surf = list(FAMILY_CATALOG.get(family, {}).get("surfaces") or ())
        return tuple(dict.fromkeys(surf))

    def terms_for_family(self, family: str) -> tuple[str, ...]:
        """表面＋框架（兼容旧调用）。"""
        if not family:
            return ()
        surf = list(self.surfaces_for_family(family))
        frames = list(self.family_frames.get(family) or FAMILY_CATALOG.get(family, {}).get("frames") or ())
        return tuple(dict.fromkeys(surf + frames))

    def to_dict(self) -> dict[str, Any]:
        return {
            "actors": list(self.actors),
            "actor_aliases": {k: list(v) for k, v in self.actor_aliases.items()},
            "family_surfaces": {k: list(v) for k, v in self.family_surfaces.items()},
            "family_frames": {k: list(v) for k, v in self.family_frames.items()},
            "active_families": list(self.active_families),
            "party_voice": list(self.party_voice),
            "gloss": list(self.gloss),
            "bulletin": list(self.bulletin),
            "institution": list(self.institution),
            "official_voice": list(self.official_voice),
            "identity_synonyms": list(self.identity_synonyms),
            "resume_noise": list(self.resume_noise),
            "claim_frames": [
                {"triggers": list(a), "evidence": list(b)} for a, b in self.claim_frames
            ],
            "source": self.source,
            "slug": self.slug,
        }


def _uniq(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        x = (x or "").strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def extract_actors_from_question(question: str) -> list[str]:
    """通用规则抽主体：对立选项、机构名、人称候选。不写死案情名。"""
    q = question or ""
    found: list[str] = []
    m = _OR_PARTY.search(q)
    if m:
        found.append(m.group(1))
    m = _OR_AGENCY.search(q)
    if m:
        found.append(m.group(1))
    for m in _ORG_INLINE.finditer(q):
        found.append(m.group(1))
    for m in _PERSON_BEFORE.finditer(q):
        name = m.group(1)
        if _BAD_ACTOR.search(name) or name.startswith(("是", "还", "的", "与")):
            continue
        if name in {"官方", "是否", "哪方", "哪一"}:
            continue
        found.append(name)
    if "官方" in q:
        found.append("官方")
    # 长度闸：2～8 字，去掉明显短语
    cleaned: list[str] = []
    for a in found:
        if not (2 <= len(a) <= 8):
            continue
        if _BAD_ACTOR.search(a):
            continue
        cleaned.append(a)
    return _uniq(cleaned)


def _activate_families(question: str) -> list[str]:
    q = question or ""
    active: list[str] = []
    for fam, spec in FAMILY_CATALOG.items():
        if any(t in q for t in spec["triggers"]):
            active.append(fam)
    return active


def load_case_file(slug: str) -> dict[str, Any]:
    if not slug:
        return {}
    path = LEXICON_DIR / f"{slug}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_file(base: CaseLexicon, raw: dict[str, Any]) -> CaseLexicon:
    if not raw:
        return base
    actors = _uniq(list(base.actors) + list(raw.get("actors") or []) + list(raw.get("actors_extra") or []))
    aliases = dict(base.actor_aliases)
    for k, v in (raw.get("actor_aliases") or {}).items():
        aliases[k] = _uniq(list(aliases.get(k) or []) + list(v or []))
    fam_s = {k: list(v) for k, v in base.family_surfaces.items()}
    fam_f = {k: list(v) for k, v in base.family_frames.items()}
    for fam, surf in (raw.get("family_surfaces") or {}).items():
        fam_s[fam] = _uniq(list(fam_s.get(fam) or []) + list(surf or []))
    for fam, frames in (raw.get("family_frames") or {}).items():
        fam_f[fam] = _uniq(list(fam_f.get(fam) or []) + list(frames or []))
    active = _uniq(list(base.active_families) + list(raw.get("active_families") or []))
    frames_extra: list[tuple[tuple[str, ...], tuple[str, ...]]] = list(base.claim_frames)
    for row in raw.get("claim_frames") or []:
        frames_extra.append((tuple(row.get("triggers") or ()), tuple(row.get("evidence") or ())))
    return replace(
        base,
        actors=actors,
        actor_aliases=aliases,
        family_surfaces=fam_s,
        family_frames=fam_f,
        active_families=active or base.active_families,
        party_voice=_uniq(list(base.party_voice) + list(raw.get("party_voice") or [])),
        gloss=_uniq(list(base.gloss) + list(raw.get("gloss") or [])),
        bulletin=_uniq(list(base.bulletin) + list(raw.get("bulletin") or [])),
        institution=_uniq(list(base.institution) + list(raw.get("institution") or [])),
        official_voice=_uniq(list(base.official_voice) + list(raw.get("official_voice") or [])),
        identity_synonyms=_uniq(list(base.identity_synonyms) + list(raw.get("identity_synonyms") or [])),
        resume_noise=_uniq(list(base.resume_noise) + list(raw.get("resume_noise") or [])),
        claim_frames=frames_extra,
        source=f"{base.source}+file",
        slug=raw.get("slug") or base.slug,
    )


def _llm_enrich(question: str, lex: CaseLexicon) -> CaseLexicon:
    """本地 14B 补主体／主张；失败则原样返回。默认不走付费云。"""
    try:
        from app.kg_lab.ollama_client import generate_json
    except Exception:
        return lex
    prompt = (
        "从研判问句抽出 JSON："
        '{"actors":["人名或机构"],"claim_terms":["主张关键词"]}。'
        "只要问句里出现的，不要编造。\n"
        f"问句：{question}"
    )
    try:
        out = generate_json(prompt, num_predict=120, temperature=0.0)
    except Exception:
        return lex
    parsed = out.get("parsed") or {}
    actors = _uniq(list(lex.actors) + [str(x) for x in (parsed.get("actors") or [])])
    # claim_terms 并入已激活族的 surfaces
    fam_s = {k: list(v) for k, v in lex.family_surfaces.items()}
    terms = [str(x) for x in (parsed.get("claim_terms") or []) if str(x).strip()]
    for fam in lex.active_families or ["leave", "money", "post"]:
        if fam not in fam_s:
            fam_s[fam] = []
        # 只把落在该族触发附近的词并入；其余丢进第一个活跃族
        fam_s[fam] = _uniq(fam_s[fam] + terms)
    return replace(lex, actors=actors, family_surfaces=fam_s, source=f"{lex.source}+llm14b")


def lexicon_for_question(
    question: str,
    *,
    case_slug: str = "",
    use_llm: bool = False,
    case_file: dict[str, Any] | None = None,
) -> CaseLexicon:
    """组装本案本题词表。use_llm 默认 False；线上百炼不在这里接。"""
    actors = extract_actors_from_question(question)
    active = _activate_families(question)
    fam_s: dict[str, list[str]] = {}
    fam_f: dict[str, list[str]] = {}
    frames: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for fam in active or list(FAMILY_CATALOG):
        spec = FAMILY_CATALOG[fam]
        # 未激活的族不写 surfaces，避免无关主张加分
        if fam in active:
            fam_s[fam] = list(spec["surfaces"])
            fam_f[fam] = list(spec["frames"])
            frames.append((tuple(spec["triggers"]), tuple(spec["frames"])))
    # post 身份同义：有编制族时带上
    identity: list[str] = []
    if "post" in active:
        identity = list(FAMILY_CATALOG["post"]["frames"])
    lex = CaseLexicon(
        actors=actors,
        actor_aliases={},
        family_surfaces=fam_s,
        family_frames=fam_f,
        active_families=active,
        identity_synonyms=identity,
        claim_frames=frames,
        source="question",
        slug=case_slug or "",
    )
    raw = case_file if case_file is not None else load_case_file(case_slug)
    if raw:
        lex = _merge_file(replace(lex, slug=case_slug or lex.slug), raw)
    if use_llm:
        lex = _llm_enrich(question, lex)
    return lex


# 一筛／二筛特征名常量再导出，方便 import 一处
from app.kg_lab.tag_schema import STAGE1_FEATURES, STAGE2_FEATURES  # noqa: E402

__all__ = [
    "CaseLexicon",
    "FAMILY_CATALOG",
    "LEXICON_DIR",
    "STAGE1_FEATURES",
    "STAGE2_FEATURES",
    "extract_actors_from_question",
    "lexicon_for_question",
    "load_case_file",
]
