# -*- coding: utf-8 -*-
"""Pillar C 复核裁决固化逐帖缓存（v21，2026-09-09，纯逻辑不调 API）。

不变量（实时推送稳定）：
- I1 无新增→不反转：复核 fix（多→空）后，后续档同帖全缓存命中（零标注零复核）仍=空——
  复核前若只 patch 当档展示行，下档坍缩会从缓存原始行把旧观点捞回（跨档反转）。
- I2 无变化→不缩水 / drop 不复活：复核 drop 后，该帖该板主张持久剔除（缓存余空 entry 保留、
  绝不整删防 cache-miss 重抽复活），后续档该博主不入卡且零调用。
- idx≠上证 的 fix：持久化后 collapse 自动挡在上证卡外 → 当档与后续档均不上卡（持久删除式效果）。
- I1/I2 纯 replay：固定缓存无 fresh，两次 extract_layers 输出 rows_by_board / board_counts 深等。

fix/drop 走逐帖缓存 mutate（源行与 win_rows/缓存条目同对象）→ _collapse_all 重坍缩，当档
卡面 == 后续档坍缩输入。monkeypatch opinion.annotate.annotate_blogger /
opinion.verify.review_candidates，缓存文件走 tempfile，直接 python3 运行。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from opinion import annotate as ann_mod      # noqa: E402
from opinion import cache as o_cache         # noqa: E402
from opinion import verify as vfy_mod        # noqa: E402
import briefing.scripts.summarize as sm      # noqa: E402

TS = 1_760_003_600          # 发帖时刻（epoch 秒）；starts=None 无窗口门，取值随意
PUB = "2026-09-08 09:00"    # 周一，纯 t1/week 词不触 nweek_first→calendar 降级分支


def _full(blogger, pid, d, spec, horizon, summary, quote, idx="上证指数", s=1):
    """全字段规范行（annotate fake / 预置缓存用）：quote_ts/pub 与帖一致，post_n=0。"""
    return {"blogger": blogger, "post_id": pid, "quote_ts": TS, "post_n": 0,
            "pub": PUB, "d": d, "s": s, "idx": idx, "spec": spec, "cat": "scored",
            "horizon": horizon, "quote": quote, "summary": summary}


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
r1_post, r2_post = _post("R1-a"), _post("R2-a")
_write_cache(CACHE, {
    "R1": {"posts": {o_cache.post_key(r1_post): {"ts": TS, "at": "t",
                                                 "rows": [_full("R1", "R1-a", d=1, spec="t1",
                                                               horizon="明天", summary="明天看多",
                                                               quote="明天看多")]}}},
    "R2": {"posts": {o_cache.post_key(r2_post): {"ts": TS, "at": "t",
                                                 "rows": [_full("R2", "R2-a", d=-1, spec="week",
                                                               horizon="本周", summary="本周看空",
                                                               quote="本周看空")]}}},
})
work4 = {"R1": {"posts": [r1_post], "boards": ["short"]},
         "R2": {"posts": [r2_post], "boards": ["swing"]}}
(rbb4, errs4), calls4 = extract(work4, raise_calls=True)
assert errs4 == [] and calls4 == {"annotate": 0, "review": 0}, (errs4, calls4)
assert rbb4["short"]["R1"]["stance"] == "多" and rbb4["swing"]["R2"]["stance"] == "空", rbb4
(rbb4b, errs4b), calls4b = extract(work4, raise_calls=True)
assert rbb4b == rbb4 and sm.board_counts(rbb4b) == sm.board_counts(rbb4)
print("[PASS] I1/I2 纯 replay：窗口不变两次输出逐位一致（rows_by_board / board_counts 深等）")

print("\nPillar C 复核裁决固化逐帖缓存全部通过 ✅")
