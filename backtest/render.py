# -*- coding: utf-8 -*-
"""05§6 报告与净值图。

**报告正文的顺序**：① 头部 → ② 本次参数 → ③ 净值图 → ④ 指标表 → ⑤ 逐笔。

**净值图**：横轴按**档** —— 交易日一天 20 个点。**非交易日那 5 档不画**（横轴上不出现），
否则周末与长假会拉出一排水平台阶。
"""

from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")                     # 无头环境也要出图
import matplotlib.pyplot as plt           # noqa: E402

from backtest import metrics             # noqa: E402

# 中文字体 —— 落图里的汉字不能变成方块
matplotlib.rcParams["font.sans-serif"] = [
    "Arial Unicode MS", "Songti SC", "STHeiti", "Hiragino Sans GB", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

LINES = (                       # (图例, 取自哪一列)
    ("整体", 1),
    ("多头段", 2),
    ("空头段", 3),
)
BENCH = (("多头标的买持", "long"), ("空头标的的反向买持", "short"))


def report(book, cfg: dict, days: int, end: str, have: list[str], missing: list[str],
           named: dict, bench: dict) -> str:
    """整份 `回测.md`。"""
    m = metrics.table(book, days)
    L = ["# 回测", ""]
    L += _head(cfg, days, end, have, missing)
    L += _params(cfg, named)
    L += ["## 净值图", "", "![净值](净值.png)", "",
          "横轴按档 —— 交易日一天 20 个点。**非交易日那 5 档不在横轴上。**", ""]
    L += _table(m)
    L += _trades(book)
    return "\n".join(L)


# ── ① 头部 ──────────────────────────────────────────────────────────────

def _head(cfg: dict, days: int, end: str, have: list[str], missing: list[str]) -> list[str]:
    L = ["| 项 | 值 |", "|:---|:---|",
         f"| 数据截止 | {end} |",
         f"| 回测区间 | {cfg['begin'] or '（信号最早那天）'} ~ {cfg['end'] or '（行情末日）'} |",
         f"| 交易日数 | {days} |",
         f"| 池子 | {len(cfg['pool'])} 位 |",
         f"| 实际有数据 | {len(have)} 位 |", ""]
    if missing:
        L += [f"**池子里这 {len(missing)} 位没数据，没进分布**："
              + "、".join(missing) + "。", ""]
    return L


# ── ② 本次参数 ──────────────────────────────────────────────────────────

def _params(cfg: dict, named: dict) -> list[str]:
    """与 `参数.json` 同一份内容 —— 两份档要能各自说清「我是怎么跑出来的」（05§6）。"""
    L = ["## 本次参数", "", "| 键 | 值 |", "|:---|:---|",
         f"| 博主池 | {'、'.join(cfg['pool'])} |",
         f"| 跑之前重跑全库 | {'是' if cfg['update'] else '**否** —— 只刷了行情'} |",
         f"| 回看窗口 | 前 {cfg['window']} 个交易日 |",
         f"| 档表 | 交易日 {len(cfg['grid'])} 档 |",
         f"| 两档边界 | 交易日跨度 ≥ {cfg['bucket_span']} 归波段 |",
         f"| 多头标的 | {cfg['long_symbol']} |",
         f"| 空头标的 | {cfg['short_symbol']} |",
         f"| 区间 | {cfg['begin'] or '（空）'} ~ {cfg['end'] or '（空）'} |",
         f"| 开多阈值 TO_LONG | ρ > {_f(cfg['to_long'])} |",
         f"| 开空阈值 TO_SHORT | ρ < {_f(cfg['to_short'])} |",
         f"| 平多阈值 TX_LONG | ρ < {_f(cfg['tx_long'])} |",
         f"| 平空阈值 TX_SHORT | ρ > {_f(cfg['tx_short'])} |",
         f"| 开仓法定人数 Q_open | e > {cfg['q_open']} |",
         f"| 平仓法定人数 Q_exit | e > {cfg['q_exit']} |", ""]
    if named:
        L += ["有数据的那几位：", ""]
        L += [f"- {k}：{v} 条（上证、跨度 ≥ {cfg['bucket_span']}）" for k, v in named.items()]
        L += [""]
    return L


def _f(f: tuple[int, int]) -> str:
    return f"{f[0]}/{f[1]}"


# ── ④ 指标表 ────────────────────────────────────────────────────────────

def _table(m: dict) -> list[str]:
    L = ["## 指标表", "",
         "| 指标 | 整体 | 多头段 | 空头段 |", "|:---|:---:|:---:|:---:|"]
    for key in ("累计收益", "年化收益", "波动率", "夏普", "最大回撤", "卡玛比",
                "笔数", "胜率", "改仓次数", "换手率"):
        cells = " | ".join(_cell(key, m[s][key]) for s in metrics.SEGMENTS)
        L.append(f"| **{key}** | {cells} |")
    L += ["",
          "**两段的指标只看自己那一段的账**；**整体那一列把两向合起来算**。",
          "波动率、最大回撤、夏普都按日聚合 —— 每天取收盘档（15:00）的净值算。", ""]
    return L


PCT = ("累计收益", "年化收益", "波动率", "最大回撤", "胜率")     # 百分比
RATIO = ("夏普", "卡玛比")                                     # 比值，不是百分比
COUNT = ("笔数", "改仓次数")


def _cell(key: str, v) -> str:
    if v is None:
        return "—"
    if key in COUNT:
        return f"{v}"
    if key in RATIO:
        return f"{v:.2f}"
    if key == "换手率":
        return f"{v:.1f}"
    return f"{v * 100:+.2f}%" if key in PCT else f"{v}"


# ── ⑤ 逐笔 ──────────────────────────────────────────────────────────────

def _trades(book) -> list[str]:
    L = ["## 逐笔", ""]
    if not book.trades:
        return L + ["一次都没开过仓。", ""]
    L += ["| # | 开仓档 | 开仓价 | 平仓档 | 平仓价 | 方向 | 标的 | 收益 | 持仓档数 |",
          "|:---:|:---|:---:|:---|:---:|:---:|:---|:---:|:---:|"]
    for i, t in enumerate(book.trades, 1):
        L.append(f"| {i} | {t['开仓档']} | {t['开仓价']:.2f} | {t['平仓档']} | "
                 f"{t['平仓价']:.2f} | {t['方向']} | {t['标的']} | "
                 f"{t['收益'] * 100:+.2f}% | {t['持仓档数']} |")
    L += ["",
          "- **收益** = 标的在 `[开仓价, 平仓价]` 上按方向算的变化率，**不计成本**",
          "- **换向那一档出两行** —— 旧的一笔在这一档收尾，新的一笔在这一档开张",
          "- **区间末尾那一笔**按末档平掉，照常入表",
          f"- 合计 {len(book.trades)} 笔", ""]
    return L


# ── ③ 净值图 ────────────────────────────────────────────────────────────

def chart(path, book, bench: dict) -> None:
    """五条线落一张图：整体／多头段／空头段／两条基准。"""
    xs = list(range(len(book.curve)))
    fig, ax = plt.subplots(figsize=(12, 5.5), dpi=140)

    for label, col in LINES:
        ax.plot(xs, [row[col] for row in book.curve], linewidth=1.6, label=label)
    for label, key in BENCH:
        ax.plot(xs, bench[key], linewidth=1.0, linestyle="--", label=label)

    _days_axis(ax, [row[0] for row in book.curve])
    ax.axhline(1.0, color="#999999", linewidth=0.8)
    ax.set_ylabel("净值")
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _days_axis(ax, stamps: list[str]) -> None:
    """横轴按档，**刻度落在每天第一档**（09:00）—— 非交易日不在其中（05§6）。"""
    ticks, labels = [], []
    for i, s in enumerate(stamps):
        if i == 0 or s[:10] != stamps[i - 1][:10]:
            ticks.append(i)
            labels.append(s[5:10])
    step = max(1, len(ticks) // 12)          # 日子多了就隔几个标一次，免得糊成一片
    ax.set_xticks(ticks[::step])
    ax.set_xticklabels(labels[::step])
    ax.set_xlabel("档（交易日一天 20 档）")


def params_json(cfg: dict) -> str:
    """`参数.json` —— 这份档的一部分：换池不是功能，池子就是参数。"""
    return json.dumps(cfg, ensure_ascii=False, indent=1) + "\n"


__all__ = ["report", "chart", "params_json"]
