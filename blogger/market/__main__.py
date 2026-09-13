# -*- coding: utf-8 -*-
"""01§10 的命令行。

    python -m blogger.market [--until 2026-09-13]
    python -m blogger.market --check

**差一天就非零退出** —— 静默退化的代价比抓不到大得多（01§10.4）。
"""

import sys

from blogger.market import flow

if __name__ == "__main__":
    sys.exit(flow.main())
