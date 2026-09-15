# -*- coding: utf-8 -*-
"""文本比对：引文是不是**逐字**出自原帖。

一条结构化数据的 `quote` 是**证据**，不是容器 —— 它必须能在帖子的 `title` 或 `content` 里
逐字搜到。允许**不连续的两段拼起来**（段与段之间在原文里可以不挨着），但每一段都要能搜到、
且顺序不能颠倒。

搜之前先做**版式归一** —— 全角半角、空白、各种引号破折号在各处写法不一，那是版式差异，
不是改写。
"""

from __future__ import annotations

import re
import unicodedata

# 省略号的各种写法：引文用它表示「这里略过一段」
ELLIPSIS_RE = re.compile(r"…+|\.{2,}|。{2,}")

_PUNCT_MAP = str.maketrans({
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "—": "-", "–": "-", "－": "-", "─": "-",
    "，": ",", "。": ".", "、": ",", "；": ";", "：": ":",
    "！": "!", "？": "?", "（": "(", "）": ")", "《": "<", "》": ">",
    "【": "[", "】": "]", "％": "%", "　": " ",
})


def normalize(s: str) -> str:
    """版式归一：全角转半角、统一标点、抹掉所有空白。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_PUNCT_MAP)
    return re.sub(r"\s+", "", s)


def split_quote(quote: str) -> list[str]:
    """按省略号把引文切成若干段。"""
    return [p for p in ELLIPSIS_RE.split(quote or "") if p.strip()]


SEP = "\x01"        # 字段之间的隔断，normalize 不会抹掉它
JOIN = "……"         # 引文并起来时的段间隔，split_quote 认得它


def union_quote(quotes: list[str], *texts: str, limit: int = 0) -> str:
    """把几份引文**并成一份** —— 各段按在帖里的先后接起来，段间用省略号（02§9）。

    重复的段、与别的段重叠的段（同一处只留**最长**的那段）、接上就超 `limit` 的段，都不要。
    一段都留不下就返回空串 —— 调用方自己决定退回哪一份。
    """
    body = SEP.join(b for b in (normalize(t) for t in texts) if b)
    if not body:
        return ""
    frags, seen = [], set()
    for q in quotes:
        for frag in split_quote(q):
            n = normalize(frag)
            if not n or n in seen:
                continue
            seen.add(n)
            i = body.find(n)
            if i >= 0:                   # 搜不到的段不该有（进来的都过了强校验），防一手
                frags.append((i, i + len(n), frag.strip()))

    frags.sort(key=lambda g: (g[0] - g[1], g[0]))   # 长的先来 —— 抢下那处，短的让位
    kept: list[tuple[int, int, str]] = []
    for s, e, frag in frags:
        if any(s < ke and ks < e for ks, ke, _ in kept):
            continue                     # 与已留下的那段重叠 → 不要
        kept.append((s, e, frag))
    kept.sort()                          # 输出照在帖里的先后 —— 顺序颠倒就搜不到了

    out, used = [], 0
    for _, _, frag in kept:
        add = len(frag) + (len(JOIN) if out else 0)
        if limit and used + add > limit:
            continue                     # 接上就超限 → 这一段不要（宁可短，不改字）
        out.append(frag)
        used += add
    return JOIN.join(out)


def verbatim_in(quote: str, *texts: str) -> bool:
    """引文是不是逐字出自这几段文本（**两边都可以**：来源是 `title` 或 `content`）。

    允许**不连续的两段拼起来** —— 段与段之间在原文里可以不挨着，但每一段都要能搜到、
    **顺序不能颠倒**。两段分别来自标题与正文也算数，所以先把几个字段接成一条再比。
    """
    fragments = [normalize(f) for f in split_quote(quote)]
    if not fragments:
        return False
    body = SEP.join(b for b in (normalize(t) for t in texts) if b)
    if not body:
        return False
    pos = 0
    for frag in fragments:
        i = body.find(frag, pos)
        if i < 0:
            return False
        pos = i + len(frag)
    return True
