# -*- coding: utf-8 -*-
"""06 的命令行。

    python -m push <板块> [--init] [--dry-run] [--force]

`--init` 建窗口 —— 池里每位抓一次帖、判窗口内那些帖，再攒出初始分布（只跑一次）；
`--dry-run` 只看不发，`--force` 补一档（不在时刻表上也当一档推出去）——
见 06§4、06§5.1、06§8。
"""

import sys

from push import flow

if __name__ == "__main__":
    sys.exit(flow.main())
