# -*- coding: utf-8 -*-
"""今日头条：翻列表 + 取详情页。

一次抓取只做三件事：**抓、并、记**。它不判断观点、不打分、不推送，
也不管下次该从哪续 —— 起始时间由调用环节算好传进来。

命令行：
    python -m blogger.scrape <帖子链接> --begin_date 2026-01-01
"""

from __future__ import annotations

import html as htmlmod
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright

from blogger.common import config, paths

# ── 常量 ────────────────────────────────────────────────────────────────

FEED_API = "https://www.toutiao.com/api/pc/list/user/feed"

DESKTOP_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")

TOKEN_RE = re.compile(r"/c/user/token/([A-Za-z0-9_=-]{30,})")

# 列表页噪声：形如「<博主名>：发布了一篇内容-今日头条」
NOISE_RE = re.compile(r"^.{1,30}：发布了一篇内容-今日头条$")

# 风控墙文案：正文含它 = 这条帖没抓到，要重试
WALL_TEXT = "当前网络环境无法查看"
# 视频帖的第三个判据：SSR 占位文案
VIDEO_TEXT = "视频加载中"
# 视频帖的第二个判据：页面里的播放器标记
PLAYER_MARK = "xgplayer"
# 视频帖的第四个判据：链接域名
CDN_HOST = "toutiaoimg"

MAX_PAGES = 400          # 翻页上限（高密度博主回溯 6 个月需 200+ 页）
TARGET_POSTS = 5000      # 累计到这么多就停
EMPTY_PAGE_LIMIT = 5     # 连续这么多页没新帖就停

DETAIL_RETRY = 3         # 详情页重试次数
DETAIL_INTERVAL = 1.2    # 详情页之间的间隔（秒），防风控
EMPTY_RUN_PAUSE = 5      # info 接口连续空响应这么多次 → 暂停
EMPTY_RUN_SLEEP = 60     # 暂停多久（秒）


def log(msg: str) -> None:
    print(msg, flush=True)


# ── 帖子编号 ────────────────────────────────────────────────────────────

def post_id_of(url: str) -> str:
    """从各种链接形态里抠出帖子编号。"""
    for pat in (r"/(?:group|article|w)/(\d+)", r"/(?:a|i)(\d+)", r"/i(\d+)"):
        m = re.search(pat, url or "")
        if m:
            return m.group(1)
    return ""


def is_microheadline(url: str) -> bool:
    """微头条：链接形如 `.../w/<id>`。它没有单独标题，列表给的文字就是全文。"""
    return bool(re.search(r"/w/\d+", url or ""))


# ── 列表接口 ────────────────────────────────────────────────────────────

def resolve_token(page, post_url: str) -> str:
    """从链接里拿用户 token；链接里没有就加载页面从页面链接里找。"""
    m = TOKEN_RE.search(post_url)
    if m:
        return m.group(1)

    log("  链接里没有 token，加载页面提取…")
    page.goto(post_url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(3)
    try:
        page.wait_for_selector('a[href*="/c/user/token/"]', timeout=10000)
    except Exception:
        pass
    time.sleep(2)

    href = page.evaluate(
        "() => { const a = document.querySelectorAll('a[href*=\"/c/user/token/\"]');"
        " return a.length ? a[0].href : ''; }")
    if not href:
        m = TOKEN_RE.search(page.content())
        href = f"https://www.toutiao.com/c/user/token/{m.group(1)}/" if m else ""
    return href.split("/c/user/token/")[1].split("/")[0].split("?")[0] if href else ""


def feed_page(page, token: str, cursor: int = 0) -> dict | None:
    """在浏览器里调列表接口 —— 签名由页面自己带，我们不伪造。"""
    js = """
        async (args) => {
            const p = new URLSearchParams({category: 'profile_all', token: args.token});
            if (args.cursor) p.append('max_behot_time', String(args.cursor));
            try {
                const r = await fetch('https://www.toutiao.com/api/pc/list/user/feed?' + p.toString(),
                                       {method: 'GET', credentials: 'include'});
                return await r.json();
            } catch (e) { return {error: e.message}; }
        }
    """
    try:
        return page.evaluate(js, {"token": token, "cursor": cursor})
    except Exception as e:
        log(f"    列表接口调用异常：{e}")
        return None


def parse_item(item: dict) -> dict | None:
    """把列表返回的一条条目整理成我们认的形态。过不了「时间关」或「噪声关」的返回 None。

    这里**不判身份、也不判置顶** —— 身份要等整轮 feed 看完、认出博主本人之后才判得了；
    置顶只需在条目上打个标，回到主流程里连同别的关一起处置。
    """
    if not isinstance(item, dict):
        return None

    # 时间关：只认 publish_time，退而取 create_time。两个都没有 → 丢掉。
    # 绝不用 behot_time —— 它是 feed 的热度游标，约等于抓取时刻。
    ts = item.get("publish_time") or item.get("create_time") or 0
    if not isinstance(ts, (int, float)) or ts <= 0:
        return None
    if ts > 1e12:            # 毫秒时间戳
        ts = ts / 1000
    ts = int(ts)

    text = item.get("content") or item.get("abstract") or ""
    if isinstance(text, dict):
        text = text.get("text") or text.get("title") or ""
    text = (text or "").strip()

    # 噪声关：列表页占位条
    if NOISE_RE.match(text):
        return None

    pid = str(item.get("id") or item.get("thread_id_str") or item.get("item_id")
              or (item.get("log_pb") or {}).get("group_id_str") or "")
    url = (item.get("share_url")
           or ((item.get("itemCell") or {}).get("shareInfo") or {}).get("shareURL", "")
           or (f"https://www.toutiao.com/w/{pid}/" if pid else ""))
    if not pid:
        pid = post_id_of(url)
    if not pid:
        return None

    user = _user_of(item)
    title = (item.get("title") or "").strip()

    return {
        "post_id": pid,
        "user": user.get("name", ""),
        "_user_id": str(user.get("id") or user.get("user_id") or ""),
        "_desc": (user.get("desc") or user.get("description") or "").strip(),
        "title": title or None,
        "_list_text": text,          # 列表给的文字，详情页取不到时兜底
        "_ts": ts,
        # 置顶帖：挂在主页顶上的公告位，**可能有好几条**，日期任意。
        # 别的条目压根没有这两个键 —— 有键且为真才算置顶。
        "_stick": bool(item.get("is_stick") or item.get("stick_style")),
        "pub": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
        "url": url,
        "digg_count": item.get("digg_count", 0),
        "comment_count": item.get("comment_count", 0),
        "read_count": item.get("read_count", 0) or item.get("display_count", 0),
    }


def _user_of(item: dict) -> dict:
    """头条 feed 的用户信息有三种形态，级联兼容。认不出就返回空 dict。"""
    u = item.get("user") or {}
    if isinstance(u, dict) and u.get("name"):
        return u
    wrap = item.get("user_info") or {}
    if isinstance(wrap, dict):
        if isinstance(wrap.get("ui"), dict) and wrap["ui"].get("name"):
            return wrap["ui"]
        if wrap.get("name"):
            return wrap
    return {}


def crawl_feed(page, token: str, since_ts: int) -> tuple[list[dict], str]:
    """翻列表，返回 (条目, 停止原因)。停止原因只有四种：

    | 取值 | 什么时候盖 | 覆盖 |
    |:---|:---|:---|
    | `since` | 碰到起始时间了 | 齐了 |
    | `no_more` | feed 真的翻到底了（没有下一页／连空页） | 再也拿不到更早的帖，也齐了 |
    | `capped` | **我们自己截断的** —— 翻到页数上限／条数收够 | 还拿得到，只是没拿 |
    | `error` | 接口重试三次仍失败 | 没拿全 |

    前两种是**正常收工**，后两种**不算收全**：都别推进「抓取截止」，
    否则下次从今天续，没抓到的中段就被永久跳过。
    """
    items: list[dict] = []
    seen: set[str] = set()
    cursor = 0
    empty_streak = 0
    stop = ""

    for page_num in range(1, MAX_PAGES + 1):
        raw = None
        for attempt in range(3):
            raw = feed_page(page, token, cursor)
            if raw and "error" not in raw:
                break
            time.sleep(3)
        if not raw or "error" in raw or raw.get("message") != "success":
            log(f"  第{page_num}页：接口异常，翻页结束")
            stop = "error"
            break

        fresh = []
        for it in (raw.get("data") or []):
            p = parse_item(it)
            if p and p["post_id"] not in seen:
                seen.add(p["post_id"])
                fresh.append(p)
        items.extend(fresh)
        empty_streak = empty_streak + 1 if not fresh else 0

        oldest = min((p["_ts"] for p in fresh), default=0)
        newest = max((p["_ts"] for p in fresh), default=0)
        log(f"  第{page_num}页：+{len(fresh)} 条 | 累计 {len(items)} 条 | "
            f"最近 {datetime.fromtimestamp(newest).strftime('%m-%d') if newest else '?'}")

        # 到起点了：本页**最新的一条**都已早于起始时间，后面只会更早。
        # 用最新的那条判、不用最旧的那条 —— feed 会在末页混入历史兜底帖，
        # 按最旧那条判会把整页正常内容误当"已到起点"而提前收工。
        if since_ts and newest and newest < since_ts:
            stop = "since"
            break
        if len(items) >= TARGET_POSTS:
            stop = "capped"
            break
        if empty_streak >= EMPTY_PAGE_LIMIT:
            stop = "no_more"
            break

        nxt = (raw.get("next") or {}).get("max_behot_time", 0)
        if not raw.get("has_more") and empty_streak >= 3:
            stop = "no_more"
            break
        if not nxt:
            stop = "no_more"
            break
        cursor = nxt
        time.sleep(1)

    # 循环跑满 MAX_PAGES 还没 break —— 是我们自己把翻页截断的，不是 feed 到底了
    return items, (stop or "capped")


# ── 详情页 ──────────────────────────────────────────────────────────────

def fetch_detail(ctx, page, post: dict) -> dict:
    """取一条帖的全文。

    返回 `{"kind": "text"|"video"|"blocked", "title": str, "content": str}`。

    **微头条不走详情页** —— 链接形如 `m.toutiao.com/w/…` 的，列表接口给的文字**就是它的全文**
    （实测与详情页正文逐字相同），再渲染一遍纯属浪费。文章类才逐级取详情页。
    """
    pid = post["post_id"]
    url = post["url"]

    # 判据四：链接域名是 CDN —— 视频帖
    if CDN_HOST in (url or ""):
        return {"kind": "video", "by": "域名", "title": post.get("title"), "content": ""}

    if is_microheadline(url):
        # 微头条：正文用列表给的文字。只花一次便宜的 info 接口请求做视频判定。
        if _info_is_video(ctx, pid):
            return {"kind": "video", "by": "播放凭证", "title": post.get("title"), "content": ""}
        body = (post.get("_list_text") or "").strip()
        if body:
            return {"kind": "text", "title": post.get("title"), "content": body}
        return {"kind": "blocked", "title": post.get("title"), "content": ""}

    # 文章类：一级 info 接口 → 二级页面渲染 → 三级段落拼接 → 兜底用列表文字
    body, is_video = _from_info_api(ctx, pid)
    if is_video:
        return {"kind": "video", "by": "播放凭证", "title": post.get("title"), "content": ""}
    if body and VIDEO_TEXT in body:
        return {"kind": "video", "by": "视频加载中", "title": post.get("title"), "content": ""}
    if body and WALL_TEXT not in body:
        return {"kind": "text", "title": post.get("title"), "content": body}

    text, html = _from_page(page, pid)
    if PLAYER_MARK in html and not text:
        return {"kind": "video", "by": "播放器标记", "title": post.get("title"), "content": ""}
    if VIDEO_TEXT in text and len(text) < 40:
        return {"kind": "video", "by": "视频加载中", "title": post.get("title"), "content": ""}
    if text and WALL_TEXT not in text:
        return {"kind": "text", "title": post.get("title"), "content": text}

    fallback = (post.get("_list_text") or "").strip()
    if fallback:
        return {"kind": "text", "title": post.get("title"), "content": fallback}
    return {"kind": "blocked", "title": post.get("title"), "content": ""}


def _info(ctx, pid: str) -> dict | None:
    """移动端 info 接口。取不到返回 None。

    **先用 `requests`，不行才退回浏览器上下文。** info 接口不校验 cookie，裸请求 0.3 秒就回；
    走 `ctx.request` 要过浏览器的网络栈，实测每次约 6 秒 —— 一条帖一次，几百条就是几十分钟。
    """
    api = f"https://m.toutiao.com/i{pid}/info/"
    try:
        r = requests.get(api, timeout=10, headers={"User-Agent": MOBILE_UA,
                                                   "Referer": f"https://m.toutiao.com/i{pid}/"})
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    try:
        return ctx.request.get(api, timeout=10000,
                               headers={"Referer": f"https://m.toutiao.com/i{pid}/"}).json()
    except Exception:
        return None


def _info_is_video(ctx, pid: str) -> bool:
    """判据一：info 接口给了**视频播放凭证**就是视频帖。"""
    data = _info(ctx, pid)
    # 取不到就当不是 —— 不能因为探针失败把正常帖判成视频
    return bool(((data or {}).get("data") or {}).get("play_auth_token_v2"))


def _from_info_api(ctx, pid: str) -> tuple[str, bool]:
    """一级：移动端 info 接口。返回 `(正文, 是不是视频帖)`。"""
    d = (_info(ctx, pid) or {}).get("data") or {}
    if d.get("play_auth_token_v2"):
        return "", True
    return _html_to_text(d.get("content") or ""), False


# 正文容器，**由紧到松** —— `article` 最松，放最后，免得在移动端抓到无关的外层容器
BODY_SELECTORS = (".article-content", ".tt-article-content", ".syl-article-base",
                  ".article-text", ".weitoutiao-content", ".r-content", "article")


def _from_page(page, pid: str) -> tuple[str, str]:
    """二级：渲染页面取正文元素；三级：把段落拼起来。返回 (正文, HTML)。"""
    html = ""
    try:
        page.goto(f"https://m.toutiao.com/i{pid}/", timeout=12000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(", ".join(BODY_SELECTORS), timeout=2000)
        except Exception:
            pass

        text = ""
        for sel in BODY_SELECTORS:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text()
                if len(text) > 20:
                    break
        if not text:
            # 换行符必须用 String.fromCharCode(10)：表达式被包进模板字符串求值时，
            # 字面 \n 会变成真实换行，把 JS 语句截断。
            text = page.eval_on_selector_all(
                "p", "els => els.map(e => e.innerText).join(String.fromCharCode(10))")
        html = page.content()
        return (text or "").strip(), html
    except Exception:
        return "", html


def _html_to_text(raw: str) -> str:
    """info 接口给的是 HTML 片段，转成纯文本。"""
    if not raw or len(raw) <= 20:
        return ""
    text = re.sub(r"<[^>]+>", "", raw)
    text = htmlmod.unescape(text)
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── 已完成记录（视频帖与置顶帖） ────────────────────────────────────────

def load_done(blogger: str) -> set[str]:
    """**判定即丢、不入库，但要记下来永不重抓** —— 否则每轮都要为它们再取一次详情页。

    视频帖与置顶帖共用这一份：两者的共同点是「已经判过了，只是不进主文件」。
    """
    for path in (paths.DONE_IDS, paths.LEGACY_DONE_IDS):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return set(data.get(blogger) or [])
        except Exception:
            continue
    return set()


def save_done(blogger: str, ids: set[str]) -> None:
    paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(paths.DONE_IDS.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data[blogger] = sorted(ids)
    tmp = paths.DONE_IDS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, paths.DONE_IDS)


# ── 合并与保存 ──────────────────────────────────────────────────────────

def load_existing(blogger: str) -> dict:
    path = paths.posts_file(blogger)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def merge_posts(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """按 post_id 并入 —— **旧帖原样保留，永不覆盖**，主文件的帖子数只增不减。"""
    by_id = {p["post_id"]: p for p in existing if p.get("post_id")}
    for p in fresh:
        by_id.setdefault(p["post_id"], p)
    return sorted(by_id.values(), key=lambda p: p.get("pub", ""), reverse=True)


def save(blogger: str, payload: dict) -> None:
    paths.POSTS_DIR.mkdir(parents=True, exist_ok=True)
    path = paths.posts_file(blogger)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ── 主流程 ──────────────────────────────────────────────────────────────

def to_timestamp(begin_date: str) -> int:
    """起始时间：`YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM`。"""
    if not begin_date:
        return 0
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(begin_date, fmt).timestamp())
        except ValueError:
            continue
    raise SystemExit(f"起始时间格式不对：{begin_date}（要 YYYY-MM-DD 或 YYYY-MM-DD HH:MM）")


def run(post_url: str, begin_date: str = "") -> str:
    """抓一次。成功返回**博主名**，失败返回空串 —— 调用环节靠这个名字知道抓的是谁。

    **微头条的列表文字就是全文** —— 它不走详情页，只花一次便宜的 info 接口请求做视频判定。
    """
    begin_date = config.resolve_begin_date(begin_date)
    begin_ts = to_timestamp(begin_date)
    log(f"起始时间：{begin_date}（抓这一段到今天）")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080},
                                  user_agent=DESKTOP_UA, locale="zh-CN",
                                  timezone_id="Asia/Shanghai")
        page = ctx.new_page()

        log("[1] 认博主")
        token = resolve_token(page, post_url)
        if not token:
            log("  找不到用户 token —— 链接可能不是博主本人的帖子。退出，不抓。")
            browser.close()
            return ""

        # 无论 token 从哪来，都先走一次页面把 cookie 建起来（列表接口依赖）
        try:
            page.goto("https://www.toutiao.com/" if "/c/user/token/" in post_url else post_url,
                      timeout=30000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(3)

        log("[2] 翻列表")
        items, stop = crawl_feed(page, token, begin_ts)
        log(f"  翻页结束：{stop}，共 {len(items)} 条")

        # 身份关：博主本人 = feed 里出现最多的那个用户。
        # 认不出是谁的一律不收 —— 不用任何旁证去补。
        counter = Counter(it["user"] for it in items if it["user"])
        blogger = counter.most_common(1)[0][0] if counter else ""
        if not blogger:
            log("  feed 里没有一条带得出身份 —— 无法认定博主本人。退出，不写文件。")
            browser.close()
            return ""

        kept = [it for it in items if it["user"] == blogger]
        dropped = len(items) - len(kept)
        log(f"  博主：{blogger}｜本人帖 {len(kept)} 条"
            + (f"｜身份不符丢掉 {dropped} 条" if dropped else ""))

        # 置顶帖关：公告位，插在列表最前面，日期可以是任何一天。判定即丢，
        # 只记「已完成」—— 它不入库，但也不能每轮都为它再取一次详情页。
        done_ids = load_done(blogger) | {it["post_id"] for it in kept if it["_stick"]}
        sticky = [it for it in kept if it["_stick"]]
        kept = [it for it in kept if not it["_stick"]]

        # 起始时间关：翻页是**整页收**的，边界页上早于起始时间的几条会一起进来，
        # 收完统一过一遍。**只筛这一轮收下来的**，文件里已有的帖一律不动。
        over = [it for it in kept if it["pub"][:10] < begin_date[:10]]
        kept = [it for it in kept if it["pub"][:10] >= begin_date[:10]]
        if sticky or over:
            log(f"  置顶帖丢掉 {len(sticky)} 条"
                + (f"｜早于起始时间丢掉 {len(over)} 条" if over else ""))

        # 增量抓取最常见的一种结局就是**这一轮一条新帖都没有**（kept 空）——
        # 那是正常的，不是错。所以取身份信息要能退回上一轮存下来的那份。
        existing = load_existing(blogger)
        old_posts = existing.get("posts") or []
        owner = kept[0] if kept else items[0]
        stored = existing.get("user_info") or {}
        user_info = {"name": blogger,
                     "user_id": owner.get("_user_id") or stored.get("user_id", ""),
                     "description": owner.get("_desc") or stored.get("description", "")}

        # 只对「主文件里没有、且不是已完成记录里的」的帖子取详情页
        known = {p.get("post_id") for p in old_posts}
        todo = [it for it in kept if it["post_id"] not in known and it["post_id"] not in done_ids]
        log(f"[3] 取详情页：{len(todo)} 条要取"
            f"（已知 {len(known)} 条，已完成记录 {len(done_ids)} 条）")

        # 详情页换成移动端上下文：info 接口与移动端渲染都要 iPhone 的 UA
        mctx = browser.new_context(viewport={"width": 390, "height": 844},
                                   user_agent=MOBILE_UA, locale="zh-CN",
                                   timezone_id="Asia/Shanghai")
        mpage = mctx.new_page()
        try:
            mpage.goto("https://www.toutiao.com/", timeout=12000, wait_until="domcontentloaded")
        except Exception:
            pass

        fresh: list[dict] = []
        new_video: set[str] = set()
        blocked = 0
        empty_run = 0
        for i, it in enumerate(todo, 1):
            result = None
            for attempt in range(DETAIL_RETRY):
                time.sleep(DETAIL_INTERVAL)
                result = fetch_detail(mctx, mpage, it)
                if result["kind"] != "blocked":
                    break
                log(f"    {it['post_id']}：风控墙，重试 {attempt + 1}/{DETAIL_RETRY}")
                time.sleep(5 * (attempt + 1))

            if result["kind"] == "video":
                new_video.add(it["post_id"])       # 判定即丢，只记「已完成」
            elif result["kind"] == "text" and result["content"]:
                fresh.append(_build_post(it, result))
            else:
                # 没抓到就不收 —— 下轮再来。绝不拿列表给的碎片充当全文。
                blocked += 1
                empty_run += 1
                if empty_run >= EMPTY_RUN_PAUSE:
                    log(f"    连续 {empty_run} 条没取到，暂停 {EMPTY_RUN_SLEEP}s 避风控")
                    time.sleep(EMPTY_RUN_SLEEP)
                    empty_run = 0
                continue
            empty_run = 0

            if i % 30 == 0:
                log(f"    {i}/{len(todo)}")
                if new_video:
                    save_done(blogger, done_ids | new_video)

        # 置顶帖也要落进已完成记录 —— 它这回没走详情页，全靠这一步记住，
        # 否则下一轮它又会被排进 todo。
        if new_video or sticky:
            save_done(blogger, done_ids | new_video)

        log(f"[4] 并入")
        posts = merge_posts(old_posts, fresh)
        log(f"  新增 {len(fresh)} 条，视频帖丢掉 {len(new_video)} 条"
            f"，置顶帖丢掉 {len(sticky)} 条，没抓到 {blocked} 条｜文件共 {len(posts)} 条")

        # 抓取截止是**抓取这一刻的挂钟时间**，不是最后一条帖的发布时间。
        # 但它同时是调用环节算下次起点的依据 —— **只有正常收工才推进它**，
        # 没抓全（截断／接口异常）时保留旧值，免得下次从今天续、把中段永久跳过。
        old_scrape_time = existing.get("scrape_time", "")
        scrape_time = (datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                       if stop in ("since", "no_more") else old_scrape_time)

        pubs = sorted(p["pub"][:10] for p in posts if p.get("pub"))
        payload = {
            "user_info": user_info,
            "source_url": post_url,
            "scrape_time": scrape_time,
            "stop_reason": stop,
            "time_range": {"earliest": pubs[0] if pubs else "", "latest": pubs[-1] if pubs else ""},
            "posts": posts,
        }
        save(blogger, payload)

        log(f"[5] 记完 → {paths.posts_file(blogger)}")
        log(f"  抓取截止 {scrape_time or '（未推进）'}｜停止原因 {stop}｜"
            f"区间 {payload['time_range']['earliest']} ~ {payload['time_range']['latest']}")
        browser.close()
    return blogger


def _build_post(item: dict, detail: dict) -> dict:
    """一条帖落库的形态 —— 只有这几个字段。

    **`title` 没有就不写这个键**（微头条没有标题）—— 不是写成 `null`（见 01§8）。
    """
    post = {
        "post_id": item["post_id"],
        "content": detail["content"],
        "pub": item["pub"],
        "url": item["url"],
        "digg_count": item["digg_count"],
        "comment_count": item["comment_count"],
        "read_count": item["read_count"],
    }
    title = (detail.get("title") or item.get("title") or "").strip()
    if title:
        post["title"] = title
    return post


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    begin_date, rest = config.split_begin_date(argv)

    url = next((a for a in rest if not a.startswith("-")), "")
    if not url:
        print(__doc__.strip())
        print("\n用法：python -m blogger.scrape <帖子链接> --begin_date 2026-01-01")
        return 2
    unknown = [a for a in rest if a != url]
    if unknown:
        print(f"认不得的参数：{' '.join(unknown)}")
        return 2
    return 0 if run(url, begin_date) else 2


if __name__ == "__main__":
    sys.exit(main())
