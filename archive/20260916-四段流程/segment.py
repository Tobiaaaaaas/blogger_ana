# -*- coding: utf-8 -*-
"""① 切与标 —— 把帖切成可指认的单元（句），逐句打标记。**零模型调用。**

切句是这套流程的地基：模型不再自己划「一处表述」的边界，只对**编好号的句子**表态。
单元固定下来，「哪一句」才可审、可指认、可复算。

标记（`lexicons.marks_of`）是**提示**，不是判决 —— 它只用来做两件事：提醒模型这几句不许
沉默，以及给 `assemble` 的守门做依据。切句与标记都是纯函数：同一份输入重跑逐字节相同。
"""

from __future__ import annotations

import re
from datetime import date

from blogger.common import market, params
from blogger.parse import lexicons

# 断句点 —— 句末标点，**加句内分号**。中文帖里「！」「？」也断句。
SENT_END = re.compile(r"(?<=[。！？!?；;])")

# 一个单元里至少要有这么一个字才算数 —— 光剩标点的碎片不成句
_HAS_WORD = re.compile(r"[\w一-鿿]")

TITLE_S = 0                  # 标题占句号 0；正文从 1 起

PER_POST_LIMIT = params.get("parse.per_post_limit", 4000)   # 单帖正文截断长度

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def weekday_of(pub: str) -> str:
    """发帖日的周几 —— 02§2：判定「本周／今天」这类周期词离不开发帖时间与周几，
    不能让模型从日期自己推。"""
    try:
        return WEEKDAY_CN[date.fromisoformat(pub[:10]).weekday()]
    except ValueError:
        return ""


def truncate(s: str, limit: int = PER_POST_LIMIT) -> str:
    """超长正文掐中间：保头 60%、尾 40% —— 结论常在开头，落款与收尾也常带信息。"""
    if len(s) <= limit:
        return s
    head = int(limit * 0.6)
    return s[:head] + "\n……（中略）……\n" + s[-(limit - head):]


def sentences(text: str) -> list[str]:
    """按断句点切句，去掉空白句与纯标点碎片。**顺序与边界都确定**。

    **分号断句，省略号不断。** 这两条都是实测定的：

    - 语料里大量用 `；` 当句内停顿，一个 `。` 段落常常是**一整段**十几处表述。只按句末
      标点切，单元中位 39 字、最长 632 字、超 200 字的 1532 个；而模型天然按小句数 ——
      它会照着段落里的实际小句数往下编编号，编到合法编号之外（实测：一段 2 句的帖，
      模型给到 `s:22`；另几次直接退化到 `s:327`，8192 token 耗尽截断）。加上 `；` 之后
      超 200 字的只剩 44 个，实测同一条帖 20 句、连跑三次全部干净收尾、零越界。
    - **省略号不断**。「……」在中文帖里多数是句中一顿（「第一……第二……」），按它切会
      把一句拆成两截半句 —— 试过，句数翻一倍（→ 74318），反而不成句。
    """
    return [s for s in (p.strip() for p in SENT_END.split(text or ""))
            if s and _HAS_WORD.search(s)]


def segment_post(post: dict) -> list[dict]:
    """一条帖 → `[{"s": 句号, "text": 原话, "marks": 标记串}, …]`。

    标题占 `s=0`（标题常直接给出预测结论，02§2），正文从 `s=1` 起。超长正文先照
    `truncate` 掐中间，再切句。
    """
    body = truncate(post.get("content") or "")
    rows: list[dict] = []
    title = (post.get("title") or "").strip()
    if title:
        rows.append({"s": TITLE_S, "text": title, "marks": lexicons.marks_of(title)})
    for i, s in enumerate(sentences(body), start=1):
        rows.append({"s": i, "text": s, "marks": lexicons.marks_of(s)})
    return rows


def render_post(n: int, post: dict, note: str, rows: list[dict]) -> str:
    """一条帖喂给模型的样子：帖号、发帖时间**加周几**、行情注记、逐句编号带标记。"""
    head = f"[{n}] 发帖 {post['pub']} {weekday_of(post['pub'])}"
    lines = [head, note]
    for r in rows:
        tag = f"[{r['marks']}]" if r["marks"] else ""
        lines.append(f" {n}.{r['s']} {tag} {r['text']}")
    return "\n".join(lines)


def render_batch(posts: list[dict]) -> tuple[str, list[dict], list[dict[int, dict]]]:
    """渲染一批帖。返回 `(给模型的文本, 真正进了这批的帖, 每条的句表)`。

    **注记取不到的帖直接不进批** —— 不解析它，也不给它编一个位置（02§2.2）。
    句表与帖一一对应，且**按句号索引**（`{句号: 行}`）而不是按位置 —— 标题缺席时句号不
    从 0 起头，按位置查会整体错开一位、最后一句越界。带 `T`／`D` 的句子漏判就是从这里
    开始错的，所以这一处宁可按句号查。
    """
    blocks, kept, segs = [], [], []
    for post in posts:
        note = market.pub_note(post["pub"])
        if note is None:
            continue
        rows = segment_post(post)
        if not rows:
            continue
        blocks.append(render_post(len(kept), post, note, rows))
        kept.append(post)
        segs.append({r["s"]: r for r in rows})
    return "\n\n".join(blocks), kept, segs


__all__ = ["sentences", "segment_post", "render_post", "render_batch", "TITLE_S",
           "truncate", "weekday_of", "PER_POST_LIMIT", "SENT_END"]
