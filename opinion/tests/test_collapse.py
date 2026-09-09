# -*- coding: utf-8 -*-
"""collapse_board 确定性坍缩回归（C1–C8，纯逻辑单测、不调 API）。

v17 把 v16 LAYER prompt 的「窗口判层/路过/取最新/quote 归属」散文坍缩进 opinion.annotate.
collapse_board。本套用例迁移 /tmp/test_layers.py 的合成语义，用**固定规范行**直测坍缩：
- C1 纯明天→swing 无行（只到明天永不作波段）
- C2 混合两层 quote 各归各层
- C3 转述不认（无合格行 → 无观点）
- C4 最新纯明天 + 更早波段 → swing 取更早行
- C5 最新复盘路过 → swing 不抹 09-07 本周行
- C6 最新状态路过 → short 不抹 09-07 明天行
- C7 长句明天 quote 保时间词
- C8 09-08 12:00 窄幅震荡路过 → short 仍引 09-07 明天空（子房回归）

行 = to_canonical 输出形状（规范行），post 构造与测试帖同构。直接 python3 运行。
"""
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from opinion import annotate as ann
from opinion import schema as sch

BJ = timezone(timedelta(hours=8))
CARD_DAY = "2026-09-08 09:30"          # 卡片日 09-08 周二，前一交易日 09-07
SHORT_START = "2026-09-07 00:00"        # 超短窗 = 前一交易日 00:00
SWING_START = "2026-08-31 00:00"        # 波段窗 ≈ 前 5 交易日


def ep(s):
    return int(datetime(*map(int, s.split(" ")[0].split("-")),
                        *map(int, s.split(" ")[1].split(":")), tzinfo=BJ).timestamp())


def post(pid, ts, title, content):
    return {"post_id": str(pid), "publish_time": ep(ts), "publish_date": ts,
            "title": title, "content": content}


def canon(post, model):
    """模型行 + 帖 → to_canonical 规范行（系统回填身份/时间）。"""
    row = ann.to_canonical(model, post, "测试博主", 0)
    assert row is not None, f"to_canonical 拒绝行: {model!r}"
    return row


def _win_start(board):
    return ep(SHORT_START) if board == "short" else ep(SWING_START)


def col(board, rows, ws=None):
    return ann.collapse_board(board, "测试博主", rows,
                              window_start=_win_start(board) if ws is None else ws)


def check(name, got, want_key, note=""):
    ok = got is not None and got.get("has_view") and got["horizon"] == want_key
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}: horizon={got.get('horizon') if got else None} "
          f"(want {want_key})  quote_ts={got.get('quote_ts') if got else None}  {note}")
    return ok


# ── C1：纯明天 → swing 无行 ───────────────────────────────────────────────
_p1 = post(101, "2026-09-07 16:26", "明天大盘走势前瞻",
           "明天大盘冲高回落概率大，沪指3900-3950来回磨，仓位重的可逢高减一点。")
_r1 = canon(_p1, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                  "horizon": "明天", "quote": "明天大盘冲高回落概率大，沪指3900-3950来回磨",
                  "summary": "明天大盘冲高回落概率大"})
assert col("short", [_r1]) is not None and col("short", [_r1])["horizon"] == "明天"
assert col("swing", [_r1]) is None, "C1: 只到明天 永不作波段行"
print("[PASS] C1 纯明天：short=明天 有行；swing=None")

# ── C2：混合两层 quote 各归各层 ───────────────────────────────────────────
_p2 = post(201, "2026-09-07 21:40", "短线与波段",
           "明天先回踩3900不破再看企稳；本周守住3850就是波段底。")
_r2a = canon(_p2, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                   "horizon": "明天", "quote": "明天先回踩3900不破再看企稳",
                   "summary": "明天先回踩3900"})
_r2b = canon(_p2, {"d": 1, "s": 1, "idx": "上证指数", "spec": "week", "cat": "scored",
                   "horizon": "本周", "quote": "本周守住3850就是波段底",
                   "summary": "本周守住3850就是波段底"})
s2 = col("short", [_r2a, _r2b])
w2 = col("swing", [_r2a, _r2b])
assert s2 and s2["horizon"] == "明天" and s2["quote"].startswith("明天"), s2
assert w2 and w2["horizon"] == "本周" and w2["quote"].startswith("本周"), w2
print("[PASS] C2 混合两层：short=明天 / swing=本周，quote 各引各层")

# ── C3：纯转述不认 → 无合格行 → 无观点 ─────────────────────────────────────
assert col("swing", []) is None
assert col("short", []) is None
# 转述若被模型误抽为行，但 d/spec 非法 → to_canonical 拒 → 无行 → 无观点
_p3 = post(301, "2026-09-07 20:10", "机构观点汇总",
           "券商普遍觉得9月上半月还是震荡磨底，先稳一稳再谈方向。")
assert ann.to_canonical({"d": 0, "spec": "t1", "summary": "转述"}, _p3, "测试博主", 0) is None
assert ann.to_canonical({"d": -1, "spec": "??", "summary": "x"}, _p3, "测试博主", 0) is None
print("[PASS] C3 转述不认：无合格行 → swing/short 均无观点；非法行被拒")

# ── C4：最新纯明天 + 更早真波段 → swing 取更早行 ────────────────────────────
_p4new = post(401, "2026-09-07 16:26", "明天大盘走势前瞻",
              "明天大盘冲高回落概率大，沪指3900-3950来回磨，仓位重的可逢高减。")
_p4old = post(402, "2026-09-04 22:07", "周线展望",
              "下周一沪指3900是多空分水岭，若跌破可能要探3880，注意节奏。")
_r4a = canon(_p4new, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                      "horizon": "明天", "quote": "明天大盘冲高回落概率大",
                      "summary": "明天大盘冲高回落概率大"})
_r4b = canon(_p4old, {"d": 1, "s": 1, "idx": "上证指数", "spec": "nweek", "cat": "scored",
                      "horizon": "下周", "quote": "下周一沪指3900是多空分水岭",
                      "summary": "下周一沪指3900是多空分水岭"})
rows4 = [_r4a, _r4b]  # 新→旧
s4 = col("short", rows4)
w4 = col("swing", rows4)
assert s4 and s4["quote_ts"] == ep("2026-09-07 16:26"), "short 应取最新明天帖"
assert w4 and w4["quote_ts"] == ep("2026-09-04 22:07") and w4["horizon"] == "下周", \
    "swing 应取更早 09-04 下周行"
print("[PASS] C4 最新明天+更早波段：short=09-07 / swing=09-04(下周)")

# ── C5：最新复盘路过 → swing 不抹 09-07 本周行 ──────────────────────────────
_p5recent = post(501, "2026-09-08 11:07", "盘中",
                 "昨天科技比大盘强，今天角色互换，明天又会互换，精彩的应该在周四以后。")
_p5old = post(502, "2026-09-07 12:24", "午评", "上证本周低位在3910-3880之间。")
# 09-08 盘中是复盘/日内推演，无合格波段行；只有 09-07 本周行
_r5 = canon(_p5old, {"d": 1, "s": 1, "idx": "上证指数", "spec": "week", "cat": "scored",
                     "horizon": "本周", "quote": "上证本周低位在3910-3880之间",
                     "summary": "上证本周低位在3910-3880之间"})
w5 = col("swing", [_r5])
assert w5 and w5["quote_ts"] == ep("2026-09-07 12:24") and w5["horizon"] == "本周", w5
print("[PASS] C5 最新复盘路过：swing 仍取 09-07 本周行（路过不抹旧行）")

# ── C6：最新状态路过 → short 不抹 09-07 明天行 ──────────────────────────────
_p6recent = post(601, "2026-09-08 10:30", "盘中",
                 "早盘没什么风险，指数按预期走，先看着。")
_p6old = post(602, "2026-09-07 19:53", "晚间",
              "明天是检验抛压的关键一天，防冲高回落。")
_r6 = canon(_p6old, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                     "horizon": "明天", "quote": "明天是检验抛压的关键一天",
                     "summary": "明天是检验抛压的关键一天"})
s6 = col("short", [_r6])
assert s6 and s6["quote_ts"] == ep("2026-09-07 19:53") and s6["horizon"] == "明天", s6
print("[PASS] C6 最新状态路过：short 仍取 09-07 明天行")

# ── C7：长句明天 quote 保时间词（quote 从载时间承诺句头截）───────────────────
_p7 = post(701, "2026-09-07 16:26", "明天大盘走势前瞻",
           "明天（9月8日周二）大盘大概率高开晃悠、板块轮动快，沪指就在3900到3950点之间来回磨。")
_r7 = canon(_p7, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                  "horizon": "明天",
                  "quote": "明天（9月8日周二）大盘大概率高开晃悠、板块轮动快，沪指3900-3950点之间来回磨…"
                           "两种可能走势：大概率震荡偏强，要防一手冲高回落",
                  "summary": "明天大盘大概率高开晃悠，沪指3900到3950点来回磨"})
s7 = col("short", [_r7])
assert s7 and s7["quote"].startswith("明天"), f"quote 应保留时间词: {s7['quote']!r}"
assert len(s7["quote"]) <= 60, f"quote 应 ≤60: {s7['quote']}"
print(f"[PASS] C7 长句明天：quote 保时间词且 ≤60  → {s7['quote']!r}")

# ── C8：09-08 12:00 窄幅震荡路过 → short 非 null、引 09-07（子房回归）──────
_p8recent = post(801, "2026-09-08 12:00", "午间",
                 "指数窄幅震荡，上下空间都不大，等方向明朗再说。")
_p8old = post(802, "2026-09-07 21:10", "收盘梳理",
              "明天重点看量能能不能跟上，放不出量就防冲高回落，谨慎为主。")
_r8 = canon(_p8old, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                     "horizon": "明天", "quote": "明天重点看量能能不能跟上",
                     "summary": "明天重点看量能"})
s8 = col("short", [_r8])
assert s8 is not None, "C8: 最新窄幅震荡路过 → short 不可判无观点"
assert s8["quote_ts"] == ep("2026-09-07 21:10") and s8["horizon"] == "明天", s8
# 反向证伪：若 12:00 帖被误抽成 horizon=今天 行且窗内合法 → 会覆盖（模型纪律问题，非坍缩）
_r8_wrong = canon(_p8recent, {"d": 1, "s": 1, "idx": "上证指数", "spec": "today",
                              "cat": "scored", "horizon": "今天",
                              "quote": "今天窄幅震荡", "summary": "今天窄幅震荡"})
s8w = col("short", [_r8, _r8_wrong])
assert s8w is not None and s8w["quote_ts"] == ep("2026-09-08 12:00"), s8w
print("[PASS] C8 09-08 窄幅震荡路过：short=09-07 明天 非 null；误抽 今天 行才覆盖")

# ── 同帖同层多行 → 目标日更近优先 ──────────────────────────────────────────
_pm = post(901, "2026-09-07 20:00", "波段观点",
           "这波守住3850本周就是底部区域；下月还有上行空间但先看本周能不能站稳。")
_rm_near = canon(_pm, {"d": 1, "s": 1, "idx": "上证指数", "spec": "week", "cat": "scored",
                       "horizon": "本周", "quote": "这波守住3850本周就是底部区域",
                       "summary": "这波守住3850本周就是底部区域"})
_rm_far = canon(_pm, {"d": 1, "s": 1, "idx": "上证指数", "spec": "month", "cat": "scored",
                      "horizon": "更长", "quote": "下月还有上行空间",
                      "summary": "下月还有上行空间"})
wm = col("swing", [_rm_near, _rm_far])
assert wm and wm["horizon"] == "本周", f"同帖同层更近目标(本周)应优先于更长: {wm}"
print(f"[PASS] 同帖同层多行：更近(本周 rank1)优先于更长(rank3)  → {wm['horizon']}")

# horizon 与 spec 不自洽 → 弃行（不静默），其余合格行照常坍缩
_bad = {"blogger": "测试博主", "horizon": "更长", "spec": "t1", "cat": "scored",
        "quote_ts": ep("2026-09-07 20:00"), "d": 1, "s": 1, "summary": "不自洽行"}
_wm = col("swing", [_rm_far, _bad])
assert _wm is not None and _wm["horizon"] == "更长" and _wm["quote"] == "下月还有上行空间", _wm
print("[PASS] horizon=更长 与 spec=t1 不自洽行被弃，合格行照常坍缩")

# ── C9：idx 门——创业板/科创50/上证50/双创 行（即便周期合法）一律不进卡 ──────
_p9 = post(911, "2026-09-07 20:30", "创业板", "创业板明天若是再破3400就要小心了。")
_r9_gem = canon(_p9, {"d": -1, "s": 1, "idx": "创业板指", "spec": "t1", "cat": "scored",
                      "horizon": "明天", "quote": "创业板明天若是再破3400就要小心了",
                      "summary": "创业板明天再破3400看空"})
assert col("short", [_r9_gem]) is None, "C9: idx=创业板指+明天 → short 应无行"
assert col("swing", [_r9_gem]) is None, "C9: idx=创业板指+明天 → swing 应无行"
_p9b = post(912, "2026-09-07 20:35", "科创板", "科创50下周有望站上1550。")
_r9_kc = canon(_p9b, {"d": 1, "s": 1, "idx": "科创50", "spec": "week", "cat": "scored",
                      "horizon": "本周", "quote": "科创50下周有望站上1550",
                      "summary": "科创50下周看多"})
assert col("swing", [_r9_kc]) is None, "C9: idx=科创50+本周 → swing 应无行"
print("[PASS] C9 idx 门：创业板指(明天)/科创50(本周) 行不进 short/swing")

# ── C10：混合博主 上证行 + 创业板行并存 → 只取上证 ──────────────────────────
_p10 = post(921, "2026-09-07 21:00", "两手抓",
            "上证明天冲高回落概率大；创业板那边看3400支撑，破位就麻烦。")
_r10_sh = canon(_p10, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                       "horizon": "明天", "quote": "上证明天冲高回落概率大",
                       "summary": "上证明天冲高回落"})
_r10_gem = canon(_p10, {"d": 1, "s": 1, "idx": "创业板指", "spec": "t1", "cat": "scored",
                        "horizon": "明天", "quote": "创业板那边看3400支撑破位麻烦",
                        "summary": "创业板看3400支撑"})
s10 = col("short", [_r10_sh, _r10_gem])
assert s10 is not None and s10["horizon"] == "明天", s10
assert "上证" in s10["quote"] and "3400" not in s10["quote"], \
    f"C10: short 只取上证行、quote 不得混入创业板触发: {s10}"
# 反转：只剩创业板行 → 该博主 short 无观点（上证卡不显示他）
assert col("short", [_r10_gem]) is None, "C10: 只余创业板行 → short 无观点"
print("[PASS] C10 混合博主：short 只取上证行；仅创业板行时不上卡")

# ── C11：上证行缺 idx 键 / 异常 None → 兜底按上证放行（to_canonical 已默认填）──
_r11 = {"blogger": "测试博主", "horizon": "明天", "spec": "t1", "cat": "scored",
        "quote_ts": ep("2026-09-07 21:00"), "d": 1, "s": 1, "summary": "上证兜底行",
        "quote": "明天看涨"}
s11 = col("short", [_r11])
assert s11 is not None and s11["horizon"] == "明天", "C11: 无 idx 键行按上证放行（兼容旧缓存）"
print("[PASS] C11 无 idx 键行兜底上证放行")

# ── 交易日相对再分类（2026-09-09）──
# 用户裁决：超短 = 当天或下一个交易日。周五~周日发帖的 nweek_first（下周一/下周首个交易日）
# 目标 == 发帖后首个交易日 → 行降级 short（预测周期=1）；nweek（整周）/周一~周四的 nweek_first 不降级。
# stub 日历：无节假日，跳过周末即可。


class _StubCal:
    """next_trading_day(d)：d 之后首个工作日（2026-09 无节假日）。"""

    @staticmethod
    def next_trading_day(d):
        cur = d + timedelta(days=1)
        while cur.weekday() >= 5:
            cur += timedelta(days=1)
        return cur


_STUB = _StubCal()
# 09-04=周五, 09-05=周六, 09-07=周一, 09-08=周二（对齐卡片日 09-08）


def ccol(board, rows, ws=None, cal=_STUB):
    return ann.collapse_board(board, "测试博主", rows,
                              window_start=None if ws is None else ws, cal=cal)


# C12：周五(09-04)发帖 spec=nweek_first horizon=下周 → 降级 short、swing 无行
_p12 = post(1201, "2026-09-04 22:07", "周一前瞻",
            "下周一沪指3900是多空分水岭，守住还有反弹，破位则下探3880。")
_r12 = canon(_p12, {"d": 1, "s": 1, "idx": "上证指数", "spec": "nweek_first", "cat": "scored",
                    "horizon": "下周", "quote": "下周一沪指3900是多空分水岭",
                    "summary": "下周一守住3900看反弹破位看3880"})
s12 = ccol("short", [_r12], ws=None)
w12 = ccol("swing", [_r12], ws=None)
assert s12 is not None and s12["horizon"] == "明天", \
    f"C12: 周五下周一=nweek_first 应降级 short 且归一明天: {s12}"
assert w12 is None, "C12: 周五下周一=nweek_first → swing 应无行"
print("[PASS] C12 周五 nweek_first：降级 short(明天)、swing 无行")

# C13：周一(09-07)发帖 spec=nweek_first horizon=下周（真·下周一周=隔 7 日）→ 仍 swing
_p13 = post(1301, "2026-09-07 21:00", "下周展望",
            "下周一（9月14日）若放量突破3950则打开上行空间。")
_r13 = canon(_p13, {"d": 1, "s": 1, "idx": "上证指数", "spec": "nweek_first", "cat": "scored",
                    "horizon": "下周", "quote": "下周一若放量突破3950则打开上行空间",
                    "summary": "下周一看涨"})
assert ccol("swing", [_r13], ws=None) is not None, "C13: 周一 nweek_first(隔7日) 应留 swing"
assert ccol("short", [_r13], ws=None) is None, "C13: 周一 nweek_first 不进 short"
print("[PASS] C13 周一 nweek_first：留 swing、不进 short（目标隔 7 日）")

# C14：周五发帖 spec=nweek horizon=下周（整周观点）→ 不降级，留 swing
_p14 = post(1401, "2026-09-04 17:46", "下周破位",
            "宣告下周的破位大跌已经箭在弦上，注意风险。")
_r14 = canon(_p14, {"d": -1, "s": 1, "idx": "上证指数", "spec": "nweek", "cat": "scored",
                    "horizon": "下周", "quote": "宣告下周的破位大跌已经箭在弦上",
                    "summary": "下周破位大跌"})
assert ccol("swing", [_r14], ws=None) is not None, "C14: nweek 整周观点不降级 → swing 有行"
assert ccol("short", [_r14], ws=None) is None, "C14: nweek 整周观点不进 short"
print("[PASS] C14 周五 nweek 整周观点：留 swing、不进 short（不误伤下周破位句）")

# C15：cal=None（旧调用/报告侧）→ 原行为保留：周五 nweek_first 仍 swing 上卡、short 无
assert ccol("swing", [_r12], ws=None, cal=None) is not None, "C15: cal=None 旧行为 swing 上卡"
assert ccol("short", [_r12], ws=None, cal=None) is None, "C15: cal=None 旧行为 short 无行"
print("[PASS] C15 cal=None 回退：nweek_first 按字面词判层（swing 上卡）")

# ── 主结论对象门（2026-09-09 衡山/诸葛复盘）──
# 渲染底限：idx=上证 但摘要点名他指且全文无上证指向的自相矛盾行永不上上证卡（主结论对象不是
# 上证）。矛盾 = 标注指错，恢复在上游（annotate 对象门 + extract_layers 缓存自愈，见各自测试）；
# 本层只测：矛盾行绝不渲染上卡（C16/C17）、带上证别称的合法行不受误伤（C18）、conflict_rows
# 对 idx=科创50 的自洽行不误报（下面直测）。


def conflict_of(s, q):
    return ann._idx_object_conflict({"summary": s, "quote": q})


# C16：衡山形——idx=上证 摘要"看空科创50，等待下探年线" 无上证指向 → 弃推
_p16 = post(1601, "2026-09-08 18:20", "科创50", "耐心等待科创50下探年线和回补1495缺口吧。")
_r16 = canon(_p16, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t5", "cat": "scored",
                    "horizon": "近日", "quote": "耐心等待科创50下探年线和回补1495缺口吧",
                    "summary": "看空科创50，等待下探年线和回补1495缺口"})
assert conflict_of("看空科创50，等待下探年线和回补1495缺口",
                   "耐心等待科创50下探年线和回补1495缺口吧") == "科创50"
assert ccol("swing", [_r16], ws=None) is None, "C16: 上证idx+科创50主句 → swing 应无行"
assert ccol("short", [_r16], ws=None) is None, "C16: 上证idx+科创50主句 → short 应无行"
# C16 正向对照：同型行仅把主句对象换成上证 → 不被对象门误伤，swing 正常上卡
_r16ok = dict(_r16)
_r16ok["summary"] = "看空上证指数，等待下探年线"
_r16ok["quote"] = "耐心等待上证指数下探年线"
w16ok = ccol("swing", [_r16ok], ws=None)
assert w16ok is not None, f"C16 对照: 上证主句行不应被对象门拦: {w16ok}"
print("[PASS] C16 衡山形：idx=上证 但摘要点名科创50 无上证指向 → 两板弃推（上证主句对照放行）")

# C17：诸葛形——摘要"科创50若破位则看空"，引文不点名指数 → 弃推
_p17 = post(1701, "2026-09-08 15:07", "破位", "一旦破位，要设置好止损点位。中阴线跌破第一个低点，次日收不回来就要纠错了。")
_r17 = canon(_p17, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t5", "cat": "scored",
                    "horizon": "近日", "quote": "一旦破位，要设置好止损点位。中阴线跌破第一个低点",
                    "summary": "科创50若破位中阴线则看空，需止损纠错"})
assert conflict_of("科创50若破位中阴线则看空，需止损纠错",
                   "一旦破位，要设置好止损点位。") == "科创50"
assert ccol("swing", [_r17], ws=None) is None, "C17: 科创50破位看空摘要 → swing 应无行"
# C17 正向对照：破位对象换成上证 → 放行（只点"破位"不点名指数的行本来就是上证默认口径）
_r17ok = dict(_r17)
_r17ok["summary"] = "上证若破位中阴线则看空，需止损纠错"
w17ok = ccol("swing", [_r17ok], ws=None)
assert w17ok is not None, f"C17 对照: 上证破位主句行不应被对象门拦: {w17ok}"
print("[PASS] C17 诸葛形：科创50破位看空摘要 无上证指向 → 弃推（上证破位对照放行）")

# C18：合法——"科创50领跌拖累上证…" 带上证指向 → 不误伤，short 照常上卡
_p18 = post(1801, "2026-09-08 09:10", "盘中", "若科创50破位则拖累上证继续下探，上证明天走弱概率大。")
_r18 = canon(_p18, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                    "horizon": "明天", "quote": "若科创50破位则拖累上证继续下探",
                    "summary": "科创50领跌拖累上证明日走弱看空"})
assert conflict_of("科创50领跌拖累上证明日走弱看空", "若科创50破位则拖累上证继续下探") is None
s18 = ccol("short", [_r18], ws=None)
assert s18 is not None and s18["horizon"] == "明天", f"C18: 带上证指向不误伤: {s18}"
print("[PASS] C18 合法形：科创50作条件+上证为主句 → 不误伤，short 上卡")

# C19：conflict_rows 先滤 idx=上证——同文本标 idx=科创50 的自洽行不误报（他指行给报告侧）
assert ann.conflict_rows([_r16]) == [_r16], "conflict_rows 应命中 衡山形 矛盾行"
_r16idx = dict(_r16)
_r16idx["idx"] = "科创50"
assert ann.conflict_rows([_r16idx]) == [], "同文本 idx=科创50 的自洽行不得误报"
assert ann.conflict_rows([]) == [] and ann.conflict_rows(None) == []
print("[PASS] C19 conflict_rows：idx 过滤——上证矛盾行命中 / 科创50 自洽行不误报")

print("\n全部 collapse_board 回归通过 ✅")
