# -*- coding: utf-8 -*-
"""02 llm解析 —— **解析一条帖**这一个动作。

输入一批帖，输出零到多条结构化数据。**批的大小、排序、跑几次、存哪，都不在这里** ——
那是调用方（03 报告 / 06 推送）的事，本文只管「给我这些帖，我还你结构化数据」。

外部事实只有一样：**行情注记**（发帖时刻七个主指数的现值）。**取不到注记的帖不解析** ——
点位类判断会退回「模型凭旧记忆猜」，而旧记忆里的点位和发帖时的点位常常差几百点。
"""

from __future__ import annotations

import json
import time
from datetime import date

from blogger.common import ds, market
from blogger.parse import prompts, schema

BATCH_SIZE = 15          # 一批最多几条帖
BATCH_CHAR_BUDGET = 30000
PER_POST_LIMIT = 4000    # 单帖正文截断长度（保头 60% 尾 40%）
BATCH_PAUSE = 0.5        # 批与批之间的间隔（秒）

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
    """一条帖喂给模型的样子：编号、发帖时间**加周几**、标题、正文、行情注记。"""
    head = f"[{i}] 发帖 {post['pub']} {weekday_of(post['pub'])}"
    title = (post.get("title") or "").strip()
    if title:
        head += f"｜{title}"
    return "\n".join([head, truncate(post.get("content") or ""), note])


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

def parse_batch(posts: list[dict], label: str = "") -> tuple[list[dict], dict]:
    """一批帖跑**一遍**模型，就地做强校验。返回 `(本批的信号, 计数)`。"""
    if not posts:
        return [], {}

    user_text, kept = render_batch(posts)
    if not kept:
        return [], {"跳过": len(posts), "原因": "行情注记取不到"}
    if not user_text.strip():
        return [], {"跳过": len(kept)}

    result = ds.call_json(prompts.ANNOTATION_SYSTEM_PROMPT, user_text, label or "解析")
    if result is None:
        return [], {"失败": len(kept)}

    signals, dropped, bad_n = [], [], 0
    for raw in (result.get("signals") or []):
        n = raw.get("post_n")
        if not isinstance(n, int) or not (0 <= n < len(kept)):
            bad_n += 1
            continue
        sig, why = schema.to_signal(raw, kept[n])
        if sig is None:
            # 带上出处 —— 这条被丢了，报告里再也看不到它，只有这里能说明白是哪儿丢的
            dropped.append(f"{kept[n]['pub']} {kept[n]['post_id']}｜{why}")
        else:
            signals.append(sig)

    signals, dups = schema.dedup_with_dropped(signals)

    return signals, {
        "帖": len(kept), "产": len(signals), "去重": len(dups),
        "丢弃": len(dropped), "编号错": bad_n,
        "丢弃清单": dropped,
        "去重清单": [f"{s['pub']} {s['post_id']}｜同帖同对象同周期的重复表述"
                     f"（{s['idx']} {s['spec']} {s['d']:+d}｜{s['quote'][:20]}…）" for s in dups],
    }


# ── 定夺 ────────────────────────────────────────────────────────────────

def reconcile(posts: list[dict], runs: list[list[dict]], label: str = ""
              ) -> tuple[list[dict], list[str]]:
    """把 N 份产出连同原文交给模型，由它定夺最终取哪些。

    **N = 1 时没有分歧可定夺，这一步退化成单纯的自查** —— 照样跑，让模型独立看一遍
    「引文里的方向词在原帖里搜不搜得到」。

    返回 `(结构化数据, 被丢掉的清单)`。清单要在这儿数、不在第一遍解析那儿数：
    **这一步的产出才是最终进文件的那一份**，第一遍的那些只是它的输入。
    """
    if not posts:
        return [], []

    user_text, kept = render_batch(posts)
    if not kept:
        return [], []
    body = json.dumps({"runs": runs}, ensure_ascii=False, indent=1)
    result = ds.call_json(prompts.RECONCILE_SYSTEM_PROMPT,
                          f"{user_text}\n\n## 各遍产出\n{body}", label or "定夺")
    if result is None:
        # 定夺没跑成，退回各遍的并集 —— 这一退没有「被丢掉」可言
        return schema.dedup([s for run in runs for s in run]), []

    signals, lost, bad_n = [], [], 0
    for raw in (result.get("signals") or []):
        n = raw.get("post_n")
        if not isinstance(n, int) or not (0 <= n < len(kept)):
            bad_n += 1
            continue
        sig, why = schema.to_signal(raw, kept[n])
        if sig is None:
            lost.append(f"{kept[n]['pub']} {kept[n]['post_id']}｜{why}")
        else:
            signals.append(sig)

    signals, dups = schema.dedup_with_dropped(signals)
    if bad_n:
        lost.append(f"（另有 {bad_n} 处编号指错：指向了不存在的帖号，整条丢掉）")
    lost += [f"{s['pub']} {s['post_id']}｜同帖同对象同周期的重复表述"
             f"（{s['idx']} {s['spec']} {s['d']:+d}｜{s['quote'][:20]}…）" for s in dups]
    return signals, lost


# ── 入口 ────────────────────────────────────────────────────────────────

def extract(posts: list[dict], runs: int = 1, self_check: bool = True,
            batch_size: int = BATCH_SIZE, progress=None, on_judged=None
            ) -> tuple[list[dict], dict]:
    """解析这一批帖，返回 `(结构化数据, 统计)`。

    - `runs`：同一条帖跑几遍。跑几遍、怎么定夺归本文；**N 由调用方给**（见 03）
    - `self_check`：`runs=1` 时要不要仍然让模型自查一遍
    - `on_judged(批里的帖, 这批产出的行, 成没成)`：一批判完就报一次。**调用方靠它记
      「这条帖判过了」** —— 失败的那批不能记，否则这几条帖永远判不到了
    """
    if runs < 1:
        raise ValueError("runs 至少是 1")

    batches = build_batches(posts, batch_size)
    all_signals: list[dict] = []
    tally = {"批": len(batches), "帖": 0, "产": 0, "丢弃": 0, "失败批": 0,
             "编号错": 0, "丢弃清单": []}

    for bi, batch in enumerate(batches, 1):
        # 注记取不到的帖在这儿就被筛掉，不进 runs
        _, kept = render_batch(batch)
        tally["帖"] += len(kept)
        if not kept:
            continue

        outs: list[list[dict]] = []
        failed = False
        for r in range(runs):
            sigs, st = parse_batch(kept, label=f"解析 批{bi}/{len(batches)} 第{r + 1}遍")
            outs.append(sigs)
            tally["产"] += len(sigs)
            tally["丢弃"] += st.get("丢弃", 0)
            tally["编号错"] += st.get("编号错", 0)
            if st.get("失败"):
                tally["失败批"] += 1
                failed = True
            if runs > 1:
                time.sleep(BATCH_PAUSE)

        # 被丢掉的清单**只从最终那一份产出里数** —— 中间那几遍只是它的输入，
        # 把它们丢的也算进来，报出来的会是「本来就不作数的东西」。
        if failed and not any(outs):
            # 各遍**全都失败**：没有产出可定夺。**不许把空产出交给模型定夺** ——
            # 那等于让它对着空气编，编出来的引文只要在帖里搜得到就能通过强校验。
            merged, lost = [], []
        elif self_check or runs > 1:
            merged, lost = reconcile(kept, outs, label=f"定夺 批{bi}/{len(batches)}")
        else:
            merged, dups = schema.dedup_with_dropped([s for o in outs for s in o])
            lost = [f"{s['pub']} {s['post_id']}｜同帖同对象同周期的重复表述"
                    f"（{s['idx']} {s['spec']} {s['d']:+d}｜{s['quote'][:20]}…）" for s in dups]
        all_signals.extend(merged)
        tally["丢弃清单"].extend(lost)

        if on_judged:
            on_judged(kept, merged, not failed)
        if progress:
            progress(bi, len(batches), len(merged))
        time.sleep(BATCH_PAUSE)

    all_signals = schema.dedup(all_signals)
    all_signals.sort(key=lambda s: (s["pub"], s["idx"], s["spec"]))
    tally["产"] = len(all_signals)
    return all_signals, tally


def parse_one(post: dict, runs: int = 1) -> list[dict]:
    """解析单独一条帖 —— 调试用。"""
    sigs, _ = extract([post], runs=runs)
    return sigs


__all__ = ["extract", "parse_batch", "parse_one", "reconcile", "render_batch",
           "render_post", "build_batches", "ready_posts", "weekday_of", "truncate"]
