"""C-109：一筛进池出口只 pool_ids；系数不进 pack；旗回退。

C-133：旧密度桥已删。本文件只直测适配层 ``app.core.kg_stage1_pool``
（旗读点＋出口禁系数）；「系数不进 pack」改走测试树共用面
（ensure_test_tree_submit → apply → pack），不再借旧桥造面。
桥行为格（stage1 关→BM25 回退、上游短盒信任）随桥一并删除。
"""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _c109_no_embed(monkeypatch):
    """单测不烧本机 embed；测量脚本默认开。"""
    monkeypatch.setenv("VERITAS_KG_STAGE1_EMBED", "0")
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.kg_stage1_pool import kg_stage1_enabled, stage1_pool_from_dossier
from app.core.kg_submit_surface import (
    FORBIDDEN_PACK_KEYS,
    apply_kg_submit_surface,
    audit_forbidden_keys,
    pack_kwargs_for_kg,
)


def _dossier() -> Dossier:
    d = Dossier(question="这笔49.4万元应认定为买断费还是自主择业经济补偿金，以哪方口径为准？")
    texts = [
        ("SRC1", "官方通报：按规定给予自主择业经济补偿金49.4万元。2024年3月12日10时30分许发布。"),
        ("SRC2", "当事人称这是买断费，不是补偿金，不愿走。"),
        ("SRC3", "今天天气晴朗，适合晾晒衣物。"),
        ("SRC4", "媒体：买断费与自主择业经济补偿金口径对立。"),
        ("SRC5", "体育局回应记者称按规定给予补偿。"),
    ]
    for sid, text in texts:
        src = Source.create(sid, SourceType.REPORT, id=sid)
        src.segments.append(Segment(id=f"{sid}#s1", source_id=sid, text=text))
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


def test_c109_stage1_default_on_env_off(monkeypatch):
    monkeypatch.delenv("VERITAS_KG_STAGE1", raising=False)
    assert Settings().kg_stage1 is True
    assert kg_stage1_enabled() is True
    monkeypatch.setenv("VERITAS_KG_STAGE1", "0")
    assert Settings.from_env().kg_stage1 is False
    assert kg_stage1_enabled() is False


def test_c109_export_only_pool_ids_no_coeff():
    d = _dossier()
    out = stage1_pool_from_dossier(d, pool_n=20)
    exp = out["export"]
    assert exp["layer"] == "stage1_pool"
    assert exp["pool_ids"]
    assert audit_forbidden_keys(exp) == []
    for bad in ("coeff", "feats", "weights", "multidim", "r9_coeff", "r21_coeff"):
        assert bad not in exp
        assert bad in FORBIDDEN_PACK_KEYS
    assert set(exp) <= {
        "schema_version", "layer", "pool_n", "pool_ids", "pool_ranked",
    }


def test_c109_pack_kwargs_never_take_stage1_coeffs(monkeypatch):
    """C-133 迁移：改走测试树共用面造面，不借旧桥。"""
    from app.core.kg_test_tree_line import ensure_test_tree_submit

    monkeypatch.delenv("VERITAS_KG_CAP_SEGMENTS", raising=False)
    _fake_embeddings(monkeypatch)
    d = _dossier()
    ensure_test_tree_submit(d)
    apply_kg_submit_surface(d, enabled=True)
    kw = pack_kwargs_for_kg(d)
    assert "coeff" not in kw and "weights" not in kw and "feats" not in kw
    assert audit_forbidden_keys(kw) == []
