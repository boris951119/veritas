"""C-24：可靠性曲线／ECE／缺 label 门／候选清单／件⑤ 三格守护。"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "calibrate_confidence.py"
TABLE_SCRIPT = ROOT / "scripts" / "check_markdown_tables.py"
CANDIDATES = ROOT / "calibration" / "candidates_self.jsonl"
PY = ROOT / ".venv" / "bin" / "python"
if not PY.is_file():
    PY = Path(sys.executable)

# 可 import 的纯函数
sys.path.insert(0, str(ROOT / "scripts"))
from calibrate_confidence import (  # noqa: E402
    BIN_EDGES,
    compute_curve,
    label_accuracy,
)


def _run(args: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PY), str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def _write_labels(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _row(score: float, label: str = "对", **kw) -> dict:
    base = {
        "case": "cases/bi-delivery-risk",
        "conclusion_id": kw.pop("conclusion_id", f"CON-{score}-{label}"),
        "statement_sha8": kw.pop("statement_sha8", "abcd1234"),
        "score": score,
        "band": "低",
        "band_rel": "低",
        "label": label,
        "labeled_by": kw.pop("labeled_by", "fixture"),
    }
    base.update(kw)
    return base


# ---------- a ----------
def test_a_help_and_labels_required():
    help_p = _run(["--help"])
    assert help_p.returncode == 0
    assert "labels" in help_p.stdout.lower() or "--labels" in help_p.stdout
    no = _run([])
    assert no.returncode != 0
    err = (no.stderr + no.stdout)
    assert "labels" in err.lower() or "--labels" in err
    assert "自家" in err or "cases/" in err


# ---------- b1 ----------
def test_b1_empty_label_errors(tmp_path: Path):
    p = _write_labels(tmp_path / "empty_label.jsonl", [
        _row(0.3, label=""),
    ])
    # _row always sets label; write raw
    p.write_text(
        json.dumps({
            "case": "cases/bi-delivery-risk",
            "conclusion_id": "c1",
            "statement_sha8": "a1",
            "score": 0.3,
            "label": "",
            "labeled_by": "x",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    r = _run(["--labels", str(p), "--out-dir", str(tmp_path / "o")])
    assert r.returncode != 0
    assert "label" in (r.stderr + r.stdout).lower() or "空" in (r.stderr + r.stdout)


def test_b1_missing_label_key_errors(tmp_path: Path):
    row = {
        "case": "cases/bi-delivery-risk",
        "conclusion_id": "c1",
        "statement_sha8": "a1",
        "score": 0.3,
        "labeled_by": "x",
        # 整行缺 label 键
    }
    p = tmp_path / "missing_key.jsonl"
    p.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    r = _run(["--labels", str(p), "--out-dir", str(tmp_path / "o")])
    assert r.returncode != 0
    assert "label" in (r.stderr + r.stdout)


def test_b1_empty_labeled_by_errors(tmp_path: Path):
    p = tmp_path / "empty_by.jsonl"
    p.write_text(
        json.dumps({
            "case": "cases/bi-delivery-risk",
            "conclusion_id": "c1",
            "statement_sha8": "a1",
            "score": 0.3,
            "label": "对",
            "labeled_by": "",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    r = _run(["--labels", str(p), "--out-dir", str(tmp_path / "o")])
    assert r.returncode != 0
    assert "labeled_by" in (r.stderr + r.stdout)


# ---------- b2 ----------
def test_b2_candidates_self_set_and_no_official():
    assert CANDIDATES.is_file()
    lines = [l for l in CANDIDATES.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) >= 60
    for i, line in enumerate(lines):
        obj = json.loads(line)
        case = obj["case"]
        assert case.startswith("cases/") or case.startswith("eval/"), case
        assert obj.get("label", "") == ""
        assert obj.get("labeled_by", "") == ""
        assert "statement_sha8" in obj
        assert len(line.encode("utf-8")) <= 512
    blob = CANDIDATES.read_text(encoding="utf-8")
    for bad in ("s4runs", "veritas-testcases", "Desktop"):
        assert bad not in blob


# ---------- c ----------
def _fixture_rows_spread() -> list[dict]:
    """每档至少若干条，总和已知；含一档 <5 以测 insufficient。"""
    rows: list[dict] = []
    # 0.0-0.2: 6 条全对
    for i in range(6):
        rows.append(_row(0.05 + i * 0.02, "对", conclusion_id=f"lo-{i}"))
    # 0.2-0.4: 6 条
    for i in range(6):
        rows.append(_row(0.25 + i * 0.02, "对", conclusion_id=f"a-{i}"))
    # 0.4-0.6: 6 条
    for i in range(6):
        rows.append(_row(0.45 + i * 0.02, "部分", conclusion_id=f"b-{i}"))
    # 0.6-0.8: 3 条 → insufficient
    for i in range(3):
        rows.append(_row(0.65 + i * 0.02, "对", conclusion_id=f"c-{i}"))
    # 0.8-1.0: 6 条
    for i in range(6):
        rows.append(_row(0.85 + i * 0.02, "对", conclusion_id=f"hi-{i}"))
    return rows


def test_c_bin_sum_and_insufficient(tmp_path: Path):
    rows = _fixture_rows_spread()
    p = _write_labels(tmp_path / "lab.jsonl", rows)
    out = tmp_path / "curve_out"
    r = _run(["--labels", str(p), "--out-dir", str(out)])
    assert r.returncode == 0, r.stderr
    curve = json.loads((out / "curve.json").read_text(encoding="utf-8"))
    assert sum(b["n"] for b in curve["bins"]) == len(rows)
    assert len(curve["bins"]) == len(BIN_EDGES)
    insuff = [b for b in curve["bins"] if b["n"] > 0 and b.get("insufficient")]
    assert insuff, "expected at least one insufficient bin"
    for b in insuff:
        assert "accuracy" not in b
        assert "accuracy_pct" not in b
    ok = [b for b in curve["bins"] if b["n"] >= 5]
    assert ok
    for b in ok:
        assert "accuracy_pct" in b


# ---------- d reverse + self-proof ----------
def test_d_flip_labels_drops_accuracy(tmp_path: Path):
    rows = _fixture_rows_spread()
    # 锁定 0.0-0.2 箱
    base = compute_curve(rows)
    lo = next(b for b in base["bins"] if b["bin"] == "0.0-0.2")
    assert not lo.get("insufficient")
    acc0 = lo["accuracy"]

    flipped = []
    for r in rows:
        rr = dict(r)
        if 0.0 <= rr["score"] < 0.2:
            rr["label"] = "错"
        flipped.append(rr)
    after = compute_curve(flipped)
    lo2 = next(b for b in after["bins"] if b["bin"] == "0.0-0.2")
    assert lo2["accuracy"] < acc0


def test_d_identity_impl_must_fail_self_proof():
    """自证：若曲线用 score 反推准确率（恒等作弊），本格必红。"""
    rows = _fixture_rows_spread()
    # 作弊实现：accuracy := mean(score)
    def bogus_curve(rs):
        from collections import defaultdict
        buckets = defaultdict(list)
        for r in rs:
            # reuse bin_index
            from calibrate_confidence import bin_index
            buckets[bin_index(r["score"])].append(r)
        bins = []
        for i, (name, lo, hi) in enumerate(BIN_EDGES):
            xs = buckets[i]
            bn = len(xs)
            entry = {"bin": name, "n": bn, "insufficient": bn < 5}
            if bn:
                # 作弊：拿 score 当准确率
                entry["accuracy"] = sum(x["score"] for x in xs) / bn
                if bn >= 5:
                    entry["accuracy_pct"] = 100.0 * entry["accuracy"]
            bins.append(entry)
        return {"bins": bins, "n": len(rs)}

    real = compute_curve(rows)
    fake = bogus_curve(rows)
    # 构造：把某低分箱 label 全改成错后，真实现准确率掉、作弊实现几乎不动
    flipped = []
    for r in rows:
        rr = dict(r)
        if 0.0 <= rr["score"] < 0.2:
            rr["label"] = "错"
        flipped.append(rr)
    real2 = compute_curve(flipped)
    fake2 = bogus_curve(flipped)
    lo_real_drop = (
        next(b for b in real["bins"] if b["bin"] == "0.0-0.2")["accuracy"]
        - next(b for b in real2["bins"] if b["bin"] == "0.0-0.2")["accuracy"]
    )
    lo_fake_drop = (
        next(b for b in fake["bins"] if b["bin"] == "0.0-0.2")["accuracy"]
        - next(b for b in fake2["bins"] if b["bin"] == "0.0-0.2")["accuracy"]
    )
    assert lo_real_drop > 0.5  # 全改成错，从 ~1.0 掉到 0
    assert lo_fake_drop == 0.0  # 作弊实现不读 label
    # 本格本身断言：真实现必须读 label（与作弊可区分）
    assert lo_real_drop > lo_fake_drop + 0.4


# ---------- e ECE hand calc ----------
def test_e_ece_matches_hand_calc():
    rows = _fixture_rows_spread()
    curve = compute_curve(rows)
    n = len(rows)
    # 手算
    from calibrate_confidence import bin_index, label_accuracy as la
    members = [[] for _ in BIN_EDGES]
    for r in rows:
        members[bin_index(r["score"])].append(r)
    ece = 0.0
    for xs in members:
        bn = len(xs)
        if bn == 0:
            continue
        acc = sum(la(x["label"]) for x in xs) / bn
        mean_c = sum(float(x["score"]) for x in xs) / bn
        ece += (bn / n) * abs(acc - mean_c)
    assert abs(curve["ece"] - ece) <= 1e-6


# ---------- f proposal 两套口径分列 ----------
def test_f_proposals_split_calibers_and_placeholder():
    prop = (ROOT / "docs" / "proposal.md").read_text(encoding="utf-8")
    formal = (ROOT / "docs" / "proposal-formal.md").read_text(encoding="utf-8")
    for text, name in ((prop, "proposal.md"), (formal, "proposal-formal.md")):
        assert "待 #38" in text or "#38" in text, name
        assert "自标定" in text, name
        # 不许把 11%/61% 与自标定平均成一个「正确率」
        assert "11%/61%" not in text.replace(" ", "")
        assert "平均为" not in text and "取平均" not in text
        assert "禁止" in text and ("分列" in text or "两套" in text)
    # 结构性结论
    blob = prop + formal
    assert "高档" in blob
    assert "渐近" in blob or "结构性" in blob or "天然为空" in blob


# ---------- g：本单测文件禁止版本对照型瞬时断言 ----------
def test_g_no_vcs_diff_instant_assert_in_c24_tests():
    src = Path(__file__).read_text(encoding="utf-8")
    needle = "git" + " " + "diff"
    assert needle not in src
    assert src.count(needle) == 0


# ---------- h 件⑤ ----------
def test_h_markdown_tables_ok_and_mismatch_errors(tmp_path: Path):
    r = subprocess.run(
        [str(PY), str(TABLE_SCRIPT), str(ROOT / "docs"), *sorted(str(p) for p in ROOT.glob("*.md"))],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "mismatched=0" in r.stdout
    # h① 内容：docstring 不得再钉 23／93 这类会随树漂移的绝对基准（不变式只钉 mismatched==0）
    doc = TABLE_SCRIPT.read_text(encoding="utf-8")
    assert "23 文件" not in doc
    assert "93 张" not in doc

    bad = tmp_path / "bad.md"
    bad.write_text(
        "# t\n\n| a | b |\n|---|---|\n| 1 | 2 | 3 |\n",
        encoding="utf-8",
    )
    r2 = subprocess.run(
        [str(PY), str(TABLE_SCRIPT), str(bad)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert r2.returncode != 0
    assert "MISMATCH" in r2.stdout or "mismatched=1" in r2.stdout


def test_h_parse_drops_no_vcs_diff_concat():
    src = (ROOT / "tests" / "test_parse_drops.py").read_text(encoding="utf-8")
    needle = "git" + " " + "diff"
    assert needle not in src
    assert '["git", "diff"' not in src
    assert "['git', 'diff'" not in src


def test_h_cli_errors_has_venv_skip_guard():
    src = (ROOT / "tests" / "test_c25_errors_sensitivity.py").read_text(encoding="utf-8")
    assert "venv" in src
    assert "pytest.skip" in src
    assert "test_cli_errors_flag" in src
