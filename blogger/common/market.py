# -*- coding: utf-8 -*-
"""行情：交易日历、现值、收盘价、验证终点、交易日跨度。

**这一层是 02 与 03 的公共地基。** 02 喂给模型的「行情注记」和 03 事后打分的「参考价」
必须**同源同值** —— 模型据以判方向的数字，就是引擎据以打分的数字。所以两边都调这里的
`ref_price()`，绝不各算各的。

两个数据源：
- `data/market/trade_cal.json` —— **交易日历**，官方日历、含未来。数日子只认它
- `data/market/intraday/<指数>_30min.json` —— 30 分钟线，算参考价、终点价，并给出**行情水位**（数据到哪天）

**日历与行情是两件事，不许互相倒推**（01§10.3）：日历缺一天是休市，行情缺一天是缺口。
合在一起时后者会被前者悄悄吃掉 —— 那天既算不出价、也数不进日子。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from blogger.common import params, paths

# 八个合法对象的别名归一（板块 → 指数）—— 02§5.2 的映射表，逐行对着抄。
# 本名不列，`normalize_idx` 对它们本来就是恒等。
IDX_ALIASES = {
    "创业板": "创业板指", "创业板ETF": "创业板指",
    "科创": "科创50", "科创板": "科创50",
    "半导体": "科创50", "芯片": "科创50",
    "小盘": "中证1000", "成长": "中证1000",
    "50ETF": "上证50", "老登": "上证50", "大金融": "上证50",
    "银行": "上证50", "保险": "上证50", "券商": "上证50",
    "证券": "上证50", "白酒": "上证50", "酒": "上证50",
    "上证综指": "上证指数", "上证": "上证指数", "综指": "上证指数",
    "大盘": "上证指数",
}

# 有 30 分钟线的主指数（双创不单列，由创业板指与科创50 各半合成）
NOTE_INDICES = ["上证指数", "创业板指", "沪深300", "上证50", "中证500", "中证1000", "科创50"]

SESSION_AM = (9 * 60 + 30, 11 * 60 + 30)
SESSION_PM = (13 * 60, 15 * 60)


def normalize_idx(idx: str) -> str:
    return IDX_ALIASES.get(idx, idx)


# ── 装载 ────────────────────────────────────────────────────────────────

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


INTRADAY = _load_intraday()

# **交易日历**（哪天开市）—— 官方日历，含未来。数日子（验证终点、交易日跨度）只认它。
CAL: tuple[str, ...] = ()
CAL_SET: set[str] = set()
CAL_ERR = ""

# **行情水位**（数据到哪天）—— 上证指数 30 分钟线的末根。算价只认它。**与日历是两件事**。
LAST_DATE = INTRADAY["上证指数"][-1][0] if INTRADAY.get("上证指数") else ""


def _load_cal() -> None:
    """读官方日历 → `CAL` / `CAL_SET` / `CAL_ERR`。**读不出不抛** —— 抓日历那一步还得跑。"""
    global CAL, CAL_SET, CAL_ERR
    try:
        doc = json.loads(paths.MARKET_CAL.read_text(encoding="utf-8")) or {}
        days = tuple(sorted({str(d)[:10] for d in (doc.get("days") or [])}))
    except (ValueError, OSError) as e:
        CAL, CAL_SET, CAL_ERR = (), set(), f"{type(e).__name__}: {e}"
        return
    CAL, CAL_SET, CAL_ERR = days, set(days), "" if days else "日历里一天都没有"


_load_cal()


def _require_cal() -> None:
    """**日历是数日子的唯一依据，缺了硬失败**（01§10.3）—— 不许拿行情倒推一份凑合。"""
    if CAL_ERR:
        raise RuntimeError(
            f"交易日历不可用（{CAL_ERR}）。交易日历与行情是两件事，缺了不许拿行情倒推一份 —— "
            f"先跑：python -m blogger.market"
        )


def reload() -> None:
    """补完行情后重新载入 —— 本层在 import 时就把行情读进内存了。

    **补行情之后必须调一次**，否则同一进程里算出来的还是补之前的那份。
    """
    global INTRADAY, LAST_DATE
    INTRADAY = _load_intraday()
    LAST_DATE = INTRADAY["上证指数"][-1][0] if INTRADAY.get("上证指数") else ""
    _load_cal()


def is_trading_day(d: str) -> bool:
    _require_cal()
    return d in CAL_SET


def after_calendar(d: str) -> bool:
    """`d` 晚于日历末日 —— 那天是不是交易日，**日历说了不算，现在判不了**。

    `is_trading_day` 对它只会说 False，与「日历里明确是休市」混成一个答案。要分开：
    前者是「还判不了」，后者是「那天没开市」（03§3.6 ②）。
    """
    _require_cal()
    return bool(CAL) and d > CAL[-1]


def prev_td(d: str) -> str | None:
    """d 之前最近一个交易日（不含 d）。"""
    _require_cal()
    for x in reversed(CAL):
        if x < d:
            return x
    return None


def next_td(d: str) -> str | None:
    """d 之后最近一个交易日（不含 d）。"""
    _require_cal()
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


def _intraday_price(idx: str, pub: str) -> tuple[float | None, str | None]:
    """单指数（不含双创）的现值，附快照性质 —— **发帖时刻可获取的最新价格**（02§2.1）。

    快照性质两种：`open:<那根>` 盘中（`9:30~11:30`、`13:00~15:00`）取**所处那根的开盘价**
    —— 那一刻已经知道，与上一根的收盘是同一个数；`prev` 其余时间取**上一根的收盘价**
    （`11:30`、`15:00` 本身，以及午休、盘后、盘前、休市）。

    报告与回测是事后的，那根一定在；推送是实时的，它直接取现价，不走这里（06§5.3）。
    """
    days = INTRADAY.get(normalize_idx(idx))
    if not days:
        return None, None
    pub_day, hhmm = pub[:10], pub[11:16]
    hm = _minutes(pub)
    if hm is None or len(hhmm) < 5:
        return None, None

    today = next((rows for day, rows in days if day == pub_day), []) if is_trading_day(pub_day) else []

    if SESSION_AM[0] <= hm < SESSION_AM[1] or SESSION_PM[0] <= hm < SESSION_PM[1]:
        ahead = [(t, b) for t, b in today if t > hhmm]
        if ahead:
            t, b = ahead[0]
            return b["open"], f"open:{t}"

    done = [(t, b) for t, b in today if t <= hhmm]
    if done:                                      # 午休、盘后：当日上一根的收盘
        return done[-1][1]["close"], "prev"

    prev = prev_td(pub_day)                       # 盘前、休市：上一交易日末根
    if prev is None:
        return None, None
    for day, rows in days:
        if day == prev:
            return rows[-1][1]["close"], "prev"
    return None, None


def ref_price(idx: str, pub: str) -> float | None:
    """**参考价** —— 发帖那一刻该指数的现值。取不到返回 None。

    双创 = 创业板指与科创50 各占一半。
    """
    if idx in COMBO:
        vals = [ref_price(one, pub) for one in COMBO[idx]]
        return sum(vals) / len(vals) if all(v is not None for v in vals) else None
    return _intraday_price(idx, pub)[0]


def snapshot_label(pub: str) -> str | None:
    """发帖时刻的快照性质，写进行情注记的头部（02§2.1）。

    盘中 → `盘中(30分钟线当根开盘)`；其余 → `上一根(30分钟线收盘)`。
    """
    if len(pub[11:16]) < 5 or _minutes(pub) is None:
        return None
    _, snap = _intraday_price("上证指数", pub)
    if snap is None:
        return None
    return "盘中(30分钟线当根开盘)" if snap.startswith("open:") else "上一根(30分钟线收盘)"


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
    """`d` 所在那一周的最后交易日。

    **整周一个交易日都没有**（春节那一周）时取该周最后一天（周日）—— 它不是交易日，
    这条表述因此不成立（03§3.6 ②）。这不是特例，是同一条规则。
    """
    _require_cal()
    y, w, _ = date.fromisoformat(d).isocalendar()
    days = [x for x in CAL if date.fromisoformat(x).isocalendar()[:2] == (y, w)]
    return days[-1] if days else date.fromisocalendar(y, w, 7).isoformat()


def _last_day_of_month(ym: str) -> str:
    """该月的最后一天（自然日）—— 整月没交易日时拿它当终点，与周那一路同一条规矩。"""
    return (date.fromisoformat(_next_month(ym) + "-01") - timedelta(days=1)).isoformat()


def _weekday_of_week(d: str, weekday: int, plus_weeks: int = 0) -> str | None:
    """发帖当周（或下 N 周）的那个星期几。weekday：周一=1 … 周五=5。"""
    y, w, _ = date.fromisoformat(d).isocalendar()
    monday = date.fromisocalendar(y, w, 1) + timedelta(weeks=plus_weeks)
    return (monday + timedelta(days=weekday - 1)).isoformat()


WEEKDAY_SPECS = {"monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5}


def _last_td_of_month(d: str) -> str | None:
    _require_cal()
    ym = d[:7]
    days = [x for x in CAL if x[:7] == ym]
    return days[-1] if days else _last_day_of_month(ym)


def _next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def endpoint(pub: str, spec: str) -> str | None:
    """**验证终点** —— 这条观点信号该看哪一天。

    **就是博主说的那一天，不顺延**（02§4.1）：落在非交易日的话，这条表述没有可验证的
    终点，03 判成「报错」（03§3.6 ②）。日历**含未来**（01§10.3），所以「明天」「下周」
    这类终点都算得出；算不出的只有两种：`long` 没有终点，以及终点超过日历末日。
    """
    _require_cal()
    day = pub[:10]
    base = base_day(day)
    if base is None:
        return None

    if spec == "long":
        return None
    if spec == "today":
        # 终点就是发帖当天 —— 非交易日发布的话它不是交易日，03 判「报错」（03§3.6 ②）
        return day

    if spec.startswith("t") and spec[1:].isdigit():
        n = int(spec[1:])
        i = CAL.index(base) + n
        return CAL[i] if 0 <= i < len(CAL) else None

    if spec == "week":
        return _last_td_of_week(day)
    if spec == "nweek":
        nxt = (date.fromisoformat(day) + timedelta(days=7)).isoformat()
        return _last_td_of_week(nxt)
    if spec == "month":
        return _last_td_of_month(day)
    if spec == "nmonth":
        return _last_td_of_month(_next_month(day[:7]) + "-01")

    if spec.startswith("d:"):
        target = spec[2:]
        return target if _ok_date(target) else None

    # 周几：monday~friday 指本周的那一天，nmonday~nfriday 指下周的那一天
    if spec in WEEKDAY_SPECS:
        return _weekday_of_week(day, WEEKDAY_SPECS[spec])
    if spec.startswith("n") and spec[1:] in WEEKDAY_SPECS:
        return _weekday_of_week(day, WEEKDAY_SPECS[spec[1:]], plus_weeks=1)

    return None


def _ok_date(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def ep_close(idx: str, ep: str) -> float | None:
    """**终点价** —— 验证终点那天的收盘价（30 分钟线当日末根）。取不到返回 None。

    **不兜底**：行情水位到了、这个指数这天却没数据的话，就是「报错」（03§3.6 ⑤），
    不拿别的源凑一个数出来 —— 凑出来的数看不出是凑的。
    """
    if idx in COMBO:
        vals = [ep_close(one, ep) for one in COMBO[idx]]
        return sum(vals) / len(vals) if all(v is not None for v in vals) else None

    for day, rows in INTRADAY.get(normalize_idx(idx), []):
        if day == ep:
            return rows[-1][1]["close"]
    return None


def span(pub: str, ep: str) -> int | None:
    """**交易日跨度** —— 发帖日到验证终点隔了几个交易日。

    从发帖日的锚（发帖日是交易日就用它，否则前一交易日）起算。
    """
    _require_cal()
    base = base_day(pub[:10])
    if base is None or ep not in CAL_SET or base not in CAL_SET:
        return None
    return CAL.index(ep) - CAL.index(base)


def span_bucket(n: int) -> str:
    """按跨度分两档（03§3.4）：跨度 `< 2` 超短期，`≥ 2` 波段。

    **边界只有这一处** —— 与 03、04 的两档表读的是同一个配置键。
    """
    return "波段" if n >= params.get("report.bucket_span", 2) else "超短期"


# ── 合法域 ──────────────────────────────────────────────────────────────

VALID_IDX = {"上证指数", "上证50", "沪深300", "中证500", "中证1000", "创业板指", "科创50", "双创"}

# 组合指数 = 哪几个单指数各占一半。`ref`／`epc` 取两者的均值；`ret` 由 03 各算各的再平均（03§3.3）。
COMBO = {"双创": ("创业板指", "科创50")}

# spec 全表。`tN` 的 N 走数字，`d:` 的日期要真实存在，其余是固定值。
FIXED_SPECS = ({"today", "week", "nweek", "month", "nmonth", "long"}
               | set(WEEKDAY_SPECS)
               | {f"n{k}" for k in WEEKDAY_SPECS})

# `tN` 的 N 上界 —— 20 个交易日约合一个月，超过就不算可验证的短期周期（超过落 `long`）
T_MAX = 20


def spec_ok(spec: str) -> bool:
    if not isinstance(spec, str) or not spec:
        return False
    if spec in FIXED_SPECS:
        return True
    if spec.startswith("t") and spec[1:].isdigit():
        return 1 <= int(spec[1:]) <= T_MAX
    if spec.startswith("d:"):
        return _ok_date(spec[2:])
    return False
