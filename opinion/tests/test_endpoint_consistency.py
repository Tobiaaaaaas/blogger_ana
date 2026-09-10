# -*- coding: utf-8 -*-
"""验证终点（endpoint_of）三份实现一致性回归（2026-09-10 新增）。

背景：spec → 验证终点日 的推算全仓有**三份实现**，无法合并（依赖方向/boot 方式不同）：

  | 实现 | 位置 | 形态 | 谁在用 |
  |---|---|---|---|
  | canonical | `scripts/eval/run_direction.py:endpoint_of` | 返回 `'YYYY-MM-DD'` 字符串 | 打分引擎（报告链） |
  | mirror    | `research/trading_cal.py:endpoint_of`     | 返回 `date`            | research 语料/回测 |
  | push      | `briefing/scripts/endpoint.py:endpoint_of` | 返回 `date`            | 推送卡（终点标注 + 过期门） |

`scripts/eval/` 无 `__init__.py`（不可包导入）、`briefing/` 也不该反向依赖打分引擎 →
三份实现并存是既成事实。本测试用**全网格三方比对**把它们钉死：任何一份改了语义，
这里立刻红。新增/修改任何一份时**必须同步另两份**。

比对规则（重要——三个日历的**边界**本来就不同，不是语义分歧）：
1. `research == push`：两者的交易日历都**向前无上限**（不依赖行情数据末日）→ 全网格必须相等；
2. `push` 的终点**落在行情覆盖内**（非 None 且 ≤ `CAL` 末日）→ `canonical` 必须给出**同一个**终点；
3. `push` 的终点**越过行情覆盖边界**（None 或 > `CAL` 末日）→ canonical 的取值不作判：
   它可能 None（`next_td` 走到 `CAL` 尽头），也可能**截断**（如 08-24 问 `nmonth`，
   行情只覆盖到 09-04 → 它答 09-04 而非真值 09-30）。这是行情数据新鲜度问题，
   不是三份实现的语义分歧（补行情后本分支自动收窄）。

**已知语义分歧 1 处（2026-09-10 发现，push 已修、canonical/mirror 未修）**：
`周六/周日 × nweek`。canonical/mirror 写作 `pub + 7 天` 再取 ISO 周，而 ISO 周是
**周一~周日**——周六/日 +7 天仍落在**同一个** ISO 周内，"下周"因此永不前进，与其自身的
`week`（会顺延到下一交易日）撞成同一天（09-06 周日：week 与 nweek **同为** 09-11）。
push 侧改用 `calendar.blogger_week_monday(pub) + 7 天`，与推送卡锚定展示同一口径
（否则卡面自相矛盾："下周 09-14~09-18 · 终点 09-11 收盘"，且过期门提前一周剔除该行）。
本测试**枚举**这一处分歧（`_KNOWN_DIVERGENT`，非模式豁免）：分歧格断言 push 的正确值 +
canonical/mirror 的现状值，并**钉住撞车现象**——canonical/mirror 一旦修正，本文件立刻红，
提示撤销豁免并三份归一。

注意：import run_direction 会装载行情（market_data + intraday），与报告重渲同环境。
直接 python3 运行。
"""
import importlib.util
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "briefing"))

# canonical（打分引擎；importlib，非包路径）
_spec = importlib.util.spec_from_file_location(
    "run_direction", os.path.join(ROOT, "scripts", "eval", "run_direction.py"))
eng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eng)

from research import trading_cal as TC            # noqa: E402  mirror
import scripts.endpoint as EP                     # noqa: E402  push（briefing/scripts/endpoint.py）

CAL_LAST = date.fromisoformat(eng.CAL[-1])        # 行情数据最新交易日（canonical 的日历上限）

import scripts.calendar as CALMOD                 # noqa: E402  博主视角周（push 与锚定共用）


def _known_divergent(pub, spec):
    """canonical/mirror 与 push 的**已知语义分歧**格：仅「周六/周日 × nweek」（见文件头）。"""
    return spec == "nweek" and pub.weekday() >= 5

SPECS = ["today", "t1", "t2", "t5", "t30", "week", "nweek", "nweek_first",
         "month", "nmonth", "d:2026-09-18", "d:2026-10-12", "long"]
# 网格：覆盖整周（周一~周日）× 节假日（中秋 09-25~09-27）× 月末月初 × 跨月
GRID_START, GRID_END = date(2026, 8, 24), date(2026, 10, 16)


def _canon(pub, spec):
    """canonical → date|None；畸形 spec 抛错时原样抛出（供断言）。"""
    r = eng.endpoint_of(pub.isoformat(), spec)
    return date.fromisoformat(r) if r else None


def _research(pub, spec):
    return TC.endpoint_of(pub, spec)


def _push(pub, spec):
    return EP.endpoint_of(pub, spec)


n = 0
won = 0          # canonical 给值（三方必须全等）的组数
cov = 0          # canonical 为 None 但被行情覆盖解释掉的组数
div = 0          # 已知分歧格（周六/日 × nweek）组数
pub = GRID_START
while pub <= GRID_END:
    for spec in SPECS:
        n += 1
        r, p = _research(pub, spec), _push(pub, spec)
        if _known_divergent(pub, spec):
            div += 1
            # 分歧格：push 取博主视角周 +1 周的最后交易日。用**未分歧的 week 分支**独立求期望值
            # （week 在周一不触发分歧），构成非循环校验。
            want = _push(CALMOD.blogger_week_monday(pub) + timedelta(days=7), "week")
            assert p == want, (f"[push nweek] {pub} {spec}：push={p} 期望 {want}"
                               "（= 博主视角周 +1 周的最后交易日，与卡面 anchor 同口径）")
            assert p > _push(pub, "week"), \
                f"{pub}：博主视角「下周」终点 {p} 必须晚于「本周」终点 {_push(pub, 'week')}"
            assert r == _push(pub, "week"), \
                (f"canonical/mirror 的周末 nweek 似乎已修（{pub}：research={r} 不再等于其 week "
                 f"{_push(pub, 'week')}）→ 请同步三份实现并撤销 _known_divergent 豁免")
            continue
        assert r == p, (f"[mirror≠push] {pub} {spec}：research={r} push={p}"
                        "—— 两份无上限日历必须逐格相等，改一份就要同步另一份")
        if p is not None and p <= CAL_LAST:
            # 终点在行情覆盖内 → 该周期完整可判 → canonical 必须给同一个终点
            won += 1
            c = _canon(pub, spec)
            assert c == p, (f"[canonical≠push] {pub} {spec}：canonical={c} push={p} "
                            f"（终点 {p} 在行情覆盖内 {CAL_LAST}，属真语义分歧）")
        else:
            cov += 1   # 周期越过行情覆盖边界 → canonical 的 None/截断值不作判（见文件头规则 3）
    pub += timedelta(days=1)

print(f"[PASS] 验证终点三方一致：网格 {n} 组 —— 除 {div} 组已知分歧格（周六/日 × nweek，"
      f"push 已修 / canonical·mirror 未修）外 research==push 全等；其中 {won} 组终点落在"
      f"行情覆盖内（≤{CAL_LAST}）且 canonical 同值；{cov} 组越过覆盖边界（canonical 的"
      f"None/截断不作判，属行情新鲜度）")

# ── 钉住 canonical/mirror 的周末 nweek 撞车（已知缺陷，未修）：修正后本段会红，提示归一 ──
# 08-29 周六 / 08-30 周日落在 canonical 行情覆盖内（CAL 至 09-04），可直接探其现状。
for pub in (date(2026, 8, 29), date(2026, 8, 30), date(2026, 9, 5), date(2026, 9, 6)):
    assert _research(pub, "week") == _research(pub, "nweek"), \
        (f"mirror 的 {pub} 「本周」与「下周」不再撞车 → 缺陷似已修，"
         "请同步 canonical 并撤销 _known_divergent 豁免")
for pub in (date(2026, 8, 29), date(2026, 8, 30)):
    assert _canon(pub, "week") == _canon(pub, "nweek"), \
        f"canonical 的 {pub} 「本周」与「下周」不再撞车 → 缺陷似已修，请同步三份实现"
print("[PASS] canonical/mirror 的周末 nweek 撞车现象已钉住（本周==下周，属缺陷；push 侧已修正）")

# ── spec 语义的定点断言（防"三份一起改错"）：与 SKILL §3 / 打分引擎口径逐条对齐 ──
# 09-04 是周五；09-07 周一、09-11 周五、09-14 周一、09-18 周五、09-30 周三（09-25~09-27 中秋休）
FRI, SAT, SUN, MON = date(2026, 9, 4), date(2026, 9, 5), date(2026, 9, 6), date(2026, 9, 7)
cases = [
    (FRI, "today", FRI),                    # 交易日"今天" = 当天收盘
    (SAT, "today", MON),                    # 非交易日"今天" 顺延下一交易日
    (FRI, "t1", MON),                       # 明天 = 下一交易日（跨周末）
    (SUN, "t1", MON),
    (MON, "t5", date(2026, 9, 14)),         # 发帖后第 5 个交易日
    (MON, "week", date(2026, 9, 11)),       # 本周最后交易日（周五）
    (SAT, "week", date(2026, 9, 11)),       # 周末"本周" → 下一交易周最后交易日
    (MON, "nweek", date(2026, 9, 18)),      # 周一"下周" = 09-14~09-18 最后交易日
    (FRI, "nweek", date(2026, 9, 11)),      # 周五"下周" = 09-07~09-11（周五与 canonical 同值）
    (SUN, "nweek", date(2026, 9, 18)),      # ★ 周日"下周" = 博主视角周 +1 周（canonical 误答 09-11）
    (SUN, "nweek_first", MON),              # ★ 周末"下周一" = 发帖后首个交易日（=t1，同值）
    (MON, "nweek_first", date(2026, 9, 14)),  # 周一"下周一" 隔一个整周（≠t1）
    (MON, "month", date(2026, 9, 30)),
    (MON, "nmonth", date(2026, 10, 30)),
    (MON, "long", None),
    (MON, "d:2026-09-19", date(2026, 9, 21)),  # 具体日期落在周六 → 顺延至下一交易日
]
for pub, spec, want in cases:
    got = _push(pub, spec)
    assert got == want, f"push endpoint_of({pub}, {spec!r}) = {got}，期望 {want}"
    if not _known_divergent(pub, spec):        # 分歧格另在下方单列（mirror 现状不同）
        assert _research(pub, spec) == want, f"research mirror 语义漂移：{pub} {spec!r}"
print(f"[PASS] 验证终点语义定点 {len(cases)} 条（含周末「下周一」=t1 与 交易日「下周一」=nweek_first 的分叉）")

# ── 2026-09-10 编码纠正的直接校验：「下周一」是否落在 t1 与 nweek_first 的分界上 ──
for pub in (FRI, SAT, SUN):
    assert _push(pub, "nweek_first") == _push(pub, "t1"), \
        f"{pub}（周五~周日）说「下周一」：nweek_first 与 t1 必须同终点（都是发帖后首个交易日）"
print("[PASS] 周五/周六/周日「下周一」：nweek_first 与 t1 终点等价（编码分叉的依据成立）")
for pub in (MON, date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)):
    assert _push(pub, "nweek_first") != _push(pub, "t1"), \
        f"{pub}（周一~周四）说「下周一」：终点必须 ≠ t1（隔着一个整周，仍是波段）"
print("[PASS] 周一~周四「下周一」：终点 ≠ t1（仍属 nweek_first/波段）")

# ── endpoint_dt：终点时刻 = 终点日 15:00 收盘（过期门判据） ──
dt = EP.endpoint_dt(MON, "t1")
assert dt.date() == date(2026, 9, 8) and (dt.hour, dt.minute) == (15, 0), dt
assert dt.utcoffset() == timedelta(hours=8), dt
assert EP.endpoint_dt(MON, "long") is None
print("[PASS] endpoint_dt：终点日 15:00 北京时；long 无终点 → None")

print("\n全部验证终点一致性回归通过 ✅")
