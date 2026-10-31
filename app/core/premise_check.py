"""议题前提核对器（零 LLM）：问题中的实体在信源零命中时前置亮灯。

「为什么客户B拖欠回款？」——前提「客户B拖欠」若在任何信源中都找不到，
模型顺着框架作答就是在编确认理由。本模块在研判开始前机械核对：从
议题里抽实体候选项（字母数字词 + 中文实义词），任一在全部段落中零
命中即记黄色警示——提示分析师与读者「该前提未被资料覆盖」，回答
须先核前提。纯字符串运算，宁漏勿误（只对高置信零命中最警）。
"""

from __future__ import annotations

import re

from app.core.citation_check import normalize
from app.core.evidence import Dossier
from app.core.warrant_check import _THEME_GROUPS

# 简称 ↔ 年报全称。字面 shingle 会把「归母净利润」判成零命中。
_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("归母净利润", "归母净利", "归属于上市公司股东的净利润"),
)

# 框架词：把议题长句切成实体候选的分隔符（疑问/连接/助词/分析动词）
# 不把「按/后/过/属」当切刀——那是公司搭配字面，会拆掉「按披露口径」等真术语。
_FRAME = re.compile(
    r"的|了|吗|呢|吧|是否|如何|为什么|怎么|什么样|什么|哪些|哪个|哪家|"
    "请|和|与|及|或|对|对于|关于|在|有|无|将|把|被|给|向|从|其|之|该|各|"
    "并|会不会|能不能|是不是|还有|以及|存在|出现|进行|"
    "年前|能否|之后|以后|何时|多久|"
    "多少|几|何|哪|分别|有何|为何|文中|上述|"
    "核查|区分|引用|属于|触及|主营|"
    "分析|评估|研判|总结|概述|判断|说明|给出|列出")
# 超长中文串再切一层，避免 >8 字整段丢弃导致闸静默
_LONG_SPLIT = re.compile(r"的|占|比|金额|情况|及|变化|期内|客户|集中|海外")
# 纯分析框架词与泛指后缀名词，本身不是实体，不参与核对
_GENERIC = {
    "风险", "问题", "情况", "影响", "原因",
    "现状", "进展", "趋势", "背景", "结论", "证据",
    "资料", "材料", "文档", "报告", "公司",
    "整体", "主要", "当前", "未来", "过去", "时间", "数据", "信息",
    "内容", "方面", "是否", "如何", "为什么", "什么", "哪些", "请",
    "第一大股东", "大股东", "股东", "持股", "持股比例", "持股数量",
    "截至", "期末", "报告期末", "半年度报告期末", "报告期",
    "年半年度报告期末", "半年度报告", "年度报告", "年报", "半年报",
    "变化", "占比", "集中度", "用途", "行业", "摘要", "年报摘要",
    "重大事项", "异常波动", "金额区间", "对比", "多久",
}
# 以框架名词收尾的复合词（“交付风险”“回款情况”）不是实体
_GENERIC_SUFFIX = ("风险", "情况", "问题", "影响", "原因", "趋势",
                   "进展", "现状", "背景", "变化")
# 问句尾巴：实体候选上粘着的「是谁/是多少」不是专有名
_QUESTION_TAIL = re.compile(
    r"(是谁|是什么|是多少|有多少|怎么样|如何|为何|为什么|分别是|是)$")
# 语素级疑问残渣（只认疑问素；不做「股派/按披露」等公司搭配）
_RESIDUE = re.compile(
    r"多少|多久|几[类轮个条次]|何|有何|为何|什么|怎么|如何|"
    r"哪[几类个]|分别|文中|上述|不同")
# 报警 token 首尾粘着的语气碎片；「年+真术语」在 _clean_token 另剥
_EDGE_NOISE = re.compile(r"^[的各同]+|[是的各]+$")

_MAX_FLAGS = 5
_MAX_INJECT = 3
_MAX_TOKEN = 8


def extract_entities(question: str) -> list[str]:
    """议题 → 实体候选清单（字母数字词 ≥2 字；中文实义词 2-8 字）。"""
    candidates: list[str] = []
    for latin in re.findall(r"[A-Za-z][A-Za-z0-9\-]+", question):
        candidates.append(latin)
    for run in re.findall(r"[\u4e00-\u9fff]+", question):
        for frag in _FRAME.split(run):
            frag = _QUESTION_TAIL.sub("", frag.strip())
            if not frag:
                continue
            for piece in _pieces(frag):
                token = _clean_token(piece)
                if not (2 <= len(token) <= _MAX_TOKEN) or token in _GENERIC:
                    continue
                if token.endswith(_GENERIC_SUFFIX):
                    continue
                if _is_residue(token) or _is_procedure(token) or _is_date_scrap(token):
                    continue
                candidates.append(token)
    # 去重保序
    seen: set[str] = set()
    return [c for c in candidates
            if not (c in seen or seen.add(c))]


def _pieces(frag: str) -> list[str]:
    """超长串按结构词再切；仍过长则放弃该片，不整题静默。"""
    frag = (frag or "").strip()
    if not frag:
        return []
    if len(frag) <= _MAX_TOKEN:
        return [frag]
    out: list[str] = []
    for sub in _LONG_SPLIT.split(frag):
        sub = sub.strip()
        if not sub:
            continue
        if len(sub) <= _MAX_TOKEN:
            out.append(sub)
        else:
            # 再切一次仍超长：取尾部名词片，避免整段丢掉导致无候选
            out.append(sub[-_MAX_TOKEN:])
    return out


def _clean_token(token: str) -> str:
    token = _EDGE_NOISE.sub("", token or "")
    # 数字/疑问切开后的粘连头：「日恒兴…」「轮股份…」「类产品」
    token = re.sub(r"^[日轮类条次个]+", "", token)
    # 「多久能回款」类疑问头；切开后残留「能回款」再剥情态
    if token.startswith("多久") and len(token) > 2:
        token = token[2:]
    if token.startswith(("能", "会", "要")) and len(token) > 2:
        token = token[1:]
    # 「本公司商誉减值」→ 与覆盖侧 _bare_prefix 对齐
    token = _bare_prefix(token)
    # 「核查后」去时间后缀，剩下「核查」走框架词
    if token.endswith("后") and len(token) > 2:
        token = token[:-1]
    # 「年商誉减值…」去粘连年；「年报/年度」保留。日期碎屑「年披露」后面再滤。
    if (token.startswith("年") and len(token) > 4
            and not token.startswith(("年报", "年度", "半年"))):
        token = token[1:]
    return token


def _is_residue(token: str) -> bool:
    """整词是疑问残渣，或去掉疑问语素后几乎不剩——不用 search 误伤真术语。"""
    t = (token or "").strip()
    if not t:
        return True
    if _RESIDUE.fullmatch(t):
        return True
    stripped = _RESIDUE.sub("", t)
    if len(stripped) < 2:
        return True
    # 「股派多少现金红利」：疑问素在中间的问句碎片
    if re.search(r"多少|什么|怎么|如何|有何|为何", t) and len(t) <= 10:
        return True
    return False


def _is_procedure(token: str) -> bool:
    """问句程序语（按…时间区分 / 应披露未披露），不是可比对实体。"""
    t = token or ""
    if t.startswith("按") and ("时间" in t or t.endswith("区分")):
        return True
    return "应披露未披露" in t


def _is_date_scrap(token: str) -> bool:
    """数字年份切开后的碎屑：年披露、年全年归。"""
    t = token or ""
    if t in ("年报", "年度", "半年报", "全年") or t.startswith(("年报", "年度")):
        return False
    return bool(re.match(r"^年.{0,4}$", t))


def _bare_prefix(token: str) -> str:
    """剥掉「公司/本公司」前缀再做简称桥接。"""
    for p in ("本公司", "本集团", "公司"):
        if token.startswith(p) and len(token) > len(p) + 1:
            return token[len(p):]
    return token


def _covered(token: str, corpus: str) -> bool:
    """实体是否被语料覆盖：外文词整串命中；主题词/简称走共享词表；
    其余中文词按二元 shingle 覆盖率判定（≥60%）。

    双字词的唯一字片就是它自己，「延期」字面不在、但「延迟/进度」在，
    必须靠词表桥接，不能当成资料未覆盖。只亮黄灯，不删结论。"""
    if any(c.isascii() for c in token):
        return token.lower() in corpus.lower()
    if _synonym_covered(token, corpus):
        return True
    shingles = [token[i:i + 2] for i in range(len(token) - 1)]
    if not shingles:
        return token in corpus
    hits = sum(1 for sh in shingles if sh in corpus)
    return hits / len(shingles) >= 0.6


def _synonym_covered(token: str, corpus: str) -> bool:
    """token 落在主题词组或简称组时，组内任一说法出现即算覆盖。"""
    bare = _bare_prefix(token)
    for group in (*_THEME_GROUPS, *_ALIAS_GROUPS):
        in_group = (
            token in group
            or bare in group
            or any(len(t) >= 4 and t in token for t in group)
        )
        if not in_group:
            continue
        if any(term and term in corpus for term in group):
            return True
    return False


def _corpus_text(dossier: Dossier) -> str:
    return normalize("".join(
        seg.text for src in dossier.sources for seg in src.segments))


# 与 answer_slots 股权/时点快照问法对齐：专有名在答里，不在问里。
_TEMPLATE_Q = re.compile(
    r"第一大股东|控股股东|实际控制人|十大股东|股东是谁|股东持股|"
    r"截至.{0,12}报告期末|期末持股|持股比例|持股数量")


def is_template_question(question: str) -> bool:
    """问句模板：无比对专有名，前提闸应免核而非 no_candidates。"""
    q = re.sub(
        r"归属于上市公司股东的净利润|归属于上市公司股东|归母净利润|归母净利",
        " ", question or "")
    return bool(_TEMPLATE_Q.search(q))


def premise_record(dossier: Dossier) -> dict:
    """前提核对账本：已核无缺口 / 有缺口 / 未核 / 免核（模板问句）。

    无信源正文时不得报 checked_ok——以前 flags=[] 会伪装成「已核无缺口」。
    股东/持股模板抽不出实体是预期行为 → exempt_template，勿与漏抽混淆。"""
    entities = extract_entities(dossier.question)
    corpus = _corpus_text(dossier)
    if not entities and is_template_question(dossier.question):
        status = "exempt_template"
        flags: list[dict] = []
    elif not entities:
        status = "no_candidates"
        flags = []
    elif not corpus:
        status = "no_corpus"
        flags = []
    else:
        flags = premise_flags(dossier, entities=entities)
        status = "gaps" if flags else "checked_ok"
    return {
        "kind": "premise",
        "status": status,
        "n_candidates": len(entities),
        "candidates": entities[:12],
        "n_flags": len(flags),
        "flags": flags,
        "note": {
            "no_candidates": "议题前提：未核（议题未抽出可比对实体）",
            "no_corpus": "议题前提：未核（案卷无信源正文）",
            "exempt_template": "议题前提：免核（问句模板，无比对专有名）",
            "checked_ok": "议题前提：已核无缺口",
            "gaps": f"议题前提：已核，{len(flags)} 项未覆盖",
        }.get(status, status),
    }


def premise_flags(dossier: Dossier,
                  entities: list[str] | None = None) -> list[dict]:
    """议题实体 × 全部信源段落命中核对；零命中 → 黄色警示。"""
    corpus = _corpus_text(dossier)
    if not corpus:
        return []
    tokens = entities if entities is not None else extract_entities(
        dossier.question)
    flags: list[dict] = []
    for token in tokens:
        if _covered(token, corpus):
            continue
        flags.append({
            "kind": "premise", "severity": "medium",
            "value": token,
            "detail": f"议题中的「{token}」在全部信源中零命中"
                      "——该前提未被资料覆盖，相关回答须先核前提",
        })
        if len(flags) >= _MAX_FLAGS:
            break
    return flags


def injectible_premise_flags(dossier: Dossier) -> list[dict]:
    """可进分析师提示的高置信零命中：≥3 字、非疑问残渣，最多 3 条。

    宁漏勿误的字面启发式不够格命令模型写「资料不足」；其余只亮灯。"""
    out: list[dict] = []
    for flag in premise_flags(dossier):
        token = str(flag.get("value") or "")
        if len(token) < 3 or _is_residue(token):
            continue
        out.append(flag)
        if len(out) >= _MAX_INJECT:
            break
    return out
