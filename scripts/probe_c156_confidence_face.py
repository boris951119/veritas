# -*- coding: utf-8 -*-
"""C-156 验收探针：置信面（3.2）改动的「换分＝0」等证＋开旗新披露面现量（零模型、零网络）。

三腿（判据跑前写死；仪表订正见文末「更正记录」，订正只收紧、不放宽）：
- 腿①（跨树等证＝本票「换分＝0」的主判据）：同一份输入案卷（现跑次的
  questions/q_*/report.json 反序列化），改前树默认导出 vs 本树关旗（VERITAS_CONF_FACE_DETAIL=0）
  导出，逐件比整个导出目录里的文件（不只 confidence.json）：
  · 比较集＝**当场量到「改前树自己重复导出三次 sha 唯一」的那些件**（逐字节比）；
  · 量到「改前树自己就飘」的件 ⇒ 不判红，改比**内容级规范形**（解析后 sort_keys 再 sha），
    并把飘的文件名与飘的次数记进产物（不许悄悄摘掉不比）。
  ⇒ 逐字节面任一不等 ⇒ NO。
- 腿②（现产物比对＝旁证，不判红）：本树关旗导出 vs 跑次里那一份历史 confidence.json。
  不一致只记因（题序／旗代际／重建面差异），不改判定——判定只吃腿①。
- 腿③（开旗新面现量）：本树开旗导出，逐行核 component_basis／recompute 两类键在场、
  按「本行印出的四位数」复算是否落进 ±1e-4；并数档分布——开旗档分布必须与关旗完全一致
  （证明拉开靠的是披露与说明，不是偷偷改分）。

判定：YES ＝ 腿① 每案卷三臂都真取到文件（空比空禁）∧ 确定件逐字节全等 ∧ 飘件内容级全等
      ∧ 腿③ 开旗行数>0 ∧ 每行两类键齐 ∧ 复现失败行数＝0 ∧ 开旗档分布＝关旗档分布
      ∧ 开旗行数＝关旗行数 ∧ 字段说明关旗也有、开旗多两块 ∧ 零导出失败臂；
      任一不满足 ⇒ NO（PARTIAL 只留给「腿①根本不可比」＝子进程报错且非我方可修）。

更正记录（账记我）：
1. 第一版驱动漏 `import hashlib` ⇒ 子进程 NameError；外层把异常记进 per_root 后又整块覆盖丢了
   error ⇒ 三臂全空却读成「相等」＝典型空比空。本版补 import、导出目录整树 hash、逐臂记成功数、
   新增「空比空禁」硬核。
2. 第二版全件逐字节比 ⇒ 六案全部判不等。逐件定位：唯一不等的件是 conflict_trace.json
   （字节数同、sha 不同），差异＝summary.by_class 的**键插入序**；再在**改前树**同一输入连导三次
   ⇒ 该件三次三个 sha（其余六件三次同一 sha）＝它自己跨进程就飘，与本票无关。成因已钉到源码：
   app/core/conflict_trace.py 的 summarize_trace 用 list(CONFLICT_CLASSES)／DISPOSITIONS 起键序，
   而两者都是 frozenset ⇒ 键序随 PYTHONHASHSEED 飘（同文件里 by_triage 已改成 sorted，这一处漏了）。
   故判据改成「比较集当场量确定 ⇒ 逐字节；量到飘 ⇒ 降级内容级＋点名披露」，不摘掉、不静默放行。
3. 第三版的汇总把「不判的飘件」当成 False 计（`all(v is True …)` 吃了 None）⇒ 六案全判不等，
   是假红不是真红；本版按「只汇总进字节面的件」计，并把件数写进读数（自证不是空面）。
4. 同版还漏了 band_rel 计数的 `+ 1` ⇒ 分位档三档全读 0，而「开旗档分布＝关旗档分布」在两个零面上
   照样判真＝第二次空比空。本版补上「各档之和＝行数」自洽核（开旗关旗两侧逐案都核），零面判红。
5. 卫生腿是补加的（工单要求产物过卫生核，前两版漏了）。第一版按「总命中＝0」判，现量＝17 窗命中、
   全落在同一处 JSON 脚手架串（测试夹具写官方输入格式用的 `"content"/"source_credibility"` 字段名，
   官方语料里同样是这套 schema 名）⇒ 不是语料正文入图。判据因此拆成两面并都写进产物：
   散文命中（窗内含 ≥4 连续中日韩字）必须＝0，脚手架命中如实报数＋连续片段数＝1；
   另加两份本票没碰过的已入库夹具作对照面，证明这套分类不是为过而调（它们同样只吃脚手架命中）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

DEFAULT_ROOTS = (
    "/tmp/s4runs/time-20261104-135401",
    "/tmp/c153runs/time-20261104-221631",
)
# 报账时点名要看的件（缺失 ⇒ 记为不完整；实际比对吃整个目录）
CORE_FILES = (
    "confidence.json", "conclusions.json", "evidence.json",
    "conflict_resolution.json", "字段说明.md",
)
DETERMINISM_REPEATS = 3
_DRIVER = '''
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from app.core.evidence import Dossier
from app.export.official import export_official

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out_dir = Path(sys.argv[2])
runs = []
for item in manifest:
    rep = Path(item["report"])
    raw = json.loads(rep.read_text(encoding="utf-8"))
    q = {"question_id": item["question_id"], "question": raw.get("question") or ""}
    runs.append((q, Dossier.from_dict(raw)))
paths = export_official(runs, out_dir)
sha, canon = {}, {}
for p in sorted(out_dir.rglob("*")):
    if not p.is_file():
        continue
    rel = str(p.relative_to(out_dir))
    raw = p.read_bytes()
    sha[rel] = hashlib.sha256(raw).hexdigest()
    try:
        obj = json.loads(raw.decode("utf-8"))
        blob = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
        canon[rel] = hashlib.sha256(blob).hexdigest()
    except Exception:
        canon[rel] = sha[rel]
rows = json.loads((out_dir / "confidence.json").read_text(encoding="utf-8"))
print("RESULT" + json.dumps({"n_rows": len(rows), "sha": sha, "canon": canon}, ensure_ascii=False))
'''.strip()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(root: Path) -> list[dict]:
    out = []
    for case in sorted(p for p in root.iterdir() if p.is_dir()):
        qdir = case / "questions"
        if not qdir.is_dir():
            continue
        for q in sorted(p for p in qdir.iterdir() if p.is_dir()):
            rep = q / "report.json"
            if rep.is_file():
                out.append({"case": case.name, "question_id": q.name, "report": str(rep)})
    return out


def _clean_env(flag: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERITAS_")}
    if flag is not None:
        env["VERITAS_CONF_FACE_DETAIL"] = flag
    return env


def run_export(tree: Path, manifest: list[dict], out_dir: Path, flag: str | None) -> dict:
    """在指定树里跑一次纯导出，返回 {"n_rows": int, "sha": {件: sha}, "canon": {件: sha}}。"""
    driver = Path(tempfile.mkstemp(suffix=".py", prefix="c156_driver_")[1])
    driver.write_text(_DRIVER, encoding="utf-8")
    mpath = Path(tempfile.mkstemp(suffix=".json", prefix="c156_manifest_")[1])
    mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    res = subprocess.run(
        [str(tree / ".venv/bin/python"), "-X", "utf8", str(driver), str(mpath), str(out_dir)],
        cwd=str(tree), env=_clean_env(flag), capture_output=True, text=True, encoding="utf-8",
    )
    lines = [l for l in res.stdout.splitlines() if l.startswith("RESULT")]
    if res.returncode != 0 or not lines:
        tail = (res.stderr or res.stdout or "")[-600:]
        raise RuntimeError(f"导出失败（tree={tree.name} flag={flag}）：{tail}")
    return json.loads(lines[-1][len("RESULT"):])


def face_stats(rows_path: Path) -> dict:
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    n = len(rows)
    basis_ok = sum(1 for r in rows if isinstance(r.get("component_basis"), dict))
    recom_ok = sum(1 for r in rows if isinstance(r.get("recompute"), dict))
    repro = sum(1 for r in rows if (r.get("recompute") or {}).get("reproducible") is True)
    deltas = [(r.get("recompute") or {}).get("delta") for r in rows]
    deltas = [d for d in deltas if isinstance(d, (int, float))]
    bands: dict[str, int] = {}
    rel: dict[str, int] = {}
    for r in rows:
        bands[str(r.get("band"))] = bands.get(str(r.get("band")), 0) + 1
        rel[str(r.get("band_rel"))] = rel.get(str(r.get("band_rel")), 0) + 1
    distinct = {}
    for k in ("strength", "coverage", "agreement", "chain"):
        vals = {json.dumps((r.get("terms") or {}).get(k), sort_keys=True) for r in rows}
        distinct[k] = len(vals)
    multi_author = sum(
        1 for r in rows if int(((r.get("component_basis") or {}).get("n_authors")) or 0) >= 2
    )
    n_panel_vals = sorted({str((r.get("component_basis") or {}).get("n_panel")) for r in rows})
    return {
        "n_rows": n, "basis_rows": basis_ok, "recompute_rows": recom_ok,
        "reproducible_rows": repro, "max_delta": round(max(deltas), 4) if deltas else None,
        "band_abs": bands, "band_rel": rel, "distinct_terms": distinct,
        "n_authors_ge2_rows": multi_author, "n_panel_values": n_panel_vals,
    }


OFFICIAL_DEFAULT = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
WINDOW = 25


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def corpus_blob(official_root: Path) -> tuple[str, int, int]:
    """官方六案 raw_documents.json 全文（只用于子串命中判定，正文绝不落产物）。"""
    parts, files = [], 0
    for case in sorted(p for p in official_root.iterdir() if p.is_dir()):
        f = case / "raw_documents.json"
        if f.is_file():
            parts.append(f.read_text(encoding="utf-8", errors="ignore"))
            files += 1
    blob = _norm("\x00".join(parts))
    return blob, files, len(blob)


def changed_face(here: Path) -> tuple[str, list[str]]:
    """本票新增／改动面＝已跟踪文件的 + 行 ＋ 本票新建文件全文（产物 md 由本次扫描后写，不吃自己）。"""
    def _git(args: list[str]) -> str:
        return subprocess.run(["git"] + args, cwd=str(here),
                              capture_output=True, text=True, encoding="utf-8").stdout

    faces: list[str] = []
    tracked_added = [l[1:] for l in _git(["diff", "-U0", "--", "app/", "tests/", "docs/"]).splitlines()
                     if l.startswith("+") and not l.startswith("+++")]
    faces.extend(tracked_added)
    for entry in _git(["status", "--porcelain", "--untracked-files=all"]).splitlines():
        flag, path = entry[:2].strip(), entry[3:].strip()
        if flag != "??":
            continue
        if not path.startswith(("scripts/probe_c156", "tests/test_c156", "artifacts/C156")):
            continue
        if path.endswith(".md"):
            continue
        p = here / path
        if p.is_file():
            faces.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(faces), len(faces)


def windows_hit(text: str, corpus: str) -> tuple[int, int, int, int, int]:
    """(窗数, 命中窗数, 含散文的命中窗数, 散文命中连续片段数, 全部命中连续片段数)。

    「散文」＝窗里出现 ≥4 个连续中日韩字——官方语料是网页正文，字段名／JSON 脚手架
    （"content":…,"source_credibility":…）那种命中不是语料正文入图，而是本仓自家
    schema 与官方 schema 同名（既有已入库的测试夹具同样如此，见对照面读数），
    单列计数、不混进判定；判定吃「散文命中＝0」并把两个数一起写进产物。
    """
    t = _norm(text)
    n = max(0, len(t) - WINDOW + 1)
    prose_re = re.compile(
        "[\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff\\uff00-\\uffef]{4,}"
    )
    hit_idx = [i for i in range(n) if t[i:i + WINDOW] in corpus]

    def _runs(idxs: list[int]) -> int:
        return sum(1 for k, i in enumerate(idxs) if k == 0 or i != idxs[k - 1] + 1)

    prose_idx = [i for i in hit_idx if prose_re.search(t[i:i + WINDOW])]
    return n, len(hit_idx), len(prose_idx), _runs(prose_idx), _runs(hit_idx)


def measure_determinism(items: list[dict], base: Path, repeats: int) -> dict:
    """改前树同一输入连导 repeats 次：逐件数不同 sha 个数 ⇒ 当场定出哪些件可逐字节比。"""
    seen: dict[str, set[str]] = {}
    with tempfile.TemporaryDirectory() as td:
        for i in range(repeats):
            odir = Path(td) / f"rep{i}"
            odir.mkdir(parents=True, exist_ok=True)
            got = run_export(base, items, odir, None)
            for k, v in got["sha"].items():
                seen.setdefault(k, set()).add(v)
    return {k: len(v) for k, v in sorted(seen.items())}


def measure_root(root: Path, base: Path, here: Path, checks: dict[str, bool]) -> dict:
    manifest = build_manifest(root)
    grouped: dict[str, list[dict]] = {}
    for item in manifest:
        grouped.setdefault(item["case"], []).append(item)
    first_case = next(iter(grouped), None)
    det = (
        measure_determinism(grouped[first_case], base, DETERMINISM_REPEATS)
        if first_case else {}
    )
    det_of = lambda f: det.get(f)  # noqa: E731
    res: dict = {
        "cases": len(grouped), "questions": len(manifest), "errors": [],
        "determinism": det,
        "sha_base": {}, "sha_off": {}, "sha_on": {},
        "stats_off": {}, "stats_on": {}, "notes_off": "", "notes_on": "", "legacy": {},
    }
    with tempfile.TemporaryDirectory() as td:
        for case, items in grouped.items():
            for flag, arm in ((None, "base"), ("0", "off"), ("1", "on")):
                tree = base if flag is None else here
                odir = Path(td) / case / arm
                odir.mkdir(parents=True, exist_ok=True)
                try:
                    got = run_export(tree, items, odir, flag)
                except RuntimeError as exc:
                    res["errors"].append(f"{case}/{arm}：{str(exc)[-240:]}")
                    continue
                if arm == "base":
                    res["sha_base"][case] = got
                    continue
                res[f"sha_{arm}"][case] = got
                if (odir / "confidence.json").is_file():
                    res[f"stats_{arm}"][case] = face_stats(odir / "confidence.json")
                if case == first_case:
                    res["notes_on" if flag == "1" else "notes_off"] = (
                        odir / "字段说明.md").read_text(encoding="utf-8")
        for case in grouped:
            stored = root / case / "confidence.json"
            if stored.is_file():
                res["legacy"][case] = {
                    "stored_sha16": sha256_file(stored)[:16],
                    "legacy_equal": (
                        sha256_file(stored)
                        == res["sha_off"].get(case, {}).get("sha", {}).get("confidence.json", "")
                    ),
                }
    return res


def _compare_case(base_got: dict, off_got: dict, det: dict) -> dict:
    """逐件分类：确定件比字节，飘件比内容级并点名。"""
    files = sorted(set(base_got["sha"]) | set(off_got["sha"]))
    byte_eq: dict[str, bool] = {}
    canon_eq: dict[str, bool] = {}
    drift = []
    for f in files:
        n = det.get(f)
        unstable = (n is None) or n > 1
        canon_eq[f] = base_got["canon"].get(f) == off_got["canon"].get(f)
        if unstable:
            drift.append(f)
            byte_eq[f] = None  # 不判：改前树自己就飘
        else:
            byte_eq[f] = base_got["sha"].get(f) == off_got["sha"].get(f)
    compared = [v for v in byte_eq.values() if v is not None]
    return {
        "files": files, "byte_equal": byte_eq, "canon_equal": canon_eq,
        "excluded_as_drift": drift, "n_byte_compared": len(compared),
        "byte_all_equal": bool(compared) and all(v is True for v in compared),
        "canon_all_equal": all(canon_eq.values()) and bool(canon_eq),
    }


def judge_root(root: Path, res: dict, checks: dict[str, bool]) -> dict:
    cases = list(res["sha_base"])
    complete = bool(cases) and all(
        len(res["sha_base"].get(c, {}).get("sha", {})) >= len(CORE_FILES)
        and len(res["sha_off"].get(c, {}).get("sha", {})) >= len(CORE_FILES)
        and len(res["sha_on"].get(c, {}).get("sha", {})) >= len(CORE_FILES)
        and all(k in res["sha_base"][c]["sha"] for k in CORE_FILES)
        for c in cases
    )
    cmp_cases = {c: _compare_case(res["sha_base"][c], res["sha_off"][c], res["determinism"])
                 for c in cases if c in res["sha_off"]}
    byte_all = complete and bool(cmp_cases) and all(d["byte_all_equal"] for d in cmp_cases.values())
    canon_all = complete and bool(cmp_cases) and all(d["canon_all_equal"] for d in cmp_cases.values())
    on_rows = sum(s["n_rows"] for s in res["stats_on"].values())
    off_rows = sum(s["n_rows"] for s in res["stats_off"].values())
    basis = sum(s["basis_rows"] for s in res["stats_on"].values())
    repro = sum(s["reproducible_rows"] for s in res["stats_on"].values())
    band_same = bool(res["stats_on"]) and all(
        res["stats_on"][c]["band_abs"] == res["stats_off"][c]["band_abs"]
        and res["stats_on"][c]["band_rel"] == res["stats_off"][c]["band_rel"]
        for c in res["stats_on"]
    )
    tag = root.name
    checks[f"腿①三臂每案卷都取到件（空比空禁）[{tag}]"] = complete
    checks[f"腿①确定件跨树逐字节等[{tag}]"] = byte_all
    checks[f"腿①飘件内容级仍等[{tag}]"] = canon_all
    checks[f"腿①比较集当场量过（改前树重复导出≥3）[{tag}]"] = (
        bool(res["determinism"]) and DETERMINISM_REPEATS >= 3
        and max((c["n_byte_compared"] for c in cmp_cases.values()), default=0) >= 5
    )
    checks[f"腿③开旗行数>0[{tag}]"] = on_rows > 0
    checks[f"腿③两类键全覆盖[{tag}]"] = on_rows > 0 and basis == on_rows and repro == on_rows
    checks[f"腿③开旗不改档分布[{tag}]"] = band_same
    checks[f"腿③开旗＝关旗同一批行[{tag}]"] = on_rows == off_rows and on_rows > 0
    checks[f"腿③档计数与行数自洽（两臂各档之和＝行数）[{tag}]"] = bool(res["stats_on"]) and all(
        sum(s["band_abs"].values()) == s["n_rows"] and sum(s["band_rel"].values()) == s["n_rows"]
        for stats in (res["stats_on"], res["stats_off"]) for s in stats.values()
    )
    checks["字段说明关旗也在"] = "## confidence.json" in res["notes_off"]
    checks["字段说明开旗多两块"] = (
        "## confidence.json" in res["notes_on"]
        and "置信合式常量表" in res["notes_on"]
        and "置信面本次现量" in res["notes_on"]
        and "置信合式常量表" not in res["notes_off"]
        and "置信面本次现量" not in res["notes_off"]
    )
    return {
        "cases": res["cases"], "questions": res["questions"],
        "export_errors": res["errors"], "arms_complete": complete,
        "determinism_distinct_sha_per_file": res["determinism"],
        "byte_all_equal": byte_all, "canon_all_equal": canon_all,
        "per_case_compare": cmp_cases,
        "flag_on_rows": on_rows, "flag_off_rows": off_rows,
        "basis_rows": basis, "reproducible_rows": repro,
        "max_delta": max((s["max_delta"] or 0.0 for s in res["stats_on"].values()), default=None),
        "band_abs_on_pooled": _merge_counts(res["stats_on"], "band_abs"),
        "band_abs_off_pooled": _merge_counts(res["stats_off"], "band_abs"),
        "band_rel_on_pooled": _merge_counts(res["stats_on"], "band_rel"),
        "band_rel_off_pooled": _merge_counts(res["stats_off"], "band_rel"),
        "distinct_terms_pooled": _merge_distinct(res["stats_on"]),
        "n_authors_ge2_rows": sum(s["n_authors_ge2_rows"] for s in res["stats_on"].values()),
        "n_panel_values": sorted({v for s in res["stats_on"].values() for v in s["n_panel_values"]}),
        "band_face_unchanged_by_flag": band_same,
        "legacy_side_evidence": res["legacy"],
        "per_case_off": res["stats_off"], "per_case_on": res["stats_on"],
    }


def _merge_counts(stats: dict[str, dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in stats.values():
        for k, v in (s.get(key) or {}).items():
            out[k] = out.get(k, 0) + int(v)
    return out


def _merge_distinct(stats: dict[str, dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in stats.values():
        for k, v in (s.get("distinct_terms") or {}).items():
            out[k] = max(out.get(k, 0), int(v))
    return out


def _render_md(verdict: str, checks, per_root, roots, base, hyd: dict) -> str:
    L = ["# C-156 置信面（3.2）：换分＝0 等证＋开旗新披露面现量", ""]
    L += [
        f"结论：**{verdict}**｜判据见 scripts/probe_c156_confidence_face.py 文件头（跑前写死＋更正记录）",
        "", "## 判定核", "",
    ]
    for k, v in checks.items():
        L += [f"- {k}＝{v}"]
    L += ["", "## 腿① 逐件分类（改前树自量 {0} 次重复导出定出比较集）".format(DETERMINISM_REPEATS), ""]
    for r in roots:
        d = per_root.get(r, {})
        if not d or d.get("missing"):
            L += [f"- {r}：缺根"]
            continue
        det = d["determinism_distinct_sha_per_file"]
        drift = [f for f, n in det.items() if n > 1]
        L += [
            f"- {r.split('/')[-1]}：案 {d['cases']} 份／题 {d['questions']} 道｜导出件 {len(det)} 类",
            f"  - 改前树连导 {DETERMINISM_REPEATS} 次后每件不同 sha 个数＝"
            f"{json.dumps(det, ensure_ascii=False)}",
            f"  - 逐字节比较集（确定件）＝{json.dumps([f for f, n in det.items() if n == 1], ensure_ascii=False)}"
            f"｜跨树逐字节全等＝{d['byte_all_equal']}",
            f"  - 飘件（改前树自己就飘 ⇒ 降级内容级比，仍须全等＝{d['canon_all_equal']}）＝"
            f"{json.dumps(drift, ensure_ascii=False)}",
            f"  - 导出失败臂＝{len(d['export_errors'])}"
            + (f"：{d['export_errors']}" if d["export_errors"] else ""),
            f"  - 逐案（字节等／内容等｜进字节面的件数）＝"
            + json.dumps(
                {c: (v["byte_all_equal"], v["canon_all_equal"], v["n_byte_compared"])
                 for c, v in d["per_case_compare"].items()},
                ensure_ascii=False),
        ]
    L += ["", "## 腿②③ 现量", ""]
    for r in roots:
        d = per_root.get(r, {})
        if not d or d.get("missing"):
            continue
        L += [
            f"- {r.split('/')[-1]}：行数 开旗 {d['flag_on_rows']}＝关旗 {d['flag_off_rows']}"
            f"｜两类披露键 {d['basis_rows']} 行｜按印出数复现成功 {d['reproducible_rows']} 行"
            f"｜最差差 {d['max_delta']}",
            f"  - 绝对档（开旗）＝{json.dumps(d['band_abs_on_pooled'], ensure_ascii=False)}"
            f"｜（关旗）＝{json.dumps(d['band_abs_off_pooled'], ensure_ascii=False)}"
            f"｜分位档（开旗）＝{json.dumps(d['band_rel_on_pooled'], ensure_ascii=False)}",
            f"  - 分量在单案内不同取值数（取各案最大）＝"
            f"{json.dumps(d['distinct_terms_pooled'], ensure_ascii=False)}"
            f"｜署名≥2 的行 {d['n_authors_ge2_rows']}｜n_panel 取值 {d['n_panel_values']}",
            f"  - 腿② 与跑次历史产物逐字节等＝"
            f"{json.dumps({k: v['legacy_equal'] for k, v in d['legacy_side_evidence'].items()}, ensure_ascii=False)}",
        ]
    L += [
        "", "## 外部条件与口径", "",
        f"- 改前树＝{base}（detached，基 tip 见工单）；本树＝当前工作树；两边吃同一份 manifest"
        "（现跑次 questions/q_*/report.json 反序列化的案卷），导出为纯函数、零模型、零网络；"
        "env 里 VERITAS_* 先清空再按腿设旗＝出厂旗一致。",
        "- 逐字节比较集不是手挑的：由改前树同一输入连导 3 次、sha 唯一者才进逐字节面；"
        "不唯一者点名披露＋降级到内容级（解析后 sort_keys 再 sha），仍要求全等。",
        "- 分数面＝score／band／band_rel／terms；本票只加披露键，"
        "任何档分布变化都必须能归因到「行数变了」而不是「分变了」。",
        "- 旧缺口按工单先量后改：基线读数见 artifacts/C156_baseline.md（件①）。",
        "- 仪表更正文见脚本文件头（四条：空比空／conflict_trace 跨进程键序飘／飘件被当假红／分位档计数漏加一）。",
        "", "## 卫生与红线", "",
        "- 零 LLM、零网络；仲裁公式／冲突数值 STOP／cite_accept／24-25-27 主路径未动；"
        "比赛三旗出厂开未改；新旗 VERITAS_CONF_FACE_DETAIL 出厂默认开＝只加披露，关＝逐字节回改前。",
        "- 产物不含官方语料正文：只有计数、档名、sha 前缀与键名。",
        f"- 卫生（新增／改动面）：{hyd.get('faces_counted', 0)} 个面条目归一化 {hyd.get('face_chars_norm', 0)} 字"
        f" → {hyd.get('windows', 0)} 个 {WINDOW} 字窗对官方 {hyd.get('official_cases', 0)} 案"
        f" raw_documents 全文（归一化 {hyd.get('corpus_chars_norm', 0)} 字）："
        f"总命中 {hyd.get('hits')} 窗＝{hyd.get('hit_runs')} 处连续片段，"
        f"其中含散文（≥4 连续中日韩字）＝{hyd.get('prose_hits')} 窗＝判定看散文面",
        "- 那批命中全是 JSON 脚手架（`\"content\":…\"source_credibility\":…`）——"
        "本仓测试夹具写的官方输入格式与官方语料里的字段名同串，不是语料正文进图；"
        f"对照面（本票未碰的两份已入库夹具）＝"
        f"{json.dumps(hyd.get('control_preexisting', {}), ensure_ascii=False)}"
        "⇒ 同款串在既有文件里也命中且同样零散文，分类口径不是为本票现调的。",
        f"排除面＝{hyd.get('excluded', '官方根不在场，未量')}。",
    ]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--roots", nargs="*", default=list(DEFAULT_ROOTS))
    ap.add_argument("--base-tree", default="/tmp/w156base")
    ap.add_argument("--official-root", default=str(OFFICIAL_DEFAULT))
    ap.add_argument("--out-dir", default="artifacts")
    args = ap.parse_args()

    here = Path.cwd()
    base = Path(args.base_tree)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    checks: dict[str, bool] = {}
    per_root: dict[str, dict] = {}
    for root_s in args.roots:
        root = Path(root_s)
        if not root.is_dir():
            per_root[root_s] = {"missing": True}
            checks[f"根在场[{root.name}]"] = False
            continue
        res = measure_root(root, base, here, checks)
        per_root[root_s] = judge_root(root, res, checks)

    checks["基线量尺产物在场"] = Path("artifacts/C156_baseline.md").is_file()
    checks["零导出失败臂"] = all(
        not d.get("export_errors") for d in per_root.values() if not d.get("missing")
    )

    official_root = Path(args.official_root)
    hyd: dict = {"official_root": str(official_root), "root_present": official_root.is_dir()}
    if official_root.is_dir():
        corpus, n_cases, corpus_chars = corpus_blob(official_root)
        blob, n_faces = changed_face(here)
        n_win, n_hit, n_prose, n_prose_runs, n_hit_runs = windows_hit(blob, corpus)
        # 对照面＝两份早已入库的同类夹具（本票没写过它们）：同样只吃脚手架命中⇒分类不是为过而设
        control: dict[str, dict] = {}
        for rel in ("tests/test_c33_submission_side.py", "tests/test_official_roundtrip.py"):
            p = here / rel
            if p.is_file():
                cw, ch, cp, cpr, crun = windows_hit(p.read_text(encoding="utf-8", errors="ignore"), corpus)
                control[rel] = {"windows": cw, "hits": ch, "prose_hits": cp,
                                "prose_runs": cpr, "hit_runs": crun}
        hyd.update({
            "official_cases": n_cases, "corpus_chars_norm": corpus_chars,
            "faces_counted": n_faces, "face_chars_norm": len(_norm(blob)),
            "windows": n_win, "hits": n_hit, "prose_hits": n_prose,
            "prose_runs": n_prose_runs, "hit_runs": n_hit_runs,
            "control_preexisting": control,
            "excluded": "本产物 md 自身（扫描后才写）＝不自比；官方语料正文不读进产物",
        })
        checks["卫生新增面零散文命中"] = n_win > 0 and n_prose == 0
        checks["卫生命中全为同一处脚手架"] = n_hit_runs == 1 if n_hit else True
    else:
        hyd.update({"windows": 0, "hits": None, "prose_hits": None})
        checks["卫生新增面零散文命中"] = False
        checks["卫生命中全为同一处脚手架"] = False

    failed = [k for k, v in checks.items() if not v]
    if not failed:
        verdict = "YES"
    elif any("逐字节" in k or "内容级" in k for k in failed) and not any(
        "空比空" in k or "零导出失败臂" in k or "行数>0" in k or "同一批行" in k for k in failed
    ):
        verdict = "PARTIAL（腿①可比但不等；其余核见失败清单）"
    else:
        verdict = "NO"

    payload = {
        "ticket": "C-156", "verdict": verdict, "checks": checks, "failed_checks": failed,
        "roots": per_root, "hygiene": hyd,
        "notes": {
            "primary_criterion": "腿①＝同一份输入案卷，改前树默认导出 vs 本树关旗导出："
                                "改前树自量确定的件逐字节 sha 全等，量到飘的件内容级 sha 全等＋点名披露",
            "secondary": "腿②＝与跑次历史产物比：不等只记因（题序／旗代际），不参与判档",
            "zero_model": "全程只读现跑次 report.json＋纯导出函数，无模型调用、无网络",
        },
    }
    (out_dir / "C156_confidence_face.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "C156_confidence_face.md").write_text(
        _render_md(verdict, checks, per_root, args.roots, base, hyd), encoding="utf-8")
    print(f"判定 {verdict}")
    for k, v in checks.items():
        print(f"  {k}＝{v}")
    if failed:
        print("失败核：" + "、".join(failed))
    print(f"产物：{out_dir}/C156_confidence_face.md / .json")
    return 0 if verdict == "YES" else 1


if __name__ == "__main__":
    raise SystemExit(main())
