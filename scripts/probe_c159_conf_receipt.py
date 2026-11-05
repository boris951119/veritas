"""C-159 量尺：置信面「档位依据＋高档收据」（主观 3.2 收据面；只量不改）。

全程零模型、零网络：只读现跑次 ``questions/q_*/report.json`` 反序列化案卷，
再调纯导出函数重导三臂（改前树默认／本树关旗／本树开旗）。

判尺门槛（跑前写死，跑后不许改口径）：
- G1 不抬档：开旗与关旗的 band 逐档计数相等，band_rel 逐档计数相等，
  且同一 (question_id, conclusion_id) 的 score 逐行相等。
- G2 理由句在场：开旗臂 196/196 类在场（在场率＝1.0）；改前臂必须＝0（且两侧行数都 >0，
  禁「空比空」——任何一侧 n_rows==0 直接记红）。
- G3 空理由率＝0：在场句去空白后非空。
- G4 数字溯源：理由句里每个数字 token，必须落在「该行自身数值 ∪ 合式常量表 ∪
  由这两者现算的乘积／差值（round4）」允许集内；违规行数必须＝0。
- G5 关旗同形：本树 ``VERITAS_CONF_RECEIPT=0`` 的 confidence.json＋字段说明.md
  与改前树默认导出逐字节等（不稳定的件降级到内容级 sha，仍要求全等；
  稳定集由改前树连导 3 次当场定，不手挑）。
- G6 高档收据自洽：带「高档收据」的行数＝band「高」行数，且收据里的「本行分数」
  与该行 score 四位一致。
- G7 别动别的件：开旗 vs 关旗，evidence／conclusions／causal_evidence／
  conflict_resolution 四件逐字节等（本票只许动 confidence.json 与字段说明）。

裁决（跑前写死）：
- YES＝G1..G7 全过（高档覆盖本身不变是本票的设定，不算缺口；分布事实照实披露）。
- PARTIAL＝G1∧G6∧G7 过，但 G2/G3/G4/G5 任一未过（＝披露有洞或同形没证成）。
- NO＝G1 或 G7 任一不过（＝抬档或改了别的提交件，越界）。

产物卫生：只写计数、比率、档名、键名、sha 前缀与本票生成的理由句样例；零案卷原文。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART_JSON = REPO / "artifacts" / "C159_conf_face.json"
ART_MD = REPO / "artifacts" / "C159_conf_face.md"
ART_BASE_JSON = REPO / "artifacts" / "C159_baseline.json"
ART_BASE_MD = REPO / "artifacts" / "C159_baseline.md"
DEFAULT_ROOTS = (
    "/tmp/s4runs/time-20261104-135401",
    "/tmp/c153runs/time-20261104-221631",
)
BASE_TREE = os.environ.get("C159_BASE_TREE", "/private/tmp/w156")
RECEIPT_KEY = "档位依据"
HIGH_KEY = "高档收据"
OTHER_FILES = ("evidence.json", "conclusions.json", "causal_evidence.json",
               "conflict_resolution.json")
CORE_COMPARE = ("confidence.json", "字段说明.md")
STABILITY_REPEATS = 3
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")

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
    raw = json.loads(Path(item["report"]).read_text(encoding="utf-8"))
    q = {"question_id": item["question_id"], "question": raw.get("question") or ""}
    runs.append((q, Dossier.from_dict(raw)))
export_official(runs, out_dir)
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
print("RESULT" + json.dumps({"n_rows": len(rows), "sha": sha, "canon": canon},
                            ensure_ascii=False))
'''.strip()


def _clean_env(receipt: str | None, extra: dict | None = None) -> dict:
    """清场：剥掉所有 VERITAS_*，再按本臂显式设旗（出厂默认＝两边一致）。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERITAS_")}
    env["PYTHONIOENCODING"] = "utf-8"
    if receipt is not None:
        env["VERITAS_CONF_RECEIPT"] = receipt
    env.update(extra or {})
    return env


def build_manifest(root: Path) -> list[dict]:
    items: list[dict] = []
    for case in sorted(p for p in root.iterdir() if p.is_dir()):
        qdir = case / "questions"
        if not qdir.is_dir():
            continue
        for q in sorted(p for p in qdir.iterdir() if p.is_dir()):
            rep = q / "report.json"
            if rep.exists():
                items.append({"report": str(rep), "question_id": q.name})
    return items


def run_export(tree: Path, manifest_file: Path, out_dir: Path,
               receipt: str | None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.rglob("*"):
        if f.is_file():
            f.unlink()
    cmd = [str(tree / ".venv" / "bin" / "python"), "-c", _DRIVER,
           str(manifest_file), str(out_dir)]
    proc = subprocess.run(cmd, cwd=str(tree), env=_clean_env(receipt),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"export failed in {tree}: {proc.stderr[-800:]}")
    line = [l for l in proc.stdout.splitlines() if l.startswith("RESULT")][-1]
    return json.loads(line[len("RESULT"):])


def face_stats(rows_path: Path) -> dict:
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    band = collections.Counter(str(r.get("band") or "") for r in rows)
    rel = collections.Counter(str(r.get("band_rel") or "") for r in rows)
    n = len(rows)
    sent = [str(r.get(RECEIPT_KEY) or "") for r in rows]
    nonempty = sum(1 for s in sent if s.strip())
    hi_receipt = sum(1 for r in rows if isinstance(r.get(HIGH_KEY), dict))
    undisclosed = sum(1 for s in sent if "未披露" in s)
    per_id = {f"{r.get('question_id')}｜{r.get('conclusion_id')}":
              round(float(r.get("score") or 0.0), 4) for r in rows}
    return {
        "n_rows": n,
        "band": {k: band[k] for k in ("高", "中", "低") if band[k]},
        "band_rel": {k: rel[k] for k in ("高", "中", "低", "不可分") if rel[k]},
        "n_sentence": nonempty,
        "sentence_share": round(nonempty / n, 4) if n else 0.0,
        "n_high_band": band.get("高", 0),
        "n_high_receipt": hi_receipt,
        "high_coverage": round(band.get("高", 0) / n, 4) if n else 0.0,
        "n_undisclosed_clause": undisclosed,
        "score_by_conclusion": per_id,
        "n_empty": n - nonempty,
        "sent_len_min": min((len(s) for s in sent if s), default=0),
        "sent_len_max": max((len(s) for s in sent if s), default=0),
        "sent_len_mean": round(sum(len(s) for s in sent) / n, 1) if n else 0.0,
    }


def _numbers_in(obj: object) -> set[float]:
    """把一个对象里所有数字 token 收进允许集（float 比较，不吃格式化差异）。"""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return {float(m.group()) for m in _NUM_RE.finditer(text)}


def provenance_failures(rows: list[dict], consts: dict, level_weights: dict) -> dict:
    """G4：逐行核理由句里的数字是否都在允许集内；允许集由本函数独立现算。"""
    allowed_const = _numbers_in(consts) | _numbers_in(
        {k: v for k, v in level_weights.items()})
    w = consts["weights"]
    thr = consts["band_thresholds"]
    hi, mid = float(thr["high"]), float(thr["mid"])
    bad: list[dict] = []
    checked = 0
    for row in rows:
        sent = str(row.get(RECEIPT_KEY) or "")
        if not sent:
            continue
        checked += 1
        base = {k: v for k, v in row.items() if k not in (RECEIPT_KEY, HIGH_KEY)}
        allowed = set(allowed_const) | _numbers_in(base)
        terms = row.get("terms") or {}
        vals = [float(terms.get(k) or 0.0) for k in
                ("strength", "coverage", "agreement", "agreement_factor",
                 "chain", "chain_for_aggregate")]
        score = round(float(row.get("score") or 0.0), 4)
        for wv in w.values():
            for v in vals:
                allowed.add(round(float(wv) * v, 4))
                allowed.add(round(float(wv) * (1.0 - v), 4))
        allowed.add(round(hi - score, 4))
        allowed.add(round(score - hi, 4))
        allowed.add(round(mid - score, 4))
        allowed.add(round(score - mid, 4))
        cb = row.get("component_basis")
        if isinstance(cb, dict):
            allowed.add(float(len(list(cb.get("chain_rings_applicable") or []))))
            allowed.add(float(len(list(cb.get("chain_rings_broken") or []))))
        for m in _NUM_RE.finditer(sent):
            if float(m.group()) not in allowed:
                bad.append({"conclusion_id": row.get("conclusion_id"),
                            "token": m.group()})
    return {"rows_checked": checked, "n_violation_tokens": len(bad),
            "violations": bad[:10]}


def stability_set(tree: Path, manifest_file: Path, tag: str, tmp: Path) -> dict:
    """改前树连导 N 次：sha 唯一者才进逐字节面，不唯一者点名并降级到内容级。"""
    seen: dict[str, set[str]] = collections.defaultdict(set)
    canon_seen: dict[str, set[str]] = collections.defaultdict(set)
    for i in range(STABILITY_REPEATS):
        res = run_export(tree, manifest_file, tmp / f"stab{i}", None)
        for k, v in res["sha"].items():
            seen[k].add(v)
            canon_seen[k].add(res["canon"][k])
    stable = sorted(k for k, v in seen.items() if len(v) == 1)
    unstable = sorted(k for k, v in seen.items() if len(v) > 1)
    return {"repeats": STABILITY_REPEATS, "stable": stable, "unstable": unstable,
            "n_distinct_sha": {k: len(v) for k, v in sorted(seen.items())}}


def _cmp(res_a: dict, res_b: dict, stable: list[str]) -> dict:
    """两臂逐件比：稳定件要求字节等，其余降级内容等；两侧都必须真取到件。"""
    keys = sorted(set(res_a["sha"]) | set(res_b["sha"]))
    byte_equal, content_equal, missing = {}, {}, []
    for k in keys:
        if k not in res_a["sha"] or k not in res_b["sha"]:
            missing.append(k)
            continue
        content_equal[k] = res_a["canon"][k] == res_b["canon"][k]
        if k in stable:
            byte_equal[k] = res_a["sha"][k] == res_b["sha"][k]
    return {"files_compared": len(keys), "missing_on_one_side": missing,
            "byte_equal": byte_equal, "content_equal": content_equal}


def judge_root(root: Path, tmp: Path, checks: dict[str, bool],
               notes: dict) -> dict:
    manifest = build_manifest(root)
    if not manifest:
        checks[f"{root.name} 案卷清单非空"] = False
        return {"root": str(root), "empty_manifest": True}
    tmp.mkdir(parents=True, exist_ok=True)
    mf = tmp / "manifest.json"
    mf.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    base_tree = Path(BASE_TREE)
    here = REPO
    stab = stability_set(base_tree, mf, "base", tmp)
    stable = stab["stable"]
    r_base = run_export(base_tree, mf, tmp / "base", None)
    r_off = run_export(here, mf, tmp / "off", "0")
    r_on = run_export(here, mf, tmp / "on", "1")
    s_base = face_stats(tmp / "base" / "confidence.json")
    s_off = face_stats(tmp / "off" / "confidence.json")
    s_on = face_stats(tmp / "on" / "confidence.json")

    checks[f"{root.name}｜三臂都取到行（空比空禁）"] = all(
        s["n_rows"] > 0 for s in (s_base, s_off, s_on))
    checks[f"{root.name}｜G1 不抬档（band 逐档计数相等）"] = (
        s_off["band"] == s_on["band"] == s_base["band"])
    checks[f"{root.name}｜G1 不抬档（分位档 band_rel 逐档计数相等）"] = (
        s_off["band_rel"] == s_on["band_rel"] == s_base["band_rel"])
    checks[f"{root.name}｜G1 不抬档（逐行 score 相等）"] = (
        s_off["score_by_conclusion"] == s_on["score_by_conclusion"]
        and len(s_on["score_by_conclusion"]) == s_on["n_rows"])
    checks[f"{root.name}｜G2 改前理由句＝0"] = s_base["n_sentence"] == 0
    checks[f"{root.name}｜G2 关旗理由句＝0"] = s_off["n_sentence"] == 0
    checks[f"{root.name}｜G2 开旗理由句全覆盖"] = (
        s_on["n_sentence"] == s_on["n_rows"])
    checks[f"{root.name}｜G3 空理由率＝0"] = s_on["n_empty"] == 0
    cmp_base_off = _cmp(r_base, r_off, stable)
    core_present = [f for f in CORE_COMPARE if f in cmp_base_off["content_equal"]]
    checks[f"{root.name}｜G5 比较件两侧都在场"] = (
        not cmp_base_off["missing_on_one_side"] and len(core_present) == len(CORE_COMPARE))
    checks[f"{root.name}｜G5 关旗＝改前同形（confidence＋字段说明）"] = bool(
        core_present) and all(
        cmp_base_off["content_equal"].get(f) is True
        and cmp_base_off["byte_equal"].get(f, True) is True
        for f in core_present)
    checks[f"{root.name}｜G5 稳定集真覆盖比较件（不许全飘当通过）"] = any(
        f in stable for f in CORE_COMPARE)
    cmp_on_off = _cmp(r_on, r_off, stable)
    other_present = [f for f in OTHER_FILES if f in cmp_on_off["content_equal"]]
    checks[f"{root.name}｜G7 别动别的件（四件等）"] = (
        len(other_present) == len(OTHER_FILES) and all(
            cmp_on_off["content_equal"].get(f) is True
            and cmp_on_off["byte_equal"].get(f, True) is True
            for f in other_present))
    checks[f"{root.name}｜G6 高档收据行数＝高档行数"] = (
        s_on["n_high_receipt"] == s_on["n_high_band"])
    rows_on = json.loads((tmp / "on" / "confidence.json").read_text(encoding="utf-8"))
    samples = notes.setdefault("samples", {})
    for band in ("高", "中"):
        if band in samples:
            continue
        cands = sorted((r for r in rows_on if r.get("band") == band),
                       key=lambda r: str(r.get("conclusion_id")))
        if cands:
            samples[band] = str(cands[0].get(RECEIPT_KEY) or "")
    mis_score = [r.get("conclusion_id") for r in rows_on
                 if isinstance(r.get(HIGH_KEY), dict)
                 and round(float(r[HIGH_KEY].get("本行分数") or -1), 4)
                 != round(float(r.get("score") or 0.0), 4)]
    checks[f"{root.name}｜G6 收据分数与本行一致"] = not mis_score
    notes.setdefault("score_mismatch", []).extend(mis_score)

    sys.path.insert(0, str(here))
    from app.core.confidence import aggregate_constants
    from app.core.evidence import LEVEL_WEIGHT, EvidenceLevel
    consts = aggregate_constants()
    lws = {str(l.value): float(LEVEL_WEIGHT[l]) for l in EvidenceLevel}
    pv = provenance_failures(rows_on, consts, lws)
    checks[f"{root.name}｜G4 数字溯源零越界"] = pv["n_violation_tokens"] == 0
    notes.setdefault("provenance", []).append({"root": str(root), **pv})
    notes.setdefault("band_stability", []).append({"root": str(root), **stab})
    notes.setdefault("cmp_base_off", []).append({"root": str(root), **cmp_base_off})
    notes.setdefault("cmp_on_off", []).append({"root": str(root), **cmp_on_off})
    return {"root": str(root), "n_questions": len(manifest),
            "base": s_base, "off": s_off, "on": s_on,
            "provenance": pv, "stability": stab}


def verdict(checks: dict[str, bool]) -> str:
    hard = [k for k in checks if ("不抬档" in k or "别动别的件" in k
                                  or "都取到行" in k)]
    if not checks or not all(checks[k] for k in hard):
        return "NO"
    if all(checks.values()):
        return "YES"
    return "PARTIAL"


def _render(per_root: list[dict], checks: dict[str, bool], hyd: dict,
            v: str) -> None:
    lines = [
        "# C-159 置信面收据读数（脚本现抄，非手打）",
        "",
        f"- 判定＝{v}｜改前树＝{BASE_TREE}｜门槛 G1..G7 跑前写死（见本尺文件头）",
        "- 一句话：本票不改档，只让「这条凭什么算高置信」在交卷面上可核。",
        "",
        "## 高档覆盖（分布事实，本票不动它）",
    ]
    for r in per_root:
        if r.get("empty_manifest"):
            lines.append(f"- {r['root']}：案卷清单为空（记红，不比）")
            continue
        lines += [
            f"- {r['root']}（{r['n_questions']} 题）：改前 高 "
            f"{r['base']['band'].get('高', 0)}/{r['base']['n_rows']}＝"
            f"{r['base']['high_coverage']} → 开旗 高 "
            f"{r['on']['band'].get('高', 0)}/{r['on']['n_rows']}＝"
            f"{r['on']['high_coverage']}（关旗同改前＝"
            f"{r['off']['high_coverage']}）",
            f"  档分布 开旗＝{r['on']['band']}｜分位档 开旗＝{r['on']['band_rel']}",
        ]
    lines += ["", "## 理由句与收据面"]
    for r in per_root:
        if r.get("empty_manifest"):
            continue
        lines += [
            f"- {r['root']}：理由句在场 改前 {r['base']['n_sentence']}／"
            f"关旗 {r['off']['n_sentence']}／开旗 {r['on']['n_sentence']} 行"
            f"（在场率 {r['on']['sentence_share']}，空 {r['on']['n_empty']} 行）",
            f"  字数 最小 {r['on']['sent_len_min']}／最大 {r['on']['sent_len_max']}"
            f"／均值 {r['on']['sent_len_mean']}；「未披露」子句 "
            f"{r['on']['n_undisclosed_clause']} 行",
            f"  高档收据 {r['on']['n_high_receipt']} 个（高档行 "
            f"{r['on']['n_high_band']}）",
            f"  G4 数字溯源：查 {r['provenance']['rows_checked']} 行，"
            f"越界数字 {r['provenance']['n_violation_tokens']} 个",
            f"  改前树连导 {r['stability']['repeats']} 次→逐字节稳定件 "
            f"{len(r['stability']['stable'])}／飘件 {len(r['stability']['unstable'])}"
            f"（飘件＝{r['stability']['unstable']}，降级内容级比）",
        ]
    lines += ["", "## 判尺腿逐条"]
    for k in sorted(checks):
        lines.append(f"- {k}＝{checks[k]}")
    for sec, key in (("关旗 vs 改前", "cmp_base_off"), ("开旗 vs 关旗", "cmp_on_off")):
        lines += ["", f"## {sec} 逐件比对"]
        for c in hyd.get(key, []):
            lines.append(f"- {c['root']}：比较 {c['files_compared']} 件｜"
                         f"单边缺件 {c['missing_on_one_side']}｜"
                         f"字节等 {c['byte_equal']}｜内容等 {c['content_equal']}")
    prov = [p for p in hyd.get("provenance", []) if p["violations"]]
    lines += [
        "",
        "## 样例（脚本从开旗臂产物现抄，非手打；取 conclusion_id 排序后的首条）",
    ]
    for tag in ("高", "中"):
        s = (hyd.get("samples") or {}).get(tag)
        lines.append(f"- {tag}档：{s or '本次该档无行'}")
    lines += [
        "",
        "## 外部条件与口径",
        "- 三臂吃同一份输入：现跑次 questions/q_*/report.json 反序列化案卷，"
        "导出为纯函数、零模型、零网络；env 里 VERITAS_* 先清空再按臂设旗＝出厂旗一致。",
        "- 本尺把一个跑次的各案**合并成一份** confidence.json 再量（分位档切点＝合并面）；"
        "生产跑次是逐案各出一份（切点＝本案面），两个面的分位档计数本就不同——"
        "本件报的是合并面，不与逐案相加的读数混读。绝对档与 score 不受此影响。",
        "- 逐字节比较集不是手挑的：由改前树同一输入连导 3 次、sha 唯一者才进字节面；"
        "不唯一者点名披露＋降级内容级（解析后 sort_keys 再 sha），仍要求全等。",
        "- 分数面＝score／band／band_rel／terms；本票只加两个解释键，"
        "任何档分布变化都必须能归因到「行数变了」而不是「分变了」。",
    ]
    lines += ["", f"## 越界数字明细（应为空）＝{prov or '无'}",
              f"## 收据分数不一致明细（应为空）＝{hyd.get('score_mismatch') or '无'}",
              "", "产物卫生：本件只含 id／计数／比率／档名／键名与本票生成的理由句文本，"
              "零案卷原文、零模型输出原文。"]
    ART_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ART_JSON.write_text(json.dumps(
        {"verdict": v, "base_tree": BASE_TREE, "checks": checks,
         "per_root": per_root, "hygiene": hyd},
        ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=("measure", "judge", "all"))
    ap.add_argument("--roots", default=",".join(DEFAULT_ROOTS))
    ap.add_argument("--tmp", default="/tmp/c159_face")
    args = ap.parse_args()
    tmp = Path(args.tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    roots = [Path(r) for r in args.roots.split(",") if r.strip()]
    checks: dict[str, bool] = {}
    hyd: dict = {}
    per_root = []
    for root in roots:
        if not root.is_dir():
            checks[f"{root.name} 跑次目录在场"] = False
            continue
        per_root.append(judge_root(root, tmp / root.name, checks, hyd))
    v = verdict(checks)
    _render(per_root, checks, hyd, v)
    if args.stage in ("measure", "all"):
        base_lines = ["# C-159 改前面读数（基线＝C-156 tip，脚本现抄）", ""]
        for r in per_root:
            if r.get("empty_manifest"):
                continue
            b = r["base"]
            base_lines += [
                f"- {r['root']}：{b['n_rows']} 行｜档分布 {b['band']}｜"
                f"高档覆盖 {b['high_coverage']}",
                f"- 理由句在场 {b['n_sentence']}/{b['n_rows']}＝"
                f"{b['sentence_share']}（空理由率＝"
                f"{round(1 - b['sentence_share'], 4)}）｜高档收据 "
                f"{b['n_high_receipt']} 个",
            ]
        base_lines += ["", "改前缺口清单（本票要补的）：",
                       "- 每行人话理由句＝0（分数与分项都在，但没有「为什么落这档」的句子）",
                       "- 高档行的可核收据（阈值原样值／高出量／五项贡献／等级权／"
                       "支撑与署名／六环／逐门硬门状态）＝0",
                       "- 数字溯源闸（理由句里的数字必须来自行内或常量表）＝无（因为没句子）"]
        ART_BASE_MD.write_text("\n".join(base_lines) + "\n", encoding="utf-8")
        ART_BASE_JSON.write_text(json.dumps(
            {"base_tree": BASE_TREE, "per_root": per_root,
             "note": "同一输入在改前树默认导出；零模型零网络"},
            ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"VERDICT {v}｜checks {sum(checks.values())}/{len(checks)} 过")
    for k in sorted(checks):
        if not checks[k]:
            print("RED", k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
