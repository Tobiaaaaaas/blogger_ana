# -*- coding: utf-8 -*-
"""01§6 对齐总览 —— 把所有人的 `scrape_time` 放在一起，比**距现在多久**。

    python -m blogger.scrape.align

**只读**：不联网、不抓取、不写盘。

    博主              起始         抓取截止            帖数   距今
    张大坤            2026-01-01   2026-09-08 10:14   2191   4 天
    白猫财眼          2026-01-01   2026-09-10 18:40   1847   2 天
    稀豹              2026-01-01   2026-08-28 09:12   1582   15 天

总览**只显示时间差，不划落后线** —— 「多远算落后」是人的判断，不是这里的规则。
真要动手补是 `python -m blogger.scrape.fill`（01§11）。

退出码：0 = 打出总览；2 = 库里一位博主都没有。
"""

from __future__ import annotations

import json
import sys
import unicodedata
from datetime import date, datetime

from blogger.common import paths

HEAD = ("博主", "起始", "抓取截止", "帖数", "距今")


def _load(name: str) -> dict:
    try:
        return json.loads(paths.posts_file(name).read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {}


def days_since(stamp: str) -> int | None:
    """距今天几天。`stamp` 认不出来就是 `None`。"""
    try:
        return (date.today() - datetime.strptime(stamp[:10], "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return None


def overview() -> list[dict]:
    """每人一条 —— 名单就是 `data/posts/` 下的每一位（§0：库里有什么就总览什么）。

    「起始」取文件里**实际最早的那条帖**，不是当初传进去的起始时间 ——
    两者不一样时，说明起点根本没抓到位（feed 就到不了那么早），那正是要看见的东西。
    """
    rows = []
    for name in paths.roster():
        doc = _load(name)
        stamp = (doc.get("scrape_time") or "").strip()
        rows.append({
            "name": name,
            "begin": (doc.get("time_range") or {}).get("earliest") or "—",
            "stamp": stamp[:16] or "—",       # 到分钟就够（§6 的表就这个粒度）
            "posts": len(doc.get("posts") or []),
            "days": days_since(stamp),
        })
    return rows


# ── 打印 ────────────────────────────────────────────────────────────────
#
# 中文字符占两格，`str.ljust` 按字符数补空格必然对不齐 —— 得按显示宽度算。

def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, n: int, right: bool = False) -> str:
    gap = " " * max(0, n - _width(s))
    return gap + s if right else s + gap


def _line(cells: list[str], widths: list[int], right: set[int] = frozenset()) -> str:
    return "   ".join(_pad(c, w, i in right) for i, (c, w) in enumerate(zip(cells, widths)))


def render(rows: list[dict]) -> str:
    """整张表 —— 列宽按内容撑开，数字列右对齐。"""
    body = [[r["name"], r["begin"], r["stamp"], str(r["posts"]),
             "—" if r["days"] is None else f"{r['days']} 天"] for r in rows]
    widths = [max(_width(HEAD[i]), *(_width(r[i]) for r in body)) if body
              else _width(HEAD[i]) for i in range(len(HEAD))]
    return "\n".join([_line(list(HEAD), widths)]
                     + [_line(r, widths, right={3, 4}) for r in body])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        print(f"认不得的参数：{' '.join(argv)}")
        return 2

    rows = overview()
    if not rows:
        print("库里一位博主都没有。先给一条帖子链接把博主引进来（01§11）。")
        return 2

    print(render(rows))
    print(f"\n{len(rows)} 位｜今天 {date.today().isoformat()}。"
          f"总览只报时间差，不划落后线 —— 要补是 `python -m blogger.scrape.fill`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
