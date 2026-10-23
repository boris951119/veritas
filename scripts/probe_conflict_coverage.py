"""C-41 冲突面覆盖量尺（只读探针）：现行冲突映射能交几条、三种映射各交几条、对金标两阶段匹配。

零 LLM、零网络、不写 app/、不把样例集／六案产物复制进仓库。只读既有 report.json。

跑法：
    .venv/bin/python scripts/probe_conflict_coverage.py
    OFFICIAL_CASES=/path/to/样例集 OFFICIAL_RUN=/path/to/time-run \\
        .venv/bin/python scripts/probe_conflict_coverage.py

环境变量（均可覆盖；缺目录或空目录 ⇒ 退出码 2，不许静默印 0）：
    OFFICIAL_CASES  官方样例集根（默认 ~/Desktop/veritas-testcases/样例集-拓尔思-20261012）
    OFFICIAL_RUN    六案跑产物根，形如 <case>/questions/<qid>/report.json
                    （默认 /tmp/s4runs/time-20261020-174839）
    INREPO_ROOT     仓内产物扫描根（默认 <repo>/cases）；甲档自检用
                    cases/*/out*/report.json（一层，34 份）

件① 从 report.json 重建 dossier，跑现行冲突映射，逐案打印
    内部冲突对／进入 conflicting_facts（对数＝未跳过且映射出段落的对）／
    平局跳过／取不到段落跳过／事实行数，并原样打印复算命令。
件② 同一批上三种映射条数：甲＝只交败方；乙＝平局／未分胜负也交双方；
    丙＝乙＋每条附 verdict_label（只算条数与形状，取值仅 partial_support／full_support）。
件③ 与仓库外金标做两阶段匹配算 Precision_conf／Recall_conf：
    第一步 doc_id+para_id 精确；第二步规则近似（主体＋数值＋时点三项一致）。
    输出必含：「第二步是规则近似，官方那一步是大模型语义判定」。
件④／丁档（C-42）候选条目全集上界＝四路并集：
    conflicts（乙形＝败方＋平局双方）／fact_ledger 对撞 Fact／rejected／dissent；
    条目形 (doc_id, para_id, 陈述文本, 来源标签)，去重键 (doc_id, para_id)；
    定位不到段落的不计入上界，但单独打印丢弃条数；第二步仍 approx=not_available。
件⑤／戊档（C-44）「口径并存」上界＝find_collisions 同 (实体, 指标) 多值组
    × precedent._diff_kind 成对；两侧各锚 (doc_id, para_id)；去重键同；
    只算对金标 91 条（去重段键 78）第一步 doc_id+para_id 精确覆盖；
    类别取值以 _diff_kind 实测为准（时点／数字／收场）；票文「统计口径／
    单位换算／信源层级」与源码不符时打印 §3.4 质疑，不闷着改分类器；
    定位不到不计入并单独打印丢弃数；通用性腿＝同一规则跑仓内 34 份 ≥1 对。
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.core.evidence import Dossier  # noqa: E402
from app.core.fact_ledger import find_collisions  # noqa: E402
from app.core.precedent import _diff_kind  # noqa: E402
from app.core.conflicts import dissent_conclusions  # noqa: E402
from app.export.official import _conflicting_facts, _segment_locator  # noqa: E402

OFFICIAL_CASES = os.environ.get(
    "OFFICIAL_CASES",
    os.path.expanduser("~/Desktop/veritas-testcases/样例集-拓尔思-20261012"),
)
OFFICIAL_RUN = os.environ.get(
    "OFFICIAL_RUN",
    "/tmp/s4runs/time-20261023-173124",
)
INREPO_ROOT = os.environ.get("INREPO_ROOT", str(REPO / "cases"))

# 官方样例集里出现过的 verdict_label；不许自造枚举。
_VERDICT_ALLOWED = ("partial_support", "full_support")
# 丙档形状占位：只证明字段形状，不做真实判定（dominant 金标值）。
_VERDICT_SHAPE_PLACEHOLDER = "partial_support"
assert _VERDICT_SHAPE_PLACEHOLDER in _VERDICT_ALLOWED

_SLOT_KEYS = ("主体", "时间", "数值口径")  # 主体＋时点＋数值
_APPROX_NOTE = "第二步是规则近似，官方那一步是大模型语义判定"
_APPROX_NA_NOTE = (
    "第二步近似档需要我方自有槽位、当前不可测："
    "我方只从 quote／segment 正则年份与数字（主体抽不出），"
    "与金标 argument（主体／时间／数值口径）字面不可比，故只报 exact-only；"
    "官方第二步是大模型语义判定、本探针不做"
)
_DING_OFFICIAL_STEP2 = "官方第二步是大模型语义判定、本探针不做"
_DING_LAYER_NOTE = {
    "conflicts": (
        "放行 conflicts／平局另一侧：导出层一条规则"
        "（现行甲只交败方；乙形把平局／未分胜负双方也交出去）"
    ),
    "fact_ledger": (
        "放行 fact_ledger 对撞：导出层新增来源"
        "（数据已在 accounting／dossier 可重算，不需要模型）"
    ),
    "rejected": (
        "放行 rejected：导出层新增来源＋要不要给它一个「所涉结论」字段的口径"
        "（持久化只有 evidence_id／conclusion_id／quote／problems，无原生 segment_ids）"
    ),
    "dissent": (
        "放行 dissent 少数意见：导出层新增来源＋要不要给它一个「所涉结论」字段的口径"
        "（结论自带 statement＋evidence_ids，经 evidences_of→segment_ids 可定位）"
    ),
}
_WU_KIND_NOTE = (
    "§3.4 质疑（件① 当场实测）：票文期望类别＝时点不同／统计口径不同／"
    "单位换算不同／信源层级不同；源码 app/core/precedent.py:_diff_kind "
    "实际只返回 {'时点','数字','收场'}；Collision.cross_source 是属性、"
    "不是 _diff_kind 类别。本档按实测三类记账，不闷着改分类器。"
)
_WU_THRESHOLD = 40  # 硬门槛：可定位并集覆盖 ≥40／78 才进件②
_WU_GOLD_KEYS = 78  # 金标 conflicting_facts 去重段键

# rejected.problems 里「（seg_id）」形；无原生 segment_ids 时的唯一定位线索
_REJECTED_SEG_RE = re.compile(r"（([^）]*#[^）]*)）")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _require_dir(path: str, label: str) -> Path:
    p = Path(path)
    if not p.is_dir():
        _die(f"找不到{label}目录：{p}\n"
             f"用对应 env 指定（样例集／产物不入仓库，见模块 docstring）。")
    return p


def _official_case_dirs(root: Path) -> list[Path]:
    out = []
    for name in sorted(os.listdir(root)):
        d = root / name
        if d.is_dir() and not name.startswith(".") and (d / "conclusions.json").is_file():
            out.append(d)
    if not out:
        _die(f"{root} 为空或不含官方案卷（缺 conclusions.json）")
    return out


def _run_case_dirs(root: Path, official_names: set[str]) -> list[Path]:
    out = []
    for name in sorted(os.listdir(root)):
        d = root / name
        if not d.is_dir() or name.startswith("."):
            continue
        if official_names and name not in official_names:
            continue
        reports = list((d / "questions").glob("*/report.json"))
        if reports:
            out.append(d)
    if not out:
        _die(f"{root} 为空或不含六案跑产物（缺 <case>/questions/*/report.json）")
    return out


def _inrepo_reports(root: Path) -> list[Path]:
    """一层 cases/*/out*/report.json＝判据 d 的 34 份面（不含 Q 嵌套）。"""
    root = Path(root)
    if not root.is_dir():
        _die(f"找不到仓内产物根：{root}（用 INREPO_ROOT 指定）")
    paths = sorted(root.glob("*/out*/report.json"))
    if not paths:
        _die(f"{root} 下没有 cases/*/out*/report.json")
    return paths


def _load_dossier(path: Path) -> Dossier:
    return Dossier.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _pair_sides(pair: dict) -> tuple[str, str, str, list[str] | None]:
    """返回 (a_id, b_id, winner, sides_or_None)。

    sides_or_None：
      - [loser] 有胜方
      - [a, b] 调用方在乙／丙下对平局使用
      - None 表示甲档应计平局跳过
    """
    a_id = str(pair.get("a_id") or "")
    b_id = str(pair.get("b_id") or "")
    res = pair.get("resolution") if isinstance(pair.get("resolution"), dict) else {}
    winner = str((res or {}).get("winner_id") or "")
    if a_id and b_id and winner in (a_id, b_id):
        loser = b_id if winner == a_id else a_id
        return a_id, b_id, winner, [loser]
    return a_id, b_id, winner, None


def _map_side_facts(dossier: Dossier, side_ids: list[str],
                    seen: set[tuple[str, str]],
                    with_verdict: bool) -> tuple[list[dict], bool]:
    facts: list[dict] = []
    mapped_any = False
    for cid in side_ids:
        for ev in dossier.evidences_of(cid):
            for sid in ev.segment_ids:
                loc = _segment_locator(dossier, sid)
                if loc is None:
                    continue
                mapped_any = True
                if loc in seen:
                    continue
                seen.add(loc)
                item: dict = {"doc_id": loc[0], "para_id": loc[1]}
                if with_verdict:
                    item["verdict_label"] = _VERDICT_SHAPE_PLACEHOLDER
                facts.append(item)
    return facts, mapped_any


def map_conflicts(dossier: Dossier, mode: str) -> dict:
    """mode ∈ {jia, yi, bing}。

    甲＝现行（有胜方取败方；平局／未分胜负整对丢弃）＝直接调 _conflicting_facts。
    乙＝平局／未分胜负也交双方。
    丙＝乙＋verdict_label 形状（占位 partial_support，不计真实判定）。
    """
    if mode not in ("jia", "yi", "bing"):
        raise ValueError(mode)
    pairs = [p for p in (dossier.conflicts or []) if isinstance(p, dict)]
    n_pairs = len(pairs)

    if mode == "jia":
        facts, skipped_tie, skipped_noloc = _conflicting_facts(dossier)
        # 「进入」按对数＝未跳过且至少映射出 1 个段落的对（与架构师 44/39/5 对齐）
        entered_pairs = 0
        for pair in pairs:
            _a, _b, _w, sides = _pair_sides(pair)
            if sides is None:
                continue
            _f, mapped = _map_side_facts(dossier, sides, set(), False)
            if mapped:
                entered_pairs += 1
        return {
            "n_pairs": n_pairs,
            "entered_pairs": entered_pairs,
            "n_facts": len(facts),
            "skipped_tie": skipped_tie,
            "skipped_noloc": skipped_noloc,
            "facts": facts,
        }

    with_verdict = mode == "bing"
    facts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    skipped_tie = 0  # 乙／丙不因平局跳过
    skipped_noloc = 0
    entered_pairs = 0
    for pair in pairs:
        _a, _b, _w, sides = _pair_sides(pair)
        if sides is None:
            sides = [_a, _b] if _a and _b else []
            if not sides:
                skipped_tie += 1
                continue
        chunk, mapped = _map_side_facts(dossier, sides, seen, with_verdict)
        facts.extend(chunk)
        if mapped:
            entered_pairs += 1
        else:
            skipped_noloc += 1
    return {
        "n_pairs": n_pairs,
        "entered_pairs": entered_pairs,
        "n_facts": len(facts),
        "skipped_tie": skipped_tie,
        "skipped_noloc": skipped_noloc,
        "facts": facts,
    }


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


def _slots_of(argument: dict | None) -> tuple[str, str, str]:
    a = argument or {}
    return tuple(_norm(str(a.get(k) or "")) for k in _SLOT_KEYS)


def _slots_match(a: tuple[str, str, str], b: tuple[str, str, str]) -> bool:
    """三项一致；全空不算命中（避免空＝空虚匹配）。"""
    if a != b:
        return False
    return any(a)


def _fact_index(evidence_rows: list[dict]) -> dict[str, dict]:
    """fact_id → evidence row（含 doc_id/para_id/argument）。"""
    out: dict[str, dict] = {}
    for row in evidence_rows:
        fid = row.get("fact_id")
        if fid is None or str(fid) == "":
            continue
        out[str(fid)] = row
    return out


def _gold_conf_items(case_dir: Path) -> list[dict]:
    """金标 conflicting_facts 换形为带 para_id + slots 的条目（可一对一消耗）。

    金标槽位仍读 argument（主体／时间／数值口径）；我方槽位另走原文正则。
    两口径字面不可比 ⇒ 近似档由 _approx_available 判 not_available，只报 exact-only。
    """
    conc = json.loads((case_dir / "conclusions.json").read_text(encoding="utf-8"))
    ev_rows = json.loads((case_dir / "evidence_samples.json").read_text(encoding="utf-8"))
    index = _fact_index(ev_rows)
    by_dp: dict[tuple[str, str], dict] = {}
    for row in ev_rows:
        key = (str(row.get("doc_id") or ""), str(row.get("para_id") or ""))
        if key[0] and key[1]:
            by_dp.setdefault(key, row)
    items: list[dict] = []
    for row in conc:
        qid = str(row.get("question_id") or "")
        for item in row.get("conflicting_facts") or []:
            if not isinstance(item, dict):
                continue
            fid = str(item.get("fact_id") or "")
            ev = index.get(fid)
            if ev and ev.get("doc_id") and ev.get("para_id"):
                doc_id = str(ev["doc_id"])
                para_id = str(ev["para_id"])
                argument = ev.get("argument") or {}
            else:
                doc_id = str(item.get("doc_id") or "")
                para_id = str(item.get("para_id") or "")
                argument = (by_dp.get((doc_id, para_id)) or {}).get("argument") or {}
            items.append({
                "question_id": qid,
                "doc_id": doc_id,
                "para_id": para_id,
                "slots": _slots_of(argument if isinstance(argument, dict) else {}),
                "verdict_label": str(item.get("verdict_label") or ""),
            })
    return items


def _slots_from_our_text(text: str) -> tuple[str, str, str]:
    """我方自有槽位＝(主体, 时间, 数值口径)。

    只从原文正则：时间←年份，数值口径←数字；主体无法可靠正则 ⇒ 空。
    不查金标 argument（R-C41-2）。
    """
    if not (text or "").strip():
        return ("", "", "")
    years = list(dict.fromkeys(_YEAR_RE.findall(text)))
    nums = list(dict.fromkeys(_NUM_RE.findall(text)))
    return ("", " ".join(years), " ".join(nums))


def _our_text_by_dp(dossier: Dossier) -> dict[tuple[str, str], str]:
    """(doc_id, para_id) → 我方原文（segments.text 与 evidences.quote 拼接）。"""
    out: dict[tuple[str, str], str] = {}

    def _add(key: tuple[str, str], chunk: str) -> None:
        chunk = (chunk or "").strip()
        if not chunk:
            return
        prev = out.get(key)
        out[key] = chunk if not prev else (prev + "\n" + chunk)

    for src in dossier.sources:
        doc_id = str((src.meta or {}).get("doc_id") or src.id or "")
        for seg in src.segments:
            _add((doc_id, str(seg.id)), getattr(seg, "text", "") or "")
    for ev in dossier.evidences:
        for sid in ev.segment_ids:
            loc = _segment_locator(dossier, sid)
            if loc is None:
                continue
            _add(loc, getattr(ev, "quote", "") or "")
    return out


def _merge_text_by_dp(dst: dict[tuple[str, str], str],
                     src: dict[tuple[str, str], str]) -> None:
    for k, v in src.items():
        if not v:
            continue
        prev = dst.get(k)
        dst[k] = v if not prev else (prev + "\n" + v)


def _submitted_items(facts: list[dict],
                     text_by_dp: dict[tuple[str, str], str]) -> list[dict]:
    """我方提交项：槽位只从我方产物原文正则，不查金标 argument。"""
    items = []
    for f in facts:
        doc_id = str(f.get("doc_id") or "")
        para_id = str(f.get("para_id") or "")
        text = text_by_dp.get((doc_id, para_id)) or ""
        items.append({
            "doc_id": doc_id,
            "para_id": para_id,
            "slots": _slots_from_our_text(text),
            "verdict_label": str(f.get("verdict_label") or ""),
            "has_our_text": bool(text.strip()),
        })
    return items


def _approx_available(submitted: list[dict]) -> bool:
    """近似档可测判定。

    我方槽位＝原文正则年份／数字（主体抽不出）；金标槽位＝argument 三槽。
    两口径字面不可比 ⇒ 本探针固定不可测（避免结构性／误导性 approx=0）。
    取不到我方原文时同样不可测。保留 has_our_text 供日后可比口径启用。
    """
    _ = submitted  # 口径不可比；不靠 submitted 放行
    return False


def two_stage_match(submitted: list[dict], gold: list[dict],
                    *, approx_available: bool | None = None) -> dict:
    """第一步精确 (doc_id, para_id)；第二步规则近似（主体＋数值＋时点）。

    一对一消耗，与 score_official.exact_hits 同形。
    approx_available=False ⇒ 不跑第二步、approx=not_available，只报 exact-only P／R。
    """
    if approx_available is None:
        approx_available = _approx_available(submitted)
    gold_left = list(gold)
    sub_left: list[dict] = []
    exact = 0
    for s in submitted:
        key = (s["doc_id"], s["para_id"])
        hit_i = next((i for i, g in enumerate(gold_left)
                      if (g["doc_id"], g["para_id"]) == key), None)
        if hit_i is None:
            sub_left.append(s)
            continue
        gold_left.pop(hit_i)
        exact += 1
    n_sub = len(submitted)
    n_gold = len(gold)
    if not approx_available:
        precision = 0.0 if n_sub == 0 else exact / n_sub
        recall = 0.0 if n_gold == 0 else exact / n_gold
        return {
            "n_sub": n_sub,
            "n_gold": n_gold,
            "exact": exact,
            "approx": "not_available",
            "hits": exact,
            "Precision_conf": precision,
            "Recall_conf": recall,
            "approx_available": False,
        }
    approx = 0
    still: list[dict] = []
    for s in sub_left:
        hit_i = next((i for i, g in enumerate(gold_left)
                      if _slots_match(s["slots"], g["slots"])), None)
        if hit_i is None:
            still.append(s)
            continue
        gold_left.pop(hit_i)
        approx += 1
    hits = exact + approx
    precision = 0.0 if n_sub == 0 else hits / n_sub
    recall = 0.0 if n_gold == 0 else hits / n_gold
    return {
        "n_sub": n_sub,
        "n_gold": n_gold,
        "exact": exact,
        "approx": approx,
        "hits": hits,
        "Precision_conf": precision,
        "Recall_conf": recall,
        "approx_available": True,
    }



def _entry(doc_id: str, para_id: str, statement: str, source: str) -> dict:
    return {
        "doc_id": doc_id,
        "para_id": para_id,
        "statement": statement or "",
        "sources": [source],
    }


def _stream_conflicts(dossier: Dossier) -> tuple[list[dict], list[dict], str]:
    """一路＝conflicts 乙形（败方＋平局／未分胜负双方）→ 可定位条目。

    返回 (locable_entries, discarded, empty_reason)。
    原始单位＝冲突对侧结论×其证据段；定位靠 _segment_locator。
    """
    pairs = [p for p in (dossier.conflicts or []) if isinstance(p, dict)]
    if not pairs:
        return [], [], "dossier.conflicts 为空（本份产物无冲突对）"
    raw_rows: list[tuple[str, str, str, str]] = []  # side_id used only for stmt
    discarded: list[dict] = []
    for pair in pairs:
        a_id, b_id, _w, sides = _pair_sides(pair)
        if sides is None:
            sides = [a_id, b_id] if a_id and b_id else []
        for cid in sides:
            con = dossier.conclusion(cid) if cid else None
            stmt = (con.statement if con else "") or ""
            evs = dossier.evidences_of(cid) if cid else []
            if not evs:
                discarded.append({
                    "reason": "结论无证据",
                    "conclusion_id": cid,
                    "stream": "conflicts",
                })
                continue
            any_seg = False
            for ev in evs:
                for sid in ev.segment_ids:
                    any_seg = True
                    loc = _segment_locator(dossier, sid)
                    if loc is None or not loc[0] or not loc[1]:
                        discarded.append({
                            "reason": "segment 定位失败",
                            "segment_id": sid,
                            "conclusion_id": cid,
                            "stream": "conflicts",
                        })
                        continue
                    raw_rows.append((loc[0], loc[1], stmt, "conflicts"))
            if not any_seg:
                discarded.append({
                    "reason": "证据无 segment_ids",
                    "conclusion_id": cid,
                    "stream": "conflicts",
                })
    # 本路内先按 (doc_id, para_id) 去重，来源标签合并（同路只有 conflicts）
    by: dict[tuple[str, str], dict] = {}
    for doc_id, para_id, stmt, src in raw_rows:
        key = (doc_id, para_id)
        if key not in by:
            by[key] = _entry(doc_id, para_id, stmt, src)
        else:
            if stmt and not by[key]["statement"]:
                by[key]["statement"] = stmt
    return list(by.values()), discarded, ""


def _stream_fact_ledger(dossier: Dossier) -> tuple[list[dict], list[dict], str]:
    """一路＝fact_ledger 对撞 Fact（find_collisions → 每条 Fact 尝试落段）。"""
    collisions = find_collisions(dossier)
    if not collisions:
        return [], [], "find_collisions(dossier) 返回空（无数字对撞）"
    discarded: list[dict] = []
    by: dict[tuple[str, str], dict] = {}
    n_facts = 0
    for col in collisions:
        for f in col.facts:
            n_facts += 1
            loc = _segment_locator(dossier, f.seg_id)
            stmt = f"{col.entity or '（未指明主体）'}·{col.metric}：{f.raw}"
            if loc is None or not loc[0] or not loc[1]:
                discarded.append({
                    "reason": "Fact.seg_id 定位失败",
                    "seg_id": f.seg_id,
                    "source_id": f.source_id,
                    "stream": "fact_ledger",
                })
                continue
            key = (loc[0], loc[1])
            if key not in by:
                by[key] = _entry(loc[0], loc[1], stmt, "fact_ledger")
            # 同段多值：保留已有陈述，来源已是 fact_ledger
    # 附带原始对撞组／事实行数到 empty_reason 不用；由调用方读 len
    _ = n_facts
    return list(by.values()), discarded, ""


def _stream_fact_ledger_counts(dossier: Dossier) -> tuple[int, int]:
    """返回 (对撞组数, 对撞内 Fact 行数)，与架构师可行性读数对齐。"""
    collisions = find_collisions(dossier)
    n_facts = sum(len(c.facts) for c in collisions)
    return len(collisions), n_facts


def _stream_rejected(dossier: Dossier) -> tuple[list[dict], list[dict], str]:
    """一路＝rejected 未采信反方。

    持久化字段＝evidence_id／conclusion_id／quote／problems（无原生 segment_ids）。
    定位＝从 problems 文本「（seg_id）」解析后走 _segment_locator；
    解析不到或 locator 失败 ⇒ 丢弃（计入因定位不到丢弃）。
    """
    rows = [r for r in (dossier.rejected or []) if isinstance(r, dict)]
    if not rows:
        return [], [], "dossier.rejected 为空（本份产物无打回证据）"
    discarded: list[dict] = []
    by: dict[tuple[str, str], dict] = {}
    for r in rows:
        quote = str(r.get("quote") or "")
        probs = r.get("problems") or []
        segs: list[str] = []
        for pr in probs:
            segs.extend(_REJECTED_SEG_RE.findall(str(pr)))
        segs = list(dict.fromkeys(segs))
        if not segs:
            discarded.append({
                "reason": "problems 中无（seg_id）可解析",
                "evidence_id": r.get("evidence_id"),
                "stream": "rejected",
            })
            continue
        located = False
        for sid in segs:
            loc = _segment_locator(dossier, sid)
            if loc is None or not loc[0] or not loc[1]:
                continue
            located = True
            key = (loc[0], loc[1])
            if key not in by:
                by[key] = _entry(loc[0], loc[1], quote, "rejected")
        if not located:
            discarded.append({
                "reason": "problems 解析出的 seg_id 定位失败",
                "evidence_id": r.get("evidence_id"),
                "segs": segs,
                "stream": "rejected",
            })
    return list(by.values()), discarded, ""


def _stream_dissent(dossier: Dossier) -> tuple[list[dict], list[dict], str]:
    """一路＝dissent_conclusions()；经 evidences_of→segment_ids 定位。"""
    cons = dissent_conclusions(dossier)
    if not cons:
        return [], [], "dissent_conclusions(dossier) 为空（无 status=dissent 结论）"
    discarded: list[dict] = []
    by: dict[tuple[str, str], dict] = {}
    for con in cons:
        stmt = con.statement or ""
        evs = dossier.evidences_of(con.id)
        if not evs:
            discarded.append({
                "reason": "dissent 结论无证据",
                "conclusion_id": con.id,
                "stream": "dissent",
            })
            continue
        any_loc = False
        any_seg = False
        for ev in evs:
            for sid in ev.segment_ids:
                any_seg = True
                loc = _segment_locator(dossier, sid)
                if loc is None or not loc[0] or not loc[1]:
                    discarded.append({
                        "reason": "segment 定位失败",
                        "segment_id": sid,
                        "conclusion_id": con.id,
                        "stream": "dissent",
                    })
                    continue
                any_loc = True
                key = (loc[0], loc[1])
                if key not in by:
                    by[key] = _entry(loc[0], loc[1], stmt, "dissent")
        if not any_seg:
            discarded.append({
                "reason": "证据无 segment_ids",
                "conclusion_id": con.id,
                "stream": "dissent",
            })
        elif not any_loc:
            pass  # 已逐条记 discarded
    return list(by.values()), discarded, ""



def _wu_pair_rows(dossier: Dossier) -> tuple[list[dict], list[dict], str]:
    """一份产物 → 戊档成对条目（可定位两侧）＋丢弃。

    多值组＝find_collisions（同 (实体小写, 指标)、数值不可调和 ≥2）；
    对内全序无序配对，跳过「同段同值同时点」平凡对；
    类别＝_diff_kind 实测返回值；两侧各锚 (doc_id, para_id)。
    返回 (pairs, discarded, empty_reason)。
    """
    collisions = find_collisions(dossier)
    if not collisions:
        return [], [], "find_collisions(dossier) 返回空（无数字对撞多值组）"
    pairs: list[dict] = []
    discarded: list[dict] = []
    for col in collisions:
        located: list[tuple] = []
        for f in col.facts:
            loc = _segment_locator(dossier, f.seg_id)
            if loc is None or not loc[0] or not loc[1]:
                discarded.append({
                    "reason": "Fact.seg_id 定位失败",
                    "seg_id": f.seg_id,
                    "source_id": f.source_id,
                    "entity": col.entity,
                    "metric": col.metric,
                    "stream": "wu_coexist",
                })
                continue
            located.append((f, loc))
        for i in range(len(located)):
            for j in range(i + 1, len(located)):
                fa, la = located[i]
                fb, lb = located[j]
                # 平凡对：同段 + 同值 + 同时点 ⇒ 不是「口径并存」
                if (la == lb
                        and abs(fa.value - fb.value) <= 1e-9
                        and (fa.date or "") == (fb.date or "")):
                    continue
                kind, desc = _diff_kind(fa, fb)
                pairs.append({
                    "kind": kind,
                    "desc": desc,
                    "entity": col.entity,
                    "metric": col.metric,
                    "cross_source": fa.source_id != fb.source_id,
                    "a": {"doc_id": la[0], "para_id": la[1],
                          "raw": fa.raw, "date": fa.date,
                          "source_id": fa.source_id, "seg_id": fa.seg_id},
                    "b": {"doc_id": lb[0], "para_id": lb[1],
                          "raw": fb.raw, "date": fb.date,
                          "source_id": fb.source_id, "seg_id": fb.seg_id},
                })
    if not pairs and not discarded:
        return [], [], "多值组有对撞但未生成非平凡对"
    return pairs, discarded, ""


def map_wu(dossiers: list[Dossier],
           gold_items: list[dict]) -> dict:
    """戊档＝口径并存上界。

    覆盖口径＝可定位并集键 ∩ 金标去重段键；分母固定为金标去重键数
    （现场重算，缺金标键时仍印分子／分母整数）。
    """
    all_pairs: list[dict] = []
    discarded_total = 0
    empty_reasons: list[str] = []
    files_nonempty = 0
    files_empty = 0
    for d in dossiers:
        pairs, discarded, empty_reason = _wu_pair_rows(d)
        discarded_total += len(discarded)
        if empty_reason and not pairs:
            files_empty += 1
            empty_reasons.append(empty_reason)
        else:
            files_nonempty += 1
        all_pairs.extend(pairs)

    # 并集键（两侧）
    union: dict[tuple[str, str], dict] = {}
    kind_keys: dict[str, set[tuple[str, str]]] = {}
    kind_pairs = Counter()
    cross_pairs = Counter()
    for p in all_pairs:
        kind = str(p.get("kind") or "")
        kind_pairs[kind] += 1
        cross_pairs["cross" if p.get("cross_source") else "same"] += 1
        kind_keys.setdefault(kind, set())
        for side in ("a", "b"):
            s = p[side]
            key = (str(s["doc_id"]), str(s["para_id"]))
            if key not in union:
                union[key] = {
                    "doc_id": key[0],
                    "para_id": key[1],
                    "kinds": [kind],
                }
            else:
                if kind not in union[key]["kinds"]:
                    union[key]["kinds"].append(kind)
            kind_keys[kind].add(key)

    gold_keys = {
        (str(g["doc_id"]), str(g["para_id"]))
        for g in gold_items
        if g.get("doc_id") and g.get("para_id")
    }
    n_gold_keys = len(gold_keys)
    hit_keys = set(union.keys()) & gold_keys
    # 逐类贡献＝该类键 ∩ 金标键（一类可独立贡献；并集命中另报）
    kind_hit = {
        k: len(ks & gold_keys) for k, ks in sorted(kind_keys.items())
    }
    kind_key_n = {k: len(ks) for k, ks in sorted(kind_keys.items())}

    # 一对一 exact（对 91 条）——换算句用
    sub_facts = [{"doc_id": e["doc_id"], "para_id": e["para_id"]}
                 for e in union.values()]
    # slots 空即可；exact-only
    sub_items = [
        {"doc_id": f["doc_id"], "para_id": f["para_id"],
         "slots": ("", "", ""), "verdict_label": "", "has_our_text": False}
        for f in sub_facts
    ]
    m = two_stage_match(sub_items, gold_items, approx_available=False)

    return {
        "n_pairs": len(all_pairs),
        "n_collisions_files": files_nonempty,
        "files_empty": files_empty,
        "empty_reasons": empty_reasons,
        "discarded_total": discarded_total,
        "union_n": len(union),
        "union_facts": list(union.values()),
        "kind_pairs": dict(kind_pairs),
        "kind_keys": kind_key_n,
        "kind_hit_keys": kind_hit,
        "cross_pairs": dict(cross_pairs),
        "gold_keys": n_gold_keys,
        "hit_keys": len(hit_keys),
        "coverage": (len(hit_keys), n_gold_keys),
        "match_91": m,
        "diff_kinds_seen": sorted(kind_pairs.keys()),
        "threshold": _WU_THRESHOLD,
        "pass_threshold": len(hit_keys) >= _WU_THRESHOLD,
    }


def probe_wu_inrepo_generality() -> dict:
    """判据 b · 通用性腿：同一规则跑仓内 cases/*/out*/report.json ≥1 对。"""
    print("=" * 78)
    print("⑤′／判据 b · 戊档通用性腿（仓内一层产物；规则禁案名／专有实体／专有数字）")
    print("=" * 78)
    paths = _inrepo_reports(Path(INREPO_ROOT))
    n_pairs = 0
    n_files_with = 0
    kind_pairs = Counter()
    for p in paths:
        d = _load_dossier(p)
        pairs, _disc, _er = _wu_pair_rows(d)
        if pairs:
            n_files_with += 1
        n_pairs += len(pairs)
        for pr in pairs:
            kind_pairs[str(pr.get("kind") or "")] += 1
    ok = n_pairs >= 1
    print(f"  仓内产物份数={len(paths)} 含戊对份数={n_files_with} "
          f"戊对数={n_pairs} 逐类对={dict(kind_pairs)}")
    print(f"  通用性腿={'PASS（≥1 对）' if ok else 'FAIL（0 对＝规则被六案用词绑住，返工）'}")
    # 规则面自检：本函数／_wu_pair_rows 源码不得含官方案名
    src = Path(__file__).read_text(encoding="utf-8")
    banned = [
        "刘翔", "王虹", "吉隆口岸", "印度航空", "柬泰", "中美AI",
        "AI171", "discouraged", "泥石流",
    ]
    hits = [b for b in banned if b in src]
    # 允许出现在本打印字符串与 docstring 举例之外？禁品＝规则里不许。
    # 上面 banned 列表本身含这些字 ⇒ 只查 _wu_pair_rows / map_wu 函数体。
    import ast
    tree = ast.parse(src)
    rule_src_chunks = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in ("_wu_pair_rows", "map_wu"):
                rule_src_chunks.append(ast.get_source_segment(src, node) or "")
    rule_blob = "\n".join(rule_src_chunks)
    rule_hits = [b for b in banned if b in rule_blob]
    print(f"  规则函数体案名命中={rule_hits or '无'}")
    if rule_hits:
        ok = False
        print("  ⚠ 规则函数体出现案名／专有实体 ⇒ 通用性腿 FAIL")
    return {
        "n_files": len(paths),
        "n_files_with_pairs": n_files_with,
        "n_pairs": n_pairs,
        "kind_pairs": dict(kind_pairs),
        "ok": ok,
        "rule_banned_hits": rule_hits,
    }


def print_wu_section(wu: dict) -> None:
    """打印戊档读数（分子分母原样整数＋逐类贡献＋门槛裁决）。"""
    print()
    print("=" * 78)
    print("⑤／戊档 · 「口径并存」上界（find_collisions × _diff_kind；"
          "去重键 doc_id+para_id）")
    print("=" * 78)
    print(_WU_KIND_NOTE)
    print(f"产物非空份数={wu['n_collisions_files']} 空份={wu['files_empty']}")
    if wu["files_empty"] and wu["empty_reasons"]:
        uniq = list(dict.fromkeys(wu["empty_reasons"]))
        print("  空因样例：")
        for r in uniq[:5]:
            print(f"    · {r}")
    print(f"成对条目数（非平凡）={wu['n_pairs']}  "
          f"cross_source 拆={wu['cross_pairs']}")
    print(f"可定位并集键数={wu['union_n']}  "
          f"因定位不到丢弃 Fact 行={wu['discarded_total']}（不计入并集）")
    print(f"逐类成对：{wu['kind_pairs']}")
    print(f"逐类可定位键：{wu['kind_keys']}")
    print(f"逐类贡献（该类键 ∩ 金标去重段键）：{wu['kind_hit_keys']}")
    cov_n, cov_d = wu["coverage"]
    print(f"可定位并集覆盖 = {cov_n}/{cov_d}"
          f"  （金标去重段键；门槛 ≥{_WU_THRESHOLD}/{cov_d or _WU_GOLD_KEYS}）")
    m = wu["match_91"]
    print(f"换算（对 91 条一对一 exact）："
          f"exact={m['exact']}/{m['n_gold']} "
          f"Recall_conf={m['exact']}/{m['n_gold']}={m['Recall_conf']:.4f} "
          f"sub={m['n_sub']}")
    # 判据 g 换算句
    print()
    print(f"覆盖 {cov_n}/{cov_d} ⇒ Recall_conf＝{m['exact']}/91"
          f"＝{m['Recall_conf']:.4f}，"
          f"够不够 ≥46 档＝{'够' if m['exact'] >= 46 else '不够'}；"
          f"精度档本档不评（只量召回上界）")
    print()
    if wu["pass_threshold"]:
        print(f"门槛裁决：PASS（{cov_n}≥{_WU_THRESHOLD}）⇒ 可交架构师复放、"
              f"再决定是否发件②")
    else:
        print(f"门槛裁决：STOP（{cov_n}<{_WU_THRESHOLD}）⇒ **不许进件②**；"
              f"根因＝fact_ledger 多值段键与金标段键重叠太少"
              f"（本批并集∩金标＝{cov_n}），不是阈值问题、不许调阈值／加词表凑数")


def map_ding(dossiers: list[Dossier]) -> dict:
    """丁档＝四路并集。跨多份 report 累加后按 (doc_id, para_id) 去重。

    返回结构含逐路原始／可定位／并入新增、并集、丢弃、空因、守恒。
    """
    stream_fns = (
        ("conflicts", _stream_conflicts),
        ("fact_ledger", _stream_fact_ledger),
        ("rejected", _stream_rejected),
        ("dissent", _stream_dissent),
    )
    # 逐路累加（跨 dossier 先合并同路再去重）
    per: dict[str, dict] = {
        name: {
            "raw": 0,          # 原始条数（定位前的候选次数；fact_ledger＝Fact 行）
            "n_collisions": 0,  # 仅 fact_ledger
            "locable": [],     # list[dict] 本路可定位（路内已按 dp 去重后的跨文件再并）
            "discarded": 0,
            "empty_reasons": [],
            "files_nonempty": 0,
            "files_empty": 0,
        }
        for name, _ in stream_fns
    }
    for d in dossiers:
        for name, fn in stream_fns:
            if name == "fact_ledger":
                n_col, n_fact = _stream_fact_ledger_counts(d)
                per[name]["n_collisions"] += n_col
                per[name]["raw"] += n_fact
            entries, discarded, empty_reason = fn(d)
            if name != "fact_ledger":
                # conflicts／rejected／dissent：原始＝本份尝试条数
                # conflicts：用 discarded+entries 近似；更准＝调用前计数
                if name == "conflicts":
                    # 重新按对侧证据段计原始（含定位失败）
                    pairs = [p for p in (d.conflicts or []) if isinstance(p, dict)]
                    raw_n = 0
                    for pair in pairs:
                        a_id, b_id, _w, sides = _pair_sides(pair)
                        if sides is None:
                            sides = [a_id, b_id] if a_id and b_id else []
                        for cid in sides:
                            evs = d.evidences_of(cid) if cid else []
                            n_seg = sum(len(ev.segment_ids) for ev in evs)
                            raw_n += n_seg if n_seg else 1  # 无证据也算 1 次原始尝试
                    per[name]["raw"] += raw_n
                elif name == "rejected":
                    per[name]["raw"] += len([r for r in (d.rejected or []) if isinstance(r, dict)])
                elif name == "dissent":
                    cons = dissent_conclusions(d)
                    raw_n = 0
                    for con in cons:
                        evs = d.evidences_of(con.id)
                        n_seg = sum(len(ev.segment_ids) for ev in evs)
                        raw_n += n_seg if n_seg else 1
                    per[name]["raw"] += raw_n
            per[name]["discarded"] += len(discarded)
            if empty_reason:
                per[name]["files_empty"] += 1
                per[name]["empty_reasons"].append(empty_reason)
            else:
                per[name]["files_nonempty"] += 1
            # 跨文件并入本路 locable（按 dp 去重）
            bucket: dict[tuple[str, str], dict] = {
                (e["doc_id"], e["para_id"]): e for e in per[name]["locable"]
            }
            for e in entries:
                key = (e["doc_id"], e["para_id"])
                if key not in bucket:
                    bucket[key] = dict(e)
                    bucket[key]["sources"] = list(e["sources"])
                else:
                    for s in e["sources"]:
                        if s not in bucket[key]["sources"]:
                            bucket[key]["sources"].append(s)
                    if e["statement"] and not bucket[key]["statement"]:
                        bucket[key]["statement"] = e["statement"]
            per[name]["locable"] = list(bucket.values())

    # 并集：按流顺序并入，计「并入后新增」
    union: dict[tuple[str, str], dict] = {}
    order = [name for name, _ in stream_fns]
    added_by_stream: dict[str, int] = {}
    for name in order:
        added = 0
        for e in per[name]["locable"]:
            key = (e["doc_id"], e["para_id"])
            if key not in union:
                union[key] = {
                    "doc_id": e["doc_id"],
                    "para_id": e["para_id"],
                    "statement": e["statement"],
                    "sources": list(e["sources"]),
                }
                added += 1
            else:
                for s in e["sources"]:
                    if s not in union[key]["sources"]:
                        union[key]["sources"].append(s)
                if e["statement"] and not union[key]["statement"]:
                    union[key]["statement"] = e["statement"]
        added_by_stream[name] = added

    locable_counts = {name: len(per[name]["locable"]) for name in order}
    n_union = len(union)
    max_loc = max(locable_counts.values()) if locable_counts else 0
    sum_loc = sum(locable_counts.values())
    if not (max_loc <= n_union <= sum_loc):
        raise RuntimeError(
            f"丁档守恒失败：max(可定位)={max_loc} 并集={n_union} "
            f"Σ(可定位)={sum_loc}；逐路={locable_counts}"
        )

    discarded_total = sum(per[name]["discarded"] for name in order)
    return {
        "streams": {
            name: {
                "raw": per[name]["raw"],
                "n_collisions": per[name]["n_collisions"],
                "n_locable": locable_counts[name],
                "added_to_union": added_by_stream[name],
                "discarded": per[name]["discarded"],
                "files_nonempty": per[name]["files_nonempty"],
                "files_empty": per[name]["files_empty"],
                "empty_reasons": per[name]["empty_reasons"],
                "layer_note": _DING_LAYER_NOTE[name],
            }
            for name in order
        },
        "union_n": n_union,
        "union_facts": [
            {"doc_id": e["doc_id"], "para_id": e["para_id"]}
            for e in union.values()
        ],
        "discarded_total": discarded_total,
        "conservation": {
            "max_locable": max_loc,
            "union": n_union,
            "sum_locable": sum_loc,
            "ok": True,
        },
        "order": order,
    }


def _print_recompute_cmd() -> None:
    cmd = (
        f"OFFICIAL_CASES={OFFICIAL_CASES} OFFICIAL_RUN={OFFICIAL_RUN} "
        f"INREPO_ROOT={INREPO_ROOT} "
        f"{sys.executable} scripts/probe_conflict_coverage.py"
    )
    print()
    print("复算命令（原样粘贴）：")
    print(cmd)


def probe_inrepo_jia() -> dict:
    print("=" * 78)
    print("①′／判据 d · 仓内一层产物甲档自检（cases/*/out*/report.json）")
    print("=" * 78)
    paths = _inrepo_reports(Path(INREPO_ROOT))
    tot = Counter()
    for p in paths:
        d = _load_dossier(p)
        m = map_conflicts(d, "jia")
        tot["n_files"] += 1
        tot["n_pairs"] += m["n_pairs"]
        tot["entered_pairs"] += m["entered_pairs"]
        tot["n_facts"] += m["n_facts"]
        tot["skipped_tie"] += m["skipped_tie"]
        tot["skipped_noloc"] += m["skipped_noloc"]
        if m["n_pairs"] or m["skipped_tie"] or m["n_facts"]:
            rel = p.relative_to(REPO) if str(p).startswith(str(REPO)) else p
            print(f"  {rel}: 对={m['n_pairs']} 进对={m['entered_pairs']} "
                  f"事实行={m['n_facts']} 平局跳过={m['skipped_tie']} "
                  f"无段落={m['skipped_noloc']}")
    print(f"  合计 files={tot['n_files']} 对={tot['n_pairs']} "
          f"进对={tot['entered_pairs']} 事实行={tot['n_facts']} "
          f"平局跳过={tot['skipped_tie']} 无段落={tot['skipped_noloc']}")
    print(f"  判据 d 锚点＝对/进对/平局丢弃 → "
          f"{tot['n_pairs']}/{tot['entered_pairs']}/{tot['skipped_tie']} "
          f"（期望 44/39/5）")
    return dict(tot)


def probe_six_cases() -> dict:
    print("=" * 78)
    print("①②③④ · 六案：金标／甲／乙／丙／丁 ＋ 两阶段 Precision_conf／Recall_conf")
    print("=" * 78)
    print(_APPROX_NOTE)

    cases_root = _require_dir(OFFICIAL_CASES, "官方样例集")
    run_root = _require_dir(OFFICIAL_RUN, "六案跑产物")
    case_dirs = _official_case_dirs(cases_root)
    official_names = {c.name for c in case_dirs}
    run_dirs = _run_case_dirs(run_root, official_names)

    print(f"OFFICIAL_CASES={cases_root}")
    print(f"OFFICIAL_RUN={run_root}")
    print(f"官方案卷数={len(case_dirs)} 跑产物案卷数={len(run_dirs)}")

    # verdict_label 金标分布（复量前提 2）
    vl = Counter()
    gold_total = 0
    for c in case_dirs:
        for item in _gold_conf_items(c):
            gold_total += 1
            if item["verdict_label"]:
                vl[item["verdict_label"]] += 1
    print(f"金标 conflicting_facts 合计={gold_total}  verdict_label={dict(vl)}")

    header = (f"{'案例':<28}{'金标':>6}{'甲对':>6}{'甲进对':>6}{'甲行':>6}"
              f"{'甲平局':>6}{'甲无段':>6}{'乙行':>6}{'丙行':>6}")
    print(header)
    print("-" * len(header))

    sum_gold = 0
    sum_jia = Counter()
    sum_yi_facts = 0
    sum_bing_facts = 0
    all_sub_jia: list[dict] = []
    all_sub_yi: list[dict] = []
    all_sub_bing: list[dict] = []
    all_gold: list[dict] = []
    per_case_rows = []

    run_by_name = {d.name: d for d in run_dirs}
    all_dossiers: list[Dossier] = []
    for c in case_dirs:
        gold_items = _gold_conf_items(c)
        n_gold = len(gold_items)
        sum_gold += n_gold
        all_gold.extend(gold_items)

        jia = Counter()
        yi_facts: list[dict] = []
        bing_facts: list[dict] = []
        sub_j: list[dict] = []
        text_by_dp: dict[tuple[str, str], str] = {}
        rd = run_by_name.get(c.name)
        reports = sorted((rd / "questions").glob("*/report.json")) if rd else []
        for rp in reports:
            d = _load_dossier(rp)
            all_dossiers.append(d)
            _merge_text_by_dp(text_by_dp, _our_text_by_dp(d))
            mj = map_conflicts(d, "jia")
            my = map_conflicts(d, "yi")
            mb = map_conflicts(d, "bing")
            jia["n_pairs"] += mj["n_pairs"]
            jia["entered_pairs"] += mj["entered_pairs"]
            jia["n_facts"] += mj["n_facts"]
            jia["skipped_tie"] += mj["skipped_tie"]
            jia["skipped_noloc"] += mj["skipped_noloc"]
            sub_j.extend(mj["facts"])
            yi_facts.extend(my["facts"])
            bing_facts.extend(mb["facts"])

        sum_jia.update(jia)
        sum_yi_facts += len(yi_facts)
        sum_bing_facts += len(bing_facts)
        all_sub_jia.extend(_submitted_items(sub_j, text_by_dp))
        all_sub_yi.extend(_submitted_items(yi_facts, text_by_dp))
        all_sub_bing.extend(_submitted_items(bing_facts, text_by_dp))

        name = c.name[:26]
        print(f"{name:<28}{n_gold:>6}{jia['n_pairs']:>6}{jia['entered_pairs']:>6}"
              f"{jia['n_facts']:>6}{jia['skipped_tie']:>6}{jia['skipped_noloc']:>6}"
              f"{len(yi_facts):>6}{len(bing_facts):>6}")
        per_case_rows.append({
            "case": c.name,
            "gold": n_gold,
            "jia_pairs": jia["n_pairs"],
            "jia_entered": jia["entered_pairs"],
            "jia_facts": jia["n_facts"],
            "jia_tie": jia["skipped_tie"],
            "jia_noloc": jia["skipped_noloc"],
            "yi_facts": len(yi_facts),
            "bing_facts": len(bing_facts),
            "n_reports": len(reports),
        })

    print("-" * len(header))
    print(f"{'合计':<28}{sum_gold:>6}{sum_jia['n_pairs']:>6}{sum_jia['entered_pairs']:>6}"
          f"{sum_jia['n_facts']:>6}{sum_jia['skipped_tie']:>6}{sum_jia['skipped_noloc']:>6}"
          f"{sum_yi_facts:>6}{sum_bing_facts:>6}")

    gap = sum_gold - sum_jia["n_facts"]
    print()
    print(f"91 与现行甲档事实行之差：金标 {sum_gold} − 甲行 {sum_jia['n_facts']}＝{gap}")
    print(f"  跳过桶拆解（甲）＝平局跳过对 {sum_jia['skipped_tie']} ＋ 无段落跳过对 "
          f"{sum_jia['skipped_noloc']}；"
          f"内部冲突对仅 {sum_jia['n_pairs']}（远小于金标 91）⇒ "
          f"主缺口在检出侧（内部根本没配对），其次才是导出平局丢弃。")
    print(f"  乙／丙事实行＝{sum_yi_facts}/{sum_bing_facts}（丙＝乙＋verdict_label 形状，"
          f"占位={_VERDICT_SHAPE_PLACEHOLDER}；条数应相等）")
    if sum_yi_facts != sum_bing_facts:
        print("  ⚠ 乙／丙条数不一致——形状附加不该改条数")
    if all_sub_bing:
        shape = {k: all_sub_bing[0].get(k) for k in ("doc_id", "para_id", "verdict_label")}
        print(f"  丙形状样例＝{json.dumps(shape, ensure_ascii=False)}")

    print()
    print("两阶段匹配（按映射档分别算；命中＝exact ∪ approx，一对一消耗）")
    print("我方槽位来源＝evidences[].quote／sources[].segments[].text 正则年份·数字"
          "（不查金标 argument）；金标槽位仍读 argument；两口径不可比⇒approx=not_available")
    results = {}
    for label, sub in (("甲", all_sub_jia), ("乙", all_sub_yi), ("丙", all_sub_bing)):
        m = two_stage_match(sub, all_gold)
        results[label] = m
    any_na = any(not m.get("approx_available") for m in results.values())
    any_ok = any(m.get("approx_available") for m in results.values())
    if any_ok:
        print(_APPROX_NOTE)
    if any_na:
        print(_APPROX_NA_NOTE)
    for label, m in results.items():
        if m.get("approx_available"):
            print(f"  {label}: sub={m['n_sub']} gold={m['n_gold']} "
                  f"exact={m['exact']} approx={m['approx']} hits={m['hits']} "
                  f"Precision_conf={m['Precision_conf']:.4f} "
                  f"Recall_conf={m['Recall_conf']:.4f}")
        else:
            print(f"  {label}: sub={m['n_sub']} gold={m['n_gold']} "
                  f"exact={m['exact']} approx=not_available "
                  f"hits={m['hits']}(exact-only) "
                  f"Precision_conf={m['Precision_conf']:.4f} "
                  f"Recall_conf={m['Recall_conf']:.4f}")


    # ---- 丁档：四路并集上界 ----
    print()
    print("=" * 78)
    print("④／丁档 · 候选条目全集上界（四路并集；去重键 doc_id+para_id）")
    print("=" * 78)
    print(_DING_OFFICIAL_STEP2)
    print("approx=not_available；" + _APPROX_NA_NOTE)
    try:
        ding = map_ding(all_dossiers)
    except RuntimeError as exc:
        print(f"丁档守恒自检失败：{exc}")
        raise SystemExit(2) from exc

    print(f"产物份数={len(all_dossiers)}（六案 questions/*/report.json）")
    print(f"{'来源':<14}{'原始':>8}{'可定位':>8}{'并入新增':>8}{'丢弃':>8}")
    print("-" * 46)
    for name in ding["order"]:
        st = ding["streams"][name]
        extra = ""
        if name == "fact_ledger":
            extra = f"  （对撞组={st['n_collisions']}）"
        print(f"{name:<14}{st['raw']:>8}{st['n_locable']:>8}"
              f"{st['added_to_union']:>8}{st['discarded']:>8}{extra}")
        if st["n_locable"] == 0:
            reasons = st["empty_reasons"]
            if reasons:
                # 去重原因后打印
                uniq = list(dict.fromkeys(reasons))
                print(f"  └ 空因（{st['files_empty']} 份空／"
                      f"{st['files_nonempty']} 份非空）：")
                for r in uniq[:5]:
                    print(f"     · {r}")
            else:
                print("  └ 空因：可定位条数为 0（原始候选均因定位不到被丢弃）")
    print("-" * 46)
    print(f"{'并集':<14}{ding['union_n']:>8}")
    print(f"因定位不到丢弃 {ding['discarded_total']} 条"
          f"（四路 discarded 合计；不计入上界）")
    cons = ding["conservation"]
    print(f"守恒：max(可定位)={cons['max_locable']} ≤ 并集={cons['union']} "
          f"≤ Σ(可定位)={cons['sum_locable']} → OK")

    print()
    print("逐路「放行需要动哪一层」（只描述、不改 app/）：")
    for name in ding["order"]:
        print(f"  · {ding['streams'][name]['layer_note']}")

    # 与金标 exact-only（合并六案我方原文供槽位；approx 仍 not_available）
    text_all: dict[tuple[str, str], str] = {}
    for d in all_dossiers:
        _merge_text_by_dp(text_all, _our_text_by_dp(d))
    ding_sub = _submitted_items(ding["union_facts"], text_all)
    m_ding = two_stage_match(ding_sub, all_gold, approx_available=False)
    results["丁"] = m_ding
    print()
    print("丁档 vs 金标（只算第一步 doc_id+para_id 精确匹配；"
          "第二步 approx=not_available）")
    print(_DING_OFFICIAL_STEP2)
    # 分子／分母原样整数
    p_num, p_den = m_ding["exact"], m_ding["n_sub"]
    r_num, r_den = m_ding["exact"], m_ding["n_gold"]
    print(f"  丁: sub={m_ding['n_sub']} gold={m_ding['n_gold']} "
          f"exact={m_ding['exact']} approx=not_available "
          f"hits={m_ding['hits']}(exact-only)")
    print(f"  Precision_conf = {p_num}/{p_den}"
          f" = {m_ding['Precision_conf']:.4f}")
    print(f"  Recall_conf    = {r_num}/{r_den}"
          f" = {m_ding['Recall_conf']:.4f}")

    # 判据 g：硬结论句
    print()
    if m_ding["exact"] < 46:
        print("结论：改导出到不了 Recall_conf 最低档 3 分＝出路只剩检出侧"
              "（判定变更、须用户点头）")
    else:
        print("结论：导出侧扩面可到最低档，且必须同步《字段说明》")

    # ---- 戊档：口径并存上界（C-44 件①）----
    wu = map_wu(all_dossiers, all_gold)
    print_wu_section(wu)
    results["戊"] = {
        "n_sub": wu["union_n"],
        "n_gold": wu["match_91"]["n_gold"],
        "exact": wu["match_91"]["exact"],
        "hits": wu["match_91"]["hits"],
        "Precision_conf": wu["match_91"]["Precision_conf"],
        "Recall_conf": wu["match_91"]["Recall_conf"],
        "approx_available": False,
        "coverage_keys": wu["coverage"],
        "kind_hit_keys": wu["kind_hit_keys"],
        "discarded_total": wu["discarded_total"],
        "pass_threshold": wu["pass_threshold"],
    }

    return {
        "gold_total": sum_gold,
        "verdict_label": dict(vl),
        "jia": dict(sum_jia),
        "yi_facts": sum_yi_facts,
        "bing_facts": sum_bing_facts,
        "per_case": per_case_rows,
        "match": results,
        "ding": ding,
        "wu": wu,
    }


def probe_verdict_label_zero_hits() -> None:
    print("=" * 78)
    print("前提 2 附 · verdict_label 在 app/＋scripts/ 命中数（本探针文件自身除外）")
    print("=" * 78)
    hits = []
    for base in (REPO / "app", REPO / "scripts"):
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if p.resolve() == Path(__file__).resolve():
                continue
            if p.suffix not in {".py", ".md", ".json", ".txt"}:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "verdict_label" in text:
                hits.append(str(p.relative_to(REPO)))
    print(f"  命中文件数={len(hits)}")
    for h in hits[:20]:
        print(f"    {h}")


def main() -> None:
    # 反向腿：任何关键目录不存在或为空都 exit 2（在真正读数之前）
    _require_dir(OFFICIAL_CASES, "官方样例集")
    _official_case_dirs(Path(OFFICIAL_CASES))
    _require_dir(OFFICIAL_RUN, "六案跑产物")
    _run_case_dirs(Path(OFFICIAL_RUN), set())  # 先按非空产物验；六案名对齐在 probe_six 再筛

    print(f"样例集根: {OFFICIAL_CASES}")
    print(f"六案产物根: {OFFICIAL_RUN}")
    print(f"仓内产物根: {INREPO_ROOT}")

    inrepo = probe_inrepo_jia()
    six = probe_six_cases()
    wu_gen = probe_wu_inrepo_generality()
    probe_verdict_label_zero_hits()
    _print_recompute_cmd()

    print()
    print("=" * 78)
    print("摘要")
    print("=" * 78)
    print(f"仓内甲档: {inrepo['n_files']} 份／"
          f"{inrepo['n_pairs']} 对／{inrepo['entered_pairs']} 进／"
          f"{inrepo['skipped_tie']} 平局丢弃／事实行 {inrepo['n_facts']}")
    print(f"六案金标={six['gold_total']} 甲行={six['jia'].get('n_facts', 0)} "
          f"乙行={six['yi_facts']} 丙行={six['bing_facts']}")
    for label, m in six["match"].items():
        if m.get("approx_available"):
            ap = m["approx"]
            tail = f"(exact={m['exact']} approx={ap})"
            print(f"  {label} Precision_conf={m['Precision_conf']:.4f} "
                  f"Recall_conf={m['Recall_conf']:.4f} {tail}")
        else:
            # 丁档强制打印分子／分母整数；甲乙丙保持原形兼打整数
            p_num, p_den = m["exact"], m["n_sub"]
            r_num, r_den = m["exact"], m["n_gold"]
            print(f"  {label} Precision_conf={p_num}/{p_den}"
                  f"={m['Precision_conf']:.4f} "
                  f"Recall_conf={r_num}/{r_den}"
                  f"={m['Recall_conf']:.4f} "
                  f"(exact={m['exact']} approx=not_available；exact-only)")
    if any(not m.get("approx_available") for m in six["match"].values()):
        print(_APPROX_NA_NOTE)
        print(_DING_OFFICIAL_STEP2)
    else:
        print(_APPROX_NOTE)
    ding = six.get("ding") or {}
    if ding:
        print(f"丁并集={ding.get('union_n')} 丢弃={ding.get('discarded_total')} "
              f"守恒={ding.get('conservation')}")
        m = six["match"].get("丁") or {}
        if m:
            if m.get("exact", 0) < 46:
                print("结论：改导出到不了 Recall_conf 最低档 3 分＝出路只剩检出侧"
                      "（判定变更、须用户点头）")
            else:
                print("结论：导出侧扩面可到最低档，且必须同步《字段说明》")
    wu = six.get("wu") or {}
    if wu:
        cov_n, cov_d = wu["coverage"]
        m91 = wu["match_91"]
        print(f"戊并集键={wu.get('union_n')} 覆盖={cov_n}/{cov_d} "
              f"丢弃={wu.get('discarded_total')} "
              f"逐类贡献={wu.get('kind_hit_keys')} "
              f"通用性腿={'PASS' if wu_gen.get('ok') else 'FAIL'}"
              f"（仓内对={wu_gen.get('n_pairs')}）")
        print(f"覆盖 {cov_n}/{cov_d} ⇒ Recall_conf＝{m91['exact']}/91"
              f"＝{m91['Recall_conf']:.4f}，"
              f"够不够 ≥46 档＝{'够' if m91['exact'] >= 46 else '不够'}")
        if wu.get("pass_threshold"):
            print("戊门槛：PASS ≥40／78 ⇒ 可交架构师复放件①")
        else:
            print("戊门槛：STOP <40／78 ⇒ 不许发件②、不许调阈值凑数")


if __name__ == "__main__":
    main()
