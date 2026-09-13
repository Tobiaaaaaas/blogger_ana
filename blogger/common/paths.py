# -*- coding: utf-8 -*-
"""全系统的路径常量 —— 只有这一处写死目录，别处一律 import。

`BLOGGER_ROOT` 环境变量可以把整个数据根挪到别处 —— 测试时用它写进临时目录，
生产数据一个字节都不碰。
"""

import os
from pathlib import Path

ROOT = Path(os.environ.get("BLOGGER_ROOT") or Path(__file__).resolve().parents[2]).resolve()

DATA = ROOT / "data"

POSTS_DIR = DATA / "posts"            # 01 抓取的产物：<博主名>.json
SIGNALS_DIR = DATA / "signals"        # 02 解析的产物：<博主名>.json
MARKET_DIR = DATA / "market"
STATE_DIR = DATA / "state"            # 辅助记录，不是产物
REPORTS_DIR = ROOT / "reports"        # 产物根：03 与 04 都落这儿
PER_BLOGGER_DIR = REPORTS_DIR / "per_blogger"   # 03 的产物：<博主名>.md
COMPARE_FILE = REPORTS_DIR / "博主对比.md"       # 04 的产物
BACKTEST_RUNS = ROOT / "backtest" / "runs"    # 05 的产物：<日期>_<时刻>/ 一个夹子
BRIEFINGS_DIR = DATA / "briefings"    # 06 的留档：<日期>_<时刻>_<板块>.json

MARKET_DAILY = MARKET_DIR / "market_data.json"      # 日线
MARKET_INTRADAY_DIR = MARKET_DIR / "intraday"       # 30 分钟线
MARKET_CAL = MARKET_DIR / "trade_cal.json"          # 官方交易日历 —— 就是系统日历（01§10.3）

DONE_IDS = STATE_DIR / "done_posts.json"            # 已完成记录：视频帖与置顶帖（01§1）
LEGACY_DONE_IDS = STATE_DIR / "video_posts.json"    # 旧的「已完成记录」，只认不写
PARSE_CACHE_DIR = STATE_DIR / "parse_cache"         # 判过的帖（03§2.2）


def roster() -> list[str]:
    """名单 —— **所有抓过的博主**：`data/posts/` 下的每一位（03§6）。

    **不是**已有信号文件的博主 —— 否则新博主一旦还没解析过，就永远进不了名单。
    03／04／01 的对齐总览用的是**同一份名单**，所以只在这一处算。

    放在这里而不是报告链里，是为了让**只读命令**（`blogger.scrape.align`）拿得到名单
    又不必把报告链连同浏览器一起拉起来。
    """
    if not POSTS_DIR.exists():
        return []
    return sorted(p.stem for p in POSTS_DIR.glob("*.json"))


def posts_file(blogger: str) -> Path:
    return POSTS_DIR / f"{blogger}.json"


def signals_file(blogger: str) -> Path:
    return SIGNALS_DIR / f"{blogger}.json"


def parse_cache_file(blogger: str) -> Path:
    return PARSE_CACHE_DIR / f"{blogger}.json"


def report_file(blogger: str) -> Path:
    return PER_BLOGGER_DIR / f"{blogger}.md"
