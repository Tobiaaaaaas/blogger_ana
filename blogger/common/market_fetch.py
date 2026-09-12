# -*- coding: utf-8 -*-
"""补行情 —— 03 备料的第二件事（第一件是抓帖，见 01）。

两组都要：

| 组 | 落在哪 | 干什么用 |
|:---|:---|:---|
| **日线** | `data/market/market_data.json` | 算**交易日历**（以上证指数的日期序列为唯一基准） |
| **30 分钟线** | `data/market/intraday/<指数>_30min.json` | 算**参考价**与**终点价** |

**两个源不一样，不是随便挑的**：日线走东财（akshare），30 分钟线走新浪 —— 东财对分钟线
做了 TLS 指纹封锁，且服务端只滚动保留约 32 个交易日，回溯不了。

**补不到不算失败**：行情缺一段，对应的信号状态记「待验证」，是算不出、不是算错（见 03§3.6）。
所以单个指数抓失败只提示，不中断。
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

from blogger.common import market, paths

# 七个主指数（双创不单列，由创业板指与科创50 各半合成）
INDICES = [("sh000001", "上证指数"), ("sh000300", "沪深300"), ("sz399006", "创业板指"),
           ("sh000016", "上证50"), ("sh000905", "中证500"), ("sh000852", "中证1000"),
           ("sh000688", "科创50")]

SINA_API = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "CN_MarketData.getKLineData")
SINA_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
SINA_SCALE = "30"
SINA_DATALEN = 6000      # 30 分钟 × 6000 根 ≈ 750 交易日，够回溯
PAUSE = 0.4              # 每个指数之间的间隔（秒），防风控


def needs_refresh(until: str = "") -> bool:
    """日历够不够到 `until`（默认今天）。够就不必再抓。"""
    target = until or date.today().isoformat()
    return market.LAST_DATE < _last_trading_day_on_or_before(target)


def refresh(until: str = "", progress=None) -> dict:
    """把日线与 30 分钟线补到 `until`（默认今天）。返回补了什么。"""
    target = until or date.today().isoformat()
    daily = _fetch_daily(target, progress)
    intraday = _fetch_intraday(progress)
    market.reload()
    return {"日线": daily, "30分钟": intraday, "日历到": market.LAST_DATE}


def _last_trading_day_on_or_before(day: str) -> str:
    """`day` 或其之前最近的一个工作日（不查日历，只跳周末）—— 判断「够不够」用。"""
    d = date.fromisoformat(day)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


# ── 日线 ────────────────────────────────────────────────────────────────

def _fetch_daily(until: str, progress=None) -> int:
    store = json.loads(paths.MARKET_DAILY.read_text(encoding="utf-8")) \
        if paths.MARKET_DAILY.exists() else {}
    start = (market.LAST_DATE or "2024-01-01")
    # 从已有末日的前一天起抓：末日那根可能是不完整的（盘中抓的），要让它被覆盖一次
    start = (date.fromisoformat(start) - timedelta(days=1)).strftime("%Y%m%d")

    added = 0
    for sym, name in INDICES:
        rows = _daily_rows(sym, start, until)
        if rows is None:
            continue
        by_day = {r["日期"]: r for r in store.get(name) or []}
        new = sum(1 for r in rows if r["日期"] not in by_day)
        for r in rows:
            by_day[r["日期"]] = r
        store[name] = [by_day[k] for k in sorted(by_day)]
        added += new
        if progress:
            progress(f"  日线 {name}：+{new} → {len(store[name])} 条，"
                     f"止于 {store[name][-1]['日期']}")
        time.sleep(PAUSE)

    paths.MARKET_DAILY.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    return added


def _daily_rows(symbol: str, start: str, end: str) -> list[dict] | None:
    """东财日线。抓不到返回 None —— 不中断，其余指数继续。"""
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily_em(symbol=symbol, start_date=start,
                                        end_date=end.replace("-", ""))
    except Exception as e:
        print(f"  日线 {symbol} 没抓到：{e}")
        return None
    out = []
    for _, r in df.iterrows():
        row = {"日期": str(r["date"])[:10], "开盘": float(r["open"]), "收盘": float(r["close"]),
               "最高": float(r["high"]), "最低": float(r["low"])}
        if "volume" in df.columns:
            row["成交量"] = float(r["volume"])
        out.append(row)
    return out


# ── 30 分钟线 ───────────────────────────────────────────────────────────

def _fetch_intraday(progress=None) -> int:
    paths.MARKET_INTRADAY_DIR.mkdir(parents=True, exist_ok=True)
    added = 0
    for sym, name in INDICES:
        raw = _sina_bars(sym)
        if raw is None:
            continue
        f = paths.MARKET_INTRADAY_DIR / f"{name}_30min.json"
        doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        bars = {b["time"]: b for b in (doc.get("bars") or [])}
        new = sum(1 for b in raw if b["time"] not in bars)
        for b in raw:
            bars[b["time"]] = b
        keys = sorted(bars)[-SINA_DATALEN:]
        doc.update({"index": name, "symbol": sym, "period": 30,
                    "scrape_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "time_range": {"earliest": keys[0][:10], "latest": keys[-1][:10]},
                    "bars": [bars[k] for k in keys]})
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        added += new
        if progress:
            progress(f"  30分钟 {name}：+{new} → {len(keys)} 根，止于 {keys[-1]}")
        time.sleep(PAUSE)
    return added


def _sina_bars(symbol: str) -> list[dict] | None:
    """新浪 30 分钟线。返回的键与旧文件一致（`time`／`open`／`high`／`low`／`close`／`volume`）。"""
    import requests
    try:
        r = requests.get(SINA_API, headers={"User-Agent": SINA_UA}, timeout=30,
                         params={"symbol": symbol, "scale": SINA_SCALE, "ma": "no",
                                 "datalen": str(SINA_DATALEN)})
        r.raise_for_status()
        # 新浪返回的是**非标准 JSON**（键没引号），补上引号再解析
        text = r.text
        for k in ("day", "open", "high", "low", "close", "volume"):
            text = text.replace(f"{k}:", f'"{k}":')
        rows = json.loads(text)
    except Exception as e:
        print(f"  30分钟 {symbol} 没抓到：{e}")
        return None
    return [{"time": b["day"], "open": float(b["open"]), "high": float(b["high"]),
             "low": float(b["low"]), "close": float(b["close"]),
             "volume": float(b["volume"])} for b in rows]


__all__ = ["refresh", "needs_refresh", "INDICES"]
