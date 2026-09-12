# -*- coding: utf-8 -*-
"""行情：交易日历、现值、收盘价、验证终点、交易日跨度。

**这一层是 02 与 03 的公共地基。** 02 喂给模型的「行情注记」和 03 事后打分的「参考价」
必须**同源同值** —— 模型据以判方向的数字，就是引擎据以打分的数字。所以两边都调这里的
`ref_price()`，绝不各算各的。

两个数据源：
- `data/market/market_data.json` —— 日线，**交易日历以「上证指数」的日期序列为唯一基准**
- `data/market/intraday/<指数>_30min.json` —— 30 分钟线，只在算「发帖时刻现值」时用
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from blogger.common import paths

# 八个合法对象的别名归一（板块 → 指数）
IDX_ALIASES = {"上证综指": "上证指数", "上证": "上证指数", "综指": "上证指数"}

# 有 30 分钟线的主指数（双创不单列，由创业板指与科创50 各半合成）
NOTE_INDICES = ["上证指数", "创业板指", "沪深300", "上证50", "中证500", "中证1000", "科创50"]

SESSION_AM = (9 * 60 + 30, 11 * 60 + 30)
SESSION_PM = (13 * 60, 15 * 60)


def normalize_idx(idx: str) -> str:
    return IDX_ALIASES.get(idx, idx)


# ── 装载 ────────────────────────────────────────────────────────────────

def _load_daily() -> dict:
    with open(paths.MARKET_DAILY, encoding="utf-8") as f:
        return json.load(f)


def _load_intraday() -> dict:
    """{指数: [(日期, [(hhmm, bar), …]), …]}，按日期升序。缺文件跳过。"""
    out = {}
    for idx in NOTE_INDICES:
        p = paths.MARKET_INTRADAY_DIR / f"{idx}_30min.json"
        if not p.exists():
            continue
        bars = (json.loads(p.read_text(encoding="utf-8")) or {}).get("bars", [])
        by_day: dict[str, list] = {}
        for b in bars:
            by_day.setdefault(b["time"][:10], []).append((b["time"][11:16], b))
        out[idx] = sorted((d, sorted(rows, key=lambda x: x[0])) for d, rows in by_day.items())
    return out


DAILY = _load_daily()
# 交易日历：有上证行情的那天就是交易日。**全系统只此一份**。
CAL = sorted(r["日期"] for r in DAILY["上证指数"])
CAL_SET = set(CAL)
INTRADAY = _load_intraday()

LAST_DATE = CAL[-1] if CAL else ""


def reload() -> None:
    """补完行情后重新载入 —— 本层在 import 时就把行情读进内存了。

    **补行情之后必须调一次**，否则同一进程里算出来的还是补之前的那份。
    """
    global DAILY, CAL, CAL_SET, INTRADAY, LAST_DATE
    DAILY = _load_daily()
    CAL = sorted(r["日期"] for r in DAILY["上证指数"])
    CAL_SET = set(CAL)
    INTRADAY = _load_intraday()
    LAST_DATE = CAL[-1] if CAL else ""


def is_trading_day(d: str) -> bool:
    return d in CAL_SET


def prev_td(d: str) -> str | None:
    """d 之前最近一个交易日（不含 d）。"""
    for x in reversed(CAL):
        if x < d:
            return x
    return None


def next_td(d: str) -> str | None:
    """d 之后最近一个交易日（不含 d）。"""
    for x in CAL:
        if x > d:
            return x
    return None


def base_day(pub_day: str) -> str | None:
    """发帖日的锚：**发帖日若是交易日就用它，否则用它前一个交易日**。

    `span` 从这里起算 —— 周六发的帖，锚在周五。
    """
    return pub_day if is_trading_day(pub_day) else prev_td(pub_day)


# ── 参考价：发帖时刻的现值 ──────────────────────────────────────────────

def _minutes(pub: str) -> int | None:
    try:
        return int(pub[11:13]) * 60 + int(pub[14:16])
    except (TypeError, ValueError, IndexError):
        return None


def _anchorable(pub_day: str) -> bool:
    """发帖日能不能用「上一交易日收盘」当现值锚。

    日历覆盖范围内的非交易日 = 真周末/假日 → 行。日历末日之后的**周末** → 也行（博主谈的就是
    最新收盘）。但日历末日之后的**工作日**没法确认是不是交易日（可能已经开盘了）→ 宁可不给价，
    也不锚一个陈旧价上去。
    """
    if pub_day <= LAST_DATE:
        return True
    try:
        return date.fromisoformat(pub_day).weekday() >= 5
    except ValueError:
        return False


def _intraday_price(idx: str, pub: str) -> tuple[float | None, str | None]:
    """单指数（不含双创）的现值，附快照性质。

    快照性质分四种：`session` 盘中当根开盘 / `lunch` 午休 11:30 收盘 /
    `after` 盘后 15:00 收盘 / `prev` 上一交易日收盘（盘前或休市）。
    """
    days = INTRADAY.get(normalize_idx(idx))
    if not days:
        return None, None
    pub_day, hhmm = pub[:10], pub[11:16]
    hm = _minutes(pub)
    if hm is None or len(hhmm) < 5:
        return None, None

    if not is_trading_day(pub_day) or hm < SESSION_AM[0]:
        if not is_trading_day(pub_day) and not _anchorable(pub_day):
            return None, None
        prev = prev_td(pub_day)
        if prev is None:
            return None, None
        for day, rows in days:
            if day == prev:
                return rows[-1][1]["close"], "prev"
        return None, None

    for day, rows in days:
        if day != pub_day:
            continue
        if SESSION_AM[0] <= hm < SESSION_AM[1] or SESSION_PM[0] <= hm < SESSION_PM[1]:
            # 盘中 → 所处那根 30 分钟 bar 的开盘价。
            # 取**严格大于**：整点发帖（如 10:00）拿的是刚开盘那根 = 此刻现价，
            # 不用 `>=` 回落上一根（那会让 10:00 拿到的价比 10:01 还旧一档）。
            for t, b in rows:
                if t > hhmm:
                    return b["open"], "session"
            return None, None
        if SESSION_AM[1] <= hm < SESSION_PM[0]:
            for t, b in rows:
                if t == "11:30":
                    return b["close"], "lunch"
            return None, None
        return rows[-1][1]["close"], "after"      # 盘后 → 当日 15:00 收盘
    return None, None


def ref_price(idx: str, pub: str) -> float | None:
    """**参考价** —— 发帖那一刻该指数的现值。取不到返回 None。

    双创 = 创业板指与科创50 各占一半。
    """
    if idx == "双创":
        a, b = ref_price("创业板指", pub), ref_price("科创50", pub)
        return (a + b) / 2 if a is not None and b is not None else None
    return _intraday_price(idx, pub)[0]


def snapshot_label(pub: str) -> str | None:
    """发帖时刻的快照性质，写进行情注记的头部。"""
    pub_day, hhmm = pub[:10], pub[11:16]
    hm = _minutes(pub)
    if hm is None or len(hhmm) < 5:
        return None
    if not is_trading_day(pub_day) or hm < SESSION_AM[0]:
        if not is_trading_day(pub_day) and not _anchorable(pub_day):
            return None
        return "上一交易日收盘(盘前或休市)"
    if SESSION_AM[0] <= hm < SESSION_AM[1] or SESSION_PM[0] <= hm < SESSION_PM[1]:
        return f"{hhmm}盘中(30分钟线当根开盘)"
    if SESSION_AM[1] <= hm < SESSION_PM[0]:
        return "午休(11:30收盘)"
    return "盘后(15:00收盘)"


def pub_note(pub: str) -> str | None:
    """**行情注记** —— 喂给模型的一行外部事实：发帖时刻七个主指数的现值（**双创不单列**）。

    七个全取不到 → None，**取不到就不开解析**。
    """
    label = snapshot_label(pub)
    if label is None:
        return None
    vals = [f"{i}≈{p:.2f}" for i in NOTE_INDICES if (p := ref_price(i, pub)) is not None]
    if not vals:
        return None
    return f"[行情@发帖 {pub[:16]}] {label}：" + " ".join(vals)


# ── 验证终点与终点价 ────────────────────────────────────────────────────

def _last_td_of_week(d: str) -> str | None:
    iso = date.fromisoformat(d).isocalendar()
    days = [x for x in CAL
            if date.fromisoformat(x).isocalendar()[:2] == iso[:2]]
    return days[-1] if days else None


def _first_td_of_week(d: str) -> str | None:
    iso = date.fromisoformat(d).isocalendar()
    days = [x for x in CAL
            if date.fromisoformat(x).isocalendar()[:2] == iso[:2]]
    return days[0] if days else None


def _settle(x: str | None) -> str | None:
    """验证终点落在非交易日 → 顺延到之后最近的一个交易日。"""
    if x is None:
        return None
    return x if is_trading_day(x) else next_td(x)


def _weekday_of_week(d: str, weekday: int, plus_weeks: int = 0) -> str | None:
    """发帖当周（或下 N 周）的那个星期几。weekday：周一=1 … 周五=5。"""
    y, w, _ = date.fromisoformat(d).isocalendar()
    monday = date.fromisocalendar(y, w, 1) + timedelta(weeks=plus_weeks)
    return (monday + timedelta(days=weekday - 1)).isoformat()


WEEKDAY_SPECS = {"monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5}


def _last_td_of_month(d: str) -> str | None:
    ym = d[:7]
    days = [x for x in CAL if x[:7] == ym]
    return days[-1] if days else None


def _next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def endpoint(pub: str, spec: str) -> str | None:
    """**验证终点** —— 这条观点信号该看哪一天。

    找不到（`long`、或算出来超出日历覆盖）返回 None。
    """
    day = pub[:10]
    base = base_day(day)
    if base is None:
        return None

    if spec == "long":
        return None
    if spec == "today":
        # 非交易日发布的「今天」类由 03 判成「报错」；这里顺延只是防御，别让它崩
        return day if is_trading_day(day) else next_td(day)

    if spec.startswith("t") and spec[1:].isdigit():
        n = int(spec[1:])
        i = CAL.index(base) + n
        return CAL[i] if 0 <= i < len(CAL) else None

    if spec == "week":
        return _last_td_of_week(day)
    if spec in ("nweek", "nweek_first"):
        nxt = (date.fromisoformat(day) + timedelta(days=7)).isoformat()
        return _first_td_of_week(nxt) if spec == "nweek_first" else _last_td_of_week(nxt)
    if spec == "month":
        return _last_td_of_month(day)
    if spec == "nmonth":
        return _last_td_of_month(_next_month(day[:7]) + "-01")

    if spec.startswith("d:"):
        target = spec[2:]
        if not _ok_date(target):
            return None
        return _settle(target)

    # 周几：monday~friday 指本周的那一天，nmonday~nfriday 指下周的那一天
    if spec in WEEKDAY_SPECS:
        return _settle(_weekday_of_week(day, WEEKDAY_SPECS[spec]))
    if spec.startswith("n") and spec[1:] in WEEKDAY_SPECS:
        return _settle(_weekday_of_week(day, WEEKDAY_SPECS[spec[1:]], plus_weeks=1))

    return None


def _ok_date(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def ep_close(idx: str, ep: str) -> float | None:
    """**终点价** —— 验证终点那天的收盘价。取不到返回 None。"""
    if idx == "双创":
        a, b = ep_close("创业板指", ep), ep_close("科创50", ep)
        return (a + b) / 2 if a is not None and b is not None else None

    want = normalize_idx(idx)
    # 主指数先用 30 分钟线的当日末根；没有就走日线收盘
    for day, rows in INTRADAY.get(want, []):
        if day == ep:
            return rows[-1][1]["close"]
    for r in DAILY.get(want, []):
        if r["日期"] == ep:
            return r["收盘"]
    return None


def span(pub: str, ep: str) -> int | None:
    """**交易日跨度** —— 发帖日到验证终点隔了几个交易日。

    从发帖日的锚（发帖日是交易日就用它，否则前一交易日）起算。
    """
    base = base_day(pub[:10])
    if base is None or ep not in CAL_SET or base not in CAL_SET:
        return None
    return CAL.index(ep) - CAL.index(base)


def span_bucket(n: int) -> str:
    """按跨度分两档：`span ≤1` 超短期 / `span ≥2` 波段。"""
    return "超短期" if n <= 1 else "波段"


# ── 合法域 ──────────────────────────────────────────────────────────────

VALID_IDX = {"上证指数", "上证50", "沪深300", "中证500", "中证1000", "创业板指", "科创50", "双创"}

# spec 全表。`tN` 的 N 走数字，`d:` 的日期要真实存在，其余是固定值。
FIXED_SPECS = ({"today", "week", "nweek", "nweek_first", "month", "nmonth", "long"}
               | set(WEEKDAY_SPECS)
               | {f"n{k}" for k in WEEKDAY_SPECS})


def spec_ok(spec: str) -> bool:
    if not isinstance(spec, str) or not spec:
        return False
    if spec in FIXED_SPECS:
        return True
    if spec.startswith("t") and spec[1:].isdigit():
        return 1 <= int(spec[1:]) <= 30
    if spec.startswith("d:"):
        return _ok_date(spec[2:])
    return False
