# -*- coding: utf-8 -*-
"""05 的主流程 —— 全库更新 → 逐档攒分布 → 状态机 → 成交 → 盯市 → 出报告（05§1）。

    python -m backtest

**就这一条命令。** 回测自己先调 04 的**全库更新**（04§2），把库里每一位刷新到同一时点，
再开始逐档推进 —— 不必手动先跑别的命令（05§8）。

**`backtest.update` 关掉时只省抓帖** —— 直接拿 `data/signals/` 里现成的开跑，
**行情照刷**，那是算价的前提（05§8）。

**每一档都从头重算窗口与分布** —— 不增量、不缓存。回测是事后跑的，增量只会引入前视。
"""

from __future__ import annotations

import bisect
import sys
from datetime import date, datetime

from blogger.common import config, consensus, market, paths
from blogger.compare_all import pool as cmp_pool
from blogger.report import flow as report_flow, store

from backtest import book as book_mod, conf, render

# 05§8：**回测不给自己开开关** —— 新博主的抓取起点走 `scrape.begin_date`、
# 一条帖跑几遍走 `parse.runs`、先刷行情。要改这些就改配置。
BEGIN_DATE = config.BEGIN_DATE

# 05§0：**回测只考察上证指数** —— 写死的，不开配置键（04 的榜已改吃全部计分信号，
# 那条线上只剩本文与推送）。
IDX = "上证指数"


def run(log=print) -> int:
    """跑一次回测。返回 0 成功、2 出错。"""
    cfg = conf.load()
    if not cfg["pool"]:
        log("回测池是空的 —— `backtest.pool` 里一位都没有。")
        return 2
    if not cfg["grid"]:
        log("时刻表是空的 —— `push.grid.trading` 里一档都没有。")
        return 2

    log("[① 全库更新]")
    if cfg["update"]:
        names, failed = cmp_pool.update(BEGIN_DATE, True, log)
        if failed:
            log(f"  这 {len(failed)} 位这轮没更新成：{'、'.join(failed)}")
    else:
        # `backtest.update` 关掉 —— 只省抓帖，**行情照刷**，那是 §5 算价的前提（05§8）。
        log("  关掉了（backtest.update = false）—— 不抓帖，只刷行情")
        report_flow.market_refresh(log)
        names, failed = paths.roster(), []
    if not names:
        log("库里一位博主都没有。先给一条帖子链接把博主引进来（03§0）。")
        return 2

    log("[② 攒信号]")
    rows, named, missing = _load(cfg, log)
    if not rows:
        log("池子里一位都没有可用的信号（上证、跨度 ≥ "
            f"{cfg['bucket_span']}）—— 没有可回测的。")
        return 2

    log("[③ 定区间]")
    spans = _span(cfg, rows, log)
    begin, end, days = spans
    if not days:
        log(f"  区间 {begin} ~ {end} 里一个交易日都没有 —— 跑不了。")
        return 2

    log("[④ 逐档推进]")
    bk = _walk(cfg, rows, begin, days, log)
    if not bk.curve:
        log("  一档都没走成 —— 行情没覆盖到这段区间？")
        return 2

    log("[⑤ 出报告]")
    _write(cfg, bk, spans, named, missing, log)
    return 0


# ── ② 攒信号 ────────────────────────────────────────────────────────────

def _load(cfg: dict, log) -> tuple[dict, dict, list[str]]:
    """池里每一位的候选信号 —— **先筛**（05§3 第 1 步）。

    | 筛掉什么 | 判据 |
    |:---|:---|
    | 不是上证 | `idx` ≠ `上证指数` |
    | 超短期 | 交易日跨度 < `report.bucket_span` |

    跨度为 `None` 的（`long`、或终点超出日历）一并落在这里 —— 算不出跨度就分不了档。
    """
    bucket = cfg["bucket_span"]
    out, named, missing = {}, {}, []
    for name in cfg["pool"]:
        picked = []
        for sig in store.load(name):
            if sig.get("idx") != IDX:
                continue
            rec = consensus.derive(sig)
            if rec["span"] is not None and rec["span"] >= bucket:
                picked.append(rec)
        if not picked:
            missing.append(name)
            continue
        picked.sort(key=lambda r: r["pub"])
        out[name] = picked
        named[name] = len(picked)
    log(f"  池子 {len(cfg['pool'])} 位｜有数据 {len(out)} 位"
        + (f"｜没数据 {len(missing)} 位" if missing else ""))
    return out, named, missing


# ── ③ 定区间 ────────────────────────────────────────────────────────────

def _span(cfg: dict, rows: dict, log) -> tuple[str, str, int]:
    """`[begin, end]` 与区间内的交易日数（05§5.3）。

    | 键 | 空着时取什么 |
    |:---|:---|
    | `begin` | **信号能覆盖到的最早那天** —— 更早的档必然空仓，白拉一段平坦净值 |
    | `end` | **行情末日** |
    """
    begin = cfg["begin"] or min(r["pub"][:10] for rs in rows.values() for r in rs)
    end = cfg["end"] or market.LAST_DATE
    days = [d for d in market.CAL if begin <= d <= end]
    log(f"  {begin} ~ {end}｜{len(days)} 个交易日")
    return begin, end, days


# ── ④ 逐档推进 ──────────────────────────────────────────────────────────

def _walk(cfg: dict, rows: dict, begin: str, days: list[str], log) -> book_mod.Book:
    bk = book_mod.Book(cfg["long_symbol"], cfg["short_symbol"])
    window = int(cfg["window"])

    pubs = {n: [r["pub"] for r in rs] for n, rs in rows.items()}
    bench = {"long": [], "short": []}
    skipped = 0
    i = -1
    last = None

    for day in days:
        wstart = consensus.window_start(day, window)
        for tick in cfg["grid"]:
            now = f"{day} {tick}"
            px = {leg: market.ref_price(cfg[f"{leg}_symbol"], now) for leg in ("long", "short")}
            if px["long"] is None or px["short"] is None:
                skipped += 1
                continue
            i += 1
            last = (i, now, px)

            picked = [r for r in _latest(rows, pubs, now, wstart) if r]
            e, longs = consensus.spread(picked)
            bk.switch(i, now, book_mod.decide(bk.pos, e, longs, cfg), px)
            bk.mark(now, px)
            bench["long"].append(px["long"])
            bench["short"].append(px["short"])

    if last is None:
        return bk
    if bk.pos:
        # **区间末尾还持着仓 → 按末档现值强行平掉，记成完整一笔**（05§5.3）。
        # 末档的净值本来就是按这个价记的，所以曲线不用重记。
        bk.switch(last[0], last[1], 0, last[2])
        log("  末尾那一笔按末档平掉了")

    _normalize(bench)
    bk.bench = bench
    log(f"  {len(bk.curve)} 档｜{len(bk.trades)} 笔"
        + (f"｜{skipped} 档取不到价、跳过" if skipped else ""))
    return bk


def _latest(rows: dict, pubs: dict, now: str, wstart: str) -> list[dict]:
    """池里每一位取「窗口内最新的一条」（05§3 第 2 步）。取不到的这位不进分布。

    先**二分**到「`pub` ≤ 本档时刻」的右边界，再往回走到滑出窗口为止 ——
    窗口只有几个交易日，回走的步数很少。

    **过期的那条不能就此收手**：最新那条终点已过时，更早的长周期观点可能还活着
    （06§5.6）。所以往回走的路上只挑活着的，不因为撞见一条死的就停。
    """
    out = []
    for name, rs in rows.items():
        ps = pubs[name]
        hi = bisect.bisect_right(ps, now)
        alive = []
        for k in range(hi - 1, -1, -1):
            if ps[k] < wstart:
                break
            rec = consensus.candidate(rs[k], now, wstart)
            if rec is not None:
                alive.append(rec)
        got = consensus.latest(alive)
        if got is not None:
            out.append(got)
    return out


def _normalize(bench: dict) -> None:
    """两条基准线：多头标的买持、空头标的的**反向**买持（05§6）。"""
    for key in ("long", "short"):
        xs = bench[key]
        if not xs:
            continue
        base = xs[0]
        bench[key] = [x / base for x in xs] if key == "long" else [2 - x / base for x in xs]


# ── ⑤ 出报告 ────────────────────────────────────────────────────────────

def _write(cfg: dict, bk, spans, named: dict, missing: list[str], log) -> None:
    begin, end, days = spans
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out = paths.BACKTEST_RUNS / stamp
    out.mkdir(parents=True, exist_ok=True)

    text = render.report(bk, cfg, len(days), end, sorted(named), missing, named, bk.bench)
    (out / "回测.md").write_text(text, encoding="utf-8")
    render.chart(out / "净值.png", bk, bk.bench)
    (out / "参数.json").write_text(render.params_json(cfg), encoding="utf-8")
    for f in ("回测.md", "净值.png", "参数.json"):
        log(f"  {out / f}")


# ── 入口 ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        print(f"认不得的参数：{' '.join(argv)}")
        print("用法：python -m backtest")
        return 2
    return run()


__all__ = ["run", "main"]
