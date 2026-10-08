# -*- coding: utf-8 -*-
"""上市公司评测语料构建 v2:两年内全部官方公告 → 桌面语料库。

- 巨潮资讯(cninfo):A股/北交所 8 家,两年窗口内全部公告逐条下载;
- SEC EDGAR:AOSL(纳斯达克)10-K/10-Q/8-K 主文档(HTML);
- 输出:桌面 veritas-testcases/eval-corpus/<公司>/(PDF/HTML 不入 git);
- 断点续传:已存在且非空的文件跳过;单文件失败仅记账不炸。

用法:.venv/bin/python scripts/build_eval_corpus.py [--max N](每家上限,N=0 不限)
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT_ROOT = Path("/Users/liuboyu/Desktop/veritas-testcases/eval-corpus")
BASE = "https://www.cninfo.com.cn"
SE_DATE = "2023-10-01~2025-10-01"
SLEEP = 0.4

CN_COMPANIES = [
    ("600219", "gssh0600219", "南山铝业", "sse"),
    ("601991", "9900001601", "大唐发电", "sse"),
    ("600795", "gssh0600795", "国电电力", "sse"),
    ("601988", "jjxt0000028", "中国银行", "sse"),
    ("000785", "gssz0000785", "居然之家", "szse"),
    ("000977", "gssz0000977", "浪潮信息", "szse"),
    ("832469", "gfbj0832469", "富恒新材", "bj"),
    ("603276", "9900047855", "恒兴新材", "sse"),
]
AOSL_TICKER = "AOSL"
UA = {"User-Agent": "veritas-research contact@veritas.dev"}  # SEC 要求「名称 邮箱」格式


def _post_json(url: str, form: dict) -> dict:
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={**UA, "Content-Type": "application/x-www-form-urlencoded; "
                                "charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url: str, dest: Path, cap: int = 200 * 1024 * 1024,
         min_size: int = 10_000) -> bool:
    """下载到 dest。超过 cap 截断判失败；小于 min_size 视为空包。"""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read(cap + 1)
        if len(data) > cap or len(data) <= min_size:
            dest.unlink(missing_ok=True)
            return False
        dest.write_bytes(data)
        return True
    except Exception as exc:
        print(f"      ✗ {type(exc).__name__}: {str(exc)[:60]}")
        dest.unlink(missing_ok=True)
        return False


def sanitize(title: str) -> str:
    for ch in '\\/:*?"<>|\n\r\t ':
        title = title.replace(ch, "_")
    return title[:80]


def fetch_cn_all(code: str, org: str, name: str, column: str,
                 out_dir: Path, max_n: int) -> dict:
    """两年内全部公告:分页查询 → 逐条下载。"""
    all_ann: list[dict] = []
    page = 1
    while True:
        form = {"pageNum": str(page), "pageSize": "30", "column": column,
                "tabName": "fulltext", "plate": "", "stock": f"{code},{org}",
                "searchkey": "", "secid": "", "category": "", "trade": "",
                "seDate": SE_DATE, "sortName": "", "sortType": "",
                "isHLtitle": "true"}
        try:
            data = _post_json(BASE + "/new/hisAnnouncement/query", form)
        except Exception as exc:
            print(f"    查询失败 page{page}: {exc}")
            break
        anns = data.get("announcements") or []
        all_ann.extend(anns)
        if len(all_ann) >= (data.get("totalRecordNum") or 0) or not anns:
            break
        page += 1
        time.sleep(SLEEP)
        if page > 40:
            break
    ok = fail = 0
    index = []
    for ann in all_ann[:max_n] if max_n else all_ann:
        adj = ann.get("adjunctUrl") or ""
        if not adj:
            continue
        ts = time.strftime("%Y-%m-%d", time.gmtime(
            (ann.get("announcementTime") or 0) / 1000))
        title = sanitize(ann.get("announcementTitle") or adj)
        dest = out_dir / f"{ts}_{title}.pdf"
        index.append({"date": ts, "title": ann.get("announcementTitle"),
                      "file": dest.name})
        if dest.is_file() and dest.stat().st_size > 10_000:
            ok += 1
            continue
        if _get("http://static.cninfo.com.cn/" + adj, dest):
            ok += 1
        else:
            fail += 1
        time.sleep(SLEEP)
    (out_dir / ".announcements.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"total": len(all_ann), "ok": ok, "fail": fail}


def fetch_aosl(out_dir: Path, max_n: int) -> dict:
    """AOSL(纳斯达克)SEC EDGAR:10-K/10-Q/8-K 主文档。"""
    cache = Path("/tmp/edgar_tickers.json")
    if not cache.is_file():
        cache.write_bytes(_edgar("https://www.sec.gov/files/company_tickers.json",
                                 timeout=120))
    tickers = json.loads(cache.read_text(encoding="utf-8"))
    cik = next(int(v["cik_str"]) for v in tickers.values()
               if v["ticker"] == AOSL_TICKER)
    sub = json.loads(_edgar(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
    recent = sub["filings"]["recent"]
    want = {"10-K", "10-Q", "8-K"}
    got = {"total": 0, "ok": 0, "fail": 0}
    index = []
    for form, fdate, doc, acc in zip(
            recent["form"], recent["filingDate"], recent["primaryDocument"],
            recent["accessionNumber"]):
        if form not in want or fdate < SE_DATE[:10]:
            continue
        got["total"] += 1
        if max_n and got["ok"] >= max_n:
            break
        acc_n = acc.replace("-", "")
        dest = out_dir / f"{fdate}_{form}_{sanitize(doc)[:60]}"
        index.append({"date": fdate, "form": form, "file": dest.name})
        if dest.is_file() and dest.stat().st_size > 5_000:
            got["ok"] += 1
            continue
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_n}/{doc}"
        if _get(url, dest):
            got["ok"] += 1
        else:
            got["fail"] += 1
        time.sleep(0.2)
    (out_dir / ".announcements.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return got


def _edgar(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def migrate_repo_corpus_to_desktop() -> int:
    """把仓库 eval/corpus/<公司> 同步到桌面（复制，不删仓库）。

    返回同步的公司目录数。绝不能 rmtree(REPO/eval)——会毁掉
    questions.jsonl / layout / report 等评测资产。
    """
    old = REPO / "eval" / "corpus"
    if not old.is_dir():
        return 0
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    n = 0
    for d in sorted(old.iterdir()):
        if not d.is_dir():
            # MANIFEST 等说明文件也拷过去
            if d.is_file() and d.suffix in (".md", ".txt", ".json"):
                dest_f = OUT_ROOT / d.name
                if not dest_f.exists():
                    shutil.copy2(d, dest_f)
            continue
        dest = OUT_ROOT / d.name
        dest.mkdir(parents=True, exist_ok=True)
        for f in d.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(d)
            # 仓库里 PDF 在 pdf/ 下；若误放根目录，归入 pdf/
            if rel.parts[0] == "pdf" or f.suffix.lower() in (
                    ".pdf", ".htm", ".html"):
                if rel.parts[0] == "pdf":
                    t = dest / rel
                else:
                    t = dest / "pdf" / f.name
            else:
                t = dest / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            if not t.exists() or t.stat().st_size != f.stat().st_size:
                shutil.copy2(f, t)
        n += 1
    return n


def main() -> int:
    max_n = 0
    if "--max" in sys.argv:
        max_n = int(sys.argv[sys.argv.index("--max") + 1])
    migrate_only = "--migrate-only" in sys.argv
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    # 迁移旧语料(仓库 eval/corpus/<公司> → 桌面)；绝不可删除整个 eval/
    # （questions.jsonl / layout / report.md 必须留在仓库）
    n_mig = migrate_repo_corpus_to_desktop()
    if n_mig:
        print(f"旧语料已同步到桌面（{n_mig} 个公司目录，仓库副本保留）")
    if migrate_only:
        return 0
    summary = []
    for code, org, name, column in CN_COMPANIES:
        d = OUT_ROOT / name
        d.mkdir(parents=True, exist_ok=True)
        print(f"== {name}({code})全量公告", flush=True)
        st = fetch_cn_all(code, org, name, column, d, max_n)
        print(f"   公告 {st['total']} 条,下载 {st['ok']},失败 {st['fail']}")
        summary.append((name, st))
        time.sleep(SLEEP)
    d = OUT_ROOT / "AOSL"
    d.mkdir(parents=True, exist_ok=True)
    print("== AOSL(纳斯达克)SEC EDGAR", flush=True)
    st = fetch_aosl(d, max_n)
    print(f"   文件 {st['total']},下载 {st['ok']},失败 {st['fail']}")
    summary.append(("AOSL", st))
    print("\n===== 汇总 =====")
    lines = [
        "# 上市公司评测语料（巨潮全量 + SEC AOSL）",
        "",
        f"窗口: `{SE_DATE}`",
        f"路径: `{OUT_ROOT}`",
        f"生成: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "| 公司 | 公告条数 | 下载成功 | 失败 |",
        "|---|---:|---:|---:|",
    ]
    for name, st in summary:
        print(f"  {name}: {st['total']} 条 / 下载 {st['ok']} / 失败 {st['fail']}")
        lines.append(
            f"| {name} | {st['total']} | {st['ok']} | {st['fail']} |")
    lines += [
        "",
        "说明：PDF/HTML 仅存桌面，不入 git；仓库 `eval/corpus/` 保留 B4 启动包。"
        "断点续传：已存在且 >10KB 的文件跳过。",
        "",
    ]
    (OUT_ROOT / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")
    print("MANIFEST:", OUT_ROOT / "MANIFEST.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
