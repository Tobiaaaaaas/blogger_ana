# -*- coding: utf-8 -*-
"""02§10.2 的守门 —— **验收看有没有错筛，不看覆盖率**。

> 引文所在的**那一整句**是条件句（§3.2），这一处却产了方向 → **丢**。
> **这是唯一一条按字面判死的守门。代码守门不许悄悄改** —— 只丢，且丢了记名。

按字面筛，覆盖率天生不高（「像条件句」的其余几类拦不住）。这不是缺陷 —— 放行一处
该丢的，代价是留着一条错信号；冤枉一处该产的，代价是**永远看不到它**。后者不可逆。

    python -m blogger.tests.gate            # 断言 ＋ 全库旧行复核
    python -m blogger.tests.gate <博主名…>   # 只复核这几位

**必须带 `-m`** —— 直接 `python blogger/tests/gate.py` 会因为 `blogger` 不在
`sys.path` 上而报 `ModuleNotFoundError`。

两段各管一件事：

| 段 | 管什么 | 怎么算过 |
|:---|:---|:---|
| 断言 | 守门与清单的既有口径有没有被改坏 | 全过才退出 0 |
| 复核 | **拿库里已落盘的历史行反过来过一遍守门** | 命中的逐条打出来，**要人读** |

第二段不自动判对错 —— 命中的里面本来就该有条真该丢的。它把「可能被冤枉的那几处」
摆到你眼前，这就是「不看覆盖率」那句话的落实。
"""

from __future__ import annotations

import json
import sys

from blogger.common import paths
from blogger.parse import extract, hints

# ── 断言 ────────────────────────────────────────────────────────────────

_COND = "若明天跌破3900，就减仓；不然继续持有。"
_PLAIN = "明天大盘低开走弱概率大，注意风险。"

# 每一处都是「像条件、其实不是」—— `has_cond` 的七类排除各来一个（§3.2）
_DECOY = [
    ("一旦缩量调整过后", "习惯式，不是挂在条件上"),
    ("主要是这几点", "「要是」的假朋友"),
    ("资金面的情况", "「如果」的假朋友"),
    ("60日均线失守了", "均线名，不是时间窗口"),
]


def _post(pub: str, content: str, title: str = "") -> dict:
    return {"post_id": "1", "pub": pub, "title": title, "content": content}


def checks() -> list[str]:
    """返回没过的那些条 —— 空列表就是全过。"""
    bad: list[str] = []
    p = _post("2026-09-07 16:26", _COND)

    def want(cond: bool, got, what: str) -> None:
        if bool(got) != cond:
            bad.append(f"{what}：期望{'丢' if cond else '放行'}，实际{'丢' if got else '放行'}")

    # 守门 · 该丢的丢
    want(True, hints.cond_reason(p, "若明天跌破3900，就减仓"), "条件句上的方向没被丢")
    # 守门 · 不该丢的放行
    want(False, hints.cond_reason(_post("2026-09-07 16:26", _PLAIN),
                                  "明天大盘低开走弱"), "无条件方向被冤枉")
    for text, why in _DECOY:
        want(False, hints.cond_reason(_post("2026-09-07 16:26", text + "，我看涨。"), text),
             f"「{text}」被冤枉（{why}）")
    # 定位不到 → 放行（跨 title／content 拼起来的引文就走这一路）
    want(False, hints.cond_reason(p, "这句帖里根本没有"), "搜不到的引文被当成条件句丢了")

    # 守门 · 一句引文压住两句：方向在无条件那句里，不许丢
    both = _post("2026-09-07 16:26", "我认为明天会涨。如果放量突破就更好了。")
    want(False, hints.cond_reason(both, "我认为明天会涨。如果放量突破就更好了"),
         "跨句引文被当成条件句丢了")

    # 守门 · **两段引文之间的那一片不算进来**（2026-09-16 实测冤枉过一次，就栽在这里）
    far = _post("2026-09-07 16:26",
                "期待长阳突破，继续逼空！\n\n"
                "上证50指数连续调整两天，如果跌破支撑就要小心了。\n\n"
                "有仓位就别追高了，老老实实去潜伏，会有轮动上涨的。")
    want(False, hints.cond_reason(far, "期待长阳突破，继续逼空！……有仓位就别追高了，"
                                      "老老实实去潜伏，会有轮动上涨的。"),
         "两段引文之间的条件句被算成了这一处的条件")

    # 守门 · 只丢不改：过一遍守门，信号对象逐字节不动
    sig = {"d": -1, "spec": "t1", "idx": "上证指数", "quote": "若明天跌破3900，就减仓"}
    before = json.dumps(sig, sort_keys=True, ensure_ascii=False)
    extract.cond_drop(p, sig)
    if json.dumps(sig, sort_keys=True, ensure_ascii=False) != before:
        bad.append("守门改了信号对象 —— 只许丢，不许改")

    # 清单 · 同一份输入两遍逐字节相同
    for probe in (_post("2026-09-07 16:26", _COND), _post("2026-09-07 16:26", ""),
                  _post("2026-09-07 16:26", "。。。！？")):
        if hints.hints_of(probe) != hints.hints_of(probe):
            bad.append("清单两遍不一致")

    # 清单 · 四栏都认不出 → 整行不出现，不是摆一行「无」
    if hints.hints_of(_post("2026-09-07 16:26", "随便写点什么")):
        bad.append("认不出时仍摆了清单行")

    # 清单 · 具体日期补出四位年份；补出来早于发帖日的是**明年**那一个（§4.3）
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

    return bad


# ── 全库旧行复核 ────────────────────────────────────────────────────────

def _posts_of(name: str) -> dict[str, dict]:
    p = paths.posts_file(name)
    if not p.exists():
        return {}
    return {x["post_id"]: x for x in (json.loads(p.read_text(encoding="utf-8")).get("posts") or [])}


def review(name: str) -> int:
    """把这位博主已落盘的行反过来过一遍守门，命中逐条打出来。返回命中数。"""
    p = paths.signals_file(name)
    if not p.exists():
        return 0
    rows = json.loads(p.read_text(encoding="utf-8")).get("signals") or []
    posts = _posts_of(name)
    hits = 0
    for s in rows:
        post = posts.get(s.get("post_id"))
        if post is None:
            continue
        why = extract.cond_drop(post, s)
        if not why:
            continue
        hits += 1
        print(f"  {s['pub']}  {s['idx']} {s['spec']} {s['d']:+d}")
        print(f"    引文　{s['quote']}")
        print(f"    整句　{why}")
    return hits


def main(argv: list[str] | None = None) -> int:
    names = list(argv if argv is not None else sys.argv[1:]) or paths.roster()

    bad = checks()
    print(f"断言 {len(bad)} 条没过" if bad else "断言全过")
    for b in bad:
        print(f"  ✗ {b}")

    n_rows, n_hits = 0, 0
    print(f"\n全库旧行复核（{len(names)} 位）—— 命中的逐条读，看有没有冤枉的")
    for name in names:
        p = paths.signals_file(name)
        if not p.exists():
            continue
        n_rows += len(json.loads(p.read_text(encoding="utf-8")).get("signals") or [])
        hits = review(name)
        if hits:
            print(f"  ↑ {name} 命中 {hits} 处")
            n_hits += hits
    print(f"\n{n_rows} 行里命中 {n_hits} 处")

    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
