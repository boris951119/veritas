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


def _get(url: str, dest: Path, cap: int = 50 * 1024 * 1024) -> bool:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=90) as r:
            dest.write_bytes(r.read(cap + 1))
        ok = 10_000 < dest.stat().st_size <= cap
        if not ok:
            dest.unlink(missing_ok=True)
        return ok
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


def main() -> int:
    max_n = 0
    if "--max" in sys.argv:
        max_n = int(sys.argv[sys.argv.index("--max") + 1])
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    # 迁移旧语料(仓库 eval/corpus → 桌面)
    old = REPO / "eval" / "corpus"
    if old.is_dir():
        for d in old.iterdir():
            dest = OUT_ROOT / d.name
            if not dest.exists():
                shutil.move(str(d), str(dest))
            else:
                for f in d.rglob("*"):
                    if f.is_file():
                        t = dest / "pdf" / f.name
                        t.parent.mkdir(parents=True, exist_ok=True)
                        if not t.exists():
                            shutil.copy2(f, t)
        shutil.rmtree(REPO / "eval", ignore_errors=True)
        print("旧语料已迁移到桌面")
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
    for name, st in summary:
        print(f"  {name}: {st['total']} 条 / 下载 {st['ok']} / 失败 {st['fail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
