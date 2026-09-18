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

**初始化只做窗口内那一段** —— `--init` 池里每位抓一次帖（只抓窗口内那一段）、判窗口内
那些帖，再取窗口内的全部行攒成初始分布（06§4）。窗口之外的一概不碰，报告产物归 03。

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
    """推一档（或建一次窗口）。返回 0 成功、1 本档没推成、2 出错。"""
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

    wstart = conf.window_start(cfg, day, stamp)
    if not wstart:
        log(f"  回看窗口算不出来（日历覆盖不到前 {cfg['window']} 个交易日）—— 本档不推")
        return 1

    if init:
        log("[④ 抓窗口内的帖]")
        _scrape(cfg, log, wstart, window_only=True)
        log("[⑤ 解析窗口内的帖]")
        rows = _judge(cfg, wstart, log)
        log("[⑥⑦ 攒初始分布]")
    else:
        log("[④ 抓增量帖]")
        _scrape(cfg, log, wstart)
        log("[⑤ 解析增量]")
        rows = _judge(cfg, wstart, log)
        log("[⑥ 淘汰]")
        book["book"] = _drop(book["book"], stamp, wstart, log)
        log("[⑦ 并入]")
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
        feishu.alert(cfg, f"【{cfg['name']}板】{stamp} 本档卡片没发出去，本档作废，"
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
    当成休市日、用错时刻表，甚至把本档静悄悄地跳过去。
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

    **这与注记取价不是同一根** —— 02§2.1 取的是「覆盖本档时刻」的那一根（盘中取结束时刻
    严格晚于发帖时刻的第一根），与本档的收盘价那根在盘中档差一根。门问的只是「本档时刻的
    数据到没到」，按取价那根核，每个盘中档都会当场判「本档不推」。
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


# ── ④ 抓帖 ──────────────────────────────────────────────────────────────

def _scrape(cfg: dict, log, wstart: str = "", window_only: bool = False) -> None:
    """池里每一位从**各自的续抓起点**往后抓到此刻（06§5.4）。

    **某一位抓失败只影响他自己**：不中断本档，状态里那条旧条目照留；
    他的 `scrape_time` 没推进，下一档还会从原处接着抓。

    `window_only` 是初始化那一遍（06§4）—— **只抓窗口内那一段**：起点取「续抓起点」
    与「窗口起点」里晚的那个（窗口外的那一段推送用不着；窗口内的那一段，要么这次抓回来、
    要么本来就在库里）。增量那一遍不掐头，起点就是续抓起点本身。

    帖档里还没有「续抓起点」的（只有 `source_url` 的空壳，01§5）没有起点可比，退回
    窗口起点 —— **不是固定起始时间**，空壳不触发全量重抓；水位照旧空着
    （`_restore_scrape_time`），将来真要补全量还补得回来。

    起点被窗口掐了头的（`start != before`）抓完**把「抓取截止」退回原值** —— 这一轮
    不算 01§5 意义上的抓全了，水位不往前推。

    **点名抓** —— 传给 `run` 的是池子里那位的名字，链接解出来的 token 若属于别人
    （01§3.1），第 1 页上就认出来、当场收手，不去吞别人整个 feed。
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
        before = config.resume_start(doc)
        start = max(before, wstart) if window_only else (before or wstart)
        try:
            got = toutiao.run(url, start, expect=name)
            if start != before:
                _restore_scrape_time(name, before)
            if not got:
                log(f"  {name}：没抓成 —— 只影响他自己")
            # 抓完就地校验（01§9）—— 硬失败算他本档抓失败，只影响他自己
            elif verify.verify(got, start, log=log) != 0:
                log(f"  {name}：校验有硬失败 —— 只影响他自己")
        except Exception as e:
            log(f"  {name}：抓帖出岔子（{e!r}）—— 只影响他自己")
    if miss:
        log(f"  池里这 {len(miss)} 位库里没有，跳过：{'、'.join(miss)}")


def _restore_scrape_time(name: str, before: str) -> None:
    """把「抓取截止」退回抓之前的值（06§4）—— 这一轮被窗口掐了头，不算抓全了（01§4）。

    `before` 是空串 = 这位**从没抓全过**（01§5）—— 退回空串正是这个意思：水位一直空着，
    下一档还是从窗口起点抓（`_scrape`）。这一轮只抓了窗口内那一段，退回空串才留得住
    「将来补全量」这条路。
    """
    p = paths.posts_file(name)
    try:
        doc = json.loads(p.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return
    if doc.get("scrape_time") == before:
        return
    doc["scrape_time"] = before
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _posts_doc(name: str) -> dict:
    p = paths.posts_file(name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {}


# ── ⑤ 解析 ──────────────────────────────────────────────────────────────

def _judge(cfg: dict, wstart: str, log) -> dict:
    """判窗口内还没判过的帖，返回这一位**窗口内全部**的行（06§5.5、§5.6）。

    **返回「窗口内全部」，不是「这一轮新判出来的」。** 判断缓存是共用的一份
    （03§2.2）—— 报告链会判它，本栈另一个板块也会判它，谁先判谁就把这条帖
    「吃掉」：另一个板块那一轮 `judge_posts` 认得它已经判过，不产新行。只取新的
    就会把它们整批漏掉，卡上少人（06§5.6）。并进状态是幂等的，取回来多并一遍
    没有代价。

    **窗口之外的一条不判、不取** —— 与本档的分布无关，判了白花模型钱；真要判
    它们，报告链自己会判（03§2.2）。判不成的博主不进结果 —— 他那一条旧条目在
    状态里照留（06§7）。
    """
    rows = {}
    for name in cfg["pool"]:
        if not paths.posts_file(name).exists():
            continue
        try:
            posts = [p for p in report_flow.load_posts(name)
                     if consensus.in_window(p.get("pub") or "", wstart)]
            report_flow.judge_posts(name, posts, log)
        except Exception as e:
            log(f"  {name}：解析出岔子（{e!r}）—— 跳过他自己")
            continue
        rows[name] = [r for r in cache.rows_of(cache.load(name)["judged"])
                      if consensus.in_window(r.get("pub") or "", wstart)]
    return rows


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
    """每位取**最新**的那条（06§5.6 第 3 步的三级判据）—— 就是他本档的立场。

    按**池子里的顺序**返回 —— 名单顺序就是卡面上的显示顺序，不重排。
    取不到的那位本档不显示、不计数；他下次发了新帖再回来（06§5.7）。
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
