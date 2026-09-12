# -*- coding: utf-8 -*-
"""03 的主流程 —— 定位 → 备料 → 解析 → 保存 → 事后验证 → 清库 → 统计（见 03§1）。

**只有「解析」这一步要用模型。** 其余全是纯计算，什么都不落盘。

定位：**给博主名 = 我指的是已有的这位；给链接 = 你自己去找，找不到就新建。**
所以新博主只能靠链接引进 —— 光给名字，系统不知道该去哪找（03§0）。
"""

from __future__ import annotations

import json

from blogger.common import config, market, market_fetch, paths
from blogger.parse import extract
from blogger.report import cache, render, store, verify
from blogger.scrape import toutiao

BATCH_SIZE = 15          # 03§2.2：一次喂 15 帖
RUNS = 1                 # 03§2.2：一条帖跑 1 遍


def looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def report_one(locator: str, begin_date: str = "", runs: int = RUNS,
               refresh: bool = True, log=print) -> int:
    """一位博主 —— 入库或更新。返回 0 成功、2 出错。

    `begin_date` 只在**新博主**身上生效（全量抓的起点）；旧博主走**续抓起点**（01§5），
    「从哪续」由这里的 `_locate` 算好传进抓取。

    抓回来的帖**必然在区间内** —— 越界的那些在 01 就被滤掉了（01§4），这里不再筛一道。
    """
    place = _locate(locator, begin_date, log)
    if place is None:
        return 2
    blogger, url, start = place

    log(f"[① 备料] {'新博主入库' if not blogger else blogger}")
    if refresh:
        _market(log)
    blogger = _scrape(blogger, url, start, log)
    if not blogger:
        return 2

    log("[② 解析]")
    posts = _load_posts(blogger)
    judged, tally, no_note = _parse(blogger, posts, runs, log)

    log("[③ 保存]")
    ids = {p["post_id"] for p in posts}
    rows = [r for r in cache.rows_of(judged) if r["post_id"] in ids]
    store.save(blogger, rows)
    log(f"  {len(rows)} 条 → {paths.signals_file(blogger)}")

    log("[④ 事后验证]")
    scored_rows = [verify.evaluate(r) for r in rows]

    log("[⑤ 清库]")
    kept, dropped = _prune(judged, scored_rows)
    if dropped:
        cache.save(blogger, judged)
        store.save(blogger, kept)
        log(f"  删掉 {len(dropped)} 条「无效-过时」")
    else:
        log("  没有要删的")

    log("[⑥ 统计]")
    _write_report(blogger, kept, posts, log)

    log("[⑦ 过滤清单]")
    _report_dropped(tally, no_note, dropped, log)
    return 0


def report_all(begin_date: str = "", runs: int = RUNS, refresh: bool = True,
               log=print) -> int:
    """全库 —— **所有抓过的博主**，各更新一遍。

    名单取 `data/posts/` 下的每一位，**不是**已有信号文件的博主 ——
    否则新博主一旦还没解析过，就永远进不了名单（03§6）。
    """
    names = sorted(p.stem for p in paths.POSTS_DIR.glob("*.json")) \
        if paths.POSTS_DIR.exists() else []
    if not names:
        log("库里一位博主都没有。先给一条帖子链接把博主引进来。")
        return 2

    log(f"全库 {len(names)} 位")
    if refresh:
        _market(log)

    bad = 0
    for i, name in enumerate(names, 1):
        log(f"\n{'=' * 60}\n[{i}/{len(names)}] {name}")
        if report_one(name, begin_date, runs, refresh=False, log=log) != 0:
            bad += 1
    log(f"\n全库跑完：{len(names) - bad} 位成功，{bad} 位出错")
    return 1 if bad else 0


# ── 定位 ────────────────────────────────────────────────────────────────

def _locate(locator: str, begin_date: str, log) -> tuple[str, str, str] | None:
    """定出 `(博主名, 用哪条链接抓, 起始时间)`。定不出来返回 None。

    | 给的是 | 库里有 | 结果 |
    |:---|:---|:---|
    | **博主名** | 有 | 更新 —— 用库里存的 `source_url` 抓，从他上次抓到的零点点往后补 |
    | **博主名** | 没有 | **报错** —— 光给名字，系统不知道该去哪找 |
    | **帖子链接** | 有 | 更新 —— 起点同上 |
    | **帖子链接** | 没有 | **新博主入库** —— 从 `begin_date` 全量抓 |

    **链接那位是谁，靠帖子编号反查** —— 不认得的编号就是新博主。
    """
    fallback = config.resolve_begin_date(begin_date)
    if not looks_like_url(locator):
        doc = _load_doc(locator)
        if not doc:
            log(f"库里没有这位博主：{locator}")
            log("　新博主只能靠**帖子链接**引进 —— 光给名字，系统不知道该去哪找。")
            return None
        url = doc.get("source_url") or ""
        if not url:
            log(f"  {paths.posts_file(locator)} 里没有 source_url，没法定位博主")
            return None
        return locator, url, _start_of(doc) or fallback

    blogger = _blogger_of_post(toutiao.post_id_of(locator))
    if not blogger:
        return "", locator, fallback                         # 新博主
    return blogger, locator, _start_of(_load_doc(blogger)) or fallback


def _start_of(doc: dict) -> str:
    """续抓起点 = **上次抓取截止所在那一日的零点**（01§2／01§5）。"""
    stamp = doc.get("scrape_time") or ""
    return f"{stamp[:10]} 00:00" if stamp else ""


def _blogger_of_post(pid: str) -> str:
    """这条帖在谁名下 —— 扫一遍库里的帖子编号。认不得就是新博主。"""
    if not pid or not paths.POSTS_DIR.exists():
        return ""
    for f in sorted(paths.POSTS_DIR.glob("*.json")):
        try:
            posts = (json.loads(f.read_text(encoding="utf-8")) or {}).get("posts") or []
        except (ValueError, OSError):
            continue
        if any(p.get("post_id") == pid for p in posts):
            return f.stem
    return ""


# ── ① 备料 ──────────────────────────────────────────────────────────────

def _scrape(blogger: str, url: str, start: str, log) -> str:
    """抓帖（01）。返回博主名 —— **新博主是靠这一次抓取才知道自己叫什么的。**

    `start` 就是起始时间：新博主是固定日期，旧博主是续抓起点（01§5）——
    两者的区别由上面的 `_locate` 判，抓取自己不知道有这回事。

    抓不成就不往下走：宁可报错，也不拿旧数据出一份看着正常的报告。
    """
    got = toutiao.run(url, start)
    if not got:
        log("  抓取没成 —— 这次到此为止。")
        return ""
    if blogger and got != blogger:
        log(f"  **注意**：这条链接认出来的是「{got}」，不是「{blogger}」—— 按 {got} 继续。")
    return got


def _market(log) -> None:
    """补行情 —— 日线（算交易日历）＋ 30 分钟线（算参考价与终点价）。

    已经补到今天就不重复抓。
    """
    if not market_fetch.needs_refresh():
        log(f"  行情已到 {market.LAST_DATE}，不必补")
        return
    log(f"  补行情（现在到 {market.LAST_DATE}）…")
    got = market_fetch.refresh(progress=log)
    log(f"  行情到 {got['日历到']}")


# ── ② 解析 ──────────────────────────────────────────────────────────────

def _parse(blogger: str, posts: list[dict], runs: int, log
           ) -> tuple[dict, dict, list[dict]]:
    """只判**还没判过的帖**；判过的直接从缓存取行（03§2.2）。

    排序：从新到旧。返回 `(缓存, 这一轮的解析统计, 缺行情注记没判的帖)`。
    """
    cached = cache.load(blogger)
    judged = cached["judged"]
    fresh = cache.pending(sorted(posts, key=lambda p: p["pub"], reverse=True), judged)
    ready = extract.ready_posts(fresh)
    ready_ids = {p["post_id"] for p in ready}
    no_note = [p for p in fresh if p["post_id"] not in ready_ids]

    log(f"  帖 {len(posts)} 条｜判过 {len(judged)} 条｜这次判 {len(ready)} 条"
        + (f"（{len(no_note)} 条缺行情注记，等行情补上再判）" if no_note else ""))

    tally: dict = {}
    if ready:
        def remember(batch, signals, ok):
            if not ok:
                return
            by_post: dict[str, list[dict]] = {}
            for s in signals:
                by_post.setdefault(s["post_id"], []).append(s)
            for p in batch:
                judged[p["post_id"]] = {"pub": p["pub"],
                                        "signals": by_post.get(p["post_id"], [])}

        _, tally = extract.extract(ready, runs=runs, batch_size=BATCH_SIZE,
                                   on_judged=remember,
                                   progress=lambda i, n, k: log(f"    批 {i}/{n} → {k} 条"))
        cache.save(blogger, judged)
    return judged, tally, no_note


# ── ⑦ 过滤清单 ──────────────────────────────────────────────────────────

def _report_dropped(tally: dict, no_note: list[dict], stale: list[dict], log) -> None:
    """把**没能进到报告里**的观点信号逐条报出来（03§3.8）。

    **只打印在命令行，不写进报告** —— 报告是给人看结论的，不是流水账。
    但这一份必须报：不报，读者只会看到「信号比上次少了」，却不知道少在哪一步。
    """
    lost = tally.get("丢弃清单") or []

    if not (lost or stale or no_note):
        log("  没有过滤掉的")
        return

    if lost:
        log(f"  解析阶段：{len(lost)} 条没能成为观点信号")
        for s in lost:
            log(f"    {s}")
    for r in stale:
        log(f"  清库：{r['pub']} {r['post_id']}｜无效-过时"
            f"（{r['idx']} {r['spec']} {r['d']:+d}｜{r['quote'][:20]}…）")
    if no_note:
        log(f"  行情注记取不到：{len(no_note)} 条帖这一轮压根没判")
        for p in no_note:
            log(f"    {p['pub']} {p['post_id']}")


# ── ⑤ 清库 ──────────────────────────────────────────────────────────────

def _prune(judged: dict, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """把 `note` 是「无效-过时」的**从库里删掉**（03§3.7）。

    删的是**行**，文件还是 6 键 —— **不写状态、不加字段**。

    **缓存里也要删，而且是就地删调用方手上这一份** —— 信号文件是由缓存派生的，
    只删文件、或删了另一份缓存，下次一跑这条又会长回来。
    """
    stale = [r for r in rows if verify.is_stale(r)]
    if not stale:
        return rows, []
    keys = {(r["post_id"], r["idx"], r["spec"], r["d"]) for r in stale}
    for pid, entry in judged.items():
        entry["signals"] = [s for s in (entry.get("signals") or [])
                            if (pid, s["idx"], s["spec"], s["d"]) not in keys]
    return [r for r in rows if not verify.is_stale(r)], stale


# ── ⑥ 统计 ──────────────────────────────────────────────────────────────

def _write_report(blogger: str, rows: list[dict], posts: list[dict], log) -> None:
    text = render.report(blogger, rows, posts)
    p = paths.report_file(blogger)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    log(f"  {p}")


# ── 读帖子 ──────────────────────────────────────────────────────────────

def _load_doc(blogger: str) -> dict:
    p = paths.posts_file(blogger)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {}


def _load_posts(blogger: str) -> list[dict]:
    return _load_doc(blogger).get("posts") or []


__all__ = ["report_one", "report_all", "looks_like_url", "_prune"]
