# -*- coding: utf-8 -*-
"""02 llm解析 —— **解析一条帖**这一个动作。

输入一批帖，输出零到多条结构化数据。**批的大小、排序、存哪，都不在这里** —— 那是调用方
（03 报告 / 06 推送）的事，本文只管「给我这些帖，我还你结构化数据」。

流程四段（02§10）：

| 段 | 在哪 | 调模型吗 |
|:---|:---|:---|
| ① 切与标 | `segment` | 不调 |
| ② 逐句表态 | `annotate` | **调**，一批一遍；`parse.runs` 遍，第 2 遍起看得见上一遍 |
| ③ 核与组装 | `assemble` | 不调 |
| ④ 失败粒度 | 本文件 | 不调 —— 一批没成只跳过这一批 |

外部事实只有一样：**行情注记**（发帖时刻七个主指数的现值）。**取不到注记的帖不解析** ——
点位类判断会退回「模型凭旧记忆猜」，而旧记忆里的点位和发帖时的点位常常差几百点。
"""

from __future__ import annotations

import time

from blogger.common import market, params
from blogger.parse import annotate, assemble, prompts, schema
from blogger.parse.segment import PER_POST_LIMIT, truncate, weekday_of

BATCH_SIZE = params.get("parse.batch_size", 15)     # 一批最多几条帖
BATCH_CHAR_BUDGET = params.get("parse.batch_char_budget", 30000)
BATCH_PAUSE = params.get("parse.batch_pause", 0.5)  # 批与批之间的间隔（秒）
RUNS = params.get("parse.runs", 1)                  # 逐句表态跑几遍（02§10.2）


def ready_posts(posts: list[dict]) -> list[dict]:
    """挑出**注记取得到**的帖。取不到的这批不解析，等行情补上再说。

    调用方拿它先筛一道，才知道「这次到底判了哪些帖」。
    """
    return [p for p in posts if market.pub_note(p["pub"]) is not None]


def build_batches(posts: list[dict], batch_size: int = BATCH_SIZE) -> list[list[dict]]:
    """按条数与字符预算双重切批。顺序照传入的顺序，**不重排**。"""
    batches, cur, budget = [], [], 0
    for post in posts:
        size = len(truncate(post.get("content") or "")) + len(post.get("title") or "") + 90
        if cur and (len(cur) >= batch_size or budget + size > BATCH_CHAR_BUDGET):
            batches.append(cur)
            cur, budget = [], 0
        cur.append(post)
        budget += size
    if cur:
        batches.append(cur)
    return batches


# ── 入口 ────────────────────────────────────────────────────────────────

def extract(posts: list[dict], batch_size: int = BATCH_SIZE, progress=None,
            on_judged=None) -> tuple[list[dict], dict]:
    """解析这一批帖，返回 `(结构化数据, 统计)`。

    **② 跑 `parse.runs` 遍，以最后一遍为准**（02§10.2）。第 2 遍起把上一遍的表态原样接在
    批文本后面（`annotate.block`）—— 它在同一批原文上再判一次，既能把漏的补上、把错的
    改掉，也在复述上一遍给的答案。`runs = 1` 就是不复读。

    **④ 失败粒度**：某一遍没调通（`annotate` 返回 `ok=False`）→ 这一批记名跳过，其余批
    照常、已成的批照常交给调用方。**不退回上一遍的产出** —— 最终那份必须出自最后一遍，
    退回等于把「没判到」伪装成「判成不产」。

    `on_judged(批里的帖, 这批产出的行, 成没成)`：一批判完就报一次。**调用方靠它记
    「这条帖判过了」** —— 失败的那批不能记，否则这几条帖永远判不到了。
    """
    if RUNS < 1:
        raise ValueError("parse.runs 至少是 1")

    batches = build_batches(posts, batch_size)
    all_signals: list[dict] = []
    tally = {"批": len(batches), "帖": 0, "产": 0, "丢": 0, "非信号": 0, "无格": 0,
             "待复核": 0, "缺口": 0, "去重": 0, "沉默": 0, "沉默批": 0,
             "失败批": 0, "失败帖": [], "丢弃清单": [], "编号错": 0}

    for bi, batch in enumerate(batches, 1):
        signals: list[dict] = []
        rows: list[dict] = []            # 上一遍的审计行 —— 下一遍要拿它摆回去
        gaps: list[dict] = []
        ok = True
        b = None

        for r in range(RUNS):
            # 第 2 遍起：换复读提示词，并把上一遍的表态接在批文本后面
            b = annotate.annotate(
                batch,
                label=f"{bi}/{len(batches)}" + (f" 第{r + 1}遍" if RUNS > 1 else ""),
                prompt="" if r == 0 else prompts.REREAD_PROMPT,
                tail=None if r == 0 else (lambda kept, segs, _r=rows: annotate.block(kept, _r)))
            if not b.ok:
                ok = False
                break
            signals, rows, gaps, at = assemble.assemble(b.verdicts, b.kept, b.segs)
            time.sleep(BATCH_PAUSE)

        if b is None:                    # 一批帖一条都没进（注记全取不到）
            continue
        tally["帖"] += len(b.kept)

        if not ok:
            # **失败的那批不记** —— 记了就是把「没判到」当成「判成不产」（02§11）
            tally["失败批"] += 1
            tally["失败帖"].extend(f"{p['pub']} {p['post_id']}" for p in b.kept)
            if on_judged:
                on_judged(b.kept, [], False)
            continue

        for k in ("产", "丢", "非信号", "无格", "待复核", "缺口", "去重"):
            tally[k] += at.get(k, 0)
        tally["编号错"] += b.tally.get("编号错", 0)
        tally["沉默"] += b.tally.get("沉默数", 0)
        tally["沉默批"] += 1 if b.tally.get("沉默数") else 0
        tally["丢弃清单"].extend(
            f"{r['pub']} {r['post_id']}｜{r['说明']}｜{r['text'][:24]}"
            for r in rows if r.get("处置") == "丢")

        all_signals.extend(signals)
        if on_judged:
            on_judged(b.kept, signals, True)
        if progress:
            progress(bi, len(batches), len(signals))

    all_signals = schema.dedup(all_signals, posts)
    all_signals.sort(key=lambda s: (s["pub"], s["idx"], s["spec"]))
    tally["产"] = len(all_signals)
    return all_signals, tally


def parse_one(post: dict) -> list[dict]:
    """解析单独一条帖 —— 调试用。"""
    sigs, _ = extract([post])
    return sigs


__all__ = ["extract", "parse_one", "build_batches", "ready_posts",
           "weekday_of", "truncate", "BATCH_SIZE", "RUNS", "PER_POST_LIMIT"]
