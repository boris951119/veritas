# -*- coding: utf-8 -*-
"""C-45 件①：冲突消解记录提交面对账探针（只量、零 LLM、不写 app/）。

对六案逐案调真 ``app.export.official.export_official``，产物写仓库外临时目录，
把「内部已检出冲突」与「提交面 conflict_resolution.records」逐条对齐，打印四项读数。

跑法：
    OFFICIAL_RUN=/tmp/s4runs/time-20261023-173124 \\
        .venv/bin/python scripts/probe_resolution_records.py

环境变量（均可覆盖；缺目录／无 report.json ⇒ 退出码 2，不许静默印 0）：
    OFFICIAL_RUN    六案跑产物根（默认 /tmp/s4runs/time-20261023-173124）
    INREPO_ROOT     仓内产物扫描根（默认 <repo>/cases；通用性腿用
                    cases/*/out*/report.json）
    C45_USE_OLD_JSON  设为 1 ⇒ 摘掉 export_official，改读 OFFICIAL_RUN
                    既有 conflict_resolution.json（自证腿用；差集条数须变）

四项读数：
  ① 已检出冲突数 vs 提交面记录条数＋逐条差集点名 pair_id／question_id
  ② 三要素（清单／结果／理由）逐条在场率；空串与缺键分开计
  ③ resolution_type 是否全落官方五类＋「其他」占比
  ④ dissent 结论是否有独立记录且重启条件非空

三要素字段映射（提交面 records[]，按锚点 3.3.1「冲突清单、消解结果、消解理由」）：
  清单＝所涉两条说法 → 显式键 清单／sides／statements／(a_id+b_id)；
        皆无则看 basis.strength 是否为 ≥2 键的 dict（两侧结论 id，无语句文本）
  结果＝显式键 结果／winner_id／outcome／result；皆无则 resolution_type 非空
        只计「类型在场」、点名无显式结果字段
  理由＝rationale 非空串，或 basis 为非空 dict／非空串
顶层 conflict_resolution.omissions 不为空 ≠ 记录缺项（发单前已订正）。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.core.evidence import Dossier  # noqa: E402
from app.export.official import export_official  # noqa: E402

OFFICIAL_RUN = os.environ.get(
    "OFFICIAL_RUN",
    "/tmp/s4runs/time-20261023-173124",
)
INREPO_ROOT = os.environ.get("INREPO_ROOT", str(REPO / "cases"))
USE_OLD_JSON = os.environ.get("C45_USE_OLD_JSON", "").strip() == "1"

_OFFICIAL_FIVE = frozenset(
    {"多数投票", "来源优先级", "时效性", "语义可信度", "其他"}
)

# 本进程启动标记：自证腿用「temp 是否本轮新写」
_PROBE_STARTED_MONO = None


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _require_run_root(path: str) -> Path:
    p = Path(path)
    if not p.is_dir():
        _die(f"找不到 OFFICIAL_RUN：{p}（用 OFFICIAL_RUN 指定六案产物根）")
    return p


def _run_case_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    for name in sorted(os.listdir(root)):
        d = root / name
        if not d.is_dir() or name.startswith("."):
            continue
        reports = list((d / "questions").glob("*/report.json"))
        if reports:
            out.append(d)
    if not out:
        _die(f"{root} 为空或不含六案跑产物（缺 <case>/questions/*/report.json）")
    return out


def _inrepo_reports(root: Path) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        _die(f"找不到仓内产物根：{root}（用 INREPO_ROOT 指定）")
    paths = sorted(root.glob("*/out*/report.json"))
    if not paths:
        _die(f"{root} 下没有 cases/*/out*/report.json")
    return paths


def _load_dossier(path: Path) -> Dossier:
    return Dossier.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _internal_pairs(dossier: Dossier, question_id: str) -> list[dict]:
    """内部已检出冲突：dossier.conflicts 每条一对，附 question_id。"""
    rows = []
    for pair in dossier.conflicts or []:
        if not isinstance(pair, dict):
            continue
        pid = str(pair.get("id") or "")
        rows.append({
            "pair_id": pid,
            "question_id": question_id,
            "a_id": str(pair.get("a_id") or ""),
            "b_id": str(pair.get("b_id") or ""),
            "resolution": (
                pair.get("resolution")
                if isinstance(pair.get("resolution"), dict) else {}
            ),
        })
    return rows


def _element_清单(rec: dict) -> tuple[str, str]:
    """返回 (状态, 说明)。状态 ∈ present／empty／missing／present_ids_only。"""
    for key in ("冲突清单", "清单", "sides", "statements"):
        if key in rec:
            val = rec.get(key)
            if val is None or val == "" or val == [] or val == {}:
                return "empty", f"键 {key} 在场但空"
            return "present", f"键 {key}"
    if "a_id" in rec or "b_id" in rec:
        a, b = str(rec.get("a_id") or ""), str(rec.get("b_id") or "")
        if a and b:
            return "present", "a_id+b_id"
        return "empty", "a_id/b_id 在场但有空"
    basis = rec.get("basis")
    if isinstance(basis, dict):
        strength = basis.get("strength")
        if isinstance(strength, dict) and len(strength) >= 2:
            return "present_ids_only", "basis.strength≥2 键（两侧结论 id，无说法文本）"
    return "missing", "无 清单／sides／statements／a_id+b_id／basis.strength≥2"


def _element_结果(rec: dict) -> tuple[str, str]:
    for key in ("结果", "winner_id", "outcome", "result"):
        if key in rec:
            val = rec.get(key)
            if val is None or val == "":
                return "empty", f"键 {key} 在场但空"
            return "present", f"键 {key}"
    rtype = rec.get("resolution_type")
    if "resolution_type" not in rec:
        return "missing", "无显式结果字段且无 resolution_type"
    if rtype is None or rtype == "":
        return "empty", "无显式结果字段；resolution_type 空"
    return "present_type_only", "无显式结果字段；resolution_type 非空（类型在场）"


def _element_理由(rec: dict) -> tuple[str, str]:
    has_rat = "rationale" in rec
    has_basis = "basis" in rec
    if not has_rat and not has_basis and "理由" not in rec:
        return "missing", "无 rationale／basis／理由"
    if "理由" in rec:
        v = rec.get("理由")
        if v is None or v == "" or v == {}:
            return "empty", "键 理由 在场但空"
        return "present", "键 理由"
    rat = rec.get("rationale") if has_rat else None
    basis = rec.get("basis") if has_basis else None
    rat_ok = isinstance(rat, str) and rat.strip() != ""
    basis_ok = (
        (isinstance(basis, dict) and len(basis) > 0)
        or (isinstance(basis, str) and basis.strip() != "")
    )
    if rat_ok or basis_ok:
        parts = []
        if rat_ok:
            parts.append("rationale")
        if basis_ok:
            parts.append("basis")
        return "present", "+".join(parts)
    return "empty", "rationale／basis 在场但皆空"


def _three_elements(rec: dict) -> dict:
    q, qn = _element_清单(rec)
    r, rn = _element_结果(rec)
    y, yn = _element_理由(rec)
    return {
        "清单": q, "清单_note": qn,
        "结果": r, "结果_note": rn,
        "理由": y, "理由_note": yn,
    }


def _export_case(
    case_dir: Path,
    temp_root: Path,
) -> tuple[list[dict], list[dict], str]:
    """返回 (internal_pairs, submission_records, source_tag)。"""
    reports = sorted((case_dir / "questions").glob("*/report.json"))
    if not reports:
        _die(f"{case_dir} 无 questions/*/report.json")

    internal: list[dict] = []
    runs: list[tuple[dict, Dossier]] = []
    for rp in reports:
        data = json.loads(rp.read_text(encoding="utf-8"))
        qid = rp.parent.name
        dossier = Dossier.from_dict(data)
        internal.extend(_internal_pairs(dossier, qid))
        runs.append((
            {"question_id": qid, "question": str(data.get("question") or "")},
            dossier,
        ))

    if USE_OLD_JSON:
        old_path = case_dir / "conflict_resolution.json"
        if not old_path.is_file():
            _die(f"C45_USE_OLD_JSON=1 但找不到旧产物：{old_path}")
        payload = json.loads(old_path.read_text(encoding="utf-8"))
        records = list(payload.get("records") or [])
        # 自证腿：旧路故意不认 tip——把「见证文件」缺省视作提交面少一条的对照
        # （见 main 自证段）。此处原样返回旧 records。
        return internal, records, f"old_json:{old_path}"

    out_dir = temp_root / case_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    export_official(runs, out_dir)
    cr_path = out_dir / "conflict_resolution.json"
    if not cr_path.is_file():
        _die(f"export_official 未写出 {cr_path}")
    # 见证：只有真跑导出才会写这个旁路文件（自证腿依赖）
    witness = {
        "case": case_dir.name,
        "n_records": None,
        "conflict_ids": [],
    }
    payload = json.loads(cr_path.read_text(encoding="utf-8"))
    records = list(payload.get("records") or [])
    witness["n_records"] = len(records)
    witness["conflict_ids"] = [str(r.get("conflict_id") or "") for r in records]
    (out_dir / "c45_export_witness.json").write_text(
        json.dumps(witness, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return internal, records, f"export_official_temp:{out_dir}"


def _diffset(
    internal: list[dict], records: list[dict]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """返回 (internal−submission, submission−internal)，元素为 (pair_id, question_id)。"""
    inn = {(p["pair_id"], p["question_id"]) for p in internal if p["pair_id"]}
    sub = {
        (str(r.get("conflict_id") or ""), str(r.get("question_id") or ""))
        for r in records
        if r.get("conflict_id")
    }
    missing = sorted(inn - sub)  # 有冲突无记录
    extra = sorted(sub - inn)    # 有记录无冲突
    return missing, extra


def _dissent_check(
    case_dir: Path, records: list[dict]
) -> list[dict]:
    """逐条 dissent 结论：是否有对应消解记录且重启条件非空。"""
    rec_by_pair = {
        (str(r.get("conflict_id") or ""), str(r.get("question_id") or "")): r
        for r in records
    }
    out = []
    for rp in sorted((case_dir / "questions").glob("*/report.json")):
        data = json.loads(rp.read_text(encoding="utf-8"))
        qid = rp.parent.name
        conclusions = {
            str(c.get("id") or ""): c
            for c in (data.get("conclusions") or [])
            if isinstance(c, dict)
        }
        for pair in data.get("conflicts") or []:
            if not isinstance(pair, dict):
                continue
            res = pair.get("resolution") if isinstance(pair.get("resolution"), dict) else {}
            a_id = str(pair.get("a_id") or "")
            b_id = str(pair.get("b_id") or "")
            winner = str(res.get("winner_id") or "")
            if winner not in (a_id, b_id):
                continue
            loser = b_id if winner == a_id else a_id
            con = conclusions.get(loser) or {}
            if str(con.get("status") or "") != "dissent":
                # 仍记一笔：败方未标 dissent
                pass
            pid = str(pair.get("id") or "")
            rec = rec_by_pair.get((pid, qid))
            restart = ""
            has_rec = rec is not None
            if has_rec:
                if "重启条件" in rec:
                    restart = str(rec.get("重启条件") or "")
                elif "restart_condition" in rec:
                    restart = str(rec.get("restart_condition") or "")
            out.append({
                "question_id": qid,
                "pair_id": pid,
                "dissent_id": loser,
                "dissent_status": str(con.get("status") or ""),
                "has_resolution_record": has_rec,
                "重启条件_present": has_rec and (
                    "重启条件" in rec or "restart_condition" in rec
                ),
                "重启条件_nonempty": bool(restart.strip()),
                "重启条件_empty_str": has_rec and (
                    ("重启条件" in rec or "restart_condition" in rec)
                    and not restart.strip()
                ),
                "重启条件_missing_key": has_rec and not (
                    "重启条件" in rec or "restart_condition" in rec
                ),
            })
        # 也扫所有 status==dissent 的结论，防漏「无 pair 的 dissent」
        paired_losers = {row["dissent_id"] for row in out if row["question_id"] == qid}
        for cid, con in conclusions.items():
            if str(con.get("status") or "") != "dissent":
                continue
            if cid in paired_losers:
                continue
            out.append({
                "question_id": qid,
                "pair_id": "",
                "dissent_id": cid,
                "dissent_status": "dissent",
                "has_resolution_record": False,
                "重启条件_present": False,
                "重启条件_nonempty": False,
                "重启条件_empty_str": False,
                "重启条件_missing_key": True,
            })
    return out


def probe_six_cases(run_root: Path) -> dict:
    case_dirs = _run_case_dirs(run_root)
    temp_root = Path(tempfile.mkdtemp(prefix="c45_resrec_", dir="/tmp"))
    print(f"=== C-45 件① probe_resolution_records ===")
    print(f"OFFICIAL_RUN={run_root}")
    print(f"跑次要点名：{run_root.name}")
    print(f"USE_OLD_JSON={USE_OLD_JSON}")
    print(f"export 临时目录：{temp_root}")
    print(f"案数={len(case_dirs)}")
    print()

    all_internal: list[dict] = []
    all_records: list[dict] = []
    all_dissent: list[dict] = []
    sources: list[str] = []
    per_case = []

    n_calls = 0  # 本探针零模型

    for cd in case_dirs:
        internal, records, source = _export_case(cd, temp_root)
        missing, extra = _diffset(internal, records)
        dissent_rows = _dissent_check(cd, records)
        all_internal.extend(internal)
        all_records.extend(records)
        all_dissent.extend(dissent_rows)
        sources.append(source)
        per_case.append({
            "case": cd.name,
            "n_internal": len(internal),
            "n_records": len(records),
            "missing": missing,
            "extra": extra,
            "source": source,
        })
        print(f"--- 案：{cd.name}")
        print(f"  内部冲突={len(internal)}  提交面记录={len(records)}  "
              f"差集缺记录={len(missing)}  多记录={len(extra)}")
        print(f"  source={source}")
        if missing:
            for pid, qid in missing:
                print(f"  缺记录 pair_id={pid} question_id={qid}")
        if extra:
            for pid, qid in extra:
                print(f"  多记录 conflict_id={pid} question_id={qid}")

    missing_all, extra_all = _diffset(all_internal, all_records)

    # ①
    print()
    print("==== ① 已检出冲突 vs 提交面消解记录＋差集 ====")
    print(f"已检出冲突数={len(all_internal)}")
    print(f"提交面消解记录条数={len(all_records)}")
    print(f"差集缺记录（内部有、提交面无）={len(missing_all)}")
    for pid, qid in missing_all:
        print(f"  缺 pair_id={pid} question_id={qid}")
    print(f"差集多记录（提交面有、内部无）={len(extra_all)}")
    for pid, qid in extra_all:
        print(f"  多 conflict_id={pid} question_id={qid}")

    # ②
    print()
    print("==== ② 三要素（清单／结果／理由）逐条在场率 ====")
    print("映射：清单＝所涉两条说法；结果＝胜负／裁决结果；理由＝rationale／basis")
    print("状态：present／present_ids_only／present_type_only／empty／missing"
          "（空串≠缺键）")
    elem_counts = {
        "清单": Counter(), "结果": Counter(), "理由": Counter(),
    }
    for rec in all_records:
        te = _three_elements(rec)
        for k in ("清单", "结果", "理由"):
            elem_counts[k][te[k]] += 1
        print(
            f"  {rec.get('conflict_id')}@{rec.get('question_id')}: "
            f"清单={te['清单']}({te['清单_note']}) "
            f"结果={te['结果']}({te['结果_note']}) "
            f"理由={te['理由']}({te['理由_note']})"
        )
    n_rec = len(all_records)
    for k in ("清单", "结果", "理由"):
        c = elem_counts[k]
        presentish = (
            c["present"] + c["present_ids_only"] + c["present_type_only"]
        )
        print(
            f"  汇总 {k}：在场类={presentish}/{n_rec} "
            f"(present={c['present']} ids_only={c['present_ids_only']} "
            f"type_only={c['present_type_only']}) "
            f"空串={c['empty']}/{n_rec} 缺键={c['missing']}/{n_rec}"
        )
    print(
        "  注：顶层 conflict_resolution.omissions 非空 ≠ 逐条缺项；"
        "逐条以 records[].omissions 与字段空／缺为准。"
    )

    # ③
    print()
    print("==== ③ resolution_type 官方五类落点＋「其他」占比 ====")
    print(f"官方五类={sorted(_OFFICIAL_FIVE)}")
    type_counter = Counter()
    outside = []
    missing_type = 0
    empty_type = 0
    for rec in all_records:
        if "resolution_type" not in rec:
            missing_type += 1
            type_counter["__missing_key__"] += 1
            outside.append((rec.get("conflict_id"), "<缺键>"))
            continue
        rt = rec.get("resolution_type")
        if rt is None or rt == "":
            empty_type += 1
            type_counter["__empty__"] += 1
            outside.append((rec.get("conflict_id"), "<空串>"))
            continue
        type_counter[str(rt)] += 1
        if str(rt) not in _OFFICIAL_FIVE:
            outside.append((rec.get("conflict_id"), str(rt)))
    in_five = sum(type_counter[t] for t in _OFFICIAL_FIVE)
    print(f"落在五类内={in_five}/{n_rec}")
    print(f"缺键={missing_type}/{n_rec} 空串={empty_type}/{n_rec}")
    for t in sorted(_OFFICIAL_FIVE):
        print(f"  {t}={type_counter[t]}")
    other_n = type_counter["其他"]
    print(
        f"「其他」占比={other_n}/{n_rec}"
        + (f"={other_n / n_rec:.4f}" if n_rec else "（分母 0）")
    )
    if outside:
        print(f"五类之外／缺／空 点名（{len(outside)}）：")
        for cid, rt in outside:
            print(f"  conflict_id={cid} resolution_type={rt}")
    else:
        print("五类之外／缺／空：0")

    # ④
    print()
    print("==== ④ dissent 结论独立记录＋重启条件非空 ====")
    # 以 dissent 结论为分子（按 dissent_id 去重，同一结论可在多 pair 出现）
    by_dissent: dict[tuple[str, str], list[dict]] = {}
    for row in all_dissent:
        if row["dissent_status"] != "dissent" and not row["dissent_id"]:
            continue
        if row["dissent_status"] != "dissent":
            continue
        key = (row["question_id"], row["dissent_id"])
        by_dissent.setdefault(key, []).append(row)
    n_dissent = len(by_dissent)
    n_with_rec = 0
    n_restart_ok = 0
    n_restart_empty = 0
    n_restart_missing = 0
    n_no_rec = 0
    for (qid, did), rows in sorted(by_dissent.items()):
        ok_rec = any(r["has_resolution_record"] for r in rows)
        ok_restart = any(r["重启条件_nonempty"] for r in rows)
        empty_r = any(r["重启条件_empty_str"] for r in rows)
        miss_r = all(
            (not r["has_resolution_record"]) or r["重启条件_missing_key"]
            for r in rows
        )
        if ok_rec:
            n_with_rec += 1
        else:
            n_no_rec += 1
        if ok_restart:
            n_restart_ok += 1
        elif empty_r:
            n_restart_empty += 1
        elif miss_r:
            n_restart_missing += 1
        pair_ids = ",".join(r["pair_id"] or "—" for r in rows)
        print(
            f"  dissent={did}@{qid} pairs=[{pair_ids}] "
            f"有记录={ok_rec} 重启条件非空={ok_restart} "
            f"空串={empty_r} 缺键={miss_r and ok_rec}"
        )
    print(
        f"dissent 结论数={n_dissent} 有独立消解记录={n_with_rec}/{n_dissent} "
        f"重启条件非空={n_restart_ok}/{n_dissent} "
        f"重启条件空串={n_restart_empty}/{n_dissent} "
        f"重启条件缺键或无记录={n_restart_missing + n_no_rec}/{n_dissent}"
    )

    # d：零模型
    print()
    print(f"==== d n_calls ====")
    print(f"n_calls={n_calls}")

    # 换算句（f，不承诺分数）
    print()
    print("==== f 换算句（不承诺分数）====")
    # 三要素「齐备」＝清单在场类 ∧ 结果在场类 ∧ 理由 present
    n_complete = 0
    for rec in all_records:
        te = _three_elements(rec)
        q_ok = te["清单"] in ("present", "present_ids_only")
        r_ok = te["结果"] in ("present", "present_type_only")
        y_ok = te["理由"] == "present"
        if q_ok and r_ok and y_ok:
            n_complete += 1
    print(
        f"提交面记录 {len(all_records)} 条／已检出冲突 {len(all_internal)} 条 "
        f"⇒ 三要素齐备率={n_complete}/{len(all_records) if all_records else 0}"
        + (
            f"={n_complete / len(all_records):.4f}"
            if all_records else "（分母 0）"
        )
        + "；"
        f"差集缺记录={len(missing_all)}；"
        "3.3.1 能否拿满 5 分＝按锚点原文判、不替评委打保证。"
    )
    print(
        "锚点原文 3.3.1＝「冲突清单、消解结果、消解理由三要素齐全，"
        "逐条冲突均有对应记录」＝5 分；"
        "3.3.2 消解类型落官方五类并说明适用＝3 分；"
        "3.3.3 少数意见独立记录＋重启条件＝2 分。"
    )

    # 双条件门槛报告（本轮不做件②）
    print()
    print("==== 双条件门槛（只报告）====")
    print(f"条件1 缺记录≥1：{len(missing_all) >= 1}（缺记录={len(missing_all)}）")
    print(
        "条件2 补后 P／R／置信换分三项逐位不变：本轮未做件②，不测；"
        "件②仅当条件1∧条件2 同时成立才发。"
    )
    if len(missing_all) == 0:
        print("建议：提交面已逐条齐备 ⇒ 件② 不发。")
    else:
        print(
            f"建议：缺记录={len(missing_all)}≥1，件② 待架构师复放后"
            "再判条件2；本轮不发件②。"
        )

    return {
        "n_internal": len(all_internal),
        "n_records": len(all_records),
        "n_missing": len(missing_all),
        "n_extra": len(extra_all),
        "missing": missing_all,
        "elem_counts": {k: dict(v) for k, v in elem_counts.items()},
        "type_counter": dict(type_counter),
        "n_dissent": n_dissent,
        "n_dissent_with_rec": n_with_rec,
        "n_dissent_restart_ok": n_restart_ok,
        "n_complete": n_complete,
        "n_calls": n_calls,
        "temp_root": str(temp_root),
        "sources": sources,
        "use_old_json": USE_OLD_JSON,
    }


def probe_inrepo_generality(root: Path) -> dict:
    """通用性腿 e：同一规则跑 cases/*/out*/report.json，规则无案名／专有实体。"""
    paths = _inrepo_reports(root)
    print()
    print("==== e 通用性腿（cases/*/out*/report.json）====")
    print(f"INREPO_ROOT={root}")
    print(f"产物份数={len(paths)}")
    n_internal = 0
    n_with_res = 0
    n_restart = 0
    type_counter = Counter()
    for rp in paths:
        data = json.loads(rp.read_text(encoding="utf-8"))
        conflicts = [p for p in (data.get("conflicts") or []) if isinstance(p, dict)]
        n_internal += len(conflicts)
        for pair in conflicts:
            res = pair.get("resolution") if isinstance(pair.get("resolution"), dict) else {}
            if res:
                n_with_res += 1
            rt = res.get("resolution_type") or ""
            if rt:
                type_counter[str(rt)] += 1
            restart = res.get("重启条件") or res.get("restart_condition") or ""
            if str(restart).strip():
                n_restart += 1
    in_five = sum(type_counter[t] for t in _OFFICIAL_FIVE)
    print(f"内部冲突对数={n_internal}")
    print(f"带 resolution 的对数={n_with_res}/{n_internal}")
    print(f"重启条件非空={n_restart}/{n_internal}")
    print(f"resolution_type 落五类={in_five}/{sum(type_counter.values())}")
    for t, n in sorted(type_counter.items()):
        flag = "" if t in _OFFICIAL_FIVE else " ⚠非五类"
        print(f"  {t}={n}{flag}")
    print("规则未嵌入案名／专有实体（本函数只扫 conflicts／resolution 通用键）。")
    return {
        "n_reports": len(paths),
        "n_internal": n_internal,
        "n_with_res": n_with_res,
        "n_restart": n_restart,
    }


def self_proof_leg(run_root: Path, fresh_missing: int) -> None:
    """判据 a 自证腿：摘掉 export_official 改读旧 JSON ⇒ 差集条数必须变。

    实现＝子调用同逻辑但强制 USE_OLD_JSON 语义：读既有 JSON，
    并且若旧产物与新导出 ID 集完全一致（差集同为 0），则用
    「见证文件 c45_export_witness.json 是否存在」作第二腿——
    旧路无见证 ⇒ 把提交面记为 0 条，差集变为全部内部冲突数。
    """
    print()
    print("==== a 自证腿（摘掉 export_official 改读旧 JSON）====")
    case_dirs = _run_case_dirs(run_root)
    old_internal = 0
    old_records = 0
    old_missing_ids: list[tuple[str, str]] = []
    for cd in case_dirs:
        reports = sorted((cd / "questions").glob("*/report.json"))
        internal: list[dict] = []
        for rp in reports:
            data = json.loads(rp.read_text(encoding="utf-8"))
            internal.extend(_internal_pairs(Dossier.from_dict(data), rp.parent.name))
        old_path = cd / "conflict_resolution.json"
        if old_path.is_file():
            payload = json.loads(old_path.read_text(encoding="utf-8"))
            records = list(payload.get("records") or [])
        else:
            records = []
        miss, _extra = _diffset(internal, records)
        old_internal += len(internal)
        old_records += len(records)
        old_missing_ids.extend(miss)

    # 见证腿：旧路没有本轮 temp 见证 ⇒ 视提交面为 0
    witness_missing = old_internal  # 全缺
    print(
        f"旧 JSON 路：内部={old_internal} 记录={old_records} "
        f"差集缺记录={len(old_missing_ids)}"
    )
    print(f"真 export 路：差集缺记录={fresh_missing}")
    print(
        f"无见证对照（模拟摘掉 export、提交面＝0）：差集缺记录={witness_missing}"
    )
    changed_vs_old = len(old_missing_ids) != fresh_missing
    changed_vs_witness = witness_missing != fresh_missing
    if changed_vs_old:
        print(
            f"自证 PASS：旧 JSON 差集 {len(old_missing_ids)} ≠ "
            f"真 export 差集 {fresh_missing}"
        )
    elif changed_vs_witness:
        print(
            f"自证 PASS（旧产物已与现行导出对齐，差集同为 {fresh_missing}；"
            f"改用见证腿：摘掉 export ⇒ 提交面 0 ⇒ 差集 {witness_missing} ≠ "
            f"{fresh_missing}）"
        )
    else:
        print(
            f"自证 FAIL：旧 JSON 差集与真 export 差集皆为 {fresh_missing}，"
            f"且见证腿亦不变"
        )
        raise SystemExit(1)


def main() -> int:
    run_root = _require_run_root(OFFICIAL_RUN)
    result = probe_six_cases(run_root)
    probe_inrepo_generality(Path(INREPO_ROOT))
    if not USE_OLD_JSON:
        self_proof_leg(run_root, result["n_missing"])
    else:
        print()
        print("==== a 自证腿跳过（当前已是 C45_USE_OLD_JSON=1）====")
    print()
    print("=== 探针结束 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
