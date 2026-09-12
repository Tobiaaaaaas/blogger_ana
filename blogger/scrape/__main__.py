# -*- coding: utf-8 -*-
"""`python -m blogger.scrape <帖子链接> --begin_date 2026-01-01`"""

import sys

from blogger.scrape.toutiao import main

if __name__ == "__main__":
    sys.exit(main())
