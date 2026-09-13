# -*- coding: utf-8 -*-
"""05§4 状态机 + 05§5 成交与净值 —— 本包唯一改账的地方。

**输入**：现持仓 `pos ∈ {+1, 0, −1}`、本档 `e` 与 `多方`。**输出**：目标仓位。

**判定与成交只发生在交易日的 20 档**（05§4）。非交易日那 5 档不成交 —— 状态机只看
「当前持仓 + 本档 ρ」，不看别的；非交易日那几档不产生任何可积累的东西。

**不计成本**（05§5.1）—— 手续费与滑点整个不进来，净值、逐笔收益全是毛数。

**多空不可能同时存在**，所以整体净值是两段的纯分解：`整体 = 多头段 × 空头段`（05§5.2）。
"""

from __future__ import annotations

from backtest import conf

CLOSE_TICK = "15:00"        # 每天这一档收进「日序列」，指标按它算（05§7）


# ── 状态机 ──────────────────────────────────────────────────────────────

def decide(pos: int, e: int, longs: int, c: dict) -> int:
    """本档的目标仓位（05§4）。**同一档先平后开**，允许 +1 ↔ −1 当档完成。

    `e = 0` → ρ 无定义，**本档不动作**，持仓照留。

    所有比较都是**严格不等**，按整数比算（`conf.over` / `conf.below`）——
    ρ 恰等于阈值不触发，维持原持仓。
    """
    if e == 0:
        return pos

    # 第一步 · 平仓门（pos ≠ 0 才走）
    if pos > 0 and conf.below(longs, e, c["tx_long"]) and e > c["q_exit"]:
        pos = 0
    elif pos < 0 and conf.over(longs, e, c["tx_short"]) and e > c["q_exit"]:
        pos = 0

    # 第二步 · 开仓门（pos = 0，或第一步刚平完）
    if pos == 0:
        if conf.over(longs, e, c["to_long"]) and e > c["q_open"]:
            return 1
        if conf.below(longs, e, c["to_short"]) and e > c["q_open"]:
            return -1
    return pos


# ── 账 ──────────────────────────────────────────────────────────────────

class Book:
    """两段的账 + 逐笔 + 净值曲线。

    **一笔 = 一段连续同向持仓**，从开仓档到平仓档（05§6）。
    **换向那一档出两行**：旧的一笔在这一档收尾，新的一笔在这一档开张（05§4）——
    换手率因此计 2，中间不隔空仓。
    """

    def __init__(self, long_symbol: str, short_symbol: str):
        self.pos = 0
        self.symbols = {"long": long_symbol, "short": short_symbol}
        self.nav = {"long": 1.0, "short": 1.0}   # 各段的净值；不持那一段时它不动
        self.base = 0.0        # 开仓那一刻该段的净值
        self.entry = 0.0       # 开仓价
        self.entry_i = 0       # 开仓档的序号（数「持仓档数」用）
        self.entry_at = ""     # 开仓档的时刻
        self.trades: list[dict] = []
        self.curve: list[tuple] = []      # 逐档： (档, 整体, 多, 空)
        self.closes: list[tuple] = []     # 日序列：每天 CLOSE_TICK 那一档
        self.bench: dict = {"long": [], "short": []}    # 两条基准线（05§6）

    # 换仓 ──────────────────────────────────────────────────────────────

    def switch(self, i: int, now: str, target: int, px: dict) -> None:
        """把仓位改到 `target`。**先平后开** —— 换向就是这一档两笔（05§4）。"""
        if target == self.pos:
            return
        if self.pos:
            self._close(i, now, px)
        if target:
            leg = self._leg(target)
            self.base, self.entry, self.entry_i, self.entry_at = \
                self.nav[leg], px[leg], i, now
        self.pos = target

    def _close(self, i: int, now: str, px: dict) -> None:
        leg = self._leg(self.pos)
        gross = self._gross(leg, px[leg])
        self.nav[leg] = self.base * gross
        self.trades.append({
            "开仓档": self.entry_at, "开仓价": self.entry,
            "平仓档": now, "平仓价": px[leg],
            "方向": "多" if self.pos > 0 else "空", "标的": self.symbols[leg],
            "收益": gross - 1,
            # **从开仓档数到平仓档，含两端** —— 当档进出记 1 档，不是 0
            "持仓档数": i - self.entry_i + 1,
        })

    # 盯市 ──────────────────────────────────────────────────────────────

    def mark(self, now: str, px: dict) -> None:
        """按本档现值记一次净值（05§5.2）。"""
        vals = self.values(px)
        self.curve.append((now, *vals))
        if now[11:16] == CLOSE_TICK:
            self.closes.append((now[:10], *vals))

    def values(self, px: dict) -> tuple[float, float, float]:
        """`(整体, 多头段, 空头段)`。

        持有那一段时，净值 = **开仓时的净值 × 按方向算的变化率**；不持有时它不动。
        这样**平仓那一档的净值乘数正好等于那笔的收益** —— 净值与逐笔表对得上账。
        """
        long_v = self.base * self._gross("long", px["long"]) if self.pos > 0 else self.nav["long"]
        short_v = self.base * self._gross("short", px["short"]) if self.pos < 0 else self.nav["short"]
        return long_v * short_v, long_v, short_v

    # ── 内部 ────────────────────────────────────────────────────────────

    def _gross(self, leg: str, price: float) -> float:
        """从开仓价到 `price` 的净值乘数。持多 `价/开`，持空是它的**反向** `2 − 价/开`。

        与 05§6 逐笔表的「收益」同一个口径：持多 `平/开 − 1`，持空取相反数。
        """
        r = price / self.entry - 1
        return 1 + (r if leg == "long" else -r)

    @staticmethod
    def _leg(pos: int) -> str:
        return "long" if pos > 0 else "short"


__all__ = ["decide", "Book", "CLOSE_TICK"]
