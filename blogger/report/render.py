# -*- coding: utf-8 -*-
"""出报告 —— `reports/<博主名>.md`，给人看的一页纸（见 03§4）。

**列名就是字段名。** 逐条汇总表的列直接叫 `pub`／`spec`／`idx`／`ref`… ——
不翻译成中文，免得对不上数据文件里的键。
"""

from __future__ import annotations

from blogger.report import stats, verify

QUOTE_LIMIT = 60        # 逐条汇总表里引文的截断长度
SAMPLE_MONTHS = 6       # §5 的样本线：帖子跨度 ≥ 6 个月
SAMPLE_SIGNALS = 10     # §5 的样本线：观点信号 > 10 条


def report(blogger: str, rows: list[dict], posts: list[dict]) -> str:
    """整份报告。`rows` 是清库之后的全部信号（含单列的）。"""
    L: list[str] = [f"# {blogger}", ""]
    L += _head(blogger, rows, posts)
    L += _summary(rows)
    L += _tables(rows)
    L += _monthly(rows)
    L += _distribution(rows)
    L += _each(rows)
    L += _notes(rows)
    return "\n".join(L).rstrip() + "\n"


# ── 头部 ────────────────────────────────────────────────────────────────

def _head(blogger: str, rows: list[dict], posts: list[dict]) -> list[str]:
    days = sorted(p["pub"][:10] for p in posts if p.get("pub"))
    t = stats.tally(rows)
    L = [f"帖子 {len(posts)} 条｜观点信号 {t['total']} 条"
         f"（计分 {t['scored']}）"
         + (f"｜区间 {days[0]} ~ {days[-1]}" if days else ""), ""]
    L += _sample_warning(days, t)
    return L


def _sample_warning(days: list[str], t: dict) -> list[str]:
    """§5：**每一位博主都出报告**，样本不足只在头部写明，指标照算照列。"""
    months = _months_between(days[0], days[-1]) if len(days) >= 2 else 0
    short = []
    if months < SAMPLE_MONTHS:
        short.append(f"跨度 {months} 个月（要 ≥{SAMPLE_MONTHS} 个月）")
    if t["total"] <= SAMPLE_SIGNALS:
        short.append(f"信号 {t['total']} 条（要 >{SAMPLE_SIGNALS} 条）")
    if not short:
        return []
    return [f"> **样本不足，指标仅供参考** —— {'；'.join(short)}。", ""]


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + (int(b[5:7]) - int(a[5:7]))


# ── 汇总指标 ────────────────────────────────────────────────────────────

def _summary(rows: list[dict]) -> list[str]:
    scored = [r for r in rows if r["note"] == verify.SCORED]
    t = stats.tally(rows)
    s = stats.summarize(scored)
    L = ["## 汇总", ""]
    L.append(f"信号总数：{t['total']}")
    L.append(f"　另有：不计分 {t['unscored']} 条 / 报错 {t['error']} 条 / "
             f"待验证 {t['pending']} 条")
    L.append(f"计分信号：{t['scored']} 条")
    if not scored:
        L += ["", "没有可计分的信号 —— 下面的指标都算不出来。", ""]
        return L
    L.append(f"正确率：{s['acc']:.1f}%（{s['win']}/{s['denom']}，平局 {s['n'] - s['denom']} 条不入分母）")
    L.append(f"平均分：{s['avg']:+.2f}")
    L.append(f"波动率：{s['vol']:.2f}")
    L.append(f"信息比率：{_fmt_ir(s['ir'])}")
    L.append(f"最高分 / 最低分：{max(r['score'] for r in scored):+.2f} / "
             f"{min(r['score'] for r in scored):+.2f}")
    L.append(_side_line(scored, 1))
    L.append(_side_line(scored, -1))
    L.append("")
    return L


def _fmt_ir(ir: float | None) -> str:
    return "—" if ir is None else f"{ir:+.2f}"


def _side_line(scored: list[dict], d: int) -> str:
    side = [r for r in scored if r["d"] == d]
    name = "看多" if d > 0 else "看空"
    if not side:
        return f"{name}平均分：—（0 条）"
    return f"{name}平均分：{stats.mean_score(side):+.2f}（{len(side)} 条）"


# ── 三张分类表 ──────────────────────────────────────────────────────────

def _tables(rows: list[dict]) -> list[str]:
    scored = [r for r in rows if r["note"] == verify.SCORED]
    L: list[str] = []
    for title, groups in (("按预测对象", stats.by_index(scored)),
                          ("按两档", stats.by_bucket(scored)),
                          ("按方向", stats.by_direction(scored))):
        L += [f"## {title}", ""]
        L += _table(groups, title == "按两档")
        L.append("")
    return L


def _table(groups: dict, keep_order: bool) -> list[str]:
    L = ["| 分类 | 信号数 | 平均分 | 正确率 | 波动率 | 信息比率 |",
         "|:---|---:|---:|---:|---:|---:|"]
    keys = list(stats.BUCKETS) if keep_order else sorted(groups)
    keys = [k for k in keys if k in groups]
    if not keys:
        return L + ["| — | 0 | — | — | — | — |"]
    for k in keys:
        s = stats.summarize(groups[k])
        L.append(f"| {k} | {s['n']} | {s['avg']:+.2f} | {s['acc']:.1f}% | "
                 f"{s['vol']:.2f} | {_fmt_ir(s['ir'])} |")
    return L


# ── 月度表现 ────────────────────────────────────────────────────────────

def _monthly(rows: list[dict]) -> list[str]:
    scored = [r for r in rows if r["note"] == verify.SCORED]
    L = ["## 月度表现", ""]
    L += _table(stats.by_month(scored), keep_order=False)
    L.append("")
    return L


# ── 时间分布与集中度 ────────────────────────────────────────────────────

def _distribution(rows: list[dict]) -> list[str]:
    L = ["## 时间分布", ""]
    months = stats.by_month(rows)
    if months:
        L.append("| 月份 | 信号数 |")
        L.append("|:---|---:|")
        for m in sorted(months):
            L.append(f"| {m} | {len(months[m])} |")
        L.append("")
    warns = stats.concentration(rows)
    if warns:
        L.append("**集中度警告**")
        L.append("")
        for level, what in warns:
            L.append(f"- **{level}**：{what}")
    else:
        L.append("分布上没有需要提示的集中或缺口。")
    L.append("")
    return L


# ── 逐条汇总表 ──────────────────────────────────────────────────────────

def _each(rows: list[dict]) -> list[str]:
    L = ["## 逐条汇总", "",
         "| # | pub | quote | d | spec | idx | ref | ep | epc | ret | score | note |",
         "|:---|:---|:---|:---:|:---|:---|:---:|:---|:---:|:---:|:---:|:---|"]
    for i, r in enumerate(sorted(rows, key=lambda x: x["pub"]), 1):
        L.append("| " + " | ".join([
            str(i), r["pub"][:10], _quote(r["quote"]),
            "↑" if r["d"] > 0 else "↓", r["spec"], r["idx"],
            _num(r["ref"], 2), r["ep"] or "—", _num(r["epc"], 2),
            _pct(r["ret"]), _num(r["score"], 2, sign=True), _note(r),
        ]) + " |")
    L.append("")
    return L


def _quote(q: str) -> str:
    q = (q or "").replace("|", "｜").replace("\n", " ")
    return q if len(q) <= QUOTE_LIMIT else q[:QUOTE_LIMIT] + "…"


def _num(x, digits: int, sign: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x:+.{digits}f}" if sign else f"{x:.{digits}f}"


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.2f}%"


def _note(r: dict) -> str:
    if r["intraday"]:
        return "日内"
    return "—" if r["note"] == verify.SCORED else r["note"]


# ── 观察要点 ────────────────────────────────────────────────────────────

def _notes(rows: list[dict]) -> list[str]:
    scored = [r for r in rows if r["note"] == verify.SCORED]
    t = stats.tally(rows)
    L = ["## 观察要点", ""]
    if not scored:
        L.append("没有可计分的信号，这一节无从谈起。")
        L.append("")
        return L

    s = stats.summarize(scored)
    best = max(scored, key=lambda r: r["score"])
    worst = min(scored, key=lambda r: r["score"])

    L.append(f"- 正确率 {s['acc']:.1f}%、平均分 {s['avg']:+.2f}："
             + ("方向判对的比判错的多。" if s["acc"] > 50 else
                "判错的和判对的差不多，方向没有系统性优势。")
             + ("平均分为正，说明判对的时候赚得比判错的时候多。"
                if s["avg"] > 0 else "平均分为负 —— 判错的时候亏得更多。"))
    L.append(f"- 看多 {len([r for r in scored if r['d'] > 0])} 条、"
             f"看空 {len([r for r in scored if r['d'] < 0])} 条："
             + _side_note(scored))
    L.append(f"- 最强的一档：{_top(stats.by_bucket(scored))}；"
             f"最弱的一档：{_bottom(stats.by_bucket(scored))}")
    L.append(f"- 最强的一只：{_top(stats.by_index(scored))}；"
             f"最弱的一只：{_bottom(stats.by_index(scored))}")
    L.append(f"- 命中最狠：{best['pub'][:10]} {_quote(best['quote'])}"
             f"（{best['idx']} {best['spec']}，{best['score']:+.2f}）")
    L.append(f"- 失误最大：{worst['pub'][:10]} {_quote(worst['quote'])}"
             f"（{worst['idx']} {worst['spec']}，{worst['score']:+.2f}）")
    singles = []
    if t["unscored"]:
        singles.append(f"不计分 {t['unscored']} 条")
    if t["error"]:
        singles.append(f"报错 {t['error']} 条")
    if t["pending"]:
        singles.append(f"待验证 {t['pending']} 条")
    L.append("- 单列的信号：" + ("、".join(singles) if singles else "没有")
             + ("（不计分是年度／中长期预测，报错是非交易日说「今天」，"
                "待验证是行情还没覆盖到终点）" if singles else ""))
    L.append("")
    return L


def _side_note(scored: list[dict]) -> str:
    bull = [r for r in scored if r["d"] > 0]
    bear = [r for r in scored if r["d"] < 0]
    if not bull or not bear:
        return "只有一边，没有可比的两边。"
    b, s = stats.mean_score(bull), stats.mean_score(bear)
    return ("看多平均分更高。" if b > s else
            "看空平均分更高。" if s > b else "两边平均分一样。")


def _top(groups: dict) -> str:
    if not groups:
        return "—"
    k = max(groups, key=lambda x: stats.summarize(groups[x])["avg"])
    return f"{k}（{stats.summarize(groups[k])['avg']:+.2f}）"


def _bottom(groups: dict) -> str:
    if not groups:
        return "—"
    k = min(groups, key=lambda x: stats.summarize(groups[x])["avg"])
    return f"{k}（{stats.summarize(groups[k])['avg']:+.2f}）"


__all__ = ["report"]
