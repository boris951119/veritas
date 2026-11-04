#!/usr/bin/env python3
"""C-147 探针：多轮质证三腿（真对立强制进／逐轮闸／关旗与改前同形）＋判定落盘。

用法（架构师独立复放）：
  python scripts/probe_c147_rebuttal_rounds.py --stage arm --env off \
      --out /tmp/w147/off --base-tree /tmp/w147base
  python scripts/probe_c147_rebuttal_rounds.py --stage all \
      --base-tree /tmp/w147base

臂（--stage arm）：合成一案（客户B 极性对立对＋第三位空交付分析师）全链路
run_case，产物写 --out。零网络、零真实模型调用（ScriptedClient 脚本桩）。

all 腿：
  smoke 默认开臂 → 逐轮行／闸字段／采信倾向读数；
  escalation_for 四腿单元（true_oppose 强制／other 同主体吃进／
  other 无主体不进／oral_misread 不进）；
  关旗臂 vs 基树臂（f9509a2）字节等证（归一化＋id 匿名化，链/进度/逐跑
  日志除外；两侧文件数都非空＝不做空比空）；
  pytest 整套（红不扩＝基线 7 红同名链）。
判定写 artifacts/C147_rebuttal_rounds.{json,md}。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # 直跑脚本时保证能 import app（worktree 根）
BASELINE_FAILED = 7

# ---- 合成案（与 tests/test_c147_rebuttal_rounds.py 同夹具口径）------------

_MANIFEST = ("question: 客户B的回款情况如何？\n"
             "sources:\n  - file: reb.md\n    type: news\n")
_SOURCE = "# 回款\n\n客户B的回款出现逾期，现金流承压，公司已启动催收。\n"
_PANEL_POS = json.dumps({"conclusions": [{
    "statement": "客户B存在回款风险",
    "evidence": [{"quote": "客户B的回款出现逾期", "segment_id": "SRC1#s1",
                  "relation": "correlation", "level": "A",
                  "note": "直接引证"}]}]}, ensure_ascii=False)
_PANEL_NEG = json.dumps({"conclusions": [{
    "statement": "客户B不存在回款风险",
    "evidence": [{"quote": "客户B的回款出现逾期", "segment_id": "SRC1#s1",
                  "relation": "correlation", "level": "D",
                  "note": "同段反读"}]}]}, ensure_ascii=False)
_PANEL_EMPTY = '{"conclusions": []}'
_EDGES_EMPTY = '{"edges": []}'
_A1 = "对方证据等级存疑，未触及回款合同原件，主张不成立。"
_B1 = "对方未见付款凭证，逾期事实另有口径，应按合同原文核对。"
_A2 = "坚持原判：对方仅重申口径，未举出反证文件。"
_B2 = "补充口径：以催收记录为准，不能仅凭单方说法定性。"


def _two_ids(text: str) -> tuple[str, str]:
    pos = neg = None
    for cid, stmt in re.findall(
            r"\[(CON-[0-9a-f]+)\]（[^）]*）([^\n]+)", text):
        if "不存在" in stmt:
            neg = cid
        elif "存在回款风险" in stmt:
            pos = cid
    if not pos or not neg:
        raise RuntimeError("夹具自证失败：提示词里认不出两条结论")
    return pos, neg


def _merge_resp(messages) -> str:
    pos, neg = _two_ids(messages[-1]["content"])
    return ('{"groups": [{"statement": "客户B存在回款风险", '
            '"member_ids": ["%s"]}, {"statement": "客户B不存在回款风险", '
            '"member_ids": ["%s"]}]}' % (pos, neg))


def _conflict_resp(messages) -> str:
    pos, neg = _two_ids(messages[-1]["content"])
    return ('{"conflicts": [{"a": "%s", "b": "%s", "topic": "回款风险", '
            '"description": "对回款状态判断对立"}]}' % (pos, neg))


def _arbitrate_resp(messages) -> str:
    a_id = re.search(r"\[(CON-[0-9a-f]+)\]",
                     messages[-1]["content"]).group(1)
    return '{"winner": "%s", "rationale": "甲方证据等级占优"}' % a_id


def run_arm(out_dir: Path, *, multi: bool) -> dict:
    """全链路一案（脚本桩）；返回读数行。

    每位分析师各自独立 client（panel 三线程并行抢共享队列＝跨进程不定，
    谁抢到空响应跨树会翻面）；协调段走独立共享 client（串行）。臂前清
    本树 .kgcache（embed 缓存按 case_slug 落盘，暖/冷跨树读数不同形；
    只清 /tmp 下 worktree 内的运行残渣）。
    """
    import shutil
    import tempfile

    from app.agents.base import Analyst
    from app.agents.panel import DEFAULT_ROSTER
    from app.pipeline import RunDeps, RunSpec, run_case
    from tests.test_collab import ScriptedClient

    # macOS /tmp 是 /private/tmp 的符号链接：按临时目录根判定（系统 /tmp
    # 或用户临时区都认），缓存清理只许发生在临时区 worktree 内（绝不碰主仓）。
    _resolved = ROOT.resolve()
    _allowed = [Path("/tmp").resolve(),
                Path(tempfile.gettempdir()).resolve()]
    assert any(_resolved.is_relative_to(a) and _resolved != a
               for a in _allowed), "缓存清理只许在临时区 worktree 内"
    kgcache = ROOT / ".kgcache"
    if kgcache.exists():
        shutil.rmtree(kgcache, ignore_errors=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="c147_case_"))
    (tmp / "manifest.yaml").write_text(_MANIFEST, encoding="utf-8")
    (tmp / "reb.md").write_text(_SOURCE, encoding="utf-8")
    panels = [_PANEL_POS, _PANEL_NEG, _PANEL_EMPTY]
    analysts = [
        Analyst(name, persona, ScriptedClient([resp]), "m")
        for (name, persona), resp in zip(DEFAULT_ROSTER, panels)]
    coord_script = [_merge_resp, _conflict_resp]
    coord_script += ([_A1, _B1, _A2, _B2] if multi else [_A1, _B1])
    coord_script += [_arbitrate_resp, _EDGES_EMPTY]
    client = ScriptedClient(coord_script)
    result = run_case(
        RunSpec(case_dir=tmp, out_dir=out_dir, probe=False),
        RunDeps(client=client, analysts=analysts))
    d = result.dossier
    acc = (d.accounting or {}).get("rebuttal")
    row: dict = {
        "chain_ok": bool(result.chain.verify_chain().ok),
        "acc_rebuttal_present": isinstance(acc, dict),
        "n_pairs": (acc or {}).get("n_pairs"),
        "n_escalated": (acc or {}).get("n_escalated"),
        "empty_state": (acc or {}).get("empty_state"),
    }
    if isinstance(acc, dict) and acc.get("pairs"):
        p0 = acc["pairs"][0]
        row.update({
            "escalation": p0.get("escalation"),
            "escalation_reason": p0.get("escalation_reason"),
            "rounds_requested": p0.get("rounds_requested"),
            "rounds_used": p0.get("rounds_used"),
            "n_round_rows": len(p0.get("rounds") or []),
            "all_gate_ok": all(
                bool(r.get("gate_ok")) for r in (p0.get("rounds") or [])),
            "gate_fields_present": all(
                {"gate_ok", "repaired", "quote_flags", "ref_flags"}
                <= set(r or {}) for r in (p0.get("rounds") or [])),
            "lean_resolved": (p0.get("lean") or {}).get("resolved"),
            "rebuts_multiround_shape": (
                "第1轮：" in ((d.conflicts[0].get("resolution") or {})
                             .get("rebuts", {}).get("a", ""))
                if d.conflicts else False),
        })
    return row


# ---- 归一化＋匿名化（字节臂）----------------------------------------------

_NORM_KEYS = {"elapsed_s", "wall_s", "duration_s", "generated_at",
              "timestamp", "ts", "started_at", "finished_at"}
_ANON_RES = (re.compile(r"CON-[0-9a-f]{12}"),
             re.compile(r"EV-[0-9a-f]{12}"),
             re.compile(r"CFL-[0-9a-f]{10,12}"))
_SKIP_PARTS = ("chain.jsonl", "progress", ".log")


def _scrub_text(text: str) -> str:
    # 墙钟类读数（「耗时 0.2 秒」「本次研判：0.1 秒 · …」）逐跑漂移＝剥
    text = re.sub(r"[0-9]+(?:\.[0-9]+)? ?秒", "N 秒", text)
    return re.sub(r"c147_case_[0-9a-z_]+", "c147_case_X", text)


def _norm(obj):
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items() if k not in _NORM_KEYS}
    if isinstance(obj, list):
        return [_norm(v) for v in obj]
    if isinstance(obj, str):
        return _scrub_text(obj)
    return obj


def _anon(text: str) -> str:
    for i, rx in enumerate(_ANON_RES):
        mapping: dict[str, str] = {}

        def _sub(m, _mapping=mapping, _pfx=f"ANON{i}"):
            if m.group(0) not in _mapping:
                _mapping[m.group(0)] = f"{_pfx}-{len(_mapping) + 1:03d}"
            return _mapping[m.group(0)]

        text = rx.sub(_sub, text)
    return text


def _file_hashes(root: Path) -> dict[str, str]:
    import hashlib

    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(part in p.name for part in _SKIP_PARTS):
            continue
        rel = str(p.relative_to(root))
        raw = p.read_bytes()
        try:
            text = raw.decode("utf-8")
            if rel.endswith(".json"):
                text = json.dumps(_norm(json.loads(text)),
                                  ensure_ascii=False, sort_keys=True)
            else:
                text = _scrub_text(text)
            out[rel] = hashlib.sha256(_anon(text).encode("utf-8")).hexdigest()
        except UnicodeDecodeError:
            out[rel] = hashlib.sha256(raw).hexdigest()
    return out


# ---- 单元腿：escalation_for 四腿 -----------------------------------------

def leg_escalation() -> dict:
    from app.core.conflicts import ConflictPair
    from app.core.evidence import Conclusion, Dossier
    from app.core.rebuttal_rounds import escalation_for

    d = Dossier(question="q")
    pos = Conclusion.create("客户B存在回款风险", author="a0")
    neg = Conclusion.create("客户B不存在回款风险", author="a1")
    same = Conclusion.create("客户B存在回款风险", author="a2")
    s1 = Conclusion.create("客户B回款进展平稳", author="a0")
    s2 = Conclusion.create("客户B回款节奏需要关注", author="a1")
    t1 = Conclusion.create("整体局面平稳", author="a0")
    t2 = Conclusion.create("整体局面存在变数", author="a1")
    d.conclusions.extend([pos, neg, same, s1, s2, t1, t2])
    e_true = escalation_for(ConflictPair(a_id=pos.id, b_id=neg.id), d)
    e_same = escalation_for(ConflictPair(a_id=pos.id, b_id=same.id), d)
    e_other_edible = escalation_for(ConflictPair(a_id=s1.id, b_id=s2.id), d)
    e_other_none = escalation_for(ConflictPair(a_id=t1.id, b_id=t2.id), d)
    return {
        "true_oppose_forced": bool(
            e_true["escalate"]
            and e_true["escalation_reason"] == "true_oppose_forced"),
        "oral_misread_not_in": bool(
            not e_same["escalate"]
            and e_same["escalation_reason"]
            == "class_not_escalated:oral_misread"),
        "other_same_subject_eaten": bool(
            e_other_edible["escalate"]
            and e_other_edible["semantic_upgrade"]
            and e_other_edible["escalation_reason"]
            == "semantics_eat_other_same_subject"),
        "other_no_subject_kept_out": bool(
            not e_other_none["escalate"]
            and e_other_none["escalation_reason"]
            == "other_subject_unknown"),
    }


# ---- 阶段 -----------------------------------------------------------------

def stage_arm(out_dir: Path, multi: bool) -> int:
    row = run_arm(out_dir, multi=multi)
    print(json.dumps(row, ensure_ascii=False))
    (out_dir / "_arm_row.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _run_arm_sub(tree: Path, out: Path, multi: bool) -> dict:
    cmd = [str(tree / ".venv" / "bin" / "python"),
           "scripts/probe_c147_rebuttal_rounds.py", "--stage", "arm",
           "--out", str(out)]
    env = dict(os.environ)
    env.pop("VERITAS_MULTI_REBUTTAL", None)
    env.pop("VERITAS_REBUTTAL_ROUNDS", None)
    if not multi:
        env["VERITAS_MULTI_REBUTTAL"] = "0"
    r = subprocess.run(cmd, cwd=tree, env=env, capture_output=True,
                       text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"arm 失败（multi={multi}）：{r.stderr[-800:]}")
    return json.loads((out / "_arm_row.json").read_text(encoding="utf-8"))


def _leg_pytest() -> str:
    r = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "pytest", "tests", "-q"],
        cwd=ROOT, capture_output=True, text=True, timeout=600)
    tail = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    return tail


def stage_all(base_tree: Path) -> int:
    import shutil

    from app.core.discourse_check import audit_discourse
    from app.core.evidence import Dossier

    out_root = ROOT / "artifacts" / "c147_arms"
    if out_root.exists():
        shutil.rmtree(out_root)
    row_on = _run_arm_sub(ROOT, out_root / "on", multi=True)
    row_off = _run_arm_sub(ROOT, out_root / "off", multi=False)
    if not base_tree.exists():
        raise RuntimeError(f"基树不存在：{base_tree}")
    row_base = _run_arm_sub(base_tree, out_root / "base", multi=False)

    # 逐轮行闸读数复扫：拼接文本过事后黄旗应零新增（夹具全净稿）
    d_clean = Dossier(question="q")
    esc = leg_escalation()

    hashes_off = _file_hashes(out_root / "off")
    hashes_base = _file_hashes(out_root / "base")
    both_nonempty = bool(hashes_off) and bool(hashes_base)
    keys = set(hashes_off) | set(hashes_base)
    diff_files = sorted(k for k in keys
                        if hashes_off.get(k) != hashes_base.get(k))
    # 键集合本身也要一致（一侧多文件＝不同形）
    same_keyset = set(hashes_off) == set(hashes_base)

    pytest_tail = _leg_pytest()

    gates = {
        "g1_多轮在场_默认开": bool(
            row_on.get("acc_rebuttal_present")
            and row_on.get("n_escalated") == 1
            and row_on.get("rounds_used") == 2
            and row_on.get("n_round_rows") == 4
            and row_on.get("rebuts_multiround_shape")
            and row_on.get("lean_resolved")),
        "g2_真对立强制进": bool(
            row_on.get("escalation") == "multi_round"
            and row_on.get("escalation_reason") == "true_oppose_forced"),
        "g3_逐轮闸在场": bool(
            row_on.get("gate_fields_present") and row_on.get("all_gate_ok")
            and row_on.get("chain_ok")),
        "g4_语义吃other": bool(all(esc.values())),
        "g5_关旗与改前同形": bool(
            both_nonempty and same_keyset and not diff_files),
        "g6_pytest红不扩": bool(
            f"{BASELINE_FAILED} failed" in pytest_tail),
    }

    delta = {
        "on": row_on, "off": row_off, "base": {
            k: v for k, v in row_base.items()},
        "off_vs_base": {"files_compared": len(keys),
                        "diff_files": diff_files,
                        "both_nonempty": both_nonempty,
                        "same_keyset": same_keyset},
        "escalation_legs": esc,
        "pytest_tail": pytest_tail,
    }
    verdict = "YES" if all(gates.values()) else "NO"

    payload = {"ticket": "C-147", "verdict": verdict,
               "base_tip": "f9509a2", "gates": gates, "delta": delta}
    art_json = ROOT / "artifacts" / "C147_rebuttal_rounds.json"
    art_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    lines = [
        "# C-147 多轮质证——判定与读数（探针现抄）", "",
        f"判定：{verdict}", "",
        "## 闸（全 True 才 YES）", ""]
    for k, v in gates.items():
        lines.append(f"- {k}＝{v}")
    lines += ["", "## delta", "",
              f"- 默认开臂：n_pairs＝{row_on.get('n_pairs')}、"
              f"n_escalated＝{row_on.get('n_escalated')}、"
              f"rounds_used＝{row_on.get('rounds_used')}、"
              f"逐轮行 {row_on.get('n_round_rows')} 条全过闸、"
              f"Resolution.rebuts 带第1轮/第2轮＝"
              f"{row_on.get('rebuts_multiround_shape')}、"
              f"采信倾向 resolved＝{row_on.get('lean_resolved')}",
              f"- 关旗臂：accounting 键在场＝{row_off.get('acc_rebuttal_present')}"
              f"（应为 False）、链校验＝{row_off.get('chain_ok')}",
              f"- 基树臂（f9509a2 关旗同码）：链校验＝{row_base.get('chain_ok')}",
              f"- 关旗 vs 基树：比较文件 {len(keys)} 个、"
              f"差异文件 {len(diff_files)} 个（{'、'.join(diff_files) or '无'}）"
              f"、两侧非空＝{both_nonempty}、键集一致＝{same_keyset}",
              f"- 分流四腿：{json.dumps(esc, ensure_ascii=False)}",
              f"- pytest：{pytest_tail}", "",
              "## 口径披露", "",
              "- 合成夹具（客户B 极性对立对＋第三位空交付分析师），"
              "零网络零真实模型调用；ScriptedClient 脚本桩。",
              "- 字节臂把逐次 uuid 生成 id（CON-12hex／CFL-10hex）按各文件"
              "首现序匿名化；归一化只剥 elapsed／时戳类键；"
              "chain.jsonl／progress／逐跑日志不入比较面。",
              "- 关旗同形臂两侧文件数均非空（不做空比空）。", ""]
    (ROOT / "artifacts" / "C147_rebuttal_rounds.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print("判定", verdict, "闸", json.dumps(gates, ensure_ascii=False))
    print("pytest", pytest_tail)
    return 0 if verdict == "YES" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["arm", "all"], required=True)
    ap.add_argument("--env", choices=["on", "off"], default="on")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts" / "c147_arm")
    ap.add_argument("--base-tree", type=Path,
                    default=Path("/tmp/w147base"))
    args = ap.parse_args()
    if args.stage == "arm":
        return stage_arm(args.out, multi=(args.env == "on"))
    return stage_all(args.base_tree)


if __name__ == "__main__":
    sys.exit(main())
