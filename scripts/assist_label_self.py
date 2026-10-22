# -*- coding: utf-8 -*-
"""#38 第一步＝**模型辅助标注**（只出草稿，**不入库**；最终 label 必须人签）。

为什么要它：C-24 的校准曲线要 `对／部分／错` 三种人签 label，而候选清单里 256 行
`label` 全空。用户 2026-10-22 拍＝**甲**＝我用**本机 Ollama 14B** 先标一遍、
**用户抽检签字**后才是真标定集。⇒ 本脚本产的是**草稿**，一律落 `/tmp/s4runs/`，
**绝不写 `calibration/`**（未经人签的 label 不入库）。

r2：引文喂足＝证据 quote + 所指 segment；口径收紧；定位放宽；出抽检表。
r3（再退回）：抽检表「引文」加长到可见关键句；「对」再收紧（判断词／多主体／sure
机械纠偏）；表列拆开理由与引文，避免截到看不出对错。

安全闸（照 `measure_s4_gates.lock_local`，不发一次请求就退出）：
网关必须硬钉本机 Ollama＋假密钥 `ollama`＋单模型链，任何不满足直接 SystemExit。

一条防编造的机械核：模型给的「支撑片段」必须在喂给它的那几条逐字引文里**逐字可定位**，
定位不到 ⇒ 这行 `flag="支撑片段不可定位"`、label 记空，**不计入**（宁缺毋标）。

用法：
    .venv/bin/python scripts/assist_label_self.py --limit 60
    .venv/bin/python scripts/assist_label_self.py --limit 0   # 全量 256
    .venv/bin/python scripts/assist_label_self.py --help
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = Path("/tmp/s4runs")
ALLOWED = ("对", "部分", "错")
# r2：14B 窗约 40k，引文加足到 ~4500 字（quote + 所指段落）
MAX_QUOTES_CHARS = 4500
PER_SEG_CHARS = 900          # 单段最多截取（防一篇技术方案占满）
SHEET_DUI_PER_BAND = 5
SHEET_FLAGGED = 20
SHEET_SEED = 38              # #38 可复现抽检

LABEL_SYSTEM = (
    "你在为一条「置信度校准」的标定集做**辅助标注**，最终由人签字。"
    "只依据我给你的逐字引文判断这条结论，不使用你自己的知识、不补全没给的数字。\n"
    "默认偏严：拿不准就标「部分」，只有铁证才标「对」。\n"
    "三档口径（必须逐字选一个）：\n"
    "对＝结论里**每一条**主体／指标／程度／时点／判断都能被引文**直接原词**支撑，且无矛盾；\n"
    "部分＝方向对，但多断言只撑住一部分，或判断词（风险／无风险／可信／缺乏第三方等）"
    "在引文里没有原词、只是你推断出来的；\n"
    "错＝无支撑、直接矛盾、或主体（客户／项目）与引文不一致"
    "（含把「未提及」说成「已发生」、客户张冠李戴、把「无冗余」当成「无流失」）。\n"
    "硬规则：\n"
    "1) 多客户／多风险点：缺任一主体或任一判断的原词支撑 ⇒ 不得「对」；\n"
    "2) 引文只有数字／事实、没有结论里的判断词 ⇒ 该判断不算被支撑 ⇒ 部分或错；\n"
    "3) 近义不等同：无冗余≠无流失，付款暂停≠已定性为回款风险（除非引文写了风险）；\n"
    "4) why 写「未提／缺乏／无法／推断」却标「对」⇒ 改部分或错；\n"
    "5) quote 从引文逐字抄**足够长的关键句**（建议 40–120 字），禁 /no_think、禁自造、禁 [n] 前缀；\n"
    "6) sure＝只有真正铁证才 true，否则 false（false 时不要标对）。\n"
    "只输出一个 JSON 对象，不解释、不额外文本：\n"
    '{"label":"对|部分|错","why":"不超过 50 字的中文理由",'
    '"quote":"从给定引文逐字抄的支撑关键句（找不到就写空串）",'
    '"sure":true}'
)

_THINK_RE = re.compile(
    r"(?is)</?think>|</?reasoning>|/no_think|<\|?/?think\|?>"
)


def _locks() -> str:
    """复用测量脚本里那把闸（规则只许一条，别自己再写一份）。"""
    from scripts.measure_s4_gates import lock_local

    return lock_local()


def _strip_think(s: str) -> str:
    s = _THINK_RE.sub(" ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _find_conclusion(case: str, cid: str) -> dict[str, Any] | None:
    """按候选清单同一批产物树取回结论原文，并**加足**引文＝quote + 所指 segment。"""
    for rp in sorted((ROOT / case).glob("out*/report.json")):
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        by_id = {str(c.get("id")): c for c in (data.get("conclusions") or [])}
        con = by_id.get(cid)
        if not con:
            continue
        ev_by_id = {str(e.get("id")): e for e in (data.get("evidences") or [])}
        seg_by_id: dict[str, str] = {}
        for src in (data.get("sources") or []):
            for seg in (src.get("segments") or []):
                sid = str(seg.get("id") or "")
                text = _strip_think(str(seg.get("text") or ""))
                if sid and text:
                    seg_by_id[sid] = text

        pieces: list[str] = []          # 喂给模型的文本块
        seen_norm: set[str] = set()

        def _add(block: str) -> None:
            b = _strip_think(block)
            if len(b) < 4:
                return
            key = _norm(b)[:80]
            if key in seen_norm:
                return
            seen_norm.add(key)
            pieces.append(b)

        for eid in (con.get("evidence_ids") or []):
            ev = ev_by_id.get(str(eid)) or {}
            q = str(ev.get("quote") or "").strip()
            if q:
                _add(q)
            for sid in (ev.get("segment_ids") or []):
                text = seg_by_id.get(str(sid)) or ""
                if not text:
                    continue
                # 优先：quote 在段内则取 quote 前后窗口；否则段首截断
                if q and q[:20] in text:
                    i = text.index(q[:20])
                    lo = max(0, i - 200)
                    hi = min(len(text), i + max(len(q), 200) + 400)
                    _add(text[lo:hi])
                else:
                    _add(text[:PER_SEG_CHARS])

        # 预算裁剪：整块保留，超了就停（不再半截切断关键句）
        total = 0
        kept: list[str] = []
        dropped = 0
        for p in pieces:
            if total + len(p) > MAX_QUOTES_CHARS:
                dropped += 1
                continue
            kept.append(p)
            total += len(p)
        return {"question": str(data.get("question") or ""),
                "statement": str(con.get("statement") or ""),
                "status": str(con.get("status") or ""),
                "confidence": con.get("confidence"),
                "quotes": kept, "n_quotes": len(pieces),
                "dropped_quotes": dropped,
                "report": str(rp)}
    return None


def _norm(s: str) -> str:
    """去 Markdown 强调、编号前缀与空白后的比对文本。"""
    s = re.sub(r"^\s*\[\d+\]\s*", "", s or "")
    return re.sub(r"[\s\*_`#\|｜\-–—…·.,，。；;:：、()（）\[\]【】<>\"'“”‘’]+", "", s).lower()


def _unlocatable(quote: str, quotes: list[str]) -> str:
    """模型抄的支撑片段须在给定引文里可定位；返回第一个失败片段，全过返回空串。"""
    quote = _strip_think(quote)
    # 去掉模型爱加的 [1] 前缀
    quote = re.sub(r"^\s*\[\d+\]\s*", "", quote)
    normed = [_norm(q) for q in quotes if _norm(q)]
    if not normed:
        return quote[:24] or "空引文"
    for frag in re.split(r"[|｜\n]+|\.{3}|…{1,}", quote):
        f = _norm(frag)
        if len(f) < 6:
            continue
        if any(f in n or n in f for n in normed):
            continue
        # 再试：frag 的前 12／后 12 字（模型偶发拼接两段）
        if len(f) >= 12 and any(f[:12] in n or f[-12:] in n for n in normed):
            continue
        return frag[:24]
    return ""


def _maybe_demote(label: str, why: str, statement: str, quote: str,
                 fed: list[str], sure: bool) -> tuple[str, str]:
    """机械纠偏：凡「对」须过闸；过不了 → 部分（宁多部分）。"""
    if label != "对":
        return label, ""
    w = why or ""
    if not sure:
        return "部分", "纠偏:sure=false不得标对"
    if re.search(r"未提|未提及|缺乏|无法判断|不完整|只支撑|仅支撑|没有提到|未明确|推断|近义", w):
        return "部分", "纠偏:why承认缺口不得标对"
    fed_blob = "".join(fed or []) + (quote or "")
    # 案卷引文多用真名（某地产集团），结论用客户B；两边都认
    _alias = {
        "客户A": ("客户A", "股份制商业银行"),
        "客户B": ("客户B", "地产集团"),
        "客户C": ("客户C", "券商"),
        "客户D": ("客户D", "国有大行", "某国有大行"),
        "客户E": ("客户E", "商业地产运营商"),
        "客户F": ("客户F", "电子科技"),
    }
    customers = set(re.findall(r"客户[A-F]", statement or ""))
    if len(customers) >= 2:
        def _hit(c: str) -> bool:
            return any(a in fed_blob for a in _alias.get(c, (c,)))
        missing = sorted(c for c in customers if not _hit(c))
        if missing:
            return "部分", f"纠偏:缺主体{','.join(missing)}"
    # 判断词：结论有、整段喂入引文无 → 降级（近义不算）
    checks = [
        (r"无(?:延期)?风险|不存在.{0,6}风险", r"无(?:延期)?风险|不存在.{0,6}风险|风险.?低"),
        (r"存在.{0,8}风险|有.{0,6}风险", r"风险"),
        (r"缺乏独立第三方|无第三方|未经第三方", r"第三方"),
        (r"无人员流失|不存在人员流失|人员流失风险", r"流失|离职"),
        (r"无坏账|不存在坏账|坏账风险", r"坏账"),
        (r"可信|不可信", r"可信|验证|确认"),
    ]
    for need_pat, support_pat in checks:
        if re.search(need_pat, statement or ""):
            if not re.search(support_pat, fed_blob):
                return "部分", "纠偏:判断词无原文支撑"
    # 「无人员冗余」撑不起「无人员流失」
    if re.search(r"流失", statement or "") and re.search(r"冗余", quote or "") \
            and not re.search(r"流失|离职", fed_blob):
        return "部分", "纠偏:冗余≠流失"
    return label, ""


def _display_quote(model_quote: str, fed: list[str]) -> str:
    """抽检表展示用：优先模型 quote；过短则换喂入引文里含该片段的整句窗口。"""
    mq = (model_quote or "").strip()
    if len(mq) >= 60:
        return mq[:180]
    needle = _norm(mq)[:16] if mq else ""
    for block in fed or []:
        if needle and needle in _norm(block):
            # 取含针的窗口
            raw = block
            # 简易：若能定位原文短句
            for frag in re.split(r"[。；;\n]", raw):
                if needle and needle in _norm(frag) and len(frag.strip()) >= 20:
                    return frag.strip()[:180]
            return raw[:180]
    if mq:
        return mq[:180]
    return ((fed or [""])[0][:180] if fed else "")


def _label_one(client, model: str, rec: dict[str, Any]) -> dict[str, Any]:
    lines = [f"[{i + 1}] {q}" for i, q in enumerate(rec["quotes"])]
    user = (f"研判议题：{rec['question']}\n\n待标结论：{rec['statement']}\n\n"
            "逐字引文（唯一可用依据；含证据原句与所指段落）：\n"
            + ("\n".join(lines) or "（案卷里没有给它任何引文）"))
    t0 = time.perf_counter()
    try:
        from app.agents.base import extract_json

        resp = client.chat(model, [{"role": "system", "content": LABEL_SYSTEM},
                                   {"role": "user", "content": user}], json_mode=True)
        data = extract_json(resp.content)
        el = time.perf_counter() - t0
        label = str(data.get("label") or "").strip()
        quote = _strip_think(str(data.get("quote") or "").strip())
        why = str(data.get("why") or "")[:80]
        flag = ""
        if label not in ALLOWED:
            flag = f"label 越界({label})"
        if label in ALLOWED and quote:
            bad = _unlocatable(quote, rec["quotes"])
            if bad:
                flag = f"支撑片段不可定位({bad})"
        if label in ALLOWED and not quote:
            flag = flag or "无支撑片段"
        sure = bool(data.get("sure"))
        note = ""
        if label in ALLOWED and not flag:
            label, note = _maybe_demote(label, why, rec["statement"], quote,
                                       rec["quotes"], sure)
        disp = _display_quote(quote, rec["quotes"])
        return {"model_label": label if not flag else "",
                "why": why, "quote": quote[:240], "display_quote": disp,
                "sure": sure,
                "flag": flag or note, "elapsed_s": round(el, 2),
                "tokens": getattr(resp, "total_tokens", None),
                "n_quote_chars": sum(len(q) for q in rec["quotes"])}
    except Exception as exc:                       # 标注失败要留痕，不许当成「错」
        return {"model_label": "", "why": "", "quote": "", "display_quote": "",
                "sure": False,
                "flag": f"调用失败({type(exc).__name__})",
                "elapsed_s": round(time.perf_counter() - t0, 2), "tokens": None,
                "n_quote_chars": sum(len(q) for q in rec["quotes"])}


def _band(score: Any) -> str:
    s = float(score or 0)
    for lo, hi, lab in ((0.0, 0.2, "0.0–0.2"), (0.2, 0.4, "0.2–0.4"),
                        (0.4, 0.6, "0.4–0.6"), (0.6, 0.8, "0.6–0.8"),
                        (0.8, 1.01, "0.8–1.0")):
        if lo <= s < hi:
            return lab
    return "0.8–1.0"


def _build_sheet(drafts: list[dict[str, Any]], out_dir: Path, counts: dict[str, int],
                 n_flagged: int) -> tuple[int, Path]:
    """抽检表＝全部部分／错 + 每箱若干「对」+ 被旗样本；结构同 r1 人签表。"""
    part_wrong = [d for d in drafts if d.get("model_label") in ("部分", "错")]
    dui = [d for d in drafts if d.get("model_label") == "对"]
    flagged = [d for d in drafts if not d.get("model_label")]

    rng = random.Random(SHEET_SEED)
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _take(row: dict[str, Any]) -> None:
        cid = row["conclusion_id"]
        if cid in seen:
            return
        seen.add(cid)
        picked.append(row)

    for d in part_wrong:
        _take(d)

    by_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in dui:
        by_band[_band(d.get("score"))].append(d)
    for lab in ("0.0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1.0"):
        pool = by_band.get(lab) or []
        if not pool:
            continue
        pool = pool[:]
        rng.shuffle(pool)
        for d in pool[:SHEET_DUI_PER_BAND]:
            _take(d)

    fpool = flagged[:]
    rng.shuffle(fpool)
    for d in fpool[:SHEET_FLAGGED]:
        _take(d)

    n_labeled = sum(counts.values())
    # r3：理由／引文分列；引文展示 ≥120 字关键句，避免截到看不出对错
    head = (
        f"# 自标定集抽检表（模型先标，等你签）\n\n"
        f"草稿统计＝{len(drafts)} 行全标｜有效草稿 **{n_labeled}**"
        f"（对 {counts.get('对', 0)}／部分 {counts.get('部分', 0)}／错 {counts.get('错', 0)}）"
        f"｜被旗 **{n_flagged}**\n\n"
        f"本表抽 **{len(picked)}** 行：全部「部分／错」＋每箱 {SHEET_DUI_PER_BAND} 行「对」"
        f"＋被旗的 {min(SHEET_FLAGGED, len(flagged))} 行。"
        f"（r3：引文列加长，可见支撑关键句）\n\n"
        f"| # | 案例 | 置信 | 分箱 | 结论 | 模型标 | 我的签 | 理由 | 引文（加长） | 旗 |\n"
        f"| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
    )
    lines = [head.rstrip("\n")]
    rows_json: list[dict[str, Any]] = []
    quote_lens: list[int] = []
    for i, d in enumerate(picked, 1):
        case = str(d.get("case") or "").split("/")[-1]
        score = float(d.get("score") or 0)
        stmt = (d.get("statement") or "").replace("|", "｜")[:72]
        lab = d.get("model_label") or "—"
        why = (d.get("why") or "").replace("|", "｜")[:60]
        q = (d.get("display_quote") or d.get("quote") or "").replace("|", "｜")
        q = q.replace("\n", " ")[:160]
        quote_lens.append(len(q))
        flag = (d.get("flag") or "").replace("|", "｜")[:40]
        lines.append(
            f"| {i} | {case} | {score:.3f} | {_band(score)} | {stmt} "
            f"| {lab} |  | {why} | {q} | {flag} |"
        )
        rows_json.append({
            "case": d.get("case"),
            "conclusion_id": d.get("conclusion_id"),
            "statement_sha8": d.get("statement_sha8"),
            "draft_label": d.get("model_label") or "",
            "flag": d.get("flag") or "",
            "display_quote": q,
            "your_label": "",
            "labeled_by": "",
        })

    n_dui_sheet = sum(1 for d in picked if d.get("model_label") == "对")
    n_ok = n_labeled or 1
    dui_pct = round(100 * counts.get("对", 0) / n_ok)
    avg_disp = round(sum(quote_lens) / max(1, len(quote_lens))) if quote_lens else 0
    tail = (
        f"\n\n> 本表引文列平均 **{avg_disp}** 字（r3 加长；勿再截到看不出对错）。\n"
        f"\n\n## 两件事要你定\n\n"
        f"1. 逐行改标：上表「我的签」列填 对／部分／错（不认同草稿就改，认同就照抄）。\n"
        f"2. 整批裁定：草稿里「对」占 {counts.get('对', 0)}/{n_labeled}＝**{dui_pct}%**。"
        f"若你在本表里对「对」那一档的改标率 ≤10%，就＝**整批按草稿入账、你在文件末尾签一次名**；"
        f"若 >10%＝整批退回、我把引文喂得更足再重标。\n\n"
        f"## 签名字段（写完请填）\n\n"
        f"- labeled_by＝\n"
        f"- 签字日期＝\n"
        f"- 改标率（我改了几行／抽检几行）＝\n"
        f"- 本表「对」档抽检行数＝{n_dui_sheet}\n"
    )
    sheet_path = out_dir / "spot_check_sheet.md"
    sheet_path.write_text("\n".join(lines) + tail, encoding="utf-8")
    (out_dir / "spot_check_rows.json").write_text(
        json.dumps(rows_json, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(picked), sheet_path


def run(cands_path: Path, limit: int) -> int:
    gate = _locks()
    from app.llm.model_client import ModelClientFactory
    from scripts.measure_s4_gates import MODEL, settings_for

    client = ModelClientFactory(settings_for(None)).create()
    rows = [json.loads(l) for l in cands_path.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    todo = rows[:limit] if limit else rows
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = OUT / f"assist-label-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[assist] {gate}\n候选 {len(rows)} 行，本轮标 {len(todo)} 行，草稿目录＝{out_dir}"
          "（**不写 calibration/**；r3＝引文加长展示＋对收紧）", flush=True)

    drafts: list[dict[str, Any]] = []
    for n, r in enumerate(todo, 1):
        rec = _find_conclusion(r["case"], r["conclusion_id"])
        if not rec or not rec["statement"]:
            drafts.append({**r, "model_label": "", "flag": "案卷里找不到该结论",
                           "why": "", "quote": "", "display_quote": "",
                           "sure": False,
                           "elapsed_s": 0.0, "n_quote_chars": 0})
            print(f"  {n:>3} {r['case'][-18:]} {r['conclusion_id'][:14]} 找不到结论", flush=True)
            continue
        got = _label_one(client, MODEL, rec)
        row = {**r, "statement": rec["statement"][:120], "score": rec["confidence"],
               "n_quotes": rec["n_quotes"], "dropped_quotes": rec["dropped_quotes"],
               **got}
        drafts.append(row)
        with (out_dir / "draft_labels.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  {n:>3} {r['case'][-18:]} {r['conclusion_id'][:14]} "
              f"分 {float(rec['confidence'] or 0):.3f} "
              f"引文{got.get('n_quote_chars', 0)}字 → {got['model_label'] or '—'} "
              f"{('｜' + got['flag']) if got['flag'] else ''} ({got['elapsed_s']}s)", flush=True)

    ok = [d for d in drafts if d["model_label"] in ALLOWED]
    counts = {k: sum(1 for d in ok if d["model_label"] == k) for k in ALLOWED}
    n_flagged = len(drafts) - len(ok)
    avg_chars = round(sum(d.get("n_quote_chars") or 0 for d in drafts) / max(1, len(drafts)))
    summary = {"dir": str(out_dir), "n_rows": len(drafts), "n_labeled": len(ok),
               "counts": counts, "n_flagged": n_flagged,
               "flags": sorted({d["flag"] for d in drafts if d.get("flag")}),
               "avg_s": round(sum(d["elapsed_s"] for d in drafts) / max(1, len(drafts)), 2),
               "avg_quote_chars": avg_chars,
               "max_quotes_chars": MAX_QUOTES_CHARS,
               "revision": "r3-long-cite-strict-dui",
               "signed": False,
               "note": "草稿＝模型先标；未经用户抽检签字不得进 calibration/、不得当 ground truth"}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    md = ["# 自标定集抽检表（模型先标，等你签字）", "",
          "| # | 案例 | 结论（截断） | 置信 | 模型标 | 理由 | 支撑片段 | 旗 |",
          "|---|---|---|---|---|---|---|---|"]
    for i, d in enumerate(drafts, 1):
        md.append(f"| {i} | {d['case'].split('/')[-1]} | {d.get('statement', '')[:40]} "
                  f"| {float(d.get('score') or 0):.3f} | {d['model_label'] or '—'} "
                  f"| {d.get('why', '')} | {(d.get('quote') or '')[:36]} | {d.get('flag', '')} |")
    (out_dir / "spot_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    n_sheet, sheet_path = _build_sheet(drafts, out_dir, counts, n_flagged)
    summary["n_sheet"] = n_sheet
    summary["sheet"] = str(sheet_path)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(f"抽检表＝{sheet_path}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--candidates", default=str(ROOT / "calibration/candidates_self.jsonl"))
    ap.add_argument("--limit", type=int, default=60,
                    help="标前 N 行（0＝全量）；默认 60＝达标行数")
    args = ap.parse_args()
    path = Path(args.candidates)
    if not path.is_file():
        raise SystemExit(f"找不到候选清单 {path}（先生成：python scripts/calibrate_confidence.py "
                         "--emit-candidates）")
    return run(path, max(0, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
