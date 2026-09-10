# -*- coding: utf-8 -*-
"""opinion.ref_price 共享参考价单测（2026-09-09 报告链复核 L0/D2）。

用合成 bar 表 monkeypatch 模块内 CAL/CAL_SET/INTRADAY，验证：
- D2 整点边界：10:00:00 发帖取「首根 t>hhmm」bar 的 open（= 刚开盘那根的现价），与 10:01 同根；
  旧 `>=` 会让 10:00 回落上一根（09:30 价）——比 10:01 还"旧"一档的怪癖已修。
- 非交易时段回退：午休→11:30 close、盘后→15:00 close、盘前/非交易日→上一交易日 15:00 close。
- 数据末日后的工作日宁缺勿锚（None），周末仍锚上一收盘。
- 双创 = 创业板指/科创50 均值；target_d_check 三态 + no_ref。

直接 python3 运行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:                      # Windows GBK 控制台：断言已全过，别让收尾 emoji 崩掉退出码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from opinion import ref_price as rp  # noqa: E402

# 合成交易日历：2026-09-01(二) 之后 09-02(三)、09-03(四)、09-04(五)；数据末日 = 09-04。
# 09-05/06 为周末（真实休市），09-07(一) 为数据末日后的工作日（宁缺勿锚）。
CAL = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
CAL_SET = set(CAL)

# 每根 bar：open = 该 bar 起始时刻现值（30 分钟 K，bar 标签 = 收盘时间）。
# 上证：09-01 每根 open 递增以便断言取的是哪根。
def _bar(open_p, close_p, t):
    return {"time": t, "open": open_p, "close": close_p}

SH = [
    ("2026-09-01", sorted([
        ("10:00", _bar(1000, 1005, "10:00")),   # 9:30-10:00 完成
        ("10:30", _bar(1050, 1060, "10:30")),   # 10:00-10:30（10:00 开盘价=1050）
        ("11:00", _bar(1100, 1110, "11:00")),
        ("11:30", _bar(1120, 1105, "11:30")),   # 午休锚 11:30 close=1105
        ("13:30", _bar(1200, 1210, "13:30")),
        ("14:00", _bar(1250, 1260, "14:00")),
        ("14:30", _bar(1300, 1310, "14:30")),
        ("15:00", _bar(1350, 1340, "15:00")),   # 盘后锚 15:00 close=1340
    ])),
    ("2026-09-02", sorted([
        ("10:00", _bar(2000, 2005, "10:00")),
        ("10:30", _bar(2050, 2060, "10:30")),
        ("15:00", _bar(2300, 2290, "15:00")),
    ])),
    ("2026-09-04", sorted([("15:00", _bar(3000, 3010, "15:00"))])),  # 数据末日 09-04
]
CY = [(d, rows) for d, rows in SH]           # 创业板/科创 用同一张表（均值断言看取值）
SH_ = [("2026-09-03", sorted([("15:00", _bar(7000, 7010, "15:00"))]))]  # 科创50 只到 09-03


def _patch(idx_intraday=None, cal=CAL):
    idx_intraday = idx_intraday or {"上证指数": SH}
    orig = (rp.CAL, rp.CAL_SET, rp.INTRADAY)
    rp.CAL, rp.CAL_SET, rp.INTRADAY = list(cal), set(cal), idx_intraday
    return orig


def _restore(orig):
    rp.CAL, rp.CAL_SET, rp.INTRADAY = orig


# ── D2 整点边界：10:00 与 10:01 同取 10:30 bar 的 open（= 10:00 现值）──
orig = _patch()
try:
    p, kind, ok = rp._intraday_price("上证指数", "2026-09-01 10:00")
    assert (ok, p, kind) == (True, 1050, "session"), (ok, p, kind)
    p2, kind2, ok2 = rp._intraday_price("上证指数", "2026-09-01 10:01")
    assert (ok2, p2, kind2) == (True, 1050, "session"), (ok2, p2, kind2)
    # 旧 `>=` 会让 10:00 取到 09:30 价 1000——10:00 比 10:01 还旧一档的怪癖
    p3, _, _ = rp._intraday_price("上证指数", "2026-09-01 09:31")
    assert p3 == 1000, p3  # 9:31 → 首根 10:00 bar open=1000（9:30 现值）
    print("[PASS] D2 整点边界：10:00/10:01 同取刚开盘根 open=1050；09:31 取 1000")

    # ── 非交易时段回退 ──
    pl, kl, okl = rp._intraday_price("上证指数", "2026-09-01 12:00")   # 午休 → 11:30 close
    assert (okl, pl, kl) == (True, 1105, "lunch"), (okl, pl, kl)
    pa, ka, oka = rp._intraday_price("上证指数", "2026-09-01 15:30")   # 盘后 → 当日 15:00 close
    assert (oka, pa, ka) == (True, 1340, "after"), (oka, pa, ka)
    pp, kp, okp = rp._intraday_price("上证指数", "2026-09-02 09:00")   # 盘前 → 上一交易日 09-01 15:00 close
    assert (okp, pp, kp) == (True, 1340, "prev"), (okp, pp, kp)
    print("[PASS] 午休/盘后/盘前回退锚正确")

    # ── snapshot_label 标签 ──
    assert rp.snapshot_label("2026-09-01 10:00") == "10:00盘中(30分钟线当根开盘)"
    assert rp.snapshot_label("2026-09-01 12:00") == "午休(11:30收盘)"
    assert rp.snapshot_label("2026-09-01 15:30") == "盘后(15:00收盘)"
    assert rp.snapshot_label("2026-09-05 12:00") == "上一交易日收盘(盘前或休市)"
    print("[PASS] snapshot_label 盘中/午休/盘后/休市标签正确")

    # ── 数据末日边界：周末锚上一收盘、末日后的工作日宁缺勿锚 ──
    p_w, k_w, ok_w = rp._intraday_price("上证指数", "2026-09-05 12:00")   # 周六 → 上一交易日收盘
    assert (ok_w, p_w, k_w) == (True, 3010, "prev"), (ok_w, p_w, k_w)
    p_m, k_m, ok_m = rp._intraday_price("上证指数", "2026-09-07 10:00")   # 数据末日后的周一
    assert not ok_m and p_m is None, (p_m, k_m, ok_m)
    print("[PASS] 数据末日边界：周末锚上一收盘 3010、末日后的工作日宁缺勿锚 None")
finally:
    _restore(orig)

# ── pub_note 单行注记（默认 7 指数；全指数无价 → None 不发）──
three = {"上证指数": SH, "创业板指": SH, "沪深300": SH, "上证50": SH,
         "中证500": SH, "中证1000": SH, "科创50": SH}   # 各表同价 1050
orig = _patch(three)
try:
    note = rp.pub_note("2026-09-01 10:00")
    assert note and note.startswith("[行情@发帖 2026-09-01 10:00]"), note
    assert "上证指数≈1050.00" in note and "创业板指≈1050.00" in note, note
    note2 = rp.pub_note("2026-09-07 10:00")
    assert note2 is None, note2
    print("[PASS] pub_note 注记格式 / 行情缺失不发")
finally:
    _restore(orig)

# ── ref_price_at 双创 = 创业板指/科创50 均值（两表各自不同点位，验证平均而非取单指）──
CY_2 = [(d, rows) for d, rows in SH]                    # 创业板 = 上证同价（10:00 → 1050）
SH2 = []
for d, rows in SH:
    SH2.append((d, sorted((t, {"time": b["time"], "open": b["open"] + 1000.0,
                               "close": b["close"] + 1000.0}) for t, b in rows)))
# 科创50 = 上证 + 1000 → 10:00 档 2050
orig = _patch({"上证指数": SH, "创业板指": CY_2, "科创50": SH2})
try:
    v, okv = rp.ref_price_at("双创", "2026-09-01 10:00")
    assert okv and v == (1050 + 2050) / 2 == 1550, (v, okv)
    # 三表都缺 09-03 → 双创无价（单指无价 → 双创 no_ref）
    v2, okv2 = rp.ref_price_at("双创", "2026-09-03 10:00")
    assert not okv2, (v2, okv2)
    print("[PASS] ref_price_at 双创均值 (1550) / 单指缺行情 → 双创 no_ref")
finally:
    _restore(orig)

# ── target_d_check：agree/conflict/flat/no_ref（不依赖行情）──
assert rp.target_d_check(4250, 3940, 1) == "agree"      # 目标在上、看多 → 一致
assert rp.target_d_check(3900, 3940, -1) == "agree"     # 目标在下、看空 → 一致
assert rp.target_d_check(4250, 3940, -1) == "conflict"  # 目标在上却看空 → flag
assert rp.target_d_check(3940, 3940, 1) == "flat"
assert rp.target_d_check("abc", 3940, 1) == "no_ref"
print("[PASS] target_d_check agree/conflict/flat/no_ref 三态 + no_ref")

print("\n全部 ref_price 单测通过 ✅")
