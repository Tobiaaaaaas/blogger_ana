# -*- coding: utf-8 -*-
"""验证终点推算（spec → 该预测被验证的那一刻），推送链专用（2026-09-10 新增）。

**语义与 `scripts/eval/run_direction.py:endpoint_of`（canonical，打分引擎）逐条对齐**，
另有 `research/trading_cal.py:endpoint_of`（mirror）。`scripts/eval/` 无 `__init__.py`
不可包导入、`briefing/` 也不该反向依赖打分引擎，故此处是**第三份实现**——由
`opinion/tests/test_endpoint_consistency.py` 三方网格比对钉死不漂移（勿只改一处）。

用途（用户 2026-09-10 需求）：
- 推送卡每行注明「验证终点 MM-DD 收盘」；
- 两板块统一**过期门**：终点（终点交易日 15:00 收盘）已过 → 该行不再显示
  （"9月9日晚上发的、预测 9.9 下午三点收盘"这类已发生验证的行不得再推）。

与 canonical 的**两处已知差异**（均由 `opinion/tests/test_endpoint_consistency.py` 显式
枚举并断言，不靠人工比对）：

1. **行情覆盖上限**：canonical 的 `next_td` 以行情数据末日为上限（超出即 None），本模块用
   `briefing.scripts.calendar`（无上限，可向前无限推算）——推送侧只关心"终点是否已过"，
   不需要被行情覆盖截断。
2. **`nweek` 的周口径（2026-09-10 修正）**：canonical 写作 `pub + 7 天` 再取 ISO 周，而
   ISO 周为周一~周日——**周六/日发帖**时 `pub+7` 仍落在同一 ISO 周，导致"下周"不前进、
   与其自身的"本周"撞成同一天（09-06 周日：week 与 nweek 同为 09-11）。本模块改用
   `calendar.blogger_week_monday(pub) + 7 天`，与推送锚定展示（`summarize._anchor_row`
   的 `下周 MM-DD~MM-DD`）同一口径；否则卡面会自相矛盾（"下周 09-14~09-18 · 终点 09-11
   收盘"），且过期门会提前一周剔除该行。**canonical 未改**（它参与历史打分，改动会波及
   已冻结的 curated 信号评分）——是否同步修正待用户裁决。
"""
from datetime import date as _date, datetime, time, timedelta, timezone

from . import calendar

BEIJING = timezone(timedelta(hours=8))
ENDPOINT_CLOSE = time(15, 0)   # A 股收盘时刻：终点日的验证时刻


def _as_date(d) -> _date:
    """date 或 'YYYY-MM-DD'（含带时间的 ISO 串）→ date。"""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, _date):
        return d
    return _date.fromisoformat(str(d)[:10])


def endpoint_of(pub_date, spec):
    """spec → 验证终点日（date）；`long`（不计分/无期限）或无法推算 → None。

    pub_date：发帖自然日（date 或 'YYYY-MM-DD'）。语义逐条对齐 canonical：
    today=发帖日收盘（非交易日顺延）、tN=发帖后第 N 个交易日（t0 同 canonical 返回发帖日，
    上游 sanitize 已拦畸形档）、week=博主视角周最后交易日、nweek=博主视角周 +1 周最后交易日
    （见下差异 2）、nweek_first=发帖日 +7 天所在 ISO 周首个交易日（= t1，见该分支注释）、
    month/nmonth=当月/下月最后交易日、d:YYYY-MM-DD=该日（非交易日顺延，兼容既有行）。
    """
    if spec == "long":
        return None                      # 不计分周期：无验证终点（同 canonical）
    pub = _as_date(pub_date)
    if spec == "today":
        return pub if calendar.is_trading_day(pub) else calendar.next_trading_day(pub)
    if isinstance(spec, str) and spec.startswith("t") and spec[1:].isdigit():
        d = pub
        for _ in range(int(spec[1:])):
            d = calendar.next_trading_day(d)      # tN = 发帖后第 N 个交易日
        return d
    if spec == "week":
        # 保持 canonical 口径（非交易日顺延到下一交易日再取 ISO 周）：周六/日顺延进下一 ISO 周，
        # 结果与博主视角周一致（09-05 周六 / 09-06 周日 → 均为 09-11），故与卡面 anchor 不矛盾。
        # 已知角落（未修，非本轮引入）：**周内节假日**发帖（如 09-25 中秋周五）此处顺延到 09-28
        # 那一周 → 答 09-30，而 anchor 仍按 09-21~09-25 展示；该情形 anchor 通常已判"目标周已过"
        # 剔除，实际极罕见，留待后续统一。
        base = pub if calendar.is_trading_day(pub) else calendar.next_trading_day(pub)
        days = calendar.trading_days_in_iso_week(base)
        return days[-1] if days else None
    if spec == "nweek":
        # 下周 = 博主视角周 +1 周的最后交易日。**不可写作 pub+7 再取 ISO 周**：ISO 周是
        # 周一~周日，周六/日 +7 天落进的那一周，正是 `week` 分支顺延到下一交易日时落进的
        # 同一周（09-06 周日：week 与 nweek 同为 09-11）——"下周"于是与"本周"撞车，且与
        # 卡面 anchor（下周 09-14~09-18）自相矛盾（canonical/mirror 现存缺陷，2026-09-10 发现）。
        days = calendar.trading_days_in_iso_week(calendar.blogger_week_monday(pub) + timedelta(days=7))
        return days[-1] if days else None
    if spec == "nweek_first":
        # **刻意不对齐 blogger_week_monday**：「下周一」是**星期几**指代而非"整周"指代，
        # 其语义 = pub+7 所在 ISO 周的首个交易日；对周五/周六/周日发帖，该日恰好就是
        # 发帖后首个交易日 → 与 t1 同值（见 test 的 nweek_first ≡ t1 断言，A1 编码分叉
        # 正是建立在这条等价上）。若改走博主视角周，周六/日会跳到再下一周，等价即破。
        days = calendar.trading_days_in_iso_week(pub + timedelta(days=7))
        return days[0] if days else None
    if spec == "month":
        days = calendar.trading_days_in_month(pub)
        return days[-1] if days else None
    if spec == "nmonth":
        y, m = pub.year, pub.month + 1
        if m > 12:
            y, m = y + 1, 1
        days = calendar.trading_days_in_month(_date(y, m, 1))
        return days[-1] if days else None
    if isinstance(spec, str) and spec.startswith("d:"):
        tgt = _date.fromisoformat(spec[2:])
        return tgt if calendar.is_trading_day(tgt) else calendar.next_trading_day(tgt)
    raise ValueError(f"未知 spec: {spec!r}")


def endpoint_dt(pub_date, spec):
    """验证终点时刻（终点日 15:00 收盘，北京时）；无终点（long/无法推算）→ None。

    过期门判据：`endpoint_dt(...) <= now` → 该预测的验证时点已经过去，行不得再显示。
    """
    ep = endpoint_of(pub_date, spec)
    if ep is None:
        return None
    return datetime.combine(ep, ENDPOINT_CLOSE, tzinfo=BEIJING)
