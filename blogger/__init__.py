# -*- coding: utf-8 -*-
"""新一代 blogger_ana —— 按 `docs/01`–`docs/06` 写的实现。

与旧代码严格隔离：本包**不 import** `opinion/`、`scripts/`、`briefing/`、`research/`，
旧代码也不 import 本包。换掉旧代码的方式是把本包改名/上移，不是就地改。

六个功能各占一个子包，编号与文档一致：

    scrape/   01 抓取
    parse/    02 llm解析
    report/   03 单博主报告
    compare/  04 全博主对比
    backtest/ 05 回测
    push/     06 推送
"""
