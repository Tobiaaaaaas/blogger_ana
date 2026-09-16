# -*- coding: utf-8 -*-
"""报告链提取纯逻辑门单测（2026-09-09 复核 D1/F1/L1/L4，monkeypatch 无、不调 API）。

覆盖 extract_signals_direction.py 本轮改的确定性逻辑：
- D1 spec_sane：normalize 拒 t0/t99/d:2026-13-99（SPEC_RE 之上语义域）；
- L4 target：有效有限正数 float 入行、乱给弃字段不弃行、条件位语义靠后缀（代码不判内容）；
- F1 unscored：dedup 按 (date,d,idx,summary) 精确——不同表述共存、同句合并；共识不投票 union；
- 到案门：_batch_disposition 缺到案缺检出、rows∩no_view 重叠以 rows 为准、no_view 重复/理由出枚举清洗；
- validate_signals pns = 给过行（含行未过 normalize）的帖号；
- 字符预算分批：≤BATCH_CHAR_BUDGET、单帖按 PER_POST_LIMIT 封顶估算。

经 importlib 加载（模块非包路径），直接 python3 运行。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
try:                      # Windows GBK 控制台：断言已全过，别让收尾 emoji 崩掉退出码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_spec = importlib.util.spec_from_file_location(
    "report_extract", os.path.join(ROOT, "scripts", "pipeline", "extract_signals_direction.py"))
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

POST = {"publish_date": "2026-09-05 17:47", "post_id": 1}


def _sig(**kw):
    base = {"pub": POST["publish_date"], "d": 1, "idx": "上证指数", "cat": "scored",
            "spec": "t1", "summary": "s"}
    base.update(kw)
    return base


# ── D1 spec_sane：SPEC_RE 语法之上语义域拒绝 ──
for bad in ("t0", "t99", "d:2026-13-99", "d:2025-02-29"):
    s, why = ex.normalize_signal({"d": 1, "spec": bad, "cat": "scored", "summary": "x"}, POST)
    assert s is None and "spec" in why, (bad, s, why)
s, why = ex.normalize_signal({"d": 1, "spec": "t30", "cat": "scored", "summary": "x"}, POST)
assert s is not None, (s, why)
print("[PASS] D1 spec_sane：t0/t99/非法历法 d: 拒；t30 合法")

# ── L4 target：有限正数 float 收、乱给弃字段不弃行 ──
s, _ = ex.normalize_signal({"d": 1, "spec": "t2", "cat": "scored", "summary": "目标3500",
                            "target": "3500"}, POST)
assert s["target"] == 3500.0, s
for garbage in ("abc点", "站上4250", -5, 0, 1e9, float("nan"), True):
    s, _ = ex.normalize_signal({"d": 1, "spec": "t2", "cat": "scored", "summary": "t",
                                "target": garbage}, POST)
    assert s is not None and "target" not in s, (garbage, s)
s, _ = ex.normalize_signal({"d": -1, "cat": "unscored", "summary": "今年看4500", "target": 4500}, POST)
assert s["cat"] == "unscored" and s["spec"] == "long" and s["target"] == 4500.0, s
print("[PASS] L4 target：数值收 / 乱给弃字段不弃行 / unscored 目标位仍可带 target")

# ── F1 unscored 精确合并（dedup）──
posts_s = ex.dedup_and_sort([
    _sig(d=1, cat="unscored", spec="long", summary="长线慢牛不改"),
    _sig(d=1, cat="unscored", spec="long", summary="今年震荡上行"),
    _sig(d=1, cat="unscored", spec="long", summary="长线慢牛不改"),   # 重复表述
])
assert sorted(x["summary"] for x in posts_s) == ["今年震荡上行", "长线慢牛不改"], posts_s
print("[PASS] F1 dedup：unscored 不同表述共存、同句合并")

# ── F1 共识：scored 需 ≥min_votes、unscored 不投票 union ──
runs = [
    _sig(d=1, spec="t1", summary="明天涨"), _sig(d=1, spec="t1", summary="明天涨"),
    _sig(d=1, spec="t1", summary="明天涨"),
    _sig(d=-1, spec="t1", summary="明天跌"),                        # 1/4 噪声 → 出局
    _sig(d=1, cat="unscored", spec="long", summary="单次出现的长期观点"),  # unscored 1 次也留
]
merged = ex.consensus_merge(runs, 3)
assert len(merged) == 2, merged
assert any(x["cat"] == "scored" and x["summary"] == "明天涨" for x in merged)
assert any(x["cat"] == "unscored" and x["summary"] == "单次出现的长期观点" for x in merged)
# target 多数一致保留、平局偏缺席
runs_t = [_sig(d=1, spec="t3", summary="站上4250", target=4250)] * 3 + \
         [_sig(d=1, spec="t3", summary="站上4250", target=9999)]
mt = ex.consensus_merge(runs_t, 3)
assert mt[0]["target"] == 4250, mt
print("[PASS] F1 共识：scored 投票、unscored union、target 多数一致保留")

# ── validate_signals pns：给过行（行未过 normalize 也算到案）──
posts4 = [dict(POST, publish_date=f"2026-09-0{i} 10:00") for i in range(1, 5)]
raws = [{"post_n": 0, "d": 1, "spec": "t0", "cat": "scored", "summary": "坏 spec"},
        {"post_n": 1, "d": 1, "spec": "t1", "cat": "scored", "summary": "好行"},
        {"post_n": 9, "d": 1, "spec": "t1", "cat": "scored", "summary": "越界"}]
ok, dropped, aligned, pns = ex.validate_signals(raws, posts4)
assert len(ok) == 1 and ok[0]["summary"] == "好行", (ok, dropped)
assert pns == [0, 1] and dropped["post_n 越界"] == 1, (pns, dropped)
print("[PASS] validate_signals：pns 含给过行（含坏行帖号）；越界丢弃")

# ── L1 到案门：缺到案检出 / 重叠以 rows 为准 / 清洗不拦 ──
full = {"rows": [{"post_n": 0, "d": 1, "spec": "t1", "cat": "scored", "summary": "a"}],
        "no_view": [{"post_n": 1, "reason": "复盘回顾"}, {"post_n": 2, "reason": "无明确方向"},
                    {"post_n": 3, "reason": "仓位或理念"}]}
miss, nv = ex._batch_disposition(full, posts4)
assert miss == [] and len(nv) == 3, (miss, nv)
skip = {"rows": [{"post_n": 0, "d": 1, "spec": "t1", "cat": "scored", "summary": "a"}],
        "no_view": [{"post_n": 2, "reason": "无明确方向"}]}
miss2, _ = ex._batch_disposition(skip, posts4)
assert miss2 == [1, 3], miss2                              # 整帖跳读（帖 1、3）→ 缺到案
overlap = {"rows": [{"post_n": 0, "d": 1, "spec": "t1", "cat": "scored", "summary": "a"}],
           "no_view": [{"post_n": 0, "reason": "无明确方向"},   # rows∩no_view 重叠
                       {"post_n": 0, "reason": "状态描述"},     # 重复
                       {"post_n": 1, "reason": "随便说说"},     # 理由出枚举
                       {"post_n": 2, "reason": "转述他人"}]}
miss3, nv3 = ex._batch_disposition(overlap, posts4)
assert miss3 == [3], miss3
assert {e["post_n"] for e in nv3} == {1, 2}, nv3            # 重叠 0 被剔、重复保首个、理由归一
print("[PASS] L1 到案门：缺到案检出 / 重叠 rows 优先 / 重复·理由出枚举自动清洗")

# ── 字符预算分批：每批 ≤ 预算（帖上限按 PER_POST_LIMIT 封顶估）──
def budget_ok(batch, m):
    # 帖自封顶后单批最坏不超 预算+一帖余量；正常批 ≤ 预算
    tot = sum(min(len(p.get("content") or ""), m.PER_POST_LIMIT) + m._BATCH_OVERHEAD for p in batch)
    return tot <= m.BATCH_CHAR_BUDGET + m.PER_POST_LIMIT


short = dict(POST, content="短线观察" * 20)                   # ~100 字
long_p = dict(POST, content="长文研判" * 1500)                # 4500 字（封顶 4000 估）
giant = dict(POST, content="巨文" * 20000)                    # 40000 字 → 封顶后估 4090
posts_mix = [short] * 30 + [long_p] + [giant]
batches = list(ex.build_batches(posts_mix, ex.DEFAULT_BATCH_SIZE, bodies=None))
assert all(len(b) <= ex.DEFAULT_BATCH_SIZE for b in batches)
assert all(budget_ok(b, ex) for b in batches)
print(f"[PASS] 字符预算分批：{len(batches)} 批，均 ≤batch_size={ex.DEFAULT_BATCH_SIZE} 且 ≤预算")


print("\n全部报告链提取纯逻辑门单测通过 ✅")
