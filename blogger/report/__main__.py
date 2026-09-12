# -*- coding: utf-8 -*-
"""03 单博主报告的命令行。

    python -m blogger.report.report <博主名 或 帖子链接> [--begin_date 2026-01-01]
    python -m blogger.report.report_all [--begin_date 2026-01-01]

`--begin_date` 只对**库里还没有的新博主**生效（全量抓的起点）；旧博主一律走续抓起点。

两个命令共用这一处入口，靠 `argv[0]` 分不出来，所以由 `report.py` / `report_all.py`
两个薄壳各自调。直接跑本模块等于跑 `report`。
"""

from __future__ import annotations

import sys

from blogger.common import config
from blogger.report import flow


def main(argv: list[str] | None = None, all_bloggers: bool = False) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    begin_date, rest = config.split_begin_date(argv)

    runs, no_market, names = 1, False, []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--runs":
            i += 1
            runs = int(rest[i])
        elif a == "--no-market":
            no_market = True
        elif not a.startswith("-"):
            names.append(a)
        else:
            print(f"认不得的参数：{a}")
            return 2
        i += 1

    if all_bloggers:
        return flow.report_all(begin_date, runs, not no_market)
    if len(names) != 1:
        print(__doc__.strip())
        return 2
    return flow.report_one(names[0], begin_date, runs, not no_market)


if __name__ == "__main__":
    sys.exit(main())
