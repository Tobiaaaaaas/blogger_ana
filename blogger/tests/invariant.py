# -*- coding: utf-8 -*-
"""04§3.2 的交叉核对 —— **榜上的数与单博主报告里那五个必须逐格相同**。

> 榜上某位博主的五个数（计分信号／平均分／正确率／波动率／信息比率），
> 与他单博主报告的「汇总指标」逐格相同（03§4.1）。**对不上就是错了。**

**榜不分指数** —— 两边算的都是这位博主的**全部计分信号**（04§3.1）。

这条不能只靠「两边调的是同一个函数」来保证 —— 那样一旦有一边的筛选条件写歪了
（比如漏了「只算计分」），函数再对也照样分叉。所以这里是**从报告正文里把那五个数读回来**，
跟对比那边算出来的比。

**两边都没有那五个数 = 一致，不是「对不上」。** 没有可比的东西和数值不一致是两回事，
混在一起报会把「他本来就没有计分信号」说成「算错了」。

**报告文件压根不在同理** —— 那是上一趟没跑，不是这一步算错。全库重刷之前库里是空的，
这时报「对不上」是**误报**。

    python -m blogger.tests.invariant [博主名…]

**必须带 `-m`** —— 直接 `python blogger/tests/invariant.py` 会因为 `blogger` 不在
`sys.path` 上而报 `ModuleNotFoundError`。

不给博主名就核对全库。`blogger/tests/drive.py` 跑完会顺手调它。
"""

from __future__ import annotations

import re
import sys

from blogger.common import market, paths
from blogger.compare_all import pool
from blogger.report import flow, stats

LINE = re.compile(r"^(正确率|平均分|波动率|信息比率)：(.*)$")
SIGNALS = re.compile(r"^信号总数：(\d+)（计分 (\d+) / 不计分 (\d+)）$")


def report_row(blogger: str) -> list[str] | None:
    """从报告正文的「汇总」里，把那五个数读回来（03§4.1）。

    读回来的是**纸面上的样子**：位数照报告那一格（正确率一位、其余两位）。
    一条计分信号都没有的报告里计分是 0，返回 `None`。
    """
    p = paths.report_file(blogger)
    if not p.exists():
        return None
    parts = p.read_text(encoding="utf-8").split("## 汇总", 1)
    if len(parts) < 2:
        return None
    got: dict[str, str] = {}
    scored: int | None = None
    for line in parts[1].splitlines():
        line = line.strip()
        if m := SIGNALS.match(line):
            scored = int(m.group(2))
            continue
        if m := LINE.match(line):
            got.setdefault(m.group(1), m.group(2).strip())
    if scored is None or not {"正确率", "平均分", "波动率", "信息比率"} <= got.keys():
        return None
    if not scored:
        return None
    return [str(scored),
            f"{float(got['平均分']):.2f}",
            f"{float(got['正确率'].split('%')[0]):.1f}",
            f"{float(got['波动率']):.2f}",
            got["信息比率"]]


def compare_row(people: list[dict], blogger: str) -> list[str] | None:
    """对比那边算出来的那五个 —— 榜上那份样本（全部计分信号）。

    **位数照报告那一格取**（正确率一位、其余两位）—— 「逐格相同」比的是**纸面上的那一格**，
    比到报告根本没有的位数上去，比出来的差是格式差、不是算错。

    **一条计分信号都没有就返回 `None`。** 报告那边这时**根本没有那五个数**，
    拿一行全是 0 的出来比，只会比出个假「对不上」（2026-09-13 养基阳哥即此）。
    两边都「没有」才是一致的。
    """
    for p in people:
        if p["name"] == blogger:
            s = stats.summarize(p["scored"])
            if not s["n"]:
                return None
            return [str(s["n"]), f"{s['avg']:.2f}", f"{s['acc']:.1f}",
                    f"{s['vol']:.2f}",
                    "—" if s["ir"] is None else f"{s['ir']:+.2f}"]
    return None


def check(blogger: str) -> bool:
    if not paths.report_file(blogger).exists():
        # 报告是上一趟跑出来的**产物**，不是这一步算的。没有它就没有可比的东西 ——
        # 那不等于「对不上」。全库重刷之前，库里本来就是空的。
        print(f"  {blogger}：报告还没出，没有可比的东西")
        return True

    want = report_row(blogger)
    got = compare_row(pool.collect([blogger], [], lambda *a: None), blogger)

    if want is None and got is None:
        # 两边都没有那五个数 —— **一致，只是没有可比的东西**，不是「对不上」。
        # 只要有一条计分信号，两边就都该有；两边都没有 = 他确实没有。
        print(f"  {blogger}：没有可比的东西（没有计分信号）")
        return True

    if want is None or got is None:
        print(f"  {blogger}：**对不上** —— 只有一边有那五个数")
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
