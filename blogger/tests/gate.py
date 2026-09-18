# -*- coding: utf-8 -*-
"""02§10.1／§10.5 字面辅助层的断言 —— **清单与复核的既有口径有没有被改坏**。

> 清单只摆不判，复核只报不改。**这一层没有一处按字面删行。**

**复核命中不等于错** —— 它只指出「产出与引文里能查到的字面对不上」，改不改由模型（§10.5）。
所以这里断的是**每一条的查出条件本身**，不断言它判得准。

    python -m blogger.tests.gate

**必须带 `-m`** —— 直接 `python blogger/tests/gate.py` 会因为 `blogger` 不在
`sys.path` 上而报 `ModuleNotFoundError`。
"""

from __future__ import annotations

import json
import sys

from blogger.parse import hints

# ── 断言 ────────────────────────────────────────────────────────────────

_COND = "若明天跌破3900，就减仓；不然继续持有。"


def _post(pub: str, content: str, title: str = "") -> dict:
    return {"post_id": "1", "pub": pub, "title": title, "content": content}


def _sig(pub: str, quote: str, **kw) -> dict:
    """一条待复核的产出 —— 默认这一处本身是自洽的，各条断言只改要试的那一栏。"""
    return {"pub": pub, "quote": quote, "d": 1, "spec": "t1", "idx": "上证指数", **kw}


def checks() -> list[str]:
    """返回没过的那些条 —— 空列表就是全过。"""
    bad: list[str] = []

    # 清单 · 同一份输入两遍逐字节相同
    for probe in (_post("2026-09-07 16:26", _COND), _post("2026-09-07 16:26", ""),
                  _post("2026-09-07 16:26", "。。。！？")):
        if hints.hints_of(probe) != hints.hints_of(probe):
            bad.append("清单两遍不一致")

    # 清单 · 四栏都认不出 → 整行不出现，不是摆一行「无」
    if hints.hints_of(_post("2026-09-07 16:26", "随便写点什么")):
        bad.append("认不出时仍摆了清单行")

    # 清单 · 具体日期补出四位年份；补出来早于发帖日的是**明年**那一个（§4.1）
    for text, want_date in (("12月20日会涨", "d:2026-12-20"), ("3月2日会涨", "d:2027-03-02")):
        got = hints.hints_of(_post("2026-09-07 16:26", text))
        if want_date not in got:
            bad.append(f"「{text}」该补成 {want_date}：{got}")

    # 清单 · 同一位置取最长：「不会大涨」只摆一个词，不许再摆出「大涨」「涨」
    got = hints.hints_of(_post("2026-09-07 16:26", "明天不会大涨"))
    if got.split("方向词：")[-1] != "不会大涨":
        bad.append(f"方向词栏没取最长匹配：{got}")

    # 清单 · 均线名不许当时间词
    got = hints.hints_of(_post("2026-09-07 16:26", "60日均线失守就看空"))
    if "均线" in got.split("｜ 对象词")[0]:
        bad.append(f"均线名进了时间词栏：{got}")

    # 复核 · 引文里的对象词与产出对不上 → 报出来（§10.5）
    if not hints.contradiction(_sig("2026-09-07 16:26", "科创板明天会有超跌反弹的机会",
                                    idx="上证50")):
        bad.append("引文里的对象词与 idx 对不上，没报出来")

    # 复核 · 引文里的时间词与产出对不上 → 报出来
    if not hints.contradiction(_sig("2026-09-07 16:26", "科创50明天会有超跌反弹的机会",
                                    spec="t5", idx="科创50")):
        bad.append("引文里的时间词与 spec 对不上，没报出来")

    # 复核 · 引文里查不出值 → 放行（那是**查不着**，不是对不上）
    if hints.contradiction(_sig("2026-09-07 16:26", "明天低开走弱概率大")):
        bad.append("引文里查不出对象词却报了矛盾")

    # 复核 · 产出 long 不算矛盾 —— 开区间，引文里查出某一天不等于冲突
    if hints.contradiction(_sig("2026-09-07 16:26", "等明年5月28号再说", spec="long")):
        bad.append("long 被当成了矛盾")

    # 复核 · **方向那一栏不查** —— 字面反了不算数（引文里的方向词是词义层面的值）
    if hints.contradiction(_sig("2026-09-07 16:26", "科创50明天不会大跌",
                                idx="科创50", d=1)):
        bad.append("方向那一栏查了 —— 它逐条读完一条真错也没有")

    # 复核 · 只报不改：过一遍复核，信号对象逐字节不动
    sig = _sig("2026-09-07 16:26", "科创板明天会有超跌反弹的机会", idx="上证50")
    before = json.dumps(sig, sort_keys=True, ensure_ascii=False)
    hints.contradiction(sig)
    if json.dumps(sig, sort_keys=True, ensure_ascii=False) != before:
        bad.append("复核改了信号对象 —— 只许报，不许改")

    # 复核 · 引文所在的那整句是条件句、这一处却产了方向 → 报出来（§3.2）
    post = _post("2026-09-07 16:26", _COND)
    if not hints.suspects(post, [_sig("2026-09-07 16:26", "若明天跌破3900")]):
        bad.append("引文压在条件句上、这一处却产了方向，没报出来")

    # 复核 · 引文落在的句子里**有一句不是条件句** → 放行（前提管不着的那一处，照产）
    post = _post("2026-09-07 16:26", "明天低开就走弱。若跌破3900，就减仓。")
    if hints.suspects(post, [_sig("2026-09-07 16:26", "明天低开就走弱")]):
        bad.append("引文落在的句子无条件，却报了条件句那一栏")

    # 复核 · 引文在帖里搜不到 → 一律不判（落不到不是对不上）
    if hints.suspects(_post("2026-09-07 16:26", "随便写点什么"),
                      [_sig("2026-09-07 16:26", "若明天跌破3900")]):
        bad.append("引文在帖里搜不到，条件句那一栏仍开了火")

    # 复核 · 同帖同对象同周期、方向相反 → 两条都报出来（§6 骑墙）
    post = _post("2026-09-07 16:26", "涨多了，卖一点；跌多了，买一点。")
    pair = [_sig("2026-09-07 16:26", "涨多了，卖一点", d=-1),
            _sig("2026-09-07 16:26", "跌多了，买一点", d=1)]
    if len(hints.suspects(post, pair)) != 2:
        bad.append("同帖方向相反的两条，没两条都报出来")

    # 复核 · 方向相同、或周期不同 → 不算互斥
    for peer in (_sig("2026-09-07 16:26", "跌多了，买一点", d=-1),
                 _sig("2026-09-07 16:26", "跌多了，买一点", d=1, spec="t5")):
        if hints.suspects(post, [_sig("2026-09-07 16:26", "涨多了，卖一点", d=-1), peer]):
            bad.append(f"不互斥的两条被当成了互斥（{peer['d']:+d} {peer['spec']}）")

    # 复核 · 同一处命中几条 → 并成一行，不是摆两行（摆两行模型会当两处答）
    post = _post("2026-09-07 16:26", "若明天跌破3900，就减仓。")
    both = _sig("2026-09-07 16:26", "若明天跌破3900", idx="科创50", d=-1)
    if len(hints.suspects(post, [both])) != 1:
        bad.append("一处命中几条时没并成一行")

    return bad


def main() -> int:
    bad = checks()
    print(f"断言 {len(bad)} 条没过" if bad else "断言全过")
    for b in bad:
        print(f"  ✗ {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
