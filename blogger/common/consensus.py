# -*- coding: utf-8 -*-
"""**共识分布** —— 回看窗口、三条淘汰、取最新、计数。**05 与 06 共用这一份**。

05§2 定死了一条：**规则同一套，机制两条路，结果必须一致。**

| | 怎么拿到分布 |
|:---|:---|
| **推送**（06） | **实时增量** —— 状态里带着「窗口内那几条」，每档淘汰过期的、并入新的、取最新 |
| **回测**（05） | **事后重算** —— 每档从信号文件从头筛一遍 |

两条路的**规则**都落在本模块 —— 窗口怎么算、什么算过期、谁是最新、怎么数人头。
两边各写一套的话，算出来的分布迟早不同，而那是 bug，不是风格（05§2）。

**一条观点信号的有效期 = 到它自己的验证终点为止。** 所以状态里要留着窗口内那几条 ——
最新那条过期时要能退回次新那条（06§5.6）。
"""

from __future__ import annotations

from blogger.common import market

CLOSE_AT = "15:00"          # 收盘时刻，「终点已过」判到分


# ── 回看窗口 ────────────────────────────────────────────────────────────

def window_start(day: str, days: int) -> str:
    """回看窗口的起点 —— **前 N 个交易日的 00:00**（06§3）。

    非交易日先**锚定到它之前最近的那个交易日**再往前数（06§3）：
    2026-09-05 周六、N=1 → 起点 09-03 周四 00:00。

    **每档现算，不存进状态** —— 存了就会随时间失真（06§3）。
    日历覆盖不到那么早（`prev_td` 走到头）返回空串。
    """
    anchor = day if market.is_trading_day(day) else market.prev_td(day)
    for _ in range(days):
        if anchor is None:
            return ""
        anchor = market.prev_td(anchor)
    return f"{anchor} 00:00" if anchor else ""


# ── 三条淘汰 ────────────────────────────────────────────────────────────
# 判据与次序都照 03§3.6 的状态机 —— 那一条线上的信号在报告里是什么下场，
# 在卡上、在回测里就是什么下场（06§0、06§5.7、05§3）。

def nontrading(ep: str | None) -> bool:
    """**终点没开市**（06§5.7）—— 验证终点落不到交易日，这条表述不成立（03§3.6 ②）。

    **终点超过日历末日的不算** —— 那是「还判不了」，不是「不成立」（`after_calendar`）。
    这类跟「终点算不出的」一样，只等「滑出窗口」把它带出去。
    """
    return bool(ep) and not market.after_calendar(ep) and not market.is_trading_day(ep)


def expired(ep: str | None, now: str) -> bool:
    """**终点已过**（06§5.7）—— 验证终点**已经收盘**，含正好收盘那一刻。

    **终点算不出的不按这条淘汰**（`ep is None` → False）—— 只等「滑出窗口」把它带出去。
    日历含未来（覆盖到哪天以文件为准），所以这只在「终点超过日历末日」时发生。
    """
    return bool(ep) and f"{ep} {CLOSE_AT}" <= now


def in_window(pub: str, wstart: str) -> bool:
    """**没滑出窗口**（06§5.7）—— `pub` 不早于本档现算的窗口起点。"""
    return bool(wstart) and pub >= wstart


def derive(sig: dict) -> dict:
    """给一条信号补上现算的两样：`ep`（验证终点）与 `span`（交易日跨度）。

    两者都从 `pub` 与 `spec` 推得，**不存进任何文件**（03§3 同一条规矩）。
    回测每档要过一遍全库，所以**先算一次、反复用**；推送每档只看增量的那几条，
    现算也够。
    """
    ep = market.endpoint(sig["pub"], sig["spec"])
    return {**sig, "ep": ep, "span": market.span(sig["pub"], ep) if ep else None}


def candidate(rec: dict, now: str, wstart: str) -> dict | None:
    """本档里，这条信号还算不算数。算就原样返回，不算返回 None。`rec` 是 `derive` 过的。

    三条淘汰按 §5.7 的次序走：滑出窗口 → 终点没开市 → 终点已过。
    """
    pub = rec.get("pub") or ""
    if not pub or pub > now:              # **前视**：本档只看 pub ≤ 本档时刻的帖（05§3）
        return None
    if not in_window(pub, wstart):
        return None
    if nontrading(rec.get("ep")):
        return None
    if expired(rec.get("ep"), now):
        return None
    return rec


# ── 取最新 ──────────────────────────────────────────────────────────────

def latest(rows: list[dict]) -> dict | None:
    """**最新**的那条（06§5.6 三级判据）：`pub` 大 → 验证终点更晚 → 信号文件里先出现。

    第 2 条管「同一帖出了两条同板块信号」（如「今天涨，明天也涨」）；
    第 3 条要确定、可复现，所以拿**列表里的先后**当依据 —— 信号文件与状态文件都按
    `pub`／`idx`／`spec` 排（`report.store.save`、`push.state.save`），两条链同序。
    """
    if not rows:
        return None
    return max(enumerate(rows),
               key=lambda it: (it[1]["pub"], it[1]["ep"] or "", -it[0]))[1]


# ── 计数 ────────────────────────────────────────────────────────────────

def spread(picked: list[dict]) -> tuple[int, int]:
    """把「每位取最新」之后的那一份数成 `(e, 多方)`（05§3、06§5.8）。

        e  = 分布里的条数 = 看多 + 看空
        多方 = d = +1 的条数

    **一位都没留下的博主不进 e** —— 没表态是正常状态，不是缺数据。
    `d` 只有 `+1` 与 `−1` 两个取值。
    """
    return len(picked), sum(1 for r in picked if r["d"] > 0)


__all__ = ["window_start", "nontrading", "expired", "in_window", "derive", "candidate",
           "latest", "spread", "CLOSE_AT"]
