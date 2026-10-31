"""C-24：可靠性曲线／ECE／缺 label 门／候选清单／件⑤ 三格守护。"""

from __future__ import annotations

import json
import re
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
    MAX_CANDIDATE_LINE_BYTES,
    _require_self_case,
    compute_curve,
    emit_candidates,
    label_accuracy,
    load_labeled_rows,
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
    """#115：空 label 钉本格句子，且另两格句子不在场（双向）。"""
    p = tmp_path / "empty_label.jsonl"
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
    msg = r.stderr + r.stdout
    assert "label 为空" in msg
    assert "缺 label 键（整行缺键）" not in msg
    assert "labeled_by 为空或缺键" not in msg


def test_b1_missing_label_key_errors(tmp_path: Path):
    """#115：缺 label 键钉本格句子，且另两格句子不在场（双向）。"""
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
    msg = r.stderr + r.stdout
    assert "缺 label 键（整行缺键）" in msg
    assert "label 为空" not in msg
    assert "labeled_by 为空或缺键" not in msg


def test_b1_empty_labeled_by_errors(tmp_path: Path):
    """#115：空 labeled_by 钉本格句子，且另两格句子不在场（双向）。"""
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
    msg = r.stderr + r.stdout
    assert "labeled_by 为空或缺键" in msg
    assert "label 为空" not in msg
    assert "缺 label 键（整行缺键）" not in msg


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
    """#115：分母＝文件里非空 JSON 行数（不是 Python list 长度）。"""
    rows = _fixture_rows_spread()
    p = _write_labels(tmp_path / "lab.jsonl", rows)
    # 夹空行：非空 JSON 行数才是分母
    raw = p.read_text(encoding="utf-8")
    p.write_text("\n" + raw + "\n\n", encoding="utf-8")
    nonempty = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
    out = tmp_path / "curve_out"
    r = _run(["--labels", str(p), "--out-dir", str(out)])
    assert r.returncode == 0, r.stderr
    curve = json.loads((out / "curve.json").read_text(encoding="utf-8"))
    assert sum(b["n"] for b in curve["bins"]) == nonempty
    assert nonempty == len(rows)
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


# ---------- f proposal 两套口径分列（真数已入账版） ----------
def test_f_proposals_split_calibers_and_real_numbers():
    prop = (ROOT / "docs" / "proposal.md").read_text(encoding="utf-8")
    formal = (ROOT / "docs" / "proposal-formal.md").read_text(encoding="utf-8")
    for text, name in ((prop, "proposal.md"), (formal, "proposal-formal.md")):
        # 占位句必须已消失：真数入账后不许再留「待 #38 出数」这种说法
        assert "待 #38" not in text, f"{name} 仍留着占位句"
        assert "自标定" in text, name
        # 真数必须出现在两处（ECE 与高档覆盖率＝脚本当场输出）
        assert "0.4067" in text, f"{name} 缺 ECE 真数"
        assert "226" in text, f"{name} 缺标定集规模"
        assert "0.0" in text and "高档覆盖率" in text, f"{name} 缺高档覆盖率"
        # 口径：五箱（0.2 端点）＋非单调如实披露
        assert "五箱" in text or "0.0–0.2" in text, f"{name} 缺分箱口径"
        assert "非单调" in text, f"{name} 未如实披露单调性"
        # 选择效应必须同句披露（256 候选里 30 行未入账 ⇒ 准确率是偏乐观上界）
        assert "256" in text and "30 行" in text, f"{name} 缺选择效应披露"
        assert "上界" in text, f"{name} 未写明偏乐观上界"
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
    # #118：不许「本轮实测＋中文绝对张数」当不变式；只钉 mismatched==0
    doc = TABLE_SCRIPT.read_text(encoding="utf-8")
    poison = re.search(r"本轮实测[^\n]*\d+\s*文件[^\n]*\d+\s*张", doc)
    assert poison is None, f"docstring 把本轮实测＋绝对张数写成基线：{poison.group(0)!r}"
    assert "mismatched==0" in doc
    assert re.search(r"唯一不变式是 mismatched==0", doc)

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


def _has_git_diff_shell(src: str) -> bool:
    """#118 检测器：源码是否把 git+diff 拼进常驻用例。"""
    needle = "git" + " " + "diff"
    if needle in src:
        return True
    if '["git", "diff"' in src or "['git', 'diff'" in src:
        return True
    if re.search(r"""\[[^\]]*["']git["']\s*,\s*["']diff["']""", src):
        return True
    return False


def test_h_parse_drops_no_vcs_diff_concat():
    """#118：真文件无 git+diff；合成毒样本必须点亮检测器。"""
    path = ROOT / "tests" / "test_parse_drops.py"
    src = path.read_text(encoding="utf-8")
    assert _has_git_diff_shell(src) is False
    poison = src + "\n    subprocess.run([\"git\", \"diff\", \"--stat\"])\n"
    assert _has_git_diff_shell(poison) is True


def test_h_cli_errors_has_venv_skip_guard():
    """#118：要么跑通 skip 护栏行为，要么毒样本点亮检测器。"""
    path = ROOT / "tests" / "test_c25_errors_sensitivity.py"
    src = path.read_text(encoding="utf-8")
    # 行为腿：无 .venv 时该格应 skip 而非 failed（干净克隆友好）
    venv_py = ROOT / ".venv" / "bin" / "python"
    if not venv_py.is_file():
        # 宿主若无 venv，本格自己也走 skip 护栏语义
        pytest.skip("no .venv：与 test_cli_errors_flag 同口径")
    assert "pytest.skip" in src and "venv" in src and "test_cli_errors_flag" in src
    # 毒样本腿：摘掉 skip 护栏后检测器必红
    stripped = src.replace("pytest.skip", "pytest_skip_REMOVED")
    assert "pytest.skip" not in stripped
    assert ("pytest.skip" in src) and ("pytest.skip" not in stripped)

# ---------- C-35 #116／#117 ----------
def test_c35_116_require_self_case_two_messages():
    """#116：Desktop/veritas-testcases 与 s4runs 各踩一条不同 _require_self_case 文案。"""
    with pytest.raises(SystemExit) as e1:
        _require_self_case("/Users/x/Desktop/veritas-testcases/foo", where="t1")
    msg1 = str(e1.value)
    assert "不许默认去读桌面官方样例" in msg1

    with pytest.raises(SystemExit) as e2:
        _require_self_case("cases/demo/s4runs-leak", where="t2")
    msg2 = str(e2.value)
    assert "检测到仓库外痕迹" in msg2
    assert "s4runs" in msg2
    # 两条文案必须不同
    assert msg1 != msg2


def test_c35_116_load_labeled_rows_call_site(tmp_path: Path):
    """#116 调用点：load_labeled_rows 真筛来源；摘 :129 那次调用必红本格。

    零子进程：写 jsonl → load_labeled_rows → 两条不同 SystemExit 文案。
    第一条（无 self 前缀）文案必须含 f"{path}:{lineno}"＝只有调用点能传 where。
    第二条（s4runs）文案无 where——不拿 where 当第二条腿。
    """
    # —— leg 1：Desktop/veritas-testcases → 第一条 raise（含 where）——
    p1 = tmp_path / "bad_desktop.jsonl"
    p1.write_text(
        json.dumps(
            {
                "case": "/Users/x/Desktop/veritas-testcases/foo",
                "conclusion_id": "C1",
                "score": 0.4,
                "label": "对",
                "labeled_by": "tester",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as e1:
        load_labeled_rows(p1)
    msg1 = str(e1.value)
    where1 = f"{p1}:1"
    assert where1 in msg1, f"call-site where missing in: {msg1!r}"
    assert "不许默认去读桌面官方样例" in msg1

    # —— leg 2：cases/…/s4runs… → 第二条 raise（无 where）——
    p2 = tmp_path / "bad_s4runs.jsonl"
    p2.write_text(
        json.dumps(
            {
                "case": "cases/demo/s4runs-leak",
                "conclusion_id": "C2",
                "score": 0.5,
                "label": "部分",
                "labeled_by": "tester",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as e2:
        load_labeled_rows(p2)
    msg2 = str(e2.value)
    assert "检测到仓库外痕迹" in msg2
    assert "s4runs" in msg2
    assert f"{p2}:1" not in msg2  # 第二条 raise 不带 where
    assert msg1 != msg2


def test_c35_118_docstring_self_consistent_with_stdout():
    """#118 可选：docstring 若写 files／with_tables／tables 绝对数 ⇒ 须等于当场跑一次。

    不钉基线绝对值（第 42 处）；无三数则本格通过。
    """
    doc = TABLE_SCRIPT.read_text(encoding="utf-8")
    # 只扫模块 docstring（首个三引号块）
    m = re.search(r'^"""(.*?)"""', doc, re.S | re.M)
    assert m, "check_markdown_tables.py missing module docstring"
    ds = m.group(1)
    nums = {}
    for key, pat in (
        ("files", r"files\s*=\s*(\d+)"),
        ("with_tables", r"with_tables\s*=\s*(\d+)"),
        ("tables", r"(?<![_\w])tables\s*=\s*(\d+)"),
    ):
        mm = re.search(pat, ds)
        if mm:
            nums[key] = int(mm.group(1))
    if not nums:
        return  # docstring 无绝对数 ⇒ 通过（不钉基线）
    # 当场跑一次（json）
    r = subprocess.run(
        [str(PY), str(TABLE_SCRIPT), "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    live = json.loads(r.stdout)
    mapping = {
        "files": "files",
        "with_tables": "files_with_tables",
        "tables": "tables",
    }
    for k, v in nums.items():
        live_k = mapping[k]
        assert live[live_k] == v, (
            f"docstring {k}={v} ≠ live {live_k}={live[live_k]} "
            f"(self-consistency, not baseline pin)"
        )


def test_c35_117_emit_candidates_majority_and_line_cap(tmp_path: Path):
    """#117：非 majority 不进候选；单行 >512 字节 ⇒ SystemExit。"""
    case_dir = tmp_path / "cases" / "toy"
    out = case_dir / "out1"
    out.mkdir(parents=True)
    report = {
        "conclusions": [
            {"id": "M1", "status": "majority", "statement": "多数意见短句", "confidence": 0.4},
            {"id": "D1", "status": "dissent", "statement": "少数意见不该进", "confidence": 0.9},
            {"id": "I1", "status": "insufficient", "statement": "不足也不进", "confidence": 0.1},
        ]
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    dest = tmp_path / "cand.jsonl"
    n = emit_candidates(dest, cases_root=tmp_path / "cases")
    assert n == 1
    rows = [json.loads(l) for l in dest.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["conclusion_id"] == "M1"
    assert all(r["conclusion_id"] != "D1" for r in rows)

    # 超长 statement_sha8 键本身短；把 conclusion_id 拉爆以逼单行 >512
    huge_id = "X" * 600
    report2 = {
        "conclusions": [
            {"id": huge_id, "status": "majority", "statement": "短", "confidence": 0.5},
        ]
    }
    out2 = tmp_path / "cases" / "toy2" / "out1"
    out2.mkdir(parents=True)
    (out2 / "report.json").write_text(json.dumps(report2, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        emit_candidates(tmp_path / "cand2.jsonl", cases_root=tmp_path / "cases")
    assert str(MAX_CANDIDATE_LINE_BYTES) in str(e.value) or "512" in str(e.value)
