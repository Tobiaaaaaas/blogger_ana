# -*- coding: utf-8 -*-
"""推送时效门回归（2026-09-10 用户需求①②，纯逻辑、不调 API）。

用户需求原文：
  ①「超短线推送：只看验证终点时间晚于现在推送时间的（不然已经过期了…）。但是预测能力限定
     spec=t1 或 today。例如 9月9日晚上发布的就不要推送预测 9.9 下午三点收盘的」
  ②「实时推送的每一条 注明验证终点时间、spec 标注」

本测试钉死三件事（`briefing/scripts/summarize.resolve_anchors` + `render._fmt_board_row`）：
- **验证终点过期门（两板统一）**：终点时刻（终点日 15:00 收盘）≤ 卡片时刻 → 该行不显示。
  用户原例：09-09 20:00 发的 spec=today（终点 09-09 15:00，已过）→ 任何档位都不得再上卡；
  同帖 spec=t1（终点 09-10 15:00）→ 09-09 20:00 当晚仍应上卡。
- **超短 spec 门**：spec ∉ {today, t1} → 不上超短卡（其余档位即便 horizon 落在今天/明天）。
- **行头标注**：`· 终点 MM-DD 收盘 · spec <code>`（有终点/spec 才追加）。

直接 python3 运行。
"""
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIEFING = os.path.join(ROOT, "briefing")
sys.path.insert(0, BRIEFING)      # scripts.summarize / scripts.render（包内相对 import）
sys.path.insert(0, ROOT)

from opinion import schema as sch              # noqa: E402
import scripts.render as R                     # noqa: E402
import scripts.summarize as S                  # noqa: E402
from scripts import endpoint as EP             # noqa: E402

BJ = timezone(timedelta(hours=8))
logging.disable(logging.CRITICAL)   # 静音门命中的 info/warning（门行为由断言判，不靠日志）


def ts(s):
    """'2026-09-09 20:00' → epoch 秒（北京时）。"""
    d, hm = s.split(" ")
    return int(datetime(*map(int, d.split("-")), *map(int, hm.split(":")), tzinfo=BJ).timestamp())


def now(s):
    d, hm = s.split(" ")
    return datetime(*map(int, d.split("-")), *map(int, hm.split(":")), tzinfo=BJ)


def row(board, spec, horizon, pub, stance="多"):
    """构造坍缩后的板面行（形状同 collapse_board 输出：带 spec）。"""
    assert sch.horizon_spec_ok(horizon, spec), f"用例自检：{horizon}/{spec} 不自洽"
    return {"blogger": "测试博主", "post_id": "P1", "has_view": True, "stance": stance,
            "horizon": horizon, "spec": spec, "summary": "摘要一句",
            "quote": "原话一句", "quote_ts": ts(pub)}


# 2026-09 日历：09-04 周五 / 09-05 周六 / 09-06 周日 / 09-07 周一 / 09-10 周四 / 09-11 周五
#               09-14 周一 / 09-18 周五（无节假日；中秋 09-25~09-27 不落在用例内）

# ── 门①：验证终点过期门（两板统一）────────────────────────────────────────────
# 用户原例：09-09（周三）20:00 发帖、spec=today → 终点 09-09 15:00，发帖时即已过
USER_CASE = row("short", "today", "今天", "2026-09-09 20:00")
assert EP.endpoint_dt(date(2026, 9, 9), "today") == now("2026-09-09 15:00")
for t in ("2026-09-09 20:00", "2026-09-09 22:00", "2026-09-10 09:00", "2026-09-11 14:30"):
    out = S.resolve_anchors({"short": {"测试博主": USER_CASE}}, now(t))["short"]
    assert out == {}, f"门①失效：{t} 仍显示已过期行 {out}"
print("[PASS] 门① 用户原例：09-09 20:00 发的 spec=today（终点 09-09 15:00）在任何档位都不上卡")

# 同帖 spec=t1（终点 09-10 15:00）→ 09-09 当晚仍应上卡，09-10 收盘后剔除
T1_CASE = row("short", "t1", "明天", "2026-09-09 20:00")
assert S.resolve_anchors({"short": {"测试博主": T1_CASE}}, now("2026-09-09 20:00"))["short"], \
    "门①过严：终点未到的 t1 行被误剔"
assert S.resolve_anchors({"short": {"测试博主": T1_CASE}}, now("2026-09-10 14:30"))["short"], \
    "门①过严：终点当日盘中（未收盘）的行被误剔"
assert S.resolve_anchors({"short": {"测试博主": T1_CASE}}, now("2026-09-10 15:00"))["short"] == {}, \
    "门①失效：终点 09-10 15:00 收盘后仍显示"
print("[PASS] 门① 边界：终点未到/当日盘中保留，终点 15:00 收盘（含）即剔除")

# 当日盘中发的 today 行：终点当日 15:00 → 盘中上卡、收盘即下卡
TODAY_CASE = row("short", "today", "今天", "2026-09-10 08:00")
assert S.resolve_anchors({"short": {"测试博主": TODAY_CASE}}, now("2026-09-10 09:00"))["short"]
assert S.resolve_anchors({"short": {"测试博主": TODAY_CASE}}, now("2026-09-10 14:30"))["short"]
assert S.resolve_anchors({"short": {"测试博主": TODAY_CASE}}, now("2026-09-10 20:00"))["short"] == {}
print("[PASS] 门① 当日 today 行：09:00/14:30 上卡、20:00（收盘后）剔除")

# 波段板同门：本周行终点 = 本周最后交易日（09-11 周五）15:00 → 09-11 盘后剔除
WEEK_CASE = row("swing", "week", "本周", "2026-09-07 09:30")
assert S.resolve_anchors({"swing": {"测试博主": WEEK_CASE}}, now("2026-09-11 14:30"))["swing"]
assert S.resolve_anchors({"swing": {"测试博主": WEEK_CASE}}, now("2026-09-11 16:00"))["swing"] == {}, \
    "门①未覆盖波段板：本周行在终点收盘后仍显示"
# 下周行终点 09-18 → 09-14（下周一）上卡
NWEEK_CASE = row("swing", "nweek", "下周", "2026-09-07 09:30")
assert S.resolve_anchors({"swing": {"测试博主": NWEEK_CASE}}, now("2026-09-14 09:00"))["swing"]
print("[PASS] 门① 两板统一：波段本周行 09-11 盘后剔除 / 下周行 09-14 上卡")

# ── 门① 与 anchor 同口径（2026-09-10 修正的周末 nweek 缺陷回归，用户案例）────────
# 智由智哉 09-06（周日）帖「下周先抑后扬，整体看多」：anchor = 下周 09-14~09-18，
# 则验证终点必须是 09-18（该周最后交易日）。修复前 endpoint 走 pub+7 取 ISO 周 → 09-11，
# 卡面自相矛盾（"下周 09-14~09-18 · 终点 09-11 收盘"），且门① 会在 09-11 盘后提前一周剔除该行。
ZYZZ = row("swing", "nweek", "下周", "2026-09-06 11:29")
assert EP.endpoint_of(date(2026, 9, 6), "nweek") == date(2026, 9, 18), "周末 nweek 终点口径回退"

def _swing_out(t):
    return S.resolve_anchors({"swing": {"智由智哉": ZYZZ}}, now(t))["swing"].get("智由智哉")

# 用户看到的那一档：卡 09-10 → anchor「下周 09-14~09-18」、终点 09-18（修复前误答 09-11）
o = _swing_out("2026-09-10 09:00")
assert o["anchor"] == "下周 09-14~09-18" and o["endpoint"] == date(2026, 9, 18), o
# 跨档不变式：**终点日必须始终落在 anchor 展示的周段内**（卡面自洽；标签随卡片日变，周段不变）
for t, want_anchor in (("2026-09-10 09:00", "下周 09-14~09-18"),
                       ("2026-09-11 16:00", "下周 09-14~09-18"),   # 修复前 09-11 盘后即被误剔
                       ("2026-09-14 09:00", "本周 09-14~09-18")):  # 进入目标周后改口径为「本周」
    o = _swing_out(t)
    assert o, f"{t}：行被提前剔除（周末 nweek 终点算错 → 门① 早于目标周触发）"
    assert o["anchor"] == want_anchor, (t, o["anchor"])
    lo, hi = (date(2026, 9, 14), date(2026, 9, 18))
    assert lo <= o["endpoint"] <= hi, f"{t}：终点 {o['endpoint']} 不在 anchor 周段 {lo}~{hi} 内"
# 到真正的终点 09-18 15:00 收盘后才剔除
assert _swing_out("2026-09-18 14:30")
assert _swing_out("2026-09-18 20:00") is None
print("[PASS] 门① 周末 nweek 与 anchor 同口径：09-11 盘后不再误剔、终点恒落在 anchor 周段内（用户案例）")

# long（无终点）不过门，不编造日期
LONG_CASE = {"blogger": "测试博主", "post_id": "P1", "has_view": True, "stance": "多",
             "horizon": "", "spec": "long", "summary": "s", "quote": "", "quote_ts": ts("2026-09-07 09:30")}
out = S.resolve_anchors({"swing": {"测试博主": LONG_CASE}}, now("2026-09-14 09:00"))["swing"]
assert out and "endpoint" not in out, f"long 行不应有终点、也不应被门① 剔除: {out}"
print("[PASS] 门① long 无终点：不过门（不编造日期）、正常上卡")

# ── 门②：超短 spec 门（预测能力 = 1 个交易日内 → 只认 today/t1）────────────────
for bad_spec, bad_h in (("t2", "近日"), ("t5", "未提"), ("nweek", "下周"), ("month", "更长")):
    r = {"blogger": "测试博主", "post_id": "P1", "has_view": True, "stance": "多",
         "horizon": bad_h, "spec": bad_spec, "summary": "s", "quote": "q",
         "quote_ts": ts("2026-09-09 20:00")}
    out = S.resolve_anchors({"short": {"测试博主": r}}, now("2026-09-10 09:00"))["short"]
    assert out == {}, f"门②失效：spec={bad_spec} 混进超短卡 {out}"
print("[PASS] 门② 超短只认 today/t1：t2/t5/nweek/month 一律不上超短卡")

# 未归一的 nweek_first（周一发帖真·下周，B3 兜底路径之外的手工行）→ 同样被门② 拦
r = {"blogger": "测试博主", "post_id": "P1", "has_view": True, "stance": "多",
     "horizon": "明天", "spec": "nweek_first", "summary": "s", "quote": "q",
     "quote_ts": ts("2026-09-07 09:30")}
assert S.resolve_anchors({"short": {"测试博主": r}}, now("2026-09-07 10:00"))["short"] == {}, \
    "门②失效：未归一的 nweek_first 混进超短卡（坍缩侧应已归一为 t1，此处为防御）"
print("[PASS] 门② 防御：未归一的 nweek_first 也上不了超短卡（坍缩侧归一 t1 是主路径）")

# ── ② 行头标注：终点 + spec ──────────────────────────────────────────────────
SHORT_ROW = {"blogger": "测试博主", "post_id": "P1", "has_view": True, "stance": "多",
             "horizon": "明天", "spec": "t1", "summary": "明天看多", "quote": "明天看多",
             "quote_ts": ts("2026-09-09 20:00"), "anchor": "09-10",
             "endpoint": date(2026, 9, 10)}
line1 = R._fmt_board_row("测试博主", SHORT_ROW).split("\n")[0]
assert line1 == "🔴 **测试博主** 看多 · 明天(09-10) · 终点 09-10 收盘 · spec t1", line1
print(f"[PASS] 行头标注（超短）：{line1}")

SWING_ROW = {"blogger": "智由智哉", "post_id": "P2", "has_view": True, "stance": "多",
             "horizon": "下周", "spec": "nweek", "summary": "先抑后扬，整体看多",
             "quote": "下周先抑后扬，整体看多", "quote_ts": ts("2026-09-06 11:29"),
             "anchor": "下周 09-14~09-18", "endpoint": date(2026, 9, 18)}
line1 = R._fmt_board_row("智由智哉", SWING_ROW).split("\n")[0]
assert line1 == "🔴 **智由智哉** 看多 · 下周 09-14~09-18 · 终点 09-18 收盘 · spec nweek", line1
print(f"[PASS] 行头标注（波段，用户案例）：{line1}")

# 无终点（long / 无 anchor 的历史行）→ 只给 spec，不编造终点
NO_EP = {"blogger": "测试博主", "has_view": True, "stance": "空", "horizon": "未提",
         "spec": "t5", "summary": "s", "quote": "q", "quote_ts": ts("2026-09-07 09:30")}
line1 = R._fmt_board_row("测试博主", NO_EP).split("\n")[0]
assert line1 == "🟢 **测试博主** 看空 · 周期未提 · spec t5", line1
NO_SPEC = dict(NO_EP); NO_SPEC.pop("spec")
line1 = R._fmt_board_row("测试博主", NO_SPEC).split("\n")[0]
assert line1 == "🟢 **测试博主** 看空 · 周期未提", line1
print("[PASS] 行头标注降级：无终点省去终点段 / 无 spec 省去 spec 段（绝不编造）")

# ── ② 总结快照带终点（LLM 可照抄、不自行推算）─────────────────────────────────
snap_src = open(os.path.join(BRIEFING, "scripts", "summarize.py"), encoding="utf-8").read()
assert 'ep_txt = f"·终点 {ep:%m-%d} 收盘" if ep else ""' in snap_src, "总结快照未带终点"
for pname in ("SHORT_SUMMARY_SYSTEM_PROMPT", "SWING_SUMMARY_SYSTEM_PROMPT"):
    p = getattr(S, pname)
    assert "验证终点" in p and "禁止自行推算" in p, f"{pname} 未写终点引用纪律"
print("[PASS] 总结侧：快照行带终点 + 两个总结 prompt 允许引用/禁止推算")

print("\n全部推送时效门回归通过 ✅")
