# -*- coding: utf-8 -*-
"""`python -m blogger.report.report_all` —— 全库，每一位都更新一遍。"""

import sys

from blogger.report.__main__ import main

if __name__ == "__main__":
    sys.exit(main(all_bloggers=True))
