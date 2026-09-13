# -*- coding: utf-8 -*-
"""06§6 卡片 —— **卡上每一个字都能往回核对**，没有一句是模型重写的。

每位的两行从状态里现成取：谁、什么态度、什么时候见分晓；再附一句原话与它的发帖时刻。
**唯一经模型的是底部那一行总结**，那是另调的（`push.summary`）。
"""

from __future__ import annotations

import textwrap

WEEK = "一二三四五六日"

BULL, BEAR = "🔴", "🟢"        # 红涨绿跌，A 股习惯
INDENT = "　"                  # 原话那行的全角缩进


def render(cfg: dict, now: str, wstart: str, picked: list[dict],
           counts: tuple[int, int], summary: str) -> str:
    """一整张卡。`picked` 按**池子里的顺序**（§0：名单顺序就是显示顺序）。"""
    n_long, n_short = counts
    L = _head(cfg, now, wstart)
    L.append(f"{cfg['mark']} **{cfg['tag']}** · {n_long}多/{n_short}空")
    for rec in picked:
        L += _one(cfg, rec)
    L += ["", f"🧭 {summary}"]
    return "\n".join(L)


def minimal(cfg: dict, now: str, wstart: str) -> str:
    """**零表态时的最小卡**（06§6.3）—— 不渲染名单、不渲染总结，没有人可讲就不占地方。"""
    L = _head(cfg, now, wstart)
    L += [f"{cfg['mark']} **{cfg['tag']}** · 0多/0空",
          f"（前{cfg['window']}个交易日内无人给出本档的上证方向观点）"]
    return "\n".join(L)


# ── 头部两行 ────────────────────────────────────────────────────────────

def _head(cfg: dict, now: str, wstart: str) -> list[str]:
    """① 标题 —— 写的是**这一次实际执行的时刻**，不是应该执行的时刻。

    ② 覆盖范围 —— `前N个交易日` 与起点日期都从回看窗口现算（06§3）。
    """
    title = f"📊 {cfg['name']} {now[11:16]} · {now[5:10]} 周{WEEK[_weekday(now[:10])]}"
    if not wstart:
        return [title, f"🕐 覆盖：{cfg['name']}板块 前{cfg['window']}个交易日到现在"]
    return [title,
            f"🕐 覆盖：{cfg['name']}板块 前{cfg['window']}个交易日到现在（{wstart[5:10]} 起）"]


def _weekday(day: str) -> int:
    from datetime import date
    return date.fromisoformat(day).weekday()


# ── 每位两行 ────────────────────────────────────────────────────────────

def _one(cfg: dict, rec: dict) -> list[str]:
    d = rec.get("d")
    side = "看多" if d > 0 else "看空"
    L = [f"{BULL if d > 0 else BEAR} **{rec['name']}** {side} · 终点 {_直到(cfg, rec)}"]
    quote = (rec.get("quote") or "").strip()
    if quote:
        L.append(f"{INDENT}重点原话：“{_clip(quote, cfg['quote_limit'])}”"
                 f"（{_pub(rec.get('pub'))}）")
    return L


def _直到(cfg: dict, rec: dict) -> str:
    """验证终点：`终点 MM-DD 收盘`。

    日历**含未来一年**（01§10.3），所以「明天」「下周」这类终点都算得出 ——
    **只有终点超过日历末日时才退回写档位**（`spec` 的字段值，如 `week`）。
    """
    ep = rec.get("ep")
    return f"{ep[5:10]} 收盘" if ep else f"{rec.get('spec') or '—'}（终点算不出）"


def _pub(pub: str | None) -> str:
    """括注里是**这句话所属帖子的发布时间**，不是这张卡的发布时间。

    写成 `MM-DD HH:MM` —— 与卡上其他地方同一副面孔（终点、标题都去年份）。
    """
    return (pub or "")[5:16]


def _clip(s: str, limit: int) -> str:
    """引文截断长度照 `report.quote_limit`（06§6.2）—— 与 03§8 是同一个键。"""
    return textwrap.shorten(s.replace("\n", " "), width=limit, placeholder="…") \
        if len(s) > limit else s.replace("\n", " ")


__all__ = ["render", "minimal"]
