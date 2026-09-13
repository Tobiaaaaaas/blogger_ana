# -*- coding: utf-8 -*-
"""04 的命令行。

    python -m blogger.compare_all [--begin_date 2026-01-01]

`--begin_date` 透传给第一步的全库更新，**只对库里还没有的新博主有效**（03§7）。
"""

import sys

from blogger.compare_all import flow

if __name__ == "__main__":
    sys.exit(flow.main())
