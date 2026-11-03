"""C-143 探针：树22 冲突留痕可用化（借 C-123 窄修）——出口面＋旁证＋真跑。

腿A 出口面（零 LLM・确定性夹具・run_case 全路径＋export_official）：
  arm_off        旗关＋对撞夹具   → 期望＝与改前逐字同（剥时戳后）
  arm_on_records 旗开＋对撞夹具   → 期望＝键活过白名单＋回放面写出处置行
  arm_on_empty   旗开＋零对撞夹具 → 期望＝空态文件＋真实题数原因句
腿B 门控复刻（零 LLM・C-134 同尺）：两旗臂各跑两案，读数互比＋对 C-134 基线。
腿C 真跑（本机 14B）：liuxiang q_003 走 run_official_case 生产入口＋交卷面。

用法：
  .venv/bin/python -m scripts.probe_c143_trace_face --stage export --tag base  --out /tmp/c143/export_base.json
  .venv/bin/python -m scripts.probe_c143_trace_face --stage export --tag branch --out /tmp/c143/export_branch.json
  .venv/bin/python -m scripts.probe_c143_trace_face --stage real --out /tmp/c143/real.json
  .venv/bin/python -m scripts.probe_c143_trace_face --stage assemble \
      --base /tmp/c143/export_base.json --branch /tmp/c143/export_branch.json \
      --real /tmp/c143/real.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ART = ROOT / "artifacts"
OUT = Path("/tmp/c143")
MODEL_ID = "openai/veritas-qwen3-14b"
CASES = ("liuxiang", "wanghong")

ENV_GROUP = {
    "VERITAS_KG_SUBMIT_SURFACE": "1",
    "VERITAS_KG_STAGE1": "1",
    "VERITAS_KG_REHYDRATE_BOX": "1",
    "VERITAS_MULTI_BOX": "0",
    "VERITAS_SECOND_PASS": "0",
    "VERITAS_REVIEW_BOOST": "0",  # 与 C-129/C-130/C-134/C-137/C-140 门控同组
}

_EMPTY_JSON = '{"conclusions": []}'
_Q = {"question_id": "q1", "question": "客户B的回款情况如何？"}


def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _gate_env() -> None:
    for k, v in ENV_GROUP.items():
        os.environ[k] = v
    os.environ.pop("VERITAS_SUBMIT_TOP7", None)   # 出厂开
    os.environ.pop("VERITAS_TEST_TREE_LINE", None)
    os.environ.pop("VERITAS_TREE17_RANK_WEIGHT", None)
    os.environ.pop("VERITAS_TREE17_HEAD_TIER", None)


# ------------------------------------------------ 腿A：出口面（零 LLM）


class _Stub:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append(1)
        return SimpleNamespace(content=_EMPTY_JSON)


def _dossier_with_numbers(values: list[str]) -> Any:
    from app.core.evidence import Dossier, Segment, Source, SourceType

    d = Dossier(question=_Q["question"])
    for i, v in enumerate(values):
        src = Source.create(f"料{i}", SourceType.REPORT, id=f"SRC{i}")
        src.segments.append(Segment(
            id=f"SRC{i}#s1", source_id=f"SRC{i}",
            text=f"客户B回款率{v}。材料补充说明，用于占位。",
            index=0))
        d.add_source(src)
    return d


def _norm_report_json(raw: dict) -> str:
    """剥时戳后规范化（elapsed_s 逐跑必变，不计入字节等证面）。"""
    acc = dict(raw.get("accounting") or {})
    acc.pop("elapsed_s", None)
    steps = [dict(s) for s in (acc.get("steps") or [])
             if isinstance(s, dict)]
    for s in steps:
        s.pop("elapsed_s", None)
    acc["steps"] = steps
    out = dict(raw)
    out["accounting"] = acc
    return json.dumps(out, ensure_ascii=False, sort_keys=True)


_MD_ELAPSED = re.compile(r"\*\*本次研判\*\*：[0-9.]+ 秒")


def _norm_report_md(text: str) -> str:
    return _MD_ELAPSED.sub("**本次研判**：X 秒", text)


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8")
        if rel.endswith("report.json"):
            out[rel] = _sha8(_norm_report_json(json.loads(text)))
        elif rel.endswith("report.md"):
            out[rel] = _sha8(_norm_report_md(text))
        elif rel.endswith("conflict_trace.json"):
            # C-145a：摘要桶序随进程哈希种子浮动（值恒同）→ 内容面比较
            out[rel] = _sha8(json.dumps(json.loads(text),
                                        ensure_ascii=False, sort_keys=True))
        else:
            out[rel] = _sha8(text)
    return out


def _export_arm(tag: str, flag: str | None, values: list[str]) -> dict[str, Any]:
    """flag=None＝未设 env（看出厂默认）；"0"/"1"＝显式钉旗。"""
    from app.agents.base import Analyst
    from app.export.official import export_official
    from app.pipeline import RunDeps, RunSpec, run_case

    if flag is None:
        os.environ.pop("VERITAS_CONFLICT_TRACE", None)
    else:
        os.environ["VERITAS_CONFLICT_TRACE"] = flag
    tmp = Path(tempfile.mkdtemp(prefix=f"c143_{tag}_"))
    case = tmp / "case"
    case.mkdir(parents=True)
    (case / "manifest.yaml").write_text(
        f"question: {_Q['question']}\ntitle: C-143\n", encoding="utf-8")
    out = tmp / "out"
    deps = RunDeps(client=_Stub(), analysts=[
        Analyst("mainstream", "测", _Stub(), "m")])
    r = run_case(
        RunSpec(case_dir=case, out_dir=out,
                dossier=_dossier_with_numbers(values), probe=False),
        deps)
    official = out / "official"
    paths = export_official([(_Q, r.dossier)], official)
    tf = official / "conflict_trace.json"
    payload: dict[str, Any] = {}
    if tf.exists():
        payload = json.loads(tf.read_text(encoding="utf-8"))
    acc_key = isinstance((r.dossier.accounting or {}).get("conflict_trace"),
                         dict)
    row0 = (payload.get("records") or [{}])[0]
    files = _hash_tree(out)
    print(f"[腿A {tag}] 旗={flag} 值={values} 键活={acc_key} "
          f"文件={tf.exists()} n={payload.get('summary', {}).get('n')} "
          f"空态={payload.get('empty_state')}", flush=True)
    return {
        "tag": tag, "flag": flag, "values": values,
        "acc_key_live": acc_key,
        "trace_file": tf.exists(),
        "summary_n": (payload.get("summary") or {}).get("n"),
        "empty_state": payload.get("empty_state"),
        "detail": str(payload.get("detail") or ""),
        "row0_conflict_class": row0.get("conflict_class"),
        "row0_disposition": row0.get("disposition"),
        "row0_disposition_cn": row0.get("disposition_cn"),
        "n_stub_calls": len(deps.client.calls),
        "file_hashes": files,
        "official_files": sorted(p.name for p in official.iterdir()),
    }


def leg_export(tag: str) -> dict[str, Any]:
    arms = {
        "arm_off": _export_arm(f"{tag}_off", "0", ["40%", "60%"]),
        "arm_on_records": _export_arm(f"{tag}_rec", "1", ["40%", "60%"]),
        "arm_on_empty": _export_arm(f"{tag}_emp", "1", ["40%"]),
    }
    # 夹具自证：对撞夹具必须真出对撞（≥1），零对撞夹具必须真为 0
    # （改前树键被白名单剥掉＝文件不在场，跳过自证＝缺口本身就是读数）
    if arms["arm_on_records"]["trace_file"]:
        assert arms["arm_on_records"]["summary_n"] >= 1, "对撞夹具失灵"
    if arms["arm_on_empty"]["trace_file"]:
        assert arms["arm_on_empty"]["summary_n"] in (0, None), "零对撞夹具失灵"
    return {"tag": tag, "arms": arms,
            "flag_default_off": _flag_default_off()}


def _flag_default_off() -> bool:
    from app.config import Settings

    saved = os.environ.pop("VERITAS_CONFLICT_TRACE", None)
    try:
        return Settings().conflict_trace is False
    finally:
        if saved is not None:
            os.environ["VERITAS_CONFLICT_TRACE"] = saved


def _flag_default_now() -> bool:
    """C-145a 起：未设 env 时读出厂数据类默认（翻默认后应为 True）。"""
    from app.config import Settings

    saved = os.environ.pop("VERITAS_CONFLICT_TRACE", None)
    try:
        return Settings().conflict_trace
    finally:
        if saved is not None:
            os.environ["VERITAS_CONFLICT_TRACE"] = saved


# ------------------------------------------------ 腿B：门控复刻（零 LLM）


def _replica_arm(flag: str) -> dict[str, Any]:
    from scripts.probe_c125_six_case_gate import (
        CASE_MARKS, EXPECT, _case, _eval_case, _plan_cite_and_leak,
    )

    from app.core.material import DEFAULT_MATERIAL_CHAR_BUDGET
    from app.core.material import set_material_budget

    os.environ["VERITAS_CONFLICT_TRACE"] = flag
    set_material_budget(DEFAULT_MATERIAL_CHAR_BUDGET)
    out: dict[str, Any] = {}
    for slug in CASES:
        mark = CASE_MARKS[slug]
        prefer = EXPECT[slug]["role"] == "regression"
        from app.core.kg_test_tree_line import test_tree_coeff
        coeff, names = test_tree_coeff()
        dens = _eval_case(slug, mark, coeff, names, prefer_gold=prefer)
        extra = _plan_cite_and_leak(slug, mark, coeff, names,
                                    prefer_gold=prefer)
        out[slug] = {
            "slug": slug, "gold_total": dens["gold_total"],
            "cut_hits": dens["cut_hits"],
            "micro_gold_density": dens["micro_gold_density"],
            "avg_gold_density": dens["avg_gold_density"],
            "mean_gold_box_to_close": extra["mean_gold_box_to_close"],
            "n_leaks": extra["n_leaks"],
            "n_submit_ok": extra["n_submit_ok"],
        }
        print(f"[腿B 旗={flag}] {slug}: @7={dens['cut_hits']['7']} "
              f"micro={dens['micro_gold_density']} "
              f"g2c={extra['mean_gold_box_to_close']} "
              f"leak={extra['n_leaks']}", flush=True)
    return out


def leg_replica() -> dict[str, Any]:
    raw = json.loads(
        (ART / "C134_two_case_gate.json").read_text(encoding="utf-8"))
    gate = raw["gate_cases"]
    off = _replica_arm("0")
    on = _replica_arm("1")
    cmp_rows: dict[str, Any] = {}
    for slug in CASES:
        keys = ("cut_hits", "micro_gold_density", "avg_gold_density",
                "mean_gold_box_to_close", "n_leaks", "gold_total")
        arm_eq = all(off[slug][k] == on[slug][k] for k in keys)
        base_eq = all(
            gate[slug][k] == off[slug][k]
            for k in keys if k in gate[slug])
        cmp_rows[slug] = {
            "arm_off_vs_on": arm_eq,
            "vs_c134": base_eq,
            "off": {k: off[slug][k] for k in keys},
            "on": {k: on[slug][k] for k in keys},
            "c134": {k: gate[slug][k] for k in keys if k in gate[slug]},
        }
        print(f"[腿B 判] {slug}: 两臂同={arm_eq} 对C-134同={base_eq}",
              flush=True)
    return {"arms": {"off": off, "on": on}, "compare": cmp_rows}


# ------------------------------------------------ 腿C：真跑（本机 14B）


def leg_real(slug: str = "liuxiang", qid: str = "q_003") -> dict[str, Any]:
    from app.config import Settings
    from app.llm.model_client import ModelClient
    from app.pipeline import RunDeps, run_official_case
    from scripts.measure_s4_gates import lock_local
    from scripts.probe_c125_six_case_gate import (
        CASE_MARKS, _case, _questions_from_conclusions,
    )

    print(lock_local(), flush=True)
    _gate_env()
    os.environ["VERITAS_CONFLICT_TRACE"] = "1"
    case = _case(CASE_MARKS[slug])
    qrow = next(q for q in _questions_from_conclusions(case)
                if q["question_id"] == qid)
    settings = Settings.from_env()
    settings.models = [MODEL_ID]
    settings.multi_box = False
    settings.second_pass_enabled = False
    settings.review_boost = False
    settings.llm_timeout_seconds = 600
    settings = settings.validate()
    if not bool(getattr(settings, "conflict_trace", False)):
        raise AssertionError("C-143 真跑须开 VERITAS_CONFLICT_TRACE=1")
    out_dir = OUT / "real_official"
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    client = ModelClient(settings)
    deps = RunDeps(client=client)
    results = run_official_case(
        case, [qrow], out_dir=out_dir, settings=settings, deps=deps)
    wall = round(time.perf_counter() - t0, 1)
    d = results[0].dossier
    acc = d.accounting or {}
    trace = acc.get("conflict_trace")
    tf = out_dir / "conflict_trace.json"
    payload: dict[str, Any] = {}
    if tf.exists():
        payload = json.loads(tf.read_text(encoding="utf-8"))
    summary = (trace or {}).get("summary") or payload.get("summary") or {}
    recs = (trace or {}).get("records") or payload.get("records") or []
    n_ledger = sum(1 for r in recs if r.get("source") == "fact_ledger")
    n_pair = sum(1 for r in recs if r.get("source") == "conflict_pair")
    row = {
        "slug": slug, "qid": qid,
        "wall_s": wall,
        "n_calls": len(getattr(client, "call_log", []) or []),
        "acc_key_live": isinstance(trace, dict),
        "trace_file": tf.exists(),
        "summary_n": summary.get("n"),
        "n_ledger_rows": n_ledger,
        "n_pair_rows": n_pair,
        "by_class": summary.get("by_class"),
        "by_disposition": summary.get("by_disposition"),
        "coverage_rate": summary.get("coverage_rate"),
        "n_conclusions": len(d.conclusions),
        "detail_present": bool(payload.get("detail")),
        "model": MODEL_ID, "env_group": ENV_GROUP,
        "conflict_trace_flag": os.environ.get("VERITAS_CONFLICT_TRACE"),
    }
    print(f"[腿C 真跑] {slug}/{qid} 键活={row['acc_key_live']} "
          f"文件={row['trace_file']} n={row['summary_n']} "
          f"墙钟={wall}s 调用={row['n_calls']}", flush=True)
    return row


# ------------------------------------------------ 判表＋artifact


def _cmp_face(branch: dict, base: dict) -> dict[str, Any]:
    arms_b = branch["arms"]
    arms_s = base["arms"]

    def _face_hashes(arm: dict) -> dict[str, str]:
        # 等证面＝交卷 official 六件＋report 两件（剥时戳后）；
        # chain.jsonl／progress.json＝逐跑日志面（时间戳／run id），不计入
        return {k: v for k, v in arm["file_hashes"].items()
                if not k.startswith(("chain.jsonl", "progress.json"))}

    off_eq = (_face_hashes(arms_b["arm_off"])
              == _face_hashes(arms_s["arm_off"]))
    hole_g1_base = (not arms_s["arm_on_records"]["trace_file"]
                    and not arms_s["arm_on_records"]["acc_key_live"])
    g1_closed = (arms_b["arm_on_records"]["trace_file"]
                 and arms_b["arm_on_records"]["acc_key_live"]
                 and arms_b["arm_on_records"]["summary_n"] >= 1
                 and bool(arms_b["arm_on_records"]["row0_disposition"]))
    hole_g2_base = not arms_s["arm_on_empty"]["trace_file"]
    g2_closed = (arms_b["arm_on_empty"]["trace_file"]
                 and arms_b["arm_on_empty"]["empty_state"] is True
                 and "1 题" in arms_b["arm_on_empty"]["detail"]
                 and "不等于资料无冲突" in arms_b["arm_on_empty"]["detail"])
    return {
        "off_face_byte_identical": off_eq,
        "off_files": sorted(arms_b["arm_off"]["file_hashes"]),
        "base_hole_g1_trace_stripped": hole_g1_base,
        "branch_g1_closed": g1_closed,
        "base_hole_g2_empty_silent": hole_g2_base,
        "branch_g2_closed": g2_closed,
        "branch_row0": {
            "conflict_class": arms_b["arm_on_records"]["row0_conflict_class"],
            "disposition": arms_b["arm_on_records"]["row0_disposition"],
            "disposition_cn":
                arms_b["arm_on_records"]["row0_disposition_cn"],
        },
        "flag_default_off_both": (branch["flag_default_off"]
                                  and base["flag_default_off"]),
    }


def _verdict(face_cmp: dict[str, Any], replica: dict[str, Any],
             real: dict[str, Any] | None) -> dict[str, Any]:
    gates: dict[str, Any] = {}
    gates["g1_关旗与改前一致"] = face_cmp["off_face_byte_identical"]
    gates["g2_开旗出口在场_零调用"] = (
        face_cmp["branch_g1_closed"] and face_cmp["branch_g2_closed"]
        and face_cmp["base_hole_g1_trace_stripped"]
        and face_cmp["base_hole_g2_empty_silent"])
    gates["g3_旁证不掉"] = all(
        v["arm_off_vs_on"] and v["vs_c134"]
        for v in replica["compare"].values())
    gates["g4_旗默认仍关"] = face_cmp["flag_default_off_both"]
    gates["g5_真跑出口在场"] = (real is not None
                              and real["acc_key_live"]
                              and real["trace_file"])
    verdict = "YES" if all(gates.values()) else "NO"
    return {"verdict": verdict, "gates": gates}


def _render_md(v: dict[str, Any], face_cmp: dict[str, Any],
               replica: dict[str, Any], real: dict[str, Any] | None,
               pytest_note: str) -> str:
    lines: list[str] = [
        "# C-143 — 树22 冲突留痕可用化（借 C-123 窄修，不合旧枝）",
        "",
        f"> 判定＝**{v['verdict']}**（旗 VERITAS_CONFLICT_TRACE 出厂默认仍关）。",
        "> 本刀只动出口面：app/pipeline.py 两处 kept 白名单登记 "
        "conflict_trace ＋ app/export/official.py 旗开必写回放面（空态也写）。"
        "判定／打分／选段／装箱零改动；未合 C-123 整枝、未带回旧主线选料。",
        "",
        "## 0. 不带编号的说明（这段给不看代码的人）",
        "",
        "系统里有一把实验开关，打开后会把「资料里数字打架」的每一条按"
        "同窗／跨日／时点不明三类记下来，并写清处置（保留／少数意见／未决）。"
        "此前实测：开关打开后这些东西算得出来，却在写产物前被管线里一张"
        "「保留白名单」整个吃掉，交出去的文件里看不到——不是算不出，是算完被扔了。",
        "修法沿用 C-123 的两处窄修：白名单登记这个键（两处都登记）；"
        "交卷面在「一条冲突都没检出」时也写一份空态文件并写明这是未检出、"
        "不等于资料无冲突。归并硬约束（同主体×同指标×可核验才合）＝有把握才动，"
        "本轮只记账不动判定（冲突数值线 Boyu 已拍 STOP）。",
        "",
        "## 1. 腿A 出口面（零 LLM・确定性夹具・改前 vs 改后）",
        "",
        f"- 关旗臂字节等证（剥 elapsed 时戳后 report.json／report.md 与"
        f"其余产物逐文件 sha8）：{face_cmp['off_face_byte_identical']}",
        f"- 改前缺口复现：开旗臂 trace 文件写出＝"
        f"{not face_cmp['base_hole_g1_trace_stripped']}（键被白名单剥掉＝"
        f"{face_cmp['base_hole_g1_trace_stripped']}）；零对撞臂文件写出＝"
        f"{not face_cmp['base_hole_g2_empty_silent']}（空态静默＝"
        f"{face_cmp['base_hole_g2_empty_silent']}）",
        f"- 改后闭合：开旗臂键活过白名单＝"
        f"{face_cmp['branch_g1_closed']}；空态文件＋真实题数原因句＝"
        f"{face_cmp['branch_g2_closed']}",
        f"- 留痕行形状（处置行）：conflict_class＝"
        f"{face_cmp['branch_row0']['conflict_class']}｜disposition＝"
        f"{face_cmp['branch_row0']['disposition']}"
        f"（{face_cmp['branch_row0']['disposition_cn']}）",
        f"- 旗出厂默认两棵树都关：{face_cmp['flag_default_off_both']}",
        "",
        "## 2. 腿B 门控复刻（C-134 同尺・零 LLM・两旗臂）",
        "",
    ]
    for slug, row in replica["compare"].items():
        lines.append(
            f"- {slug}：两旗臂逐位同＝{row['arm_off_vs_on']}｜对 C-134 基线同＝"
            f"{row['vs_c134']}｜@7 {row['off']['cut_hits'].get('7')}｜"
            f"micro {row['off']['micro_gold_density']}｜"
            f"g2c {row['off']['mean_gold_box_to_close']}｜"
            f"leak {row['off']['n_leaks']}")
    lines += [
        "",
        "## 3. 腿C 真跑（本机 14B・零现金・生产入口 run_official_case）",
        "",
    ]
    if real:
        lines.append(
            f"- {real['slug']}/{real['qid']}｜墙钟 {real['wall_s']}s｜"
            f"模型调用 {real['n_calls']}｜键活到产物＝{real['acc_key_live']}｜"
            f"conflict_trace.json 写出＝{real['trace_file']}")
        lines.append(
            f"- 留痕条数 {real['summary_n']}（台账对撞 {real['n_ledger_rows']}"
            f"＋结论冲突对 {real['n_pair_rows']}）｜三类分布 "
            f"{real['by_class']}｜处置分布 {real['by_disposition']}｜覆盖 "
            f"{real['coverage_rate']}｜结论 {real['n_conclusions']} 条")
    else:
        lines.append("- （腿C 未跑／未交）")
    lines += [
        "",
        "## 4. 判据逐条（按单里过线口径）",
        "",
    ]
    for k, val in v["gates"].items():
        lines.append(f"- {k}＝{val}")
    lines += [
        "",
        "## 5. 诚实披露",
        "",
        "- 真跑＝一案一题、温度未钉、每臂 1 遍：只证「出口在场／不在场」，"
        "不比大小；留痕条数逐跑波动属模型采样，不是旗的效果。",
        "- 关旗字节等证剥掉了 accounting.elapsed_s／steps 时戳与 report.md "
        "那一行耗时数字（逐跑必变，与本次改动无关）。",
        "- report.md／工作台未新增冲突留痕渲染（超出「最小借用」范围，"
        "报告面＝report.json accounting＋conflict_trace.json 回放面）。",
        "- 归并硬约束最小闸未动＝只记账：动判定面须另开票（冲突数值线 STOP）。",
        f"- pytest：{pytest_note}",
        "",
        "## 6. 产物卫生",
        "",
        "- 夹具文本全部合成（客户B回款率等占位句），无官方语料原文；"
        "真跑腿只记条数／分布／档位码，不落原文。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True,
                    choices=("export", "real", "assemble"))
    ap.add_argument("--tag", default="branch")
    ap.add_argument("--out", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--branch", default="")
    ap.add_argument("--real", default="")
    ap.add_argument("--pytest", default="见交账行（探针外独立跑）")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.stage == "export":
        data = {"export": leg_export(a.tag), "replica": leg_replica()}
        path = Path(a.out or (OUT / f"export_{a.tag}.json"))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"写出 {path}", flush=True)
        return 0
    if a.stage == "real":
        row = leg_real()
        path = Path(a.out or (OUT / "real.json"))
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"写出 {path}", flush=True)
        return 0
    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    branch = json.loads(Path(a.branch).read_text(encoding="utf-8"))
    face_cmp = _cmp_face(branch["export"], base["export"])
    replica = branch["replica"]
    real = (json.loads(Path(a.real).read_text(encoding="utf-8"))
            if a.real and Path(a.real).exists() else None)
    pytest_note = a.pytest
    v = _verdict(face_cmp, replica, real)
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "C143_trace_face.json").write_text(
        json.dumps({"verdict": v, "face_compare": face_cmp,
                    "replica": replica, "real": real},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    (ART / "C143_trace_face.md").write_text(
        _render_md(v, face_cmp, replica, real, pytest_note),
        encoding="utf-8")
    print(f"判定 {v['verdict']} 闸 {v['gates']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
