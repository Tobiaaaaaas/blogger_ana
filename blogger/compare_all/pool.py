# -*- coding: utf-8 -*-
"""① 全库更新 · ② 收集 · ③ 现算 —— 把每位博主压成一份算好的样本（见 04§2、§3）。

**这一步是 03 的 `report_all`**，本文不写第二套：名单、抓法、解析、验证一律照 03。

**没跑成的博主不带进对比**，单列在报告头部 —— 绝不拿他上一次的旧数据顶上（04§2）。
"""

from __future__ import annotations

from blogger.report import flow, render, stats, store, verify


def update(begin_date: str, refresh: bool, log) -> tuple[list[str], list[str]]:
    """① 全库更新。返回 `(名单, 本轮更新失败的)`。"""
    failed: list[str] = []
    flow.report_all(begin_date, refresh, log=log,
                    on_done=lambda name, ok: None if ok else failed.append(name))
    return flow.roster(), failed


def collect(names: list[str], failed: list[str], log) -> list[dict]:
    """② 收集 ③ 现算 —— 每位博主一份样本。

    每份样本里的 `rows` 是全部行（含不是信号的那三档），`scored` 是计分的 ——
    **榜上的一切数字都从 `scored` 来**：榜不分指数，八个指数混在一张榜里排（04§3.1）。
    """
    out: list[dict] = []
    for name in names:
        if name in failed:
            continue
        rows = [verify.evaluate(r) for r in store.load(name)]
        days = sorted(p["pub"][:10] for p in flow.load_posts(name) if p.get("pub"))
        t = stats.tally(rows)
        months = render.months_between(days)
        short = render.sample_short(months, t["scored"])
        scored = [r for r in rows if r["note"] == verify.SCORED]
        out.append({
            "name": name,
            "rows": rows,
            "scored": scored,
            "months": months,
            "short": short,
            "in": not short,          # 够不够参与对比（04§4.1）
        })
    log(f"  参与对比 {sum(1 for p in out if p['in'])} 位"
        f"／够不上样本线 {sum(1 for p in out if not p['in'])} 位"
        + (f"／更新失败 {len(failed)} 位" if failed else ""))
    return out


__all__ = ["update", "collect"]
