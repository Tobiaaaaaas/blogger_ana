# -*- coding: utf-8 -*-
"""⑥ 出报告 —— `reports/博主对比.md`（见 04§5）。

**①～⑥ 全部由脚本拼** —— 数字、表格、警告清单，一个字都不经模型。
只有末尾第 ⑦ 段「总结与分析」是模型写的，由 `summary.py` 补上。
"""

from __future__ import annotations

from blogger.common import market, params
from blogger.compare_all import boards as B
from blogger.report import stats

COLUMNS = ("排名", "博主", "计分信号", "正确率", "平均分", "波动率", "信息比率")
SIDES = ("看多", "看空")
DIRECTION_BOARDS = ("看多榜", "看空榜")


def report(people: list[dict], failed: list[str], boards: list[dict]) -> str:
    L: list[str] = ["# 全博主对比", ""]
    L += head(people, failed)
    L += not_ranked(people, failed)
    for b in boards:
        L += board_section(b)
    L += warning_section(people)
    return "\n".join(L).rstrip() + "\n"


# ── ① 头部 ──────────────────────────────────────────────────────────────

def head(people: list[dict], failed: list[str]) -> list[str]:
    idx = params.get("compare.index", "上证指数")
    s = params.get("sample", {})
    rank = params.get("compare.rank_board", {})
    grp = params.get("compare.group_board", {})
    L = [f"数据截止 {market.LAST_DATE}｜库里 {len(people) + len(failed)} 位博主"
         f"｜参与对比 {sum(1 for p in people if p['in'])} 位"
         + (f"｜本轮更新失败 {len(failed)} 位" if failed else ""), ""]
    L += ["**资格线**", "",
          f"- 参与对比：帖子跨度 ≥ {s.get('span_months', 6)} 个月 且 "
          f"观点信号 > {s.get('signals', 10)} 条",
          f"- 总榜：{idx}计分信号 ≥ {rank.get('min_signals', 30)} 条 且 "
          f"平均分 > {rank.get('min_avg', 0):g}",
          f"- 分榜／方向榜：该组信号 ≥ {grp.get('min_signals', 10)} 条 且 "
          f"平均分 > {grp.get('min_avg', 0.1):g}",
          f"- 每张榜取前 {B.top_n()} 名", ""]
    return L


# ── ② 不参与排名 ────────────────────────────────────────────────────────

def not_ranked(people: list[dict], failed: list[str]) -> list[str]:
    L = ["## 不参与排名", ""]
    if failed:
        L += [f"**本轮更新失败**（{len(failed)} 位）—— 抓取／解析／写报告只要有一处没跑成，"
              "这一轮就不带他进对比，**不拿旧数据顶上**：", ""]
        L += [f"- {n}" for n in failed] + [""]
    out = [p for p in people if not p["in"]]
    if out:
        L += [f"**够不上样本线**（{len(out)} 位）—— 指标照算，但不排进任何榜：", ""]
        L += [f"- {p['name']}：{'；'.join(p['short'])}" for p in out] + [""]
    if not failed and not out:
        L.append("没有 —— 库里每一位都参与了对比。")
        L.append("")
    L += ["> 够不上**上榜资格**的见各榜榜尾。", ""]
    return L


# ── ③④⑤ 一张榜 ─────────────────────────────────────────────────────────

def board_section(b: dict) -> list[str]:
    """**每张榜的标题都写明「只考察 上证指数」**（04§3.1）。"""
    idx = params.get("compare.index", "上证指数")
    one = b["title"] in DIRECTION_BOARDS
    L = [f"## {b['title']} · 只考察 {idx}", ""]
    L += _table(b["board"]["hit"], drop_sides=one)
    if b["board"]["out"]:
        L += ["", "**榜尾** —— 参与对比但没上榜的：", "",
              "| 排名 | 博主 | 计分信号 | 正确率 | 平均分 | 波动率 | 信息比率 | 差在哪 |",
              "|:---:|:---|---:|---:|---:|---:|---:|:---|"]
        for r in b["board"]["out"]:
            L.append(_row(r, rank="—") + f" {r['why']} |")
    L.append("")
    return L


def _table(rows: list[dict], drop_sides: bool) -> list[str]:
    """**加粗的那一列 = 平均分** —— 三张榜一律按它降序（04§5.1）。"""
    cols = COLUMNS + (() if drop_sides else SIDES)
    L = ["| " + " | ".join(cols) + " |",
         "|:---:|:---|---:|---:|---:|---:|---:|"
         + ("" if drop_sides else "---:|---:|")]
    if not rows:
        L.append("| " + " | ".join(["—", "一位都没有"] + ["—"] * (len(cols) - 2)) + " |")
        return L
    for i, r in enumerate(rows, 1):
        L.append(_row(r, rank=str(i), with_sides=not drop_sides))
    return L


def _row(r: dict, rank: str, with_sides: bool = False) -> str:
    s = stats.summarize(r["rows"])
    cells = [rank, r["name"], str(s["n"]), f"{s['acc']:.1f}%",
             f"**{s['avg']:+.2f}**", f"{s['vol']:.2f}",
             "—" if s["ir"] is None else f"{s['ir']:+.2f}"]
    if with_sides:
        bull = sum(1 for x in r["rows"] if x["d"] > 0)
        cells += [str(bull), str(len(r["rows"]) - bull)]
    return "| " + " | ".join(cells) + " |"


# ── ⑥ 集中度与缺口警告 ──────────────────────────────────────────────────

def warning_section(people: list[dict]) -> list[str]:
    L = ["## 集中度与缺口警告", "",
         "**必须提出来，不许闷着** —— 样本高度集中的榜，均分再好看也不作数。"
         "算的是榜上那份样本（上证计分信号）。", ""]
    warns = B.warnings(people)
    if not warns:
        L += ["没有需要提示的。", ""]
        return L
    L += [f"- {name}：{what}" for name, what in warns] + [""]
    return L


__all__ = ["report", "head", "board_section"]
