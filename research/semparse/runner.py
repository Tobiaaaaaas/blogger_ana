# -*- coding: utf-8 -*-
"""把一位博主判一遍 —— **流程一律从 `blogger.parse` 取**，本模块只负责「怎么跑」。

尺子量的是**上线的那份代码**，不是副本。切句、表态、组装全部走 `blogger.parse`
（`segment`／`annotate`／`assemble`），所以这里量出来的数就是生产链路会得到的数。

分批与排序**照抄** `blogger.report.flow.judge_posts`（先按 `pub` 从新到旧，再筛掉取不到
行情注记的，再按 `extract.build_batches` 切）。不照抄的话，「分批不同」会混进差异里，
量出来的就不是流程的差。

**不写判断缓存、不动库里任何一个字节。**
"""

from __future__ import annotations

import time

from blogger.common import params
from blogger.parse import annotate, assemble, extract
from blogger.report import flow


def _batches(name: str) -> tuple[list[dict], list[dict], list[list[dict]]]:
    posts = flow.load_posts(name)
    posts.sort(key=lambda p: p["pub"], reverse=True)
    ready = extract.ready_posts(posts)
    return posts, ready, extract.build_batches(ready)


def judge(name: str, log=print, prompt: str = "", tail=None) -> dict:
    """判一位博主。返回 `{post_id: {"pub", "signals"}, "__tally__", "__审计__", "__缺口__"}`。

    `prompt`／`tail` 原样交给 `annotate` —— 「连着读两遍」那一版从这两个口子把第一遍的
    表态接回批后面，**分批、切句、组装一样都不动**，量出来的才是「多看了那一遍」的差。
    """
    posts, ready, batches = _batches(name)
    judged: dict[str, dict] = {}
    audit: list[dict] = []
    gaps: list[dict] = []
    tally = {"批": len(batches), "帖": len(posts), "可判": len(ready),
             "产": 0, "丢": 0, "非信号": 0, "无格": 0, "待复核": 0, "缺口": 0,
             "去重": 0, "沉默": 0, "沉默批": 0, "重试": 0,
             "码外": 0, "失败批": 0, "失败帖": 0}

    for bi, batch in enumerate(batches, 1):
        b = annotate.annotate(batch, label=f"{name} 批{bi}/{len(batches)}",
                              prompt=prompt, tail=tail)
        if not b.ok:
            # **失败的那批不记** —— 记了就是把「没判到」当成「判成不产」
            tally["失败批"] += 1
            tally["失败帖"] += len(b.kept)
            log(f"    批 {bi}/{len(batches)} 没调通：{b.tally.get('失败', '')[:120]}")
            continue

        signals, rows, batch_gaps, at = assemble.assemble(b.verdicts, b.kept, b.segs)
        # `产` 是**批内去重后**的数，`去重` 要跟着一起累加 —— 不累加的话账对不上
        # （审计里的「产」行是去重前的，两者差的正是 `去重`）
        for k in ("产", "丢", "非信号", "无格", "待复核", "缺口", "去重"):
            tally[k] += at.get(k, 0)
        tally["码外"] += b.tally.get("码外", 0)
        tally["沉默"] += b.tally.get("沉默数", 0)
        tally["沉默批"] += 1 if b.tally.get("沉默数") else 0
        tally["重试"] += b.tally.get("重试", 0)
        # 审计行**全收**，`非信号` 也收 —— 格名分布是这一版要看的东西，缺了它
        # `zeros` 又成了一串看不出所以然的编号
        audit += [{**r, "博主": name} for r in rows]
        gaps += batch_gaps

        by_post: dict[str, list[dict]] = {}
        for s in signals:
            by_post.setdefault(s["post_id"], []).append(s)
        for p in b.kept:
            judged[p["post_id"]] = {"pub": p["pub"],
                                    "signals": by_post.get(p["post_id"], [])}
        log(f"    批 {bi}/{len(batches)} → {len(signals)} 条"
            + f"／非信号 {at.get('非信号', 0)}"
            + (f"（无格 {at['无格']}）" if at.get("无格") else "")
            + (f"（沉默 {b.tally.get('沉默数')}）" if b.tally.get("沉默数") else ""))
        time.sleep(params.get("parse.batch_pause", 0.5))

    judged["__tally__"] = tally
    judged["__审计__"] = audit
    judged["__缺口__"] = gaps
    return judged


__all__ = ["judge"]
