# -*- coding: utf-8 -*-
"""抓完必须校验 —— 在把数据交给任何下游之前跑一次。

    python -m blogger.scrape.verify <博主名> [--begin_date 2026-01-01]

**传的起始时间必须与抓取是同一个值**，否则覆盖检查判不了。

分两类，**报出问题不等于抓取失败**，它只负责说清楚哪里可疑：

- **硬失败**：该抓到的区间没抓全（`post_id` 重复、关键字段为空、接口异常中断、翻页被上限截断）
- **仅提示**：可能完全正常（博主停更造成的日期空档、feed 真的翻到底了）

退出码：0 = 无硬失败；1 = 有硬失败；2 = 用法错误。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta

from blogger.common import config, paths

GAP_DAYS = 7      # 按日缺口阈值：博主停更属正常，只提示


def verify(blogger: str, begin_date: str = "") -> int:
    path = paths.posts_file(blogger)
    if not path.exists():
        print(f"错误：帖子文件不存在 {path}")
        return 2

    data = json.loads(path.read_text(encoding="utf-8"))
    posts = data.get("posts") or []
    stop = data.get("stop_reason") or ""

    print(f"== 校验 {blogger} == {path}")
    print(f"   抓取截止 {data.get('scrape_time') or '（无）'}｜停止原因 {stop or '（无）'}")

    n, hard, warn = 0, 0, 0

    def ok(msg):
        nonlocal n
        n += 1
        print(f"  [{n}] OK   {msg}")

    def bad(msg):
        nonlocal n, hard
        n += 1
        hard += 1
        print(f"  [{n}] 硬失败 {msg}")

    def hint(msg):
        nonlocal n, warn
        n += 1
        warn += 1
        print(f"  [{n}] 提示   {msg}")

    if not posts:
        bad("posts 为空：一条帖都没有")
        print(f"\n结果：{warn} 项提示 / {hard} 项硬失败")
        return 1

    # 重复 post_id —— 去重与合并的唯一钥匙，重复即数据损坏
    dups = {k: v for k, v in Counter(p.get("post_id", "") for p in posts).items() if v > 1}
    if dups:
        sample = "、".join(f"{k}×{v}" for k, v in list(dups.items())[:5])
        bad(f"重复 post_id {len(dups)} 组（{sample}…）")
    else:
        ok("无重复 post_id")

    # 关键字段为空
    empty_id = sum(1 for p in posts if not p.get("post_id"))
    empty_pub = sum(1 for p in posts if not p.get("pub"))
    empty_body = sum(1 for p in posts if not (p.get("content") or "").strip())
    if empty_id or empty_pub or empty_body:
        bad(f"空字段：post_id {empty_id} / pub {empty_pub} / content {empty_body}")
    else:
        ok("无空字段（post_id / pub / content）")

    # 时间跨度与 time_range 是否对得上
    pubs = sorted(p["pub"][:10] for p in posts if p.get("pub"))
    if pubs:
        tr = data.get("time_range") or {}
        if (tr.get("earliest"), tr.get("latest")) != (pubs[0], pubs[-1]):
            hint(f"time_range（{tr.get('earliest')} ~ {tr.get('latest')}）"
                 f"与实际（{pubs[0]} ~ {pubs[-1]}）不一致")
        else:
            ok("time_range 与实际一致")

    # 该抓到的区间没抓到。
    # **判据就是停止原因本身**，不再折天数复核 —— `since` 是抓取自证的：它只在
    # 「本页最新的一条都已早于起始时间」时才盖（01§4），页面按时间倒序且首尾相接，
    # 所以盖了 `since` 就等于「≥ 起始时间的帖一条不落」。
    if not begin_date:
        hint("没传 --begin_date，跳过覆盖检查")
    elif not pubs:
        bad("无任何发帖时间，无法判断覆盖")
    elif stop == "since":
        ok(f"覆盖到位：翻到起始时间才停的（最早 {pubs[0]}，"
           f"起始 {begin_date} 与它之间的那些天 feed 里确实没有帖）")
    elif pubs[0] <= begin_date[:10]:
        # 最早的一条正好落在起始时间当天 —— 这不用靠停止原因，本身就是覆盖到位的铁证
        ok(f"覆盖到位：最早 {pubs[0]} 已到起始时间")
    elif stop == "error":
        bad(f"接口异常中断（已收到 {len(posts)} 条，最早 {pubs[0]}）—— "
            f"这一轮的区间没收全，重抓一次")
    elif stop == "capped":
        bad(f"翻页被上限截断（已收到 {len(posts)} 条，最早 {pubs[0]}）—— "
            f"还拿得到更早的帖，只是没拿。调高页数／条数上限后重抓")
    elif stop == "no_more":
        hint(f"feed 翻到底了（最早 {pubs[0]}）—— 起始时间之前 feed 里确实没有更早的帖")
    else:
        hint(f"最早 {pubs[0]}，且没有终止原因可判读 —— 建议重抓后再看")

    # 按日缺口：博主停更属正常
    if pubs:
        present = set(pubs)
        day = datetime.strptime(pubs[0], "%Y-%m-%d")
        end = datetime.strptime(pubs[-1], "%Y-%m-%d")
        gap, gaps = 0, []
        while day <= end:
            ds = day.strftime("%Y-%m-%d")
            if ds in present:
                if gap >= GAP_DAYS:
                    gaps.append((gap, ds))
                gap = 0
            else:
                gap += 1
            day += timedelta(days=1)
        if gaps:
            gaps.sort(reverse=True)
            sample = "、".join(f"{d} 前缺 {g} 天" for g, d in gaps[:5])
            hint(f"≥{GAP_DAYS} 天的空档 {len(gaps)} 段（{sample}）—— 停更属正常")
        else:
            ok(f"无 ≥{GAP_DAYS} 天的空档")

    print("-" * 60)
    print(f"结果：{warn} 项提示 / {hard} 项硬失败｜{len(posts)} 条帖")
    return 1 if hard else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    begin_date, rest = config.split_begin_date(argv)
    blogger = next((a for a in rest if not a.startswith("-")), "")
    if not blogger:
        print("用法：python -m blogger.scrape.verify <博主名> [--begin_date 2026-01-01]")
        return 2
    return verify(blogger, begin_date)


if __name__ == "__main__":
    sys.exit(main())
