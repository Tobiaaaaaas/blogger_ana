# -*- coding: utf-8 -*-
"""单独跑一遍解析（调试/试跑用；正式产物由 03 单博主报告写）。

    python -m blogger.parse <博主名> [--runs 1] [--limit 20] [--no-check]
    python -m blogger.parse <博主名> --begin_date 2026-07-12   （试跑：只看这之后的帖）

**本模块不走缓存、也不落盘** —— 它只是把 02 拿一批帖跑一遍给你看。
正式链路的「判过的帖不重判」在 03 里。

`--begin_date` 在这里**只是一道显示过滤** —— 主文件里的帖本来就都在区间内
（越界的在 01 就滤掉了），这个参数是给你临时缩范围试跑用的。
"""

from __future__ import annotations

import json
import sys
import time

from blogger.common import config, paths
from blogger.parse import extract


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    begin_date, argv = config.split_begin_date(argv)

    blogger, runs, limit, check = "", 1, 0, True
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--runs":
            i += 1; runs = int(argv[i])
        elif a == "--limit":
            i += 1; limit = int(argv[i])
        elif a == "--no-check":
            check = False
        elif not a.startswith("-") and not blogger:
            blogger = a
        i += 1

    if not blogger:
        print(__doc__.strip())
        return 2

    path = paths.posts_file(blogger)
    if not path.exists():
        print(f"没有这位博主的帖子文件：{path}")
        return 2

    posts = json.loads(path.read_text(encoding="utf-8")).get("posts") or []
    if begin_date:
        posts = [p for p in posts if (p.get("pub") or "")[:10] >= begin_date[:10]]
    posts.sort(key=lambda p: p["pub"])          # 旧→新，便于从最早的开始看
    if limit:
        posts = posts[:limit]
    print(f"{blogger}：{len(posts)} 条帖待解析"
          f"（{begin_date or '全区间'}）｜runs={runs}｜自查={check}")

    t0 = time.time()
    signals, tally = extract.extract(posts, runs=runs, self_check=check,
                                     progress=lambda i, n, k: print(f"  批 {i}/{n} → {k} 条"))
    print(f"\n用时 {time.time() - t0:.0f}s｜{tally}")
    for s in signals:
        print(f"  {s['pub']}  d={s['d']:+d}  {s['spec']:8} {s['idx']:6}  {s['quote'][:44]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
