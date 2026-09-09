# -*- coding: utf-8 -*-
"""推送标注缓存（rows_cache.json v5，DeepSeek 增量复用，**逐帖粒度**）。

v4（2026-09-08，整博主规范行 + 窗口帖集合指纹）→ v5（逐帖）：每博主缓存从其窗口帖集合的
"一把指纹"细化为**单帖一行缓存项**——键 = (post_id, 内容 hash)，值 = 该帖自己的规范行
（schema.py 规范行，quote_ts/pub 已系统回填）。每档只把窗口内"新帖 / 正文回填变 content"
的帖送一次标注，**旧帖（含跨交易日窗口滑动重叠的帖）永不重评分**；坍缩
(annotate.collapse_board)仍每 tick 确定性重算——窗口滑动/行过期由坍缩的 quote_ts≥该层
窗口下界 门自动消化，参与坍缩的行 = 仅本次窗口内各帖的缓存行并集。

内容 hash 必须参与键：正文回填让同 post_id 从标题帖变全文，只比 post_id 会命中过期缓存
（坑位保留——hash 变 → 键变 → 只重抽那一帖）。版本或 prompt 指纹任一不符 → 整缓存作废
全量重抽（首档按博主把窗口新帖合成一次批量调用，调用数同 v4 数量级）。
"""
import hashlib
import json
import os


def post_sig(post):
    """单帖内容指纹：标题+正文的前 8 位 sha1（正文回填 = 同 post_id 内容变了）。"""
    raw = ((post.get("title") or "") + "\n" + (post.get("content") or "")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:8]


def post_key(post):
    """单帖缓存键：f"{post_id}:{内容指纹}"——内容 hash 参与，正文回填后键变只重抽该帖。

    无 post_id 的异常帖回退 "#内容指纹"（同文两帖会误并，正常帖都有 post_id）。
    """
    pid = str(post.get("post_id") or "").strip()
    return f"{pid}:{post_sig(post)}" if pid else f"#{post_sig(post)}"


def post_ts(post):
    """单帖发帖时刻（秒）——缓存修剪/诊断用（窗口只前移 → 早于窗口下界的项永不回窗）。"""
    try:
        return int(post.get("publish_time") or 0)
    except (TypeError, ValueError):
        return 0


def prompt_fp(prompt_text):
    """标注 prompt 指纹：改 ANNOTATION_SYSTEM_PROMPT 即变 → 旧口径缓存全量作废重抽。"""
    return hashlib.sha1((prompt_text or "").encode("utf-8")).hexdigest()[:8]


def load(cache_file, version, prompt_text):
    """rows_cache.json → {"version","prompt_fp","bloggers":{博主:{"posts":{键:{ts,rows}}}}。

    缺失/损坏/版本不符/prompt 变更 → 返回空结构（全量重抽）。版本校验防复用旧抽取口径
    的缓存行：v5 存规范行、坍缩进代码后每改一次 prompt/坍缩规则，缓存都须作废。
    """
    try:
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)
        cur_fp = prompt_fp(prompt_text)
        if (isinstance(data, dict) and isinstance(data.get("bloggers"), dict)
                and data.get("version") == version and data.get("prompt_fp") == cur_fp):
            return data
        # 仅在确有旧缓存时才提示作废（缺失/损坏静默重建）
        if isinstance(data, dict) or os.path.exists(cache_file):
            import logging
            logging.getLogger("opinion.cache").info(
                "  rows_cache 失效（v=%r, prompt=%r ≠ 当前 %r），作废全量重抽",
                data.get("version") if isinstance(data, dict) else None,
                data.get("prompt_fp") if isinstance(data, dict) else None, cur_fp)
    except Exception:
        pass
    return {"version": version, "prompt_fp": prompt_fp(prompt_text), "bloggers": {}}


def save(cache_file, cache, prompt_text):
    """原子写 rows_cache.json（先临时文件再 os.replace）。"""
    cache["prompt_fp"] = prompt_fp(prompt_text)
    d = os.path.dirname(cache_file)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = cache_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cache_file)
