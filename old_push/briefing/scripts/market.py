# -*- coding: utf-8 -*-
"""大盘行情背景：指数实时点位/涨跌幅/成交额。

数据源（免费、无需密钥）：
  主：腾讯行情接口 qt.gtimg.cn（字段 [3]现价 [4]昨收 [30]时间戳 [32]涨跌幅% [37]成交额万）
  兜底1：新浪 hq.sinajs.cn
  兜底2：仓库内 data/market/market_data.json 最近收盘（离线/接口全挂时）
"""
import json
import logging
import os
import re
import sys
from datetime import datetime

import requests

from . import paths

log = logging.getLogger("briefing")

UTILS_DIR = os.path.join(paths.REPO_ROOT, "scripts", "utils")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36")

# 需要展示的指数：symbol, 中文名
QUOTES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
]

TENCENT_URL = "https://qt.gtimg.cn/q={}"
SINA_URL = "https://hq.sinajs.cn/list={}"


def _parse_tencent(text):
    m = re.search(r'v_[a-z]+\d+="(.*)"', text)
    if not m:
        return None
    f = m.group(1).split("~")
    try:
        return {
            "name": f[1], "code": f[2],
            "price": float(f[3]), "prev_close": float(f[4]),
            "ts": f[30], "pct": float(f[32]),
            "amount_wan": float(f[37]),  # 成交额（万元）
        }
    except (IndexError, ValueError):
        return None


def _parse_sina(text):
    m = re.search(r'="(.*)"', text)
    if not m:
        return None
    f = m.group(1).split(",")
    try:
        prev = float(f[2])
        price = float(f[3])
        return {
            "name": f[0], "price": price, "prev_close": prev,
            "pct": (price - prev) / prev * 100 if prev else 0.0,
            "amount_wan": float(f[9]) / 1e4,  # 元 → 万元
        }
    except (IndexError, ValueError):
        return None


def _fetch_tencent(symbol):
    r = requests.get(TENCENT_URL.format(symbol), timeout=10,
                     headers={"User-Agent": UA, "Referer": "https://gu.qq.com/"})
    r.encoding = "gbk"
    return _parse_tencent(r.text)


def _fetch_sina(symbol):
    r = requests.get(SINA_URL.format(symbol), timeout=10,
                     headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"})
    r.encoding = "gbk"
    return _parse_sina(r.text)


def _fallback_from_repo(name):
    """接口全挂时用仓库日线最近收盘。"""
    try:
        fp = os.path.join(paths.MARKET_DIR, "market_data.json")
        with open(fp, encoding="utf-8") as f:
            mkt = json.load(f)
        rows = mkt.get(name, [])
        if rows:
            last = rows[-1]
            prev = rows[-2] if len(rows) > 1 else last
            price, prev_close = last["收盘"], prev["收盘"]
            pct = (price - prev_close) / prev_close * 100 if prev_close else 0.0
            return {"name": name, "price": price, "prev_close": prev_close,
                    "pct": pct, "amount_wan": None, "source": "repo-daily"}
    except Exception:
        pass
    return None


def fetch_quotes():
    """返回 {指数名: {name, price, prev_close, pct, amount_wan, source}}。"""
    out = {}
    for symbol, name in QUOTES:
        q = None
        try:
            q = _fetch_tencent(symbol)
        except Exception:
            q = None
        if not q:
            try:
                q = _fetch_sina(symbol)
            except Exception:
                q = None
        if not q:
            q = _fallback_from_repo(name)
        if q:
            q.setdefault("source", "tencent" if q.get("ts") is not None else "sina")
            out[name] = q
    return out


def _fmt_amount(wan):
    """万元 → 亿/万亿 可读字符串。"""
    if wan is None:
        return "?"
    yi = wan / 1e4
    if yi >= 10000:
        return f"{yi / 1e4:.2f}万亿"
    return f"{yi:.0f}亿"


def market_line(quotes: dict) -> str:
    """渲染卡片行情行：上证 xx (+0.32%) · 深成 … · 两市 1234亿"""
    parts = []
    for name in ["上证指数", "深证成指", "创业板指"]:
        q = quotes.get(name)
        if not q:
            continue
        sign = "+" if q["pct"] >= 0 else ""
        parts.append(f"{q['name'].replace('指数', '')} {q['price']:.2f} {sign}{q['pct']:.2f}%")
    # 两市成交额 = 沪市 + 深市
    total_wan = sum(q["amount_wan"] for k, q in quotes.items()
                    if q["amount_wan"] and k in ("上证指数", "深证成指"))
    if total_wan:
        parts.append(f"两市 {_fmt_amount(total_wan)}")
    return " · ".join(parts) if parts else "行情数据获取失败"


_UTILS = {}


def _util(name):
    """按文件路径载入 `scripts/utils/` 下的抓取器 —— 它们只有手动 CLI、不在任何包里。

    载入结果缓存：其中一个 import akshare，重载一次要好几秒。"""
    if name not in _UTILS:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"_oldpush_util_{name}", os.path.join(UTILS_DIR, f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _UTILS[name] = mod
    return _UTILS[name]


def refresh_history(intraday=True):
    """把仓库行情补到今天：**日线**（`opinion.ref_price` 的交易日历来源）＋ **30 分钟线**（发帖现值注记的来源）。

    两个抓取器原本只有手动 CLI、没有调度 —— 推送链起档时调一次，增量、抓取失败只记一行不抛
    （**备不到本档时刻由 `history_ready` 判「本档不推」，不在这里抛**）。
    补完数据必须重载 `opinion.ref_price`（它导入即装载，不重载看不到新数据）。

    周末整天不抓（行情停在最近交易日是对的，注记走 `_prev_ok` 的周末分支）；
    30 分钟线在交易日**每档都抓**（盘中一直在长，早档抓过的覆盖不到晚档的帖）；
    日线**只在盘后补**（它当天收盘前没有今天那一行，盘前盘中抓是白打东财，一档一次会把它打爆）。
    """
    now = datetime.now()
    if now.weekday() >= 5:
        log.info("行情：周末不抓，用最近交易日收盘")
        return

    today = now.strftime("%Y-%m-%d")
    if now.hour >= 15:
        try:
            last = _last_daily_date()
            if last < today:
                _ok, failed = _util("fetch_market_data").refresh(
                    start=(last.replace("-", "") if last else None), verbose=False)
                log.info("日线：末日 %s%s", _last_daily_date() or "?",
                         f"，失败 {', '.join(failed)}" if failed else "")
        except Exception as e:
            log.warning("日线抓取失败（交易日历仍靠 30 分钟线）：%s", e)

    if intraday:
        try:
            ok, failed = _util("fetch_market_intraday").refresh(verbose=False)
            log.info("30分钟线：成功 %d/%d%s", len(ok), len(ok) + len(failed),
                     f"，失败 {', '.join(failed)}" if failed else "")
        except Exception as e:
            log.warning("30分钟线抓取失败：%s", e)

    _o_ref().reload()


def prepare_history(now):
    """备料行情到本档时刻（02§2.2 / 06§5.3）。返回是否备到 —— False = 本档不推。

    已经到本档时刻 → 跳过，不重复抓；没到 → 补一次；补完还不到 → False。
    """
    if history_ready(now):
        return True
    refresh_history()
    return history_ready(now)


# 30 分钟线的八个收线时刻（02§2.1：每指数每日 8 根，bar 时间 = 收盘时间）
BAR_TIMES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")


def history_ready(now):
    """本档要的 30 分钟线在不在（02§2.2 / 06§5.3）。False = 本档不推。

    要的那根 = **结束时刻不晚于本档时刻的最后一根**；本档落在当天第一根收出来之前
    （`09:00`／`09:30` 两档，以及盘前、非交易日）→ 退到上一交易日末根。

    **逐指数核** —— 注记点到哪个指数就要哪个指数的线（`ref_price.NOTE_INDICES`，七个）。
    缺一个就当整档没备到：宁可不出卡，也不静默出一张少了注记的卡。
    """
    o_ref = _o_ref()
    day, hm = _due_bar(now, o_ref)
    for idx in o_ref.NOTE_INDICES:
        rows = _bars_on(o_ref.INTRADAY.get(idx, []), day)
        if not rows or not any(t >= hm for t, _ in rows):
            return False
    return True


def _bars_on(days, day):
    """某指数某一天的 30 分钟线 → [(时刻, bar), …]（没有 → 空表）。"""
    for d, rows in days:
        if d == day:
            return rows
    return []


def _due_bar(now, o_ref):
    """本档需要的那根 30 分钟线 → (日期, 时刻)。

    **门要的不是注记取价那根**（02§2.1：盘中取结束时刻严格晚于发帖时刻的第一根）—— 门只问
    「本档时刻的数据到没到」，按取价那根核，每个盘中档都会当场判「本档不推」（06§5.3）。
    """
    today, hm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    if today in o_ref.CAL_SET:
        due = [t for t in BAR_TIMES if t <= hm]
        if due:
            return today, due[-1]
    return (o_ref.prev_td(today) or today), "15:00"


def _o_ref():
    """`opinion.ref_price` —— briefing 是独立部署单元，兜底把仓根补进 sys.path。"""
    try:
        from opinion import ref_price as o_ref
    except ImportError:
        if not any(os.path.abspath(p) == os.path.abspath(paths.REPO_ROOT) for p in sys.path):
            sys.path.insert(0, paths.REPO_ROOT)
        from opinion import ref_price as o_ref
    return o_ref


def _last_daily_date():
    """日线文件的末根交易日（读不到 → 空串）。"""
    try:
        with open(os.path.join(paths.MARKET_DIR, "market_data.json"), encoding="utf-8") as f:
            rows = (json.load(f) or {}).get("上证指数") or []
        return rows[-1]["日期"] if rows else ""
    except Exception:
        return ""
