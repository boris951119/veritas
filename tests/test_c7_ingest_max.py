"""C-7：摄取目录封顶可配（默认 500／深度 3），非法值回落＋披露。

零 LLM。长期约束写成对源码／settings 的内容断言（禁工作树瞬时状态串）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.base import Analyst
from app.config import Settings
from app.ingest.case_loader import (
    _collect_files,
    count_case_files,
    load_case,
)
from app.ingest.import_case import (
    CaseImportError,
    append_imported_files,
    classify_import_path,
    resolve_case_file,
    write_imported_case,
)
from app.pipeline import RunDeps, RunSpec, run_case
from tests.test_agents_pipeline import GOOD_BAD_JSON, FakeClient

ROOT = Path(__file__).resolve().parents[1]


def _blank_json(monkeypatch) -> None:
    """避开仓库根 config.json，从代码默认再叠 env。"""

    def _blank(cls, path=None):
        return cls()

    monkeypatch.setattr(Settings, "from_json", classmethod(_blank))


def _case(tmp_path: Path, name: str = "c7") -> Path:
    case_dir = tmp_path / "cases" / name
    case_dir.mkdir(parents=True)
    (case_dir / "manifest.yaml").write_text(
        "question: C-7 封顶可配？\ntitle: C-7\n", encoding="utf-8")
    return case_dir


def _n_md(case_dir: Path, n: int) -> None:
    for i in range(n):
        (case_dir / f"f{i:04d}.md").write_text(
            f"材料{i}。补充句保证非空。\n", encoding="utf-8")


# -- a -------------------------------------------------------------------


def test_a_env_800_takes_800_skips_3(tmp_path, monkeypatch):
    """VERITAS_INGEST_MAX_FILES=800＋803 份 → taken=800／skipped=3，披露 max_files==800。"""
    _blank_json(monkeypatch)
    monkeypatch.delenv("VERITAS_INGEST_MAX_FILES", raising=False)
    monkeypatch.delenv("VERITAS_INGEST_MAX_DEPTH", raising=False)
    monkeypatch.setenv("VERITAS_INGEST_MAX_FILES", "800")
    case_dir = _case(tmp_path)
    _n_md(case_dir, 803)
    d = load_case(case_dir)
    notes = [n for n in d.ingest_notes if n.get("kind") == "dir_truncated"]
    assert len(notes) == 1
    note = notes[0]
    assert note["taken"] == 800
    assert note["skipped"] == 3
    assert note["max_files"] == 800
    assert note["files_capped"] is True
    assert len(d.sources) == 800


# -- b -------------------------------------------------------------------


def test_b_default_unchanged_regression(tmp_path, monkeypatch):
    """不设 env ⇒ taken=500、六个字段与今日行为全等（存量 4 条不许动）。"""
    _blank_json(monkeypatch)
    monkeypatch.delenv("VERITAS_INGEST_MAX_FILES", raising=False)
    monkeypatch.delenv("VERITAS_INGEST_MAX_DEPTH", raising=False)
    case_dir = _case(tmp_path)
    _n_md(case_dir, 501)
    d = load_case(case_dir)
    notes = [n for n in d.ingest_notes if n.get("kind") == "dir_truncated"]
    assert len(notes) == 1
    note = notes[0]
    assert note["taken"] == 500
    assert note["skipped"] == 1
    assert note["max_files"] == 500
    assert note["max_depth"] == 3
    assert note["files_capped"] is True
    assert note["depth_capped"] is False
    assert "按文件名排序取前 500" in note["detail"]
    assert "另有 1 个文件" in note["detail"]
    # 存量文件名逐字保留、collect 仍为 4
    stock = (ROOT / "tests/test_collect_files_cap.py").read_text(encoding="utf-8")
    for name in (
        "test_max_files_triggers_dir_truncated_disclosure",
        "test_max_depth_triggers_dir_truncated_disclosure",
        "test_no_cap_no_dir_truncated_disclosure",
        "test_depth4_all_png_still_dir_truncated",
    ):
        assert f"def {name}" in stock
    assert stock.count("\ndef test_") == 4


# -- c -------------------------------------------------------------------


def test_c_depth_5_no_cap_depth_3_caps(tmp_path, monkeypatch):
    """DEPTH=5 ⇒ 第 4 层不 depth_capped；设回 3 ⇒ 必出（两向）。"""
    _blank_json(monkeypatch)
    monkeypatch.delenv("VERITAS_INGEST_MAX_FILES", raising=False)
    case_dir = _case(tmp_path, "depth")
    (case_dir / "根.md").write_text("根层。", encoding="utf-8")
    deep = case_dir / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "深.md").write_text("第 4 层材料。", encoding="utf-8")

    monkeypatch.setenv("VERITAS_INGEST_MAX_DEPTH", "5")
    d5 = load_case(case_dir)
    assert not any(n.get("kind") == "dir_truncated" for n in d5.ingest_notes)
    titles5 = {s.title for s in d5.sources}
    assert "深" in titles5

    monkeypatch.setenv("VERITAS_INGEST_MAX_DEPTH", "3")
    d3 = load_case(case_dir)
    notes = [n for n in d3.ingest_notes if n.get("kind") == "dir_truncated"]
    assert len(notes) == 1
    assert notes[0]["depth_capped"] is True
    assert "深" not in {s.title for s in d3.sources}


# -- d：导入侧四个函数各一格 ---------------------------------------------


def test_d_classify_import_path_follows_depth(monkeypatch):
    _blank_json(monkeypatch)
    monkeypatch.setenv("VERITAS_INGEST_MAX_DEPTH", "5")
    # 顶层名 + 5 层 = 6 parts → 刚好到上限；7 parts 拒
    ok, reason = classify_import_path("top/a/b/c/d/e.md")
    assert reason is None and ok == "top/a/b/c/d/e.md"
    _, reason2 = classify_import_path("top/a/b/c/d/e/f.md")
    assert reason2 == "deep_path"

    monkeypatch.setenv("VERITAS_INGEST_MAX_DEPTH", "3")
    _, reason3 = classify_import_path("top/a/b/c/d.md")
    assert reason3 == "deep_path"


def test_d_resolve_case_file_follows_depth(tmp_path, monkeypatch):
    _blank_json(monkeypatch)
    case_dir = _case(tmp_path, "resolve")
    deep = case_dir / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "x.md").write_text("x", encoding="utf-8")
    monkeypatch.setenv("VERITAS_INGEST_MAX_DEPTH", "5")
    assert resolve_case_file(case_dir, "a/b/c/d/x.md") is not None
    monkeypatch.setenv("VERITAS_INGEST_MAX_DEPTH", "3")
    assert resolve_case_file(case_dir, "a/b/c/d/x.md") is None


def test_d_append_refuse_message_follows_files(tmp_path, monkeypatch):
    """append 路径：拒收文案数字跟生效值（超过 7）。"""
    _blank_json(monkeypatch)
    monkeypatch.setenv("VERITAS_INGEST_MAX_FILES", "7")
    root = tmp_path / "cases"
    root.mkdir()
    meta = write_imported_case(root, [
        (f"f{i}.md", f"体{i}".encode()) for i in range(5)
    ], question="议题")
    case = root / meta["case"]
    with pytest.raises(CaseImportError) as ei:
        append_imported_files(case, [
            (f"extra{i}.md", b"more") for i in range(5)
        ])
    msg = str(ei.value)
    assert "超过 7" in msg
    assert "请先删一批再添加" in msg
    assert "超过 500" not in msg


def test_d_write_refuse_message_follows_files(tmp_path, monkeypatch):
    """write_imported_case 路径：拒收文案数字跟生效值（超过 7）。

    _filter_items 会先拦，故此处替掉 filter 只测 write 那句「请先拆开再添加」。
    """
    _blank_json(monkeypatch)
    monkeypatch.setenv("VERITAS_INGEST_MAX_FILES", "7")
    root = tmp_path / "cases"
    root.mkdir()

    def _pass_through(items, *, existing=0, total=0):
        return (list(items), [], [])

    monkeypatch.setattr(
        "app.ingest.import_case._filter_items", _pass_through)
    with pytest.raises(CaseImportError) as ei:
        write_imported_case(root, [
            (f"f{i}.md", f"体{i}".encode()) for i in range(10)
        ], question="议题")
    msg = str(ei.value)
    assert "超过 7" in msg
    assert "请先拆开再添加" in msg
    assert "超过 500" not in msg


# -- e -------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["0", "abc", "-5"])
def test_e_env_invalid_files_falls_back_500(raw, monkeypatch):
    _blank_json(monkeypatch)
    monkeypatch.setenv("VERITAS_INGEST_MAX_FILES", raw)
    s = Settings.from_env()
    assert s.ingest_max_files == 500
    blob = "｜".join(s.ingest_max_disclosures)
    assert "回落 500" in blob
    assert "env VERITAS_INGEST_MAX_FILES" in blob


@pytest.mark.parametrize("raw", ["0", "abc", "-3"])
def test_e_env_invalid_depth_falls_back_3(raw, monkeypatch):
    _blank_json(monkeypatch)
    monkeypatch.setenv("VERITAS_INGEST_MAX_DEPTH", raw)
    s = Settings.from_env()
    assert s.ingest_max_depth == 3
    blob = "｜".join(s.ingest_max_disclosures)
    assert "回落 3" in blob
    assert "env VERITAS_INGEST_MAX_DEPTH" in blob


@pytest.mark.parametrize("raw", [0, "500", -5])
def test_e_config_json_invalid_files_falls_back_500(raw, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"ingest_max_files": raw}), encoding="utf-8")
    s = Settings.from_json(cfg)
    assert s.ingest_max_files == 500
    blob = "｜".join(s.ingest_max_disclosures)
    assert "回落 500" in blob
    assert "config.json" in blob


@pytest.mark.parametrize("raw", [0, "3", -2])
def test_e_config_json_invalid_depth_falls_back_3(raw, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"ingest_max_depth": raw}), encoding="utf-8")
    s = Settings.from_json(cfg)
    assert s.ingest_max_depth == 3
    blob = "｜".join(s.ingest_max_disclosures)
    assert "回落 3" in blob
    assert "config.json" in blob


# -- f -------------------------------------------------------------------


def test_f_count_case_files_aligns_non_default(tmp_path, monkeypatch):
    """非默认封顶下 count_case_files == taken；源码承诺同一截断。"""
    _blank_json(monkeypatch)
    monkeypatch.setenv("VERITAS_INGEST_MAX_FILES", "800")
    case_dir = _case(tmp_path, "align")
    _n_md(case_dir, 803)
    collected = _collect_files(case_dir)
    assert collected.taken == 800
    assert count_case_files(case_dir) == collected.taken == 800
    src = (ROOT / "app/ingest/case_loader.py").read_text(encoding="utf-8")
    # 反向自证锚：count 必须只委托 _collect_files，不得硬编码 500
    assert "return len(_collect_files(Path(case_dir)).files)" in src
    # 若有人把 count 改成恒返回 500，本格对齐断言必红（开发期刀测已确认）


# -- g -------------------------------------------------------------------


def test_g_run_case_report_md_shows_fallback(tmp_path, monkeypatch):
    """非法值跑完整 run_case：report.md「输入分诊账本」可读到回落 500。"""
    _blank_json(monkeypatch)
    monkeypatch.setenv("VERITAS_INGEST_MAX_FILES", "0")
    case_dir = _case(tmp_path, "run")
    (case_dir / "a.md").write_text(
        "固态电池的能量密度显著高于液态锂离子电池，但成本仍高于预期。\n",
        encoding="utf-8",
    )
    out = case_dir / "out"
    fake = FakeClient(GOOD_BAD_JSON)
    single = [Analyst("mainstream", "测", fake, "m")]
    result = run_case(
        RunSpec(case_dir=case_dir, out_dir=out, probe=False),
        RunDeps(client=fake, analysts=single),
    )
    report_md = (out / "report.md").read_text(encoding="utf-8")
    assert "输入分诊账本" in report_md
    assert "回落 500" in report_md
    # 点名 report.md（跨面复用模板时名词要点工件）
    assert any(
        "回落 500" in (t.get("reason") or "")
        for t in (result.dossier.triage or [])
    )


# -- R1：ingest_cap 必须登记进 ROUTE_LABEL ---------------------------------


def test_r1_ingest_cap_registered_chinese_label(tmp_path, monkeypatch):
    """非法 FILES=0 → triage.route 在 ROUTE_LABEL 内，渲染标签＝「封顶回落」非裸键。"""
    from app.ingest.triage import ROUTE_LABEL
    from app.pipeline import _render_triage_ledger

    _blank_json(monkeypatch)
    monkeypatch.setenv("VERITAS_INGEST_MAX_FILES", "0")
    case_dir = _case(tmp_path, "r1")
    (case_dir / "a.md").write_text("材料正文一句。\n", encoding="utf-8")
    d = load_case(case_dir)
    caps = [t for t in d.triage if t.get("route") == "ingest_cap"]
    assert caps, "非法封顶须落 ingest_cap triage 行"
    for t in caps:
        route = t["route"]
        assert route in ROUTE_LABEL
        assert ROUTE_LABEL[route] == "封顶回落"
    lines: list[str] = []
    _render_triage_ledger(lines, d)
    blob = "\n".join(lines)
    assert "封顶回落" in blob
    assert "**ingest_cap**" not in blob


# -- h / i / j -----------------------------------------------------------


def test_h_no_worktree_diff_probe_in_this_file():
    """判据 h：本单测试文件不得出现工作树 diff 探测串。"""
    text = Path(__file__).read_text(encoding="utf-8")
    assert "git" + " diff" not in text


def test_i_disclosure_names_report_md_artifact():
    """新渲染句对所在面为真：report.md 分诊账本读得到回落句（见 g）；
    源码侧 triage reason 直接带披露原文，跨面复用时点名工件。"""
    src = (ROOT / "app/ingest/case_loader.py").read_text(encoding="utf-8")
    assert 'route": "ingest_cap"' in src
    assert '"kind": "ingest_cap"' in src
    this = Path(__file__).read_text(encoding="utf-8")
    assert "report.md" in this


def test_j_env_names_appear_in_tree():
    """基数格：VERITAS_INGEST_MAX_* 改前 0 ⇒ 改后 ≥1（内容断言）。"""
    hits = []
    for base in (ROOT / "app", ROOT / "tests", ROOT / "scripts"):
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix == ".pyc":
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if ("VERITAS_INGEST_MAX_FILES" in text
                    or "VERITAS_INGEST_MAX_DEPTH" in text):
                hits.append(str(p.relative_to(ROOT)))
    assert len(hits) >= 1
    assert any("config.py" in h for h in hits)


def test_constants_remain_defaults_only():
    """import_case MAX_* 只留作默认值常量，不得再当阈值（源码内容断言）。"""
    src = (ROOT / "app/ingest/import_case.py").read_text(encoding="utf-8")
    assert "MAX_FILES = 500" in src
    assert "MAX_DEPTH = 3" in src
    assert "def _ingest_limits()" in src
    # 运行时阈值走 _ingest_limits；定义行之后不得再出现裸 MAX_FILES／MAX_DEPTH
    body = src.split("def _ingest_limits()", 1)[1]
    assert "MAX_FILES" not in body
    assert "MAX_DEPTH" not in body
    assert "len(parts) > max_depth + 1" in src
    assert "existing + len(kept) >= max_files" in src
    assert "len(kept) > max_files" in src
    assert "超过 {max_files}" in src
