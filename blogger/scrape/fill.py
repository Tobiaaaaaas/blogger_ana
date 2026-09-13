# -*- coding: utf-8 -*-
"""01§6 补齐 —— 把落后的博主从**各自的 `scrape_time`** 补到今天。

    python -m blogger.scrape.fill              # 全库
    python -m blogger.scrape.fill <博主名>      # 只补这一位

**手动动作，不自动触发。** 起点的算法归这里 —— 抓取自己不看 `scrape_time`（01§0），
「该从哪续」算好了才传进去。起点就是续抓的起点（01§5）：上次抓取截止所在那一日的零点。

**每补完一位就校验一次**（§6）—— 用这位自己算出的起点调 §9 的校验。
起点是这里算的，只有这里知道该传什么；一把跑完直接报出「谁补齐了、谁硬失败」。

退出码：0 = 全都补到位；1 = 有没补成的；2 = 用法错误／库里空。
"""

from __future__ import annotations

import json
import sys

from blogger.common import config, paths
from blogger.scrape import toutiao, verify


def _load(name: str) -> dict:
    try:
        return json.loads(paths.posts_file(name).read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {}


def fill(names: list[str] | None = None, log=print) -> int:
    """逐个补。返回 0 = 全成，1 = 有没补成的。"""
    names = list(names) if names else paths.roster()
    if not names:
        log("库里一位博主都没有。先给一条帖子链接把博主引进来（01§11）。")
        return 2

    log(f"补齐 {len(names)} 位 —— 每位从各自的 scrape_time 补到今天")
    bad = 0
    for i, name in enumerate(names, 1):
        log(f"\n{'=' * 60}\n[{i}/{len(names)}] {name}")
        bad += 0 if _one(name, log) else 1

    log(f"\n补齐跑完：{len(names) - bad} 位到位，{bad} 位有问题")
    return 1 if bad else 0


def _one(name: str, log) -> bool:
    """补一位，补完校验。补到位且无硬失败才算成。"""
    if not paths.posts_file(name).exists():
        log(f"  库里没有这位博主 —— 补齐只补已有的，新博主只能靠帖子链接引进（03§0）")
        return False

    doc = _load(name)
    url = doc.get("source_url") or ""
    if not url:
        log("  文件里没有 source_url，没法定位博主 —— 跳过")
        return False

    start = config.resume_start(doc)
    if start:
        log(f"  起点 {start}（＝上次抓取截止那一日的零点，01§5）")
    else:
        # 只有「从没抓全过」才会走到这里（01§4：只有正常收工才推进抓取截止）。
        # 没有起点就只能从头来，用新博主的默认起始时间。
        start = config.BEGIN_DATE
        log(f"  文件里没有 scrape_time（从没抓全过），改从默认起始时间全量重抓：{start}")

    got = toutiao.run(url, start)
    if not got:
        log("  抓取没成 —— 这一位跳过，下次再来")
        return False
    if got != name:
        log(f"  **注意**：这条链接认出来的是「{got}」，不是「{name}」—— 按 {got} 继续校验")

    # 校验传**与抓取同一个**起点，否则覆盖检查判不了（§9）
    return verify.verify(got, start) == 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].startswith("-"):
        print(f"认不得的参数：{' '.join(argv)}")
        return 2
    if len(argv) > 1:
        print(__doc__.strip())
        return 2
    return fill(argv or None)


if __name__ == "__main__":
    sys.exit(main())
