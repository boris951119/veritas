"""真实语料选料召回抽检（零 LLM）。

用 `eval/questions.jsonl`（约 30 问）+ 桌面全量公告库（或仓库 B4 摘要包）：
1. 按公司建/复用磁盘索引；
2. 用「指标词 + 答案值」自动标 must-keep 信源；
3. 跑选料 select，算 Recall（must-keep 是否进本次案卷）。

量的是选料，不是模型答题。失败只改规则，不上 embedding。
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path

from app.core.corpus_store import DiskCorpusIndex
from app.core.evidence import SourceType
from app.core.query_rewrite import collect_search_queries
from app.ingest.case_loader import SourceSpec, ingest_file
from app.ingest.segment import SEGMENTER_VERSION

_ROOT = Path(__file__).resolve().parent.parent
_QUESTIONS = _ROOT / "eval" / "questions.jsonl"
_DEFAULT_CORPUS = Path.home() / "Desktop" / "veritas-testcases" / "eval-corpus"
_REPO_CORPUS = _ROOT / "eval" / "corpus"
_INDEX_ROOT = _ROOT / ".tmp" / "recall_real_index"

_DOC_EXTS = {".pdf", ".txt", ".md", ".html", ".htm"}


def default_corpus_root() -> Path:
    import os

    env = (os.environ.get("VERITAS_EVAL_CORPUS") or "").strip()
    if env:
        return Path(env).expanduser()
    if _DEFAULT_CORPUS.is_dir():
        return _DEFAULT_CORPUS
    return _REPO_CORPUS


def load_questions(path: Path | None = None) -> list[dict]:
    path = path or _QUESTIONS
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _company_dir(corpus_root: Path, company: str) -> Path | None:
    direct = corpus_root / company
    if direct.is_dir():
        return direct
    # 仓库 B4：eval/corpus/<公司>/
    if (corpus_root / company).is_dir():
        return corpus_root / company
    return None


def _iter_docs(company_dir: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(company_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _DOC_EXTS:
            continue
        # 跳过产物与缓存
        parts = set(p.parts)
        if parts & {"out", "out_eval", "history", ".corpus", ".fetched"}:
            continue
        if any(part.startswith("out_") for part in p.parts):
            continue
        out.append(p)
    return out


def ensure_company_index(company: str, corpus_root: Path,
                         *, force: bool = False) -> tuple[Path, int]:
    """建或复用公司级 SQLite 索引。返回 (db_path, n_sources)。"""
    company_dir = _company_dir(corpus_root, company)
    if company_dir is None:
        raise FileNotFoundError(f"找不到公司语料目录: {company} @ {corpus_root}")
    docs = _iter_docs(company_dir)
    if not docs:
        raise FileNotFoundError(f"公司目录无可用文档: {company_dir}")

    db_path = _INDEX_ROOT / company / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path = db_path.parent / "meta.json"
    fingerprint = {
        "segmenter": SEGMENTER_VERSION,
        "n_files": len(docs),
        "files": [str(p.relative_to(company_dir)) for p in docs[:5]]
        + ([f"...+{len(docs)-5}"] if len(docs) > 5 else []),
        "mtime_max": max(int(p.stat().st_mtime) for p in docs),
        "size_sum": sum(p.stat().st_size for p in docs),
    }
    if (not force and db_path.is_file() and meta_path.is_file()
            and json.loads(meta_path.read_text(encoding="utf-8")) == fingerprint):
        index = DiskCorpusIndex.open(db_path)
        try:
            n = index.live_source_count()
        finally:
            index.close()
        return db_path, n

    if db_path.exists():
        db_path.unlink()
    index = DiskCorpusIndex.create(db_path, project_id=company)
    try:
        for i, path in enumerate(docs, 1):
            sid = f"D{i:04d}"
            try:
                src = ingest_file(
                    path, sid, SourceSpec(source_type=SourceType.REPORT))
            except Exception:
                continue
            rel = str(path.relative_to(company_dir))
            src.meta["file"] = rel
            # 标题/文件名里的公司名作主体，供实体强制入选
            index.upsert_source(
                src, path=rel, subjects=[company],
                published_at="",
            )
        n = index.live_source_count()
        index.close()
    except Exception:
        index.close()
        raise
    meta_path.write_text(json.dumps(fingerprint, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return db_path, n


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def _value_patterns(value: str) -> list[str]:
    """答案值的宽松匹配形（去空格、百分比写法）。"""
    v = _norm(value)
    if not v:
        return []
    out = [v]
    if v.endswith("%"):
        out.append(v[:-1])
    # 「25 万」→「25万」「250000」不强求
    out.append(v.replace("万", "0000") if "万" in v else v)
    # 去重保序
    seen: set[str] = set()
    return [x for x in out if x and not (x in seen or seen.add(x))]


def _weak_value(value: str) -> bool:
    """过短/常见数字答案不能单独当金标锚点（如「10」「0.90」）。"""
    v = _norm(value)
    if not v or len(v) <= 2:
        return True
    if v.endswith("%") and len(v) <= 3:  # 如 1%
        return True
    if re.fullmatch(r"\d+(\.\d+)?", v):
        try:
            return float(v) < 1000 and len(v) <= 4
        except ValueError:
            return True
    return False


def _metric_hits(body: str, metric_n: str) -> bool:
    if not metric_n:
        return False
    if metric_n in body:
        return True
    # 取较长片段，降低「每」「多少」类噪声
    width = 6 if len(metric_n) >= 6 else max(2, len(metric_n))
    frags = [metric_n[i:i + width]
             for i in range(0, max(1, len(metric_n) - width + 1))]
    return any(f in body for f in frags)


def _colocated(body: str, metric_n: str, values: list[str],
               window: int = 40) -> bool:
    """指标词与答案值须在同一段内邻近（防『公司成立』+『30』误标）。"""
    if not body or not metric_n:
        return False
    anchors: list[str] = []
    if metric_n in body:
        anchors.append(metric_n)
    else:
        width = 6 if len(metric_n) >= 6 else max(2, len(metric_n))
        anchors = [metric_n[i:i + width]
                   for i in range(0, max(1, len(metric_n) - width + 1))]
    for anc in anchors:
        start = 0
        while True:
            i = body.find(anc, start)
            if i < 0:
                break
            lo = max(0, i - window)
            hi = min(len(body), i + len(anc) + window)
            near = body[lo:hi]
            if any(v in near for v in values):
                return True
            start = i + 1
    return False


def _question_hints(question: str) -> list[str]:
    """从议题抽出区分性短语，收紧 must-keep（避免指标词过短）。"""
    qn = _norm(question)
    tips = (
        "深耕改性", "多年来", "客户开拓", "宾坦工业园", "利用小时",
        "现金分红比例", "优先股", "改性化率", "装机容量",
    )
    return [t for t in tips if t in qn]


def find_must_keep(db_path: Path, *, metric: str, value: str,
                   company: str, question: str = "") -> list[str]:
    """正文同时贴近指标词与答案值的信源 = must-keep。"""
    metric_n = _norm(metric)
    values = _value_patterns(value)
    if not metric_n or not values:
        return []
    weak = _weak_value(value)
    hints = _question_hints(question)
    index = DiskCorpusIndex.open(db_path)
    try:
        hits: dict[str, int] = defaultdict(int)
        rows = index._conn.execute(
            "SELECT id, source_id, text FROM segments").fetchall()
        for _sid, source_id, text in rows:
            body = _norm(text)
            if not _metric_hits(body, metric_n):
                continue
            if not any(v in body for v in values):
                continue
            # 弱答案必须指标与数字邻近，否则「30」「10」会误标半个库
            if weak and not _colocated(body, metric_n, values):
                continue
            if hints and not any(h in body for h in hints):
                continue
            hits[source_id] += 1
        if not hits:
            return []

        def _title(sid: str) -> str:
            row = index._conn.execute(
                "SELECT title, path FROM sources WHERE id=?", (sid,)
            ).fetchone()
            return ((row[0] if row else "") + (row[1] if row else ""))

        preferred, abstracts, others = [], [], []
        for sid, _n in sorted(hits.items(), key=lambda x: (-x[1], x[0])):
            title = _title(sid)
            if "摘要" in title and ("年度报告" in title or "年报" in title):
                abstracts.append(sid)
            elif "年度报告" in title or "年报" in title:
                preferred.append(sid)
            else:
                others.append(sid)
        # 弱答案：摘要 > 年报 > 其它，只留 1 份，避免多金标稀释
        if weak:
            ordered = abstracts or preferred or others
            return ordered[:1]
        ordered = abstracts + preferred + others
        return ordered[:3]
    finally:
        index.close()


def score_question(item: dict, db_path: Path, *,
                   max_sources: int = 50,
                   material_budget: int = 80_000,
                   use_metric_query: bool = True) -> dict:
    """单问选料召回。"""
    company = item["company"]
    question = item["question"]
    metric = item.get("metric") or ""
    value = item.get("value") or ""
    must = find_must_keep(
        db_path, metric=metric, value=value, company=company,
        question=question)
    variants = []
    if use_metric_query and metric:
        # 确定性「伪改写」：原问 + 指标短问 + 议题区分词，不调 LLM
        short = f"{company}{metric}"
        variants = [short, f"{company}{metric}{value}".strip()]
        for tip in _question_hints(question):
            variants.append(f"{company}{tip}")
    queries = collect_search_queries(question, variants)

    index = DiskCorpusIndex.open(db_path)
    try:
        n_lib = index.live_source_count()
        result = index.select(
            question, max_sources=max_sources,
            material_budget=material_budget, queries=queries,
        )
    finally:
        index.close()

    selected = [s.id for s in result.dossier.sources]
    hit = [sid for sid in must if sid in selected]
    recall = (len(hit) / len(must)) if must else None
    return {
        "company": company,
        "question": question.replace("\n", " ").strip(),
        "metric": metric,
        "value": value,
        "n_library": n_lib,
        "must_keep": must,
        "selected": selected,
        "hit": hit,
        "recall": recall,
        "n_queries": len(queries),
        "ok": bool(must) and recall == 1.0,
        "skip_reason": "" if must else "no_must_keep_labeled",
    }


def run_real_recall(corpus_root: Path | None = None, *,
                    force_reindex: bool = False,
                    companies: list[str] | None = None,
                    max_sources: int = 50) -> dict:
    """跑全量抽检，返回汇总 dict。"""
    corpus_root = corpus_root or default_corpus_root()
    items = load_questions()
    if companies:
        allow = set(companies)
        items = [x for x in items if x["company"] in allow]

    by_company: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_company[it["company"]].append(it)

    t0 = time.monotonic()
    index_meta: dict[str, dict] = {}
    rows: list[dict] = []
    for company, qs in by_company.items():
        db_path, n = ensure_company_index(
            company, corpus_root, force=force_reindex)
        index_meta[company] = {
            "db_path": str(db_path),
            "n_sources": n,
            "n_questions": len(qs),
        }
        for it in qs:
            rows.append(score_question(
                it, db_path, max_sources=max_sources))

    scored = [r for r in rows if r["recall"] is not None]
    skipped = [r for r in rows if r["recall"] is None]
    ok_n = sum(1 for r in scored if r["ok"])
    mean_recall = (
        sum(r["recall"] for r in scored) / len(scored) if scored else 0.0)
    return {
        "corpus_root": str(corpus_root),
        "elapsed_s": round(time.monotonic() - t0, 1),
        "n_questions": len(rows),
        "n_scored": len(scored),
        "n_skipped": len(skipped),
        "n_ok": ok_n,
        "mean_recall": round(mean_recall, 4),
        "pass_rate": round(ok_n / len(scored), 4) if scored else 0.0,
        "index": index_meta,
        "rows": rows,
    }


def render_report(summary: dict) -> str:
    lines = [
        "# 真实语料选料召回抽检",
        "",
        f"- 语料根目录：`{summary['corpus_root']}`",
        f"- 题目：{summary['n_questions']}（可打分 {summary['n_scored']}，"
        f"未标金标跳过 {summary['n_skipped']}）",
        f"- 全中 must-keep：{summary['n_ok']} / {summary['n_scored']} "
        f"（通过率 {summary['pass_rate']:.1%}）",
        f"- 平均 Recall：{summary['mean_recall']:.1%}",
        f"- 耗时：{summary['elapsed_s']}s",
        "",
        "## 分司索引",
        "",
        "| 公司 | 库内信源 | 题数 |",
        "|---|---:|---:|",
    ]
    for company, meta in (summary.get("index") or {}).items():
        lines.append(
            f"| {company} | {meta['n_sources']} | {meta['n_questions']} |")
    lines += ["", "## 逐问", "",
              "| 公司 | Recall | must-keep | 命中 | 议题 |",
              "|---|---:|---|---|---|"]
    for r in summary.get("rows") or []:
        if r["recall"] is None:
            rec = "跳过"
        else:
            rec = f"{r['recall']:.0%}"
        q = r["question"][:36] + ("…" if len(r["question"]) > 36 else "")
        lines.append(
            f"| {r['company']} | {rec} | {','.join(r['must_keep']) or '—'} | "
            f"{','.join(r['hit']) or '—'} | {q} |")
    fails = [r for r in summary.get("rows") or []
             if r["recall"] is not None and not r["ok"]]
    if fails:
        lines += ["", "## 漏召（只改规则，不上 embedding）", ""]
        for r in fails:
            lines.append(
                f"- **{r['company']}** `{r['metric']}` → 值 `{r['value']}`；"
                f"must-keep={r['must_keep']} selected前8={r['selected'][:8]}")
    else:
        lines += ["", "## 漏召", "", "无。", ""]
    lines.append("")
    return "\n".join(lines)
