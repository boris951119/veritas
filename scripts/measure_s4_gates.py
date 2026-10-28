"""S4《需求说明》新增达标线的三项实测：单专题墙钟、单分析师基线、置信度分档×金标一致率。

2026-10-17 用户拍板「三件都跑」。三份新文件里从未量过的达标线（docs/contest-requirements-S4-2026-10-17.md）：
- 「每个专题 ≤30 分钟出结果」——仓库内已有 3 倍反例（单问 32.8 分），但那是**一题**、不是**一专题**，
  且预算档与本案不同 ⇒ 必须按「一专题（该案全部题）墙钟」重量；
- 「多智能体协同」值多少分没人证过——三分析师 vs 单分析师在同一批题上的客观分与耗时差；
- 「高置信（≥0.8）结论正确率 ≥85%」——**我们没有档位字段**，也从未把置信度和金标对过一次账。

三种模式各量一件，产物只写 `S4_OUT`（默认 `/tmp/s4runs`，**不进仓库**）：
    budget  零 LLM：按窗口反解「不超窗的最大装箱字数」，全员同料 ⇒ 取 18 题的全局最小（C-19 的配置数）
    time    A：六案 × 三题真跑（三分析师），逐题 elapsed_s/n_calls/tokens，逐案墙钟 vs 1800 s
    solo    B：单分析师真跑（默认一案三题），并跑 score_official 与 A 的产物对账
    calib   C：拿本地 14B 当评判模型，把每题金标结论与我们交的结论对一次语义账 ⇒ 分档一致率表
    all     budget → time → solo → calib 顺序执行（同一时刻只有一份模型在推理）

跑法（样例集在仓库外，只读）：
    .venv/bin/python scripts/measure_s4_gates.py budget
    .venv/bin/python scripts/measure_s4_gates.py all
    .venv/bin/python scripts/measure_s4_gates.py solo --case 刘翔
    .venv/bin/python scripts/measure_s4_gates.py calib --from /tmp/s4runs/time-2026xxxx

安全闸（不发一次请求就退出）：本脚本会**强制覆盖** OPENAI_API_KEY/OPENAI_BASE_URL 为本机 Ollama
与假密钥 `ollama`，把 `settings.models` 钉成**单模型**（ModelClient 的换腿链因此不含任何云端模型），
并删掉其余供应商密钥；config.json 的 connections 若把该模型指到非本机地址同样直接退出。
**这条不是形式主义**：仓库 config.json 现在列的全是云端模型，`.env` 里是真的付费 key。

口径纪律（三条容易读错，写在输出里也写在这里）：
1. B 的单分析师**不只是少两个分析师**：`app/pipeline.py:610` 的 `if len(analysts) >= 2` 让
   归并·冲突·质证·仲裁整段跳过 ⇒ B 量的差值＝「一个人 vs 一整套协作」，不是「一个人的边际成本」。
2. C 只有 **18 个带标注单元**（每题一条金标结论）——分档表里任何一档 n<5 都没有统计意义，
   读数只用来定「阈值该放哪」，不许对外说成校准过的正确率。
3. A 的墙钟含探针调用与修复环（这两项在上一次真跑里占 218 s＋509 s）——官方计时口径（谁的机器、
   含不含探针）**还没问清**，所以本脚本同时给「整次墙钟」和「逐题 elapsed_s 之和」两个数。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OFFICIAL = os.environ.get(
    "OFFICIAL_CASES",
    os.path.expanduser("~/Desktop/veritas-testcases/样例集-拓尔思-20261012"))
OUT = Path(os.environ.get("S4_OUT", "/tmp/s4runs"))
MODEL = os.environ.get("S4_MODEL", "openai/veritas-qwen3-14b")
BASE_URL = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434/v1")
# 单次调用超时的**测量侧覆盖**（None＝沿用 `config.json`）。由 `--timeout-seconds`
# 赋值，见 `settings_for`；交件配置 `config.json` 一字不动。
TIMEOUT_OVERRIDE: int | None = None
TIME_GATE_S = 1800          # 参考线秒数（2026-10-28 起官方已撤 ≤30 分钟达标线；常量保留作事实描述）
# C-75 件①：打印用字样——数值仍比 TIME_GATE_S；旧「超／未超 + 官方半小时线」字样已撤
TIME_GATE_LABEL = "参考线（2026-10-28 起官方已撤，只作事实描述）"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "[::1]"}
OTHER_KEY_ENVS = ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                  "MX_APIKEY", "AZURE_API_KEY", "MOONSHOT_API_KEY")
BANDS = ((0.8, 1.0), (0.6, 0.8), (0.4, 0.6), (0.0, 0.4))


def scan_question_reports(root: Path) -> tuple[list[Path], int]:
    """扫产物树：收集 `**/questions/<qid>/report.json`；缺报告的题目录计入跳过。

    空 `time-*`／`solo-*`／`calib-*`（底下没有任何 questions 子树）也计 1 次跳过，
    避免「空跑次目录吃掉整臂」。返回 `(report_paths, n_skipped)`；从不因空目录抛错。
    """
    if not root.is_dir():
        return [], 0
    reports = sorted(p.resolve() for p in root.glob("**/questions/*/report.json"))
    q_dirs = [p for p in root.glob("**/questions/*") if p.is_dir()]
    n_skipped = sum(1 for q in q_dirs if not (q / "report.json").is_file())
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (child.name.startswith(("time-", "solo-", "calib-"))):
            continue
        if any(child.glob("**/questions/*")):
            continue
        n_skipped += 1
    return reports, n_skipped


def _gate_compare_phrase(wall_s: float | None) -> str:
    """墙钟 vs TIME_GATE_S 的事实描述（不含达标／未达标语气）。"""
    w = float(wall_s or 0)
    side = "高于" if w > TIME_GATE_S else "不高于"
    return f"{side}{TIME_GATE_LABEL} {TIME_GATE_S:g}s"


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.startswith("127.")


def lock_local() -> str:
    """把网关钉死在本机，任何不满足的情况直接退出（宁可不跑）。"""
    if not _is_local(BASE_URL):
        raise SystemExit(f"拒绝：OLLAMA_BASE 不是本机地址 {BASE_URL}")
    os.environ["OPENAI_API_KEY"] = "ollama"
    os.environ["OPENAI_BASE_URL"] = BASE_URL
    os.environ["VERITAS_MODELS"] = MODEL
    os.environ["VERITAS_OCR"] = "0"
    for key in OTHER_KEY_ENVS:
        os.environ.pop(key, None)
    from app.llm.connections import resolve_credentials

    creds = resolve_credentials(MODEL) or {}
    if creds.get("base_url") and not _is_local(creds["base_url"]):
        raise SystemExit(f"拒绝：config.json 把 {MODEL} 连到非本机 {creds['base_url']}")
    return f"网关={BASE_URL} 模型={MODEL}（单模型链、假密钥）"


def settings_for(budget: int | None):
    from app.config import Settings

    st = Settings.from_env()
    st.models = [MODEL]
    if budget is not None:
        st.material_char_budget = int(budget)
    # 超时只在**测量侧**覆盖，不写进 `config.json`（那是交件配置、云端也读它）。
    # 动因＝10-25 吉隆四次整案中断：本机单网关把三分析师串成一队，单次调用
    # 已贴 300s 线；而超时按设计不在同腿重试（防烧穿多腿链），单模型链没有
    # 备胎 ⇒ 一次贴线抖动直接升级成整案报废。放宽窗口不改变任何判定口径。
    if TIMEOUT_OVERRIDE is not None:
        st.llm_timeout_seconds = int(TIMEOUT_OVERRIDE)
    st.ocr_enabled = False
    return st.validate()


def case_dirs() -> list[Path]:
    if not os.path.isdir(OFFICIAL):
        raise SystemExit(f"找不到官方样例集：{OFFICIAL}（用 OFFICIAL_CASES 指定；样例集不入仓库）")
    out = []
    for name in sorted(os.listdir(OFFICIAL)):
        d = Path(OFFICIAL) / name
        if (d / "raw_documents.json").is_file() and (d / "conclusions.json").is_file():
            out.append(d)
    if not out:
        raise SystemExit(f"{OFFICIAL} 下没有官方案卷")
    return out


def questions_of(case_dir: Path) -> list[dict]:
    """从结论样例只抽 question_id 与 question，先落成清单文件（研判之外）。

    清单落 S4_OUT，不写案例目录——样例集只读。"""
    rows = json.loads((case_dir / "conclusions.json").read_text(encoding="utf-8"))
    seen: dict[str, str] = {}
    for r in rows:
        qid = str(r.get("question_id") or "").strip()
        q = str(r.get("question") or "").strip()
        if qid and q and qid not in seen:
            seen[qid] = q
    if not seen:
        raise SystemExit(f"{case_dir.name} 的结论样例里没有 question_id/question")
    path = OUT / "questions" / f"{case_dir.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"question_id": k, "question": v}
                                for k, v in seen.items()],
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return [{"question_id": k, "question": v} for k, v in seen.items()]


def _read_report(q_dir: Path) -> dict:
    data = json.loads((q_dir / "report.json").read_text(encoding="utf-8"))
    acc = data.get("accounting") or {}
    pw = acc.get("prompt_window") or {}
    cons = [c for c in (data.get("conclusions") or []) if c.get("status") != "merged"]
    return {"accounting": acc, "prompt_window": pw, "conclusions": cons,
            "dossier": data}


def _exported_rows(case_run: Path) -> list[dict]:
    """提交物 `confidence.json` 的原始行（案级、只含 majority 态）。缺文件＝空表。"""
    f = case_run / "confidence.json"
    if not f.is_file():
        return []
    return [r for r in json.loads(f.read_text(encoding="utf-8"))
            if isinstance(r, dict) and isinstance(r.get("score"), (int, float))]


def _exported_scores(case_run: Path) -> dict[str, float]:
    """取**提交物**里的置信度行（`confidence.json` 在案级，只交 majority 态）。

    缺这个文件＝这份产物早于导出层，返回空表而不是拿 report 的字段凑数。"""
    return {str(r["conclusion_id"]): float(r["score"])
            for r in _exported_rows(case_run) if r.get("conclusion_id") is not None}


def _submitted_conclusions(case_run: Path) -> dict[str, dict]:
    """取**官方真正收到的那份结论**（`conclusions.json`，每题一行、由 `_conclusion_text` 生成）。

    这是「消解后一致率」这条达标行的被评对象——它跟 `report.json` 里的内部结论集**不是一个集合**
    （内部每题可有多条、含 `insufficient`／`dissent` 态，提交层每题只交一条 headline）。"""
    f = case_run / "conclusions.json"
    if not f.is_file():
        return {}
    out: dict[str, dict] = {}
    by_q: dict[str, list[float]] = {}
    for r in _exported_rows(case_run):
        by_q.setdefault(str(r.get("question_id")), []).append(float(r["score"]))
    for row in json.loads(f.read_text(encoding="utf-8")):
        if not isinstance(row, dict) or row.get("question_id") is None:
            continue
        qid = str(row["question_id"])
        scores = by_q.get(qid) or []
        out[qid] = {"statement": str(row.get("conclusion") or ""),
                    "n_facts": len(row.get("supporting_facts") or []),
                    "max_score": max(scores) if scores else None}
    return out


def env_snapshot() -> dict:
    """本机内存态一帧（2026-10-20 吉隆定责学出来的：墙钟超闸的第一嫌疑是换页，不是代码）。

    那一轮同一份代码、同一个 `budget_used`、calls/tokens 只差 4%，整案墙钟却从
    1,322.5 s 涨到 2,290.3 s——只有把 swap／空闲内存逐题落到 rows.jsonl 里，
    「环境 vs 代码」这道账才不必靠人回忆。只读；没有这两条命令的机器返回空 dict，
    绝不因为测量帧报错而打断数小时的真跑。
    """
    out: dict = {}
    if sys.platform != "darwin":
        return out
    try:
        import subprocess

        sw = subprocess.run(["sysctl", "-n", "vm.swapusage"],
                            capture_output=True, text=True, timeout=5).stdout
        used = re.search(r"used\s*=\s*([\d.]+)M", sw)
        total = re.search(r"total\s*=\s*([\d.]+)M", sw)
        if used:
            out["swap_used_mb"] = float(used.group(1))
        if total:
            out["swap_total_mb"] = float(total.group(1))
        mp = subprocess.run(["memory_pressure", "-Q"],
                            capture_output=True, text=True, timeout=10).stdout
        free = re.search(r"percentage:\s*(\d+)%", mp)
        if free:
            out["mem_free_pct"] = int(free.group(1))
    except Exception as exc:                                    # 测量帧不许炸真跑
        out["env_error"] = f"{type(exc).__name__}: {exc}"
    return out


def preflight(st) -> None:
    from app.llm.model_client import ModelClientFactory

    client = ModelClientFactory(st).create()
    resp = client.chat(MODEL, [{"role": "user", "content": "只回复两个字：正常"}])
    print(f"[预检] {lock_local()} 应答 {resp.model!r} {resp.content[:12]!r} "
          f"tok={resp.total_tokens}", flush=True)


# ---------------------------------------------------------------- budget ----
def fit_safe_budget(snap, window: int, density: float, ref: int) -> tuple[int, dict]:
    """C-19 将落地的「迭代缩档」在测量侧的同口径近似（**未动生产代码**）。

    线性反解（两点：0 字与 `ref` 字）＋有界回退（≤6 步，每次 −12%），
    目标＝**渲染后的整条提示词** est ≤ 窗口满值（不减 `max_response_tokens`——
    C-19 ③ 已实测输出不参与截断）。渲染与估算全部复用 `scripts/probe_pack_window.py`
    ＋`app/core/prompt_guard.estimate_prompt_window`，避免两处口径漂移。
    """
    import probe_pack_window as ppw
    from app.core.prompt_guard import estimate_prompt_window

    chars_cap = int(window * density)
    est = {}
    for b in (0, ref):
        msgs, _ = ppw.messages_for(snap, b)
        rec = estimate_prompt_window(msgs, window_tokens=window,
                                     zh_chars_per_token=density)
        est[b] = rec["total_chars"]
    slope = max(0.5, (est[ref] - est[0]) / ref)
    fit = max(0, min(int((chars_cap - est[0]) / slope), 40_000))
    rec = {"total_chars": est[ref], "est_tokens": 0, "overflow_tokens": 0}
    selected: set[str] = set()
    n_over = 0
    while True:
        msgs, selected = ppw.messages_for(snap, fit)
        rec = estimate_prompt_window(msgs, window_tokens=window,
                                     zh_chars_per_token=density)
        if rec["overflow_tokens"] == 0 or n_over > 6:
            break
        n_over += 1
        fit = max(0, int(fit - fit * 0.12))
    return fit, {"rec": rec, "n_iters": n_over, "selected": selected}


def cmd_budget(args) -> int:
    """零 LLM：逐题反解「整条提示词刚好不超窗」的最大装箱字数。"""
    import probe_pack_window as ppw
    from app.config import Settings
    from app.core.evidence import Dossier
    from app.ingest.official_case import load_official_case

    st = Settings.from_env()
    window = int(st.model_context_tokens)
    density = float(st.zh_chars_per_token)
    chars_cap = int(window * density)
    ref = int(os.environ.get("BUDGET", "19000"))
    rows = []
    for case_dir in case_dirs():
        base = load_official_case(case_dir)
        for qid, question, gold in ppw.question_gold(case_dir):
            snap = Dossier.from_dict(base.to_dict())
            snap.question = question or "该案议题"
            fit, extra = fit_safe_budget(snap, window, density, ref)
            rec = extra["rec"]
            rows.append({"case": case_dir.name, "qid": qid, "n_gold": len(gold),
                         "safe_budget": fit, "prompt_chars": rec["total_chars"],
                         "est_tokens": rec["est_tokens"], "window": window,
                         "n_iters": extra["n_iters"],
                         "overflow_at_fit": rec["overflow_tokens"],
                         "gold_selected": len(gold & extra["selected"])})
            print(f"{case_dir.name[:18]:<20} {qid} 安全预算 {fit:>6} 字 "
                  f"提示词 {rec['total_chars']:>6} 字 ≈{rec['est_tokens']:>6} tok "
                  f"迭代 {extra['n_iters']} 次 金标可见 "
                  f"{len(gold & extra['selected']):>3}/{len(gold)}", flush=True)
    safe = min(r["safe_budget"] for r in rows)
    summary = {"window_tokens": window, "zh_chars_per_token": density,
               "chars_cap": chars_cap, "global_min_safe_budget": safe,
               "gold_selected_at_safe": sum(r["gold_selected"] for r in rows),
               "gold_total": sum(r["n_gold"] for r in rows),
               "per_case_min": {}, "rows": rows}
    for r in rows:
        cur = summary["per_case_min"].get(r["case"])
        if cur is None or r["safe_budget"] < cur:
            summary["per_case_min"][r["case"]] = r["safe_budget"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "budget.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n窗口满值 {window} tok ≈ {chars_cap} 字（密度 {density}）")
    print(f"全员同料的全局最小安全预算 = {safe} 字 → 金标可见 "
          f"{summary['gold_selected_at_safe']}/{summary['gold_total']} 段")
    print(f"已写 {OUT / 'budget.json'}")
    return 0


# ------------------------------------------------------------------ time ----
def run_questions(label: str, roster: list | None, only_case: str | None,
                  align: bool = True, ref: int = 19000,
                  fixed: int | None = None) -> dict:
    """真跑一遍（A/B 共用）：逐案逐题记录耗时、调用数、窗口读数、结论数。

    **逐题预算对齐**（`align=True`，默认）：每题先按 C-19 的口径反解窗口安全预算，
    再用该预算跑这一题——这就是 C-19 落地后生产路径的行为（`material_char_budget` 是上限不是目标）。
    为什么不走现成的 `run_official_case`（`app/pipeline.py:1503`）：它把 settings 一次定死、
    一案一值，而窗口对齐要求**每题一个值**；本函数是它同一个函数体的逐题展开（`load_official_case`
    一次 → 逐题 `Dossier.from_dict` 快照 → `run_case(RunSpec(dossier=…))` → 末尾 `export_official`），
    除预算外不改任何编排。**若生产侧 C-19 落地，本函数应改为直接调它，读数以那张单的判据为准。**
    """
    import copy

    from app.core.evidence import Dossier
    from app.export.official import export_official
    from app.ingest.official_case import load_official_case
    from app.pipeline import RunSpec, run_case

    gate = lock_local()                     # 必须在任何 Settings.from_env 之前：先钉网关再读配置
    st = settings_for(None if align else fixed)
    window = int(st.model_context_tokens)
    density = float(st.zh_chars_per_token)
    how = (f"逐题反解（线性拟合参考档 {ref} 字）" if align
           else f"固定预算 {st.material_char_budget} 字")
    print(f"[{label}] {gate} {how} 模型链={st.models} 窗口={window} tok "
          f"密度={density} 超时={st.llm_timeout_seconds}s "
          f"输出上限={st.max_response_tokens} 探针={st.model_probe_enabled} "
          f"second_pass={st.second_pass_enabled}", flush=True)
    preflight(st)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = OUT / f"{label}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    interrupted_cases: list[str] = []
    t_all = time.monotonic()
    for case_dir in case_dirs():
        if only_case and only_case not in case_dir.name:
            continue
        questions = questions_of(case_dir)
        case_out = run_dir / case_dir.name
        t_case = time.monotonic()
        runs: list[tuple[dict, Dossier]] = []
        try:
            base = load_official_case(case_dir)
            for question in questions:
                snap = Dossier.from_dict(base.to_dict())
                snap.question = str(question["question"])
                st_q = copy.deepcopy(st)
                extra = None
                if align:
                    fit, extra = fit_safe_budget(snap, window, density, ref)
                    st_q.material_char_budget = min(
                        fit, int(st.material_char_budget))
                t_q = time.monotonic()
                env_before = env_snapshot()
                result = run_case(RunSpec(
                    dossier=snap,
                    out_dir=case_out / "questions" / str(question["question_id"]),
                    settings=st_q, roster=roster))
                wall_q = round(time.monotonic() - t_q, 1)
                env_after = env_snapshot()
                data = result.dossier.to_dict()
                acc = data.get("accounting") or {}
                pw = acc.get("prompt_window") or {}
                # 生产侧的整条提示词只有**超窗时**才写（C-9 丙的设计）：accounting 里没 total_chars，
                # 字数在同一条 ingest_note（kind=prompt_over_window）里。不超窗那格生产不记 ⇒ 只能印 —，
                # 拿拟合值顶位会把两套口径混成一行（王虹 q_003 因此印成「拟合 12,173 tok 却超窗 3,396」）。
                over_note = next((n for n in (data.get("ingest_notes") or [])
                                  if n.get("kind") == "prompt_over_window"), {})
                fit_rec = (extra or {}).get("rec") or {}
                cons = [c for c in (data.get("conclusions") or [])
                        if c.get("status") != "merged"]
                rows.append({
                    "case": case_dir.name, "qid": question["question_id"],
                    "budget_used": st_q.material_char_budget,
                    "wall_q_s": wall_q,
                    "elapsed_s": acc.get("elapsed_s"),
                    "n_calls": acc.get("n_calls"), "tokens": acc.get("tokens"),
                    # 拟合口径（探针替身消息列表，只含 system＋资料块）
                    "fit_prompt_chars": fit_rec.get("total_chars"),
                    "fit_est_tokens": fit_rec.get("est_tokens"),
                    "fit_overflow_tokens": fit_rec.get("overflow_tokens"),
                    # 生产口径（真发出去的那条，app/agents/base.py:149-150 仅在超窗时留痕）
                    "prod_prompt_chars": over_note.get("total_chars"),
                    "prod_est_tokens": over_note.get("est_tokens") or pw.get("est_tokens"),
                    "prod_overflow_tokens": pw.get("overflow_tokens"),
                    "align_iters": (extra or {}).get("n_iters"),
                    "n_conclusions": len(cons),
                    "steps": {s.get("id"): s.get("elapsed_s")
                              for s in (acc.get("steps") or [])},
                    # 环境帧＋吞吐：墙钟异常先问这两个数，再动代码
                    "tok_per_s": (round((acc.get("tokens") or 0) / wall_q, 1)
                                  if wall_q else None),
                    "env_before": env_before, "env_after": env_after,
                })
                _append_jsonl(run_dir / "rows.jsonl", rows[-1])
                r = rows[-1]
                print(f"  {case_dir.name[:16]:<18} {r['qid']} 题墙钟 {r['wall_q_s']:>7}s "
                      f"(埋点 {r['elapsed_s']}) 预算 {r['budget_used']:>6} 字 "
                      f"调用 {r['n_calls']:>2} tok {r['tokens']:>6} "
                      f"吞吐 {r['tok_per_s']}tok/s "
                      f"空闲内存 {r['env_after'].get('mem_free_pct')}% "
                      f"swap {r['env_after'].get('swap_used_mb')}MB "
                      f"拟合 {r['fit_prompt_chars'] or 0:>6}字/{r['fit_est_tokens'] or 0:>6}tok "
                      f"生产 {r['prod_prompt_chars'] or '—':>6}/"
                      f"{r['prod_est_tokens'] or '—':>6} "
                      f"超窗 {r['prod_overflow_tokens'] or 0:>5} 结论 {r['n_conclusions']:>2}",
                      flush=True)
                runs.append((question, result.dossier))
            export_official(runs, case_out)
        except Exception as exc:            # 一案炸不许带走整轮（数小时的进度在盘上）
            print(f"  ⚠ {case_dir.name} 整案中断：{type(exc).__name__}: {exc}", flush=True)
            _append_jsonl(run_dir / "errors.jsonl", {
                "case": case_dir.name, "error": f"{type(exc).__name__}: {exc}"})
            interrupted_cases.append(case_dir.name)
        case_wall = round(time.monotonic() - t_case, 1)
        for r in rows:
            if r["case"] == case_dir.name and "wall_case_s" not in r:
                r["wall_case_s"] = case_wall
        if case_dir.name in interrupted_cases:
            # C-75 件①b：中断不许被「未超线」洗白；未出结论的题单列
            done_q = {r["qid"] for r in rows if r["case"] == case_dir.name}
            missing_q = [q["question_id"] for q in questions if q["question_id"] not in done_q]
            miss = "、".join(missing_q) if missing_q else "（无）"
            print(f"  → {case_dir.name[:22]:<24} 整案中断，未据此判定"
                  f"（墙钟 {case_wall:>7}s；未出结论的题：{miss}）", flush=True)
        else:
            print(f"  → {case_dir.name[:22]:<24} 整案墙钟 {case_wall:>7}s "
                  f"{_gate_compare_phrase(case_wall)}", flush=True)
    total = round(time.monotonic() - t_all, 1)
    per_case = {}
    for r in rows:
        per_case[r["case"]] = r.get("wall_case_s")
    # 达标／参考线统计只算完成案例（中断案单列，不当过线／未过线）
    completed = {c: w for c, w in per_case.items() if c not in interrupted_cases}
    summary = {"label": label, "run_dir": str(run_dir), "align": align,
               "ref_budget": ref if align else None,
               "fixed_budget": None if align else st.material_char_budget,
               "window_tokens": window, "zh_chars_per_token": density,
               "llm_timeout_seconds": st.llm_timeout_seconds,
               "timeout_overridden": TIMEOUT_OVERRIDE is not None,
               "time_gate_s": TIME_GATE_S,
               "time_gate_label": TIME_GATE_LABEL,
               "roster": None if roster is None else [x[0] for x in roster],
               "total_wall_s": total, "rows": rows,
               "case_wall_s": per_case,
               "interrupted_cases": list(interrupted_cases),
               "case_sum_elapsed_s": {
                   c: round(sum(float(r["elapsed_s"] or 0) for r in rows
                                if r["case"] == c), 1) for c in per_case},
               "over_gate": {c: (w, bool(w and w > TIME_GATE_S))
                             for c, w in completed.items()}}
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[{label}] 总墙钟 {total}s → {run_dir}")
    if interrupted_cases:
        print(f"  整案中断 {len(interrupted_cases)} 案（未据此判定）："
              + "、".join(interrupted_cases), flush=True)
    for case, wall in per_case.items():
        if case in interrupted_cases:
            print(f"  {case[:24]:<26} 整案中断，未据此判定"
                  f"（墙钟 {wall or 0:>8}s）", flush=True)
            continue
        print(f"  {case[:24]:<26} 整案墙钟 {wall or 0:>8}s "
              f"逐题 elapsed 之和 {summary['case_sum_elapsed_s'].get(case, 0):>8}s "
              f"{_gate_compare_phrase(wall)}", flush=True)
    return summary


def _append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_time(args) -> int:
    run_questions("time", None, args.case, align=args.align, ref=args.ref,
                  fixed=args.budget)
    return 0


# ------------------------------------------------------------------ solo ----
def cmd_solo(args) -> int:
    """B：单分析师基线。预算与 time 用**同一个对齐函数**（确定性 ⇒ 逐题同值），
    否则质量差里混进"料不一样"这一项，读数不能归因给分析师人数。"""
    from app.agents.panel import MAINSTREAM_PERSONA

    solo = [("solo-mainstream", MAINSTREAM_PERSONA)]
    summary = run_questions("solo", solo, args.case, align=args.align,
                            ref=args.ref, fixed=args.budget)
    _solo_vs_panel(summary)
    return 0


def _solo_vs_panel(solo: dict) -> None:
    """把 solo 产物与同题的 panel 产物各跑一遍 2.1 第一阶段精确匹配（零 LLM）。

    只比客观分下界：结论正确率（2.3）要官方那台大模型，我们没有。"""
    import score_official as so

    panel_dir = _latest_run_dir("time")
    keys = ("Precision_src", "Recall_src", "F1_src", "score_2_2_1",
            "Precision_sup", "Recall_sup", "score_2_4_1",
            "missing_questions", "bare_supporting")
    print("\n== 客观分下界对账（2.1 第一阶段精确匹配；solo vs 三分析师）==", flush=True)
    if panel_dir is not None:
        panel_rows = json.loads((panel_dir / "summary.json").read_text(encoding="utf-8"))["rows"]
        panel_budget = {(r["case"], r["qid"]): r.get("budget_used") for r in panel_rows}
        mism = [(r["case"], r["qid"], r.get("budget_used"),
                 panel_budget.get((r["case"], r["qid"])))
                for r in solo["rows"]
                if panel_budget.get((r["case"], r["qid"])) != r.get("budget_used")]
        if mism:
            print(f"⚠ 两侧**进窗字数不同**，差值不能全归因给分析师人数：{mism}", flush=True)
    print(f"{'案例':<22}{'侧':>6}" + "".join(f"{k:>16}" for k in keys))
    for case_name in sorted({r["case"] for r in solo["rows"]}):
        case_dir = Path(OFFICIAL) / case_name
        sides = [("solo", Path(solo["run_dir"]) / case_name)]
        if panel_dir is not None:
            sides.append(("panel", panel_dir / case_name))
        for label, art in sides:
            if not (art / "evidence.json").is_file():
                print(f"{case_name[:20]:<22}{label:>6}  产物缺失：{art}")
                continue
            m = so.score_submission(
                art / "evidence.json", art / "conclusions.json",
                case_dir / "evidence_samples.json", case_dir / "conclusions.json",
                raw_documents_path=case_dir / "raw_documents.json")
            print(f"{case_name[:20]:<22}{label:>6}"
                  + "".join(f"{_fmt(m.get(k)):>16}" for k in keys), flush=True)
    if panel_dir is None:
        print("⚠ 没有 time 模式产物 ⇒ 只有 solo 一侧，差值待 time 跑完再算："
              f"`{sys.argv[0]} calib`/重跑本模式即可对上账。")
    else:
        print(f"（panel 一侧取自 {panel_dir}）")


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    return "—" if v is None else str(v)


def _latest_run_dir(label: str) -> Path | None:
    if not OUT.is_dir():
        return None
    cands = sorted(p for p in OUT.glob(f"{label}-*") if (p / "summary.json").is_file())
    return cands[-1] if cands else None


# ----------------------------------------------------------------- calib ----
JUDGE_SYSTEM = (
    "你在做结论级语义对齐。只判断「待评结论」是否表达了「金标结论」的核心主张。"
    "口径：一致＝主张与关键限定都相同；部分一致＝主张方向相同但限定或口径不同；"
    "不一致＝主张相反或答的不是同一件事；未答＝待评结论里没有可对齐的主张。"
    "必须只输出 JSON 对象，键为 agreement、matched、why。matched 是待评结论 id 数组，可为空。")


def judge_one(client, model: str, gold: str, ours: list[dict]) -> dict:
    lines = []
    for c in ours:
        lines.append(f"[{c['id']}]（置信度 {float(c.get('confidence') or 0):.3f}，"
                     f"{c.get('status')}）{c.get('statement')}")
    user = ("金标结论：\n" + gold + "\n\n待评结论（本次系统产出）：\n"
            + ("\n".join(lines) or "（本次没有交付任何结论）"))
    try:
        resp = client.chat(model, [{"role": "system", "content": JUDGE_SYSTEM},
                                   {"role": "user", "content": user}], json_mode=True)
        from app.agents.base import extract_json

        data = extract_json(resp.content)
        return {"agreement": str(data.get("agreement") or "未答"),
                "matched": [str(x) for x in (data.get("matched") or [])],
                "why": str(data.get("why") or "")[:200],
                "judge_tokens": resp.total_tokens}
    except Exception as exc:                      # 评判失败要留痕，不许当"不一致"
        return {"agreement": "评判失败", "matched": [], "why": "",
                "error": f"{type(exc).__name__}: {exc}"}


def cmd_calib(args) -> int:
    """把每题金标结论与我们交的结论对一次语义账 ⇒ 置信度分档表（C-20 的前置数）。"""
    from app.llm.model_client import ModelClientFactory

    src = Path(args.from_dir) if args.from_dir else _latest_run_dir("time")
    if not src or not src.is_dir():
        raise SystemExit("找不到 time 模式的产物目录（用 --from 指定）")
    gate = lock_local()
    st = settings_for(None)
    client = ModelClientFactory(st).create()
    print(f"[calib] {gate} 读取 {src} 对齐口径＝"
          f"{'提交物 conclusions.json 每题那一行' if getattr(args, 'submitted', False) else 'report.json 内部结论集（每题多条）'}",
          flush=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = OUT / f"calib-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    conf_hist: list[float] = []
    n_noscore = 0
    n_sub_missing = 0
    # C-75 件①a：先扫一遍，空跑次／缺报告题计入跳过，不许因空目录中止整臂
    _reports, n_scan_skipped = scan_question_reports(src)
    report_set = {p.resolve() for p in _reports}
    for case_dir in case_dirs():
        case_run = src / case_dir.name
        if not case_run.is_dir():
            continue
        gold_rows = json.loads((case_dir / "conclusions.json").read_text(encoding="utf-8"))
        band_by_id = _exported_scores(case_run)
        sub_mode = bool(getattr(args, "submitted", False))
        submitted_by_q = _submitted_conclusions(case_run) if sub_mode else {}
        gold_by_q: dict[str, str] = {}
        for g in gold_rows:
            gold_by_q.setdefault(str(g.get("question_id")), str(g.get("conclusion") or ""))
        for qid, gold in gold_by_q.items():
            q_dir = case_run / "questions" / qid
            rep_path = (q_dir / "report.json").resolve()
            if rep_path not in report_set:
                rows.append({"case": case_dir.name, "qid": qid,
                             "agreement": "无产物", "matched": [], "why": ""})
                continue
            rep = _read_report(q_dir)
            ours = rep["conclusions"]
            # 置信度只按**提交物里真存在的行**统计：`confidence.json` 在案级、只交 majority 态，
            # 拿 report 里的 confidence 字段去凑会把没分档的结论当成 0（曾量出 median 0.0／lt_0.4=96 那种假数）
            noscore = [c["id"] for c in ours if c["id"] not in band_by_id]
            n_noscore += len(noscore)
            conf_hist.extend(band_by_id[c["id"]] for c in ours if c["id"] in band_by_id)
            if sub_mode:
                # 达标行「消解后一致率」的被评对象＝官方收到的那一行（每题一条 headline），
                # 不是 report 里的内部结论集（每题可多条、含 insufficient／dissent）。两套不许混，
                # 所以这里是**另一条独立读数**，用 align_scope 标着，内部那版照旧跑得到。
                # ⚠ 分支条件必须是 `sub_mode` 而不是 `submitted_by_q`（真数踩过）：整案提交物为 `[]`
                # 时那个字典是空的，按真值判会**悄悄退回内部口径**，一格里混两套读数。
                sub = submitted_by_q.get(qid) or {"statement": "", "max_score": None, "n_facts": 0}
                target = [{"id": f"SUB::{qid}", "statement": sub["statement"],
                           "status": "submitted"}]
                verdict = judge_one(client, MODEL, gold, target)
                matched_conf = [sub["max_score"]] if sub["max_score"] is not None else []
                n_sub_missing += (0 if sub["statement"].strip() else 1)
            else:
                verdict = judge_one(client, MODEL, gold, ours)
                matched_conf = [band_by_id[m] for m in verdict["matched"]
                                if m in band_by_id]
            rows.append({"case": case_dir.name, "qid": qid, "n_ours": len(ours),
                         "align_scope": "submitted" if sub_mode else "internal",
                         "n_band_rows": len(band_by_id), "n_no_band_row": len(noscore),
                         "gold_chars": len(gold),
                         "agreement": verdict["agreement"],
                         "matched": verdict["matched"],
                         "matched_conf": [round(x, 3) for x in matched_conf if x is not None],
                         "max_matched_conf": (round(max(matched_conf), 3)
                                              if matched_conf else None),
                         "why": verdict.get("why") or verdict.get("error", "")})
            r = rows[-1]
            print(f"  {case_dir.name[:16]:<18} {qid} {r['agreement']:<5} "
                  f"命中 {len(r['matched'])} 条 最高置信 "
                  f"{r['max_matched_conf'] if r['max_matched_conf'] is not None else '—'}",
                  flush=True)
            _append_jsonl(out_dir / "rows.jsonl", rows[-1])

    scope = "submitted" if getattr(args, "submitted", False) else "internal"
    table = _band_table(rows, conf_hist)
    summary = {"run_dir": str(out_dir), "source": str(src), "rows": rows,
               "bands": table, "n_units": len(rows), "align_scope": scope,
               "n_sub_empty": n_sub_missing,
               "n_ours": len(conf_hist), "n_no_band_row": n_noscore,
               "conf_stats": _conf_stats(conf_hist)}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_calib_md(out_dir / "calib.md", summary)
    print("\n== 置信度分档 × 与金标语义一致率 ==")
    print(f"{'档位':<14}{'金标题数':>8}{'一致':>6}{'部分一致':>8}{'不一致':>7}{'正确率':>9}")
    for b in table:
        rate = "—" if b["n"] == 0 else f"{b['agree'] / b['n'] * 100:.0f}%"
        print(f"{b['label']:<14}{b['n']:>8}{b['agree']:>6}{b['partial']:>8}"
              f"{b['disagree']:>7}{rate:>9}")
    print(f"\n对齐口径＝{summary['align_scope']}"
          + (f"；提交层交空白的那题 {summary['n_sub_empty']} 个" if scope == "submitted" else ""))
    print(f"标注单元 n={summary['n_units']}（官方六案每题一条金标结论＝上限 18）；"
          f"分档口径＝提交物 `confidence.json` 的行（只含 majority 态），"
          f"计入 {summary['n_ours']} 条、无分档行 {summary['n_no_band_row']} 条"
          f"（minority／conflict 态，导出层本就不交），分布见 {out_dir / 'calib.md'}")
    # C-75 件①a：空跑次／缺报告必须显式披露跳过数（失败即跳，不许吃掉整臂）
    print(f"扫描跳过 {n_scan_skipped}（空 time-*／缺 report.json 的题目录；"
          f"有报告 {len(_reports)}）", flush=True)
    print("⚠ n<5 的档位没有统计意义；此表只用来定阈值，不是可对外声明的校准正确率。")
    return 0


def _band_table(rows: list[dict], conf: list[float]) -> list[dict]:
    out = []
    for lo, hi in BANDS:
        unit = [r for r in rows
                if r.get("max_matched_conf") is not None
                and lo <= r["max_matched_conf"] < hi + (1e-9 if hi == 1.0 else 0)]
        out.append({"label": f"[{lo:g}, {hi:g})", "band_lo": lo, "band_hi": hi,
                    "n": len(unit),
                    "agree": sum(1 for r in unit if r.get("agreement") == "一致"),
                    "partial": sum(1 for r in unit if r.get("agreement") == "部分一致"),
                    "disagree": sum(1 for r in unit
                                    if r.get("agreement") in ("不一致", "未答", "评判失败")),
                    "n_ours_in_band": sum(1 for c in conf if lo <= c < hi + (1e-9 if hi == 1.0 else 0))})
    return out


def _conf_stats(conf: list[float]) -> dict:
    if not conf:
        return {"n": 0}
    xs = sorted(conf)
    return {"n": len(xs), "min": round(xs[0], 3), "max": round(xs[-1], 3),
            "median": round(xs[len(xs) // 2], 3),
            "mean": round(sum(xs) / len(xs), 3),
            "ge_0.8": sum(1 for c in xs if c >= 0.8),
            "lt_0.4": sum(1 for c in xs if c < 0.4)}


def _write_calib_md(path: Path, s: dict) -> None:
    lines = ["# 置信度分档 × 金标语义一致率（本机 14B 当评判模型）", "",
             f"- 产物来源：`{s['source']}`",
             f"- 标注单元 n={s['n_units']}；分档口径＝提交物 `confidence.json` 的行（只含 majority 态）："
             f"计入 {s['n_ours']} 条、无分档行 {s.get('n_no_band_row', 0)} 条",
             f"- 置信度分布：{json.dumps(s['conf_stats'], ensure_ascii=False)}", "",
             "| 档位 | 命中该档的金标题数 | 一致 | 部分一致 | 不一致/未答 | 正确率 | 系统结论落该档条数 |",
             "|---|---|---|---|---|---|---|"]
    for b in s["bands"]:
        rate = "—" if not b["n"] else f"{b['agree'] / b['n'] * 100:.0f}%"
        lines.append(f"| {b['label']} | {b['n']} | {b['agree']} | {b['partial']} "
                     f"| {b['disagree']} | {rate} | {b['n_ours_in_band']} |")
    lines += ["", "## 逐题读数", "",
              "| 案例 | 题 | 一致判定 | 命中结论 | 最高置信 | 评判理由 |", "|---|---|---|---|---|---|"]
    for r in s["rows"]:
        why = re.sub(r"\|", "／", str(r.get("why", "")))[:60]
        lines.append(f"| {r['case'][:14]} | {r['qid']} | {r.get('agreement', '')} "
                     f"| {len(r.get('matched') or [])} "
                     f"| {r.get('max_matched_conf', '—')} | {why} |")
    lines += ["", "⚠ 口径：官方六案只有 18 条金标结论 ⇒ 每个档位最多 18 个标注单元，",
              "任何 n<5 的档都没有统计意义；本表用来定 C-20 的阈值，不能当校准过的正确率对外声明。"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------- all ----
def cmd_all(args) -> int:
    """顺序跑四项：任何一项炸掉都记下继续（一轮要几个小时，不能一错全弃）。"""
    import traceback

    failed = []
    for name, fn in (("budget", cmd_budget), ("time", cmd_time),
                     ("solo", cmd_solo), ("calib", cmd_calib)):
        print(f"\n########## {name} ##########", flush=True)
        try:
            fn(args)
        except SystemExit as exc:            # 样例集缺失／没有前置产物 = 该停就停
            print(f"[{name}] 停止：{exc}", flush=True)
            failed.append(name)
            if name == "budget":
                return 2
        except Exception:
            print(f"[{name}] 异常，继续下一项：", flush=True)
            traceback.print_exc()
            failed.append(name)
    print(f"\nall 完成，失败项={failed or '无'}", flush=True)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="S4 达标线三项实测（本机 14B，产物只落 S4_OUT）")
    parser.add_argument("mode", choices=["budget", "time", "solo", "calib", "all"])
    parser.add_argument("--budget", type=int, default=None,
                        help="配合 --no-align：固定装箱字数（不给则用 config 默认 8 万字）")
    parser.add_argument("--ref", type=int, default=int(os.environ.get("BUDGET", "19000")),
                        help="窗口反解的线性拟合参考档（默认 19000＝上次真跑实证预算）")
    parser.add_argument("--no-align", dest="align", action="store_false",
                        help="不做窗口对齐，按固定预算跑（复放旧读数时用）")
    parser.add_argument("--case", default=None,
                        help="只跑案名含该子串的案例（子串匹配）。solo 不给时默认「刘翔」；"
                             "time 不给＝跑全部六案（C-18 落地后补量单案墙钟用 `time --case 吉隆`）")
    parser.add_argument("--timeout-seconds", dest="timeout_seconds", type=int, default=None,
                        help="**只在测量侧**覆盖单次 LLM 调用超时（默认沿用 config.json 的 300s）。"
                             "本机单网关把三分析师串成一队、单次调用已贴 300s 线，而超时按设计不在"
                             "同腿重试＋单模型链无备胎 ⇒ 一次贴线抖动会升级成整案报废（吉隆四次中断"
                             "的根因）。建议本机 14B 跑给 900。不改 `config.json`（交件配置）")
    parser.add_argument("--all", dest="all_cases", action="store_true",
                        help="solo 用：跑全部六案（要和 panel 侧凑成同样的 18 个题级单元才有 A/B 分母，"
                             "默认只跑刘翔一案）")
    parser.add_argument("--submitted", action="store_true",
                        help="calib 用：金标对齐的对象改成**提交物 conclusions.json 每题那一行**"
                             "（达标行「消解后一致率」真正被评的东西），而不是 report.json 的内部结论集")
    parser.add_argument("--from", dest="from_dir", default=None,
                        help="calib 读取的 time 产物目录（默认最近一次）")
    args = parser.parse_args(argv)
    if args.timeout_seconds is not None:
        if int(args.timeout_seconds) <= 0:
            raise SystemExit(f"--timeout-seconds 必须为正整数，当前: {args.timeout_seconds}")
        global TIMEOUT_OVERRIDE
        TIMEOUT_OVERRIDE = int(args.timeout_seconds)
    if args.mode == "solo" and not args.case and not args.all_cases:
        args.case = "刘翔"
    OUT.mkdir(parents=True, exist_ok=True)
    return {"budget": cmd_budget, "time": cmd_time, "solo": cmd_solo,
            "calib": cmd_calib, "all": cmd_all}[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
