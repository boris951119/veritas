"""发布渠道层级。只看 URL 主机名和标题，不看可信度浮点，不读金标。"""

from __future__ import annotations

from urllib.parse import urlparse

TIERS: tuple[str, ...] = (
    "central_official",
    "local_official",
    "market_media",
    "foreign_media",
    "self_media",
    "other",
)

_CENTRAL = (
    "news.cn",
    "xinhuanet.com",
    "people.com.cn",
    "peopleapp.com",
    "cctv.com",
    "chinadaily.com.cn",
    "globaltimes.cn",
    "workercn.cn",
)
_LOCAL = (
    "shjjjc.gov.cn",
    "jfdaily.com",
    "kankanews.com",
    "zjol.com.cn",
    "southcn.com",
)
_MARKET = (
    "caixin.com",
    "caixinglobal.com",
    "thepaper.cn",
    "qq.com",
    "sina.com",
    "sina.cn",
    "sohu.com",
    "163.com",
    "ifeng.com",
    "huxiu.com",
    "jiemian.com",
    "guancha.cn",
    "dzng.com",
    "zhibo8.com",
    "clssn.com",
)
_FOREIGN = (
    "zaobao.com",
    "thestandard.com.hk",
    "insidethegames.biz",
)


def channel_tier(url: str, title: str = "") -> str:
    host = (urlparse(url or "").netloc or "").lower()
    title = title or ""
    if "weibo.com" in host or "网友" in title:
        return "self_media"
    if any(h in host for h in _FOREIGN):
        return "foreign_media"
    if any(h in host for h in _CENTRAL):
        return "central_official"
    if any(h in host for h in _LOCAL):
        return "local_official"
    if any(h in host for h in _MARKET):
        return "market_media"
    return "other"
