# -*- coding: utf-8 -*-
"""04§3.2 的交叉核对 —— **榜上的数与单博主报告里那一行必须逐格相同**。

> 榜上某位博主的五个数（信号数／平均分／正确率／波动率／信息比率），
> 与他单博主报告里「预测对象＝上证指数」那一行逐格相同。**对不上就是错了。**

这条不能只靠「两边调的是同一个函数」来保证 —— 那样一旦有一边的筛选条件写歪了
（比如漏了「只算计分」），函数再对也照样分叉。所以这里是**从报告正文里把那一行读回来**，
跟对比那边算出来的比。

**两边都没有那一行 = 一致，不是「对不上」。** 没有可比的行和数值不一致是两回事，
混在一起报会把「他本来就没有上证计分信号」说成「算错了」。

    python -m blogger.tests.invariant [博主名…]

**必须带 `-m`** —— 直接 `python blogger/tests/invariant.py` 会因为 `blogger` 不在
`sys.path` 上而报 `ModuleNotFoundError`。

不给博主名就核对全库。`blogger/tests/drive.py` 跑完会顺手调它。
"""

from __future__ import annotations

import re
import sys

from blogger.common import market, params, paths
from blogger.compare_all import pool
from blogger.report import flow, stats

ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(\d+)\s*\|\s*([+-]?[\d.]+)\s*\|\s*([\d.]+)%\s*"
                 r"\|\s*([\d.]+)\s*\|\s*(—|[+-][\d.]+)\s*\|\s*$")


def report_row(blogger: str, group: str) -> list[str] | None:
    """从报告正文的「按预测对象」表里，把 `group` 那一行读回来。

    读回来的是**纸面上的样子**：位数照报告那一格（正确率一位、其余两位）。
    """
    p = paths.report_file(blogger)
    if not p.exists():
        return None
    parts = p.read_text(encoding="utf-8").split("## 按预测对象", 1)
    if len(parts) < 2:
        return None
    for line in parts[1].splitlines():
        m = ROW.match(line.strip())
        if m and m.group(1) == group:
            n, avg, acc, vol, ir = m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
            return [n, f"{float(avg):.2f}", f"{float(acc):.1f}", f"{float(vol):.2f}", ir]
    return None


def compare_row(people: list[dict], blogger: str) -> list[str] | None:
    """对比那边算出来的同一行 —— 榜上那份样本（只留上证、只算计分）。

    **位数照报告那一格取**（正确率一位、其余两位）—— 「逐格相同」比的是**纸面上的那一格**，
    比到报告根本没有的位数上去，比出来的差是格式差、不是算错。

    **一条计分信号都没有就返回 `None`。** 报告那边这时**根本没有这一行**，
    拿一行全是 0 的出来比，只会比出个假「对不上」（2026-09-13 养基阳哥即此）。
    两边都「没有行」才是一致的。
    """
    for p in people:
        if p["name"] == blogger:
            s = stats.summarize(p["board"])
            if not s["n"]:
                return None
            return [str(s["n"]), f"{s['avg']:.2f}", f"{s['acc']:.1f}",
                    f"{s['vol']:.2f}",
                    "—" if s["ir"] is None else f"{s['ir']:+.2f}"]
    return None


def check(blogger: str) -> bool:
    idx = params.get("compare.index", "上证指数")
    want = report_row(blogger, idx)
    got = compare_row(pool.collect([blogger], [], lambda *a: None), blogger)

    if want is None and got is None:
        # 两边都没有这一行 —— **一致，只是没有可比的行**，不是「对不上」。
        # 只要有一条上证计分信号，两边就都该有行；两边都没有 = 他确实没有。
        why = ("报告还没出" if not paths.report_file(blogger).exists()
               else f"没有「{idx}」的计分行")
        print(f"  {blogger}：没有可比的行（{why}）")
        return True

    if want is None or got is None:
        print(f"  {blogger}：**对不上** —— 只有一边有「{idx}」那一行")
        print(f"    单博主报告　{'｜'.join(want) if want else '没有'}")
        print(f"    全博主对比　{'｜'.join(got) if got else '没有'}")
        return False

    if want != got:
        print(f"  {blogger}：**对不上**")
        print(f"    单博主报告　{'｜'.join(want)}")
        print(f"    全博主对比　{'｜'.join(got)}")
        return False
    print(f"  {blogger}：对得上　{'｜'.join(want)}")
    return True


def main(argv: list[str] | None = None) -> int:
    names = list(argv if argv is not None else sys.argv[1:]) or flow.roster()
    print(f"04§3.2 交叉核对（行情到 {market.LAST_DATE}，{len(names)} 位）")
    return 0 if all([check(n) for n in names]) else 1


if __name__ == "__main__":
    sys.exit(main())
