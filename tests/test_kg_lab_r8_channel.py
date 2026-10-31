"""R8 渠道层级：主机名规则，不看可信度。"""

from __future__ import annotations

from app.kg_lab.channel_tier import channel_tier


def test_channel_tiers_from_host():
    assert channel_tier("https://www.news.cn/a", "刘翔称已买断-新华网") == "central_official"
    assert channel_tier("https://www.jfdaily.com/sgh/detail?id=1", "情况通报_上观新闻") == "local_official"
    assert channel_tier("https://www.zaobao.com.sg/news/china/x", "联合早报") == "foreign_media"
    assert channel_tier("https://www.163.com/dy/article/x", "尘埃落定") == "market_media"
    assert channel_tier("https://weibo.com/2/detail/1", "财入门") == "self_media"
    assert channel_tier("https://news.zhibo8.com/a", "网友质问") == "self_media"
    assert channel_tier("", "无链接") == "other"
