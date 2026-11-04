#!/usr/bin/env python3
"""C-148 探针：仲裁路由三腿（上下文片段在场／轻裁不叫模型／关旗与改前同形）。

用法（架构师独立复放）：
  python scripts/probe_c148_arb_face.py --stage arm --env off \
      --out /tmp/w148/off --base-tree /tmp/w148base
  python scripts/probe_c148_arb_face.py --stage all --base-tree /tmp/w148base

臂（--stage arm）：两个合成案全链路 run_case——
  案①真对立（客户B 极性对立对）：默认开臂＝LLM 仲裁提示词尾部拼程序侧
  上下文片段（分流判定／否决史／质证留痕）；案②误读（回款↔交付 议题维
  不相交）：默认开臂＝程序轻裁（tie 形态、零仲裁模型调用、双方保 majority）。
  零网络、零真实模型调用（ScriptedClient 脚本桩）。

all 腿：
  默认开臂 → 仲裁账本／路由／上下文／轻裁读数；路由＋轻裁单元腿；
  关旗臂 vs 基树臂（bf65d23）字节等证（归一化＋id 匿名化，链/进度/逐跑
  日志除外；两侧文件数都非空＝不做空比空）；
  pytest 整套（红不扩＝基线 7 红同名链）。
判定写 artifacts/C148_arb_face.{json,md}。
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

# ---- 合成案（与 tests/test_c148_arb_face.py 同夹具口径）--------------------

_OPP_MANIFEST = ("question: 客户B的回款情况如何？\n"
                 "sources:\n  - file: reb.md\n    type: news\n")
_OPP_SOURCE = "# 回款\n\n客户B的回款出现逾期，现金流承压，公司已启动催收。\n"
_MIS_MANIFEST = ("question: 客户B的经营情况如何？\n"
                 "sources:\n  - file: reb.md\n    type: news\n")
_MIS_SOURCE = ("# 经营\n\n客户B的回款出现逾期，公司已启动催收；"
               "交付进度符合合同约定。\n")
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
_PANEL_MISREAD_A = json.dumps({"conclusions": [{
    "statement": "客户B回款存在风险",
    "evidence": [{"quote": "客户B的回款出现逾期", "segment_id": "SRC1#s1",
                  "relation": "correlation", "level": "A",
                  "note": "直接引证"}]}]}, ensure_ascii=False)
_PANEL_MISREAD_B = json.dumps({"conclusions": [{
    "statement": "客户B交付进度符合预期",
    "evidence": [{"quote": "交付进度符合合同约定", "segment_id": "SRC1#s1",
                  "relation": "correlation", "level": "B",
                  "note": "直接引证"}]}]}, ensure_ascii=False)
_PANEL_EMPTY = '{"conclusions": []}'
_EDGES_EMPTY = '{"edges": []}'
_A1 = "对方证据等级存疑，未触及回款合同原件，主张不成立。"
_B1 = "对方未见付款凭证，逾期事实另有口径，应按合同原文核对。"
_A2 = "坚持原判：对方仅重申口径，未举出反证文件。"
_B2 = "补充口径：以催收记录为准，不能仅凭单方说法定性。"
_ARB_MARK = "程序证据强度对比"
_CTX_MARK = "仲裁上下文（程序侧，可复算"


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


def _two_misread_ids(text: str) -> tuple[str, str]:
    a = b = None
    for cid, stmt in re.findall(
            r"\[(CON-[0-9a-f]+)\]（[^）]*）([^\n]+)", text):
        if "回款" in stmt:
            a = cid
        elif "交付" in stmt:
            b = cid
    if not a or not b:
        raise RuntimeError("夹具自证失败：误读对认不出两条结论")
    return a, b


def _merge_opp(messages) -> str:
    pos, neg = _two_ids(messages[-1]["content"])
    return ('{"groups": [{"statement": "客户B存在回款风险", '
            '"member_ids": ["%s"]}, {"statement": "客户B不存在回款风险", '
            '"member_ids": ["%s"]}]}' % (pos, neg))


def _conflict_opp(messages) -> str:
    pos, neg = _two_ids(messages[-1]["content"])
    return ('{"conflicts": [{"a": "%s", "b": "%s", "topic": "回款风险", '
            '"description": "对回款状态判断对立"}]}' % (pos, neg))


def _merge_mis(messages) -> str:
    a, b = _two_misread_ids(messages[-1]["content"])
    return ('{"groups": [{"statement": "客户B回款存在风险", '
            '"member_ids": ["%s"]}, {"statement": "客户B交付进度符合预期", '
            '"member_ids": ["%s"]}]}' % (a, b))


def _conflict_mis(messages) -> str:
    a, b = _two_misread_ids(messages[-1]["content"])
    return ('{"conflicts": [{"a": "%s", "b": "%s", "topic": "经营", '
            '"description": "两个判断并陈"}]}' % (a, b))


def _arbitrate_resp(messages) -> str:
    a_id = re.search(r"\[(CON-[0-9a-f]+)\]",
                     messages[-1]["content"]).group(1)
    return '{"winner": "%s", "rationale": "甲方证据等级占优"}' % a_id


def _wipe_kgcache() -> None:
    import shutil
    import tempfile

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


def run_arm(out_dir: Path, *, arb_on: bool) -> dict:
    """两案全链路（脚本桩）；返回读数。

    每位分析师各自独立 client（panel 三线程并行抢共享队列＝跨进程不定）；
    协调段走独立共享 client（串行）。臂前清本树 .kgcache（embed 缓存按
    case_slug 落盘，暖/冷跨树读数不同形）。
    """
    import tempfile

    from app.agents.base import Analyst
    from app.agents.panel import DEFAULT_ROSTER
    from app.pipeline import RunDeps, RunSpec, run_case
    from tests.test_collab import ScriptedClient

    _wipe_kgcache()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 案①真对立：多轮质证（默认开）→ LLM 仲裁
    tmp1 = Path(tempfile.mkdtemp(prefix="c148_case_"))
    (tmp1 / "manifest.yaml").write_text(_OPP_MANIFEST, encoding="utf-8")
    (tmp1 / "reb.md").write_text(_OPP_SOURCE, encoding="utf-8")
    analysts1 = [
        Analyst(name, persona, ScriptedClient([resp]), "m")
        for (name, persona), resp in zip(
            DEFAULT_ROSTER, [_PANEL_POS, _PANEL_NEG, _PANEL_EMPTY])]
    script1 = [_merge_opp, _conflict_opp, _A1, _B1, _A2, _B2,
               _arbitrate_resp, _EDGES_EMPTY]
    client1 = ScriptedClient(list(script1))
    r1 = run_case(
        RunSpec(case_dir=tmp1, out_dir=out_dir / "opp", probe=False),
        RunDeps(client=client1, analysts=analysts1))
    ctx_in_prompt = any(
        _CTX_MARK in c["messages"][-1]["content"]
        for c in client1.calls
        if _ARB_MARK in c["messages"][-1]["content"])
    arb1 = (r1.dossier.accounting or {}).get("arbitration")
    opp_row: dict = {
        "chain_ok": bool(r1.chain.verify_chain().ok),
        "n_arbitrate_calls": sum(
            1 for c in client1.calls
            if _ARB_MARK in c["messages"][-1]["content"]),
        "context_in_prompt": ctx_in_prompt,
        "acc_arbitration_present": isinstance(arb1, dict),
        "n_llm": (arb1 or {}).get("n_llm"),
        "n_light": (arb1 or {}).get("n_light"),
    }
    if isinstance(arb1, dict) and arb1.get("pairs"):
        p0 = arb1["pairs"][0]
        opp_row.update({
            "route": p0.get("route"),
            "llm_called": p0.get("llm_called"),
            "context_included": p0.get("context_included"),
            "resolved": p0.get("resolved"),
            "winner_id": p0.get("winner_id"),
            "method": p0.get("method"),
        })

    # 案②误读（回款↔交付 议题维不相交）：单轮旧路 → 按旗轻裁或旧 LLM 仲裁
    tmp2 = Path(tempfile.mkdtemp(prefix="c148_case_"))
    (tmp2 / "manifest.yaml").write_text(_MIS_MANIFEST, encoding="utf-8")
    (tmp2 / "reb.md").write_text(_MIS_SOURCE, encoding="utf-8")
    analysts2 = [
        Analyst(name, persona, ScriptedClient([resp]), "m")
        for (name, persona), resp in zip(
            DEFAULT_ROSTER, [_PANEL_MISREAD_A, _PANEL_MISREAD_B,
                             _PANEL_EMPTY])]
    script2 = [_merge_mis, _conflict_mis, _A1, _B1]
    if not arb_on:
        script2 += [_arbitrate_resp]
    script2 += [_EDGES_EMPTY]
    client2 = ScriptedClient(list(script2))
    r2 = run_case(
        RunSpec(case_dir=tmp2, out_dir=out_dir / "mis", probe=False),
        RunDeps(client=client2, analysts=analysts2))
    arb2 = (r2.dossier.accounting or {}).get("arbitration")
    pair0 = (r2.dossier.conflicts or [{}])[0]
    res0 = (pair0.get("resolution") or {}) if pair0 else {}
    mis_row: dict = {
        "chain_ok": bool(r2.chain.verify_chain().ok),
        "n_arbitrate_calls": sum(
            1 for c in client2.calls
            if _ARB_MARK in c["messages"][-1]["content"]),
        "acc_arbitration_present": isinstance(arb2, dict),
        "n_light": (arb2 or {}).get("n_light"),
        "resolution_method": res0.get("method"),
        "resolution_winner": res0.get("winner_id"),
        "light_rationale": ("程序轻裁" in str(res0.get("rationale") or "")),
        "both_majority": all(
            (r2.dossier.conclusion(str(pair0.get(k)) or "") is not None
             and r2.dossier.conclusion(str(pair0.get(k)) or "").status
             == "majority")
            for k in ("a_id", "b_id") if pair0.get(k)),
    }
    if isinstance(arb2, dict) and arb2.get("pairs"):
        p0 = arb2["pairs"][0]
        mis_row.update({
            "route": p0.get("route"),
            "llm_called": p0.get("llm_called"),
            "context_included": p0.get("context_included"),
            "triage_class": p0.get("triage_class"),
        })
    return {"opp": opp_row, "mis": mis_row}


# ---- 归一化＋匿名化（字节臂）----------------------------------------------
# id 匿名不用首现序（uuid 逐跑随机、面板三线程汇入序跨臂不定＝首现序会把
# 映射带偏）：按**内容锚定**排序赋 ANON 名——CON 按结论 statement 排序、
# EV 按（引文＋所属结论角色）排序、CFL 按（议题＋冲突说明＋双方角色）排序。
# 误读案两条结论证据等级错开（A/B）＝去并列，headline 谁顶上不再吃调度噪声。

_NORM_KEYS = {"elapsed_s", "wall_s", "duration_s", "generated_at",
              "timestamp", "ts", "started_at", "finished_at"}
_SKIP_PARTS = ("chain.jsonl", "progress", ".log")
_RESIDUAL_RES = (re.compile(r"CON-[0-9a-f]{12}"),
                 re.compile(r"EV-[0-9a-f]{12}"),
                 re.compile(r"CFL-[0-9a-f]{10,12}"))
_RESIDUAL_SUB = ("CON-X", "EV-X", "CFL-X")
# 面板汇入序不定的稳定面列表：映射后按整项 JSON 排序吃掉调度噪声
_SORT_KEYS = ("conclusions", "evidences", "conflicts", "points",
              "open_issues", "pairs", "records", "blocked")


def _build_maps(obj: object) -> tuple[dict, dict, dict]:
    cons: dict[str, str] = {}
    if isinstance(obj, dict):
        for c in obj.get("conclusions") or []:
            if isinstance(c, dict) and c.get("id"):
                cons[str(c["id"])] = str(c.get("statement") or "")
    con_map = {i: f"CON-A{n:02d}" for n, (i, _s) in enumerate(
        sorted(cons.items(), key=lambda kv: (kv[1], kv[0])))}
    evs: dict[str, tuple[str, str]] = {}
    if isinstance(obj, dict):
        for e in obj.get("evidences") or []:
            if isinstance(e, dict) and e.get("id"):
                evs[str(e["id"])] = (
                    str(e.get("quote") or ""),
                    con_map.get(e.get("conclusion_id"), "?"))
    ev_map = {i: f"EV-A{n:02d}" for n, (i, _k) in enumerate(
        sorted(evs.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[0])))}
    cfls: dict[str, tuple] = {}
    if isinstance(obj, dict):
        for p in obj.get("conflicts") or []:
            if isinstance(p, dict) and p.get("id"):
                cfls[str(p["id"])] = (
                    str(p.get("topic") or ""), str(p.get("description") or ""),
                    con_map.get(p.get("a_id"), "?"),
                    con_map.get(p.get("b_id"), "?"))
    cfl_map = {i: f"CFL-A{n:02d}" for n, (i, _k) in enumerate(
        sorted(cfls.items(), key=lambda kv: (kv[1], kv[0])))}
    return con_map, ev_map, cfl_map


def _scrub_text(text: str) -> str:
    # 墙钟类读数（「耗时 0.2 秒」「本次研判：0.1 秒 · …」）逐跑漂移＝剥
    text = re.sub(r"[0-9]+(?:\.[0-9]+)? ?秒", "N 秒", text)
    text = re.sub(r"c148_case_[0-9a-z_]+", "c148_case_X", text)
    for rx, sub in zip(_RESIDUAL_RES, _RESIDUAL_SUB):
        text = rx.sub(sub, text)
    return text


def _map_key(k, maps):
    """字典键也可能是裸 uuid（basis／evidence_weight 按 CON-id 建 dict）——
    键级走同一套映射＋残差折叠。"""
    con_map, ev_map, cfl_map = maps
    if not isinstance(k, str):
        return k
    nk = k
    for m in (con_map, ev_map, cfl_map):
        for kk, vv in m.items():
            if kk in nk:
                nk = nk.replace(kk, vv)
    for rx, sub in zip(_RESIDUAL_RES, _RESIDUAL_SUB):
        nk = rx.sub(sub, nk)
    return nk


def _norm(obj, maps=None):
    con_map, ev_map, cfl_map = maps or ({}, {}, {})
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _NORM_KEYS:
                continue
            out[_map_key(k, maps or ({}, {}, {}))] = _norm(v, maps)
        for key in _SORT_KEYS:
            if key in out and isinstance(out[key], list):
                out[key] = sorted(
                    out[key],
                    key=lambda x: json.dumps(x, ensure_ascii=False,
                                             sort_keys=True))
        return out
    if isinstance(obj, list):
        return [_norm(v, maps) for v in obj]
    if isinstance(obj, str):
        s = obj
        for m in (con_map, ev_map, cfl_map):
            for k, v in m.items():
                if k in s:
                    s = s.replace(k, v)
        return _scrub_text(s)
    return obj


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
                obj = json.loads(text)
                maps = _build_maps(obj)
                text = json.dumps(_norm(obj, maps),
                                  ensure_ascii=False, sort_keys=True)
            else:
                text = _scrub_text(text)
            out[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        except UnicodeDecodeError:
            out[rel] = hashlib.sha256(raw).hexdigest()
    return out


# ---- 单元腿 ---------------------------------------------------------------

def leg_route_and_light() -> dict:
    from app.core.arbitration_face import (
        ROUTE_LIGHT, ROUTE_LLM, arb_route, arbitrate_light, build_context,
        merge_veto_face,
    )
    from app.core.conflicts import ConflictPair, apply_resolution
    from app.core.evidence import (
        Conclusion, Dossier, EvidenceNode, Segment, Source, SourceType,
    )

    d = Dossier(question="客户B的经营情况如何？")
    src = Source.create("经营纪要", SourceType.NEWS, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1",
        text="客户B的回款出现逾期，公司已启动催收；交付进度符合合同约定。",
        index=0))
    d.sources.append(src)
    ca = Conclusion.create("客户B回款存在风险", author="a0")
    cb = Conclusion.create("客户B交付进度符合预期", author="a1")
    d.conclusions.extend([ca, cb])
    d.add_evidence(EvidenceNode.create(
        ca.id, "客户B的回款出现逾期", ["SRC1#s1"]))
    d.add_evidence(EvidenceNode.create(
        cb.id, "交付进度符合合同约定", ["SRC1#s1"]))
    mis = ConflictPair(a_id=ca.id, b_id=cb.id, topic="经营")

    pos = Conclusion.create("客户B存在回款风险", author="a2")
    neg = Conclusion.create("客户B不存在回款风险", author="a3")
    d.conclusions.extend([pos, neg])
    d.add_evidence(EvidenceNode.create(
        pos.id, "客户B的回款出现逾期", ["SRC1#s1"]))
    d.add_evidence(EvidenceNode.create(
        neg.id, "客户B的回款出现逾期", ["SRC1#s1"]))
    opp = ConflictPair(a_id=pos.id, b_id=neg.id, topic="回款")

    r_mis = arb_route(mis, d)
    r_opp = arb_route(opp, d)
    res = arbitrate_light(mis, d, {"a": "甲质证", "b": "乙质证"}, r_mis)
    mis.resolution = res
    apply_ok = apply_resolution(mis, d) is None
    both_majority = all(
        d.conclusion(cid).status == "majority"
        for cid in (mis.a_id, mis.b_id))
    d.accounting = {"merge_gate": {"blocked": [{
        "id": "MERGE-0001", "member_ids": [mis.a_id, mis.b_id],
        "fail_legs": ["polarity_opposed"]}]}}
    veto = merge_veto_face(d, [mis.a_id, mis.b_id])
    ctx = build_context(mis, d, r_mis, veto=veto)
    return {
        "misread_routes_light": bool(
            r_mis["route"] == ROUTE_LIGHT
            and r_mis["triage_class"] == "oral_misread"),
        "true_oppose_routes_llm": bool(
            r_opp["route"] == ROUTE_LLM
            and r_opp["triage_class"] == "true_oppose"),
        "light_is_tie_no_false_inequality": bool(
            res.winner_id == "tie" and res.method == "tie"
            and res.decision_path == "tie"
            and "程序轻裁" in res.rationale
            and "≤" not in str(res.basis.get("type_applies"))),
        "light_keeps_both_majority": bool(apply_ok and both_majority),
        "veto_face_hits": bool(veto and veto[0]["group_id"] == "MERGE-0001"),
        "context_carries_faces": bool(
            "oral_misread" in ctx and "MERGE-0001" in ctx
            and "归并闸否决史" in ctx),
    }


# ---- 阶段 -----------------------------------------------------------------

def stage_arm(out_dir: Path, arb_on: bool) -> int:
    row = run_arm(out_dir, arb_on=arb_on)
    print(json.dumps(row, ensure_ascii=False))
    (out_dir / "_arm_row.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _run_arm_sub(tree: Path, out: Path, arb_on: bool) -> dict:
    cmd = [str(tree / ".venv" / "bin" / "python"),
           "scripts/probe_c148_arb_face.py", "--stage", "arm",
           "--out", str(out)]
    env = dict(os.environ)
    env.pop("VERITAS_ARB_CONTEXT", None)
    if not arb_on:
        env["VERITAS_ARB_CONTEXT"] = "0"
    r = subprocess.run(cmd, cwd=tree, env=env, capture_output=True,
                       text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"arm 失败（arb_on={arb_on}）：{r.stderr[-800:]}")
    return json.loads((out / "_arm_row.json").read_text(encoding="utf-8"))


def _leg_pytest() -> str:
    r = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "pytest", "tests", "-q"],
        cwd=ROOT, capture_output=True, text=True, timeout=600)
    tail = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    return tail


def stage_all(base_tree: Path) -> int:
    import shutil

    out_root = ROOT / "artifacts" / "c148_arms"
    if out_root.exists():
        shutil.rmtree(out_root)
    row_on = _run_arm_sub(ROOT, out_root / "on", arb_on=True)
    row_off = _run_arm_sub(ROOT, out_root / "off", arb_on=False)
    if not base_tree.exists():
        raise RuntimeError(f"基树不存在：{base_tree}")
    row_base = _run_arm_sub(base_tree, out_root / "base", arb_on=False)

    legs = leg_route_and_light()

    hashes_off = _file_hashes(out_root / "off")
    hashes_base = _file_hashes(out_root / "base")
    both_nonempty = bool(hashes_off) and bool(hashes_base)
    keys = set(hashes_off) | set(hashes_base)
    diff_files = sorted(k for k in keys
                        if hashes_off.get(k) != hashes_base.get(k))
    same_keyset = set(hashes_off) == set(hashes_base)

    pytest_tail = _leg_pytest()

    gates = {
        "g1_默认开仲裁留痕在场": bool(
            row_on["opp"].get("acc_arbitration_present")
            and row_on["opp"].get("route") == "llm_enriched"
            and row_on["opp"].get("n_llm") == 1
            and row_on["mis"].get("acc_arbitration_present")
            and row_on["mis"].get("route") == "light_program"
            and row_on["mis"].get("n_light") == 1),
        "g2_轻裁不叫模型_双方保位": bool(
            row_on["mis"].get("n_arbitrate_calls") == 0
            and row_on["mis"].get("resolution_method") == "tie"
            and row_on["mis"].get("resolution_winner") == "tie"
            and row_on["mis"].get("light_rationale")
            and row_on["mis"].get("both_majority")
            and row_on["mis"].get("chain_ok")),
        "g3_上下文片段在场": bool(
            row_on["opp"].get("context_in_prompt")
            and row_on["opp"].get("context_included")
            and row_on["opp"].get("llm_called")
            and row_on["opp"].get("n_arbitrate_calls") == 1
            and row_on["opp"].get("chain_ok")),
        "g4_路由与轻裁单元腿": bool(all(legs.values())),
        "g5_关旗与改前同形": bool(
            both_nonempty and same_keyset and not diff_files),
        "g6_pytest红不扩": bool(
            f"{BASELINE_FAILED} failed" in pytest_tail),
    }

    delta = {
        "on": row_on, "off": row_off, "base": row_base,
        "off_vs_base": {"files_compared": len(keys),
                        "diff_files": diff_files,
                        "both_nonempty": both_nonempty,
                        "same_keyset": same_keyset},
        "route_and_light_legs": legs,
        "pytest_tail": pytest_tail,
    }
    verdict = "YES" if all(gates.values()) else "NO"

    payload = {"ticket": "C-148", "verdict": verdict,
               "base_tip": "bf65d23", "gates": gates, "delta": delta}
    art_json = ROOT / "artifacts" / "C148_arb_face.json"
    art_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    lines = [
        "# C-148 仲裁路由＋轻裁——判定与读数（探针现抄）", "",
        f"判定：{verdict}", "",
        "## 闸（全 True 才 YES）", ""]
    for k, v in gates.items():
        lines.append(f"- {k}＝{v}")
    lines += ["", "## delta", "",
              f"- 默认开臂·真对立案：route＝{row_on['opp'].get('route')}、"
              f"llm_called＝{row_on['opp'].get('llm_called')}、"
              f"context_included＝{row_on['opp'].get('context_included')}、"
              f"提示词含程序侧片段＝{row_on['opp'].get('context_in_prompt')}、"
              f"仲裁调用 {row_on['opp'].get('n_arbitrate_calls')} 次、"
              f"链校验＝{row_on['opp'].get('chain_ok')}",
              f"- 默认开臂·误读案：route＝{row_on['mis'].get('route')}、"
              f"仲裁调用 {row_on['mis'].get('n_arbitrate_calls')} 次、"
              f"终局 {row_on['mis'].get('resolution_method')}／"
              f"{row_on['mis'].get('resolution_winner')}、"
              f"轻裁理由在场＝{row_on['mis'].get('light_rationale')}、"
              f"双方保 majority＝{row_on['mis'].get('both_majority')}",
              f"- 关旗臂：两案 accounting 键在场＝"
              f"{row_off['opp'].get('acc_arbitration_present')}／"
              f"{row_off['mis'].get('acc_arbitration_present')}"
              f"（均应 False）、误读案仲裁调用 "
              f"{row_off['mis'].get('n_arbitrate_calls')} 次（旧路照走）",
              f"- 基树臂（bf65d23 同码缺省）：两案链校验＝"
              f"{row_base['opp'].get('chain_ok')}／"
              f"{row_base['mis'].get('chain_ok')}",
              f"- 关旗 vs 基树：比较文件 {len(keys)} 个、"
              f"差异文件 {len(diff_files)} 个（{'、'.join(diff_files) or '无'}）"
              f"、两侧非空＝{both_nonempty}、键集一致＝{same_keyset}",
              f"- 路由与轻裁腿：{json.dumps(legs, ensure_ascii=False)}",
              f"- pytest：{pytest_tail}", "",
              "## 口径披露", "",
              "- 两案合成夹具（真对立对＋误读对＋第三位空交付分析师），"
              "零网络零真实模型调用；ScriptedClient 脚本桩；误读对两侧证据"
              "等级错开（A/B）＝去并列，置信度并列不再吃线程调度噪声。",
              "- 字节臂 id 匿名按**内容锚定**：CON 按 statement、EV 按"
              "（引文＋结论角色）、CFL 按（议题＋说明＋双方角色）排序赋 "
              "ANON 名——uuid 逐跑随机、面板三线程汇入序跨臂不定，首现序"
              "映射会被带偏；稳定面列表（conclusions／evidences／conflicts／"
              "synthesis／账本 pairs 等）映射后整项排序。文本面残留 id 折叠"
              "为 CON-X／EV-X／CFL-X（胜方翻面由 report.json 精确面看守）。",
              "- 归一化只剥 elapsed／时戳类键与墙钟秒数；chain.jsonl／"
              "progress／逐跑日志不入比较面。",
              "- 关旗同形臂两侧文件数均非空（不做空比空）。", ""]
    (ROOT / "artifacts" / "C148_arb_face.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print("判定", verdict, "闸", json.dumps(gates, ensure_ascii=False))
    print("pytest", pytest_tail)
    return 0 if verdict == "YES" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["arm", "all"], required=True)
    ap.add_argument("--env", choices=["on", "off"], default="on")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts" / "c148_arm")
    ap.add_argument("--base-tree", type=Path,
                    default=Path("/tmp/w148base"))
    args = ap.parse_args()
    if args.stage == "arm":
        return stage_arm(args.out, arb_on=(args.env == "on"))
    return stage_all(args.base_tree)


if __name__ == "__main__":
    sys.exit(main())
