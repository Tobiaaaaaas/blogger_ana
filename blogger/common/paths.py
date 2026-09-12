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
REPORTS_DIR = ROOT / "reports"        # 03 的产物：<博主名>.md

MARKET_DAILY = MARKET_DIR / "market_data.json"      # 日线
MARKET_INTRADAY_DIR = MARKET_DIR / "intraday"       # 30 分钟线

DONE_IDS = STATE_DIR / "done_posts.json"            # 已完成记录：视频帖与置顶帖（01§1）
LEGACY_DONE_IDS = STATE_DIR / "video_posts.json"    # 旧的「已完成记录」，只认不写
PARSE_CACHE_DIR = STATE_DIR / "parse_cache"         # 判过的帖（03§2.2）


def posts_file(blogger: str) -> Path:
    return POSTS_DIR / f"{blogger}.json"


def signals_file(blogger: str) -> Path:
    return SIGNALS_DIR / f"{blogger}.json"


def parse_cache_file(blogger: str) -> Path:
    return PARSE_CACHE_DIR / f"{blogger}.json"


def report_file(blogger: str) -> Path:
    return REPORTS_DIR / f"{blogger}.md"
