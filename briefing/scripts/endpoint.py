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

与 canonical 的**唯一已知差异**（由 `opinion/tests/test_endpoint_consistency.py` 全网格
比对钉死，不靠人工比对）：

**行情覆盖上限**：canonical 的 `next_td` 以行情数据末日为上限（超出即 None），本模块用
`briefing.scripts.calendar`（无上限，可向前无限推算）——推送侧只关心"终点是否已过"，
不需要被行情覆盖截断。

> **周口径已于 2026-09-10 三份归一**（此前本模块对周六/日走 `blogger_week_monday(pub)+7`
> 的前瞻式口径，canonical/mirror 走 `pub+7`，两者靠测试互相豁免、且"本周/下周"在周末
> 撞车）。现三份统一为**纯自然周**：
> `week` = 发帖日所在 ISO 周最后交易日；`nweek` = 发帖日 **+7 天**所在 ISO 周最后交易日；
> `nweek_first` = 发帖日 +7 天所在 ISO 周首个交易日。
> 周末帖的「回顾 vs 前瞻」之分**不在引擎**，而在判层（前瞻即将到来的那一周 → `nweek`；
> 回顾刚结束的那一周 → 不产行）——引擎不再替模型猜"周末说的本周是哪一周"。误产的
> 周末 `week` 行终点落在发帖日之前，报告侧判 `无效-过时`、推送侧过期门剔除。
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
    上游 sanitize 已拦畸形档）、week=发帖日所在 ISO 周最后交易日、nweek=发帖日 +7 天所在
    ISO 周最后交易日、nweek_first=发帖日 +7 天所在 ISO 周首个交易日（= t1，见该分支注释）、
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
        # 本周 = **发帖日所在** ISO 周（周一~周日）的最后交易日。2026-09-10 修正：不再对
        # 非交易日顺延到下一交易日（旧口径把周末帖的"本周"挪进下一周，与 canonical/mirror
        # 不一致）。周末/节假日发帖 → 该周已结束 → 终点落在发帖日之前，过期门自然剔除；
        # 若博主真在预判即将到来的那一周，判层应编 `nweek`（见模块 docstring）。
        days = calendar.trading_days_in_iso_week(pub)
        return days[-1] if days else None
    if spec == "nweek":
        # 下周 = **发帖日 +7 天**所在 ISO 周的最后交易日（三份实现统一口径）。周末发帖说
        # "下周"即即将到来的那一周（09-06 周日 → 09-07~09-11 → 09-11），与 `week`
        # （09-04，已过）不再撞车。
        days = calendar.trading_days_in_iso_week(pub + timedelta(days=7))
        return days[-1] if days else None
    if spec == "nweek_first":
        # 「下周一」是**星期几**指代而非"整周"指代，其语义 = pub+7 所在 ISO 周的首个
        # 交易日；对周五/周六/周日发帖，该日恰好就是发帖后首个交易日 → 与 t1 同值
        # （见 test 的 nweek_first ≡ t1 断言，"下周一"编码分叉正建立在这条等价上）。
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
