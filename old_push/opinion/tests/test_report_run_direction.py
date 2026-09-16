# -*- coding: utf-8 -*-
"""report 打分引擎 run_direction 读库守卫单测（2026-09-09 A2 域外 spec / D 报告侧扩展）。

loads scripts/eval/run_direction.py（importlib，非包路径）→ sanitize_signals 纯逻辑直测：
- A2 域外 tN 归置：t90/t34/t60（N>30）→ spec=long cat=unscored（09-09 教义：中长期不计分，
  方向保留）；t0/畸形 → 丢弃；t1/t30 域内原样放行；已归 long 的行幂等；
- 域外归置行经 calc 一律 不计分（score=None），不再沿 endpoint_of 循环 N 交易日打实分。

注意：import run_direction 会装载行情（market_data + intraday），与报告重渲同环境。
直接 python3 运行。
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
    "run_direction", os.path.join(ROOT, "scripts", "eval", "run_direction.py"))
eng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eng)


def _sig(spec, d=1, cat="scored", pub="2026-01-20 10:00"):
    return {"pub": pub, "d": d, "idx": "上证指数", "cat": cat,
            "spec": spec, "summary": "s"}


def _specs(signals):
    return [(s.get("spec"), s.get("cat")) for s in eng.sanitize_signals(signals)]


# ── A2：N>30 域外 tN → spec=long/unscored（方向保留、不计分）──
out = eng.sanitize_signals([_sig("t90"), _sig("t34"), _sig("t60")])
assert _specs([_sig("t90"), _sig("t34"), _sig("t60")]) == \
    [("long", "unscored"), ("long", "unscored"), ("long", "unscored")], out
rows = [eng.calc(s) for s in out]
assert all(r["score"] is None and r["note"] == "不计分" for r in rows), rows
print("[PASS] A2 域外 tN(N>30)：t90/t34/t60 → long/unscored，经 calc 不计分")

# ── A2：t0 / 语法畸形 tN → 丢弃；t999 仍按 N>30 归 long/unscored；非 tN 形态（spec 非字符串）放行 ──
out = eng.sanitize_signals([_sig("t0"), _sig("t"), {"pub": "x", "spec": 3}])
assert out == [{"pub": "x", "spec": 3}], out          # 非 tN 形态不属守卫域 → 原样
out = eng.sanitize_signals([_sig("t999")])
assert [(s["spec"], s["cat"]) for s in out] == [("long", "unscored")], out
print("[PASS] A2 域外 t0/畸形 → 丢弃；t999 → long/unscored；非 tN 形态放行")

# ── A2：域内 t1/t30 原样放行；unscored-long 幂等 ──
out = eng.sanitize_signals([_sig("t1"), _sig("t30"), _sig("long", cat="unscored")])
assert [s["spec"] for s in out] == ["t1", "t30", "long"], out
assert out[2]["cat"] == "unscored"
print("[PASS] A2 域内 t1/t30 与 unscored-long 原样放行（幂等）")

# ── A2：d: 历法日期 / 具名词汇不经守卫（域由 calc/endpoint_of 原有逻辑处理）──
out = eng.sanitize_signals([_sig("d:2026-02-10"), _sig("week"), _sig("nmonth")])
assert [s["spec"] for s in out] == ["d:2026-02-10", "week", "nmonth"], out
print("[PASS] A2 d:历法日期与具名词汇原样放行")

print("\nreport run_direction 读库守卫 A2 全部通过 ✅")
