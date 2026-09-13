# -*- coding: utf-8 -*-
"""blogger_ana —— 按 `docs/01`–`docs/06` 写的实现。

六个功能各占一个包，编号与文档一致。**前三个在 `blogger/` 里，后三个与它同级** ——
04／05／06 是各自独立的一条线，不是 03 的子步骤：

    blogger/scrape/         01 抓取
    blogger/parse/          02 llm解析
    blogger/report/         03 单博主报告
    blogger/compare_all/    04 全博主对比   `python -m blogger.compare_all`
    backtest/               05 回测         `python -m backtest`
    push/                   06 推送         `python -m push <板块>`

`blogger/common/` 是公共地基：路径、参数、行情、判断规则（`consensus.py`）——
**回测与推送读的是同一份规则**，机制两条路、结果必须一致（05§2、06§1）。
"""
