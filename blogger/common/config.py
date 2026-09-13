# -*- coding: utf-8 -*-
"""**调用环节**的参数 —— 起始时间的默认值与命令行怎么给。

抓取与解析都是**区间式**的：抓 `[起始时间, 至今]`，抓多少就解析多少。
**起始时间一律由调用环节算好传进来**（见 `docs/01-抓取.md` §0），本文只放默认值与解析。
"""

from __future__ import annotations

from blogger.common import params

BEGIN_DATE = params.get("scrape.begin_date", "2026-01-01")   # 新博主入库的默认起始时间（见 docs/01-抓取.md）


def split_begin_date(argv: list[str]) -> tuple[str, list[str]]:
    """从命令行里摘出起始时间，返回 `(给的日期, 剩下的参数)`。没给就是空串。

        `--begin_date 2026-01-01`    给死日期
        `--begin_date=2026-01-01`    同上

    **只有这一个参数名** —— 试跑要「近两个月」就把日期自己算好传进来。
    """
    given, rest = "", []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--begin_date" and i + 1 < len(argv):
            given = argv[i + 1]
            i += 2
            continue
        if a.startswith("--begin_date="):
            given = a.split("=", 1)[1]
        else:
            rest.append(a)
        i += 1
    return given, rest


def resolve_begin_date(given: str = "") -> str:
    """归一成 `YYYY-MM-DD`。没给就用默认起始时间。"""
    return given or BEGIN_DATE


def resume_start(doc: dict) -> str:
    """**续抓起点 = 上次抓取截止所在那一日的零点**（01§2／01§5）。算不出来给空串。

    03 的更新与 01 的补齐都从这里取 —— 只此一处，别各算各的。
    """
    stamp = (doc or {}).get("scrape_time") or ""
    return f"{stamp[:10]} 00:00" if stamp else ""


__all__ = ["BEGIN_DATE", "split_begin_date", "resolve_begin_date", "resume_start"]
