# -*- coding: utf-8 -*-
"""03 的主流程 —— 定位 → 备料 → 解析 → 保存 → 事后验证 → 单列 → 统计（见 03§1）。

**只有「解析」这一步要用模型。** 其余全是纯计算，什么都不落盘。

定位：**给博主名 = 我指的是已有的这位；给链接 = 你自己去找，找不到就新建。**
所以新博主只能靠链接引进 —— 光给名字，系统不知道该去哪找（03§0）。
"""

from __future__ import annotations

import json

from blogger.common import config, market, paths
from blogger.market import fetch
from blogger.parse import extract
from blogger.report import cache, render, stats, store, verify
from blogger.scrape import toutiao
from blogger.scrape import verify as scrape_verify


def looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def report_one(locator: str, begin_date: str = "",
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
        market_refresh(log)
    blogger = _scrape(blogger, url, start, log)
    if not blogger:
        return 2

    log("[② 解析]")
    posts = load_posts(blogger)
    judged, tally, no_note = judge_posts(blogger, posts, log)

    log("[③ 保存]")
    ids = {p["post_id"] for p in posts}
    rows = [r for r in cache.rows_of(judged) if r["post_id"] in ids]
    store.save(blogger, rows)
    log(f"  {len(rows)} 条 → {paths.signals_file(blogger)}")

    log("[④ 事后验证]")
    scored_rows = [verify.evaluate(r) for r in rows]

    log("[⑤ 单列]")
    unscored = [r for r in scored_rows if r["note"] != verify.SCORED]
    t = stats.tally(scored_rows)
    log(f"  信号 {t['signals']} 条（计分 {t['scored']} / 不计分 {t['unscored']}）"
        f"｜不是信号 {t['total'] - t['signals']} 条（行照留，不删）")

    log("[⑥ 统计]")
    _write_report(blogger, scored_rows, posts, log)

    log("[⑦ 清单]")
    _report_dropped(tally, no_note, unscored, log)
    return 0


def roster() -> list[str]:
    """名单 —— **所有抓过的博主**：`data/posts/` 下的每一位（03§6）。

    03／04／01 的对齐总览用的是同一份名单，只算一处 —— 实现落在 `paths.roster`。
    """
    return paths.roster()


def report_all(begin_date: str = "", refresh: bool = True,
               log=print, on_done=None) -> int:
    """全库 —— 每位各更新一遍。`on_done(博主名, 成没成)` 每一位跑完调一次。"""
    names = roster()
    if not names:
        log("库里一位博主都没有。先给一条帖子链接把博主引进来。")
        return 2

    log(f"全库 {len(names)} 位")
    if refresh:
        market_refresh(log)

    failed: list[str] = []
    for i, name in enumerate(names, 1):
        log(f"\n{'=' * 60}\n[{i}/{len(names)}] {name}")
        try:
            ok = report_one(name, begin_date, refresh=False, log=log) == 0
        except Exception as e:           # **一位跑不成不牵连其余的** —— 单列出来就行（04§2）
            log(f"  这一位没跑成：{e!r}")
            ok = False
        if not ok:
            failed.append(name)
        if on_done:
            on_done(name, ok)
    log(f"\n全库跑完：{len(names) - len(failed)} 位成功，{len(failed)} 位出错")
    if failed:
        log(f"  没跑成的名单：{'、'.join(failed)}")      # 末尾把名单报出来（03§6）
    return 1 if failed else 0


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
    """续抓起点（01§5）。算法落在 `config.resume_start`，补齐那边调的是同一个。"""
    return config.resume_start(doc)


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
    # 抓完就地校验（01§9）—— 硬失败算这位这一轮没跑成，只影响他自己（03§6）。
    # 传**与抓取同一个**起点，否则覆盖检查判不了。
    # 注意别跟 `blogger.report.verify`（03 的事后验证）混了 —— 这是抓取那一侧的校验。
    if scrape_verify.verify(got, start, log=log) != 0:
        log("  校验有硬失败 —— 这位这次到此为止。")
        return ""
    return got


def market_refresh(log) -> None:
    """**备料行情** —— 30 分钟线（算参考价、终点价与行情水位）。见 01§10。

    已经补到**该到的那天**就不重复抓。**这里不核对** —— 核对是 `blogger.market` 的事。

    03／04 在跑之前调它；05 在 `backtest.update` 关掉时**只调它、不动库**（05§8）。
    """
    if not fetch.needs_refresh():
        log(f"  行情已到 {market.LAST_DATE}，不必补")
        return
    log(f"  补行情（现在到 {market.LAST_DATE}）…")
    got = fetch.refresh(progress=log)
    log(f"  行情到 {got['行情到']}")


# ── ② 解析 ──────────────────────────────────────────────────────────────

def judge_posts(blogger: str, posts: list[dict], log
                ) -> tuple[dict, dict, list[dict]]:
    """只判**还没判过的帖**；判过的直接从缓存取行（03§2.2）。

    排序：从新到旧。返回 `(缓存, 这一轮的解析统计, 缺行情注记没判的帖)`。

    03 每跑一次调它一遍；06 每档对**这一轮新抓回来的帖**调它一遍（06§5.5）——
    批大小、字数预算、单帖上限、排序方向都是同一套参数，两边读帖的方式必须一致。
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
            # **一批一落。** 全库一轮要几十分钟，落在最后的话，中途一次调用失败或一次
            # Ctrl-C 就把这一位已经判成的批全带走。落盘的是「判过哪些帖」，失败的那批
            # 没进 `judged`，下一轮照样重判。
            cache.save(blogger, judged)

        _, tally = extract.extract(ready,
                                   on_judged=remember,
                                   progress=lambda i, n, k: log(f"    批 {i}/{n} → {k} 条"))
    return judged, tally, no_note


# ── ⑦ 清单 ──────────────────────────────────────────────────────────────

def _report_dropped(tally: dict, no_note: list[dict], unscored: list[dict], log) -> None:
    """把**没能进到统计里**的行逐条报出来（03§3.8）。

    **只打印在命令行，不写进报告** —— 报告是给人看结论的，不是流水账。
    但这一份必须报：不报，读者只会看到「信号比上次少了」，却不知道少在哪一步。
    """
    lost = tally.get("丢弃清单") or []
    failed = tally.get("失败帖") or []

    if not (lost or failed or unscored or no_note):
        log("  没有没能进统计的")
        return

    if lost:
        log(f"  解析阶段：{len(lost)} 条没能成为观点信号")
        for s in lost:
            log(f"    {s}")
    if failed:
        log(f"  解析阶段：{len(failed)} 条帖整批没调通"
            "（这一轮没判出来，下一轮会重判）")
        for s in failed:
            log(f"    {s}")
    for r in unscored:
        log(f"  没算分：{r['pub']} {r['post_id']}｜{r['note']}"
            f"（{r['idx']} {r['spec']} {r['d']:+d}｜{r['quote'][:20]}…）")
    if no_note:
        log(f"  行情注记取不到：{len(no_note)} 条帖这一轮压根没判")
        for p in no_note:
            log(f"    {p['pub']} {p['post_id']}")


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


def load_posts(blogger: str) -> list[dict]:
    return _load_doc(blogger).get("posts") or []


__all__ = ["report_one", "report_all", "roster", "looks_like_url", "load_posts",
           "judge_posts", "market_refresh"]
