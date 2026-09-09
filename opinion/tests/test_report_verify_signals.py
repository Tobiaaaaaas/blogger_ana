# -*- coding: utf-8 -*-
"""报告链 verify_signals 循环单测（2026-09-09 D3，monkeypatch extract.call_json，不调 API）。

loads scripts/pipeline/extract_signals_direction.py（importlib，非包路径）→ verify_signals 直测
keep/fix/drop/补加/未评默认保留 的批内判定循环 + vidx 越界防御 + 批调用失败保留原信号。
fix 走 normalize_signal（与 to_core 同判）——合法 fix 替换、非法 fix 保留原行。
直接 python3 运行。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "extract_signals_direction",
    os.path.join(ROOT, "scripts", "pipeline", "extract_signals_direction.py"))
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

# o_ref.pub_note 依赖真实行情数据——测试里关掉（不发注记）
ex.o_ref.pub_note = lambda *a, **k: None

PUB = "2026-09-08 09:30"


def _post(pid, title):
    return {"post_id": pid, "title": title, "content": title, "publish_date": PUB,
            "pub": PUB}


def _sig(summary, d=1, s=1, spec="t1"):
    return {"d": d, "s": s, "idx": "上证指数", "cat": "scored", "spec": spec,
            "summary": summary, "pub": PUB}


# ── 场景 A：keep/drop/fix/补加/未评默认保留/越界 在一个批次内全部命中 ──
p0, p1, p2, p3, p4 = (_post(f"p{i}", f"帖{i}") for i in range(5))
posts = [p0, p1, p2, p3, p4, p4]            # p4 两帖同对象（同帖两条信号）
signals = [_sig("看多明天"), _sig("看空"), _sig("本周看多", d=1, s=2, spec="week"),
           _sig("再涨"), _sig("明天空A", d=-1), _sig("无周期多", spec="t5")]

_a_ret = {"verdicts": [
    {"vidx": 0, "sig": 0, "action": "keep", "reason": "主结论支持"},
    {"vidx": 1, "sig": 0, "action": "drop", "reason": "纯复盘"},
    {"vidx": 2, "sig": 0, "action": "fix", "d": -1, "s": 2, "spec": "t1", "cat": "scored",
     "summary": "修正为空", "reason": "方向判反"},
    {"vidx": 3, "sig": 0, "action": "fix", "d": 1, "s": 1, "spec": "notaspec",
     "cat": "scored", "summary": "x", "reason": "非法 fix"},
    {"vidx": 4, "sig": 0, "action": "keep", "reason": "ok"},
    {"vidx": 99, "sig": 0, "action": "drop"},                     # vidx 越界 → 忽略
], "add": [{"vidx": 0, "d": 1, "s": 1, "spec": "t5", "cat": "scored",
            "summary": "补：近期偏多"}]}

_orig_call = ex.call_json
ex.call_json = lambda *a, **k: (_a_ret, "raw")
try:
    finals, fposts, stats = ex.verify_signals(None, signals, posts, {}, "测试博主A")
finally:
    ex.call_json = _orig_call

assert stats["keep"] == 2, stats            # vidx0 + vidx4
assert stats["drop"] == 1, stats            # vidx1
assert stats["fix"] == 1, stats             # vidx2 合法 fix
assert stats["add"] == 1, stats             # vidx0 补加
assert stats["vidx 越界"] == 1, stats
assert stats["未评默认保留"] == 1, stats    # p4 第二条 (4,1) 未被评审 → 默认保留
assert sum(1 for k in stats if k.startswith("fix 非法")) == 1, stats  # vidx3 非法 fix → 保留原行
assert len(finals) == 6, [(f.get("summary")) for f in finals]  # 6 入 -1 drop +1 add = 6
summs = [f["summary"] for f in finals]
for want in ("看多明天", "修正为空", "再涨", "明天空A", "无周期多", "补：近期偏多"):
    assert want in summs, (want, summs)
assert "看空" not in summs                 # vidx1 drop 的信号确实被删
# fix 后走 normalize_signal：修正行 spec=t1 域内、无 target
fixed = [f for f in finals if f["summary"] == "修正为空"][0]
assert fixed["d"] == -1 and fixed["spec"] == "t1" and fixed["cat"] == "scored", fixed
# p4 两条都以各自 post 回填
assert [p["post_id"] for p in fposts].count("p4") == 2, [p["post_id"] for p in fposts]
print("[PASS] verify_signals：keep/drop/fix/非法 fix 保原行/补加/未评默认保留/vidx 越界 全部命中")

# ── 场景 B：批调用失败（call_json → None）→ 保留该批原信号 ──
posts_b = [_post("q0", "帖q0")]
signals_b = [_sig("无周期空", d=-1, spec="t5")]
ex.call_json = lambda *a, **k: (None, None)
try:
    finals_b, fposts_b, stats_b = ex.verify_signals(None, signals_b, posts_b, {}, "测试博主B")
finally:
    ex.call_json = _orig_call
assert stats_b["verify 批次失败"] == 1, stats_b
assert len(finals_b) == 1 and finals_b[0]["summary"] == "无周期空", finals_b
print("[PASS] verify_signals：批调用失败 → 保留原信号（不吞真实信号）")

print("\nreport verify_signals 循环全部通过 ✅")
