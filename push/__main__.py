# -*- coding: utf-8 -*-
"""06 的命令行。

    python -m push <板块> [--init] [--dry-run]

`--init` 建窗口（只跑一次），`--dry-run` 只看不发（06§4、06§8）。
"""

import sys

from push import flow

if __name__ == "__main__":
    sys.exit(flow.main())
