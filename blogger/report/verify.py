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

**为什么不存**：七样全是「结构化数据 + 行情」的纯函数 —— 行情一补、公式一改，
存下来的立刻作废。重算比维护一份会过期的副本便宜得多。

`ref` 与 02 的**行情注记**调的是同一个取价函数、同一份行情、同一个 `pub`，
所以必然同值。**两处一分叉，模型判对的会被算成算错。**
"""

from __future__ import annotations

from datetime import date

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

    ret = (epc / ref - 1) if (epc is not None and ref) else None
    score = (sig["d"] * ret * 100) if ret is not None else None

    note = _state(pub, spec, ep, epc)
    return {**sig, "ref": ref, "ep": ep, "epc": epc, "span": span,
            "ret": ret, "score": score, "note": note,
            "intraday": note == SCORED and spec == "today" and _in_session(pub)}


def _state(pub: str, spec: str, ep: str | None, epc: float | None) -> str:
    """按 03§3.6 判状态：**从上往下，命中即停**。"""
    # ① 年度预测／中长期 —— 没有验证终点，不参与打分
    if spec == "long":
        return UNSCORED
    # ② 非交易日说「今天」—— 这句话本身就不成立
    if spec == "today" and not market.is_trading_day(pub[:10]):
        return ERROR
    # ③ 发帖时该周期已经收盘了 —— 说在事后，不算数
    if ep and f"{ep} {CLOSE_AT}" < pub[:16]:
        return STALE
    # ④ 算不出来：终点还没到、或行情还没覆盖到那天（**是算不出，不是算错**）
    if ep is None or epc is None or ep > date.today().isoformat():
        return PENDING
    # ⑤ 其余
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


def is_stale(rec: dict) -> bool:
    """这条要不要从库里删掉（§3.7 清库）。"""
    return rec["note"] == STALE


__all__ = ["evaluate", "is_stale", "SCORED", "UNSCORED", "PENDING", "ERROR", "STALE"]
