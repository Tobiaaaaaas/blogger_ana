# -*- coding: utf-8 -*-
"""共享读帖层：data/posts/<博主>.json 主文件 + _bodies_s*.json 正文分片合并。

推送(briefing/run_briefing._read_window_posts 原逻辑)与报告(extract_signals_direction.
load_posts_and_bodies 原逻辑)共用的读帖入口统一在此；两场景差异只剩参数：
- 推送按 [start_ts, now_ts]（发帖时刻秒）取窗口内可读帖：新→旧、去视频/无正文短帖、上限 N
- 报告按发布时间 ≥ since 全量过滤（含 2026 前计数），并可另读正文分片兜底
data/posts 目录经调用方传入（不 import briefing，离线裸脚本可干净导入）。
"""
import glob
import json
import os

from . import text

# 默认全量抽取下界（报告用；与旧 extract_signals_direction.SIGNAL_START 同值）
DEFAULT_SINCE = "2026-01-01"


def blogger_file(blogger, posts_dir):
    """data/posts/<博主>.json 路径。"""
    return os.path.join(posts_dir, f"{blogger}.json")


def load_blogger_posts(blogger, posts_dir):
    """读 data/posts/<博主>.json 的全部帖子（磁盘序：新→旧）。文件缺失/损坏返回 None。"""
    fp = blogger_file(blogger, posts_dir)
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, encoding="utf-8") as f:
            return (json.load(f).get("posts") or [])
    except Exception:
        return None


def load_bodies(blogger, posts_dir):
    """合并 <博主>_bodies_s*.json 正文分片 → {post_id: {"title","body"}}；坏分片跳过。"""
    bodies = {}
    for fp in sorted(glob.glob(os.path.join(posts_dir, f"{blogger}_bodies_s*.json"))):
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                bodies.update(data)
        except Exception:
            continue
    return bodies


def posts_since(all_posts, since=DEFAULT_SINCE):
    """过滤发布时间 ≥ since 的评估帖（报告用）。返回 (eval_posts, pre_count)。

    无 publish_date 的帖子跳过（不计入 pre_count，与旧实现一致）。
    """
    eval_posts, pre_count = [], 0
    for p in all_posts:
        pd = (p.get("publish_date") or "").strip()
        if not pd:
            continue
        if pd[:10] < since:
            pre_count += 1
        else:
            eval_posts.append(p)
    return eval_posts, pre_count


def load_report_posts(blogger, posts_dir, since=DEFAULT_SINCE):
    """报告读帖全集：主文件 + 正文分片 + ≥since 过滤。返回 (all_posts, eval_posts, pre_count, bodies)。

    all_posts 为 None 表示主文件缺失（调用方负责报错退出）。
    """
    all_posts = load_blogger_posts(blogger, posts_dir)
    if all_posts is None:
        return None, None, None, None
    eval_posts, pre_count = posts_since(all_posts, since)
    return all_posts, eval_posts, pre_count, load_bodies(blogger, posts_dir)


def read_window_posts(blogger, posts_dir, start_ts, now_ts, limit=8):
    """推送窗口读帖：返回 [start_ts, now_ts]（发帖时刻，秒）内可读帖，新→旧，至多 limit 条。

    过滤 [视频帖]/无正文短帖（与打分/摘要口径一致）——行抽取只依赖返回列表，下标即引文来源。
    """
    posts = load_blogger_posts(blogger, posts_dir)
    if not posts:
        return []
    win = []
    for p in posts:
        ts = p.get("publish_time") or 0
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            ts = 0
        if not (start_ts <= ts <= now_ts):
            continue
        if text.is_drop_content(p.get("content") or ""):
            continue
        win.append(p)
    win.sort(key=lambda x: x.get("publish_time") or 0, reverse=True)
    return win[:limit]
