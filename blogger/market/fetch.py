# -*- coding: utf-8 -*-
"""抓行情 —— 01§10 的实现。三件事在代码里是硬的：

**逐源降级**（01§10.2）—— 每个源依次试，一个不通换下一个；每个源各自重试、间隔逐次拉长。
**源是外部事实，会变**（2026-09-13 东财整片不通），所以降级不是备选，是常态。

**原子写** —— 先写 `.tmp` 再 `os.replace`。直接覆写的话，写到一半崩了会留下**截断的 JSON**：
`market.py` 一 import 就抛异常，**全系统停摆**。

**逐指数落盘** —— 一个指数抓完就写一次。7 个跑完才写的话，第 5 个崩了前 4 个白抓。

**抓不到不算失败**：行情整体没补到时，对应的信号状态记「待验证」（03§3.6 ④），是算不出、
不是算错。够不够齐由 `flow.confirm()` 判 —— 它拿**官方日历**当尺子核（01§10.4），不归这里管。
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from pathlib import Path

from blogger.common import market, params, paths

# 七个主指数（双创不单列，由创业板指与科创50 各半合成）
INDICES = [("sh000001", "上证指数"), ("sh000300", "沪深300"), ("sz399006", "创业板指"),
           ("sh000016", "上证50"), ("sh000905", "中证500"), ("sh000852", "中证1000"),
           ("sh000688", "科创50")]

SINA_API = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "CN_MarketData.getKLineData")
SINA_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
SINA_SCALE = "30"
SINA_DATALEN = params.get("market.sina_datalen", 6000)   # 30 分钟 × 6000 根 ≈ 750 交易日，够回溯
PAUSE = params.get("market.pause", 0.4)          # 每个指数之间的间隔（秒），防风控
RETRIES = params.get("market.retries", 3)        # 同一个源试几次
RETRY_DELAY = params.get("market.retry_delay", 3)  # 第一次重试前等几秒，逐次翻倍

CLOSE_HOUR = 15                                  # 收盘（01§10.4：收盘后才要求当天）


# ── 该到哪天 ────────────────────────────────────────────────────────────

def due_day(until: str = "") -> str:
    """该到哪一天（01§10.4）。

    | 今天 | 该到 |
    |:---|:---|
    | 交易日、且已过 15:00 | **今天** |
    | 其余 | 今天或之前**最近的一个交易日** |

    `until` 传了具体日期就是在回溯，只管「不晚于它」，不看收盘没有。

    **走官方日历** —— 它是数日子的唯一依据（01§10.3）。**日历缺失或过期 → 硬失败**，
    不退回只跳周末：凑合出来的日子会把长假算成缺、把缺算成休市。
    """
    day = (until or date.today().isoformat())[:10]
    days = official_days()
    if not days:
        raise RuntimeError(
            f"交易日历不可用（本地这份没覆盖到 {date.today().isoformat()}）—— "
            f"日历是数日子的唯一依据，没有退路。先跑：python -m blogger.market"
        )
    if not until and day in set(days) and datetime.now().hour >= CLOSE_HOUR:
        return day
    earlier = [d for d in days if d <= day]
    return earlier[-1] if earlier else day


def missing_days(after: str, want: str) -> list[str]:
    """`after` 之后、`want` 之前（含 `want`）的交易日 —— **逐个列名**用，不报个「差 N 天」。

    走官方日历，**长假不会被算成缺**。
    """
    if not after:
        return []
    return [d for d in official_days() if after < d <= want]


# ── 官方日历 ────────────────────────────────────────────────────────────



def official_days() -> tuple[str, ...]:
    """官方交易日历（升序）。**它就是系统日历**（01§10.3）—— 数日子与核对共用这一份，不是两把尺子。

    本地这份**没覆盖到今天**就算过期，返回空 —— 调用方据此触发重抓，而不是拿一份过期的日子凑合。
    **日历缺了没有退路**（01§10.3）：过期 → 重抓；重抓不到 → 硬失败。
    """
    days = market.CAL
    if not days or days[-1] < date.today().isoformat():
        return ()
    return days


def calendar_stale() -> bool:
    return not official_days()


def _fetch_calendar(progress=None) -> int:
    """抓官方交易日历 → `data/market/trade_cal.json`。**抓不到就抛** —— 日历是硬前提。"""
    import akshare as ak
    df = _try("官方日历", ak.tool_trade_date_hist_sina)
    days = sorted({str(d)[:10] for d in df["trade_date"]})
    _write_json(paths.MARKET_CAL, {"scrape_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                   "days": days})
    market.reload()
    if progress:
        progress(f"  官方日历：{len(days)} 天，{days[0]} ~ {days[-1]}")
    return len(days)


# ── 抓 ──────────────────────────────────────────────────────────────────

def needs_refresh(until: str = "") -> bool:
    """要不要抓一次（01§10.4）。**日历过期也算要抓** —— 它得先补上，下游才数得出日子。"""
    if calendar_stale():
        return True
    return market.LAST_DATE < due_day(until)


def refresh(until: str = "", progress=None) -> dict:
    """把官方日历、30 分钟线补到 `until`（默认今天）。返回补了什么。

    **日历第一个抓** —— 后面的「该到哪天」要拿它算；抓不到就抛（01§10.3）。
    """
    if calendar_stale():
        _fetch_calendar(progress)
    intraday = _fetch_intraday(progress)
    market.reload()
    return {"30分钟": intraday, "行情到": market.LAST_DATE,
            "日历到": official_days()[-1] if official_days() else "**没有**"}


def _try(label: str, fn):
    """同一个源试 `market.retries` 次，间隔从 `market.retry_delay` 秒起、逐次翻倍。

    全失败抛最后一个异常 —— 交给调用方决定是降级还是放弃。
    """
    delay, last = RETRY_DELAY, None
    for i in range(1, RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < RETRIES:
                print(f"    {label} 第 {i} 次没成（{e}），{delay:g} 秒后再试")
                time.sleep(delay)
                delay *= 2
    raise last


def _write_json(path: Path, doc) -> None:
    """**原子写**：先写 `.tmp`，再 `os.replace` —— 同目录内改名是原子的。

    直接覆写的话，写到一半崩了会留下截断的 JSON，`market.py` 一 import 就抛异常，
    **全系统停摆**。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# ── 30 分钟线 ───────────────────────────────────────────────────────────

def _bar_key(t: str) -> str:
    """30 分钟线的键统一成 `YYYY-MM-DD HH:MM:SS`。

    **旧文件里有 `HH:MM` 形态的同一条 bar**（旧栈留下的），不归一就合不掉：

    - 同一条 bar 存两份，6000 根的窗口里**一半是重复**，真实历史被挤掉一半
    - 每跑一次都「新增」一批，看着像抓了很多，其实一条新的都没有

    两种形态的**数值完全相同**，所以只是白占地方，没算错价。
    """
    return t if len(t) >= 19 else t + ":00"


def _fetch_intraday(progress=None) -> int:
    added = 0
    for sym, name in INDICES:
        raw = _sina_bars(sym)
        if raw is None:
            continue
        f = paths.MARKET_INTRADAY_DIR / f"{name}_30min.json"
        doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        bars = {_bar_key(b["time"]): b for b in (doc.get("bars") or [])}
        new = sum(1 for b in raw if _bar_key(b["time"]) not in bars)
        for b in raw:
            bars[_bar_key(b["time"])] = b      # 新抓的覆盖旧的
        keys = sorted(bars)[-SINA_DATALEN:]
        doc.update({"index": name, "symbol": sym, "period": 30,
                    "scrape_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "time_range": {"earliest": keys[0][:10], "latest": keys[-1][:10]},
                    "bars": [bars[k] for k in keys]})
        _write_json(f, doc)                          # 抓一个写一个
        added += new
        if progress:
            progress(f"  30分钟 {name}：+{new} → {len(keys)} 根，止于 {keys[-1]}")
        time.sleep(PAUSE)
    return added


def _sina_bars(symbol: str) -> list[dict] | None:
    """新浪 30 分钟线。返回的键与旧文件一致（`time`／`open`／`high`／`low`／`close`／`volume`）。"""
    import requests

    def once() -> list[dict]:
        r = requests.get(SINA_API, headers={"User-Agent": SINA_UA}, timeout=30,
                         params={"symbol": symbol, "scale": SINA_SCALE, "ma": "no",
                                 "datalen": str(SINA_DATALEN)})
        r.raise_for_status()
        # 新浪返回的是**非标准 JSON**（键没引号），补上引号再解析
        text = r.text
        for k in ("day", "open", "high", "low", "close", "volume"):
            text = text.replace(f"{k}:", f'"{k}":')
        return json.loads(text)

    try:
        rows = _try(f"30分钟 {symbol}", once)
    except Exception as e:
        print(f"  30分钟 {symbol} 没抓到：{e}")
        return None
    return [{"time": b["day"], "open": float(b["open"]), "high": float(b["high"]),
             "low": float(b["low"]), "close": float(b["close"]),
             "volume": float(b["volume"])} for b in rows]


__all__ = ["refresh", "needs_refresh", "due_day", "missing_days", "official_days",
           "calendar_stale", "INDICES"]
