# -*- coding: utf-8 -*-
"""④ 筛资格 · ⑤ 排榜 · ⑥ 集中度与缺口警告（见 04§4、§5.2、§6）。

**三张榜全部只考察上证指数**，一律按**平均分**降序，**信息比率只列不排**。
门槛、取几名全从 `config.json` 读（04§8）—— 这里一个数都不写死。
"""

from __future__ import annotations

from blogger.common import params
from blogger.report import stats


def top_n() -> int:
    return params.get("compare.top_n", 20)


def order_key(rows: list[dict]) -> float:
    """三张榜按什么降序（04§5.2）—— **默认按平均分**。

    信息比率算不出的（不足 2 条、或波动率为 0）排在最后，不是当成 0 排。
    """
    s = stats.summarize(rows)
    if params.get("compare.order", "平均分") == "信息比率":
        return float("-inf") if s["ir"] is None else s["ir"]
    return s["avg"]


# ── ⑤ 排一张榜 ──────────────────────────────────────────────────────────

def board(people: list[dict], pick, min_signals: int, min_avg: float) -> dict:
    """一张榜。`pick(样本) -> 该榜的样本行`。

    返回 `{"hit": 上榜的, "out": 榜尾的}` —— 每条都是
    `{name, rows, 五个数, 为什么没上榜}`。**榜尾 = 参与对比但没上榜的每一位**，
    一个都不漏（04§4.2）。
    """
    hit, out = [], []
    for p in people:
        if not p["in"]:
            continue
        rows = pick(p)
        s = stats.summarize(rows)
        rec = {"name": p["name"], "rows": rows, "why": _why(rows, s, min_signals, min_avg)}
        (out if rec["why"] else hit).append(rec)

    hit.sort(key=lambda r: order_key(r["rows"]), reverse=True)
    over = hit[top_n():]
    for r in over:
        r["why"] = f"超出前 {top_n()} 名"
    hit = hit[:top_n()]
    out.sort(key=lambda r: -order_key(r["rows"]))
    return {"hit": hit, "out": over + out}


def _why(rows: list[dict], s: dict, min_signals: int, min_avg: float) -> str:
    """没上榜的原因 —— 差条数还是差均分，一样都不达标就都写。"""
    if not rows:
        return "这个榜里一条信号都没有"
    miss = []
    if s["n"] < min_signals:
        miss.append(f"信号 {s['n']} 条（要 ≥{min_signals} 条）")
    if not s["avg"] > min_avg:
        miss.append(f"平均分 {s['avg']:+.2f}（要 >{min_avg:g}）")
    return "；".join(miss)


# ── 三张榜 ──────────────────────────────────────────────────────────────

def all_boards(people: list[dict]) -> list[dict]:
    """总榜 · 两档分榜 · 方向榜，各一张。**顺序就是报告里的顺序**（04§5）。

    两档按**交易日跨度**分（04§3.4）—— `long` 判「不计分」，压根不在计分行里，
    跨度为 `None`，分不了档，也就进不了任何一档。
    """
    rank = params.get("compare.rank_board", {})
    grp = params.get("compare.group_board", {})
    bucket_span = params.get("report.bucket_span", 2)

    out = [{"title": "总榜", "board": board(
        people, lambda p: p["board"],
        rank.get("min_signals", 30), rank.get("min_avg", 0))}]

    for label, want_swing in ((stats.BUCKETS[0], False), (stats.BUCKETS[1], True)):
        out.append({"title": f"{label}榜", "board": board(
            people,
            lambda p, w=want_swing: [r for r in p["board"]
                                     if r["span"] is not None
                                     and (r["span"] >= bucket_span) == w],
            grp.get("min_signals", 10), grp.get("min_avg", 0.1))})

    for label, d in (("看多榜", 1), ("看空榜", -1)):
        out.append({"title": label, "board": board(
            people,
            lambda p, dd=d: [r for r in p["board"] if r["d"] == dd],
            grp.get("min_signals", 10), grp.get("min_avg", 0.1))})
    return out


# ── ⑥ 集中度与缺口 ──────────────────────────────────────────────────────

def warnings(people: list[dict]) -> list[tuple[str, str]]:
    """逐位过一遍，命中才列（04§6）。

    **算的是榜上那份样本（上证计分信号）** —— 与单博主报告里那一节（算该博主全部信号）
    可能不同，以这里为准。
    """
    out: list[tuple[str, str]] = []
    for p in people:
        if not p["in"]:
            continue
        for level, what in stats.concentration(p["board"]):
            out.append((p["name"], f"**{level}**：{what}"))
    return out


__all__ = ["board", "all_boards", "warnings", "top_n"]
