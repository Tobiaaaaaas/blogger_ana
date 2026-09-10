# -*- coding: utf-8 -*-
"""extract_layers 接线回归（Pillar C/D，2026-09-08，纯逻辑不调 API）。

- Pillar D：标注失败（rows=None）→ 不抹 win_rows，坍缩回退窗口内已缓存旧帖行续显，
  记 errors；无缓存行才置空。
- Pillar C 触发集：只对「本 tick 新标注成功帖、坍缩后上了卡」的行复核；全缓存命中 → 零复核。
- Pillar C drop：剔除该帖该板行后重坍缩，更早仍在窗口的合格行续显。
- Pillar C fix：复核 fix 字段落到卡面展示行（stance/horizon/summary/quote）。

monkeypatch opinion.annotate.annotate_blogger / opinion.verify.review_candidates，
缓存文件走 tempfile，直接 python3 运行。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:                      # Windows GBK 控制台：断言已全过，别让收尾 emoji 崩掉退出码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from opinion import annotate as ann_mod      # noqa: E402
from opinion import cache as o_cache         # noqa: E402
from opinion import verify as vfy_mod        # noqa: E402
import briefing.scripts.summarize as sm      # noqa: E402  _ROWS_CACHE_VERSION（v6）

# 经暂存缓存文件路径加载（extract_layers 调用路径读取）
paths_mod = None


def _cached_row(blogger, pid, ts, d=1, spec="t1", horizon="明天", summary="s", quote="q",
                cat="scored"):
    return {"blogger": blogger, "post_id": pid, "quote_ts": ts, "post_n": 0,
            "pub": "2026-09-07 09:00", "d": d, "s": 1, "idx": "上证指数", "spec": spec,
            "cat": cat, "horizon": horizon, "quote": quote, "summary": summary}


def _post(pid, ts, title="标题", content="正文"):
    return {"post_id": pid, "publish_date": "2026-09-08 11:00", "publish_time": ts,
            "title": title, "content": content}


def _write_cache(tmp, bloggers):
    # 须带与缓存加载同口径的 version + prompt_fp（2026-09-09 A3：指纹 = annotation_fp_input()
    # 共享 prompt + 到案后缀；version 现由 sm._ROWS_CACHE_VERSION 定），否则 cache.load 判失效全量重抽
    data = {"version": sm._ROWS_CACHE_VERSION,
            "prompt_fp": o_cache.prompt_fp(ann_mod.annotation_fp_input()),
            "bloggers": bloggers}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def run_extract(tmp, work):
    """work 按 extract_layers 约定；用 tmp 缓存文件跑一趟并打点 fake 调用。"""
    calls = {"annotate": [], "review": []}

    def fake_annotate(name, posts, **kw):
        calls["annotate"].append((name, [p.get("post_id") for p in posts]))
        handler = ann_handlers.get(name)
        return (None, {}) if handler is None else (handler(posts), {})

    def fake_review(candidates, label=""):
        calls["review"].append(len(candidates))
        return [review_map[(c["board"], c["blogger"], str(c["row"].get("post_id") or ""))]
                for c in candidates], {"keep": 0, "fix": 0, "drop": 0, "err": 0}

    import briefing.scripts.summarize as sm
    global paths_mod
    if paths_mod is None:
        import briefing.scripts.paths as p
        paths_mod = p
    orig_file = paths_mod.ROWS_CACHE_FILE
    orig_ann = ann_mod.annotate_blogger
    orig_rev = vfy_mod.review_candidates
    try:
        paths_mod.ROWS_CACHE_FILE = tmp
        ann_mod.annotate_blogger = fake_annotate
        vfy_mod.review_candidates = fake_review
        rbb, errs = sm.extract_layers(work)
        return rbb, errs, calls
    finally:
        paths_mod.ROWS_CACHE_FILE = orig_file
        ann_mod.annotate_blogger = orig_ann
        vfy_mod.review_candidates = orig_rev


ann_handlers = {}
review_map = {}

# ── Pillar D：标注失败回退缓存旧行 ────────────────────────────────────────
tmpd = tempfile.mkdtemp()
cache_file = os.path.join(tmpd, "rows_cache.json")
ts_old, ts_new = 1_760_000_000, 1_760_003_600
old_post = _post("p_old", ts_old)
blog_a = {"posts": {o_cache.post_key(old_post): {"ts": ts_old, "at": "t",
                                                 "rows": [_cached_row("A", "p_old", ts_old)]}}}
_write_cache(cache_file, {"A": blog_a})
ann_handlers["A"] = None            # rows=None = 标注失败
new_post = _post("p_fresh", ts_new)
rbb, errs, calls = run_extract(cache_file, {"A": {"posts": [new_post, old_post], "boards": ["short"]}})
assert errs == ["A"], errs
row = rbb["short"].get("A")
assert row is not None and row["post_id"] == "p_old", f"失败应回退缓存旧行 p_old，got {row}"
print("[PASS] Pillar D：标注失败回退窗口内已缓存旧行续显（记 errors），非置空")

# 全 fresh 且失败 → 无缓存行可回退 → 该板置空
_write_cache(cache_file, {})
rbb, errs, calls = run_extract(cache_file, {"A": {"posts": [new_post], "boards": ["short"]}})
assert errs == ["A"] and rbb["short"].get("A") is None
print("[PASS] Pillar D：失败且无缓存行 → 该板置空")

# ── Pillar C 触发集：全缓存命中 → 零复核 ─────────────────────────────────
blog_d = {"posts": {o_cache.post_key(old_post): {"ts": ts_old, "at": "t",
                                                 "rows": [_cached_row("D", "p_old", ts_old)]}}}
_write_cache(cache_file, {"D": blog_d})
rbb, errs, calls = run_extract(cache_file, {"D": {"posts": [old_post], "boards": ["short"]}})
assert calls["review"] == [], calls["review"]
assert rbb["short"]["D"]["post_id"] == "p_old"
print("[PASS] Pillar C 触发集：纯缓存命中不触发复核")

# ── Pillar C drop：新帖行上卡被 drop → 剔除重坍缩续显更早行 ───────────────
blog_b = {"posts": {o_cache.post_key(old_post): {"ts": ts_old, "at": "t",
                                                 "rows": [_cached_row("B", "p_old", ts_old)]}}}
_write_cache(cache_file, {"B": blog_b})
fresh_b = _post("p_newb", ts_new)
ann_handlers["B"] = lambda posts: [_cached_row("B", "p_newb", ts_new)]
review_map[("short", "B", "p_newb")] = {"board": "short", "blogger": "B",
                                        "action": "drop", "fix": None, "reason": "fake drop"}
rbb, errs, calls = run_extract(cache_file, {"B": {"posts": [fresh_b, old_post], "boards": ["short"]}})
assert calls["review"] == [1], calls["review"]
assert rbb["short"]["B"]["post_id"] == "p_old", f"drop 后应重坍缩续显 p_old，got {rows['short']['B']}"
print("[PASS] Pillar C drop：剔除新帖行重坍缩续显更早合格行")

# ── Pillar C fix：fix 落到卡面展示行 ─────────────────────────────────────
_write_cache(cache_file, {})
fresh_c = _post("p_newc", ts_new)
ann_handlers["C"] = lambda posts: [_cached_row("C", "p_newc", ts_new, d=1, spec="t1", horizon="明天")]
review_map[("short", "C", "p_newc")] = {"board": "short", "blogger": "C", "action": "fix",
                                        "fix": {"d": -1, "s": 1, "idx": "上证指数", "spec": "today",
                                                "cat": "scored", "horizon": "今天",
                                                "quote": "原话逐字", "summary": "转空"},
                                        "reason": "fake fix"}
rbb, errs, calls = run_extract(cache_file, {"C": {"posts": [fresh_c], "boards": ["short"]}})
assert calls["review"] == [1]
d = rbb["short"]["C"]
assert d["post_id"] == "p_newc" and d["stance"] == "空" and d["horizon"] == "今天", d
assert d["quote"] == "原话逐字" and d["summary"] == "转空", d
print("[PASS] Pillar C fix：复核修正落卡面展示行")

# ── 缓存自愈（2026-09-09 主结论对象门）：缓存旧帖含矛盾行 → 作废整帖重抽，而非弃推 ──
# 门上线前写入的旧缓存可能带"idx=上证 × 主结论点名他指"的矛盾行（衡山/诸葛案例）。这些帖子的
# 内容 hash 未变，永不重评分 → 每 tick 都拿错行坍缩。自愈：发现矛盾缓存帖即作废 → 下进 fresh
# 子批，用带对象门的 annotate 重抽恢复（帖子真含上证观点则重选上证句；只谈他指则 idx 纠正）。
bad_cached = _cached_row("H", "p_old", ts_old, d=-1,
                         summary="看空科创50等回补缺口", quote="看空科创50等回补缺口")
blog_h = {"posts": {o_cache.post_key(old_post): {"ts": ts_old, "at": "t", "rows": [bad_cached]}}}
_write_cache(cache_file, {"H": blog_h})


def h_handler(posts):
    return [_cached_row("H", str(posts[0].get("post_id")), ts_new, d=-1,
                        summary="明天大盘低开看空", quote="明天大盘低开看空")]


ann_handlers["H"] = h_handler
review_map[("short", "H", "p_old")] = {"board": "short", "blogger": "H",
                                       "action": "keep", "fix": None, "reason": "自愈重抽 keep"}
rbb, errs, calls = run_extract(cache_file, {"H": {"posts": [old_post], "boards": ["short"]}})
assert errs == [], errs
assert calls["annotate"] == [("H", ["p_old"])], calls["annotate"]   # 矛盾旧帖被自愈作废 → 触发重抽
d = rbb["short"]["H"]
# 卡面 summary 已剔相对日周词（"明天"），验恢复出的正是上证句而非 科创50 句
assert d is not None and "大盘" in d["summary"] and "科创50" not in d["summary"], d
with open(cache_file, encoding="utf-8") as f:
    saved = json.load(f)
saved_rows = [r for e in saved["bloggers"]["H"]["posts"].values() for r in e["rows"]]
assert ann_mod.conflict_rows(saved_rows) == [], saved_rows   # 落盘缓存不再含矛盾行
print("[PASS] 缓存自愈：矛盾旧帖作废重抽恢复上证观点，落盘缓存无矛盾行")

print("\n全部 extract_layers Pillar C/D 接线回归通过 ✅")
