"""C-145a 探针：VERITAS_CONFLICT_TRACE 出厂默认开——同形等证＋冒烟＋旁证。

腿A 出口面（零 LLM・对撞夹具・三旗态）：
  arm_default  未设 env（出厂默认）→ 期望＝回放面写出＋处置行
  arm_on       env=1  → 期望＝与改前旗开臂字节同形
  arm_off      env=0  → 期望＝与改前关旗臂字节同形（关旗回退）
腿B demo 冒烟（未设 env・零 LLM 全路径 cases/demo-solid-state）：
  期望＝conflict_trace.json 在场（空态也写＋真实题数句）；env=0 不在场
腿C 门控复刻（零 LLM・C-134 同尺・两旗臂）＝默认翻转不碰装箱的保险腿。

用法：
  .venv/bin/python -m scripts.probe_c145a_default_on --stage export --tag branch --out /tmp/c145a/export_branch.json
  .venv/bin/python -m scripts.probe_c145a_default_on --stage export --tag base   --out /tmp/c145a/export_base.json
  .venv/bin/python -m scripts.probe_c145a_default_on --stage assemble \
      --base /tmp/c145a/export_base.json --branch /tmp/c145a/export_branch.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ART = ROOT / "artifacts"
OUT = Path("/tmp/c145a")


def _face_hashes(arm: dict) -> dict[str, str]:
    """等证面＝交卷 official 六件＋report 两件（剥时戳后）。

    conflict_trace.json 由 _hash_tree 统一按 sort_keys 规范化：
    summarize_trace 的 by_class／by_disposition 桶序来自 set 迭代
    （随进程哈希种子浮动、值恒同），字节面比较的是内容不是键序。
    """
    return {k: v for k, v in arm["file_hashes"].items()
            if not k.startswith(("chain.jsonl", "progress.json"))}


def _demo_arm(tag: str, flag: str | None) -> dict[str, Any]:
    """demo 冒烟：cases/demo-solid-state 零 LLM 全路径＋export。"""
    from app.export.official import export_official
    from app.pipeline import RunDeps, RunSpec, run_case
    from scripts.probe_c143_trace_face import _Stub

    if flag is None:
        os.environ.pop("VERITAS_CONFLICT_TRACE", None)
    else:
        os.environ["VERITAS_CONFLICT_TRACE"] = flag
    tmp = Path(tempfile.mkdtemp(prefix=f"c145a_{tag}_"))
    out = tmp / "out"
    deps = RunDeps(client=_Stub(), analysts=[])
    r = run_case(
        RunSpec(case_dir=ROOT / "cases" / "demo-solid-state",
                out_dir=out, probe=False),
        deps)
    official = out / "official"
    export_official(
        [({"question_id": "q_demo", "question": r.dossier.question},
          r.dossier)],
        official)
    tf = official / "conflict_trace.json"
    payload: dict[str, Any] = {}
    if tf.exists():
        payload = json.loads(tf.read_text(encoding="utf-8"))
    row = {
        "tag": tag, "flag": str(flag),
        "trace_file": tf.exists(),
        "summary_n": (payload.get("summary") or {}).get("n"),
        "empty_state": payload.get("empty_state"),
        "detail_present": bool(payload.get("detail")),
        "detail_has_real_count": ("题" in str(payload.get("detail") or "")
                                  and "1 题" in str(payload.get("detail") or ""))
        if payload.get("empty_state") else None,
    }
    print(f"[腿B {tag}] 旗={flag} 文件={row['trace_file']} "
          f"n={row['summary_n']} 空态={row['empty_state']}", flush=True)
    return row


def leg_export(tag: str) -> dict[str, Any]:
    from scripts.probe_c143_trace_face import (
        _export_arm, _flag_default_now,
    )

    arms = {
        "arm_default": _export_arm(f"{tag}_def", None, ["40%", "60%"]),
        "arm_on": _export_arm(f"{tag}_on", "1", ["40%", "60%"]),
        "arm_off": _export_arm(f"{tag}_off", "0", ["40%", "60%"]),
    }
    demo = {
        "demo_default": _demo_arm(f"{tag}_def", None),
        "demo_off": _demo_arm(f"{tag}_off", "0"),
    }
    replica = {
        "off": _replica_arm_safe("0"),
        "on": _replica_arm_safe("1"),
    }
    return {"tag": tag, "arms": arms, "demo": demo, "replica": replica,
            "flag_default_now": _flag_default_now()}


def _replica_arm_safe(flag: str) -> dict[str, Any]:
    from scripts.probe_c143_trace_face import _replica_arm

    return _replica_arm(flag)


# ------------------------------------------------ 判表＋artifact


def _cmp(base: dict, branch: dict) -> dict[str, Any]:
    ab, as_ = branch["arms"], base["arms"]
    off_eq = (_face_hashes(ab["arm_off"]) == _face_hashes(as_["arm_off"]))
    on_eq = (_face_hashes(ab["arm_on"]) == _face_hashes(as_["arm_on"]))
    base_default_off = (not as_["arm_default"]["trace_file"])
    br_default_on = (ab["arm_default"]["trace_file"]
                     and ab["arm_default"]["acc_key_live"]
                     and (ab["arm_default"]["summary_n"] or 0) >= 1
                     and bool(ab["arm_default"]["row0_disposition"]))
    db, ds = branch["demo"], base["demo"]
    demo_on = db["demo_default"]["trace_file"]
    demo_off_same = (not db["demo_off"]["trace_file"]
                     and not ds["demo_default"]["trace_file"])
    demo_default_change = (not ds["demo_default"]["trace_file"]) and demo_on
    cmp_rows: dict[str, Any] = {}
    for slug in ("liuxiang", "wanghong"):
        keys = ("cut_hits", "micro_gold_density", "avg_gold_density",
                "mean_gold_box_to_close", "n_leaks", "gold_total")
        cmp_rows[slug] = {
            "arm_off_vs_on": all(
                branch["replica"]["off"][slug][k]
                == branch["replica"]["on"][slug][k] for k in keys),
            "vs_c134": all(
                branch["replica"]["off"][slug][k] == base["replica"]["off"][slug][k]
                for k in keys if k in base["replica"]["off"][slug]),
        }
    return {
        "off_face_byte_identical": off_eq,
        "on_face_byte_identical": on_eq,
        "base_default_arm_silent": base_default_off,
        "branch_default_arm_live": br_default_on,
        "demo_default_live": demo_on,
        "demo_default_detail_ok": (
            db["demo_default"]["detail_present"]
            and (db["demo_default"]["detail_has_real_count"] is not False
                 or db["demo_default"]["empty_state"] is not True)),
        "demo_off_silent_both": demo_off_same,
        "demo_default_changed_by_flip": demo_default_change,
        "flag_default_now_branch": branch["flag_default_now"],
        "replica": cmp_rows,
    }


def _verdict(c: dict[str, Any]) -> dict[str, Any]:
    gates = {
        "g1_出厂默认True": c["flag_default_now_branch"] is True,
        "g2_默认开出口在场": (c["branch_default_arm_live"]
                             and c["demo_default_live"]
                             and c["demo_default_detail_ok"]),
        "g3_显式关与改前同形": (c["off_face_byte_identical"]
                               and c["demo_off_silent_both"]),
        "g4_旗开与改前同形": c["on_face_byte_identical"],
        "g5_默认翻转由旗造成": (c["base_default_arm_silent"]
                               and c["demo_default_changed_by_flip"]),
        "g6_旁证不掉": all(v["arm_off_vs_on"] and v["vs_c134"]
                           for v in c["replica"].values()),
    }
    return {"verdict": "YES" if all(gates.values()) else "NO",
            "gates": gates}


def _render_md(v: dict[str, Any], c: dict[str, Any],
               pytest_note: str) -> str:
    lines: list[str] = [
        "# C-145a — VERITAS_CONFLICT_TRACE 出厂默认开",
        "",
        f"> 判定＝**{v['verdict']}**（默认 True；关＝env VERITAS_CONFLICT_TRACE=0）。",
        "> 本刀只翻默认＋改文档／图面「默认关」表述＋守护格翻向；判定／打分／"
        "选段／装箱零改动。附带一个真修：conflict_trace_enabled() 无参回退"
        "原先不读出厂默认（env 未设恒 False）＝翻默认后仲裁／导出挂点会静默"
        "不走——改为走 Settings.from_env()（默认＋env 叠加），本票新格当场咬住。",
        "",
        "## 1. 出口面四臂（零 LLM・对撞夹具・改前 vs 改后）",
        "",
        f"- 显式关臂字节等证（与改前关旗臂逐文件 sha8）：{c['off_face_byte_identical']}",
        f"- 旗开臂字节等证（与改前旗开臂逐文件 sha8）：{c['on_face_byte_identical']}",
        f"- 改前默认臂静默（文件不出）＝{c['base_default_arm_silent']}｜"
        f"改后默认臂活（键活＋处置行）＝{c['branch_default_arm_live']}",
        "",
        "## 2. demo 冒烟（cases/demo-solid-state・零 LLM 全路径）",
        "",
        f"- 改后默认（未设 env）：conflict_trace.json 在场＝{c['demo_default_live']}"
        f"｜detail 在场＝{c['demo_default_detail_ok']}",
        f"- 显式关：文件不在场（两棵树都＝{c['demo_off_silent_both']}）",
        f"- 默认翻转由旗造成（改前 demo 静默→改后在场）＝"
        f"{c['demo_default_changed_by_flip']}",
        "",
        "## 3. 门控复刻（C-134 同尺・零 LLM・保险腿）",
        "",
    ]
    for slug, row in c["replica"].items():
        lines.append(f"- {slug}：两旗臂逐位同＝{row['arm_off_vs_on']}｜"
                     f"对 C-134 基线同＝{row['vs_c134']}")
    lines += [
        "",
        "## 4. 判据逐条",
        "",
    ]
    for k, val in v["gates"].items():
        lines.append(f"- {k}＝{val}")
    lines += [
        "",
        "## 5. 诚实披露",
        "",
        "- demo 冒烟＝桩客户端零 LLM 全路径（与 demo_offline 同形状），"
        "不是 14B 真跑；真跑出口在 C-143 已证（留痕 5 条）。",
        "- 关旗／旗开字节等证面剥 elapsed 时戳（逐跑必变）并排除 "
        "chain.jsonl／progress.json（逐跑日志面）。",
        "- 架构图 s22b 弹窗＋树22 徽标同步改「默认开」；HANDOFF 里 C-118／C-115 "
        "历史条目的「默认关」是史实不改。",
        f"- pytest：{pytest_note}",
        "",
        "## 6. 产物卫生",
        "",
        "- 夹具全合成；demo 腿只记文件在场／条数／空态布尔，不落原文。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=("export", "assemble"))
    ap.add_argument("--tag", default="branch")
    ap.add_argument("--out", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--branch", default="")
    ap.add_argument("--pytest", default="见交账行（探针外独立跑）")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.stage == "export":
        data = leg_export(a.tag)
        path = Path(a.out or (OUT / f"export_{a.tag}.json"))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"写出 {path}", flush=True)
        return 0
    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    branch = json.loads(Path(a.branch).read_text(encoding="utf-8"))
    c = _cmp(base, branch)
    v = _verdict(c)
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "C145a_default_on.json").write_text(
        json.dumps({"verdict": v, "compare": c},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "C145a_default_on.md").write_text(
        _render_md(v, c, a.pytest), encoding="utf-8")
    print(f"判定 {v['verdict']} 闸 {v['gates']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
