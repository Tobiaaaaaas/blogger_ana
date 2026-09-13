# -*- coding: utf-8 -*-
"""01§10 备料：行情与交易日历 —— 搬进 `data/market/`。

| 哪一样 | 落在哪 | 干什么用 |
|:---|:---|:---|
| **交易日历** | `data/market/trade_cal.json` | 哪天开市。**数日子**（验证终点、交易日跨度）只认它（03§3.4） |
| **日线** | `data/market/market_data.json` | **行情水位** —— 数据到哪天。**算价**只认它 |
| **30 分钟线** | `data/market/intraday/<指数>_30min.json` | 算**参考价**与**终点价**（03§3） |

**日历与行情是两件事，不许互相倒推**（01§10.3）。

**管什么**：抓、降级、重试、落盘、**抓完核对**。
**不管什么**：行情怎么读、怎么算（那是 `blogger.common.market`，02 与 03 的公共地基）。

    补到今天并核对 —— 差一天就非零退出
    python -m blogger.market

    只看不抓：打印各指数末根日期。不联网、不写盘
    python -m blogger.market --check
"""

from blogger.market import fetch, flow

__all__ = ["fetch", "flow"]
