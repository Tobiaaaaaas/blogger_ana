# -*- coding: utf-8 -*-
"""强校验 —— 模型产出的每一处，不合格的**就地丢掉**。

这里定义「一条结构化数据」的合法域。**03 与 06 都不再重复校验一遍**，两边共用这一处判定。

一条结构化数据 = **6 个键**：`{post_id, pub, d, spec, idx, quote}`。
模型只写 `d`／`spec`／`idx`／`quote`，`post_id`／`pub` 由系统按帖回填。
"""

from __future__ import annotations

from blogger.common import market, text


def to_signal(raw: dict, post: dict) -> tuple[dict | None, str | None]:
    """把模型产出的一处整理成一条结构化数据。返回 `(信号, None)` 或 `(None, 丢它的原因)`。"""
    if not isinstance(raw, dict):
        return None, "不是对象"

    d = raw.get("d")
    if d not in (1, -1):
        return None, f"方向 d 非法（{d!r}）"

    idx = market.normalize_idx(str(raw.get("idx") or ""))
    if idx not in market.VALID_IDX:
        return None, f"对象 idx 不在八个合法值里（{raw.get('idx')!r}）"

    spec = str(raw.get("spec") or "")
    if not market.spec_ok(spec):
        return None, f"周期 spec 不在档位表里或语义荒谬（{spec!r}）"

    quote = str(raw.get("quote") or "").strip()
    if not quote:
        return None, "引文为空"
    if not text.verbatim_in(quote, post.get("title") or "", post.get("content") or ""):
        return None, f"引文在帖里搜不到（{quote[:30]}…）"

    return {
        "post_id": post["post_id"],
        "pub": post["pub"],
        "d": d,
        "spec": spec,
        "idx": idx,
        "quote": quote,
    }, None


def key_of(signal: dict) -> tuple:
    """同一对象 + 同一周期 + 同一方向 → 只算一条。"""
    return (signal["post_id"], signal["idx"], signal["spec"], signal["d"])


def dedup_with_dropped(signals: list[dict]) -> tuple[list[dict], list[dict]]:
    """同 `dedup`，另外把**被合掉的那些**还给你 —— 03§3.8 要把它们逐条报出来。"""
    best: dict[tuple, dict] = {}
    for s in signals:
        k = key_of(s)
        cur = best.get(k)
        if cur is None or len(s["quote"]) > len(cur["quote"]):
            best[k] = s
    return list(best.values()), [s for s in signals if best[key_of(s)] is not s]


def dedup(signals: list[dict]) -> list[dict]:
    """同帖内同对象同周期同方向的重复表述只留一条（引文取更长的那个，佐证更足）。"""
    return dedup_with_dropped(signals)[0]
