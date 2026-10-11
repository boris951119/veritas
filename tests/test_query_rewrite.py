"""检索问句：词表扩展始终在；不完整问句才对照上一句补成一条。"""

from types import SimpleNamespace

from app.config import Settings
from app.core.bm25 import fuse_rankings, rank_segments
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.query_rewrite import (
    collect_search_queries,
    needs_context,
    parse_rewrite_payload,
    prepare_search_info,
    prior_question,
    rewrite_standalone,
    sanitize_standalone,
    sanitize_variants,
)


def _src(sid: str, text: str) -> Source:
    src = Source.create(sid, SourceType.NEWS, id=sid)
    src.segments = [Segment(id=f"{sid}#s1", source_id=sid, text=text, index=0)]
    return src


def test_sanitize_keeps_entity_and_drops_drift():
    original = "某制造公司是否已因资金链断裂全面停工？"
    got = sanitize_variants(original, [
        "某制造公司资金链与停产停工",
        "别的银行暴雷了吗",  # 丢掉：丢了原实体
        "某制造公司流动性危机",
        "某制造公司资金链与停产停工",  # 去重
    ])
    assert got == ["某制造公司资金链与停产停工", "某制造公司流动性危机"]


def test_collect_search_queries_puts_original_first():
    q = "南山铝业净利润"
    qs = collect_search_queries(q, ["南山铝业归母净利", "无关"])
    assert qs[0].startswith("南山铝业净利润") or "南山铝业净利润" in qs[0]
    assert any("南山铝业归母净利" in item for item in qs)
    assert all("无关" not in item for item in qs)


def test_fuse_rankings_promotes_multi_hit():
    # A 只在第一路靠前，B 两路都靠前 → B 融合分应更高或至少进前排
    r1 = [("A", 3.0), ("B", 2.0), ("C", 1.0)]
    r2 = [("B", 3.0), ("D", 2.0), ("A", 0.0)]
    fused = dict(fuse_rankings([r1, r2]))
    assert fused["B"] > fused["A"]
    assert "C" in fused and "D" in fused


def test_multi_query_ranks_paraphrase_hit():
    d = Dossier(question="某制造公司会不会倒闭？", sources=[
        _src("RUMOR", "网传某制造公司马上要倒闭了。"),
        _src("OFF", "官方通报：某制造公司资金链紧张但未停工。"),
        _src("WX", "今天天气不错适合出游。"),
    ])
    # 单路「倒闭」更容易先打到谣言；加上「资金链/停工」后官方应进前排
    single = [sid for sid, sc in rank_segments(d) if sc > 0]
    multi = [sid for sid, sc in rank_segments(
        d, queries=["某制造公司会不会倒闭？", "某制造公司资金链停工"]) if sc > 0]
    assert "OFF#s1" in multi
    assert multi.index("OFF#s1") <= single.index("OFF#s1") if "OFF#s1" in single \
        else True


def test_needs_context_only_when_incomplete():
    assert needs_context("它的净利润呢")
    assert needs_context("净利润呢")
    assert needs_context("那分红比例是多少")
    assert not needs_context("南山铝业2024年累计现金分红比例为多少")
    assert not needs_context("其他公司应该停工吗")
    assert not needs_context("其他公司2024年净利润是多少")


def test_complete_question_does_not_call_model():
    class Boom:
        def chat(self, *a, **k):
            raise AssertionError("完整问句不应调用模型")

    info = prepare_search_info(
        "南山铝业2024年累计现金分红比例为多少",
        prior="上一句不该被用到", client=Boom(), model="m",
    )
    assert info["status"] == "skipped"
    assert info["reason"] == "complete"
    assert info["variants"] == []
    assert "南山铝业2024年累计现金分红比例为多少" in info["queries"][0]


def test_incomplete_without_prior_does_not_guess():
    class Boom:
        def chat(self, *a, **k):
            raise AssertionError("没有上一句不应调用模型")

    info = prepare_search_info("它的净利润呢", client=Boom(), model="m")
    assert info["status"] == "skipped"
    assert info["reason"] == "no_prior"
    assert info["variants"] == []


def test_rewrite_soft_fails_on_bad_client():
    class Boom:
        def chat(self, *a, **k):
            raise RuntimeError("nope")

    assert rewrite_standalone("它的净利润呢", "南山铝业分红比例是多少", Boom(), "m") == ""
    info = prepare_search_info(
        "它的净利润呢", prior="南山铝业分红比例是多少",
        client=Boom(), model="m",
    )
    assert info["status"] == "fallback"
    assert info["variants"] == []
    assert "它的净利润呢" in info["queries"][0]


def test_rewrite_fills_subject_from_prior_only():
    class Ok:
        def chat(self, *a, **k):
            return SimpleNamespace(
                content='{"query":"南山铝业净利润是多少"}')

    latest = "它的净利润呢"
    prior = "南山铝业2024年累计现金分红比例是多少"
    got = rewrite_standalone(latest, prior, Ok(), "m")
    assert got == "南山铝业净利润是多少"
    info = prepare_search_info(latest, prior=prior, client=Ok(), model="m")
    assert info["status"] == "ok"
    assert info["variants"] == ["南山铝业净利润是多少"]
    assert info["original"] == latest
    assert "未替换原议题" in info["note"]
    assert "它的净利润呢" in info["queries"][0]
    assert any("南山铝业净利润是多少" in item for item in info["queries"])


def test_sanitize_standalone_drops_invented_company():
    latest = "它的净利润呢"
    prior = "南山铝业2024年累计现金分红比例是多少"
    assert sanitize_standalone(
        latest, prior, "中国银行净利润是多少") == ""
    assert sanitize_standalone(
        latest, prior, "南山铝业净利润是多少") == "南山铝业净利润是多少"


def test_parse_rewrite_payload_tolerates_junk():
    assert parse_rewrite_payload({"query": "南山铝业净利润"}) == ["南山铝业净利润"]
    assert parse_rewrite_payload({"queries": ["a", 1]}) == ["a", "1"]
    assert parse_rewrite_payload("x") == []


def test_prior_question_prefers_history_then_manifest(tmp_path):
    case = tmp_path / "南山铝业"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "question: 南山铝业2024年分红比例是多少\n", encoding="utf-8")
    assert prior_question("它的净利润呢", case) == "南山铝业2024年分红比例是多少"
    assert prior_question("南山铝业2024年分红比例是多少", case) == ""
    hist = case / "history" / "run1"
    hist.mkdir(parents=True)
    (hist / "report.json").write_text(
        '{"question": "南山铝业净利润是多少", "sources": []}',
        encoding="utf-8")
    assert prior_question("这个比例呢", case) == "南山铝业净利润是多少"


def test_query_rewrite_env_off(monkeypatch):
    monkeypatch.setenv("VERITAS_QUERY_REWRITE", "0")
    assert Settings.from_env().query_rewrite_enabled is False
    monkeypatch.setenv("VERITAS_QUERY_REWRITE", "1")
    assert Settings.from_env().query_rewrite_enabled is True


def test_retrieval_boundary_on_report_and_embedding_falls_back(monkeypatch):
    from app.core.hashchain import HashChain
    from app.core.retrieval import register_semantic_search, retrieval_record
    from app.pipeline import render_report_md

    monkeypatch.delenv("VERITAS_RETRIEVER", raising=False)
    rec = retrieval_record(None)
    assert rec["mode"] == "bm25"
    assert "向量重排未启用" in rec["note"]
    monkeypatch.setenv("VERITAS_RETRIEVER", "embedding")
    rec2 = retrieval_record(None)
    assert rec2["fallback"] is True
    assert rec2["mode"] == "bm25"
    register_semantic_search(lambda q, qs: [])
    try:
        rec3 = retrieval_record(None)
        assert rec3["fallback"] is False
        assert rec3["mode"] == "embedding"
    finally:
        register_semantic_search(None)

    d = Dossier(question="应收账款结清了吗", sources=[
        _src("LEX", "应收账款余额 120 万，已结清 80 万。"),
        _src("SYN", "回款记录显示进度正常。"),
    ])
    ranked = dict(rank_segments(d))
    assert ranked["SYN#s1"] > 0
    assert ranked["LEX#s1"] > ranked["SYN#s1"]
    md = render_report_md(d, HashChain(), [])
    assert "检索边界" in md
    assert "向量重排未启用" in md
    assert "同义词" in md
