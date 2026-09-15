# -*- coding: utf-8 -*-
"""事后验证 —— 每条结构化数据**现算**七样，算完就扔，不写回文件（见 03§3）。

| 现算什么 | 字段名 | 一句话 |
|:---|:---|:---|
| 参考价 | `ref` | 发帖时刻该指数的现值 |
| 验证终点 | `ep` | 这条观点信号该看哪一天 |
| 终点价 | `epc` | 验证终点那天的收盘价 |
| 交易日跨度 | `span` | 发帖日到验证终点，隔了几个交易日 |
| 收益率 | `ret` | 终点价相对参考价的变化 |
| 得分 | `score` | 方向 × 收益率 × 100 |
| 状态 | `note` | 计分／不计分／待验证／报错／无效-过时 |

`ref` 与 02 的**行情注记**调的是同一个取价函数、同一份行情、同一个 `pub`，
所以必然同值。**两处一分叉，模型判对的会被算成算错。**
"""

from __future__ import annotations

from blogger.common import market

# 五种状态
SCORED = "计分"
UNSCORED = "不计分"
PENDING = "待验证"
ERROR = "报错"
STALE = "无效-过时"

CLOSE_AT = "15:00"          # 收盘时间，判「无效-过时」用


def evaluate(sig: dict) -> dict:
    """把一条结构化数据（6 键）算成一条带现算字段的记录。**不改原字典。**"""
    pub, spec, idx = sig["pub"], sig["spec"], sig["idx"]

    ref = market.ref_price(idx, pub)
    ep = market.endpoint(pub, spec)
    epc = market.ep_close(idx, ep) if ep else None
    span = market.span(pub, ep) if ep else None

    ret = _ret(idx, pub, ep, ref, epc)
    score = (sig["d"] * ret * 100) if ret is not None else None

    note = _state(pub, spec, ep, epc)
    return {**sig, "ref": ref, "ep": ep, "epc": epc, "span": span,
            "ret": ret, "score": score, "note": note,
            "intraday": note == SCORED and spec == "today" and _in_session(pub)}


def _ret(idx: str, pub: str, ep: str | None, ref, epc) -> float | None:
    """**收益率** —— 03§3.5 的「终点价 / 参考价 − 1」。

    **双创例外**（03§3.3）：两个指数**各算各的收益率**再取算术平均 ——
    不是把两个指数的均价拿来相除。`ref`／`epc` 两个展示值仍是两指数的均值。
    """
    if idx in market.COMBO:
        if ep is None:
            return None
        rs = []
        for one in market.COMBO[idx]:
            a, b = market.ref_price(one, pub), market.ep_close(one, ep)
            if a is None or b is None:
                return None
            rs.append(b / a - 1)
        return sum(rs) / len(rs)
    return (epc / ref - 1) if (epc is not None and ref) else None


def _state(pub: str, spec: str, ep: str | None, epc: float | None) -> str:
    """按 03§3.6 判状态：**从上往下，命中即停**。"""
    # ① 年度预测／中长期 —— 没有验证终点，不参与打分
    if spec == "long":
        return UNSCORED
    # ② 说的那天没开市 —— 验证终点落不到交易日（02§4.1）。终点就是博主说的那一天、
    # **不顺延**，所以它与发帖日谁先谁后都有可能：`spec=today` 而发帖日不是交易日，
    # 就是「终点 = 发帖当天」那一例。终点超过日历末日的不算 —— 那是「还判不了」。
    if ep and not market.after_calendar(ep) and not market.is_trading_day(ep):
        return ERROR
    # ③ 发帖时该周期已经收盘了 —— 说在事后，不算数。
    # **边界取等**：发帖正好是收盘那一刻（15:00:00）→ 算「晚于」，照样是 STALE（02§4.2）
    if ep and f"{ep} {CLOSE_AT}" <= pub[:16]:
        return STALE
    # ④ 算不出来：终点超出日历末日、或行情水位还没到那一天（**是算不出，不是算错**）
    if ep is None or ep > market.LAST_DATE:
        return PENDING
    # ⑤ 水位到了，这个指数在终点那天却没有行情 —— **不兜底**，报出来（03§3.6 ⑤）
    if epc is None:
        return ERROR
    # ⑥ 其余
    return SCORED


def _in_session(pub: str) -> bool:
    """发帖时点在当天交易时间内（09:30–11:30 / 13:00–15:00）。"""
    try:
        hm = pub[11:16]
        h, m = int(hm[:2]), int(hm[3:5])
    except (ValueError, IndexError):
        return False
    mins = h * 60 + m
    return market.SESSION_AM[0] <= mins <= market.SESSION_AM[1] or \
        market.SESSION_PM[0] <= mins <= market.SESSION_PM[1]


__all__ = ["evaluate", "SCORED", "UNSCORED", "PENDING", "ERROR", "STALE"]
