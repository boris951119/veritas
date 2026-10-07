# -*- coding: utf-8 -*-
"""上市公司评测语料构建:巨潮资讯公告抓取 → 评测案卷骨架。

抓取范围(每家):年报**摘要**(10-20页,适合切段)+ 业绩预告 + 更正公告。
PDF 原件不入 git(eval/.gitignore),标注与清单入库。

用法:.venv/bin/python scripts/build_eval_corpus.py [--max-per-type 2]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

COMPANIES = [
    ("600219", "gssh0600219", "南山铝业", "sse"),
    ("601991", "9900001601", "大唐发电", "sse"),
    ("600795", "gssh0600795", "国电电力", "sse"),
    ("601988", "jjxt0000028", "中国银行", "sse"),
    ("000785", "gssz0000785", "居然之家", "szse"),
    ("000977", "gssz0000977", "浪潮信息", "szse"),
    ("832469", "gfbj0832469", "富恒新材", "bj"),   # 待确认:用户说"恒新新材"
]

SE_DATE = "2025-01-01~2026-10-01"
CATS = "category_ndbg_szsh;category_yjygjxz_szsh"   # 年报 + 业绩预告
BASE = "http://www.cninfo.com.cn"
STATIC = "http://static.cninfo.com.cn/"


def query(code: str, org_id: str, column: str, max_per_type: int) -> list[dict]:
    form = {
        "stock": f"{code},{org_id}", "tabName": "fulltext",
        "pageSize": "30", "pageNum": "1", "column": column,
        "category": CATS, "seDate": SE_DATE, "isHLtitle": "true",
    }
    url = BASE + "/new/hisAnnouncement/query"
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={"User-Agent": "Mozilla/5.0",
                 "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out: dict[str, list[dict]] = {"年报摘要": [], "业绩预告": [], "更正": []}
    for ann in data.get("announcements") or []:
        title = ann.get("announcementTitle") or ""
        adj = ann.get("adjunctUrl") or ""
        if not adj:
            continue
        if "摘要" in title and ("年报" in title or "年度报告" in title):
            key = "年报摘要"
        elif "业绩预告" in title:
            key = "业绩预告"
        elif "更正" in title:
            key = "更正"
        else:
            continue
        if len(out[key]) < max_per_type:
            out[key].append({"title": title, "url": STATIC + adj})
    return [x for k in ("年报摘要", "业绩预告", "更正") for x in out[k]]


def download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read(50 * 1024 * 1024))
        return dest.stat().st_size > 10_000
    except Exception as exc:
        print(f"    ✗ 下载失败 {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    max_per_type = int(sys.argv[sys.argv.index("--max-per-type") + 1]) \
        if "--max-per-type" in sys.argv else 2
    root = REPO / "eval" / "corpus"
    root.mkdir(parents=True, exist_ok=True)
    manifest_lines = ["# 上市公司评测语料(巨潮资讯公开披露)\n"]
    for code, org_id, name, column in COMPANIES:
        print(f"== {name}({code})")
        docs = query(code, org_id, column, max_per_type)
        d = root / name
        (d / "pdf").mkdir(parents=True, exist_ok=True)
        got = []
        for item in docs:
            safe = "".join(c for c in item["title"] if c not in '\\/:*?"<>|')[:60]
            dest = d / "pdf" / f"{safe}.pdf"
            if dest.is_file() and dest.stat().st_size > 10_000:
                got.append(item["title"])
                continue
            print(f"    ↓ {item['title'][:50]}")
            if download(item["url"], dest):
                got.append(item["title"])
                time.sleep(0.5)
        (d / ".downloaded.json").write_text(
            json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
        manifest_lines.append(f"\n## {name}({code})\n")
        for t in got:
            manifest_lines.append(f"- {t}")
    (root / "MANIFEST.md").write_text("\n".join(manifest_lines) + "\n",
                                      encoding="utf-8")
    print(f"\n完成:语料在 {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
