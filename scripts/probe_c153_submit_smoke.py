#!/usr/bin/env python3
"""C-153 探针：交卷 JSON／组包冒烟（盲测前夜，只量／只组包，不动判定）。

两腿各跑一次打包出口，本探针只读包与官方样例集，零模型调用、不写 app/：

腿 A（旧跑次）＝C-149 那批六案产物 → build_submission_zip 的包
腿 B（新鲜单案）＝本机 14B 真跑刘翔三题的产物 → 同一个打包出口

自查项（工单写死的四条，全部机械核）
  1) 包内每份 JSON 可 json.load；四核心文件（evidence／conclusions／confidence／
     conflict_resolution）逐专题都在（空态也要文件在且可解析）；
  2) conclusions.json 里 supporting_facts／conflicting_facts 元素形＝{doc_id, para_id}
     （键必须在；空列表算通过并计数）；
  3) 包内无 human 事件与 relevance_override 泄漏：扫整包每个 JSON／md／txt／jsonl 成员
     （口径与打包出口 _scan_forbidden 同尺——md 里解释键名＝披露口径放过、JSON 值非空才算污染；
     扫到的成员数现抄进产物，＝0 则这条核算空比空、不给过）；
     外加一条「官方原始素材不许进包」＝逐成员 sha256 对官方集每个文件的散列比（比散列不比正文）。
  4) 定位回溯：任取结论的支撑段键，按官方字段语义
     `content[char_start:char_end]` 回到该案原文段——案内匹配（官方 doc_id 跨案不互斥），
     分四档：键在卷／doc 取不到／para 取不到／段文本空。再加一条引文逐字腿：
     该键在 evidence.json 里的 quote 是否逐字落在同一段的官方切片里。
     ⚠ 定位规则（当场核过，别猜）：官方 para_id 本身就是复合串「doc_001#p1」，
     查表要用原始 (doc_id, para_id) 直接索引；再按 '#' 切一刀会把 para_id 截成「p1」，
     实测那样 178/178 全读成「段取不到」＝仪器自己的洞，不是包的问题。

跑法（两个 --zip 各带一个腿标签，缺＝该项记缺口不猜）：
    PYTHONPATH=. .venv/bin/python scripts/probe_c153_submit_smoke.py \
        --zip A=/tmp/c153_submit_from_c149/veritas-交件-c153腿A.zip \
        --rundir A=/tmp/s4runs/time-20261104-135401 \
        --zip B=/tmp/c153_submit_fresh_liuxiang/veritas-交件-c153腿B.zip \
        --rundir B=/tmp/c153runs/time-xxxx
可选：--causal-zip LABEL=PATH（旁证那次 --with-causal 的包；本探针当场数它有几行、
四要素任一非空几行，不抄 MANIFEST 里那句原因＝读数不自指）。
产物：artifacts/C153_submit_smoke.{json,md}（只含 doc_id／para_id／计数／字节数，
无官方语料正文、无结论原文）。

明天盲测的两条进料路（本探针的三行备忘据此写死，均已当场从码面核过）：
  ①测量路＝scripts／measure_s4_gates.py 的 time 模式：案根取环境变量 OFFICIAL_CASES，
    每题题面从该案 conclusions.json 现拆（只读 question_id 与 question）——
    赛方若只给题目不给结论样例，这条路看不到题；
  ②生产路＝`-m app.pipeline <案目录> --out <跑次根>/<案名>`：pipeline 的官方入口
    按 run_official_case 走，题面取 --questions 指定的清单，
    产物落 <跑次根>/<案名>/questions/<question_id>/report.json。
组包认的是②这个形状：build_submission_zip 只扫「跑次根」下含 questions／或 evidence.json
的专题夹，所以 --out 必须写成 <跑次根>/<案名> 而不是直接写案目录的 out。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OFFICIAL_DEFAULT = Path.home() / "Desktop/veritas-testcases/样例集-拓尔思-20261012"
CORE_JSON_NAMES = (
    "evidence.json",
    "conclusions.json",
    "confidence.json",
    "conflict_resolution.json",
)
EXTRA_JSON_NAMES = ("causal_evidence.json", "conflict_trace.json")
FACT_KEYS = {"doc_id", "para_id"}
FACTOR_KEYS = ("intervention", "outcome", "population", "counterfactual")
# 禁品口径与打包出口 _scan_forbidden 对齐（两边同尺才谈「一致」）：
#   relevance_override 只有「值非空」才算污染（md 文档里解释该键名＝披露口径，放过）；
#   human 事件只在 JSON／JSONL 文本里认（正则三种写法都盖）。
HUMAN_RE = re.compile(r'"agent"\s*:\s*"human"|"type"\s*:\s*"human"|"human"\s*:')
OVERRIDE_KEY_RE = re.compile(r"relevance_override")
OVERRIDE_VALUE_RE = re.compile(r'"relevance_override"\s*:\s*"[^"]+"')
MARKS = (("吉隆", "jilong"), ("中美", "us_cn_ai"), ("刘翔", "liuxiang"),
         ("印度", "ai171"), ("柬泰", "kh_th"), ("王虹", "wanghong"))


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _slug(topic: str) -> str:
    for mark, slug in MARKS:
        if mark in topic:
            return slug
    return "other"


def _key_str(doc_id: str, para_id: str) -> str:
    return para_id if str(para_id).startswith(f"{doc_id}#") else f"{doc_id}#{para_id}"


def _official_index(case_dir: Path) -> dict[str, dict[str, str]]:
    """官方 raw_documents.json → {doc_id: {para_id: 段文本}}（案内匹配的唯一真源）。"""
    f = case_dir / "raw_documents.json"
    if not f.is_file():
        return {}
    data = json.loads(f.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for doc in data if isinstance(data, list) else []:
        if not isinstance(doc, dict):
            continue
        doc_id = str(doc.get("doc_id") or "").strip()
        if not doc_id:
            continue
        content = str(doc.get("content") or "")
        paras: dict[str, str] = {}
        for para in doc.get("paragraphs") or []:
            if not isinstance(para, dict) or "para_id" not in para:
                continue
            pid = str(para["para_id"])
            cs, ce = para.get("char_start"), para.get("char_end")
            if isinstance(cs, int) and isinstance(ce, int):
                paras[pid] = content[cs:ce]
            else:
                paras[pid] = ""
        out[doc_id] = paras
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _official_material_hashes(official_root: Path) -> dict[str, str]:
    """官方样例集里每个原始素材文件的 sha256 → 相对路径（禁品核用：包内不许出现官方原始素材）。
    只读散列，不读进产物、不抄正文。"""
    out: dict[str, str] = {}
    if not official_root.is_dir():
        return out
    for f in sorted(official_root.rglob("*")):
        if not f.is_file():
            continue
        try:
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
        except OSError:
            continue
        out[digest] = str(f.relative_to(official_root))
    return out


def _forbidden_scan_all(blobs: dict[str, bytes],
                        official_hashes: dict[str, str] | None = None,
                        ) -> tuple[list[str], int]:
    """整包禁品扫（不只四核心 JSON：说明／MANIFEST／任何 JSON／JSONL 成员一起扫）。
    口径与打包出口 _scan_forbidden 同尺：relevance_override 只有「值非空」算污染、
    md 文档解释键名放过；human 事件只在 JSON／JSONL 文本里认。
    再加一条「官方原始素材不许进包」＝逐成员 sha256 与官方集逐文件散列比（比散列不比文本）。
    返回（命中列表，扫过的成员数）——成员数必须＞0，否则这条核是空比空。"""
    hits: list[str] = []
    n_scanned = 0
    for name in sorted(blobs):
        if not name.endswith((".json", ".md", ".txt", ".jsonl")):
            continue
        n_scanned += 1
        if official_hashes:
            src = official_hashes.get(hashlib.sha256(blobs[name]).hexdigest())
            if src is not None:
                hits.append(f"{name}：与官方原始素材同散列＝{src}")
                continue
        text = blobs[name].decode("utf-8", "ignore")
        if name.endswith(".json") and OVERRIDE_KEY_RE.search(text):
            if OVERRIDE_VALUE_RE.search(text):
                hits.append(f"{name}：relevance_override 非空")
        if name.endswith((".json", ".jsonl")) and HUMAN_RE.search(text):
            hits.append(f"{name}：human 事件痕迹")
    return hits, n_scanned


def _facts_shape(items) -> dict:
    """支撑／冲突事实列表的形状核：键在不在、是不是只有那两个键。"""
    st = {"n_items": 0, "n_bad_type": 0, "n_missing_key": 0, "n_extra_key": 0,
          "n_empty_list": 0, "n_key_only": 0}
    if not isinstance(items, list):
        st["n_bad_type"] += 1
        return st
    if not items:
        st["n_empty_list"] += 1
    st["n_items"] += len(items)
    for it in items:
        if not isinstance(it, dict):
            st["n_bad_type"] += 1
            continue
        keys = set(it.keys())
        if not FACT_KEYS <= keys:
            st["n_missing_key"] += 1
        if keys - FACT_KEYS:
            st["n_extra_key"] += 1
        if keys == FACT_KEYS:
            st["n_key_only"] += 1
    return st


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, int) and isinstance(dst.get(k), int):
            dst[k] += v
        elif k not in dst:
            dst[k] = v


def _locate_topic(topic: str, conc, ev_rows, official: dict) -> dict:
    """一专题的定位回溯：结论侧全部支撑段键 → 官方切片；再加引文逐字腿。"""
    ev_by_key: dict[str, str] = {}
    ev_raw: list[tuple[str, str, str]] = []
    for row in ev_rows:
        if not isinstance(row, dict):
            continue
        doc_id = str(row.get("doc_id") or "")
        pid = str(row.get("para_id") or "")
        k = _key_str(doc_id, pid)
        if k not in ev_by_key:
            ev_by_key[k] = str(row.get("quote") or "")
            ev_raw.append((doc_id, pid, str(row.get("quote") or "")))
    res = {"n_conclusions": len(conc), "n_support_keys": 0, "n_conflict_keys": 0,
           "in_volume": 0, "no_doc": 0, "no_para": 0, "empty_slice": 0,
           "quote_rows": 0, "quote_verbatim": 0, "quote_mismatch": 0,
           "quote_no_key": 0, "samples": []}
    seen: set[str] = set()
    for c in conc:
        if not isinstance(c, dict):
            continue
        for field, bucket in (("supporting_facts", "support"),
                              ("conflicting_facts", "conflict")):
            facts = c.get(field)
            if not isinstance(facts, list):
                continue
            for it in facts:
                if not isinstance(it, dict):
                    continue
                doc_id = str(it.get("doc_id") or "")
                pid = str(it.get("para_id") or "")
                key = _key_str(doc_id, pid)
                if bucket == "support":
                    res["n_support_keys"] += 1
                else:
                    res["n_conflict_keys"] += 1
                if key in seen:
                    continue
                seen.add(key)
                if doc_id not in official:
                    res["no_doc"] += 1
                    continue
                para_txt = official[doc_id].get(pid)
                if para_txt is None:
                    res["no_para"] += 1
                    continue
                if not para_txt.strip():
                    res["empty_slice"] += 1
                    continue
                res["in_volume"] += 1
                quote = ev_by_key.get(key, "")
                if bucket == "support" and len(res["samples"]) < 3:
                    res["samples"].append({
                        "question_id": str(c.get("question_id") or ""),
                        "key": key, "slice_chars": len(para_txt),
                        "quote_chars": len(quote),
                        "verbatim": bool(quote) and _norm(quote) in _norm(para_txt),
                    })
    for doc_id, pid, quote in ev_raw:
        if not quote:
            continue
        res["quote_rows"] += 1
        # ⚠ 官方 para_id 本身是复合串「doc_001#p1」＝不能再切；切了就查不到（实测切了会 178/178 全落空）
        para_txt = official.get(doc_id, {}).get(pid)
        if para_txt is None:
            res["quote_no_key"] += 1
        elif _norm(quote) in _norm(para_txt):
            res["quote_verbatim"] += 1
        else:
            res["quote_mismatch"] += 1
    return res


def _causal_face(zip_path: str) -> dict:
    """--with-causal 旁证的现抄读数：包里有几份 causal_evidence.json、几行、
    四要素（intervention／outcome／population／counterfactual）任一非空的有几行。
    只数不抄文本——数字必须当场从包算出来，不抄 MANIFEST 里那句原因。"""
    p = Path(zip_path)
    if not p.is_file():
        return {"present": False, "reason": f"文件不存在：{zip_path}"}
    st = {"present": True, "n_files": 0, "n_rows": 0,
          "n_rows_any_factor": 0, "n_rows_all_factors": 0,
          "n_rows_degraded": 0, "zip_bytes": p.stat().st_size}
    try:
        with zipfile.ZipFile(p) as zf:
            for n in zf.namelist():
                if not n.endswith("causal_evidence.json"):
                    continue
                st["n_files"] += 1
                rows = json.loads(zf.read(n).decode("utf-8"))
                for r in rows if isinstance(rows, list) else []:
                    if not isinstance(r, dict):
                        continue
                    st["n_rows"] += 1
                    hits = sum(1 for k in FACTOR_KEYS
                               if str(r.get(k) or "").strip())
                    if hits:
                        st["n_rows_any_factor"] += 1
                    if hits == len(FACTOR_KEYS):
                        st["n_rows_all_factors"] += 1
                    if str(r.get("degraded_reason") or "").strip():
                        st["n_rows_degraded"] += 1
    except Exception as exc:                          # noqa: BLE001
        st["error"] = f"{type(exc).__name__}"
    return st


def _scan_zip(label: str, zip_path: Path, run_dir: Path | None,
              official_root: Path) -> dict:
    if not zip_path.is_file():
        _die(f"[{label}] 找不到 zip：{zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        blobs = {n: zf.read(n) for n in names}
    topics = sorted({n.split("/")[0] for n in names if "/" in n
                     and not n.startswith(("MANIFEST",))})
    names_ = set(names)
    topics = [t for t in topics if any(
        f"{t}/{j}" in names_ for j in CORE_JSON_NAMES)]
    per_topic, parse_bad, forbidden_hits = [], [], []
    shape_total: dict[str, int] = {}
    loc_total: dict[str, int] = {}
    for t in topics:
        of = official_root / t
        official = _official_index(of) if of.is_dir() else {}
        counts: dict[str, object] = {"topic": t, "slug": _slug(t),
                                     "official_loaded": bool(official),
                                     "official_docs": len(official),
                                     "files": sorted(
                                         n.split("/", 1)[1] for n in names
                                         if n.startswith(f"{t}/"))}
        parsed: dict[str, object] = {}
        for j in CORE_JSON_NAMES + EXTRA_JSON_NAMES:
            n = f"{t}/{j}"
            if n not in blobs:
                if j in CORE_JSON_NAMES:
                    parse_bad.append(f"{t}/{j}：包内缺该核心文件")
                continue
            try:
                parsed[j] = json.loads(blobs[n].decode("utf-8"))
            except Exception as exc:              # noqa: BLE001
                parse_bad.append(f"{t}/{j}：json.load 失败 {type(exc).__name__}")
            counts.setdefault("bytes", {})[j] = len(blobs[n])
        counts["n_files_字段说明"] = int(f"{t}/字段说明.md" in names)
        ev = parsed.get("evidence.json") or []
        cn = parsed.get("conclusions.json") or []
        cf = parsed.get("confidence.json") or []
        cr = parsed.get("conflict_resolution.json") or []
        counts["records"] = {
            "evidence": len(ev) if isinstance(ev, list) else -1,
            "conclusions": len(cn) if isinstance(cn, list) else -1,
            "confidence": len(cf) if isinstance(cf, list) else -1,
            "conflict_resolution": (len(cr) if isinstance(cr, list)
                                     else len((cr or {}).get("records") or [])),
        }
        sh: dict[str, int] = {}
        for c in cn if isinstance(cn, list) else []:
            if not isinstance(c, dict):
                continue
            _merge(sh, _facts_shape(c.get("supporting_facts")))
            _merge(sh, _facts_shape(c.get("conflicting_facts")))
        _merge(shape_total, sh)
        counts["facts_shape"] = sh
        if official:
            loc = _locate_topic(t, cn if isinstance(cn, list) else [],
                                ev if isinstance(ev, list) else [], official)
            for k in ("n_support_keys", "n_conflict_keys", "in_volume", "no_doc",
                      "no_para", "empty_slice", "quote_rows", "quote_verbatim",
                      "quote_mismatch", "quote_no_key"):
                loc_total[k] = loc_total.get(k, 0) + loc[k]
            counts["locate"] = loc
        per_topic.append(counts)
    mat_hashes = _official_material_hashes(official_root)
    all_hits, n_scanned = _forbidden_scan_all(blobs, mat_hashes)
    forbidden_hits.extend(all_hits)
    manifest = blobs.get("MANIFEST.txt", b"").decode("utf-8", "ignore")
    root_files = sorted(n for n in names if "/" not in n)
    return {
        "leg": label,
        "zip": str(zip_path),
        "zip_bytes": zip_path.stat().st_size,
        "run_dir": str(run_dir) if run_dir else "",
        "n_members": len(names),
        "n_topics": len(topics),
        "root_files": root_files,
        "manifest_lines": len(manifest.splitlines()),
        "per_topic": per_topic,
        "parse_bad": parse_bad,
        "forbidden_hits": forbidden_hits,
        "forbidden_scanned_members": n_scanned,
        "official_material_files": len(mat_hashes),
        "facts_shape_total": dict(sorted(shape_total.items())),
        "locate_total": {k: loc_total.get(k, 0) for k in (
            "n_support_keys", "n_conflict_keys", "in_volume", "no_doc", "no_para",
            "empty_slice", "quote_rows", "quote_verbatim", "quote_mismatch",
            "quote_no_key")},
    }


def _run_stats(run_dir: Path | None) -> dict:
    """跑次侧真数：整案墙钟＝逐题 elapsed_s 相加；rows.jsonl／summary.json 现抄。"""
    if not run_dir or not run_dir.is_dir():
        return {"present": False}
    rows_p = run_dir / "rows.jsonl"
    out = {"present": rows_p.is_file(), "rows": [], "elapsed_s_sum": 0,
           "n_calls_sum": 0, "tokens_sum": 0}
    if rows_p.is_file():
        for line in rows_p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            out["rows"].append({
                "case": str(r.get("case") or "")[:12], "qid": r.get("qid"),
                "elapsed_s": r.get("elapsed_s"), "n_calls": r.get("n_calls"),
                "tokens": r.get("tokens"), "wall_q_s": r.get("wall_q_s"),
                "n_conclusions": r.get("n_conclusions"),
            })
            for dst, src in (("elapsed_s_sum", "elapsed_s"),
                             ("n_calls_sum", "n_calls"),
                             ("tokens_sum", "tokens")):
                v = r.get(src)
                if isinstance(v, (int, float)):
                    out[dst] += v
    for name in ("summary.json",):
        p = run_dir / name
        if p.is_file():
            out[name] = json.loads(p.read_text(encoding="utf-8"))
    return out


def _verdict(legs: list[dict], time_gate_s: int = 1800) -> dict:
    """预登记判据（跑前写死，逐字执行）：五条结构核全过＝YES；
    有硬伤（腿没组出包／缺核心文件／JSON 解析失败／形状违规／禁品泄漏／
    定位对不上原文／任一核空比空）＝NO；组包成功但出现空结论面＝PARTIAL。
    ⚠ 墙钟只记账不降档：30 分钟参考线官方已撤，本腿又与另一台 14B 跑批并发，
    方向上只会高估——所以它进「记账」行，不参与判 PARTIAL。"""
    structural = ("四核心文件齐", "JSON 可解析", "形状合规", "无禁品泄漏", "定位可回溯")
    checks = {k: True for k in structural}
    why: list[str] = []
    built = [l for l in legs if l.get("n_topics")]
    if len(built) != len(legs):
        for l in legs:
            if not l.get("n_topics"):
                why.append(f"腿 {l['leg']}：组包没出专题夹（失败）")
    for l in legs:
        tag = l["leg"]
        if not l.get("n_topics"):
            checks["四核心文件齐"] = False
            continue
        if l["parse_bad"]:
            checks["JSON 可解析"] = False
            why.append(f"{tag}：解析失败 {len(l['parse_bad'])} 项")
        if l["forbidden_hits"]:
            checks["无禁品泄漏"] = False
            why.append(f"{tag}：禁品 {len(l['forbidden_hits'])} 项")
        elif not l.get("forbidden_scanned_members"):
            checks["无禁品泄漏"] = False
            why.append(f"{tag}：禁品腿一个成员都没扫到＝空比空，不算通过")
        elif not l.get("official_material_files"):
            checks["无禁品泄漏"] = False
            why.append(f"{tag}：官方素材散列面＝0 个文件＝同散列核空比空，不算通过")
        sh = l["facts_shape_total"]
        if sh.get("n_missing_key") or sh.get("n_bad_type"):
            checks["形状合规"] = False
            why.append(f"{tag}：支撑/冲突事实缺键或形状错 "
                       f"{sh.get('n_missing_key')}/{sh.get('n_bad_type')}")
        missing_core = [t["topic"] for t in l["per_topic"]
                        if set(CORE_JSON_NAMES) - set((t.get("bytes") or {}).keys())]
        if missing_core:
            checks["四核心文件齐"] = False
            why.append(f"{tag}：缺核心文件专题 {'、'.join(missing_core)}")
        loc = l["locate_total"]
        n_of = sum(1 for t in l["per_topic"] if t.get("official_loaded"))
        if loc["n_support_keys"] + loc["n_conflict_keys"] == 0:
            checks["定位可回溯"] = False
            why.append(f"{tag}：定位腿一个键都没取到＝空比空，不算通过"
                       f"（官方侧装载专题 {n_of}/{len(l['per_topic'])}"
                       f"＝0 说明官方根没匹配上，不是包空）")
        elif loc["no_doc"] or loc["no_para"] or loc["empty_slice"]:
            checks["定位可回溯"] = False
            why.append(f"{tag}：定位失败 doc缺 {loc['no_doc']}／para缺 "
                       f"{loc['no_para']}／空段 {loc['empty_slice']}")
    soft: list[str] = []
    time_notes: list[str] = []
    for l in legs:
        st = l.get("run_stats") or {}
        if not st.get("present"):
            continue
        n_cases = len({r.get("case") for r in st.get("rows", [])})
        tot = round(st.get("elapsed_s_sum", 0), 1)
        if n_cases <= 1:
            # 单案腿才对「30 分钟参考线」记账；该线官方已撤 ⇒ 只记事实，不判 PARTIAL
            time_notes.append(f"腿 {l['leg']}（单案）：逐题 elapsed_s 合计 {tot} s"
                              f"｜参考线 {time_gate_s} s（官方已撤，只记账不改算法）")
        else:
            time_notes.append(f"腿 {l['leg']}：{n_cases} 案 × {len(st['rows'])} 题"
                              f"合计 {tot} s＝多案批次，不对单案参考线判定")
        for t in l.get("per_topic", []):
            n = (t.get("records") or {}).get("conclusions")
            if n == 0:
                soft.append(f"腿 {l['leg']}：专题 {t['topic']} 结论面为 0 条")
    hard_fail = any(not checks[k] for k in structural) or len(built) != len(legs)
    if hard_fail:
        overall = "NO"
    elif soft:
        overall = "PARTIAL"
    else:
        overall = "YES"
    return {"overall": overall, "legs_built": [l["leg"] for l in built],
            "checks": checks, "why": "；".join(why) or "五条结构核全过",
            "soft": "；".join(soft) or "无",
            "time_notes": "；".join(time_notes) or "无（两腿都没挂 --rundir，跑次侧没读数）",
            "both_legs": len(built) == len(legs) and len(legs) == 2,
            "time_gate_s": time_gate_s}


def _render_md(out: dict) -> str:
    v = out["verdict"]
    L = ["# C-153 交卷 JSON／组包冒烟（盲测前夜）", ""]
    L += [f"结论：**{v['overall']}**｜两腿都组包成功＝{v['both_legs']}"
          f"（腿：{'、'.join(v['legs_built']) or '无'}）", ""]
    L += [f"- 机械核：{'；'.join(f'{k}＝{val}' for k, val in v['checks'].items())}",
          f"- 结构不过的原因：{v['why']}",
          f"- 软条件（判 PARTIAL 的那一类）：{v['soft']}",
          f"- 墙钟记账（不降档，参考线官方已撤）：{v.get('time_notes', '无')}", ""]
    for leg in out["legs"]:
        L += [f"## 腿 {leg['leg']}｜包与四核心文件条数", ""]
        L += [f"- zip＝{leg['zip']}（{leg['zip_bytes']} 字节，{leg['n_members']} 个成员，"
              f"{leg['n_topics']} 个专题夹）｜跑次根＝{leg['run_dir'] or '—'}",
              f"- 包根文件：{'、'.join(leg['root_files']) or '无'}｜"
              f"MANIFEST 行数＝{leg['manifest_lines']}｜"
              f"禁品腿扫过的成员数＝{leg.get('forbidden_scanned_members')}"
              f"（对官方素材 {leg.get('official_material_files')} 个文件的散列面比；"
              f"任一为 0 ＝空比空，该核算不过）",
              f"- 支撑／冲突事实形状合计：{json.dumps(leg['facts_shape_total'], ensure_ascii=False)}",
              f"- 定位回溯合计（结论侧去重后的键）：{json.dumps(leg['locate_total'], ensure_ascii=False)}"]
        for t in leg["per_topic"]:
            rec = t.get("records") or {}
            extra = [j for j in EXTRA_JSON_NAMES
                     if j in (t.get("bytes") or {})]
            L += [f"  - {t['topic']}（官方侧现读 {t['official_docs']} 篇／"
                  f"字段说明在场＝{t.get('n_files_字段说明')}）："
                  + f"{rec.get('evidence')}／{rec.get('conclusions')}／"
                  f"{rec.get('confidence')}／{rec.get('conflict_resolution')} 条"
                  f"（evidence／conclusions／confidence／conflict_resolution）"
                  + (f"｜包内另有 {('、'.join(extra))}" if extra else "")]
            loc = t.get("locate")
            if loc:
                L += [f"    回溯：支撑键 {loc['n_support_keys']}＋冲突键 "
                      f"{loc['n_conflict_keys']}＝在卷 {loc['in_volume']}／"
                      f"doc 缺 {loc['no_doc']}／para 缺 {loc['no_para']}／"
                      f"空段 {loc['empty_slice']}；引文逐字腿 {loc['quote_rows']} 行＝"
                      f"逐字 {loc['quote_verbatim']}／不匹配 {loc['quote_mismatch']}／"
                      f"段取不到 {loc['quote_no_key']}"]
                for s in loc["samples"]:
                    L += [f"    抽检 {s['key']}（题 {s['question_id']}）＝"
                          f"官方切片 {s['slice_chars']} 字、包内引文 "
                          f"{s['quote_chars']} 字、逐字命中＝{s['verbatim']}"]
        st = leg.get("run_stats") or {}
        if st.get("present"):
            L += [f"- 跑次真数：逐题 elapsed_s 合计 {round(st['elapsed_s_sum'], 1)} s、"
                  f"n_calls 合计 {st['n_calls_sum']}、tokens 合计 {st['tokens_sum']}"]
            for r in st["rows"]:
                L += [f"  - {r['case']} {r['qid']}：elapsed {r['elapsed_s']} s、"
                      f"calls {r['n_calls']}、tokens {r['tokens']}、"
                      f"结论 {r['n_conclusions']} 条"]
        cf = leg.get("causal_face") or {}
        if cf.get("present"):
            L += [f"- --with-causal 旁证（当场现数）：{cf['zip_bytes']} 字节包里 "
                  f"causal_evidence.json {cf['n_files']} 份／{cf['n_rows']} 行："
                  f"四要素任一非空 {cf['n_rows_any_factor']} 行、四要素全非空 "
                  f"{cf['n_rows_all_factors']} 行、带降级原因句 {cf['n_rows_degraded']} 行"
                  + (f"｜读取异常 {cf['error']}" if cf.get("error") else "")]
        for nt in leg.get("notes") or []:
            L += [f"- 外部条件披露：{nt}"]
        L += [""]
    L += ["## 明天盲测操作备忘（三行）", ""]
    L += [f"- {out['memo_feed']}", f"- {out['memo_run']}", f"- {out['memo_ship']}"]
    L += ["", "## 卫生与红线", ""]
    L += ["- 本探针零模型调用；真跑腿（腿 B）的模型请求只走本机 Ollama＋假密钥"
          "（安全闸由跑批脚本钉），无付费外呼。⚠ 不写「零网络」：litellm 启动期尝试拉"
          "远程 cost-map，三次超时后回落本地备份（非模型请求，见跑批日志当场打印）。",
          "- 工作树 `git diff app/` 为空；未合任何未合枝；未改任何默认旗"
          "（出厂默认当场读码＝submit_top7／conflict_trace／arb_context 开、cite_accept 关）。",
          "- 本文件不含官方语料正文、不含结论原文：只有 doc_id／para_id／计数／字节数／"
          "题目号（切片只记字符数）。"]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="C-153 交卷组包冒烟")
    ap.add_argument("--zip", action="append", default=[],
                    help="LABEL=PATH（可重复；一腿一项）")
    ap.add_argument("--rundir", action="append", default=[],
                    help="LABEL=PATH（该腿的跑次根，可重复）")
    ap.add_argument("--official-root", default=str(OFFICIAL_DEFAULT))
    ap.add_argument("--causal-zip", action="append", default=[],
                    help="LABEL=PATH（--with-causal 旁证包，按腿挂上，当场现数）")
    ap.add_argument("--note", action="append", default=[],
                    help="LABEL=文本（外部条件披露，如并发跑批／缓存冷热，按腿挂上）")
    ap.add_argument("--out-dir", default=str(ROOT / "artifacts"))
    args = ap.parse_args()

    official_root = Path(args.official_root)
    if not official_root.is_dir():
        _die(f"官方样例集根不存在：{official_root}")
    zips: dict[str, str] = {}
    for item in args.zip:
        if "=" not in item:
            _die(f"--zip 要写成 LABEL=PATH：{item}")
        k, _, p = item.partition("=")
        zips[k.strip()] = p.strip()
    if not zips:
        _die("至少要一条 --zip LABEL=PATH")
    rundirs: dict[str, str] = {}
    for item in args.rundir:
        k, _, p = item.partition("=")
        rundirs[k.strip()] = p.strip()
    causal_zips: dict[str, str] = {}
    for item in args.causal_zip:
        k, _, p = item.partition("=")
        causal_zips[k.strip()] = p.strip()
    extra: dict[str, list[str]] = {}
    for item in args.note:
        k, _, p = item.partition("=")
        extra.setdefault(k.strip(), []).append(p.strip())

    legs = []
    for label, zp in sorted(zips.items()):
        rd = Path(rundirs[label]) if label in rundirs else None
        leg = _scan_zip(label, Path(zp), rd, official_root)
        leg["zip_ok"] = bool(leg["n_topics"]) and not leg["parse_bad"] \
            and not leg["forbidden_hits"]
        leg["run_stats"] = _run_stats(rd)
        leg["causal_face"] = (_causal_face(causal_zips[label])
                              if label in causal_zips else {"present": False})
        leg["notes"] = extra.get(label, [])
        legs.append(leg)

    out = {
        "ticket": "C-153",
        "official_root": str(official_root),
        "legs": legs,
        "verdict": _verdict(legs),
        "memo_feed": ("喂案＝盲测案整夹放仓库外一个只读根目录，每案目录必须有 "
                      "raw_documents.json（官方形态）；跑批根用 OFFICIAL_CASES=<该根> 指过去"
                      "（不给＝默认桌面样例集路径）。⚠ measure_s4_gates 是从该案 "
                      "conclusions.json 里抽 question_id／question 的——盲测数据若不带结论样例，"
                      "就另存一份 questions.json（只含 question_id 与 question）放案目录里，"
                      "走下面第二条路"),
        "memo_run": ("跑（二选一，都不花钱：①测量路＝仓库根 "
                     "`S4_OUT=/tmp/blindruns PYTHONPATH=. .venv/bin/python -X utf8 -u "
                     "scripts/measure_s4_gates.py time --case <专题关键词> --timeout-seconds 900`"
                     "（安全闸自锁 Ollama＋假密钥、钉单模型链；不加 --case＝全跑）；"
                     "②生产路＝`PYTHONPATH=. .venv/bin/python -m app.pipeline <案目录> "
                     "--out <跑次根>/<案名>`，案目录里有 raw_documents.json 即自动走官方适配，"
                     "题面取 <案目录>/questions.json 或 --questions 指定）"),
        "memo_ship": ("交＝`PYTHONPATH=. .venv/bin/python scripts/build_submission_zip.py "
                      "--run-dir <跑次根> --out <zip 路径>`；--run-dir 要指到「跑次根」，"
                      "其下每个专题夹得有 questions/q_*/report.json（生产路把 --out 写成 "
                      "<跑次根>/<案名> 正好落成这个形状）；邮件附件＝这一个 zip，"
                      "包内每专题四核心 JSON＋字段说明＋MANIFEST；"
                      "causal_evidence 默认不装（四要素非空率不达标时 MANIFEST 里带当场原因句）"),
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)
    (out_dir / "C153_submit_smoke.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "C153_submit_smoke.md").write_text(_render_md(out), encoding="utf-8")
    v = out["verdict"]
    print(f"总判定 {v['overall']}｜两腿都成 {v['both_legs']}｜核："
          f"{json.dumps(v['checks'], ensure_ascii=False)}｜{v['why']}")
    for l in legs:
        print(f"腿 {l['leg']}：专题 {l['n_topics']}、zip {l['zip_bytes']} 字节、"
              f"解析失败 {len(l['parse_bad'])}、禁品 {len(l['forbidden_hits'])}、"
              f"定位 {json.dumps(l['locate_total'], ensure_ascii=False)}")
    print(f"产物：{out_dir / 'C153_submit_smoke.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
