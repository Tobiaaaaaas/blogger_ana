# -*- coding: utf-8 -*-
"""抓行情 —— 01§10 的实现。三件事在代码里是硬的：

**逐源降级**（01§10.2）—— 每个源依次试，一个不通换下一个；每个源各自重试、间隔逐次拉长。
**源是外部事实，会变**（2026-09-13 东财整片不通），所以降级不是备选，是常态。

**原子写** —— 先写 `.tmp` 再 `os.replace`。直接覆写的话，写到一半崩了会留下**截断的 JSON**：
`market.py` 一 import 就抛异常，**全系统停摆**。

**逐指数落盘** —— 一个指数抓完就写一次。7 个跑完才写的话，第 5 个崩了前 4 个白抓。

**抓不到不算失败**：行情缺一段，对应的信号状态记「待验证」（03§3.6），是算不出、不是算错。
够不够齐由 `flow.confirm()` 判 —— 它拿**官方日历**当尺子核（01§10.4），不归这里管。
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
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

    **走官方日历** —— 只跳周末的话，长假里会连报七天假警。
    官方日历取不到就退回只跳周末，**退得响**（`flow` 会把这件事打出来）。
    """
    day = (until or date.today().isoformat())[:10]
    days = official_days()
    if days:
        if not until and day in set(days) and datetime.now().hour >= CLOSE_HOUR:
            return day
        earlier = [d for d in days if d <= day]
        return earlier[-1] if earlier else day
    return _weekday_on_or_before(day)


def missing_days(after: str, want: str) -> list[str]:
    """`after` 之后、`want` 之前（含 `want`）的交易日 —— **逐个列名**用，不报个「差 N 天」。

    有官方日历就用它，**长假不会被算成缺**。
    """
    if not after:
        return []
    days = official_days()
    if days:
        return [d for d in days if after < d <= want]
    out, d, hi = [], date.fromisoformat(after) + timedelta(days=1), date.fromisoformat(want)
    while d <= hi:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _weekday_on_or_before(day: str) -> str:
    """`day` 或其之前最近的一个工作日（只跳周末）。官方日历取不到时的退路。"""
    d = date.fromisoformat(day)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


# ── 官方日历：核对的尺子 ────────────────────────────────────────────────

_CAL: tuple[str, ...] = ()


def official_days() -> tuple[str, ...]:
    """官方交易日历（升序）。**只当核对的尺子**，系统日历仍是「有上证行情的那天」（01§10.3）。

    **拿数据比数据，数据缺了会自己证明自己齐全** —— 所以核对必须另有一份不同源的日历。

    本地这份没覆盖到今天就算**过期**，返回空 —— 调用方退回只跳周末。
    退得响，好过拿一份过期的尺子量出「齐了」。
    """
    if not _CAL:
        _load_cal()
    days = _CAL
    if not days or days[-1] < date.today().isoformat():
        return ()
    return days


def calendar_stale() -> bool:
    return not official_days()


def _load_cal() -> None:
    global _CAL
    try:
        doc = json.loads(paths.MARKET_CAL.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        _CAL = ()
        return
    _CAL = tuple(sorted(str(d)[:10] for d in (doc.get("days") or [])))


def _fetch_calendar(progress=None) -> int:
    """抓官方交易日历 → `data/market/trade_cal.json`。"""
    import akshare as ak
    df = _try("官方日历", ak.tool_trade_date_hist_sina)
    days = sorted({str(d)[:10] for d in df["trade_date"]})
    _write_json(paths.MARKET_CAL, {"scrape_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                   "days": days})
    global _CAL
    _CAL = tuple(days)
    if progress:
        progress(f"  官方日历：{len(days)} 天，{days[0]} ~ {days[-1]}")
    return len(days)


# ── 抓 ──────────────────────────────────────────────────────────────────

def needs_refresh(until: str = "") -> bool:
    """日历够不够到**该到的那天**（01§10.4）。够就不必再抓。"""
    return market.LAST_DATE < due_day(until)


def refresh(until: str = "", progress=None) -> dict:
    """把日线、30 分钟线与官方日历补到 `until`（默认今天）。返回补了什么。"""
    target = until or date.today().isoformat()
    daily = _fetch_daily(target, progress)
    intraday = _fetch_intraday(progress)
    if calendar_stale():
        try:
            _fetch_calendar(progress)
        except Exception as e:
            print(f"  官方日历没抓到：{e}")     # 不中断 —— 核对时退回只跳周末并注明
    market.reload()
    return {"日线": daily, "30分钟": intraday, "日历到": market.LAST_DATE,
            "官方日历": official_days()[-1] if official_days() else ""}


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
        _write_json(paths.MARKET_DAILY, store)      # 抓一个写一个 —— 崩了不连累已抓到的
        added += new
        if progress:
            progress(f"  日线 {name}：+{new} → {len(store[name])} 条，"
                     f"止于 {store[name][-1]['日期']}")
        time.sleep(PAUSE)
    return added


def _daily_rows(symbol: str, start: str, end: str) -> list[dict] | None:
    """指数日线。**两个源依次降级**：东财（能按区间取）→ 新浪（全量历史，列名一致）。

    抓不到返回 None —— 不中断，其余指数继续。

    **不能只挂一个源。** 2026-09-13 东财整片连不上，日历随即停在上一个交易日；
    而日历一停，下游每条信号都退化成「待验证」，报告看上去却一切正常 ——
    这种「静悄悄地退化」比抓不到还难发现。
    """
    import akshare as ak
    df = None
    for label, fn in (
        ("东财", lambda: ak.stock_zh_index_daily_em(
            symbol=symbol, start_date=start, end_date=end.replace("-", ""))),
        ("新浪", lambda: ak.stock_zh_index_daily(symbol=symbol)),
    ):
        try:
            got = _try(f"日线 {symbol} 走{label}", fn)
        except Exception as e:
            print(f"  日线 {symbol} 走{label}没抓到：{e}")
            continue
        if got is not None and len(got):
            df = got
            break
    if df is None:
        print(f"  日线 {symbol} 两个源都没抓到")
        return None

    since = f"{start[:4]}-{start[4:6]}-{start[6:8]}" if len(start) == 8 else start[:10]
    out = []
    for _, r in df.iterrows():
        day = str(r["date"])[:10]
        if day < since:            # 全量源会把整段历史带回来，只留区间内的
            continue
        row = {"日期": day, "开盘": float(r["open"]), "收盘": float(r["close"]),
               "最高": float(r["high"]), "最低": float(r["low"])}
        if "volume" in df.columns:
            row["成交量"] = float(r["volume"])
        out.append(row)
    return out


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
