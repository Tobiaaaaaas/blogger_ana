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

**周口径已于 2026-09-10 三份归一（无豁免格）**：此前 push 对周六/日 `nweek` 走
`blogger_week_monday(pub) + 7 天`（博主视角周，前瞻式），canonical/mirror 走 `pub + 7 天`，
两者靠 `_KNOWN_DIVERGENT` 豁免互不追究；同时 push 的 `week` 对非交易日顺延到下一交易日，
与 canonical/mirror 的 `pub+7` 取 ISO 周在周末**撞车**（09-06 周日：week 与 nweek 同为 09-11）。
现行三份统一为**纯自然周**：

    week         = 发帖日所在 ISO 周最后交易日      （非交易日不顺延）
    nweek        = 发帖日 +7 天所在 ISO 周最后交易日
    nweek_first  = 发帖日 +7 天所在 ISO 周首个交易日

周末帖的「回顾 vs 前瞻」之分**不在引擎而在判层**（前瞻即将到来的那一周 → `nweek`；
回顾刚结束的那一周 → 不产行，见 `opinion/prompts.py` §3）：误产的周末 `week` 行终点落在
发帖日之前，报告侧判 `无效-过时`、推送侧过期门剔除，不再被悄悄挪进下一周计分。
本文件因此**无任何分歧格**——`research == push` 必须全网格相等，canonical 在行情覆盖内
必须同值。

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
try:                      # Windows GBK 控制台：断言已全过，别让收尾 emoji 崩掉退出码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# canonical（打分引擎；importlib，非包路径）
_spec = importlib.util.spec_from_file_location(
    "run_direction", os.path.join(ROOT, "scripts", "eval", "run_direction.py"))
eng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eng)

from research import trading_cal as TC            # noqa: E402  mirror
import scripts.endpoint as EP                     # noqa: E402  push（briefing/scripts/endpoint.py）

CAL_LAST = date.fromisoformat(eng.CAL[-1])        # 行情数据最新交易日（canonical 的日历上限）

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
pub = GRID_START
while pub <= GRID_END:
    for spec in SPECS:
        n += 1
        r, p = _research(pub, spec), _push(pub, spec)
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

print(f"[PASS] 验证终点三方一致：网格 {n} 组 —— research==push **全等（无豁免格）**；其中 "
      f"{won} 组终点落在行情覆盖内（≤{CAL_LAST}）且 canonical 同值；{cov} 组越过覆盖边界"
      f"（canonical 的 None/截断不作判，属行情新鲜度）")

# ── 周口径归一后的不变式：本周/下周在周末不再撞车，且"下周"恒晚于"本周"（2026-09-10）──
for pub in (date(2026, 8, 29), date(2026, 8, 30), date(2026, 9, 5), date(2026, 9, 6),
            date(2026, 9, 7), date(2026, 9, 11)):
    w, nw = _push(pub, "week"), _push(pub, "nweek")
    assert w != nw, f"{pub}（周{pub.weekday()+1}）：「本周」与「下周」终点撞车（均为 {w}）"
    assert nw > w, f"{pub}：「下周」终点 {nw} 必须晚于「本周」终点 {w}"
    # 周末/节假日发帖的「本周」终点必落在发帖日之前 → 报告侧判"无效-过时"、推送侧过期门剔除
    if pub.weekday() >= 5:
        assert w < pub, f"{pub}（周末）发「本周」终点 {w} 应早于发帖日（该周已收盘结束）"
        assert _research(pub, "week") == w, f"mirror 的周末 week 口径漂移：{pub}"
        assert _canon(pub, "week") == w, f"canonical 的周末 week 口径漂移：{pub}"
print("[PASS] 周口径归一：本周≠下周且下周恒晚于本周；周末「本周」终点早于发帖日"
      "（回顾句不再被挪进未来计分；前瞻句由判层编码 nweek，见 opinion/prompts.py §3）")

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
    (SAT, "week", date(2026, 9, 4)),        # ★ 周末"本周" = 发帖日所在周（已收盘）→ 09-04，落在发帖日之前
    (SUN, "week", date(2026, 9, 4)),        # ★ 同上（09-05/09-06 同属 08-31~09-04 那一周）
    (MON, "nweek", date(2026, 9, 18)),      # 周一"下周" = 09-14~09-18 最后交易日
    (FRI, "nweek", date(2026, 9, 11)),      # 周五"下周" = 09-07~09-11
    (SUN, "nweek", date(2026, 9, 11)),      # ★ 周日"下周" = 发帖日+7 所在周（09-07~09-11）→ 09-11
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
    assert _research(pub, spec) == want, f"research mirror 语义漂移：{pub} {spec!r}"
print(f"[PASS] 验证终点语义定点 {len(cases)} 条（含周末「下周一」=t1 与 交易日「下周一」=nweek_first 的分叉）")

# ── 2026-09-10 周口径修正的定点校验：周末「回顾本周」不再被挪进未来 ──
# 周日(09-06)发「本周」→ 终点 09-04（该周最后一个交易日，早于发帖日）。修正前为 09-11
# （前瞻式挪到下一周），使复盘句被当成对下一周的预测计分。
assert _push(SUN, "week") == date(2026, 9, 4) < SUN, "周末「本周」终点必须落在发帖日之前"
assert _push(SUN, "nweek") == date(2026, 9, 11), "周日「下周」= 即将到来那一周（09-07~09-11）"
# 周末发帖真在预判即将到来的那一周时，判层应编 nweek —— 引擎侧与「本周」严格分开
assert _push(SUN, "nweek") > _push(SUN, "week"), "周末：下周终点必须晚于本周终点"
# 周中不受影响：周一/周五的「本周」「下周」语义与修正前一致
assert _push(MON, "week") == date(2026, 9, 11) and _push(FRI, "week") == FRI
print("[PASS] 周末「本周」终点落在发帖日之前（回顾句由报告侧判无效-过时、推送侧过期门剔除）；"
      "「下周」= 即将到来那一周（前瞻句由判层编码 nweek）")

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
