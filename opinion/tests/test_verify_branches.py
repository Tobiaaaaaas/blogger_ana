# -*- coding: utf-8 -*-
"""opinion.verify 推送复核分支单测（2026-09-09 D1，monkeypatch ds.call_json，不调 API）。

覆盖：
- _fix_valid   每条拒分支（fix 非 dict / d 非法 / spec 语法+语义域外 / idx 非法+别名 /
                horizon 不在该板白名单 / horizon↔spec 不自洽 / summary 空 / quote 非逐字）+
               s 越界降级 1 + quote 截断 + summary 截断；
- _review_one  keep / fix / drop / err 全分支——fix 不合法 → err 保留候选行、
               调用失败 → err、verdict 结构异常 → err、未知 action → err；
- review_candidates 决策/统计（keep/drop/err 计数）。
直接 python3 运行。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from opinion import ds as ds_mod, verify as vf  # noqa: E402

FULL = "博主：明天大盘要反弹，看多。另外本周看空，注意风险。"
REVIEW_Q = "博主从没说过这句永别了"      # 不在 FULL → quote 非逐字
SHORT_FULL = "今天下午先看反弹。明天继续涨。"


class _patch_ds:
    """monkeypatch opinion.ds.call_json（verify 以模块句柄在调用时取属性）。"""

    def __init__(self, fake):
        self._fake = fake

    def __enter__(self):
        self._orig = ds_mod.call_json
        ds_mod.call_json = self._fake
        return self

    def __exit__(self, *a):
        ds_mod.call_json = self._orig
        return False


def _fx(fix, board="swing", full=FULL):
    return vf._fix_valid(fix, board, full)


# ── _fix_valid 拒分支 ──
assert _fx(None) is None and _fx("x") is None and _fx([]) is None and _fx(123) is None
print("[PASS] fix 非 dict → None")
for bad_d in (0, 2, None, "x"):
    assert _fx({"d": bad_d, "spec": "week", "horizon": "本周", "summary": "s"}) is None
print("[PASS] d 非法（∉{1,-1}）→ None")
for bad_spec in ("zzz", "", "t99", "t0"):
    assert _fx({"d": -1, "spec": bad_spec, "horizon": "本周", "summary": "s"}) is None
print("[PASS] spec 语法/语义域外 → None")
assert _fx({"d": -1, "spec": "week", "horizon": "本周", "idx": "恒生指数", "summary": "s"}) is None
assert _fx({"d": -1, "spec": "week", "horizon": "本周", "idx": "创业板", "summary": "s"}) is None
print("[PASS] idx 非法 → None")
# 别名 idx 归一后合法
out = _fx({"d": -1, "spec": "week", "horizon": "本周", "idx": "上证", "quote": "另外本周看空",
           "summary": "波段看空"})
assert out is not None and out["idx"] == "上证指数", out
print("[PASS] idx 别名（上证→上证指数）归一")
# horizon 不在该板白名单：swing 板给 明天
assert _fx({"d": -1, "spec": "t1", "horizon": "明天", "summary": "s"}) is None
# horizon 在该板但 spec 不自洽：swing 本周 ↔ t2
assert _fx({"d": -1, "spec": "t2", "horizon": "本周", "summary": "s"}) is None
assert _fx({"d": -1, "spec": "today", "horizon": "本周", "summary": "s"}) is None
print("[PASS] horizon 不在板白名单 / horizon↔spec 不自洽 → None")
assert _fx({"d": -1, "spec": "week", "horizon": "本周", "quote": "另外本周看空", "summary": "  "}) is None
print("[PASS] summary 空 → None")
assert _fx({"d": -1, "spec": "week", "horizon": "本周", "quote": REVIEW_Q, "summary": "s"}) is None
print("[PASS] quote 非逐字 → None")
# s 越界降级 1（不拒）；quote 可省；长 summary 截 50
out = _fx({"d": -1, "s": 7, "spec": "week", "horizon": "本周", "summary": "段" * 60})
assert out is not None and out["s"] == 1 and out["quote"] == "" and len(out["summary"]) == 50, out
print("[PASS] s 越界→1、quote 缺省放行、summary 截 50")

# ── _fix_valid 合法行 → 规范化 dict ──
ok = _fx({"d": -1, "s": 2, "spec": "week", "idx": "上证", "horizon": "本周",
          "quote": "另外本周看空", "summary": "波段看空"})
assert ok == {"d": -1, "s": 2, "idx": "上证指数", "spec": "week", "cat": "scored",
              "horizon": "本周", "quote": "另外本周看空", "summary": "波段看空"}, ok
short = _fx({"d": 1, "spec": "today", "horizon": "今天", "quote": "今天下午先看反弹",
             "summary": "看多"}, board="short", full=SHORT_FULL)
assert short is not None and short["horizon"] == "今天" and short["spec"] == "today", short
print("[PASS] _fix_valid 合法行（swing/short 各一）→ 规范 dict")


def _review(verdict):
    """verdict=None 模拟复核调用失败（call_json 返回 None,None）。"""
    cand = {"board": "swing", "blogger": "测试君",
            "row": {"d": -1, "s": 1, "idx": "上证指数", "spec": "week", "cat": "scored",
                    "horizon": "本周", "quote": "另外本周看空", "summary": "波段看空"},
            "post_text": "标题：x\n正文：" + FULL, "full_text": FULL}
    res = None if verdict is None else {"verdict": verdict}
    with _patch_ds(lambda *a, **k: (res, "raw")):
        return vf._review_one(cand, "t:test")


# ── _review_one 全分支 ──
a, _, why = _review(None)
assert a == "err" and why.startswith("复核调用失败"), (a, why)
a, _, why = _review("hello")
assert a == "err" and why.startswith("verdict 结构异常"), (a, why)
a, _, why = _review({"action": "keep", "reason": "主结论支持"})
assert a == "keep" and why == "主结论支持", (a, why)
a, _, why = _review({"action": "drop", "reason": "仅复盘"})
assert a == "drop" and why == "仅复盘", (a, why)
a, fx, why = _review({"action": "fix", "d": -1, "s": 2, "spec": "week", "idx": "上证",
                      "horizon": "本周", "quote": "另外本周看空", "summary": "波段看空",
                      "reason": "改措辞"})
assert a == "fix" and fx is not None and fx["spec"] == "week" and fx["s"] == 2, (a, fx)
a, fx, why = _review({"action": "fix", "d": -1, "s": 1, "spec": "week", "idx": "上证",
                      "horizon": "本周", "quote": REVIEW_Q, "summary": "x", "reason": "r"})
assert a == "err" and fx is None and why.startswith("fix 不合法"), (a, fx, why)
a, fx, why = _review({"action": "purge"})
assert a == "err" and fx is None and why.startswith("未知 action"), (a, why)
print("[PASS] _review_one：keep / fix / drop / err（调用失败·结构异常·fix 不合法·未知 action）")

# ── review_candidates 决策/统计（err = 调用方按 keep 对待）──
_queue = [
    {"verdict": {"action": "keep", "reason": "ok"}},
    {"verdict": {"action": "drop", "reason": "no"}},
    {"verdict": {"action": "fix", "d": 1, "s": 1, "spec": "t1", "horizon": "明天",
                 "idx": "上证", "quote": "明天继续涨", "summary": "看多", "reason": "r"}},
]
cands = [{"board": "swing", "blogger": "B1", "row": {}, "post_text": "x", "full_text": FULL},
         {"board": "swing", "blogger": "B2", "row": {}, "post_text": "x", "full_text": FULL},
         {"board": "short", "blogger": "B3", "row": {}, "post_text": "x", "full_text": SHORT_FULL}]
with _patch_ds(lambda *a, **k: (_queue.pop(0), "raw")):
    decisions, stats = vf.review_candidates(cands, "t:rc")
assert [d["action"] for d in decisions] == ["keep", "drop", "fix"], decisions
assert stats == {"keep": 1, "fix": 1, "drop": 1, "err": 0}, stats
assert decisions[2]["fix"]["idx"] == "上证指数", decisions[2]
print("[PASS] review_candidates：决策序列 + 统计正确（fix 落完整 dict）")

print("\nopinion.verify 复核分支全部通过 ✅")
