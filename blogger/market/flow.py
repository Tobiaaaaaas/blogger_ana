# -*- coding: utf-8 -*-
"""01§10 的命令行 —— 补行情、**抓完核对**、不达标非零退出。

    python -m blogger.market [--until 2026-09-13]
    python -m blogger.market --check

**报告流程（03）内部也会补一次行情，但它不核对。** 手动跑这个命令就是为了单独核对 ——
日历静默停住的时候，报告看上去一切正常（01§10.4）。
"""

from __future__ import annotations

import sys

from blogger.common import market
from blogger.market import fetch

MAX_LIST = 10        # 缺的日子最多列几个，再多就只报个数


def run(until: str = "", log=print) -> int:
    """① 抓 → ② 核对 → 报账。全齐 0，有缺 1。"""
    log(f"[① 抓] 该到 {fetch.due_day(until)}｜官方日历 {_cal_note()}")
    got = fetch.refresh(until, progress=log)
    log(f"  日线 +{got['日线']} 根、30 分钟线 +{got['30分钟']} 根，日历到 {got['日历到']}")
    log("")
    return 0 if not confirm(until, log) else 1


def confirm(until: str = "", log=print) -> int:
    """② 抓完必须核对（01§10.4）。返回**差了几项** —— 0 就是齐了。"""
    want = fetch.due_day(until)
    log(f"[② 核对] 该到 {want}")
    short = _shortfalls(want)
    if not short:
        log("  三样都对上了。")
        return 0
    for what, why in short:
        log(f"  **没到位** {what}：{why}")
    log(f"  共 {len(short)} 项没到位 —— 抓不到不算抓成功。")
    return len(short)


def survey(log=print) -> int:
    """只看不抓（`--check`）—— **不联网、不写盘**。返回差了几项。"""
    want = fetch.due_day("")
    log(f"系统交易日历　止于 {market.LAST_DATE or '空（一条都没有）'}")
    log(f"官方日历　　　{_cal_note()}")
    log(f"该到　　　　　{want}")
    log("")
    log("| 指数 | 日线到 | 30 分钟线到 |")
    log("|:---|:---|:---|")
    for _, name in fetch.INDICES:
        log(f"| {name} | {_daily_last(name) or '—'} | {_intraday_last(name) or '—'} |")
    log("")
    confirm("", log)
    return len(_shortfalls(want))


# ── 核对 ────────────────────────────────────────────────────────────────

def _shortfalls(want: str) -> list[tuple[str, str]]:
    """**比三样**：日历末个交易日、每个指数的日线末根、每个指数的 30 分钟线末根。"""
    out = []
    if market.LAST_DATE < want:
        out.append(("交易日历", _why(market.LAST_DATE, want)))
    for _, name in fetch.INDICES:
        last = _daily_last(name)
        if last < want:
            out.append((f"日线 {name}", _why(last, want)))
    for _, name in fetch.INDICES:
        last = _intraday_last(name)
        if last < want:
            out.append((f"30分钟 {name}", _why(last, want)))
    return out


def _why(last: str, want: str) -> str:
    """差在哪 —— **把缺的交易日逐个列名**，不报个「差 N 天」让人自己去猜。"""
    if not last:
        return "一条都没有"
    miss = fetch.missing_days(last, want)
    if len(miss) <= MAX_LIST:
        return f"止于 {last}，缺 {'、'.join(miss)}"
    return f"止于 {last}，缺 {len(miss)} 个交易日（{miss[0]} … {miss[-1]}）"


def _cal_note() -> str:
    days = fetch.official_days()
    return f"止于 {days[-1]}" if days else "**取不到或已过期，核对退回只跳周末**"


def _daily_last(name: str) -> str:
    rows = market.DAILY.get(name) or []
    return rows[-1]["日期"] if rows else ""


def _intraday_last(name: str) -> str:
    days = market.INTRADAY.get(name) or []
    return days[-1][0] if days else ""


# ── 入口 ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        return 0 if not survey() else 1
    until = args[args.index("--until") + 1] if "--until" in args else ""
    return run(until)


if __name__ == "__main__":
    sys.exit(main())
