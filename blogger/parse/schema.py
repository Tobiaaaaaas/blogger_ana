# -*- coding: utf-8 -*-
"""强校验 —— 模型产出的每一处，不合格的**就地丢掉**。

这里定义「一条结构化数据」的合法域。**03 与 06 都不再重复校验一遍**，两边共用这一处判定。

一条结构化数据 = **6 个键**：`{post_id, pub, d, spec, idx, quote}`。
模型只写 `d`／`spec`／`idx`／`quote`，`post_id`／`pub` 由系统按帖回填。
"""

from __future__ import annotations

import re

from blogger.common import market, params, text


# ── ±10% 兜底：核心预测句未点名指数时，点位须落在上证现值 ±10% 内（02§5.4／§10.1） ──

BAND = params.get("parse.band", 0.10)          # 「合理范围」的半宽
QUOTE_LIMIT = params.get("parse.quote_limit", 60)   # 引文限长（字）
POINT_MIN, POINT_MAX = 1000.0, 20000.0    # 点位量级：低于 1000 的是「还有 X 点空间」，不是点位

# 02§5.2 映射表的关键词 —— 引文里出现任一个，这一处就算**点名了对象**，本规则不适用
IDX_WORDS = ("双创", "创业板", "科创", "半导体", "芯片", "小盘", "成长",
             "中证1000", "中证500", "上证50", "50ETF", "老登", "大金融",
             "银行", "保险", "券商", "证券", "白酒", "沪深300",
             "上证综指", "上证", "综指", "大盘")

NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _band_drop(idx: str, quote: str, pub: str) -> str | None:
    """点位在不在上证现值 ±10% 内 —— 返回该丢的原因，或 `None`（放行）。

    **只在「未点名指数」时生效**：引文里出现了映射表的任何关键词，这一处就是点名了的，
    点位合不合理不归本规则管。

    **只在这一处给的每个候选点位都出带时才丢** —— 一条引文里可能既有目标位又有支撑位，
    脚本分不清哪个是被判的那个数；宁可放过，也不误杀。
    """
    if idx != "上证指数" or any(w in quote for w in IDX_WORDS):
        return None
    now = market.ref_price("上证指数", pub)
    if now is None:
        return None                      # 取不到现值 → 不判，交回给模型
    pts = [v for m in NUM_RE.finditer(quote)
           if POINT_MIN <= (v := float(m.group())) <= POINT_MAX]
    if not pts:
        return None                      # 没给点位 → 默认上证，放行
    lo, hi = now * (1 - BAND), now * (1 + BAND)
    if any(lo < p < hi for p in pts):    # **边界取等**：正好压在 10% 上算带外
        return None
    return (f"点位 {pts[0]:g} 不在上证现值 ±10%（{lo:.0f}~{hi:.0f}）内，"
            f"且这一处未点名指数")


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
    # `d:` 是**未来**的具体日期（02§4.1）—— 早于发帖日的是回顾，不是预测
    if spec.startswith("d:") and spec[2:] < post["pub"][:10]:
        return None, f"具体日期 {spec[2:]} 早于发帖日，是回顾不是预测"

    quote = str(raw.get("quote") or "").strip()
    if not quote:
        return None, "引文为空"
    if len(quote) > QUOTE_LIMIT:      # 02§10.1：超长截到限内，**不丢行**；截断后仍须逐字可搜
        quote = quote[:QUOTE_LIMIT]
    if not text.verbatim_in(quote, post.get("title") or "", post.get("content") or ""):
        return None, f"引文在帖里搜不到（{quote[:30]}…）"

    why = _band_drop(idx, quote, post["pub"])
    if why:
        return None, why

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


def _posts_by_id(posts) -> dict:
    """调用方给的是帖子列表（`[{post_id, title, content, …}]`）或现成的 `{post_id: post}`。"""
    if not posts:
        return {}
    return posts if isinstance(posts, dict) else {p["post_id"]: p for p in posts}


def _merge(group: list[dict], post: dict | None) -> dict:
    """同一条的几处合成一处 —— **引文并成一份**（§9）。

    并出来过不了强校验的（搜不到、或点位出带），退回**最长**的那份：那几份各自都是过了
    强校验进来的，退回去一定还有一条。`post` 取不到（没给帖子）时也退回最长的那份。
    """
    longest = max(group, key=lambda s: len(s["quote"]))
    quotes = list(dict.fromkeys(s["quote"] for s in group))
    if len(quotes) < 2 or post is None:
        return longest
    base = group[0]
    merged = text.union_quote(quotes, post.get("title") or "", post.get("content") or "",
                              limit=QUOTE_LIMIT)
    sig, _ = to_signal({"d": base["d"], "spec": base["spec"],
                        "idx": base["idx"], "quote": merged}, post) if merged else (None, None)
    if sig is None:
        return longest
    return {**sig, **{k: v for k, v in base.items() if k not in sig}}   # 把 post_n 之类带回去


def dedup_with_dropped(signals: list[dict],
                       posts=None) -> tuple[list[dict], list[dict]]:
    """同 `dedup`，另外把**被合掉的那些**还给你 —— 03§3.8 要把它们逐条报出来。"""
    groups: dict[tuple, list[dict]] = {}
    for s in signals:
        groups.setdefault(key_of(s), []).append(s)

    by_id = _posts_by_id(posts)
    out, dups = [], []
    for k, group in groups.items():
        if len(group) == 1:
            out.append(group[0])
        else:
            out.append(_merge(group, by_id.get(k[0])))
            dups += group[1:]
    return out, dups


def dedup(signals: list[dict], posts=None) -> list[dict]:
    """同帖内同对象同周期同方向的重复表述**只留一条，引文并成一份**（§9）。"""
    return dedup_with_dropped(signals, posts)[0]
