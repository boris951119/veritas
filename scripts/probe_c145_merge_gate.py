"""C-145 探针：归并硬约束闸（同主体×同指标×可核验）——直驱＋冒烟＋两树字节。

腿① 闸直驱（零调用・Coordinator.merge_conclusions）：三组夹具
  g1 同主体同指标（该合）｜g2 跨主体（subject_mismatch）｜g3 双缺主体
  （missing_subject）→ 读物化／否决／留痕行。
腿② 一案冒烟（零调用・run_case 全路径・3 分析师）：两好组并上、
  一坏组（缺主体）拆散且留痕；report.json accounting 与交卷回放面双在场。
腿③ 关旗字节（两树・env=0・run_case＋export_official）：branch-env0 vs
  base-env0 逐文件 sha8 同（剥时戳）；default 臂量化 delta（改前错并数 → 0）。

用法（在各树根下跑）：
  .venv/bin/python -m scripts.probe_c145_merge_gate --stage faces \
      --tag branch --out /tmp/c145/faces_branch.json
  .venv/bin/python -m scripts.probe_c145_merge_gate --stage assemble \
      --branch /tmp/c145/faces_branch.json --base /tmp/c145/faces_base.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ART = ROOT / "artifacts"
OUT = Path("/tmp/c145")

_EMPTY_JSON = '{"conclusions": []}'
_CONFLICT_EMPTY = '{"conflicts": []}'

# 三组夹具（全部合成文本，无官方语料）：
#   (CON-0, CON-1) 同主体×同指标＝该合；(CON-2, CON-3) 跨主体＝错并例；
#   (CON-4, CON-5) 双缺主体＝错并例。
_GROUPS_FIXTURE = [
    ("CON-0", "CON-1"),
    ("CON-2", "CON-3"),
    ("CON-4", "CON-5"),
]
_GROUP_JSON = '{"groups": [' + ",".join(
    '{"statement": "合并组%d", "member_ids": ["%s", "%s"]}' % (i, a, b)
    for i, (a, b) in enumerate(_GROUPS_FIXTURE)) + "]}"

_STATEMENTS = {
    "CON-0": "客户B存在回款风险",
    "CON-1": "客户B的回款存在困难",
    "CON-2": "客户C存在回款风险",
    "CON-3": "客户D存在回款风险",
    "CON-4": "项目存在回款风险",
    "CON-5": "项目回款存在困难",
}
_SEGMENT_TEXT = (
    "客户B 应收账款回款存在困难。客户C 存在回款风险提示。"
    "客户D 亦出现回款风险。项目整体回款存在风险，项目回款存在困难。"
)
_QUOTES = {
    "CON-0": "客户B 应收账款回款存在困难",
    "CON-1": "客户B 应收账款回款存在困难",
    "CON-2": "客户C 存在回款风险提示",
    "CON-3": "客户D 亦出现回款风险",
    "CON-4": "项目整体回款存在风险",
    "CON-5": "项目回款存在困难",
}


def _merge_dossier() -> Any:
    from app.core.evidence import (
        Conclusion, Dossier, EvidenceLevel, EvidenceNode, Segment, Source,
        SourceType,
    )

    d = Dossier(question="星辰数智各客户项目是否存在回款风险？")
    src = Source.create("账目", SourceType.REPORT, id="SRC1")
    src.segments.append(Segment(
        id="SRC1#s1", source_id="SRC1", text=_SEGMENT_TEXT, index=0))
    d.add_source(src)
    # 证据分 A/B/C 三层＝三组置信度严格有序：主席头条并列时按生成 id
    # （uuid）破平＝预存在逐跑非确定（与本票无关），量尺面绕开并列。
    levels = {"CON-0": EvidenceLevel.A, "CON-1": EvidenceLevel.A,
              "CON-2": EvidenceLevel.B, "CON-3": EvidenceLevel.B,
              "CON-4": EvidenceLevel.C, "CON-5": EvidenceLevel.C}
    for cid, stmt in _STATEMENTS.items():
        d.conclusions.append(Conclusion.create(stmt, author="a", id=cid))
        d.add_evidence(EvidenceNode.create(
            cid, _QUOTES[cid], ["SRC1#s1"], id=f"EV-{cid}",
            level=levels[cid]))
    return d


class _Fixed:
    """固定应答桩（分析师用）。"""

    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, model, messages, json_mode=False):
        return SimpleNamespace(content=self.content)


class _CoordStub:
    """协同段桩：归并提示词（协调员）回组表，其余回空。"""

    def __init__(self, merge_json: str) -> None:
        self.merge_json = merge_json
        self.calls: list[int] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append(1)
        sys_txt = str((messages[0] or {}).get("content", "")) \
            if messages else ""
        if "协调员" in sys_txt:
            return SimpleNamespace(content=self.merge_json)
        return SimpleNamespace(content=_CONFLICT_EMPTY)


class _SmokeCoordStub:
    """冒烟协同桩：归并调用时从提示词现抽结论 id（面板生成的 id 非固定）。"""

    def __init__(self, statements: dict[str, str],
                 groups: list[tuple[str, ...]]) -> None:
        self.statements = statements
        self.groups = groups
        self.calls: list[int] = []
        self.last_ids: dict[str, str] = {}

    def chat(self, model, messages, json_mode=False):
        import re

        self.calls.append(1)
        sys_txt = str((messages[0] or {}).get("content", "")) \
            if messages else ""
        if "协调员" not in sys_txt:
            return SimpleNamespace(content=_CONFLICT_EMPTY)
        text = str((messages[-1] or {}).get("content", ""))
        ids: dict[str, str] = {}
        for line in text.split("\n"):
            m = re.search(r"\[(CON-[0-9a-f]+)\]", line)
            if not m:
                continue
            rest = line[m.end():]
            for key, stmt in self.statements.items():
                if key not in ids and stmt in rest:
                    ids[key] = m.group(1)
        missing = [k for k in self.statements if k not in ids]
        assert not missing, f"冒烟夹具失灵：归并提示词里找不到 {missing}"
        self.last_ids = dict(ids)
        body = ",".join(
            '{"statement": "合并组%d", "member_ids": [%s]}'
            % (i, ",".join(f'"{ids[m]}"' for m in g))
            for i, g in enumerate(self.groups))
        return SimpleNamespace(content='{"groups": [%s]}' % body)


# ------------------------------------------------ 腿①：闸直驱（零调用）


def leg_unit() -> dict[str, Any]:
    from app.agents.arbiter import Coordinator
    from app.core.merge_gate import ACCOUNTING_KEY

    d = _merge_dossier()
    coord = Coordinator(_CoordStub(_GROUP_JSON), "m")
    active = coord.merge_conclusions(d, list(_STATEMENTS))
    rec = d.accounting[ACCOUNTING_KEY]
    merged_status = {c.id for c in d.conclusions if c.status == "merged"}
    # 误并例＝坏组（g2/g3）成员被并（status=merged）的条数
    wrong_merged = sorted(merged_status & {"CON-2", "CON-3", "CON-4", "CON-5"})
    # 该合的合＝g1 两成员都进组（merged）且存在组结论在场
    good_ok = ({"CON-0", "CON-1"} <= merged_status
               and any(c.id not in _STATEMENTS and c.status == "majority"
                       for c in d.conclusions)
               and rec["n_blocked"] == 2 and rec["n_groups_checked"] == 3
               and not wrong_merged)
    rows = rec["blocked"]
    out = {
        "n_active": len(active),
        "n_groups_checked": rec["n_groups_checked"],
        "n_blocked": rec["n_blocked"],
        "blocked_fail_legs": [r["fail_legs"] for r in rows],
        "wrong_merged_ids": wrong_merged,
        "good_group_merged": good_ok,
        "ok": good_ok,
    }
    print(f"[腿① 直驱] 核查 {rec['n_groups_checked']} 否决 {rec['n_blocked']} "
          f"误并 {len(wrong_merged)} 活跃 {len(active)} fail_legs="
          f"{out['blocked_fail_legs']}", flush=True)
    return out


# ------------------------------------------------ 腿②：一案冒烟（零调用・全路径）


_PANELS = {
    "mainstream": ["CON-0", "CON-2"],
    "technologist": ["CON-1", "CON-3"],
    "redteam": ["CON-4", "CON-5"],
}
# 冒烟组表：好组 (客户B m+t)、好组 (客户C m+t)、坏组 (双缺主体 redteam)。
# CON-3 在冒烟里属客户C（与直驱/字节夹具的「客户D」不同＝各腿各夹具）；
# id 由 _SmokeCoordStub 从归并提示词现抽（面板生成的 id 非固定）。
_SMOKE_STATEMENTS = dict(_STATEMENTS)
_SMOKE_STATEMENTS["CON-3"] = "客户C的回款存在困难"
_SMOKE_QUOTES = dict(_QUOTES)
_SMOKE_QUOTES["CON-3"] = "客户C 存在回款风险提示"
_SMOKE_GROUPS = [("CON-0", "CON-1"), ("CON-2", "CON-3"), ("CON-4", "CON-5")]


def leg_smoke() -> dict[str, Any]:
    from app.agents.base import Analyst
    from app.export.official import export_official
    from app.pipeline import RunDeps, RunSpec, run_case

    tmp = Path(tempfile.mkdtemp(prefix="c145_smoke_"))
    case = tmp / "case"
    case.mkdir(parents=True)
    (case / "manifest.yaml").write_text(
        "question: 星辰数智各客户项目是否存在回款风险？\ntitle: C-145\n",
        encoding="utf-8")
    (case / "a.md").write_text(f"# 账目\n\n{_SEGMENT_TEXT}\n",
                               encoding="utf-8")
    out = tmp / "out"

    def _panel_json(cids: list[str]) -> str:
        rows = ",".join(
            '{"statement": "%s", "evidence": [{"quote": "%s", '
            '"segment_id": "SRC1#s1", "relation": "correlation", '
            '"level": "B", "note": ""}]}' % (_SMOKE_STATEMENTS[c],
                                             _SMOKE_QUOTES[c])
            for c in cids)
        return '{"conclusions": [%s]}' % rows

    analysts = [
        Analyst(name, "视角", _Fixed(_panel_json(cids)), "m")
        for name, cids in _PANELS.items()
    ]
    deps = RunDeps(client=_SmokeCoordStub(_SMOKE_STATEMENTS, _SMOKE_GROUPS),
                   analysts=analysts)
    r = run_case(RunSpec(case_dir=case, out_dir=out, probe=False), deps)
    acc = r.dossier.accounting or {}
    rec = acc.get("merge_gate") or {}
    majors = [c for c in r.dossier.conclusions if c.status == "majority"]
    merged_status = {c.id for c in r.dossier.conclusions
                     if c.status == "merged"}
    # 坏组成员＝桩解析出的运行时 id（字面 CON-4/5 只是夹具键）
    real_ids = getattr(deps.client, "last_ids", {}) or {}
    bad_ids = {real_ids.get("CON-4", ""), real_ids.get("CON-5", "")}
    wrong_merged = sorted(merged_status & bad_ids - {""})
    n_groups = sum(1 for c in majors if c.id not in _STATEMENTS
                   and len(c.authors) >= 2)
    official = out / "official"
    export_official([({"question_id": "q1",
                       "question": r.dossier.question}, r.dossier)],
                    official)
    tf = official / "conflict_trace.json"
    payload = json.loads(tf.read_text(encoding="utf-8")) if tf.exists() else {}
    report_acc = json.loads(
        (out / "report.json").read_text(encoding="utf-8")).get("accounting") or {}
    out_row = {
        "case": str(case),
        "n_groups_checked": rec.get("n_groups_checked"),
        "n_blocked": rec.get("n_blocked"),
        "blocked_fail_legs": [b["fail_legs"]
                              for b in (rec.get("blocked") or [])],
        "n_cross_author_groups": n_groups,
        "n_merged_members": len(merged_status),
        "wrong_merged_ids": wrong_merged,
        "n_majority": len(majors),
        "report_accounting_has_key": "merge_gate" in report_acc,
        "trace_file": tf.exists(),
        "trace_section": isinstance(payload.get("merge_gate"), dict),
        "trace_blocked": ((payload.get("merge_gate") or {}).get("n_blocked")),
    }
    out_row["ok"] = (out_row["n_blocked"] == 1
                     and out_row["blocked_fail_legs"] == [["missing_subject"]]
                     and out_row["n_cross_author_groups"] == 2
                     and out_row["n_merged_members"] == 4
                     and not wrong_merged
                     and out_row["report_accounting_has_key"]
                     and out_row["trace_section"]
                     and out_row["trace_blocked"] == 1)
    print(f"[腿② 冒烟] 核查 {out_row['n_groups_checked']} 否决 "
          f"{out_row['n_blocked']} 会签组 {n_groups} 误并 "
          f"{len(wrong_merged)} 报面键 {out_row['report_accounting_has_key']} "
          f"回放节 {out_row['trace_section']}", flush=True)
    return out_row


# ------------------------------------------------ 腿③：两树字节（env=0 vs default）

# 归并组结论 id＝Conclusion.create 生成（uuid4，逐进程随机＝既有行为，
# 非本票引入）：凡物化了归并组的产物跨进程字节不可比。量尺面按首现序
# 匿名化（一张映射管整个臂的文件，同 id 跨文件映射一致）。
_GEN_ID = re.compile(r"CON-[0-9a-f]{12}")


def _anon_ids(text: str, id_map: dict[str, str]) -> str:
    def _sub(m: re.Match) -> str:
        tok = m.group(0)
        return id_map.setdefault(tok, f"CONX-{len(id_map) + 1:02d}")
    return _GEN_ID.sub(_sub, text)


def _arm_hashes(root: Path, id_map: dict[str, str] | None = None) -> dict[str, str]:
    from scripts.probe_c143_trace_face import _norm_report_json, _norm_report_md

    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8")
        if rel.endswith("report.json"):
            text = _norm_report_json(json.loads(text))
        elif rel.endswith("report.md"):
            text = _norm_report_md(text)
        # 每文件独立映射：各文件自身的 id 首现序稳定即可等证；
        # 共享映射会被先扫到的文件（confidence.json 等）的 id 序污染。
        out[rel] = hashlib.sha256(
            _anon_ids(text, {}).encode("utf-8")).hexdigest()[:8]
    return out


def _arm(flag: str | None) -> dict[str, Any]:
    """flag=None＝出厂默认；"0"＝显式关。run_case 全路径＋交卷面。"""
    import os

    from app.agents.base import Analyst
    from app.export.official import export_official
    from app.pipeline import RunDeps, RunSpec, run_case

    if flag is None:
        os.environ.pop("VERITAS_CONFLICT_TRACE", None)
    else:
        os.environ["VERITAS_CONFLICT_TRACE"] = flag
    tmp = Path(tempfile.mkdtemp(prefix=f"c145_byte_{flag}_"))
    case = tmp / "case"
    case.mkdir(parents=True)
    (case / "manifest.yaml").write_text(
        "question: 星辰数智各客户项目是否存在回款风险？\ntitle: C-145\n",
        encoding="utf-8")
    out = tmp / "out"
    deps = RunDeps(client=_CoordStub(_GROUP_JSON), analysts=[
        Analyst("mainstream", "测", _Fixed(_EMPTY_JSON), "m"),
        Analyst("technologist", "测", _Fixed(_EMPTY_JSON), "m")])
    r = run_case(RunSpec(case_dir=case, out_dir=out,
                         dossier=_merge_dossier(), probe=False), deps)
    official = out / "official"
    export_official([({"question_id": "q1",
                       "question": r.dossier.question}, r.dossier)],
                    official)
    acc = r.dossier.accounting or {}
    majors = [c for c in r.dossier.conclusions if c.status == "majority"]
    merged_status = {c.id for c in r.dossier.conclusions
                     if c.status == "merged"}
    wrong_merged = sorted(merged_status & {"CON-2", "CON-3", "CON-4", "CON-5"})
    tf = official / "conflict_trace.json"
    payload = json.loads(tf.read_text(encoding="utf-8")) if tf.exists() else {}
    row = {
        "flag": flag,
        "n_majority": len(majors),
        "n_merged_members": len(merged_status),
        "wrong_merged_ids": wrong_merged,
        "acc_merge_gate": isinstance(acc.get("merge_gate"), dict),
        "acc_conflict_trace": isinstance(acc.get("conflict_trace"), dict),
        "trace_file": tf.exists(),
        "trace_merge_gate_section": isinstance(
            payload.get("merge_gate"), dict),
        "trace_empty_state": payload.get("empty_state"),
        "file_hashes": _arm_hashes(out),
    }
    print(f"[腿③ 旗={flag}] 多数 {row['n_majority']} 被并成员 "
          f"{row['n_merged_members']} 误并 {len(wrong_merged)} 闸键 "
          f"{row['acc_merge_gate']} 回放节 {row['trace_merge_gate_section']}",
          flush=True)
    return row


def leg_faces() -> dict[str, Any]:
    # base 树（改前）没有 merge_gate 模块：unit/smoke 两腿缺席记原因，
    # 字节两臂（关旗同形＋改前错并在场）必须在两树都跑。
    out: dict[str, Any] = {}
    for name, fn in (("unit", leg_unit), ("smoke", leg_smoke)):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001 — base 树缺席是预期形态
            out[name] = None
            out[f"{name}_absent_reason"] = f"{type(exc).__name__}: {exc}"
            print(f"[{name}] 缺席＝{type(exc).__name__}: {exc}", flush=True)
    out["arm_default"] = _arm(None)
    out["arm_off"] = _arm("0")
    return out


# ------------------------------------------------ 判表＋artifact


def _face(h: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in h.items()
            if not k.startswith(("chain.jsonl", "progress.json"))}


def _verdict(branch: dict, base: dict) -> dict[str, Any]:
    gates: dict[str, Any] = {}
    u, s = branch["unit"], branch["smoke"]
    gates["g1_闸在场_默认开零调用"] = (
        u["n_groups_checked"] == 3 and u["n_blocked"] == 2
        and u["wrong_merged_ids"] == []
        and branch["arm_default"]["acc_merge_gate"] is True
        and branch["arm_default"]["trace_merge_gate_section"] is True)
    gates["g2_误并例等于0"] = (u["wrong_merged_ids"] == []
                              and s["wrong_merged_ids"] == []
                              and branch["arm_default"]["wrong_merged_ids"] == [])
    gates["g3_该合的合"] = (u["ok"] and s["ok"]
                            and branch["arm_default"]["wrong_merged_ids"] == [])
    gates["g4_关旗与改前同形"] = (
        _face(branch["arm_off"]["file_hashes"])
        == _face(base["arm_off"]["file_hashes"]))
    gates["g5_改前错并在场_夹具有判别力"] = (
        base["arm_default"]["wrong_merged_ids"]
        == ["CON-2", "CON-3", "CON-4", "CON-5"]
        and base["arm_default"]["n_merged_members"] == 6)
    verdict = "YES" if all(gates.values()) else "NO"
    delta = {
        "branch_default_vs_base_default_多并组数": (
            base["arm_default"]["n_merged_members"]
            - branch["arm_default"]["n_merged_members"]),
        "branch_default_n_majority": branch["arm_default"]["n_majority"],
        "base_default_n_majority": base["arm_default"]["n_majority"],
        "branch_default_wrong_merged": branch["arm_default"]["wrong_merged_ids"],
        "base_default_wrong_merged": base["arm_default"]["wrong_merged_ids"],
    }
    return {"verdict": verdict, "gates": gates, "delta": delta}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=("faces", "assemble"))
    ap.add_argument("--tag", default="branch")
    ap.add_argument("--out", default="")
    ap.add_argument("--branch", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--pytest", default="见交账行（探针外独立跑）")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.stage == "faces":
        data = leg_faces()
        path = Path(a.out or (OUT / f"faces_{a.tag}.json"))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"写出 {path}", flush=True)
        return 0
    branch = json.loads(Path(a.branch).read_text(encoding="utf-8"))
    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    v = _verdict(branch, base)
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "C145_merge_gate.json").write_text(
        json.dumps({"verdict": v, "branch": branch, "base": base},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    lines = [
        "# C-145 — 树22 归并硬约束闸（同主体×同指标×可核验才合）",
        "",
        f"> 判定＝**{v['verdict']}**（闸随 VERITAS_CONFLICT_TRACE，"
        "C-145a 起出厂默认开；env=0 全关＝改前归并行为逐字节一致）。",
        "> 只看 LLM 语义归并段；机械归并键已含三腿零改动；"
        "数值冲突加权／打分零改动（STOP 线）。",
        "",
        "## 判据逐条",
        "",
    ]
    for k, val in v["gates"].items():
        lines.append(f"- {k}＝{val}")
    lines += [
        "",
        "## delta（default 臂・branch vs base 03bfd4a）",
        "",
        f"- 改前错并成员数 {base['arm_default']['n_merged_members']} → "
        f"改后 {branch['arm_default']['n_merged_members']}"
        f"（差 {v['delta']['branch_default_vs_base_default_多并组数']}）",
        f"- 误并成员 ids：改前 {v['delta']['base_default_wrong_merged']} → "
        f"改后 {v['delta']['branch_default_wrong_merged']}",
        f"- 多数结论数：改前 {v['delta']['base_default_n_majority']} → "
        f"改后 {v['delta']['branch_default_n_majority']}",
        "",
        f"- pytest：{a.pytest}",
        "",
        "## 行为说明（关／开 CONFLICT_TRACE）",
        "",
        "- 关（VERITAS_CONFLICT_TRACE=0）：闸全关＝改前归并行为"
        "（错组照并、无闸键、无回放节）＝腿③字节等证。",
        "- 开（默认）：LLM ≥2 人组过四腿（同主体／同指标／极性不反／"
        "可核验）；不过→整组否决成员保独立＋accounting[merge_gate]"
        "＋conflict_trace.json merge_gate 节。",
        "",
        "## 产物卫生",
        "",
        "- 夹具全部合成（客户B/客户C/项目…占位句），无官方语料原文；"
        "闸行只记 id 与腿读数，不落结论文本。",
        "- 字节面归一：归并组结论 id＝uuid4 逐进程随机（既有行为，"
        "非本票引入）⇒ 量尺面把生成 id 按各文件首现序匿名化（CONX-NN）；"
        "chain.jsonl／progress.json 逐跑日志面不计入；report.json／"
        "report.md 剥 elapsed 时戳。",
        "- 主席头条并列破平键＝结论 id（uuid 生成）＝置信度精确并列时"
        "逐跑可非确定（预存在行为，与本票无关；夹具用 A/B/C 分层证据"
        "避开并列）。正式修它＝动 chair 破平键，超出本票范围。",
        "",
    ]
    (ART / "C145_merge_gate.md").write_text("\n".join(lines),
                                            encoding="utf-8")
    print(f"判定 {v['verdict']} 闸 {v['gates']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
