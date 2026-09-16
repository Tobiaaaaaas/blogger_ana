# -*- coding: utf-8 -*-
"""比 —— 两遍之间、与旧流程之间、与判例之间。

一致性的那一半**分组判定原样抄自 `research/semparse/jitter.py`** —— 甲／乙／
丙1／丙2／丙3／丁 六个组的判定，是判例与旧基线用的同一把尺子。**一个字没改**：判例与
旧基线既然是那把尺子量的，换一份实现就等于换了一把尺子，量出来的差说不清是流程的差
还是尺子的差。底下 `GROUPS` 与 `classify` 那一节连注释一起照搬。

**只有一处口径不同：`丁` 不算不一致。** 丁 的定义是「条数、周期、对象、方向四项逐项
相同，只有引文取的是哪一段不同」—— 三元组一样，说的就是同一个判断，只是同一句话里
挑出来做佐证的那一段不同。所以本模块报的「不一致」一律是**扣掉丁之后**的数，丁单列
一行供查。旧基线 343 条按同一口径扣除它的 108 条是 **235 条（12.8%）**。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from blogger.parse import lexicons
from blogger.report import cache

from research.semparse import gold

# ── 从 research/semparse/jitter.py 原样抄来 ──────────────────────────────

# 争议分组 —— 按「规则问的是哪个问题」分，不按博主
GROUPS = [
    ("甲", "一遍产、另一遍完全不产", "什么算一条观点信号（02§6 与 §3.1）"),
    ("乙", "两遍都产，但条数不同", "一条帖能出几条（02§7）"),
    ("丙1", "条数相同、周期不同", "02§4 的周期表与 §4.4"),
    ("丙2", "条数相同、对象不同", "02§5 的映射与「跟着这一处表述走」"),
    ("丙3", "条数相同、方向不同", "02§3 方向"),
    ("丁", "三元组相同、引文不同", "02§9 引文佐证"),
]


def _raw(a: list[dict], b: list[dict]) -> str:
    """两组信号属于哪一类争议。**完全一样返回空串**。

    条数与三个分量逐级判 —— 一条案例可能同时有几处不同，归到最靠前的那一类。
    """
    if not a and not b:
        return ""
    if not a or not b:
        return "甲"
    if len(a) != len(b):
        return "乙"
    if Counter(s["spec"] for s in a) != Counter(s["spec"] for s in b):
        return "丙1"
    if Counter(s["idx"] for s in a) != Counter(s["idx"] for s in b):
        return "丙2"
    if Counter(s["d"] for s in a) != Counter(s["d"] for s in b):
        return "丙3"
    if sorted(s["quote"] for s in a) != sorted(s["quote"] for s in b):
        return "丁"
    return ""


# ── 本模块的口径 ────────────────────────────────────────────────────────

def load(path: str) -> dict:
    p = Path(path)
    if not p.exists() and not path.endswith(".json"):
        p = Path(path + ".json")
    return json.loads(p.read_text(encoding="utf-8"))


def posts_of(doc: dict, name: str) -> dict:
    return {k: v for k, v in (doc.get(name) or {}).items() if not k.startswith("__")}


# ── 一致性 ──────────────────────────────────────────────────────────────

def classify(a: list[dict], b: list[dict]) -> str:
    """`_raw` 的判定，**只把 `丁` 并进「判得一样」**。

    丁 是「三元组逐项相同、只有引文取的是哪一段不同」—— 判断本身没有分歧，不记。
    实现仍是那一份：改的只是报告口径，六个组的边界一个字没动。
    """
    g = _raw(a, b)
    return "" if g == "丁" else g


def count(f1: str, f2: str) -> tuple[Counter, Counter, int, int]:
    """比两份产物 —— 返回 `(各组的帖数, 各博主各组的帖数, 判得一样, 只有一遍判到的)`。

    `丁` 那一格是**从「判得一样」里单拎出来的**（它已经计进 `n_same`），所以
    `sum(c.values())` 要扣掉它才是「不一致」。
    """
    p1, p2 = load(f1), load(f2)
    c: Counter = Counter()
    per: Counter = Counter()
    n_same = only = 0
    for name in sorted(set(p1) | set(p2)):
        if name.startswith("__"):
            continue
        a_all, b_all = posts_of(p1, name), posts_of(p2, name)
        only += len(set(a_all) ^ set(b_all))
        for pid in set(a_all) & set(b_all):
            g = classify(a_all[pid]["signals"], b_all[pid]["signals"])
            if g:
                c[g] += 1
                per[(name, g)] += 1
            else:
                n_same += 1
                if _raw(a_all[pid]["signals"], b_all[pid]["signals"]) == "丁":
                    c["丁"] += 1
                    per[(name, "丁")] += 1
    return c, per, n_same, only


def cmd_cmp(f1: str, f2: str, a: str = "", b: str = "") -> int:
    a, b = a or Path(f1).stem, b or Path(f2).stem
    print(f"「{a}」 {f1} ｜ 「{b}」 {f2}")
    c, per, n_same, only = count(f1, f2)
    tot = sum(c.values()) - c["丁"]
    done = n_same + tot
    print(f"两遍都判到的帖 {done} 条｜判得一样 {n_same} 条"
          f"｜不一致 {tot} 条（{tot * 100 / max(1, done):.1f}%）")
    print(f"  另 {c['丁']} 条只有引文取哪一段不同、三元组逐项一样 —— 不算不一致")
    print(f"只有一遍判到的帖 {only} 条（失败批／取不到注记）—— 不算差异，已剔除")
    for g, what, _ in GROUPS:
        print(f"  {g:<4}{what:<22}{c[g]} 条")
    print()
    for g, _, _ in GROUPS:
        rows = sorted(((n, v) for (n, gg), v in per.items() if gg == g),
                      key=lambda r: -r[1])
        if rows:
            print(f"  {g}：" + "、".join(f"{n} {v}" for n, v in rows))
    return 0


def baseline_markdown(doc1: dict, doc2: dict) -> str:
    """旧流程那条基线，连同**它是在哪一代规则、多少帖上量的** —— 出处 `docs/判例/第二轮.md:3`。

    基线是**旧流程**（指纹 `601a685c4730d9b9`）、**三位博主 1834 帖**跑出来的。
    **「1834 帖」这句必须留着** —— 本轮只跑了一位博主时，两个百分数隔着语料与规则两道，
    不是同一把尺子。

    扣除 `丁` 是**纯减法**：丁 是 `classify` 的最后一档，一条帖不是丁就算别的组，
    所以 343 − 108 ＝ 235 不需要重跑，除非旧流程要按新口径重新表述成 12.8%。
    """
    cur = cache.rule_fingerprint()
    names = [x for x in doc1 if not x.startswith("__")]
    n = sum(len(posts_of(doc1, x)) for x in names)
    return (f"### 与旧流程基线比\n\n"
            f"基线：三位博主、1834 帖，**判得不一样 235 条（12.8%）** —— "
            f"甲 150／乙 46／丙1 30／丙2 7／丙3 2（另有 丁 108 条已按同一口径扣除）。"
            f"出处 `docs/判例/第二轮.md:3`（原文记的是含丁的 343 条／18.7%），"
            f"规则指纹 `601a685c4730d9b9`；现行指纹 `{cur}`。本轮跑了 {len(names)} 位、"
            f"{n} 帖 —— **语料与规则两道都不同代，两个百分数只能远远看一眼。**\n\n")


def groups_markdown(doc1: dict, doc2: dict) -> str:
    """六个组名只说了「哪一项对不上」，没说**对不上的是什么**。这里把每一组拆开看。

    乙组按定义就是条数不等；要紧的是多出来那一条是「同一帖里多捞了一句」，还是
    「整帖看法不同」—— 前者是边际抖动，后者才是分歧。

    头条的「不一致」与 `cmd_cmp` 同一口径：**扣掉丁**。丁 单列一行、照旧给数，供查。
    """
    n = Counter()
    tick = {"乙_子集": 0, "乙_换句": 0, "乙_多出方向": Counter(), "丙3_同句": 0, "丙3_异句": 0}
    per = {}
    for name in sorted(set(doc1) | set(doc2)):
        if name.startswith("__"):
            continue
        A = posts_of(doc1, name)
        B = posts_of(doc2, name)
        for pid in set(A) & set(B):
            a, b = A[pid]["signals"], B[pid]["signals"]
            raw = _raw(a, b)                     # 逐博主的表要单列丁，所以这一层用原判定
            c = per.setdefault(name, Counter())
            c["一样" if raw in ("", "丁") else raw] += 1
            c["丁"] += raw == "丁"
            n["丁"] += raw == "丁"
            g = "" if raw == "丁" else raw
            if not g:
                continue
            n[g] += 1
            if g == "乙":
                qa = Counter(s["quote"] for s in a)
                qb = Counter(s["quote"] for s in b)
                small, big = (qa, qb) if len(a) < len(b) else (qb, qa)
                if not (small - big):
                    tick["乙_子集"] += 1
                    src = a if len(a) > len(b) else b
                    for q in (big - small).elements():
                        tick["乙_多出方向"][next(s["d"] for s in src if s["quote"] == q)] += 1
                else:
                    tick["乙_换句"] += 1
            if g == "丙3":
                # 两遍方向不同 —— 引的是同一句还是各引各的句。引文是切出来的，
                # 同一句两遍可能截在不同处，所以按包含判，不按相等判
                if any(x["quote"] == y["quote"] or x["quote"] in y["quote"]
                       or y["quote"] in x["quote"] for x in a for y in b):
                    tick["丙3_同句"] += 1
                else:
                    tick["丙3_异句"] += 1

    tot = sum(n.values()) - n["丁"]
    lines = [f"### 六个组各自是什么（不一致 {tot} 条）\n",
             "| 组 | 对不上的是 | 条数 |",
             "|:---|:---|---:|",
             f"| 甲 | 一遍产、另一遍一条不产 | {n['甲']} |",
             f"| 乙 | 帖内条数不等 | {n['乙']} |",
             f"| 丙1 | 周期档位 | {n['丙1']} |",
             f"| 丙2 | 指数 | {n['丙2']} |",
             f"| 丙3 | 方向 | {n['丙3']} |",
             f"| 丁 | 只有引文取哪一句（**不算不一致**） | {n['丁']} |", ""]
    lines.append(f"乙组 {n['乙']} 条里，**{tick['乙_子集']} 条是条帖子集关系** —— "
                 f"两遍认的信号是同一套，只是一遍多捞（共多出 "
                 f"{sum(tick['乙_多出方向'].values())} 条：看多 {tick['乙_多出方向'][1]}、"
                 f"看空 {tick['乙_多出方向'][-1]}），另 {tick['乙_换句']} 条是各自捞了不同的句子。"
                 f"**多出的方向两头差不多，不是偏向某一头。**\n")
    lines.append(f"丙3 {n['丙3']} 条方向翻转里，**{tick['丙3_同句']} 条两遍引的是同一句** —— "
                 f"一句话里正反两头都说了，两遍各挑了一头（例：「存在反弹修复，修复的力度和高度"
                 f"也都有限」「早盘低开低走，下午可能快速跳水，个人认为是买点」）。"
                 f"另 {tick['丙3_异句']} 条各引各的句。\n")
    lines.append("| 博主 | 判得一样 | 甲 | 乙 | 丙1 | 丙2 | 丙3 | 其中丁 |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|")
    for name, c in per.items():
        k = sum(c.values())
        lines.append(f"| {name} | {c['一样']}（{c['一样'] * 100 / k:.1f}%） | {c['甲']} "
                     f"| {c['乙']} | {c['丙1']} | {c['丙2']} | {c['丙3']} | {c['丁']} |")
    return "\n".join(lines) + "\n"


# ── 对判例 ──────────────────────────────────────────────────────────────

def eval_gold(doc: dict) -> list[dict]:
    """拿一份跑的产物核 42 条断言。返回逐条的核验结果。"""
    out = []
    for row in gold.rows():
        if row["作废"]:                       # 与 02 正文冲突、已作废 —— 不进分母
            out.append({**row, "评": False, "原因": f"作废：{row['作废']}"})
            continue
        posts = posts_of(doc, row["博主"])
        p = posts.get(row["post_id"])
        if p is None:
            # 42 条判例横跨六位博主，本轮只跑三位 —— 剩下的照不进来，不是这一遍判漏了
            why = (f"{row['博主']} 本轮没跑" if row["博主"] not in doc
                   else "这一遍没判到这条帖")
            out.append({**row, "评": False, "原因": why})
            continue
        out.append({**row, "评": True, "signals": p["signals"],
                    **gold.judge(row, p["signals"])})
    return out


def gold_markdown(results: list[dict], title: str) -> str:
    lines = [f"## {title}\n"]
    done = [r for r in results if r["评"]]
    bad = [r for r in done if r["违规"]]
    void = [r for r in results if r["作废"]]
    away = sum(1 for r in results if not r["评"] and "本轮没跑" in r["原因"])
    # 作废的那几条也算「没判到」会把账读歪 —— 它们是没进分母，不是没判到
    lines.append(f"可评 {len(done)} 条｜违规 {len(bad)} 条"
                 f"（{len(bad) * 100 / max(1, len(done)):.0f}%）"
                 f"｜没判到 {len(results) - len(done) - len(void) - away} 条"
                 f"｜作废 {len(void)} 条"
                 + (f"｜本轮没跑的博主 {away} 条\n" if away else "\n"))
    over = sum(1 for r in bad if r["空集破了"] or r["命中禁止"] or r["引文命中"])
    short = sum(1 for r in bad if r["缺应有"])
    lines.append(f"**产的（多产了不该产的）{over} 条｜漏的（该产的没产全）{short} 条** —— "
                 f"两半分开算，别合成一个数看。\n")
    if void:
        lines.append(f"作废的是（判例与 02 正文冲突）："
                     + "、".join(f"{r['编号']}（{r['作废']}）" for r in void) + "\n")
    if not bad:
        lines.append("一条都没违规。\n")
        return "\n".join(lines)
    lines.append("| 编号 | 博主 | 帖 id | 犯的是 | 新流程产的 |")
    lines.append("|:---|:---|:---|:---|:---|")
    for r in bad:
        what = []
        if r["命中禁止"]:
            what.append("产了判例点名说错的那条")
        if r["缺应有"]:
            what.append("该有的没产")
        if r["空集破了"]:
            what.append("这帖本不该产")
        if r["引文命中"]:
            what.append(f"产了含『{r['引文']}』的那条")
        got = "、".join(f"{d:+d}/{s}/{i}" for d, s, i in gold.triples(r["signals"])) or "（无）"
        lines.append(f"| {r['编号']} | {r['博主']} | `{r['post_id']}` | {'＋'.join(what)}"
                     f" | {got} |")
    return "\n".join(lines) + "\n"


# ── 词典缺口 ────────────────────────────────────────────────────────────

def _gap_bucket(g: dict) -> str:
    """这一处「模型答出的词不在表里」，是**真要补表**，还是代码／02 已经兜住了。

    时间词那一栏问的是**代码落档会不会被它带偏** —— 只在句子没有表内时间词时才带得偏。
    对象词那一栏问的是**这个词指的是谁** —— 表外词落在「整个市场」上是 §5.4 的事，落在
    板块上是 §5.2 末行的事，都不是词典漏了。
    """
    if g["类"] == "时间词":
        return "另有表内词" if lexicons.find_time_words(g["句"]) else "句里没有"
    if g["类"] == "对象词":
        w = g["词"]
        if any(m in w for m in _MARKET_WIDE) or "指数" in w:
            return "整体市场"
        return "不产的板块" if lexicons.has_ignored_sector(w) else "待看"
    return ""


# 说的是「整个市场」的词 —— 跟 `lexicons.MARKET_WORDS` 同一份，只多一个「大A」。
# 「指数」归这一桶靠的是后缀判，不列进来（列了会撞上「中证2000指数」那种点名）。
_MARKET_WIDE = lexicons.MARKET_WORDS + ("大A",)

# 每一桶怎么读 —— 表头那一行，别让读者自己去对 02
_BUCKET_SAY = {
    "句里没有": "（要看的就是这一桶）",
    "另有表内词": "（代码已按表内那个词落档，带不偏）",
    "整体市场": "（§5.4 默认本来就管，落的是上证指数，不是缺口）",
    "不产的板块": "（§5.2 末行／§5.1 明文不产，不是缺口）",
    "待看": "（**一个个看** —— 可能是 §5.2 漏收的别名，也可能是该忽略的板块）",
}


def gap_markdown(doc: dict) -> str:
    """模型答出、词典里没有的词 —— **这份是词典的下一步**。

    不分桶的话这张表是读不出行动项的：`A股`／`指数` 这类「整个市场」的说法落 §5.4 默认
    本来就算对，`科技股`／`中证2000` 属 §5.2 末行与 §5.1 明文不产 —— 它们出现在这里，
    是因为模型把「它指的是谁」写进了 `ow`，不是因为词典漏了。
    """
    allg: list[dict] = []
    for name in sorted(doc):
        if name.startswith("__"):
            continue
        allg += doc[name].get("__缺口__") or []

    lines = ["## 词典缺口\n",
             f"共 {len(allg)} 处 —— 模型答出的词不在表里。**这不是模型的错，是词典的漏** —— "
             "但要分桶看：一处缺口只有在**代码没别的词可依**时才影响结果。\n"]
    for kind in ("时间词", "对象词", "方向词"):
        rows = [g for g in allg if g["类"] == kind]
        if not rows:
            continue
        c = Counter(g["词"] for g in rows)
        lines.append(f"### {kind}（{sum(c.values())} 处，{len(c)} 个词）\n")
        ex: dict[str, str] = {}
        for g in rows:
            ex.setdefault(g["词"], g["句"])
        if kind == "方向词":                 # 开放类，不分桶 —— 本来就不指望收全
            lines.append("开放类，**这一栏不是待办**，只用来估模型的说法偏离表有多远。\n")
            lines.append("| 词 | 次数 | 例 |")
            lines.append("|:---|---:|:---|")
            for w, n in c.most_common(40):
                lines.append(f"| {w} | {n} | {ex[w][:40]} |")
            lines.append("")
            continue
        order = ("句里没有", "另有表内词") if kind == "时间词" else ("待看", "整体市场", "不产的板块")
        for bucket in order:
            sub = [g for g in rows if _gap_bucket(g) == bucket]
            if not sub:
                continue
            cs = Counter(g["词"] for g in sub)
            lines.append(f"**{bucket}** —— {len(sub)} 处、{len(cs)} 个词"
                         f"{_BUCKET_SAY[bucket]}\n")
            lines.append("| 词 | 次数 | 例 |")
            lines.append("|:---|---:|:---|")
            for w, n in cs.most_common(40):
                lines.append(f"| {w} | {n} | {ex[w][:40]} |")
            lines.append("")
    return "\n".join(lines) + "\n"


def zeros_markdown(doc: dict, per: int = 4) -> str:
    """`zeros` 那一栏 —— 模型把每个「不算」的句子归到了 §6 的哪一格。

    **这份是这套流程第一次能看见「差一点就是信号」的那些句子。** 先前 `d=0` 只写编号、
    不带理由，于是分不出是「本来就不产」还是「漏了」：模型判错可以查，模型没读到查不出来。

    读法：**哪一格最多，下一轮就攻哪一格**。每格底下直接引原句 —— 句子是代码从帖子里
    取的，不花模型的输出预算，所以「这一格具体在拦什么」看得见，不必让模型再抄一遍。
    """
    rows: list[dict] = []
    for name in sorted(doc):
        if name.startswith("__"):
            continue
        rows += [r for r in (doc[name].get("__审计__") or []) if r["处置"] == "非信号"]
    if not rows:
        return "## 归格 —— 为什么不算\n\n这一份里一处都没有。\n"

    ex: dict[str, list[str]] = {}
    for r in rows:
        ex.setdefault(r["why"] or "（未给格名）", []).append(r["text"])
    c = Counter(r["why"] or "（未给格名）" for r in rows)

    lines = ["## 归格 —— 为什么不算\n",
             f"共 {len(rows)} 句。每一句都是**模型说「这句不算一条观点信号」并给了格名**。"
             f"**格名最多的那一格就是下一轮要攻的。**\n",
             "| 格 | 句数 | 占 | 例 |", "|:---|---:|---:|:---|"]
    for k, n in c.most_common():
        # 引最短的几句 —— 长句在表里读不完，而这一栏要的是「它在拦什么」
        short = sorted(set(ex[k]), key=len)[:per]
        exs = "；".join(s[:34] for s in short)
        lines.append(f"| {k} | {n} | {n * 100 / len(rows):.0f}% | {exs} |")
    return "\n".join(lines) + "\n"


# ── 几份跑并排 ──────────────────────────────────────────────────────────

def tally_markdown(docs: dict[str, dict]) -> str:
    """几份跑各自的统计并排看。

    `去重` 数的是审计行 —— `产` 记的是**批内去重后**的数，两份跑的总账是那次之后才把
    `去重` 接进 runner 的，早先写下的 JSON 里这一项缺；审计行本来就是去重前逐条落的，
    从那儿数，新旧文件读出来是同一个口径。
    """
    keys = ["帖", "可判", "批", "失败批", "失败帖", "产", "丢", "非信号", "无格",
            "待复核", "缺口", "沉默", "沉默批", "重试", "去重", "码外"]
    lines = ["| 项 | " + " | ".join(docs) + " |", "|:---|" + "---:|" * len(docs)]
    for k in keys:
        vals = []
        for d in docs.values():
            if k == "去重":
                tot = sum(1 for n in d if not n.startswith("__")
                          for r in (d[n].get("__审计__") or []) if r["处置"] == "去重")
            else:
                tot = sum((d[n].get("__tally__") or {}).get(k, 0)
                          for n in d if not n.startswith("__"))
            vals.append(str(tot))
        if any(v != "0" for v in vals):
            lines.append(f"| {k} | " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


__all__ = ["load", "posts_of", "cmd_cmp", "groups_markdown", "eval_gold",
           "gold_markdown", "gap_markdown", "zeros_markdown", "tally_markdown"]
