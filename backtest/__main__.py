# -*- coding: utf-8 -*-
"""05 的命令行。

    python -m backtest

**就这一条** —— 回测自己先调 04 的全库更新（04§2），不必手动先跑别的命令（05§8）。
"""

import sys

from backtest import flow

if __name__ == "__main__":
    sys.exit(flow.main())
