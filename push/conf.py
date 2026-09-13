# -*- coding: utf-8 -*-
"""06§2／§9 的板块参数 —— 从仓库根的 `config.json` 读。**改参数只改那一份文件。**

两个板块的差别只有五样：**池子、回看窗口、卡面名字、卡内标签、飞书群**。
时刻表两张两板块共用（06§5.1）。**分档按交易日跨度**，与 03§3.4／04§3.4 同一口径 ——
不是卡片上的周期词。**只考察哪个指数**照 04§3.1 那个键（`compare.index`），不另配一份。
"""

from __future__ import annotations

from blogger.common import params

BOARDS = ("short", "swing")

BOARD = {
    "short": {"name": "超短", "tag": "超短(0-1日)", "mark": "⏱️",
              "webhook": "FEISHU_WEBHOOK_URL"},
    "swing": {"name": "波段", "tag": "波段(2日+)", "mark": "🌊",
              "webhook": "FEISHU_WEBHOOK_URL_SWING"},
}


def load(board: str) -> dict:
    """本次推送的全部参数。"""
    return {
        "board": board,
        **BOARD[board],
        "index": str(params.get("compare.index", "上证指数")),
        "pool": list(params.get(f"push.pools.{board}", []) or []),
        "window": int(params.get(f"push.window.{board}", 1)),
        "trading": list(params.get("push.grid.trading", []) or []),
        "restday": list(params.get("push.grid.restday", []) or []),
        "retries": int(params.get("push.retries", 3)),
        "retry_delay": int(params.get("push.retry_delay", 3)),
        "timeout": int(params.get("push.webhook_timeout", 20)),
        "summary_limit": int(params.get("push.summary_limit", 240)),
        "bucket_span": int(params.get("report.bucket_span", 2)),
        "quote_limit": int(params.get("report.quote_limit", 60)),
    }


def span_ok(board: str, span: int | None, bucket: int) -> bool:
    """这一条信号的跨度落不落在本板块（06§2）。

    | 板块 | 收哪些 |
    |:---|:---|
    | 超短 | 跨度 **≤ bucket − 1** |
    | 波段 | 跨度 **≥ bucket** |

    **算不出跨度的两张卡都上不了** —— `span is None` 一律 False（`long` 没有终点；
    终点超出日历覆盖的同样算不出，见 03§3.4）。
    """
    if span is None:
        return False
    return span <= bucket - 1 if board == "short" else span >= bucket


__all__ = ["BOARDS", "BOARD", "load", "span_ok"]
