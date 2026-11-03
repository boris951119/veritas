"""C-140 守护格：交卷硬 Top-7＋冲突成对保位（件①机制）。

钉七件事（全部零 LLM、零网络、手造夹具）：
  a. 开关：默认开；settings.submit_top7 优先；VERITAS_SUBMIT_TOP7=0
     → 关回旧可变 k（焦点面与改前逐字相同、accounting 无 submit_top7）；
  b. 纯函数：min(7, 候选长) 取前段；成对任一侧进 Top-7、对侧在候选
     但不在 → 追加保位（不占前 7 名额，可 8／9）；对侧不在候选不追加；
     重复对侧去重；cut_ids＝候选−final 逐位回放；
  c. 可迁移：face 只含 id／计数，过 audit_forbidden_keys，零案名；
  d. 账目通道：apply 只写 kg_focus_segment_ids／kg_pack_hints 同步＋
     submit_top7；候选池缺席回退 rank_order（留痕 candidates_source）；
  e. 生产路径：ensure_test_tree_submit 落候选池（rerank_order）→
     apply 后 accounting['submit_top7'] 在场、盒 rank_order 与
     tree17_cite 逐位不动；关旗＝零行为；
  f. 提示词面：focus 渲染只含 final 段；关旗 face 与改前字节相同；
  g. 登记面：kept 白名单含 submit_top7；config.json 覆写可关。
"""

from __future__ import annotations

import json

from app.core.evidence import Dossier, Segment, Source, SourceType

Q = "某市通报与网络说法对事故原因描述不一致，官方结论是什么？"

CASE_MARKS = ("刘翔", "王虹", "中美AI", "印度航空", "柬泰", "吉隆")


def _dossier(n_docs: int = 3, n_paras: int = 10) -> Dossier:
    d = Dossier(question=Q)
    d.title = "测试夹具案（无案名标记）"
    for di in range(1, n_docs + 1):
        doc = f"doc_{di:03d}"
        src = Source.create(f"信源{di}", SourceType.REPORT, id=doc)
        src.url = f"https://example.test/{doc}"
        for p in range(1, n_paras + 1):
            text = (
                f"{doc}第{p}段：事故发生于2026年3月{p}日，涉事金额{p}0万元，"
                f"通报口径与现场记录{'一致' if p % 2 else '存在差异'}，"
                f"处置进展持续更新，相关责任认定仍在进行中。"
            )
            src.segments.append(Segment(
                id=f"{doc}#p{p}", source_id=doc, text=text,
                locator=f"{doc}#p{p}"))
        d.add_source(src)
    return d


def _fake_embeddings(monkeypatch) -> None:
    from app.kg_lab.index_build import KgIndex

    def _ensure(self, *, force: bool = False, refresh_ids=None):
        self.embeddings = {
            str(r["para_id"]): [0.1, 0.2, 0.3] for r in self.rows
        }
        return {"stubbed": True}

    monkeypatch.setattr(KgIndex, "ensure_embeddings", _ensure)


def _selection_block(d: Dossier, *, c140: bool = True) -> None:
    """逐行镜像 pipeline 选料块（C-140 后形状），零 LLM。"""
    from app.core.kg_submit_surface import (
        apply_kg_submit_surface, assert_clean_pack_kwargs, pack_kwargs_for_kg,
    )
    from app.core.kg_test_tree_line import ensure_test_tree_submit

    ensure_test_tree_submit(d)
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    assert_clean_pack_kwargs(kw)
    if c140:
        from app.core.submit_top7 import apply_submit_top7
        apply_submit_top7(d, enabled=True)


# ------------------------------------------------ a. 开关

def test_a_flag_default_on_and_settings_priority(monkeypatch):
    from app.config import Settings
    from app.core.submit_top7 import submit_top7_enabled

    monkeypatch.delenv("VERITAS_SUBMIT_TOP7", raising=False)
    assert submit_top7_enabled() is True
    monkeypatch.setenv("VERITAS_SUBMIT_TOP7", "0")
    assert submit_top7_enabled() is False
    # settings 属性优先于 env
    s = Settings.from_env()
    monkeypatch.setenv("VERITAS_SUBMIT_TOP7", "0")
    assert Settings.from_env().submit_top7 is False
    s.submit_top7 = True
    assert submit_top7_enabled(s) is True


# ------------------------------------------------ b. 纯函数：Top-7＋保位

def test_b_top7_cap_and_reserve():
    from app.core.submit_top7 import build_top7_face

    cand = [f"c{i:02d}" for i in range(1, 13)]  # 12 候选
    # 无对：k_top=7、final=前 7、cut=后 5
    face = build_top7_face(cand, {"conflicts": []})
    assert face["k_top"] == 7 and face["final_n"] == 7
    assert face["top_ids"] == cand[:7]
    assert face["reserve_added"] == 0 and face["reserve_ids"] == []
    assert face["final_ids"] == cand[:7]
    assert face["cut_ids"] == cand[7:]
    assert face["candidates_n"] == 12

    # 候选不足 7：k_top＝候选长
    short = build_top7_face(cand[:5], {"conflicts": []})
    assert short["k_top"] == 5 and short["final_n"] == 5 and \
        short["cut_ids"] == []

    # 成对保位：c1 在 Top-7、c9 在候选不在 Top-7 ⇒ 追加 c9（final_n=8）
    pairs = {"conflicts": [
        {"support_id": "c01", "oppose_id": "c09"},
    ]}
    f1 = build_top7_face(cand, pairs)
    assert f1["reserve_ids"] == ["c09"] and f1["final_n"] == 8
    assert f1["final_ids"] == cand[:7] + ["c09"]
    assert f1["pair_rows"][0]["reserve_added"] == "c09"

    # 两组成对各缺一侧 ⇒ 可到 9
    pairs2 = {"conflicts": [
        {"support_id": "c01", "oppose_id": "c09"},
        {"support_id": "c10", "oppose_id": "c02"},
    ]}
    f2 = build_top7_face(cand, pairs2)
    assert f2["final_n"] == 9
    assert f2["reserve_ids"] == ["c09", "c10"]

    # 对侧不在候选 ⇒ 不追加（留痕 added=None）
    pairs3 = {"conflicts": [{"support_id": "c01", "oppose_id": "zz"}]}
    f3 = build_top7_face(cand, pairs3)
    assert f3["reserve_added"] == 0 and f3["final_n"] == 7
    assert f3["pair_rows"][0]["reserve_added"] is None

    # 重复对侧只追加一次
    pairs4 = {"conflicts": [
        {"support_id": "c01", "oppose_id": "c09"},
        {"support_id": "c05", "oppose_id": "c09"},
    ]}
    f4 = build_top7_face(cand, pairs4)
    assert f4["reserve_ids"] == ["c09"] and f4["final_n"] == 8

    # 候选空 → None（零行为）
    assert build_top7_face([], {"conflicts": []}) is None


# ------------------------------------------------ c. 可迁移＋禁键审计

def test_c_transferable_and_no_leak():
    from app.core.kg_submit_surface import audit_forbidden_keys
    from app.core.submit_top7 import build_top7_face

    cand = [f"doc_001#p{i}" for i in range(1, 13)]
    face = build_top7_face(cand, {"conflicts": [
        {"support_id": "doc_001#p1", "oppose_id": "doc_001#p9"}]})
    assert audit_forbidden_keys(face) == []
    blob = json.dumps(face, ensure_ascii=False)
    for mark in CASE_MARKS:
        assert mark not in blob, mark


# ------------------------------------------------ d. 账目通道

class _Box:
    pass


def _dossier_with_acc(candidates: list[str], pairs: dict,
                      rank_order: list[str]) -> Dossier:
    d = _dossier(n_docs=1, n_paras=12)
    d.accounting = {
        "kg_submit_active": True,
        "kg_submit": {"rank_order": list(rank_order), "k": len(rank_order)},
        "kg_test_tree": {"rerank_order": list(candidates),
                         "rerank_order_n": len(candidates)},
        "kg_conflict_pairs": pairs,
        "kg_focus_segment_ids": list(rank_order),
        "kg_pack_hints": {"focus_segment_ids": list(rank_order)},
    }
    return d


def test_d_apply_channel_and_replay():
    from app.core.kg_submit_surface import audit_forbidden_keys
    from app.core.submit_top7 import apply_submit_top7

    cand = [f"c{i:02d}" for i in range(1, 13)]
    d = _dossier_with_acc(
        cand, {"conflicts": [{"support_id": "c01", "oppose_id": "c09"}]},
        rank_order=["c01", "c05", "c09"])
    face = apply_submit_top7(d, enabled=True)
    assert face is not None and face["enabled"] is True
    acc = d.accounting
    assert face["k_top"] == 7 and face["reserve_added"] == 1
    assert face["final_n"] == 8 and face["candidates_source"] == "rerank_order"
    # 焦点面被重写为 final；hints 同步；盒 rank_order 不动
    assert acc["kg_focus_segment_ids"] == face["final_ids"]
    assert acc["kg_pack_hints"]["focus_segment_ids"] == face["final_ids"]
    assert acc["kg_submit"]["rank_order"] == ["c01", "c05", "c09"]
    assert audit_forbidden_keys(face) == []
    # 回放：final＝top7＋reserve；cut＝候选−final
    assert face["final_ids"] == cand[:7] + ["c09"]
    assert face["cut_ids"] == [c for c in cand[7:] if c != "c09"]

    # 关旗＝零行为（焦点面与 accounting 原样）
    d2 = _dossier_with_acc(cand, {"conflicts": []}, rank_order=cand[:3])
    before = list(d2.accounting["kg_focus_segment_ids"])
    assert apply_submit_top7(d2, enabled=False) is None
    assert "submit_top7" not in d2.accounting
    assert d2.accounting["kg_focus_segment_ids"] == before

    # 候选池缺席 → 回退 rank_order（留痕）
    d3 = _dossier_with_acc([], {"conflicts": []}, rank_order=cand[:4])
    f3 = apply_submit_top7(d3, enabled=True)
    assert f3["candidates_source"] == "rank_order_fallback"
    assert f3["k_top"] == 4 and f3["final_ids"] == cand[:4]

    # 未 apply 交卷面 → 零行为
    d4 = _dossier(n_docs=1, n_paras=4)
    d4.accounting = {}
    assert apply_submit_top7(d4, enabled=True) is None
    assert "submit_top7" not in d4.accounting


# ------------------------------------------------ e. 生产路径落账

def test_e_production_path(monkeypatch):
    monkeypatch.delenv("VERITAS_SUBMIT_TOP7", raising=False)
    _fake_embeddings(monkeypatch)
    from app.core.kg_submit_surface import audit_forbidden_keys

    d = _dossier()
    _selection_block(d, c140=False)  # 先拿改前形状
    pre_box = list(d.accounting["kg_submit"]["rank_order"])
    pre_focus = list(d.accounting["kg_focus_segment_ids"])
    pre_t17 = json.dumps(d.accounting["tree17_cite"], ensure_ascii=False,
                         sort_keys=True)
    pre_pack_hints = json.dumps(d.accounting["kg_pack_hints"],
                                ensure_ascii=False, sort_keys=True)

    d2 = _dossier()
    _selection_block(d2, c140=True)
    acc = d2.accounting
    face = acc.get("submit_top7")
    assert isinstance(face, dict) and face.get("enabled") is True
    assert face["k_top"] == min(7, face["candidates_n"])
    assert face["final_n"] == face["k_top"] + face["reserve_added"]
    assert acc["kg_focus_segment_ids"] == face["final_ids"]
    assert audit_forbidden_keys(face) == []
    assert audit_forbidden_keys(acc["kg_test_tree"]) == []
    # 盒／tree17／pack hints（除 focus）逐位不动
    assert acc["kg_submit"]["rank_order"] == pre_box
    assert json.dumps(acc["tree17_cite"], ensure_ascii=False,
                      sort_keys=True) == pre_t17
    hints = dict(acc["kg_pack_hints"])
    hints_pre = json.loads(pre_pack_hints)
    assert hints["priority_segment_ids"] == hints_pre["priority_segment_ids"]
    assert hints["max_segments"] == hints_pre["max_segments"]
    assert hints["focus_segment_ids"] == face["final_ids"]
    # 改前形状＝焦点面未被本机制重写（旧可变 k）
    assert pre_focus == hints_pre["focus_segment_ids"]
    # 候选池已落账（rerank_order）
    assert acc["kg_test_tree"]["rerank_order_n"] >= 1
    assert len(acc["kg_test_tree"]["rerank_order"]) == \
        acc["kg_test_tree"]["rerank_order_n"]


def test_e2_off_no_submit_top7(monkeypatch):
    monkeypatch.setenv("VERITAS_SUBMIT_TOP7", "0")
    _fake_embeddings(monkeypatch)
    d = _dossier()
    _selection_block(d, c140=False)
    # env 关旗经 apply 入口＝零行为（enabled 缺省走 submit_top7_enabled）
    from app.core.submit_top7 import apply_submit_top7

    assert apply_submit_top7(d) is None
    acc = d.accounting
    assert "submit_top7" not in acc
    # 焦点面＝旧形状（close_read／rank_order），未被重写
    surf = acc["kg_submit"]
    t17 = acc["tree17_cite"]
    close = [str(x) for x in (t17.get("close_read_ids") or [])]
    want = close or list(surf["rank_order"])
    assert acc["kg_focus_segment_ids"] == want


# ------------------------------------------------ f. 提示词面

def test_f_prompt_face_on_and_off(monkeypatch):
    monkeypatch.delenv("VERITAS_SUBMIT_TOP7", raising=False)
    _fake_embeddings(monkeypatch)
    from app.agents.prompts import render_segments_block

    d = _dossier()
    _selection_block(d, c140=False)
    face_off = render_segments_block(
        d, focus_segment_ids=d.accounting["kg_focus_segment_ids"])
    all_ids = {s.id for src in d.sources for s in src.segments}
    cut_off = all_ids - set(d.accounting["kg_focus_segment_ids"])

    d2 = _dossier()
    _selection_block(d2, c140=True)
    final_ids = set(d2.accounting["submit_top7"]["final_ids"])
    face_on = render_segments_block(
        d2, focus_segment_ids=d2.accounting["kg_focus_segment_ids"])
    # focus 渲染只含 final 段：final 全在场、被裁段不出现
    for pid in final_ids:
        assert pid in face_on, pid
    non_final = sorted(all_ids - final_ids)
    if non_final:
        assert non_final[0] not in face_on
    # 关旗 face 与「无 C-140 形状」字节相同（同 dossier 重放）
    d3 = _dossier()
    _selection_block(d3, c140=False)
    face_legacy = render_segments_block(
        d3, focus_segment_ids=d3.accounting["kg_focus_segment_ids"])
    assert face_off == face_legacy
    assert cut_off  # 自证：改前确实有裁掉的段（非空比空）


# ------------------------------------------------ g. 登记面

def test_g_kept_whitelist_and_config_override(monkeypatch, tmp_path):
    import importlib.util
    from app.config import Settings

    spec = importlib.util.find_spec("app.pipeline")
    src = (spec.origin and __import__("pathlib").Path(spec.origin)
           .read_text(encoding="utf-8")) or ""
    # 锚定 kept 白名单区域（C-139 cite_accept 与 C-140 submit_top7 同区登记；
    # 不钉逐字排版——解冲突换行不断格）
    anchor = '"kg_rehydrate", "kg_test_tree",'
    i = src.find(anchor)
    assert i >= 0, "kept 白名单锚点丢失"
    tail = src[i:i + 400]
    assert '"cite_accept"' in tail, "C-139 cite_accept 未登记 kept"
    assert '"submit_top7"' in tail, "C-140 submit_top7 未登记 kept"

    # config.json 覆写可关
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"submit_top7": False}), encoding="utf-8")
    s = Settings.from_json(cfg)
    assert s.submit_top7 is False
    cfg2 = tmp_path / "config2.json"
    cfg2.write_text(json.dumps({"submit_top7": True}), encoding="utf-8")
    assert Settings.from_json(cfg2).submit_top7 is True
