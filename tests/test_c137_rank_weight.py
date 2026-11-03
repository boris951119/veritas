"""C-137 守护格：树17 排名加权细读＋硬约束（件①机制）。

钉六件事（全部零 LLM、零网络、手造夹具）：
  a. 开关：默认开；VERITAS_TREE17_RANK_WEIGHT=0 → 注意力面整层缺席、
     分析师提示词与改前逐字相同（字节级）；
  b. 名次档：rank_order 唯一线上序——前 H 段＝close、其余＝scan；
     权重按名次单调不增、封顶 ≤1.0、轻扫＝地板；
  c. 成对强制：任一侧进细读 ⇒ 对立侧强制进细读（升级留痕 pair_forced）；
  d. 可迁移：权重键＝rank 档／in_pair／nail；注意力块零案名（六案标记
     一个都不出现）；整面过 audit_forbidden_keys；
  e. 生产路径：ensure_test_tree_submit → accounting['tree17_cite']
     ['attention'] 在场＋kg_test_tree.rank_weight 披露；关旗＝缺席；
  f. 提示词：硬约束五条在场（细读优先／禁名单外／成对两边／钉优先／
     采信对立标注）；盒与 rank_order 逐位不受影响。
"""

from __future__ import annotations

import pytest

from app.core.evidence import Dossier, Segment, Source, SourceType

Q = "某市通报与网络说法对事故原因描述不一致，官方结论是什么？"


def _dossier() -> Dossier:
    d = Dossier(question=Q)
    d.title = "测试夹具案（无案名标记）"
    for di in ("doc_001", "doc_002", "doc_003"):
        src = Source.create(f"信源{di}", SourceType.REPORT, id=di)
        src.url = f"https://example.test/{di}"
        for p in range(1, 11):
            text = (
                f"{di}第{p}段：事故发生于2026年3月{p}日，涉事金额{p}0万元，"
                f"通报口径与现场记录{'一致' if p % 2 else '存在差异'}，"
                f"处置进展持续更新，相关责任认定仍在进行中。"
            )
            src.segments.append(Segment(
                id=f"{di}#p{p}", source_id=di, text=text,
                locator=f"{di}#p{p}"))
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


def _run_selection_block(dossier: Dossier) -> dict:
    """逐行镜像 pipeline 选料块（C-132 后形状），零 LLM。"""
    from app.core.kg_submit_surface import (
        apply_kg_submit_surface, assert_clean_pack_kwargs, pack_kwargs_for_kg,
    )
    from app.core.kg_test_tree_line import ensure_test_tree_submit

    ensure_test_tree_submit(dossier)
    apply_kg_submit_surface(dossier, enabled=True)
    kw = pack_kwargs_for_kg(dossier)
    assert_clean_pack_kwargs(kw)
    return kw


CASE_MARKS = ("刘翔", "王虹", "中美AI", "印度航空", "柬泰", "吉隆")


# ------------------------------------------------ a. 开关与零 diff

def test_a_default_on_and_off_byte_identical(monkeypatch):
    from app.core.tree17_rank_weight import rank_weight_enabled

    monkeypatch.delenv("VERITAS_TREE17_RANK_WEIGHT", raising=False)
    assert rank_weight_enabled() is True
    monkeypatch.setenv("VERITAS_TREE17_RANK_WEIGHT", "0")
    assert rank_weight_enabled() is False

    # 提示词字节级：关旗＋同一 dossier → 与「无注意力面的改前形状」相同
    _fake_embeddings(monkeypatch)
    from app.agents.prompts import render_segments_block
    from app.core.kg_submit_surface import (
        apply_kg_submit_surface, kg_focus_segment_ids,
    )
    from app.core.kg_test_tree_line import ensure_test_tree_submit

    d1 = _dossier()
    ensure_test_tree_submit(d1)
    apply_kg_submit_surface(d1, enabled=True)
    monkeypatch.setenv("VERITAS_TREE17_RANK_WEIGHT", "0")
    face_off = render_segments_block(
        d1, focus_segment_ids=kg_focus_segment_ids(d1))
    # 改前形状＝同 dossier、无 tree17_cite.attention 的渲染
    d2 = _dossier()
    ensure_test_tree_submit(d2)
    apply_kg_submit_surface(d2, enabled=True)
    d2.accounting["tree17_cite"].pop("attention", None)
    face_legacy = render_segments_block(
        d2, focus_segment_ids=kg_focus_segment_ids(d2))
    assert face_off == face_legacy


# ------------------------------------------------ b/c. 名次档＋成对强制

def _fake_plan(order: list[str]) -> dict:
    """手造 tree17 计划：items 带 side／可核验分项（零金标）。"""
    items = []
    for i, pid in enumerate(order, 1):
        items.append({
            "para_id": pid, "box_rank": i, "in_close_read": True,
            "side": "option_a" if i % 2 else "option_b",
            "label": "采信", "stance": "support",
            "verifiability": {"score": 0.6, "time_n": 1 if i == 1 else 0,
                              "amount_n": 0, "bulletin_n": 1, "comment_n": 0},
        })
    return {"box": list(order), "close_read": list(order), "items": items,
            "pair_required": True, "conflict_route": True}


def _fake_pairs(order: list[str]) -> dict:
    return {"conflicts": [
        {"support_id": order[0], "oppose_id": order[-1]},
        {"support_id": order[1], "oppose_id": order[2]},
    ]}


def test_bc_tier_pair_and_weights():
    from app.core.tree17_rank_weight import (
        TIER_CLOSE, TIER_SCAN, WEIGHT_CAP, WEIGHT_FLOOR, build_attention,
    )

    order = [f"doc_001#p{i}" for i in range(1, 9)]  # 8 段
    att = build_attention(order, _fake_plan(order), _fake_pairs(order),
                          head_tier=3)
    assert att["head_tier"] == 3
    by = {t["id"]: t for t in att["tiers"]}
    # 名次档：1..3 close，4..8 scan（成对强制升级除外——见下）
    forced = set(att["pair_forced_ids"])
    for i, pid in enumerate(order, 1):
        want = TIER_CLOSE if (i <= 3 or pid in forced) else TIER_SCAN
        assert by[pid]["tier"] == want, (pid, by[pid])
    # 成对强制：p1(close) vs p8(scan) ⇒ p8 强制 close 并留痕
    assert by[order[-1]]["tier"] == TIER_CLOSE
    assert order[-1] in att["pair_forced_ids"]
    assert by[order[-1]]["pair_forced"] is True
    # p2(close) vs p3(close)＝本就同档，无强制
    assert by[order[1]]["pair_forced"] is False
    # 权重：close 内按名次单调不增、封顶 ≤1.0；scan＝地板（除非被强制）
    ws = [by[p]["weight"] for p in order[:3]]
    assert ws[0] <= WEIGHT_CAP and ws[0] > ws[1] > ws[2] >= WEIGHT_FLOOR
    assert by[order[3]]["weight"] == WEIGHT_FLOOR
    # 强制升级的段按其名次衰减计权（p8＝rank8 → 地板）
    assert by[order[-1]]["weight"] == WEIGHT_FLOOR
    # 成对两边都 close 的行数披露
    assert att["n_pair_both_close"] == 2
    # 钉加成：rank1 带时间钉 → 恰为 cap（floor 已 1.0，加成封顶）
    assert by[order[0]]["nail"] is True


# ------------------------------------------------ d. 可迁移＋禁键审计

def test_d_transferable_and_no_leak(monkeypatch):
    monkeypatch.delenv("VERITAS_TREE17_RANK_WEIGHT", raising=False)
    from app.core.tree17_rank_weight import (
        build_attention, render_attention_block,
    )
    from app.kg_lab.layer_boundary import audit_forbidden_keys

    order = [f"doc_001#p{i}" for i in range(1, 9)]
    att = build_attention(order, _fake_plan(order), _fake_pairs(order),
                          head_tier=3)
    assert audit_forbidden_keys(att) == []
    block = render_attention_block(att)
    for mark in CASE_MARKS:
        assert mark not in block, mark
    for kw in ("细读", "成对冲突", "硬约束", "可核验钉", "采信还是对立",
               "禁止引用资料清单编号以外"):
        assert kw in block, kw


# ------------------------------------------------ e. 生产路径落账

def test_e_production_path_accounting(monkeypatch):
    monkeypatch.delenv("VERITAS_TREE17_RANK_WEIGHT", raising=False)
    _fake_embeddings(monkeypatch)
    from app.kg_lab.layer_boundary import audit_forbidden_keys

    d = _dossier()
    _run_selection_block(d)
    acc = d.accounting
    att = (acc.get("tree17_cite") or {}).get("attention")
    assert isinstance(att, dict) and att.get("enabled") is True
    rw = (acc.get("kg_test_tree") or {}).get("rank_weight") or {}
    assert rw.get("enabled") is True and rw.get("head_tier") >= 1
    assert audit_forbidden_keys(acc["tree17_cite"]) == []
    assert audit_forbidden_keys(acc["kg_test_tree"]) == []
    # 盒序不被机制改动：rank_order 与 attention tiers 的 id 序逐位一致
    order = list(acc["kg_submit"]["rank_order"])
    assert [t["id"] for t in att["tiers"]] == order


def test_e2_off_no_attention(monkeypatch):
    monkeypatch.setenv("VERITAS_TREE17_RANK_WEIGHT", "0")
    _fake_embeddings(monkeypatch)
    d = _dossier()
    _run_selection_block(d)
    acc = d.accounting
    assert "attention" not in (acc.get("tree17_cite") or {})
    rw = (acc.get("kg_test_tree") or {}).get("rank_weight") or {}
    assert rw.get("enabled") is False


# ------------------------------------------------ f. 提示词块注入

def test_f_prompt_block_injected(monkeypatch):
    monkeypatch.delenv("VERITAS_TREE17_RANK_WEIGHT", raising=False)
    _fake_embeddings(monkeypatch)
    from app.agents.prompts import render_segments_block
    from app.core.kg_submit_surface import kg_focus_segment_ids

    d = _dossier()
    _run_selection_block(d)
    face_on = render_segments_block(
        d, focus_segment_ids=kg_focus_segment_ids(d))
    assert "细读注意力（按交卷排名加权）" in face_on
    assert "硬约束" in face_on
    for mark in CASE_MARKS:
        assert mark not in face_on
    monkeypatch.setenv("VERITAS_TREE17_RANK_WEIGHT", "0")
    face_off = render_segments_block(
        d, focus_segment_ids=kg_focus_segment_ids(d))
    assert "细读注意力（按交卷排名加权）" not in face_off
