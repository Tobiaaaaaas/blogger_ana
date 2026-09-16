# -*- coding: utf-8 -*-
"""02 llm解析 —— **解析一条帖**这一个动作。

输入一批帖，输出零到多条结构化数据。**批的大小、排序、存哪，都不在这里** ——
那是调用方（03 报告 / 06 推送）的事，本文只管「给我这些帖，我还你结构化数据」。

外部事实只有一样：**行情注记**（发帖时刻七个主指数的现值）。**取不到注记的帖不解析** ——
点位类判断会退回「模型凭旧记忆猜」，而旧记忆里的点位和发帖时的点位常常差几百点。

代码在这一环只做两件事：喂帖时**摆一份字面命中清单**（§10.1），收帖后**过一道强校验与
条件句守门**（§10.2）。**摆与守都不下判** —— 划表述的边界、落 `spec` 与 `idx`、抄引文，
全是模型自己下笔。
"""

from __future__ import annotations

import json
import time
from datetime import date

from blogger.common import ds, market, params
from blogger.parse import hints, prompts, schema

BATCH_SIZE = params.get("parse.batch_size", 15)     # 一批最多几条帖
BATCH_CHAR_BUDGET = params.get("parse.batch_char_budget", 30000)
PER_POST_LIMIT = params.get("parse.per_post_limit", 4000)   # 单帖正文截断长度（保头 60% 尾 40%）
BATCH_PAUSE = params.get("parse.batch_pause", 0.5)  # 批与批之间的间隔（秒）
RUNS = params.get("parse.runs", 2)                  # 同一条帖跑几遍（§10.3）

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def weekday_of(pub: str) -> str:
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


# ── 渲染 ────────────────────────────────────────────────────────────────

def render_post(i: int, post: dict, note: str) -> str:
    """一条帖喂给模型的样子：编号、发帖时间**加周几**、标题、正文、行情注记、字面命中。

    末一行是代码摆的清单（§10.1）—— **只摆不判**，认得几个词就列几个，一个字都不删不加。
    """
    head = f"[{i}] 发帖 {post['pub']} {weekday_of(post['pub'])}"
    title = (post.get("title") or "").strip()
    if title:
        head += f"｜{title}"
    lines = [head, truncate(post.get("content") or ""), note]
    listing = hints.hints_of(post)
    if listing:
        lines.append(listing)
    return "\n".join(lines)


def render_batch(posts: list[dict]) -> tuple[str, list[dict]]:
    """渲染一批帖。返回 `(给模型的文本, 真正进了这批的帖)`。

    **注记取不到的帖直接不进批** —— 不解析它，也不给它编一个位置。
    """
    blocks, kept = [], []
    for post in posts:
        note = market.pub_note(post["pub"])
        if note is None:
            continue
        blocks.append(render_post(len(kept), post, note))
        kept.append(post)
    return "\n\n".join(blocks), kept


def ready_posts(posts: list[dict]) -> list[dict]:
    """挑出**注记取得到**的帖。取不到的这批不解析，等行情补上再说。

    调用方拿它先筛一道，才知道「这次到底判了哪些帖」。
    """
    return [p for p in posts if market.pub_note(p["pub"]) is not None]


def build_batches(posts: list[dict], batch_size: int = BATCH_SIZE) -> list[list[dict]]:
    """按条数与字符预算双重切批。顺序照传入的顺序，**不重排**。"""
    batches, cur, budget = [], [], 0
    for post in posts:
        size = len(truncate(post.get("content") or "")) + len(post.get("title") or "") + 90
        if cur and (len(cur) >= batch_size or budget + size > BATCH_CHAR_BUDGET):
            batches.append(cur)
            cur, budget = [], 0
        cur.append(post)
        budget += size
    if cur:
        batches.append(cur)
    return batches


# ── 跑一遍 ──────────────────────────────────────────────────────────────

def cond_drop(post: dict, sig: dict) -> str | None:
    """条件句守门（§10.2）—— **引文所在的那一整句**是条件句、这一处却产了方向，就丢掉。

    返回丢掉的理由，不该丢返回 `None`。**代码面唯一一处会删行的判断** —— 判死在整句上，
    不在引文那半截上（「若／如果」常落在引文之外）；拿不准的一律放行。
    """
    sent = hints.cond_reason(post, sig["quote"])
    return f"条件句（{sent[:40]}…）这一处却产了方向" if sent else None


def parse_batch(posts: list[dict], label: str = "") -> tuple[list[dict], dict]:
    """一批帖跑**一遍**模型，就地做强校验。返回 `(本批的信号, 计数)`。

    产出的每一处**多带一个 `post_n`**（批内序号），给定夺那一步认帖用。调用方要么自己
    带下去，要么用 `untag()` 去掉 —— **最终出参恒为 6 键**。
    """
    if not posts:
        return [], {}

    user_text, kept = render_batch(posts)
    if not kept:
        return [], {"跳过": len(posts), "原因": "行情注记取不到"}
    if not user_text.strip():
        return [], {"跳过": len(kept)}

    # `need="signals"`：回来的不是那个带 `signals` 键的对象，算这次调用没成、走重试（§10.4）
    try:
        result = ds.call_json(prompts.ANNOTATION_SYSTEM_PROMPT, user_text,
                              label or "解析", need="signals")
    except ds.ModelError:
        # 重试耗尽 —— **这一批记名跳过，不牵连其余的批**（§10.4）。回空产出，调用方据此
        # 把这一批的帖记成「没判到」，下一轮重判；**绝不记成「判过、一条不产」**。
        return [], {"失败": len(kept)}

    signals, dropped, dropped_n, bad_n = [], [], [], 0
    for raw in (result.get("signals") or []):
        n = raw.get("post_n")
        if not isinstance(n, int) or not (0 <= n < len(kept)):
            bad_n += 1
            continue
        sig, why = schema.to_signal(raw, kept[n])
        if sig is not None:
            why = cond_drop(kept[n], sig)   # 强校验过了，再过一道条件句守门（§10.2）
        if sig is None or why:
            # 带上出处 —— 这条被丢了，报告里再也看不到它，只有这里能说明白是哪儿丢的
            dropped.append(f"{kept[n]['pub']} {kept[n]['post_id']}｜{why}")
            dropped_n.append(n)             # 与 dropped 逐条对齐，定夺那一步要用
        else:
            # 临时带上批内序号：定夺那一步要把产出回喂模型，而模型只能靠这个序号认帖 ——
            # 少了它，模型会把 A 帖的引文安到 B 帖头上。**出口处一律去掉**，出参恒为 6 键。
            signals.append({**sig, "post_n": n})

    signals, dups = schema.dedup_with_dropped(signals, kept)

    return signals, {
        "帖": len(kept), "产": len(signals), "去重": len(dups),
        "丢弃": len(dropped), "编号错": bad_n,
        "丢弃清单": dropped, "丢弃帖号": dropped_n,
        "去重清单": [f"{s['pub']} {s['post_id']}｜同帖同对象同周期的重复表述"
                     f"（{s['idx']} {s['spec']} {s['d']:+d}｜{s['quote'][:20]}…）" for s in dups],
    }


# ── 定夺 ────────────────────────────────────────────────────────────────

def untag(signals: list[dict]) -> list[dict]:
    """去掉临时带上的 `post_n` —— **出参恒为 6 键**。"""
    return [{k: v for k, v in s.items() if k != "post_n"} for s in signals]


def triple_of(signal: dict) -> tuple:
    """一条信号的三元组 —— 比对各遍产出时只看这三样，**不看 `quote`**（§10.3）。"""
    return (signal["d"], signal["spec"], signal["idx"])


def split_agreed(kept: list[dict], outs: list[list[dict]]) -> tuple[list[dict], list[int]]:
    """按帖比各遍产出的三元组。返回 `(各遍一致的那些行, 对不上的帖号)`。

    一致的帖**不必再花一次调用**：三元组既然一样，并起来去过重留下的就是**引文更长**的
    那一份（§10.2）。对不上的帖**整条**交给模型，所以这里只把帖号挑出来 —— 送哪几处、
    送什么，是调用方的事。
    """
    agreed, disputed = [], []
    for n in range(len(kept)):
        faces = {tuple(sorted(triple_of(s) for s in o if s["post_n"] == n)) for o in outs}
        if len(faces) == 1:
            agreed += [s for o in outs for s in o if s["post_n"] == n]
        else:
            disputed.append(n)
    return schema.dedup(agreed, kept), disputed


def reconcile(posts: list[dict], runs: list[list[dict]], label: str = ""
              ) -> tuple[list[dict], dict]:
    """把 N 份产出连同原文交给模型，由它**逐遍审、剔掉错的、把对的并起来**。返回 `(结构化数据, 统计)`。

    **`posts` 只是需要定夺的那些帖**（§10.3：各遍三元组对不上的），`runs` 与它一一对应、
    每一处的 `post_n` 已按 `posts` 的下标重编过。N = 1 或 `self_check` 时传整批进来，意义
    不变 —— 那一路是单纯的自查：让模型独立看一遍「引文里的方向词在原帖里搜不搜得到」。

    `runs` 里的每一处产出**必须带着 `post_n`**（批内序号）—— 模型就是照它说「这一处出自
    哪条帖」的。喂进去没有、却要它写出来，它只能一律写 0，把 A 帖的引文安到 B 帖头上，
    到强校验那一步全被当成「引文搜不到」丢掉。

    统计要在这儿数、不在第一遍解析那儿数：**这一步的产出才是最终进文件的那一份**，
    第一遍的那些只是它的输入。
    """
    if not posts:
        return [], {}

    user_text, kept = render_batch(posts)
    if not kept:
        return [], {}
    body = json.dumps({"runs": runs}, ensure_ascii=False, indent=1)
    try:
        result = ds.call_json(prompts.RECONCILE_SYSTEM_PROMPT,
                              f"{user_text}\n\n## 各遍产出\n{body}", label or "定夺",
                              need="signals")
    except ds.ModelError:
        # 定夺没跑成，退回各遍的并集 —— 这一退没有「被丢掉」可言（§10.4）
        return untag(schema.dedup([s for run in runs for s in run], posts)), {}

    signals, lost, bad_n = [], [], 0
    for raw in (result.get("signals") or []):
        n = raw.get("post_n")
        if not isinstance(n, int) or not (0 <= n < len(kept)):
            bad_n += 1
            continue
        sig, why = schema.to_signal(raw, kept[n])
        if sig is not None:
            why = cond_drop(kept[n], sig)   # 定夺的产出走同一道守门（§10.2）
        if sig is None or why:
            lost.append(f"{kept[n]['pub']} {kept[n]['post_id']}｜{why}")
        else:
            signals.append(sig)

    signals, dups = schema.dedup_with_dropped(signals, kept)
    n_lost = len(lost)                       # 先数，再往同一个清单里续去重与编号错的交代
    if bad_n:
        lost.append(f"（另有 {bad_n} 处编号指错：指向了不存在的帖号，整条丢掉）")
    lost += [f"{s['pub']} {s['post_id']}｜同帖同对象同周期的重复表述"
             f"（{s['idx']} {s['spec']} {s['d']:+d}｜{s['quote'][:20]}…）" for s in dups]
    # **已知缺口**：`编号错` 这个计数没人收 —— `extract` 只读 `丢弃清单` 与 `丢弃`，指错
    # 帖号只在清单里留一行交代，计数仍是 0。2026-09-16 定的先不修。
    return signals, {"产": len(signals), "丢弃": n_lost, "去重": len(dups),
                     "编号错": bad_n, "丢弃清单": lost}


# ── 入口 ────────────────────────────────────────────────────────────────

def extract(posts: list[dict], self_check: bool = True,
            batch_size: int = BATCH_SIZE, progress=None, on_judged=None
            ) -> tuple[list[dict], dict]:
    """解析这一批帖，返回 `(结构化数据, 统计)`。

    - 同一条帖跑几遍取 `parse.runs`（§10.3）—— **值只有这一个来源，调用方不给**
    - 各遍都过硬校验后**按帖比三元组**（§10.3）：一致的直接算过、一次调用都不花；
      对不上的那些帖才连同它们各遍的产出交给模型逐遍审
    - `self_check`：`runs=1` 时无从可比，要不要仍然让模型自查一遍
    - `on_judged(批里的帖, 这批产出的行, 成没成)`：一批判完就报一次。**调用方靠它记
      「这条帖判过了」** —— 失败的那批不能记，否则这几条帖永远判不到了
    """
    if RUNS < 1:
        raise ValueError("parse.runs 至少是 1")

    batches = build_batches(posts, batch_size)
    all_signals: list[dict] = []
    tally = {"批": len(batches), "帖": 0, "产": 0, "丢弃": 0, "失败批": 0,
             "编号错": 0, "丢弃清单": [], "失败帖": []}

    for bi, batch in enumerate(batches, 1):
        # 注记取不到的帖在这儿就被筛掉，不进解析
        _, kept = render_batch(batch)
        tally["帖"] += len(kept)
        if not kept:
            continue

        outs: list[list[dict]] = []
        failed = False
        drop_n: list[int] = []               # 各遍强校验丢掉的，逐条记着它出自批内哪条帖
        drop_txt: list[str] = []
        for r in range(RUNS):
            sigs, st = parse_batch(kept, label=f"解析 批{bi}/{len(batches)} 第{r + 1}遍")
            outs.append(sigs)
            drop_n += st.get("丢弃帖号") or []
            drop_txt += st.get("丢弃清单") or []
            tally["编号错"] += st.get("编号错", 0)
            if st.get("失败"):
                tally["失败批"] += 1
                failed = True
            if RUNS > 1:
                time.sleep(BATCH_PAUSE)

        # **整批没调通的帖要记名** —— 它们既没产出行、也没进缓存（下一轮还会重判），
        # 报不出来就成了「信号比上次少了，却不知道少在哪一步」（03§3.8）。
        if failed:
            tally["失败帖"].extend(f"{p['pub']} {p['post_id']}" for p in kept)

        # 各遍都过硬校验了，接着**按帖比三元组**：一致的直接算过，对不上的才送模型（§10.3）
        agreed, disputed = split_agreed(kept, outs)
        by_model = set(disputed)             # 最终产出由模型给的帖号 —— 下面的丢弃要用

        if disputed:
            # 只送对不上的那些帖。`post_n` 得按新下标重编 —— 模型眼里的 0 号是 subs 的第 0 条
            pos = {n: i for i, n in enumerate(disputed)}
            subs = [kept[n] for n in disputed]
            runs_in = [[{**s, "post_n": pos[s["post_n"]]} for s in o if s["post_n"] in pos]
                       for o in outs]
            merged = untag(agreed)
        elif failed and not any(outs):
            # 各遍**全都失败**：没有产出可定夺。**不许把空产出交给模型定夺** ——
            # 那等于让它对着空气编，编出来的引文只要在帖里搜得到就能通过强校验。
            subs, runs_in, merged = [], [], []
            by_model = set(range(len(kept)))
        elif RUNS == 1 and self_check:
            # 无从可比 —— 这一步退化成单纯的自查，一份产出也照样交模型复核一遍
            subs, runs_in, merged = kept, outs, []
            by_model = set(range(len(kept)))
        else:
            subs, runs_in, merged = [], [], untag(agreed)

        lost, n_drop = [], 0
        if subs:
            ruled, st = reconcile(subs, runs_in, label=f"定夺 批{bi}/{len(batches)}")
            merged += ruled
            lost, n_drop = st.get("丢弃清单") or [], st.get("丢弃", 0)

        # **丢弃只数最终那一份产出的** —— 中间那几遍只是它的输入，把它们丢的也算进来，
        # 报出来的会是「本来就不作数的东西」。计数与清单同理，两者必须同源：归模型定夺的
        # 帖由模型另给了一份，各遍在这些帖上丢的就不作数；其余帖的最终产出就是各遍的并集。
        # **已知缺口**：归各遍的这一部分只按帖去重、没按「处」去重 —— 同一处被两遍各丢
        # 一次就记两笔、清单里出现两行。只动报告里的数，不动落盘的行。2026-09-16 定的先不修。
        for txt, n in zip(drop_txt, drop_n):
            if n in by_model:
                continue
            n_drop += 1
            lost.append(txt)

        merged = untag(merged)
        all_signals.extend(merged)
        tally["丢弃"] += n_drop
        tally["丢弃清单"].extend(lost)

        if on_judged:
            on_judged(kept, merged, not failed)
        if progress:
            progress(bi, len(batches), len(merged))
        time.sleep(BATCH_PAUSE)

    all_signals = schema.dedup(all_signals, posts)
    all_signals.sort(key=lambda s: (s["pub"], s["idx"], s["spec"]))
    tally["产"] = len(all_signals)
    return all_signals, tally


def parse_one(post: dict) -> list[dict]:
    """解析单独一条帖 —— 调试用。"""
    sigs, _ = extract([post])
    return sigs


__all__ = ["extract", "parse_batch", "parse_one", "reconcile", "split_agreed", "triple_of",
           "untag", "render_batch", "render_post", "build_batches", "ready_posts",
           "weekday_of", "truncate", "cond_drop"]
