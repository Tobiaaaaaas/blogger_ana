# -*- coding: utf-8 -*-
"""统计 —— 从现算出来的那些数字算出报告要写的东西（见 03§4）。

**只用「计分」的信号。** 不计分／报错／待验证**单列**，不进任何指标；
「无效-过时」在清库那一步就被删了，到不了这里。

口径与旧报告一致（样本标准差、平局不入分母），这样新旧报告能逐格对账。
"""

from __future__ import annotations

from collections import Counter

from blogger.report import verify

# 分档标签
BUCKETS = ("超短期", "波段")


def accuracy(rows: list[dict]) -> tuple[int, int, float]:
    """正确率 —— 返回 `(得分正的条数, 参与分母的条数, 百分比)`。

    **得分为 0 的算「平」，不计入分子也不计入分母。**
    """
    win = sum(1 for r in rows if r["score"] > 0)
    flat = sum(1 for r in rows if r["score"] == 0)
    denom = len(rows) - flat
    return win, denom, (win / denom * 100 if denom else 0.0)


def mean_score(rows: list[dict]) -> float:
    return sum(r["score"] for r in rows) / len(rows) if rows else 0.0


def volatility(rows: list[dict]) -> float:
    """波动率 = 得分的**样本标准差**（n−1 分母）；不足 2 条记 0。"""
    if len(rows) < 2:
        return 0.0
    m = mean_score(rows)
    return (sum((r["score"] - m) ** 2 for r in rows) / (len(rows) - 1)) ** 0.5


def info_ratio(rows: list[dict]) -> float | None:
    """**信息比率** = 平均分 / 波动率。不足 2 条或波动率为 0 → None（显示 `—`）。

    **它不是回测里的夏普** —— 这里量的是观点本身的稳定性，回测的夏普量的是净值曲线。
    """
    v = volatility(rows)
    return mean_score(rows) / v if v > 0 else None


def summarize(rows: list[dict]) -> dict:
    """一组的五个数：信号数／平均分／正确率／波动率／信息比率。"""
    win, denom, acc = accuracy(rows)
    return {"n": len(rows), "avg": mean_score(rows), "win": win, "denom": denom,
            "acc": acc, "vol": volatility(rows), "ir": info_ratio(rows)}


# ── 分组 ────────────────────────────────────────────────────────────────

def by_index(rows: list[dict]) -> dict[str, list[dict]]:
    """按**预测对象**分组。"""
    return _group(rows, lambda r: r["idx"])


def by_bucket(rows: list[dict]) -> dict[str, list[dict]]:
    """按**两档**分组 —— 用交易日跨度分（跨度 ≤1 超短期、≥2 波段）。"""
    return _group(rows, lambda r: BUCKETS[1] if r["span"] >= 2 else BUCKETS[0],
                  only=("超短期", "波段"))


def by_direction(rows: list[dict]) -> dict[str, list[dict]]:
    return _group(rows, lambda r: "看多" if r["d"] > 0 else "看空")


def by_month(rows: list[dict]) -> dict[str, list[dict]]:
    """按**发帖月份**分组。"""
    return _group(rows, lambda r: r["pub"][:7])


def _group(rows: list[dict], key, only=None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(key(r), []).append(r)
    if only:
        out = {k: v for k, v in out.items() if k in only}
    return out


# ── 分布与集中度 ────────────────────────────────────────────────────────

def concentration(rows: list[dict]) -> list[tuple[str, str]]:
    """**必须提出来，不许闷着** —— 样本不足或高度集中的报告，指标再好看也没意义。

    返回 `[(级别, 说明)]`，级别是「高度集中」／「轻度集中」／「严重缺口」／「提示」。
    """
    out: list[tuple[str, str]] = []
    if not rows:
        return out

    months = Counter(r["pub"][:7] for r in rows)
    total = len(rows)
    for m, c in months.most_common(1):
        share = c / total
        if share >= 0.50:
            out.append(("高度集中", f"{m} 一个月占了 {share:.0%}（{c}/{total} 条）"))
        elif share >= 0.33:
            out.append(("轻度集中", f"{m} 一个月占了 {share:.0%}（{c}/{total} 条）"))

    span = _month_gaps(sorted(months))
    if span:
        worst = max(span)
        if worst >= 3:
            out.append(("严重缺口", f"相邻月份之间最多缺 {worst} 个月"))
        elif worst >= 1:
            out.append(("提示", f"相邻月份之间最多缺 {worst} 个月"))
    return out


def _month_gaps(months: list[str]) -> list[int]:
    """相邻两个有信号的月份之间，空了几个自然月。"""
    gaps = []
    for a, b in zip(months, months[1:]):
        ay, am = int(a[:4]), int(a[5:7])
        by, bm = int(b[:4]), int(b[5:7])
        gaps.append((by - ay) * 12 + (bm - am) - 1)
    return gaps


# ── 汇总 ────────────────────────────────────────────────────────────────

def tally(rows: list[dict]) -> dict:
    """按状态分堆。`rows` 是清库之后、全部信号（含单列的）。"""
    counts = Counter(r["note"] for r in rows)
    return {"total": len(rows),
            "scored": counts.get(verify.SCORED, 0),
            "unscored": counts.get(verify.UNSCORED, 0),
            "error": counts.get(verify.ERROR, 0),
            "pending": counts.get(verify.PENDING, 0)}


__all__ = ["accuracy", "mean_score", "volatility", "info_ratio", "summarize",
           "by_index", "by_bucket", "by_direction", "by_month", "concentration",
           "tally", "BUCKETS"]
