# -*- coding: utf-8 -*-
"""05§7 指标 —— 整体／多头段／空头段各算一套。

| 指标 | 怎么算 |
|:---|:---|
| 累计收益 | 末值 / 初值 − 1 |
| 年化收益 | `(末值 / 初值) ^ (242 / 交易日数) − 1` |
| 波动率 | 日收益的标准差 × √242 |
| 夏普 | 年化收益 ÷ 波动率（无风险利率取 0） |
| 最大回撤 | 净值曲线上的最大峰谷跌幅 |
| 卡玛比 | 年化收益 ÷ 最大回撤 |
| 胜率 | 赚钱的笔数 ÷ 总笔数 |
| 换手率 | 改仓次数 ÷ 回测年数 |

**波动率、最大回撤、夏普都按日聚合** —— 每天取**收盘档（15:00）**的净值算日收益。
按档年化会大 √20 倍，没法跟外部策略比。

**两段的指标只看自己那一段的账**；**整体那一列把两向合起来算** —— 胜率按两向所有笔、
换手率按两向改仓次数合计（05§7）。
"""

from __future__ import annotations

TRADING_DAYS = 242          # 一年按 242 个交易日

SEGMENTS = ("整体", "多头段", "空头段")
COLUMN = {"整体": 1, "多头段": 2, "空头段": 3}      # 在 `closes` 元组里的位置


def daily_returns(closes: list[tuple], col: int) -> list[float]:
    """日收益 —— 每天收盘档的净值相对前一日的涨跌。"""
    vals = [row[col] for row in closes]
    return [b / a - 1 for a, b in zip(vals, vals[1:]) if a]


def max_drawdown(closes: list[tuple], col: int) -> float:
    """净值曲线上的**最大峰谷跌幅**（正数表示跌了几个点）。"""
    peak, worst = None, 0.0
    for row in closes:
        v = row[col]
        peak = v if peak is None or v > peak else peak
        if peak:
            worst = max(worst, 1 - v / peak)
    return worst


def std(xs: list[float]) -> float:
    """**样本**标准差（n−1 分母）；不足 2 个记 0 —— 与 03 的波动率同一口径。"""
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def table(book, days: int) -> dict:
    """三列并排的一份指标表。`days` 是 `[begin, end]` 闭区间内的交易日个数（05§5.3）。"""
    out = {}
    for seg in SEGMENTS:
        col = COLUMN[seg]
        out[seg] = _one(seg, book, col, days)
    return out


def _one(seg: str, book, col: int, days: int) -> dict:
    closes = book.closes
    first = closes[0][col] if closes else 1.0
    last = closes[-1][col] if closes else 1.0
    total = last / first - 1 if first else 0.0
    years = days / TRADING_DAYS if days else 0.0

    ann = (last / first) ** (TRADING_DAYS / days) - 1 if (days and first > 0) else None
    rets = daily_returns(closes, col)
    vol = std(rets) * (TRADING_DAYS ** 0.5)
    mdd = max_drawdown(closes, col)

    trades = [t for t in book.trades if seg == "整体" or t["方向"] == _side(seg)]
    wins = sum(1 for t in trades if t["收益"] > 0)

    return {
        "累计收益": total,
        "年化收益": ann,
        "波动率": vol,
        "夏普": (ann / vol) if (ann is not None and vol > 0) else None,
        "最大回撤": mdd,
        "卡玛比": (ann / mdd) if (ann is not None and mdd > 0) else None,
        "笔数": len(trades),
        "胜率": (wins / len(trades)) if trades else None,
        "改仓次数": len(trades),
        "换手率": (len(trades) / years) if years else None,
    }


def _side(seg: str) -> str:
    return "多" if seg == "多头段" else "空"


__all__ = ["table", "max_drawdown", "daily_returns", "std", "TRADING_DAYS", "SEGMENTS",
           "COLUMN"]
