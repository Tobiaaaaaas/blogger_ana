# -*- coding: utf-8 -*-
"""annotate_blogger 到案契约 + quote 门路径回归（2026-09-08，monkeypatch ds，不调 API）。

真实 DeepSeek 抽查 B/C/D 后把「硬契约收窄到一条」：每条帖都必须 rows ∪ no_view 到案。
- rows∩no_view 重叠 / no_view 重复 / 理由出枚举 → 自动化解（_clean_no_view）不拦成功；
- 缺到案 → 重试 1 次 → 仍缺 → None；
- quote 坏行全弃后某帖在 rows/no_view 双双缺席 → None（防空缓存假阴性，绝不给 [] 粘住）。

直接 python3 运行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from opinion import annotate as ann
from opinion import ds as ds_mod

POST = {"post_id": "p1", "publish_date": "2026-09-08 11:00", "publish_time": 1_760_003_600,
        "title": "明天怎么看", "content": "今天缩量，明天看涨大盘到新高，但别追高。"}


def run(script, posts=None):
    """script(msg_has_retry: bool) -> (dict|None, raw) 按调用次数喂结果。返回 annotate (rows, raw)。"""
    posts = posts if posts is not None else [POST]
    calls = {"n": 0}

    def fake_call(client, system, user, label, thinking=False):
        calls["n"] += 1
        retry = "纠错" in user
        return script(retry), f"<raw{n}>" if False else None

    orig = ds_mod.call_json
    ds_mod.call_json = fake_call
    try:
        return ann.annotate_blogger("测试", posts, label="t")
    finally:
        ds_mod.call_json = orig


def model_row(quote, d=1, spec="t1", horizon="明天"):
    return {"post_n": 0, "d": d, "s": 1, "idx": "上证指数", "cat": "scored",
            "spec": spec, "horizon": horizon, "quote": quote, "summary": "明天看涨"}


# 1) 重叠冗余：行合法 + 同帖又写 no_view → 自动剔冗余，成功返回（只调 1 次，不重试）
good = model_row("明天看涨大盘到新高")
script1 = lambda retry: {"rows": [good], "no_view": [{"post_n": 0, "reason": "无明确方向"}]}
rows, _raw = run(script1)
assert rows is not None and len(rows) == 1 and rows[0]["post_id"] == "p1", rows
print("[PASS] rows∩no_view 重叠 → 自动剔冗余，成功返回不重试")

# 2) 坏 quote 两次 + no_view 无覆盖 → 弃行后缺到案 → None（绝不给 [] 粘住）
fab = model_row("编造的假句子完全不在原文")
script2 = lambda retry: {"rows": [fab], "no_view": []}
rows, _raw = run(script2)
assert rows is None, f"坏行弃尽致缺到案应 None，got {rows}"
print("[PASS] quote 坏行弃尽 → 缺到案按失败 None（防空缓存假阴性）")

# 3) 真无观点：rows=[] + no_view 到案 → 成功 []（可缓存）
script3 = lambda retry: {"rows": [], "no_view": [{"post_n": 0, "reason": "无实质内容"}]}
rows, _raw = run(script3)
assert rows == [], rows
print("[PASS] 真无观点 rows=[] + no_view 到案 → 成功空列表可缓存")

# 4) 缺到案两轮 → None（失败不缓存）
script4 = lambda retry: {"rows": [], "no_view": []}
rows, _raw = run(script4)
assert rows is None
print("[PASS] 缺到案两轮 → None 按失败处理")

# 5) no_view 理由出枚举 + 重复 → 清洗后仍成功（覆盖是硬契约，类别不拦）
script5 = lambda retry: {"rows": [], "no_view": [
    {"post_n": 0, "reason": "随便说说"}, {"post_n": 0, "reason": "状态描述"}]}
rows, _raw = run(script5)
assert rows == [], rows
print("[PASS] no_view 理由出枚举/重复 → 清洗覆盖处理，不拦成功")

# ── 主结论对象门（2026-09-09 衡山/诸葛复盘）：矛盾行不写缓存，带方向纠错重试恢复 ──
# 对象门 ≠ 弃推：纠错让模型重读原文二选一——帖子确含上证观点 → 重选上证句（idx=上证）；
# 只谈他指 → idx 改真实指数（他指行不进上证板）。quote 逐字门兜底防编造"原文没有的上证观点"。

# p2 两段都有：科创50句（无上证别称）+ 大盘句
P2 = {"post_id": "p2", "publish_date": "2026-09-08 11:00", "publish_time": 1_760_003_601,
      "title": "科创与大盘", "content": "科创50连续走弱看空，等回补缺口企稳。明天大盘低开看空，注意风险。"}
# p3 只谈科创50（无上证观点）
P3 = {"post_id": "p3", "publish_date": "2026-09-08 11:00", "publish_time": 1_760_003_602,
      "title": "科创", "content": "科创50连续走弱看空，等回补缺口企稳，仓位重的减仓。"}


def _row(summary, quote, idx="上证指数", d=-1):
    return {"post_n": 0, "d": d, "s": 1, "idx": idx, "cat": "scored",
            "spec": "t1", "horizon": "明天", "quote": quote, "summary": summary}


OBJ_ROW = _row("看空科创50，等回补企稳", "科创50连续走弱看空，等回补缺口企稳")   # idx=上证 × 他指主句
SH_ROW = _row("明天大盘低开看空", "明天大盘低开看空")                          # 上证句
IDX_FIXED = _row("看空科创50，等回补企稳", "科创50连续走弱看空，等回补缺口企稳", idx="科创50")

# 6) 失败模式二：帖子真含上证观点，首遍却把科创50句标成上证行 → 纠错后取上证句入缓存
script6 = lambda retry: {"rows": [OBJ_ROW if not retry else SH_ROW], "no_view": []}
rows, _raw = run(script6, posts=[P2])
assert rows is not None and len(rows) == 1, rows
assert rows[0]["summary"] == "明天大盘低开看空", rows[0]["summary"]
assert rows[0]["idx"] == "上证指数", rows[0]["idx"]
print("[PASS] 对象门·恢复上证观点：科创50主句矛盾行不缓存，纠错后上证句上缓存")

# 7) 失败模式一：帖子只谈科创50 → 纠错把 idx 改为科创50（合法他指行，非矛盾，不误伤）
script7 = lambda retry: {"rows": [OBJ_ROW if not retry else IDX_FIXED], "no_view": []}
rows, _raw = run(script7, posts=[P3])
assert rows is not None and len(rows) == 1, rows
assert rows[0]["idx"] == "科创50", rows[0]["idx"]
print("[PASS] 对象门·纠正 idx：只谈他指的帖纠错为 idx=科创50，他指行不被误伤")

# 8) 顽固执迷两轮（同帖另有合格上证行）→ 矛盾行弃、合格行保留
script8 = lambda retry: {"rows": [OBJ_ROW, SH_ROW], "no_view": []}
rows, _raw = run(script8, posts=[P2])
assert rows is not None and len(rows) == 1, rows
assert rows[0]["summary"] == "明天大盘低开看空", [r["summary"] for r in rows]
print("[PASS] 对象门·顽固执迷：矛盾行弃行复查，同帖合格上证行照常入缓存")

# 9) 顽固执迷且矛盾行是该帖唯一表征、无 no_view → 缺到案按失败 None（不缓存，防假阴性粘住）
script9 = lambda retry: {"rows": [OBJ_ROW], "no_view": []}
rows, _raw = run(script9, posts=[P3])
assert rows is None, rows
print("[PASS] 对象门·唯一表征仍矛盾 → 按失败不缓存（下轮/自愈重试，不给矛盾行当答案）")

print("\n全部 annotate 到案契约/quote/对象门路径回归通过 ✅")
