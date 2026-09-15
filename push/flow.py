# -*- coding: utf-8 -*-
"""06§5 的主流程 —— 每一档推送的九步。

    python -m push <板块> [--init] [--dry-run] [--force]

| 步 | 做什么 | 不在档上／出岔子时 |
|:---:|:---|:---|
| ① | 不在档上就直接退出 | 打印一行说明是哪个规则挡下的，**什么都不碰**（`--force` 是唯一的例外，见 06§5.1） |
| ② | 拿进程锁 | 上一档还在跑 → 直接退出 |
| ③ | 备料行情 | 核对到本档时刻，达不到 → **硬失败、本档不推** |
| ④ | 抓增量帖 | 某位抓失败只影响他自己 |
| ⑤ | 解析增量 | 判过的走缓存，不重判 |
| ⑥ | 淘汰 | 滑出窗口的、终点没开市的、终点已过的，逐条丢掉 |
| ⑦ | 并入 | 这一轮新产出的、符合本板块的 |
| ⑧ | 计数 | 每位取窗口内 `pub` 最大的那条，再数人头 |
| ⑨ | 渲染 → 推送 → 落档 → 推进状态 | 发不出去就不落档、不推进 |

**推送是实时增量，回测是事后重算** —— 两条路，**同一套规则，结果必须一致**（06§1、05§2）。
规则全在 `blogger.common.consensus` 那一份里，这儿不写第二套。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from blogger.common import config, consensus, market, paths
from blogger.market import fetch
from blogger.report import cache, flow as report_flow
from blogger.scrape import toutiao, verify

from push import card, conf, feishu, state, summary

BEIJING = timezone(timedelta(hours=8))    # 档按北京时间判（06§5.1）
CLOSE = "15:00"
# 30 分钟线每天的结束时刻 —— **按结束时间标注，没有 09:30 那根**（06§5.3）
BAR_ENDS = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")


def run(board: str, init: bool = False, dry_run: bool = False, force: bool = False,
        log=print) -> int:
    """推一档（或建一次窗口）。返回 0 成功、1 这一档没推成、2 出错。"""
    cfg = conf.load(board)
    if not cfg["pool"]:
        log(f"`push.pools.{board}` 里一位都没有 —— 没得推。")
        return 2

    now = datetime.now(BEIJING)
    stamp = now.strftime("%Y-%m-%d %H:%M")
    day, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")

    log(f"[{cfg['name']}板] {stamp}" + ("　（初始化）" if init else "")
        + ("　（补一档）" if force and not init else "")
        + ("　（只看不发）" if dry_run else ""))

    if not init and not force:
        # **先看一眼时刻表，再碰任何东西** —— 两张表都不含此刻时，「不在档上」
        # 已经定了，用不着日历也判得出（06§5.1「不在档上时它什么都不碰」）。
        # 补日历那一下要联网写盘，排在这里后面才不违背那句话。
        if hhmm not in cfg["trading"] and hhmm not in cfg["restday"]:
            log(f"  {day} {hhmm} 不在〈交易日 20 档〉也不在〈非交易日 5 档〉上"
                f" —— 这一下不该推。")
            return 0

    if not _calendar(log):
        return 2
    try:
        trading = market.is_trading_day(day)
    except RuntimeError as e:
        log(f"  交易日历不可用：{e}")
        return 2

    if not init and not force:
        ok, why = _on_grid(cfg, day, hhmm, trading)
        if not ok:
            log(f"  {why}")
            return 0                                   # ① 不在档上 —— 不是失败

    lock = _lock(board)
    if lock is None:
        log("  上一档还在跑 —— 直接退出（06§5.2）")
        return 0

    try:
        return _tick(cfg, stamp, day, hhmm, trading, init, dry_run, log)
    finally:
        _unlock(lock)


def _tick(cfg, stamp, day, hhmm, trading, init, dry_run, log) -> int:
    book = {"ready": True, "book": {}} if init else state.load(cfg["board"])
    if not book["ready"]:
        log(f"  状态文件不在（{state.path(cfg['board'])}）—— 窗口没建过，"
            f"先跑一次 `--init`（06§4）")
        return 1

    log("[③ 备料行情]")
    ok, why = _market(day, hhmm, trading, log)
    if not ok:
        log(f"  行情没到位：{why} —— **本档不推**（06§5.3）")
        return 1

    wstart = consensus.window_start(day, cfg["window"])
    if not wstart:
        log(f"  回看窗口算不出来（日历覆盖不到前 {cfg['window']} 个交易日）—— 本档不推")
        return 1

    log("[④ 抓增量帖]")
    _scrape(cfg, wstart, init, log)

    log("[⑤ 解析增量]")
    judged, fresh = _judge(cfg, log)

    if init:
        log("[⑥⑦ 攒初始分布]")
        # 缓存是「帖 → 这一帖判出来的行」，**摊平**才是信号清单
        rows = {name: cache.rows_of(got) for name, got in judged.items()}
    else:
        log("[⑥ 淘汰]")
        book["book"] = _drop(book["book"], stamp, wstart, log)
        log("[⑦ 并入]")
        rows = fresh
    _merge(cfg, book["book"], rows, stamp, wstart, log)

    log("[⑧ 计数]")
    picked = _pick(cfg, book["book"], stamp, wstart, log)

    log("[⑨ 渲染]")
    text = _compose(cfg, stamp, wstart, picked, log)

    if init or dry_run:
        if init and not dry_run:
            state.save(cfg["board"], book["book"])
            log(f"  初始分布已落 → {state.path(cfg['board'])}")
        if dry_run:
            log("（只看不发 —— 不碰飞书、不写状态、不留档）")
        print()
        print(text)
        return 0

    log("[⑨ 推送]")
    if not feishu.send(cfg, text, log):
        feishu.alert(cfg, f"【{cfg['name']}板】{stamp} 这一档卡片没发出去，本档作废，"
                          f"下一档带的是最新的分布。")
        return 1

    _write_briefing(cfg, stamp, day, hhmm, wstart, picked, text, log)
    state.save(cfg["board"], book["book"])
    log(f"  状态已推进 → {state.path(cfg['board'])}")
    return 0


# ── 日历 ────────────────────────────────────────────────────────────────

def _calendar(log) -> bool:
    """日历过期就先补一张（01§10.3）。**补不上 → 数不出日子，整条命令到此为止。**

    这一下必须在**①之前** —— 拿一张过期的日历判「今天是不是交易日」，会把交易日
    当成休市日、用错时刻表，甚至把这一档静悄悄地跳过去。
    """
    if not fetch.calendar_stale():
        return True
    log("  交易日历过期 —— 先补一张（01§10.3）")
    try:
        fetch.refresh(progress=log)
    except Exception as e:
        log(f"  日历补不上：{e!r}")
        return False
    return True


# ── ① 在不在档上 ────────────────────────────────────────────────────────

def _on_grid(cfg: dict, day: str, hhmm: str, trading: bool) -> tuple[bool, str]:
    """现刻对照本板块的时刻表。**日子按交易日历分**，不按星期几（06§5.1）。"""
    table = cfg["trading"] if trading else cfg["restday"]
    which = "交易日 20 档" if trading else "非交易日 5 档"
    if hhmm in table:
        return True, ""
    return False, (f"{day} 是{'交易日' if trading else '非交易日'}，本档该走〈{which}〉表，"
                   f"现刻 {hhmm} 不在表上 —— 这一下不该推。")


# ── ② 进程锁 ────────────────────────────────────────────────────────────

def _lock(board: str):
    """非阻塞地拿锁。拿不到返回 None。**锁随进程消失**，不留会卡死后续档的僵尸锁。"""
    p = paths.STATE_DIR / f"push_{board}.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_CREAT | os.O_RDWR)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _unlock(fd) -> None:
    os.close(fd)                    # 关掉 fd，锁就放了


# ── ③ 备料行情 ──────────────────────────────────────────────────────────
#
# **这一步与 06§5.3 相反，还没改** —— 06 定案推送取**现价**、不走 01 的备料链
# （30 分钟线），实时现价源与推送自己那套交易日判断都还没设计。
# 定案之前这里保持现状。

def _market(day: str, hhmm: str, trading: bool, log) -> tuple[bool, str]:
    """补到此刻并核对（06§5.3）。**已经补到就跳过，不重复抓。**"""
    want_day, want_at = _baseline(day, hhmm, trading)
    ok, why = _covered(want_day, want_at)
    if ok:
        return True, ""
    log(f"  补行情（要 {want_day} {want_at}）…")
    try:
        fetch.refresh(progress=log)
    except Exception as e:
        return False, f"行情没补成（{e!r}）"
    log(f"  行情到 {market.LAST_DATE}")
    return _covered(want_day, want_at)


def _baseline(day: str, hhmm: str, trading: bool) -> tuple[str, str]:
    """本档的核对基准 —— `(要哪天的行情, 要哪一刻的分钟线)`（06§5.3）。

    **一句话：要「结束时刻不晚于本档时刻」的最后一根。** 本档时刻落在当天第一根收出来
    之前（`09:30` 档、盘前、非交易日）就退到上一交易日末根。

    这与 02§2.1 取现值是同一条规则 —— 核的就是「拿本档时刻当发帖时刻，注记取不取得到」。
    """
    hm = _minutes(hhmm)
    if trading and hm is not None and hm >= market.SESSION_AM[0]:
        done = [t for t in BAR_ENDS if t <= hhmm]
        if done:
            return day, done[-1]
    return market.prev_td(day) or "", CLOSE


def _covered(want_day: str, want_at: str) -> tuple[bool, str]:
    """要的 30 分钟线到了没有。

    **只核 30 分钟线** —— 卡上不显示行情，而 06§5.3 要行情只有一个硬用途：
    解析新帖时的**行情注记**取的是发帖时刻的现值，那是从 30 分钟线来的（02§2.1）。
    交易日历另有一份官方日历，不靠这条线倒推。

    30 分钟线**按结束时间标注**，所以「要 `10:00` 那一刻」＝「要收到 `10:00` 那根」。
    """
    if not want_day:
        return False, "算不出要哪一天（日历覆盖不到）"
    for _, name in fetch.INDICES:
        days = market.INTRADAY.get(name) or []
        if not days or days[-1][0] < want_day:
            got = days[-1][0] if days else "空"
            return False, f"30分钟 {name} 止于 {got}，要 {want_day}"
        if days[-1][0] == want_day:
            at = days[-1][1][-1][0] if days[-1][1] else ""
            if at < want_at:
                return False, f"30分钟 {name} 的 {want_day} 只到 {at or '空'}，要 {want_at}"
    return True, ""


def _minutes(hhmm: str) -> int | None:
    try:
        return int(hhmm[:2]) * 60 + int(hhmm[3:5])
    except (ValueError, IndexError):
        return None


# ── ④ 抓增量帖 ──────────────────────────────────────────────────────────

def _scrape(cfg: dict, wstart: str, init: bool, log) -> None:
    """池里每一位从**各自的续抓起点**往后抓到此刻（06§5.4）。

    `--init` 时改从**回看窗口起点**抓（06§4）—— 窗口内的帖只读一遍、判一遍。

    **某一位抓失败只影响他自己**：不中断本档，状态里那条旧条目照留；
    他的 `scrape_time` 没推进，下一档还会从原处接着抓。
    """
    miss = []
    for name in cfg["pool"]:
        doc = _posts_doc(name)
        if not doc:
            miss.append(name)
            continue
        url = doc.get("source_url") or ""
        if not url:
            log(f"  {name}：帖子文件里没有 source_url，跳过")
            miss.append(name)
            continue
        start = wstart if init else config.resume_start(doc)
        try:
            got = toutiao.run(url, start)
            if not got:
                log(f"  {name}：没抓成 —— 只影响他自己")
            # 抓完就地校验（01§9）—— 硬失败算他这一档抓失败，只影响他自己
            elif verify.verify(got, start, log=log) != 0:
                log(f"  {name}：校验有硬失败 —— 只影响他自己")
        except Exception as e:
            log(f"  {name}：抓帖出岔子（{e!r}）—— 只影响他自己")
    if miss:
        log(f"  池里这 {len(miss)} 位库里没有，跳过：{'、'.join(miss)}")


def _posts_doc(name: str) -> dict:
    p = paths.posts_file(name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {}


# ── ⑤ 解析增量 ──────────────────────────────────────────────────────────

def _judge(cfg: dict, log) -> tuple[dict, dict]:
    """只判**这一轮新抓回来的帖**。判过的走判断缓存（06§5.5）。

    返回 `(博主 → 缓存, 博主 → 这一轮新判出来的行)`。判不成的博主不进结果 ——
    他那一条旧条目在状态里照留（06§7）。
    """
    judged, fresh = {}, {}
    for name in cfg["pool"]:
        if not paths.posts_file(name).exists():
            continue
        before = set(cache.load(name)["judged"])
        try:
            got, _, _ = report_flow.judge_posts(name, report_flow.load_posts(name), log)
        except Exception as e:
            log(f"  {name}：解析出岔子（{e!r}）—— 他那条旧条目照留")
            continue
        judged[name] = got
        rows = []
        for pid, entry in got.items():
            if pid not in before:
                rows += entry.get("signals") or []
        fresh[name] = rows
    return judged, fresh


# ── ⑥⑦ 淘汰与并入 ───────────────────────────────────────────────────────

def _drop(book: dict, now: str, wstart: str, log) -> dict:
    """淘汰三道（06§5.7）：滑出窗口的、终点没开市的、终点已过的，逐条丢掉。

    **先筛后取最新**（06§5.6）—— 删的是过期的那几条，不是整位博主。

    三道与 06§5.7 一字不差 —— 增量这条路与回测那条重算的路必须得出同一份分布（05§2）。

    前视不在这里判：`pub` 晚于本档时刻的进不来状态（`_merge` 与 `_pick` 都走
    `consensus.candidate`，那一道自带）。
    """
    out, gone = {}, 0
    for name, rows in book.items():
        kept = []
        for r in rows:
            rec = consensus.derive(r)
            if not consensus.in_window(rec["pub"], wstart):
                gone += 1
                continue
            # **终点算不出的不按后两道淘汰** —— 只等第一道把它带出去
            if consensus.nontrading(rec["ep"]):
                gone += 1
                continue
            if consensus.expired(rec["ep"], now):
                gone += 1
                continue
            kept.append(rec)
        out[name] = kept
    if gone:
        log(f"  丢掉 {gone} 条（滑出窗口、终点没开市或终点已过）")
    return out


def _merge(cfg: dict, book: dict, rows: dict, now: str, wstart: str, log) -> None:
    """把符合本板块的逐条并进状态。`idx` 必须是上证、跨度必须落在本板块（06§5.6）。

    **并入的也是「当下还成立」的那几条** —— 滑出窗口的、终点已过的一律不并。
    同一条（同帖、同周期、同方向）已经在状态里就不重复并 —— 并入是幂等的。
    """
    added = 0
    for name, sigs in rows.items():
        have = {(r["post_id"], r["spec"], r["d"]) for r in book.get(name, [])}
        for sig in sigs or []:
            if sig.get("idx") != cfg["index"]:
                continue
            rec = consensus.derive(sig)
            if not conf.span_ok(cfg["board"], rec["span"], cfg["bucket_span"]):
                continue
            if consensus.candidate(rec, now, wstart) is None:
                continue
            key = (rec["post_id"], rec["spec"], rec["d"])
            if key in have:
                continue
            have.add(key)
            book.setdefault(name, []).append(rec)
            added += 1
    log(f"  并入 {added} 条")


# ── ⑧ 计数 ──────────────────────────────────────────────────────────────

def _pick(cfg: dict, book: dict, now: str, wstart: str, log) -> list[dict]:
    """每位取**最新**的那条（06§5.6 第 3 步的三级判据）—— 就是他这一档的立场。

    按**池子里的顺序**返回 —— 名单顺序就是卡面上的显示顺序，不重排。
    取不到的那位这一档不显示、不计数；他下次发了新帖再回来（06§5.7）。
    """
    picked = []
    for name in cfg["pool"]:
        alive = [r for r in book.get(name, [])
                 if consensus.candidate(r, now, wstart) is not None]
        got = consensus.latest(alive)
        if got is not None:
            picked.append({**got, "name": name})
    e, n_long = consensus.spread(picked)
    log(f"  上卡 {e} 位｜{n_long} 多 / {e - n_long} 空")
    return picked


# ── ⑨ 渲染 ──────────────────────────────────────────────────────────────

def _compose(cfg: dict, now: str, wstart: str, picked: list[dict], log) -> str:
    """卡片。**一个人都没上卡 → 最小卡，不调模型**（06§6.3）。"""
    n_long = sum(1 for r in picked if r["d"] > 0)
    counts = (n_long, len(picked) - n_long)
    if not picked:
        return card.minimal(cfg, now, wstart)
    return card.render(cfg, now, wstart, picked, counts,
                       summary.write(cfg, picked, counts, log))


def _write_briefing(cfg: dict, stamp: str, day: str, hhmm: str, wstart: str,
                    picked: list[dict], text: str, log) -> None:
    """落档 `data/briefings/<日期>_<时刻>_<板块>.json`。**同一档重跑就覆盖同一份。**"""
    paths.BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    n_long = sum(1 for r in picked if r["d"] > 0)
    doc = {
        "board": cfg["board"],
        "at": stamp,
        "wstart": wstart,
        "counts": {"long": n_long, "short": len(picked) - n_long},
        "picked": [{k: r.get(k) for k in ("name", "post_id", "pub", "d", "spec", "idx",
                                          "ep", "span", "quote")} for r in picked],
        "card": text,
    }
    p = paths.BRIEFINGS_DIR / f"{day}_{hhmm.replace(':', '')}_{cfg['board']}.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  留档 → {p}")


# ── 入口 ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    init, dry = "--init" in args, "--dry-run" in args
    force = "--force" in args
    flags = ("--init", "--dry-run", "--force")
    rest = [a for a in args if a not in flags]
    if len(rest) != 1 or rest[0] not in conf.BOARDS:
        print(f"用法：python -m push {{{'|'.join(conf.BOARDS)}}} "
              f"[--init] [--dry-run] [--force]")
        return 2
    if force and init:
        print("`--force` 与 `--init` 一起带没有意义 —— 初始化本来就不看时刻表（06§4）。")
        return 2
    return run(rest[0], init=init, dry_run=dry, force=force)


__all__ = ["run", "main"]
