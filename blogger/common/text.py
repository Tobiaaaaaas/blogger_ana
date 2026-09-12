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
