"""C-125：测试树整线（总旗 ``VERITAS_TEST_TREE_LINE``，默认关）。

整棵端口实验测试树（veritas-obsidian-kg-exp ``app/kg_lab``，R44 交付包）
的前半链路，生产接线在 ``app/pipeline.py`` C-108 块内分流：

  0) 段语料＋摘要窗（KgIndex：原文∪摘要 BM25＋本机 bge-m3 段嵌入＋邻块）
  1) KG 召回前端＝KgIndex 融合（``fuse_r19``：经典 RRF⊕视图⊕邻块）
  2) 一筛多维加权 pool（``r8_fit.evaluate``＋R9 桶特征＋R21 portable 系数
     ——系数只活在一筛打分，出口仅 pool 序）
  3) 二筛密度盒（``authority_rerank``：in-pool、可变 k∈[3,7]、通稿簇
     keep-one、conflict_pairs、密度条 TARGET≥2/3、提交前显式 rank）
  4) 窄面 submit/pack（``layer_boundary``：rank_order＋洗净 pairs＋
     focus 信号；FORBIDDEN_PACK_KEYS 审计，零系数进 pack kwargs）
  5) tree17 cite 层只读 box+rank+pairs（``apply_tree17_cite``，不重 pack）

层边界（R44 可借鉴清单终稿，逐条守护）：
- 一筛出口仅 pool 序（coeff／feats／weights 不过窄面）；
- 二筛出口 box_ids／k／洗净 conflict_pairs（权威浮点不过窄面）；
- pack 消费面只接 priority／focus／max_segments
  （``assert_clean_pack_kwargs`` 在 pipeline 侧复核）；
- 生产链全程零金标：``authority_rerank`` 的 gold_ids 仅评测披露、
  ``apply_tree17_cite`` 的 gold 只进 L3 量尺——本模块两处都传 None。

嵌入不可达（本机 Ollama 掉线）＝显式降级词面并披露
（``kg_test_tree.embed.status="fallback_lexical"``），不静默、不崩管线。
摘要／vault 缓存缺席同样显式披露（C-127：``kg_test_tree.cache``＝
缺席布尔／影响面 summary|vault|embed／降级继续），不静默当暖缓存跑。

C-135：``kg_test_tree.expand``＝扩写披露（enabled／terms_n／paraphrase_n，
只记计数、不记扩写词原文）。

C-132 起本模块出厂开＝唯一主线（C-133：旧密度桥已删；显式
``VERITAS_TEST_TREE_LINE=0``＝跳过交卷面，不回旧路）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ENV = "VERITAS_TEST_TREE_LINE"

_COEFF_EXTRA: tuple[str, ...] = (
    "frame_align", "authority_unit", "has_time_nail", "option_align",
    "publish_recency", "verifiability", "title_option_hit",
    "role_party_relay",
)

# C-128：六案标记→slug 公共表（摘要建库脚本的 ``_slug`` 与
# 探针 ``CASE_MARKS`` 同源同义；加案只改这一处）。
CASE_MARK_PAIRS: tuple[tuple[str, str], ...] = (
    ("刘翔", "liuxiang"),
    ("王虹", "wanghong"),
    ("中美AI", "us_cn_ai"),
    ("印度航空", "ai171"),
    ("柬泰", "kh_th"),
    ("吉隆", "jilong"),
)
_CASE_FALLBACK = "case"


def resolve_case_slug(dossier: Any) -> str:
    """dossier.title（official／case_loader 都写案名）→ 六案 slug。

    未命中＝回落 ``"case"``（不臆造新案名）。生产开旗路径经
    ``ensure_test_tree_submit`` 自动解析；显式 ``case_slug=`` 可覆盖。
    """
    title = str(getattr(dossier, "title", "") or "")
    for mark, slug in CASE_MARK_PAIRS:
        if mark in title:
            return slug
    return _CASE_FALLBACK


def test_tree_line_enabled(settings: Any | None = None) -> bool:
    """C-132 默认开。settings 优先；env 兜底（显式关＝False，未设＝开）。"""
    if settings is not None and hasattr(settings, "test_tree_line"):
        return bool(getattr(settings, "test_tree_line"))
    v = (os.environ.get(_ENV) or "").strip().lower()
    if v in ("0", "false", "off", "no"):
        return False
    return True


def test_tree_coeff() -> tuple[dict[str, float], tuple[str, ...]]:
    """一筛系数＝R9 拟合值（仓内数据文件）＋R21 portable 微移。

    与实验 ``run_r22._coeff_names`` 同式；系数只进一筛打分，
    不进 pack kwargs／窄面（层边界）。
    """
    from app.kg_lab.r21_coeff import apply_r21_coeff_nudge
    from app.kg_lab.r8_fit import FEATURE_NAMES
    from app.kg_lab.r9_buckets import R9_ADDED, r9_names

    path = Path(__file__).resolve().parents[1] / "kg_lab" / "r9_coeff.json"
    r9 = json.loads(path.read_text(encoding="utf-8")).get("coeff") or {}
    names = R9_ADDED + tuple(
        n for n in r9_names(FEATURE_NAMES) if n not in R9_ADDED)
    coeff = {n: float(r9.get(n) or 0.0) for n in names}
    for n in names:
        coeff.setdefault(n, 0.0)
    for n in _COEFF_EXTRA:
        coeff.setdefault(n, 0.0)
        if n not in names:
            names = names + (n,)
    return apply_r21_coeff_nudge(coeff), names


def build_test_tree_surface(
    dossier: Any,
    *,
    case_slug: str = "case",
) -> dict[str, Any]:
    """整线一跑：KG 前端→一筛(多维)→二筛密度盒→窄面→tree17。

    零金标（gold 只活在量尺侧）；出口＝C-107 同一窄面契约的 surface＋
    hints＋披露（box／密度／路由／嵌入状态／池规模）。
    """
    from app.kg_lab.case_lexicon import lexicon_for_question
    from app.kg_lab.event_frame import extract_event_frame
    from app.kg_lab.index_build import (
        KgIndex, build_corpus_rows, keyword_expand_query,
    )
    from app.kg_lab.intent_routes import classify_route
    from app.kg_lab.layer_boundary import (
        assert_submit_no_coeff,
        audit_forbidden_keys,
        build_submit_surface,
        pack_hints_from_submit,
        stage2_box_export,
    )
    from app.kg_lab.multidim_weight import build_bundle
    from app.kg_lab.portable_tags import apply_portable_features
    from app.kg_lab.r8_fit import augment_features, evaluate
    from app.kg_lab.r9_buckets import apply_r9
    from app.kg_lab.slices import pack_selected_for_question
    from app.kg_lab.source_role import _meta_from_row
    from app.kg_lab.stage1_pool import fuse_r19
    from app.kg_lab.stage2_authority import authority_rerank
    from app.kg_lab.tree17_cite import apply_tree17_cite
    from app.kg_lab.config import DEFAULT_K

    question = str(getattr(dossier, "question", "") or "")
    seg_ids = {
        str(seg.id)
        for src in getattr(dossier, "sources", [])
        for seg in src.segments
    }
    rows = build_corpus_rows(dossier, case_slug=case_slug, para_ids=seg_ids)

    # url／publish 元数据取自主仓 Source（official loader 已带），
    # 不读官方卷 raw_documents.json
    url_of: dict[str, str] = {}
    publish_of: dict[str, str] = {}
    for src in getattr(dossier, "sources", []):
        doc = str(src.id)
        url_of[doc] = str(getattr(src, "url", "") or "")
        meta = getattr(src, "meta", None) or {}
        publish_of[doc] = str(
            meta.get("publish_time") or meta.get("published_at") or ""
        )

    # 0)／1) KG 召回前端：全库索引（嵌入缓存 .kgcache/kg-index/<slug>/）
    embed_meta: dict[str, Any] = {"status": "ok"}
    embed_dead = False
    try:
        index = KgIndex(case_slug, rows)
        index.ensure_embeddings(force=False)
    except Exception as exc:  # ollama 不可达＝显式降级词面（披露，不静默）
        index = KgIndex(case_slug, rows)
        index.embeddings = {}
        index.embed_rank = lambda q: []  # 降级：后续融合不再触嵌入出口
        embed_dead = True
        embed_meta = {
            "status": "fallback_lexical",
            "error_type": type(exc).__name__,
        }
    embed_meta["n_vec"] = len(index.embeddings)

    # C-127：缓存缺席披露——缺席必须「可读／可判」，不许静默当暖缓存跑。
    # 影响面：summary（rows 无摘要文本）／vault（SUMMARIES_DIR/<slug> 缺）／
    # embed（嵌入降级）。缺席只降读数质量、线继续跑（degraded_continue）。
    from app.kg_lab.summarize import SUMMARIES_DIR

    vault_present = bool((SUMMARIES_DIR / case_slug).is_dir())
    n_with_summary = sum(
        1 for r in rows if str(r.get("summary_text") or "").strip()
    )
    cache_state: dict[str, Any] = {
        "vault_dir_present": vault_present,
        "n_rows": len(rows),
        "n_with_summary": n_with_summary,
        "summary_missing": n_with_summary == 0,
        "affected": [
            face for face, bad in (
                ("summary", n_with_summary == 0),
                ("vault", not vault_present),
                ("embed", embed_dead),
            ) if bad
        ],
        "degraded_continue": bool(
            n_with_summary == 0 or not vault_present or embed_dead
        ),
    }

    universe = pack_selected_for_question(dossier, question)
    sub_rows = [r for r in rows if r["para_id"] in universe]
    sub = KgIndex(case_slug, sub_rows)
    sub.embeddings = {
        pid: v for pid, v in index.embeddings.items() if pid in universe
    }
    if embed_dead:
        sub.embed_rank = lambda q: []
    fr = fuse_r19(sub, question, use_llm_views=False, neighbor_window=1)
    submit_ranked = fr["ranked"]
    pool_ranked = fr.get("pool_ranked") or fr["ranked"]

    # C-135 披露键组（出口仅 kg_test_tree.expand 一个 dict）：enabled＝扩写
    # 机制在跑（fuse_r19 经典臂无条件扩写）；terms_n＝canonical 扩写词数
    # （与经典臂同一调用 keyword_expand_query(question, sub.rows)，只记词数、
    # 不记词表原文——扩写全文不进窄面／pack）；paraphrase_n＝复用 fuse_r19
    # 既有键 n_classic_paraphrase（规则改写数，n=1 封顶）。
    q_expanded = keyword_expand_query(question, sub.rows)
    expand_meta = {
        "enabled": True,
        "terms_n": len(str(q_expanded).split()) if str(q_expanded).strip() else 0,
        "paraphrase_n": int(fr.get("n_classic_paraphrase") or 0),
    }

    # 2) 一筛多维加权 pool（R19 池序＋R9/R21 系数打分；出口仅序）
    frame = extract_event_frame(question)
    route = classify_route(question, frame)
    bundle = build_bundle(
        sub_rows, submit_ranked, question, frames=True,
        prefer_ids=None, case_slug=case_slug,
    )
    by_row = {r["para_id"]: r for r in sub_rows}
    lex = lexicon_for_question(question, case_slug=case_slug)
    for pid, _sc in pool_ranked[:60]:
        if pid in bundle["metas"]:
            continue
        row = by_row.get(pid)
        if row:
            bundle["metas"][pid] = _meta_from_row(row, lex=lex)
            bundle["feats"].setdefault(pid, {})
    augment_features(bundle["feats"], bundle["metas"], url_of)
    apply_r9(bundle["feats"], bundle["metas"], question)
    apply_portable_features(
        bundle["feats"], bundle["metas"], url_of, question, frame,
        publish_of=publish_of,
    )
    coeff, names = test_tree_coeff()
    bundle["qid"] = "q"
    bundle["question"] = question
    bundle["l2"] = []  # 生产零金标
    stage1 = evaluate([bundle], coeff, k7=DEFAULT_K, k15=15, names=names)
    ranked = stage1["ranked"]["q"]

    # 3) 二筛密度盒（可变 k、簇 keep-one、pairs；gold_ids=None＝零金标）
    texts = {
        pid: str((bundle["metas"].get(pid) or {}).get("text") or "")
        for pid in set(
            [p for p, _ in ranked[:40]] + [p for p, _ in pool_ranked[:40]]
        )
    }
    out = authority_rerank(
        ranked, pool_ranked,
        texts=texts, feats=bundle["feats"], metas=bundle["metas"],
        question=question, frame=frame, url_of=url_of, publish_of=publish_of,
        pool=20, k=20,
        head_keep=1, max_inject=8,
        density_cut=True,
        gold_ids=None,
        k_min=3, k_max=7,
    )
    order = [row["id"] for row in out["order"]]
    dens = out.get("density") if out.get("density_cut") else None
    dens = dens or {}
    if dens:
        k_sel = int(dens.get("k") or 7)
        box = list(out.get("top_ids") or dens.get("submission")
                   or order[:k_sel])
    else:
        k_sel = 7
        box = order[:k_sel]
    if not box:
        box = order[:k_sel]

    # 4) 窄面 submit／pack（禁键审计＝层边界闸）
    box_export = stage2_box_export(out)
    box_export = {**box_export, "box_ids": list(box), "k": k_sel}
    leaks = audit_forbidden_keys(box_export)
    # 5) tree17 cite（只读 box+rank+pairs；gold=None）
    t17 = apply_tree17_cite(
        box, metas=bundle["metas"], question=question,
        anchors=route.anchors, align_to_box=True,
        gold_ids=None, support_ids=None,
    )
    plan = t17.get("plan") or {}
    surface = build_submit_surface(box_export, tree17_plan=plan)
    assert_submit_no_coeff(surface)
    hints = pack_hints_from_submit(surface)
    leaks += audit_forbidden_keys(hints)
    if leaks:
        raise ValueError(f"C-125 窄面禁键泄漏: {leaks}")
    pairs = surface.get("conflict_pairs")
    n_pairs = (
        len(pairs.get("conflicts") or [])
        if isinstance(pairs, dict) else 0
    )
    return {
        "surface": surface,
        "hints": hints,
        "box": list(box),
        "k": k_sel,
        # C-140：二筛显式全序（rerank 行只取 id；序尾补盒内缺员，与
        # build_conflict_pairs 同一补法）——交卷 Top-7 的候选池。
        "rerank_order": list(order) + [
            str(x) for x in box if x not in set(order)
        ],
        "density": {
            "k": dens.get("k"),
            "n_core": dens.get("n_core"),
            "n_filler": dens.get("n_filler"),
            "proxy_density": dens.get("density"),
            "met_target": dens.get("met_target"),
            "route": getattr(route, "route", ""),
        },
        "route": getattr(route, "route", ""),
        "embed": embed_meta,
        "cache": cache_state,
        "expand": expand_meta,
        "case_slug": case_slug,
        "pool_n": len(pool_ranked),
        "universe_n": len(universe),
        "rows_n": len(rows),
        "close_read": list(plan.get("close_read") or []),
        "n_pairs": n_pairs,
        "stage1_names": len(names),
    }


def ensure_test_tree_submit(
    dossier: Any,
    *,
    force: bool = False,
    case_slug: str | None = None,
) -> dict | None:
    """旗开时在 pipeline 内整线跑一遍并写 accounting（与 C-108 桥同槽位）。

    C-128：``case_slug`` 缺省时从 ``dossier.title`` 解析六案实名
    （``resolve_case_slug``；未命中回落 ``"case"``）；显式实参可覆盖。
    实际使用的 slug 与是否回落写进 ``kg_test_tree.case_slug``／
    ``case_slug_fallback``（嵌在既有白名单键内，过禁键审计）。
    已有 kg_submit 且 force=False → 不覆盖（沿旧桥语义；桥本体已删＝C-133）。
    accounting 键沿用 kept 白名单既有键（kg_submit/kg_density/kg_stage1），
    新增披露键 ``kg_test_tree``（白名单同步登记）。
    """
    acc = getattr(dossier, "accounting", None)
    if acc is None:
        dossier.accounting = {}
        acc = dossier.accounting
    if not force and isinstance(acc.get("kg_submit"), dict) and acc.get("kg_submit"):
        return None
    slug = str(case_slug) if case_slug else resolve_case_slug(dossier)
    out = build_test_tree_surface(dossier, case_slug=slug)
    surface = out["surface"]
    acc["kg_submit"] = surface
    dens = out["density"]
    acc["kg_density"] = {
        "k": dens.get("k"),
        "n_core": dens.get("n_core"),
        "n_filler": dens.get("n_filler"),
        "proxy_density": dens.get("proxy_density"),
        "met_target": dens.get("met_target"),
        "route": dens.get("route"),
        "cap_segments": False,
        "pool_order_n": out.get("pool_n"),
        "line": "test_tree",
    }
    acc["kg_test_tree"] = {
        "line": "test_tree_full",
        "embed": out["embed"],
        "cache": dict(out.get("cache") or {}),
        "expand": dict(out.get("expand") or {}),  # C-135 扩写披露（只记计数）
        "case_slug": slug,
        "case_slug_fallback": slug == _CASE_FALLBACK,
        "route": out["route"],
        "k": out["k"],
        "pool_n": out["pool_n"],
        "universe_n": out["universe_n"],
        "rows_n": out["rows_n"],
        "close_read_n": len(out["close_read"]),
        "n_pairs": out["n_pairs"],
        "stage1_names": out["stage1_names"],
        # C-140：二筛显式序 id 列表（候选池；只 id、零分值零系数）
        "rerank_order_n": len(out["rerank_order"]),
        "rerank_order": [str(x) for x in out["rerank_order"]],
    }
    from app.kg_lab.layer_boundary import audit_forbidden_keys

    leaks = audit_forbidden_keys(acc["kg_test_tree"])
    if leaks:
        raise ValueError(f"kg_test_tree accounting leaked: {leaks}")
    return out
