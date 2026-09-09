# -*- coding: utf-8 -*-
"""2026-09-09 A4 行为微调四件回归（纯逻辑、不调 API）。

- A4-1 Pillar C 降级行溯源：collapse_board 把周五 nweek_first 行降级 short、展示 horizon 归一
  「明天」后，summarize._origin_matches 精确 pass 不中、downgrade_ok pass 命中（否则交易日再
  分类新行逃复核）；真 t1 行仍精确命中、跨帖/跨时刻不误配；
- A4-2 schema.default_horizon("t5")=="未提"（此前空串 → collapse 静默弃行）；坍缩后无周期有
  方向行可上波段卡；t6 仍留空（仅报告口径）；
- A4-4 opinion.verify REVIEW_SYSTEM_PROMPT horizon 词表含「未提」。

直接 python3 运行。
"""
import os
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIEFING = os.path.join(ROOT, "briefing")
sys.path.insert(0, BRIEFING)          # scripts.summarize（包内相对 import）
sys.path.insert(0, ROOT)              # opinion.*

from opinion import annotate as ann        # noqa: E402
from opinion import schema as sch          # noqa: E402
from opinion import verify as ver          # noqa: E402
import scripts.summarize as S               # noqa: E402

BJ = timezone(timedelta(hours=8))


def ep(s):
    return int(datetime(*map(int, s.split(" ")[0].split("-")),
                        *map(int, s.split(" ")[1].split(":")), tzinfo=BJ).timestamp())


class _StubCal:
    """next_trading_day(d)：d 之后首个工作日（2026-09 无节假日）。"""

    @staticmethod
    def next_trading_day(d):
        cur = d + timedelta(days=1)
        while cur.weekday() >= 5:
            cur += timedelta(days=1)
        return cur


def post(pid, ts, content):
    return {"post_id": str(pid), "publish_time": ep(ts), "publish_date": ts,
            "title": "t", "content": content}


def canon(p, model):
    r = ann.to_canonical(model, p, "测试博主", 0)
    assert r is not None, f"to_canonical 拒绝: {model!r}"
    return r


# ── A4-1：降级行溯源豁免 ──
# 周五(09-04) nweek_first → 坍缩降级 short、展示 horizon 归一 明天（C12 语义）
_p = post(1201, "2026-09-04 22:07",
          "下周一沪指3900是多空分水岭，守住还有反弹，破位则下探3880。")
_r = canon(_p, {"d": 1, "s": 1, "idx": "上证指数", "spec": "nweek_first", "cat": "scored",
                "horizon": "下周", "quote": "下周一沪指3900是多空分水岭",
                "summary": "下周一沪指3900分水岭"})
disp = ann.collapse_board("short", "测试博主", [_r], cal=_StubCal())
assert disp and disp["horizon"] == "明天", disp        # 前提：降级归一发生
assert not S._origin_matches("short", disp, _r), "精确 pass 应不中（horizon 下周≠明天）"
assert S._origin_matches("short", disp, _r, downgrade_ok=True), "降级豁免应命中 nweek_first 源行"
assert not S._origin_matches("swing", disp, _r, downgrade_ok=True), "swing 板不适用降级豁免"
print("[PASS] A4-1 降级行溯源：精确不中 + downgrade_ok 命中（交易日再分类行不再逃复核）")

# 真 t1 行：精确命中；跨时刻/跨帖不误配
_p2 = post(2001, "2026-09-07 16:26", "明天大盘冲高回落概率大。")
_r2 = canon(_p2, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                  "horizon": "明天", "quote": "明天大盘冲高回落概率大",
                  "summary": "明天冲高回落概率大"})
disp2 = ann.collapse_board("short", "测试博主", [_r2], cal=_StubCal())
assert S._origin_matches("short", disp2, _r2), "真 t1 行应精确命中"
assert not S._origin_matches("short", disp2, _r), "跨帖不配（post_id 不同）"
_o = dict(_r2, quote_ts=_r2["quote_ts"] + 1)
assert not S._origin_matches("short", disp2, _o), "quote_ts 不同不配"
print("[PASS] A4-1 溯源：真 t1 精确命中；跨帖/quote_ts 不同不误配")

# ── A4-2：t5 兜底「未提」──
assert sch.default_horizon("t5") == "未提", sch.default_horizon("t5")
assert sch.default_horizon("t6") == "", "t6 无对应单值档仍留空"
assert sch.horizon_spec_ok("未提", "t5"), "未提↔t5 同档自洽"
_p3 = post(3001, "2026-09-07 22:10", "最近涨得差不多了，我减仓了，别追高。")
_r3 = canon(_p3, {"d": -1, "s": 1, "idx": "上证指数", "spec": "t5", "cat": "scored",
                  "summary": "涨差不多减仓"})       # 漏填 horizon → 兜底 未提
assert _r3["horizon"] == "未提", _r3
w3 = ann.collapse_board("swing", "测试博主", [_r3])  # 无时间词但方向落波段 → 上波段卡
assert w3 and w3["horizon"] == "未提" and w3["stance"] == "空", w3
print("[PASS] A4-2 t5 兜底未提：default_horizon('t5')=未提 → 裸减仓行可上波段卡（此前静默弃行）")

# ── A4-4：verify REVIEW 词表含「未提」──
assert "未提" in ver.REVIEW_SYSTEM_PROMPT and "更长/未提" in ver.REVIEW_SYSTEM_PROMPT
print("[PASS] A4-4 verify REVIEW horizon 词表含「未提」（与 swing 白名单同口径）")

print("\nA4 行为微调四件全部通过 ✅")
