# -*- coding: utf-8 -*-
"""`python -m blogger.report.report <博主名 或 帖子链接>` —— 一位博主，入库或更新。"""

import sys

from blogger.report.__main__ import main

if __name__ == "__main__":
    sys.exit(main(all_bloggers=False))
