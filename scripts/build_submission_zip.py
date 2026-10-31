#!/usr/bin/env python3
"""C-47 件④：按专题分夹组交件 zip＋MANIFEST＋三项自查。

输入＝一个跑次目录（默认 /tmp/s4runs/ 下按 mtime 最新）＋对外文档目录。
对每个专题调真 export_official（从 questions/*/report.json 读案卷），
写出五份 JSON＋字段说明，再打 zip。C-48：默认不把 causal_evidence.json 装进包，`--with-causal` 才装（不许靠文件不存在实现不装）。

自查三件事（打印）：
① 每份 JSON 可被 json.load；
② conflict_resolution 的 冲突清单／结果／重启条件 文本在场率
   （present＝说法文本真在场；empty_statements／ids_only／type_only 另计；
    复用 scripts.probe_resolution_records 的 _element_清单／_element_结果
    与记录上的「重启条件」键判定，不另写一套）；
③ 包内无 human 事件与 relevance_override（客观分机器直出）。

禁品：不把官方样例集原始素材打进包；不改判定。
跑法登记见 docs/dev-journal.md（C-47）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.evidence import Dossier  # noqa: E402
from app.export.official import export_official  # noqa: E402
from scripts.probe_resolution_records import (  # noqa: E402
    _element_清单,
    _element_结果,
)
from scripts.probe_causal_claim_coverage import (  # noqa: E402
    CLAIM_KEYS as _CAUSAL_CLAIM_KEYS,
    _pct as _causal_pct,
    _scan_root as _causal_scan_root,
)

CORE_JSON_NAMES = (
    "evidence.json",
    "conclusions.json",
    "confidence.json",
    "conflict_resolution.json",
)
CAUSAL_JSON_NAME = "causal_evidence.json"
# 导出面仍生成五份；打包默认不装因果件（C-48 件③／task #163）。
JSON_NAMES = CORE_JSON_NAMES + (CAUSAL_JSON_NAME,)

CAUSAL_INCLUDE_STATUS = (
    "causal_evidence：装入（--with-causal；见 task #163；"
    "1.3 非必须加分件／人工评测／不预测得分）"
)

# C-49 件②：省略原因必须当场从 probe_causal_claim_coverage 读数填入；
# 解析不出百分数 ⇒ 直接失败，不许回落到写死的默认串（防 #166 常量自比）。
_PCT_IN_STATUS_RE = re.compile(r"(\d+(?:\.\d+)?)%")


def format_causal_omit_status(run_dir: Path) -> str:
    """从跑次目录当场跑因果覆盖探针，填入原因行。

    含：跑次名＋四要素全非空率＋逐要素非空率＋降级条数。
    n_ev==0 或拼不出百分数 ⇒ ValueError（调用方应让组包失败）。
    """
    st = _causal_scan_root(Path(run_dir))
    n_ev = int(st["n_ev"])
    if n_ev <= 0:
        raise ValueError(
            f"因果覆盖探针在跑次 {run_dir} 下证据条数=0，"
            f"解析不出非空率数字（不许回落默认串）"
        )
    full_rate = _causal_pct(int(st["full_nonempty"]), n_ev)
    if full_rate == "n/a" or not _PCT_IN_STATUS_RE.search(full_rate):
        raise ValueError(
            f"因果覆盖探针未能产出可解析百分数：full_rate={full_rate!r}"
        )
    per_bits = []
    for k in _CAUSAL_CLAIM_KEYS:
        rate_k = _causal_pct(int(st["per_key"][k]), n_ev)
        if rate_k == "n/a" or not _PCT_IN_STATUS_RE.search(rate_k):
            raise ValueError(
                f"因果覆盖探针要素 {k} 无百分数：{rate_k!r}"
            )
        per_bits.append(f"{k}={rate_k}")
    n_deg = int(st["n_degraded"])
    line = (
        f"causal_evidence：不装（原因＝四要素非空率 {full_rate}"
        f"（{'／'.join(per_bits)}）／降级 {n_deg} 条"
        f"／跑次={Path(run_dir).name}／见 task #163；本包暂不交该加分件）"
    )
    # 自检：行内至少有一个百分数，防止以后又写成无数字的常量
    if not _PCT_IN_STATUS_RE.search(line):
        raise ValueError(f"因果省略状态行无百分数：{line!r}")
    return line


def assert_causal_omit_status_matches_live(status_line: str, run_dir: Path) -> None:
    """件② 牙：填进去的数字必须与当场探针一致；改数字 ⇒ 红。"""
    live = format_causal_omit_status(run_dir)
    assert status_line == live, (
        f"因果省略状态与当场探针不一致：\n  got={status_line!r}\n  live={live!r}"
    )


def _die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _latest_run_dir(root: Path) -> Path:
    if not root.is_dir():
        _die(f"跑次根不存在：{root}")
    cands = [p for p in root.iterdir() if p.is_dir()]
    if not cands:
        _die(f"跑次根下无子目录：{root}")
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0]


def _case_dirs(run_dir: Path) -> list[Path]:
    out = []
    for p in sorted(run_dir.iterdir()):
        if not p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        if (p / "questions").is_dir() or (p / "evidence.json").is_file():
            out.append(p)
    if not out:
        _die(f"{run_dir} 下找不到专题目录（需含 questions/ 或 evidence.json）")
    return out


def _export_topic(case_dir: Path, out_dir: Path) -> Path:
    """从 questions/*/report.json 调 export_official；无 questions 则复制既有四份并要求已有 causal。"""
    reports = sorted((case_dir / "questions").glob("*/report.json")) if (case_dir / "questions").is_dir() else []
    out_dir.mkdir(parents=True, exist_ok=True)
    if reports:
        runs: list[tuple[dict, Dossier]] = []
        for rp in reports:
            data = json.loads(rp.read_text(encoding="utf-8"))
            qid = rp.parent.name
            runs.append((
                {"question_id": qid, "question": str(data.get("question") or "")},
                Dossier.from_dict(data),
            ))
        export_official(runs, out_dir)
        return out_dir
    # 无 questions：复制既有提交物（须已含 causal_evidence，否则失败）
    for name in JSON_NAMES:
        src = case_dir / name
        if not src.is_file():
            _die(f"{case_dir} 无 questions/ 且缺 {name}；请用含 report.json 的跑次")
        (out_dir / name).write_bytes(src.read_bytes())
    notes = case_dir / "字段说明.md"
    if notes.is_file():
        (out_dir / "字段说明.md").write_bytes(notes.read_bytes())
    return out_dir


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_json_parseable(topic_dir: Path) -> list[str]:
    bad = []
    for name in JSON_NAMES:
        p = topic_dir / name
        if not p.is_file():
            bad.append(f"{topic_dir.name}/{name}: missing")
            continue
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{topic_dir.name}/{name}: {exc}")
    return bad


def _check_resolution_rates(topic_dir: Path) -> dict:
    """复用探针判定函数；按探针状态字面统计（含 present_type_only 等）。"""
    path = topic_dir / "conflict_resolution.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = list(payload.get("records") or [])
    n = len(records)
    from collections import Counter
    list_c: Counter = Counter()
    res_c: Counter = Counter()
    n_restart = 0
    for rec in records:
        q, _ = _element_清单(rec)
        r, _ = _element_结果(rec)
        list_c[q] += 1
        res_c[r] += 1
        restart = ""
        if "重启条件" in rec:
            restart = str(rec.get("重启条件") or "")
        elif "restart_condition" in rec:
            restart = str(rec.get("restart_condition") or "")
        if restart.strip():
            n_restart += 1
    # 文本在场＝仅 present（empty_statements／ids_only／type_only／empty／missing 都不算）
    def text_present(counter: Counter) -> int:
        return int(counter.get("present", 0))
    return {
        "n": n,
        "清单_by_status": dict(list_c),
        "结果_by_status": dict(res_c),
        "清单_present": text_present(list_c),
        "结果_present": text_present(res_c),
        # 兼容旧键名：语义已收到"文本在场"，不再把 empty_statements 算进去
        "清单_nonempty": text_present(list_c),
        "结果_nonempty": text_present(res_c),
        "重启条件_nonempty": n_restart,
    }


_HUMAN_RE = re.compile(r'"agent"\s*:\s*"human"|\"type\"\s*:\s*\"human\"|"human"\s*:')
_OVERRIDE_RE = re.compile(r"relevance_override")


def _scan_forbidden(root: Path) -> list[str]:
    """包内不得出现 human 事件与 relevance_override（扫 JSON／md 文本）。"""
    hits = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".json", ".md", ".txt", ".jsonl"}:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(p.relative_to(root))
        if _OVERRIDE_RE.search(text):
            # 字段说明里若解释该键＝披露口径，允许；提交 JSON 行内非空值禁止
            if p.suffix.lower() == ".json":
                try:
                    data = json.loads(text)
                except Exception:  # noqa: BLE001
                    hits.append(f"{rel}: relevance_override 字面量")
                    continue
                blob = json.dumps(data, ensure_ascii=False)
                # 值非空才算污染
                if re.search(r'"relevance_override"\s*:\s*"[^"]+"', blob):
                    hits.append(f"{rel}: relevance_override 非空")
        if p.suffix.lower() in {".json", ".jsonl"} and _HUMAN_RE.search(text):
            hits.append(f"{rel}: human 事件痕迹")
    return hits


def _collect_docs(docs_dirs: list[Path]) -> list[tuple[str, Path]]:
    """收集包根文档：部署文档／使用说明／测试报告／技术方案（按文件名匹配）。"""
    wanted = {
        "部署文档": None,
        "使用说明": None,
        "测试报告": None,
        "技术方案": None,
        "字段说明": None,
    }
    for d in docs_dirs:
        if not d or not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in {".md", ".txt"}:
                continue
            name = p.name
            for key in list(wanted):
                if key in name and wanted[key] is None:
                    wanted[key] = p
    out = []
    for key, p in wanted.items():
        if p is None:
            continue
        # 字段说明优先用各专题导出的；包根若有也放一份汇总
        out.append((p.name if key != "字段说明" else "字段说明.md", p))
    return out


def build(
    run_dir: Path,
    out_zip: Path,
    docs_dirs: list[Path],
    work_root: Path,
    with_causal: bool = False,
) -> dict:
    cases = _case_dirs(run_dir)
    staging = work_root / "staging"
    if staging.exists():
        import shutil
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    topic_stats = []
    parse_bad: list[str] = []
    n_causal_exported = 0
    n_causal_packed = 0
    for case in cases:
        topic_out = staging / case.name
        _export_topic(case, topic_out)
        # 不许用"文件不存在"实现不装：导出后因果件必须在盘上
        causal_path = topic_out / CAUSAL_JSON_NAME
        if not causal_path.is_file():
            _die(
                f"导出后缺 {CAUSAL_JSON_NAME}：{causal_path}"
                f"（口径开关不能靠文件不存在）"
            )
        n_causal_exported += 1
        parse_bad.extend(_check_json_parseable(topic_out))
        if with_causal:
            n_causal_packed += 1
        else:
            causal_path.unlink()
        rates = _check_resolution_rates(topic_out)
        topic_stats.append({"topic": case.name, **rates})
        # 包根字段说明：取第一专题的
        if not (staging / "字段说明.md").exists() and (topic_out / "字段说明.md").exists():
            (staging / "字段说明.md").write_bytes(
                (topic_out / "字段说明.md").read_bytes())

    for arc_name, src in _collect_docs(docs_dirs):
        dest = staging / arc_name
        if not dest.exists():
            dest.write_bytes(src.read_bytes())

    # 演示产物（可选）：自家 cases/*/out_offline 的 report.md 索引，不打原始金标
    demo_note = staging / "DEMO_NOTE.txt"
    demo_note.write_text(
        "演示产物请用仓库内 scripts/demo_offline.py 现场生成；"
        "本包不含 cases/*/out* 原始素材，也不含官方样例集。\n",
        encoding="utf-8",
    )

    forbidden = _scan_forbidden(staging)

    if with_causal:
        status_line = CAUSAL_INCLUDE_STATUS
    else:
        try:
            status_line = format_causal_omit_status(run_dir)
        except ValueError as exc:
            _die(str(exc), code=2)
    print(f"==== {status_line} ====")
    print(
        f"  causal_exported={n_causal_exported} "
        f"causal_packed={n_causal_packed} with_causal={with_causal}"
    )

    # MANIFEST
    cmd_bits = (
        f"PYTHONPATH=. .venv/bin/python scripts/build_submission_zip.py "
        f"--run-dir {run_dir}"
    )
    if with_causal:
        cmd_bits += " --with-causal"
    manifest_lines = [
        f"# veritas 交件 MANIFEST",
        f"# generated_at={datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"# run_dir={run_dir}",
        f"# command={cmd_bits}",
        f"# {status_line}",
        "# columns: sha256  path",
    ]
    files_for_zip: list[Path] = []
    for p in sorted(staging.rglob("*")):
        if p.is_file():
            files_for_zip.append(p)
            rel = p.relative_to(staging).as_posix()
            manifest_lines.append(f"{_sha256_file(p)}  {rel}")
    man_path = staging / "MANIFEST.txt"
    man_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    files_for_zip.append(man_path)

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files_for_zip:
            zf.write(p, arcname=p.relative_to(staging).as_posix())

    # 打印三项自查
    print("==== 自查① JSON 可解析 ====")
    if parse_bad:
        for line in parse_bad:
            print(f"  FAIL {line}")
    else:
        print(f"  OK 全部 {len(cases)} 专题 × {len(JSON_NAMES)} 文件可 json.load")

    print(
        "==== 自查② 冲突清单／结果／重启条件 文本在场率"
        "（present；empty_statements 不算在场；复用 probe 判定） ===="
    )
    for st in topic_stats:
        print(
            f"  {st['topic']}: n={st['n']} "
            f"清单_present={st['清单_present']}/{st['n']} {st['清单_by_status']} "
            f"结果_present={st['结果_present']}/{st['n']} {st['结果_by_status']} "
            f"重启条件_nonempty={st['重启条件_nonempty']}/{st['n']}"
        )

    print("==== 自查③ 包内无 human 事件与 relevance_override 非空 ====")
    if forbidden:
        for line in forbidden:
            print(f"  FAIL {line}")
    else:
        print("  OK 未检出")

    print(f"==== zip => {out_zip} ({out_zip.stat().st_size} bytes) ====")
    return {
        "zip": str(out_zip),
        "n_topics": len(cases),
        "parse_bad": parse_bad,
        "topic_stats": topic_stats,
        "forbidden": forbidden,
        "with_causal": with_causal,
        "causal_status": status_line,
        "n_causal_exported": n_causal_exported,
        "n_causal_packed": n_causal_packed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--run-dir",
        default="",
        help="跑次目录（默认 /tmp/s4runs 下 mtime 最新）",
    )
    ap.add_argument(
        "--s4runs-root",
        default="/tmp/s4runs",
        help="当未给 --run-dir 时在此根下选最新",
    )
    ap.add_argument(
        "--docs-dir",
        action="append",
        default=[],
        help="对外文档目录（可重复）；默认 docs/deliverables",
    )
    ap.add_argument(
        "--extra-docs-dir",
        action="append",
        default=[],
        help="额外文档目录（如桌面交付物夹）",
    )
    ap.add_argument(
        "--out",
        default="",
        help="输出 zip 路径（默认 dist/veritas-交件-<日期>.zip）",
    )
    ap.add_argument(
        "--work-dir",
        default="",
        help="组包工作目录（默认 /tmp/c47_submission_build）",
    )
    ap.add_argument(
        "--with-causal",
        action="store_true",
        help="把 causal_evidence.json 装进包（默认不装；见 task #163／C-48）",
    )
    args = ap.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir(Path(args.s4runs_root))
    if not run_dir.is_dir():
        _die(f"跑次目录不存在：{run_dir}")

    docs_dirs = [Path(p) for p in (args.docs_dir or ["docs/deliverables"])]
    docs_dirs.extend(Path(p) for p in args.extra_docs_dir)
    # 默认附带桌面交付物（若存在）
    desktop = Path.home() / "Desktop" / "veritas-交付物-2026-10-24"
    if desktop.is_dir() and desktop not in docs_dirs:
        docs_dirs.append(desktop)

    date_tag = datetime.now().strftime("%Y-%m-%d")
    out_zip = Path(args.out) if args.out else (ROOT / "dist" / f"veritas-交件-{date_tag}.zip")
    work = Path(args.work_dir) if args.work_dir else Path("/tmp/c47_submission_build")

    print(f"run_dir={run_dir}")
    print(f"docs_dirs={docs_dirs}")
    print(f"out_zip={out_zip}")
    result = build(run_dir, out_zip, docs_dirs, work, with_causal=args.with_causal)
    if result["parse_bad"] or result["forbidden"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
