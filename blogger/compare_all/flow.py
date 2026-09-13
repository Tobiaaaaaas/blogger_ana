# -*- coding: utf-8 -*-
"""04 的主流程 —— 全库更新 → 收集 → 现算 → 筛资格 → 排榜 → 出报告 → 写总结。

**用模型的只有 ① 和 ⑦。** ②～⑥ 全是纯计算。

报告**不留档**，每次覆盖同一份 `compare/博主对比.md`（04§改动记录）——
所以上一版要在覆盖**之前**读出来，交给第 ⑦ 段比变化。
"""

from __future__ import annotations

import sys

from blogger.common import config, market, paths
from blogger.compare_all import boards, pool, render, summary
from blogger.report import flow as report_flow

RUNS = 1


def run(begin_date: str = "", runs: int = RUNS, refresh: bool = True, log=print) -> int:
    """全博主对比。返回 0 成功、2 出错。"""
    if not report_flow.roster():
        log("库里一位博主都没有 —— 没有可比的。先给一条帖子链接把博主引进来（03§0）。")
        return 2

    log("[① 全库更新]")
    names, failed = pool.update(begin_date, runs, refresh, log)

    log("[②③ 收集与现算]")
    people = pool.collect(names, failed, log)

    log("[④⑤ 筛资格与排榜]")
    boards_ = boards.all_boards(people)
    for b in boards_:
        log(f"  {b['title']}：上榜 {len(b['board']['hit'])} 位，"
            f"榜尾 {len(b['board']['out'])} 位")

    log("[⑥ 出报告]")
    body = render.report(people, failed, boards_)
    old = _previous()

    log("[⑦ 写总结]")
    text = summary.write(body, old, log)

    out = body + "\n## 总结与分析\n\n" + text + "\n"
    p = paths.COMPARE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out, encoding="utf-8")
    log(f"  {p}")
    return 0


def _previous() -> str:
    """上一版报告。没有就是空串 —— 报告不留档，上一版就在同一个位置上。"""
    p = paths.COMPARE_FILE
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    begin_date, rest = config.split_begin_date(argv)
    if rest:
        print(f"认不得的参数：{' '.join(rest)}")
        print("用法：python -m blogger.compare_all [--begin_date 2026-01-01]")
        return 2
    print(f"库里 {len(report_flow.roster())} 位｜行情到 {market.LAST_DATE}")
    return run(begin_date)


__all__ = ["run", "main"]
