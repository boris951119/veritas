"""C-48 件③：交件包默认不装 causal_evidence；--with-causal 才装。

真守护格（按"哪个数必须变"写，不许写走了哪条路径）：
  - n_causal_default 必须＝0
  - n_causal_with 必须≥1
  - |manifest_paths_with − manifest_paths_default| 的对称差
    必须且只许是各专题的 causal_evidence.json
摘掉 with_causal 开关／改成"靠文件不存在不装" ⇒ 上述数翻红。
零模型；不许墙钟绝对秒数断言。app/ 零字节。
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from app.core.confidence import recompute_all
from app.core.evidence import RelationKind
from tests.test_c32_causal_claim import _FULL_CLAIM, _add_ev, _base_dossier

ROOT = Path(__file__).resolve().parents[1]
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)%")


def _synth_run(tmp_path: Path) -> Path:
    d = _base_dossier()
    _add_ev(
        d,
        relation=RelationKind.CAUSATION,
        claim=dict(_FULL_CLAIM),
        mechanism="direct",
        design_tier="observational",
        quote="全固态电芯的中试良率尚不足百分之四十",
    )
    recompute_all(d, n_panel=1)
    run = tmp_path / "run"
    topic = run / "专题甲"
    qdir = topic / "questions" / "q1"
    qdir.mkdir(parents=True)
    data = d.to_dict()
    data["question"] = d.question
    (qdir / "report.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return run


def _manifest_paths(zf: zipfile.ZipFile) -> set[str]:
    text = zf.read("MANIFEST.txt").decode("utf-8")
    paths: set[str] = set()
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        # "sha256  path"
        parts = line.split(None, 1)
        if len(parts) == 2:
            paths.add(parts[1].strip())
    return paths


def _n_causal(names: list[str]) -> int:
    return sum(1 for n in names if n.endswith("causal_evidence.json"))


def test_c48_default_omits_causal_with_flag_packs_and_manifest_diff_only(tmp_path):
    """哪个数必须变：n_causal_in_zip（0↔≥1）；MANIFEST 路径集对称差只许因果件。"""
    from scripts.build_submission_zip import (
        CAUSAL_INCLUDE_STATUS,
        CAUSAL_JSON_NAME,
        build,
        format_causal_omit_status,
    )

    run = _synth_run(tmp_path)
    docs = [ROOT / "docs" / "deliverables"]

    zip_default = tmp_path / "default.zip"
    r0 = build(run, zip_default, docs, tmp_path / "work0", with_causal=False)
    zip_with = tmp_path / "with.zip"
    r1 = build(run, zip_with, docs, tmp_path / "work1", with_causal=True)

    with zipfile.ZipFile(zip_default) as z0, zipfile.ZipFile(zip_with) as z1:
        names0 = z0.namelist()
        names1 = z1.namelist()
        n_causal_default = _n_causal(names0)
        n_causal_with = _n_causal(names1)
        paths0 = _manifest_paths(z0)
        paths1 = _manifest_paths(z1)
        man0 = z0.read("MANIFEST.txt").decode("utf-8")
        man1 = z1.read("MANIFEST.txt").decode("utf-8")

    # 数必须变的两格
    assert n_causal_default == 0, n_causal_default
    assert n_causal_with >= 1, n_causal_with
    assert r0["n_causal_exported"] >= 1  # 导出面有＝不是靠文件不存在
    assert r0["n_causal_packed"] == 0
    assert r1["n_causal_packed"] >= 1

    # MANIFEST 路径集对称差只许 causal_evidence.json
    only_in_with = paths1 - paths0
    only_in_default = paths0 - paths1
    assert only_in_default == set(), only_in_default
    assert only_in_with, only_in_with
    assert all(p.endswith(CAUSAL_JSON_NAME) for p in only_in_with), only_in_with

    # 状态行进 MANIFEST 与返回值（C-49：省略原因＝当场探针读数，非常量）
    omit_live = format_causal_omit_status(run)
    assert omit_live in man0
    assert CAUSAL_INCLUDE_STATUS in man1
    assert r0["causal_status"] == omit_live
    assert r1["causal_status"] == CAUSAL_INCLUDE_STATUS
    assert "task #163" in man0 and "task #163" in man1
    assert "四要素非空率" in omit_live
    assert _PCT_RE.search(omit_live), omit_live


def test_c48_zip_script_exposes_with_causal_flag():
    src = (ROOT / "scripts" / "build_submission_zip.py").read_text(encoding="utf-8")
    assert "--with-causal" in src
    assert "format_causal_omit_status" in src
    assert "task #163" in src
    # 不许用文件不存在实现不装：必须有导出后存在性检查
    assert "口径开关不能靠文件不存在" in src
    # C-49：不许再把省略原因写死成常量 0%
    assert "四要素非空率 0%" not in src
