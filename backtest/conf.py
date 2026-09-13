# -*- coding: utf-8 -*-
"""05§9 的参数 —— 从仓库根的 `config.json` 读，再加上本次跑的一份快照。

**本文每一条判据都不写死**，改参数只改配置，不碰代码。

四个阈值在配置里存成**分数** `[分子, 分母]`（05§9.1）—— 「严格不等」在恰好等于阈值时
才精确，浮点比不出「恰好」。所以下面一整套比较都走**整数比**，不出现除法。
"""

from __future__ import annotations

from blogger.common import params

TICKS_KEY = "push.grid.trading"    # 交易日 20 档 —— 与推送同一张表（05§9.2）
WINDOW_KEY = "push.window.swing"   # 回看窗口 —— 回测不另配（05§9.2）


def frac(dotted: str, default: tuple[int, int]) -> tuple[int, int]:
    """读一个分数阈值。配置里写 `[2, 3]`；写坏了就用默认值。"""
    got = params.get(dotted, None)
    if isinstance(got, (list, tuple)) and len(got) == 2:
        try:
            num, den = int(got[0]), int(got[1])
            if den > 0:
                return num, den
        except (TypeError, ValueError):
            pass
    return default


def load() -> dict:
    """本次跑的全部参数 —— 这份就是 `参数.json` 的内容（05§6）。"""
    return {
        "pool": list(params.get("backtest.pool", []) or []),
        # 关了只省抓帖 —— 行情照刷，那是算价的前提（05§8）
        "update": bool(params.get("backtest.update", True)),
        "window": params.get(WINDOW_KEY, 5),
        "grid": list(params.get(TICKS_KEY, []) or []),
        "long_symbol": params.get("backtest.long_symbol", "中证1000"),
        "short_symbol": params.get("backtest.short_symbol", "中证1000"),
        "begin": params.get("backtest.begin", "") or "",
        "end": params.get("backtest.end", "") or "",
        "to_long": frac("backtest.to_long", (2, 3)),
        "to_short": frac("backtest.to_short", (1, 3)),
        "tx_long": frac("backtest.tx_long", (1, 2)),
        "tx_short": frac("backtest.tx_short", (1, 2)),
        "q_open": int(params.get("backtest.q_open", 3)),
        "q_exit": int(params.get("backtest.q_exit", 3)),
        "bucket_span": int(params.get("report.bucket_span", 2)),
    }


# ── 严格不等的整数比 ────────────────────────────────────────────────────
#
#     ρ = 多方 / e
#     ρ > num/den   ⟺  多方 × den > num × e
#     ρ < num/den   ⟺  多方 × den < num × e

def over(part: int, whole: int, f: tuple[int, int]) -> bool:
    return part * f[1] > f[0] * whole


def below(part: int, whole: int, f: tuple[int, int]) -> bool:
    return part * f[1] < f[0] * whole


__all__ = ["load", "frac", "over", "below", "TICKS_KEY", "WINDOW_KEY"]
