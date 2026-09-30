"""网页链接：清单检测 + 显式抓取（默认关，零新依赖）。

链接是信源声明，不是信源本身——检测到 URL 密集文件只做两件事：
未开启抓取 → 诚实披露「N 条链接未抓取」，绝不假装读过；
开启抓取（CLI --fetch-links / VERITAS_FETCH_LINKS=1）→ 逐条抓取，
逐条披露成败，抓回的每一页成为正式信源（web 类型、低可信先验
0.3），与本地文件同权过全套机械闸（围栏/相关性/BM25/引文核对）。

安全边界：每条超时 15s、单页 2MB、每案 ≤30 条、仅接受 text/*；
404/超时/反爬 → 披露，绝不炸 run。离线环境整组跳过并披露
（离线演示兜底因此不受影响——这也是默认关的原因）。
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from app.core.evidence import Source, SourceType
from app.ingest.readers import parse_html
from app.ingest.segment import split_segments

_URL_LINE = re.compile(r"https?://\S+")
FETCH_TIMEOUT_SECONDS = 15
FETCH_MAX_BYTES = 2 * 1024 * 1024
MAX_LINKS_PER_CASE = 30
_FETCHED_TEXT_CAP = 200_000  # 抓回正文的入卷字符上限（防超长页）


class LinkFetchError(RuntimeError):
    """单条链接抓取失败（原因进披露，不上抛炸流程）。"""


def classify_link_list(text: str) -> tuple[bool, int]:
    """文本是否为「链接清单」：URL 行 ≥3 且占非空行 ≥60%。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    url_lines = []
    for ln in lines:
        m = _URL_LINE.match(ln)
        if m and len(m.group(0)) >= 0.8 * len(ln):
            url_lines.append(m.group(0))
    n = len(url_lines)
    return (n >= 3 and n >= 0.6 * len(lines)), n


def extract_urls(text: str, cap: int = MAX_LINKS_PER_CASE) -> list[str]:
    """去重保序抽取 URL，封顶 cap。"""
    seen: set[str] = set()
    out: list[str] = []
    for m in _URL_LINE.finditer(text):
        u = m.group(0).rstrip("。，；、)】>\"'")
        if u not in seen:
            seen.add(u)
            out.append(u)
            if len(out) >= cap:
                break
    return out


def fetch_raw(url: str) -> tuple[str, bytes]:
    """抓单条 → (content_type, body)；任何失败抛 LinkFetchError。

    测试通过 monkeypatch 本函数注入桩，零网络。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": "veritas-research/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            body = resp.read(FETCH_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise LinkFetchError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise LinkFetchError(f"网络错误: {reason}") from exc
    except Exception as exc:  # 超时/SSL/解码等一切异常都降级为披露
        raise LinkFetchError(f"{type(exc).__name__}: {exc}") from exc
    if len(body) > FETCH_MAX_BYTES:
        raise LinkFetchError(f"页面超过 {FETCH_MAX_BYTES // (1024 * 1024)}MB 上限")
    return ctype, body


def fetch_link_source(url: str) -> Source:
    """单条 URL → 正式信源（web，先验 0.3；meta 记录抓取出处）。"""
    ctype, body = fetch_raw(url)
    host = urlparse(url).netloc or url
    if "html" in ctype:
        title, text = parse_html(body.decode("utf-8", errors="replace"), host)
    elif ctype.startswith("text/") or ctype == "":
        title, text = host, body.decode("utf-8", errors="replace")
    else:
        raise LinkFetchError(f"内容类型 {ctype or '未知'} 不支持抓取（仅 text/*）")
    text = text[:_FETCHED_TEXT_CAP]
    source = Source.create(title=title or host, source_type=SourceType.WEB,
                           meta={"url": url, "fetched": True})
    for i, seg in enumerate(split_segments(text)):
        from app.core.evidence import Segment
        source.segments.append(Segment(
            id=f"{source.id}#s{i + 1}", source_id=source.id, text=seg,
            locator=f"段 {i + 1}", index=i))
    return source
