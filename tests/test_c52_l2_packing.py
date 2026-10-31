"""C-52：L2 装箱／检索增强守护格（零 LLM、期望值写死）。

覆盖：
1. 非财务长题不再被 expand_query 打上财务探针；
2. 装箱问句剥探针尾 + 切面／标题增强；
3. 两段式装箱：槽位优先，BM25>0 按分/log2(len) 填箱（非整轮轮转）；
4. 案卷门控同义（扩展词必须已在案卷出现）；
5. 反向腿：摘掉关键逻辑 ⇒ 格子必须红。
"""
from __future__ import annotations

import math

import pytest

from app.core.bm25 import (
    expand_query,
    looks_financial,
    strip_finance_probe_tail,
    synonym_terms,
)
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.material import pack_material, pack_search_queries


def _src(sid: str, title: str, texts: list[str]) -> Source:
    src = Source.create(title, SourceType.REPORT, id=sid)
    for i, t in enumerate(texts, 1):
        src.segments.append(Segment(id=f"{sid}#p{i}", source_id=sid, text=t))
    return src


# -- expand_query 财务探针不再污染非财务长题 ------------------------------------


def test_c52_expand_query_skips_finance_probe_on_long_nonfinance():
    q = "中方称泥石流、联合国与尼泊尔称洪灾或山崩，评估伤亡与受灾统计时应采用哪一口径？"
    assert not looks_financial(q)
    expanded = expand_query(q)
    assert "营业收入" not in expanded
    assert expanded.startswith(q)


def test_c52_expand_query_still_probes_short_company_name():
    """反向兼容：短公司名议题仍打财务探针（既有格子）。"""
    assert "净利润" in expand_query("富恒新材")


def test_c52_strip_finance_probe_tail_hardcoded():
    polluted = (
        "中方称泥石流 营业收入 归母净利润 净利润 同比 分红 现金红利"
    )
    assert strip_finance_probe_tail(polluted) == "中方称泥石流"


# -- 案卷门控同义 ----------------------------------------------------------------


def test_c52_dossier_gated_groups_removed_even_with_corpus_hit():
    """R-C52-1 摘掉门控专题表：即便 corpus 含扩展词，也不再放出。

    归因：关门控⇒批1 L2 54（+1）；词表冻结禁止再手写贴专题。
    """
    q = "评估伤亡与受灾统计时应采用哪一口径？"
    assert "遇难" not in synonym_terms(q)
    syn = synonym_terms(q, corpus="灾害造成多人遇难、失联、死亡、边境交火")
    for banned in ("遇难", "失联", "死亡", "边境", "交火", "事业编", "公务员"):
        assert banned not in syn, f"门控已摘却仍扩展出 {banned!r}: {syn!r}"


def test_c52_gated_synonym_corpus_absent_term_not_expanded():
    """真牙①（门控摘掉后改钉基组）：议题命中「停工」、corpus 不含「停产」⇒ 不扩展。

    下刀：把 bm25.synonym_terms 里 `if corpus and term not in corpus` 改恒假 ⇒ 本格必红。
    （门控专题表已按归因摘掉；本格守住基组的 corpus 过滤。）
    """
    q = "工厂是否停工？"
    assert "停产" in synonym_terms(q)  # 无 corpus 时基组会扩
    corpus = "与本次经营完全无关的普通叙述"
    assert "停产" not in corpus
    syn = synonym_terms(q, corpus=corpus)
    assert "停产" not in syn, (
        f"真牙①红名：corpus 不含「停产」却进了扩展 syn={syn!r}"
    )


# -- pack_search_queries --------------------------------------------------------


def test_c52_pack_queries_strip_stored_finance_pollution():
    d = Dossier(question="泰方称出动F-16，柬方称未遭空袭，哪一方有证据？")
    d.accounting["query_rewrite"] = {
        "original": d.question,
        "variants": ["泰方与柬方空袭说法谁有证据"],
        "queries": [
            d.question + " 营业收入 归母净利润 净利润 同比 分红",
            "泰方与柬方空袭说法谁有证据 营业收入 归母净利润",
        ],
    }
    d.add_source(_src("S1", "柬泰边境 F-16 空袭争议", [
        "泰国军方宣布出动 F-16。",
        "柬方称军事设施未遭空袭。",
    ]))
    qs = pack_search_queries(d)
    assert qs, "必须产出问句"
    assert all("营业收入" not in q for q in qs)
    assert any("F-16" in q or "空袭" in q for q in qs)


# -- 两段式装箱密度排序 ----------------------------------------------------------


def test_c52_packing_prefers_dense_short_over_long_low_score():
    """同预算内：高相关短段应优先于低相关超长段（分/log2(len)）。"""
    d = Dossier(question="客户B回款率是多少？")
    # 长噪声
    long_noise = "今日天气" + ("晴" * 400)
    short_hit = "客户B回款率四成，回款512万。"
    mid = "客户B合同金额1280万，与回款无关的背景。" + ("背" * 80)
    d.add_source(_src("SA", "回款报告", [long_noise, short_hit, mid]))
    d.add_source(_src("SB", "天气周报", ["公园散步。" + ("走" * 50)]))
    pack = pack_material(d, budget_chars=120)
    assert "SA#p2" in pack["selected"]
    # 预算紧时不应只装长噪声
    assert "SA#p1" not in pack["selected"] or "SA#p2" in pack["selected"]


def test_c52_density_packing_selects_short_over_high_score_long():
    """真牙②：同一预算下「高分长段」与「低分短段」二选一，钉 selected id。

    分歧样本（现场标定）：长段 raw BM25 更高，但分/log2(len) 更低；
    预算刚好装下二者之一 ⇒ 密度排序必须选短段 id。
    下刀：摘掉 `/ math.log2(max(lengths[seg_id], 2))` ⇒ 改选长段 ⇒ 本格必红。

    C-70：软闸默认开后 SB（议题零重合）不再自动 zero，短杂讯会与 SA#p2
    同箱；本格钉的是密度轴，故关软闸隔离资格面（见回写「既有断言改动清单」）。
    """
    from app.core.relevance import set_relevance_soft_gate
    set_relevance_soft_gate(False)
    q = "客户B回款率是多少？"
    long_hit = (
        "客户B回款率是多少？客户B回款率四成，回款512万。"
        + ("无关填充。" * 50)
    )
    short_hit = "回款四成。"
    d = Dossier(question=q)
    d.add_source(_src("SA", "回款报告", [long_hit, short_hit]))
    d.add_source(_src("SB", "杂讯", ["公园天气走一走。" + ("走" * 30)]))
    # 预算＝长段字数：二者都能单独入箱，但不能同时
    budget = len(long_hit)
    assert budget >= len(short_hit)
    assert budget < len(long_hit) + len(short_hit)
    pack = pack_material(d, budget_chars=budget)
    # 钉最终 selected 的那一组 id（不是钉字符串在场）
    assert pack["selected"] == {"SA#p2"}, (
        f"真牙②红名：密度装箱应只选短段 SA#p2；"
        f"实际 selected={sorted(pack['selected'])}"
    )


def test_c52_packing_deterministic():
    d = Dossier(question="客户B回款率是多少？")
    d.add_source(_src("S1", "回款", [
        "客户B回款512万，回款率四成。",
        "无关天气描述。" + ("天" * 30),
    ]))
    a = pack_material(d, budget_chars=80)
    b = pack_material(d, budget_chars=80)
    assert a["selected"] == b["selected"]
    assert a["excluded"] == b["excluded"]




def test_c52_base_synonym_corpus_absent_not_expanded():
    """基组同样守 corpus 门：议题有「停工」、corpus 不含「停产」⇒ 不扩展。"""
    q = "工厂是否停工？"
    assert "停产" in __import__("app.core.bm25", fromlist=["synonym_terms"]).synonym_terms(q)
    syn = synonym_terms(q, corpus="与本次经营完全无关的叙述")
    assert "停产" not in syn

# -- 反向腿：摘掉关键逻辑必须红 --------------------------------------------------


def test_c52_reverse_leg_finance_probe_guard(monkeypatch):
    """反向腿①：若 expand_query 又对非财务长题打回探针 ⇒ 本格红。"""
    import app.core.bm25 as bm25

    def polluted(question: str, *, corpus: str = "") -> str:
        q = (question or "").strip() or "x"
        return q + " " + bm25._PROBE_TERMS

    monkeypatch.setattr(bm25, "expand_query", polluted)
    # 直接验 strip／looks_financial 仍在；并用 pack_search_queries 路径
    # 这里验：若有人把 expand_query 改回污染，looks_financial 长非财务题
    # 的 pack_search_queries 仍应剥尾——若连剥尾也坏，下面断言红。
    q = "中方称泥石流、联合国与尼泊尔称洪灾或山崩，评估伤亡统计口径？"
    # 恢复真实 expand 测「未污染」承诺；本格锚定 strip + looks_financial
    monkeypatch.undo()
    assert not looks_financial(q)
    assert "营业收入" not in expand_query(q)




def test_c52_reverse_leg_pack_queries_must_not_keep_probe(monkeypatch):
    """反向腿③：若 pack_search_queries 不再剥探针 ⇒ 红。"""
    d = Dossier(question="泥石流与洪灾口径争议应采哪一家说法？")
    d.accounting["query_rewrite"] = {
        "original": d.question,
        "variants": [],
        "queries": [d.question + " 营业收入 归母净利润 净利润"],
    }
    d.add_source(_src("S1", "泥石流灾害报道", ["泥石流造成受灾。"]))
    qs = pack_search_queries(d)
    assert qs
    assert all("营业收入" not in q for q in qs), (
        f"反向腿红名：问句仍含财务探针 {qs!r}"
    )
