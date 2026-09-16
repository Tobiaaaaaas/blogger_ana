# -*- coding: utf-8 -*-
"""Pillar C 复核裁决固化逐帖缓存（v21，2026-09-09，纯逻辑不调 API）。

不变量（实时推送稳定）：
- I1 无新增→不反转：复核 fix（多→空）后，后续档同帖全缓存命中（零标注零复核）仍=空——
  复核前若只 patch 当档展示行，下档坍缩会从缓存原始行把旧观点捞回（跨档反转）。
- I2 无变化→不缩水 / drop 不复活：复核 drop 后，该帖该板主张持久剔除（缓存余空 entry 保留、
  绝不整删防 cache-miss 重抽复活），后续档该博主不入卡且零调用。
- idx≠上证 的 fix：持久化后 collapse 自动挡在上证卡外 → 当档与后续档均不上卡（持久删除式效果）。
- I1/I2 纯 replay：固定缓存无 fresh，两次 extract_layers 输出 rows_by_board / board_counts 深等。
- I3（v22 盲区回填）：上卡冠军行若出自**旧帖缓存**（复核触发集看不到它）也必须被复核过——
  源行 `rv` 标记随缓存持久化；未标记的当档补一轮复核并固化（场景 6）。err 按 keep 保留行、
  记 `rv_try`，两次仍不可用即放弃（场景 7，防一行永久占住每档回填名额）。

fix/drop 走逐帖缓存 mutate（源行与 win_rows/缓存条目同对象）→ _collapse_all 重坍缩，当档
卡面 == 后续档坍缩输入。monkeypatch opinion.annotate.annotate_blogger /
opinion.verify.review_candidates，缓存文件走 tempfile，直接 python3 运行。
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
import briefing.scripts.summarize as sm      # noqa: E402

TS = 1_760_003_600          # 发帖时刻（epoch 秒）；starts=None 无窗口门，取值随意
PUB = "2026-09-08 09:00"    # 周一，纯 t1/week 词不触 nweek_first→calendar 降级分支


def _full(blogger, pid, d, spec, horizon, summary, quote, idx="上证指数", s=1, rv=None, qts=TS):
    """全字段规范行（annotate fake / 预置缓存用）：pub 与帖一致，post_n=0。

    rv=1 → 预置为"已复核过"（v22 上卡行回填门据此跳过）；默认 None = 未复核。
    qts → quote_ts（同帖多行时坍缩按更近者优先，回填场景用它造"旧帖行当备胎"）。
    """
    r = {"blogger": blogger, "post_id": pid, "quote_ts": qts, "post_n": 0,
         "pub": PUB, "d": d, "s": s, "idx": idx, "spec": spec, "cat": "scored",
         "horizon": horizon, "quote": quote, "summary": summary}
    if rv is not None:
        r["rv"] = rv
    return r


def _post(pid, ts=TS):
    return {"post_id": pid, "publish_date": PUB, "publish_time": ts,
            "title": f"{pid} 标题", "content": f"{pid} 正文看涨上证"}


def _write_cache(tmp, bloggers):
    """预置缓存：version + prompt 指纹须与 load 同口径，否则判失效全量重抽。"""
    data = {"version": sm._ROWS_CACHE_VERSION,
            "prompt_fp": o_cache.prompt_fp(ann_mod.annotation_fp_input()),
            "bloggers": bloggers}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _saved(tmp, blogger):
    """读回缓存文件博主条目：{key: {ts, rows}}。"""
    with open(tmp, encoding="utf-8") as f:
        data = json.load(f)
    return data["bloggers"][blogger]["posts"]


TMPD = tempfile.mkdtemp()
CACHE = os.path.join(TMPD, "rows_cache.json")


def extract(work, *, ann=None, review=None, raise_calls=False):
    """跑一趟 extract_layers 并打点 fake 调用。raise_calls=True → 任何标注/复核调用即失败
    （run2 全缓存命中的断言：复核裁决须真持久化，不能靠重抽/重复核兜回正确卡面）。"""
    calls = {"annotate": 0, "review": 0}

    def fake_annotate(name, posts, **kw):
        if raise_calls:
            raise AssertionError(f"run2 应全缓存命中，却调用了 annotate({name})")
        calls["annotate"] += 1
        return ann(name, posts), {}

    def fake_review(candidates, label=""):
        if raise_calls:
            raise AssertionError("run2 无 fresh 候选，却调用了 review_candidates")
        calls["review"] += 1
        decs = [review[(c["board"], c["blogger"], str(c["row"].get("post_id") or ""))]
                for c in candidates]
        return decs, {"keep": 0, "fix": 0, "drop": 0, "err": 0}

    import briefing.scripts.paths as p
    orig_file, orig_ann, orig_rev = p.ROWS_CACHE_FILE, ann_mod.annotate_blogger, vfy_mod.review_candidates
    try:
        p.ROWS_CACHE_FILE = CACHE
        ann_mod.annotate_blogger = fake_annotate
        vfy_mod.review_candidates = fake_review
        return sm.extract_layers(work), calls
    finally:
        p.ROWS_CACHE_FILE = orig_file
        ann_mod.annotate_blogger = orig_ann
        vfy_mod.review_candidates = orig_rev


# ── 场景 1（I1）：复核 fix 多→空，裁决固化缓存 → run2 同帖零调用仍=空 ──────────
f1_post = _post("F1-a")
work1 = {"F1": {"posts": [f1_post], "boards": ["short"]}}
ann1 = lambda name, posts: [_full("F1", "F1-a", d=1, spec="t1", horizon="明天",
                                  summary="明天看多大盘", quote="明天看多大盘")]
rev1 = {("short", "F1", "F1-a"): {"board": "short", "blogger": "F1", "action": "fix",
                                  "fix": {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1",
                                          "cat": "scored", "horizon": "明天",
                                          "quote": "明天看空大盘", "summary": "明天看空大盘"},
                                  "reason": "fake fix 方向判反"}}
(rbb1, errs1), calls1 = extract(work1, ann=ann1, review=rev1)
assert errs1 == [], errs1
assert calls1["annotate"] == 1 and calls1["review"] == 1, calls1
d1 = rbb1["short"]["F1"]
assert d1["stance"] == "空" and d1["post_id"] == "F1-a", d1
f1_saved = _saved(CACHE, "F1")
assert len(f1_saved) == 1 and f1_saved[list(f1_saved)[0]]["rows"][0]["d"] == -1, f1_saved
print("[PASS] fix：当档卡面=空 且 缓存行已固化 d=-1（非仅本档展示 patch）")

(rbb2, errs2), calls2 = extract(work1, raise_calls=True)     # 同帖再跑：全缓存命中，零调用
assert errs2 == [] and calls2 == {"annotate": 0, "review": 0}, (errs2, calls2)
d2 = rbb2["short"]["F1"]
assert d2["stance"] == "空", d2
assert rbb2 == rbb1, "同帖纯缓存重跑卡面应逐位等于复核当档（I1：无新增不反转）"
print("[PASS] I1 fix 不反转：run2 零标注零复核，卡面仍=空且 == run1")

# ── 场景 2（I2）：复核 drop → 该板主张持久剔除，run2 零调用不入卡、条目余空保留 ──
f2_post = _post("F2-a")
work2 = {"F2": {"posts": [f2_post], "boards": ["short"]}}
ann2 = lambda name, posts: [_full("F2", "F2-a", d=1, spec="t1", horizon="明天",
                                  summary="明天看多大盘", quote="明天看多大盘")]
rev2 = {("short", "F2", "F2-a"): {"board": "short", "blogger": "F2", "action": "drop",
                                  "fix": None, "reason": "fake drop 纯复盘"}}
(rbb2d, errs2d), calls2d = extract(work2, ann=ann2, review=rev2)
assert errs2d == [] and calls2d["review"] == 1, (errs2d, calls2d)
assert rbb2d["short"].get("F2") is None, rbb2d       # drop 当档不入卡
f2_saved = _saved(CACHE, "F2")
assert len(f2_saved) == 1, f2_saved                   # 条目保留（余空 rows=[]，不整删）
assert f2_saved[list(f2_saved)[0]]["rows"] == [], f2_saved
print("[PASS] drop：当档不入卡，缓存条目余空保留（绝不整删防重抽复活）")

(rbb2d2, errs2d2), calls2d2 = extract(work2, raise_calls=True)
assert errs2d2 == [] and calls2d2 == {"annotate": 0, "review": 0}, (errs2d2, calls2d2)
assert rbb2d2["short"].get("F2") is None, rbb2d2
print("[PASS] I2 drop 不复活：run2 零调用仍不入卡（该在的没了/不该在的出现 均不发生）")

# ── 场景 3：复核 fix idx→创业板指 → 持久挡在上证卡外（当档与 run2 一致地不上卡）──
f3_post = _post("F3-a")
work3 = {"F3": {"posts": [f3_post], "boards": ["short"]}}
ann3 = lambda name, posts: [_full("F3", "F3-a", d=1, spec="t1", horizon="明天",
                                  summary="明天看多大盘", quote="明天看多大盘")]
rev3 = {("short", "F3", "F3-a"): {"board": "short", "blogger": "F3", "action": "fix",
                                  "fix": {"d": -1, "s": 1, "idx": "创业板指", "spec": "t1",
                                          "cat": "scored", "horizon": "明天",
                                          "quote": "创业板指明天低开看空",
                                          "summary": "创业板指明天看空"},
                                  "reason": "fake fix 对象指错"}}
(rbb3, errs3), _ = extract(work3, ann=ann3, review=rev3)
assert errs3 == [], errs3
assert rbb3["short"].get("F3") is None, rbb3        # idx≠上证 → collapse 挡在卡外（当档即持久语义）
f3_saved = _saved(CACHE, "F3")
assert f3_saved[list(f3_saved)[0]]["rows"][0]["idx"] == "创业板指", f3_saved
(rbb3b, errs3b), calls3 = extract(work3, raise_calls=True)
assert errs3b == [] and calls3 == {"annotate": 0, "review": 0}, (errs3b, calls3)
assert rbb3b["short"].get("F3") is None and rbb3b == rbb3, rbb3b
print("[PASS] idx≠上证 fix：持久挡在卡外，当档与 run2 均不上卡（无显示一档后回弹）")

# ── 场景 4（硬化）：fix 将成 idx=上证×点名他指 矛盾行 → 不落缓存按原行保留 ─────────
# 若矛盾 fix 落缓存，下档坍缩的自愈（作废整帖重抽）会删条目重抽、撤销本复核 → 硬化拒绝分支。
f4_post = _post("F4-a")
work4h = {"F4": {"posts": [f4_post], "boards": ["short"]}}
ann4h = lambda name, posts: [_full("F4", "F4-a", d=1, spec="t1", horizon="明天",
                                   summary="明天看多大盘", quote="明天看多大盘")]
rev4h = {("short", "F4", "F4-a"): {"board": "short", "blogger": "F4", "action": "fix",
                                   "fix": {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1",
                                           "cat": "scored", "horizon": "明天",
                                           "quote": "明天看空创业板指等回补缺口",
                                           "summary": "明天看空创业板指等回补缺口"},
                                   "reason": "fake fix 将成矛盾行"}}
(rbb4h, errs4h), calls4h = extract(work4h, ann=ann4h, review=rev4h)
assert errs4h == [] and calls4h["review"] == 1, (errs4h, calls4h)
d4h = rbb4h["short"]["F4"]
assert d4h["stance"] == "多", f"矛盾 fix 应拒（按原行保留=多），got {d4h}"  # 原行 d=1 未被覆写
f4_saved = _saved(CACHE, "F4")
assert f4_saved[list(f4_saved)[0]]["rows"][0]["d"] == 1, f4_saved     # 缓存仍原行（未固化矛盾 fix）
(rbb4h2, errs4h2), calls4h2 = extract(work4h, raise_calls=True)
assert errs4h2 == [] and calls4h2 == {"annotate": 0, "review": 0}, (errs4h2, calls4h2)
assert rbb4h2["short"]["F4"]["stance"] == "多" and rbb4h2 == rbb4h, rbb4h2
print("[PASS] 硬化：矛盾 fix（idx=上证×他指）拒绝落缓存，原行保留且 run2 一致")

# ── 场景 5（I1/I2 纯 replay）：固定缓存、无 fresh，两次输出深等 ──
# 预置行带 rv=1（= 此前复核过，v22 标记随缓存持久化）——否则会被回填轮当"从未复核"重审，
# 见场景 6；这里要验的是"已复核行纯 replay 零调用"。
r1_post, r2_post = _post("R1-a"), _post("R2-a")
_write_cache(CACHE, {
    "R1": {"posts": {o_cache.post_key(r1_post): {"ts": TS, "at": "t",
                                                 "rows": [_full("R1", "R1-a", d=1, spec="t1",
                                                               horizon="明天", summary="明天看多",
                                                               quote="明天看多", rv=1)]}}},
    "R2": {"posts": {o_cache.post_key(r2_post): {"ts": TS, "at": "t",
                                                 "rows": [_full("R2", "R2-a", d=-1, spec="week",
                                                               horizon="本周", summary="本周看空",
                                                               quote="本周看空", rv=1)]}}},
})
work4 = {"R1": {"posts": [r1_post], "boards": ["short"]},
         "R2": {"posts": [r2_post], "boards": ["swing"]}}
(rbb4, errs4), calls4 = extract(work4, raise_calls=True)
assert errs4 == [] and calls4 == {"annotate": 0, "review": 0}, (errs4, calls4)
assert rbb4["short"]["R1"]["stance"] == "多" and rbb4["swing"]["R2"]["stance"] == "空", rbb4
(rbb4b, errs4b), calls4b = extract(work4, raise_calls=True)
assert rbb4b == rbb4 and sm.board_counts(rbb4b) == sm.board_counts(rbb4)
print("[PASS] I1/I2 纯 replay：窗口不变两次输出逐位一致（rows_by_board / board_counts 深等）")

# ── 场景 6（v22 盲区回填）：新帖上卡行被复核 drop 后，**旧帖缓存行顶上** → 同一档内补复核 ──
# 这是 2026-09-10 编造行漏网的机制：复核触发集只认"本 tick 新标注帖产出"的行，旧帖行一旦
# 顶上来就永不复核（大盘蜂向标 09-07 帖即此类，连续多档上卡）。B8 修法：对最终上卡的冠军行
# 查 rv 标记，未复核 → 补一轮复核（同一通道、同 v21 固化语义），并把裁决固化 + 打标记。
b6_old, b6_new = _post("B6-old", ts=TS - 100), _post("B6-new")
_write_cache(CACHE, {
    "B6": {"posts": {o_cache.post_key(b6_old): {
        "ts": TS - 100, "at": "t",
        "rows": [_full("B6", "B6-old", d=1, spec="t1", horizon="明天",
                       summary="旧帖看多", quote="旧帖看多", qts=TS - 100)]}}},
})
work6 = {"B6": {"posts": [b6_new, b6_old], "boards": ["short"]}}
ann6 = lambda name, posts: [_full("B6", "B6-new", d=1, spec="t1", horizon="明天",
                                  summary="新帖看多", quote="新帖看多")]
rev6 = {("short", "B6", "B6-new"): {"board": "short", "blogger": "B6", "action": "drop",
                                    "fix": None, "reason": "fake 新帖行不取信"},
        ("short", "B6", "B6-old"): {"board": "short", "blogger": "B6", "action": "fix",
                                    "fix": {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1",
                                            "cat": "scored", "horizon": "明天",
                                            "quote": "旧帖看空", "summary": "旧帖看空"},
                                    "reason": "fake 盲区回填复核改向"}}
(rbb6, errs6), calls6 = extract(work6, ann=ann6, review=rev6)
assert errs6 == [] and calls6 == {"annotate": 1, "review": 2}, (errs6, calls6)
assert rbb6["short"]["B6"]["stance"] == "空", rbb6        # 新帖被 drop、旧帖被回填复核改向
b6_saved = _saved(CACHE, "B6")
b6_old_rows = b6_saved[o_cache.post_key(b6_old)]["rows"]
b6_new_rows = b6_saved[o_cache.post_key(b6_new)]["rows"]
assert b6_new_rows == [], b6_saved                        # 新帖行 drop 持久化（余空保 entry）
assert b6_old_rows[0]["d"] == -1 and b6_old_rows[0]["rv"] == 1, b6_saved   # 回填裁决固化 + 打标记
print("[PASS] v22 盲区回填：旧帖行顶上后被复核（fix 固化 + rv 标记），不再逃复核")

(rbb6b, errs6b), calls6b = extract(work6, raise_calls=True)     # run2：全命中 + 冠军已复核 → 零调用
assert errs6b == [] and calls6b == {"annotate": 0, "review": 0}, (errs6b, calls6b)
assert rbb6b == rbb6, "回填裁决固化后 run2 应逐位等于当档（无反转/无回弹）"
print("[PASS] v22 回填不重复：run2 零标注零复核（rv 标记随缓存持久化）且卡面一致")

# ── 场景 7（v22 复核不可用）：err 按 keep 保留行、只记尝试次数，两次后放弃不再占名额 ──
b7_post = _post("B7-a")
_write_cache(CACHE, {
    "B7": {"posts": {o_cache.post_key(b7_post): {"ts": TS, "at": "t",
                                                 "rows": [_full("B7", "B7-a", d=1, spec="t1",
                                                                horizon="明天", summary="看多",
                                                                quote="看多")]}}},
})
work7 = {"B7": {"posts": [b7_post], "boards": ["short"]}}
rev7 = {("short", "B7", "B7-a"): {"board": "short", "blogger": "B7", "action": "err",
                                  "fix": None, "reason": "fake 复核不可用"}}
(rbb7, errs7), calls7 = extract(work7, review=rev7)
assert rbb7["short"]["B7"]["stance"] == "多", rbb7          # err 按 keep：行仍在卡上
assert calls7["review"] == 1, calls7
r7 = _saved(CACHE, "B7")
r7row = r7[list(r7)[0]]["rows"][0]
assert r7row.get("rv") is None and r7row.get("rv_try") == 1, r7row    # 未裁决但记了一次尝试
(rbb7b, _), calls7b = extract(work7, review=rev7)           # 第二次：重试（上限 2）
assert calls7b["review"] == 1 and rbb7b == rbb7, (calls7b, rbb7b)
r7b = _saved(CACHE, "B7")
assert r7b[list(r7b)[0]]["rows"][0]["rv_try"] == 2, r7b
(rbb7c, _), calls7c = extract(work7, review=rev7)           # 第三次：已放弃（不再占每档名额）
assert calls7c["review"] == 0, calls7c
assert rbb7c == rbb7b == rbb7, "err 三次输出应一致（保留原行、不改上卡与否）"
print("[PASS] v22 复核不可用：err 保留原行 + 记尝试次数，两次后放弃（防 starvation）")

# ── 场景 8（v22 上线收敛路径）：存量上卡行全部未复核 → 每档 ≤ 上限逐档清零，不一次全审 ──
# 上线首档的存量上卡行都无 rv 标记（= 从未复核）。若一档全审会串行调 LLM 数十次、拖长推送档；
# 上限 + 确定性顺序（板→博主名）保证逐档收敛且可复现。
N_B8 = sm.REVIEW_BACKFILL_MAX + 2
b8_names = [f"C{i}" for i in range(1, N_B8 + 1)]
b8_work = {}
b8_cache = {}
for _n in b8_names:
    _p = _post(f"{_n}-a")
    b8_work[_n] = {"posts": [_p], "boards": ["short"]}
    b8_cache[_n] = {"posts": {o_cache.post_key(_p): {
        "ts": TS, "at": "t",
        "rows": [_full(_n, f"{_n}-a", d=1, spec="t1", horizon="明天",
                       summary=f"{_n} 看多", quote=f"{_n} 看多")]}}}   # 无 rv：存量未复核
_write_cache(CACHE, b8_cache)
rev8 = {(("short"), _n, f"{_n}-a"): {"board": "short", "blogger": _n, "action": "keep",
                                     "fix": None, "reason": "fake keep"}
        for _n in b8_names}
(rbb8, _), calls8 = extract(b8_work, review=rev8)
assert calls8 == {"annotate": 0, "review": 1}, calls8        # 一次调用，只喂上限条
assert all(rbb8["short"][_n]["stance"] == "多" for _n in b8_names), rbb8
marked8 = [_n for _n in b8_names if _saved(CACHE, _n)[list(_saved(CACHE, _n))[0]]["rows"][0].get("rv")]
assert marked8 == b8_names[:sm.REVIEW_BACKFILL_MAX], marked8   # 确定性顺序：先前 N 位
print(f"[PASS] v22 上线收敛：首档只补 {sm.REVIEW_BACKFILL_MAX} 条（上限），其余下档续")

(rbb8b, _), calls8b = extract(b8_work, review=rev8)          # 第二档：余下 2 条
assert calls8b == {"annotate": 0, "review": 1}, calls8b
marked8b = [_n for _n in b8_names if _saved(CACHE, _n)[list(_saved(CACHE, _n))[0]]["rows"][0].get("rv")]
assert marked8b == b8_names, marked8b                        # 存量补齐
assert rbb8b == rbb8, "回填 keep 不应改动卡面"
(rbb8c, _), calls8c = extract(b8_work, raise_calls=True)     # 第三档：全部已复核 → 零调用
assert calls8c == {"annotate": 0, "review": 0}, calls8c
assert rbb8c == rbb8, rbb8c
print("[PASS] v22 上线收敛：两三档内补齐存量，此后零回填调用（卡面稳定）")

print("\nPillar C 复核裁决固化逐帖缓存全部通过 ✅")
