# -*- coding: utf-8 -*-
"""不花一次调用就能量出来的那几组，加上「拿一份产出离线重算」的那两件。

| 函数 | 量什么 | 要一份产出吗 |
|:---|:---|:---|
| `census()` | 清单四栏覆盖多少、断句含不含分号、时间词那条正则、`has_cond` 与七类排除 | 不要 |
| `headroom()` | **清单的作用面有多大** —— 一帖几个时间词／对象词，查出的值一样不一样 | 不要 |
| `adopted(path)` | 模型落的 `spec`／`idx` 跟词典查出来的一样不一样（清单实际被采纳了多少） | 要 |
| `gold_on(path)` | 金标 42 条逐条核这一份产出 | 要 |

**`ablate(path)` 已删**（2026-09-18）—— 它量的是条件句守门的七类排除，而那一条守门整个撤掉了
（02§10.2，结论见 `README.md` §五）。要复现走 git 历史。

**一律不调模型、不写 `data/`、不碰判断缓存。** 只读 `data/posts/*.json` 与传进来的那份产出。
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

from blogger.common import paths
from blogger.parse import extract, hints, lexicons

# 只按句末标点断 —— 和 `hints.SENT_END`（含分号）对照用
NO_SEMI = re.compile(r"(?<=[。！？!?])")

LONG_UNIT = 200                      # 超过这么多字算一个「长单元」

# 七类排除 —— 键是那一类的名字，值是 `lexicons` 里的常量名。
# **DECOY 是元组，其余是编译好的正则** —— 停用办法见 `_off`。
CLASSES: list[tuple[str, str]] = [
    ("一 同形子串", "COND_DECOY"),
    ("二 口头禅与撇开不论", "COND_CLICHE"),
    ("三 假设视角", "COND_VIEW"),
    ("四 冲着读者说的", "COND_READER"),
    ("五 条件挂在半句上", "COND_HALF"),
    ("六 承诺在条件之前", "COND_AFTER"),
    ("七 让步", "COND_YIELD"),
    ("七 惯常", "COND_HABIT"),
]

NEVER = re.compile(r"(?!)")          # 永不匹配的正则


@contextlib.contextmanager
def _off(names: list[str]):
    """停用这几类排除。

    **不复制 `has_cond` 的逻辑** —— 它内部按裸名读这些常量，改常量就等于改它的判断。
    正则换成永不匹配的，元组换成空的。
    """
    old = [(n, getattr(lexicons, n)) for n in names]
    try:
        for n, v in old:
            setattr(lexicons, n, () if isinstance(v, tuple) else NEVER)
        yield
    finally:
        for n, v in old:
            setattr(lexicons, n, v)


# ── 走一遍语料 ──────────────────────────────────────────────────────────

def _posts():
    """逐帖 —— `(博主, 帖子)`。"""
    for name in paths.roster():
        f = paths.posts_file(name)
        if not f.exists():
            continue
        for post in (json.loads(f.read_text(encoding="utf-8")).get("posts") or []):
            yield name, post


def _units(post: dict, pat) -> list[str]:
    return [s for f in hints.FIELDS for s in pat.split(post.get(f) or "") if s.strip()]


def _pct(n: int, d: int) -> str:
    return f"{n * 100 / d:.2f}%" if d else "—"


# ── 一、清单与断句的底数 ────────────────────────────────────────────────

def census() -> None:
    names = paths.roster()
    n_post = 0
    n_sent = n_sent_plain = 0
    long_semi = long_plain = 0
    blank = 0
    col_posts = Counter()            # 这一栏有东西的帖数
    col_hits = Counter()             # 这一栏一共几处
    n_day = n_day_ma = n_day_ord = 0
    n_sent_cond = 0
    cond_now = 0
    cond_off = Counter()             # 停用某一类之后多认几句

    for _, post in _posts():
        n_post += 1
        sents = _units(post, hints.SENT_END)
        plain = _units(post, NO_SEMI)
        n_sent += len(sents)
        n_sent_plain += len(plain)
        long_semi += sum(1 for s in sents if len(s) > LONG_UNIT)
        long_plain += sum(1 for s in plain if len(s) > LONG_UNIT)

        if hints.hints_of(post):
            times, objs, conds = [], [], []
            for s in sents:
                times += lexicons.find_time_words(s)
                objs += lexicons.find_objects(s)
                if lexicons.has_cond(s):
                    conds += [w for w in lexicons.COND_WORDS if w in s]
            dirs = hints.find_dir_words("\n".join(post.get(f) or "" for f in hints.FIELDS))
            for key, got in (("时间词", times), ("对象词", objs),
                             ("条件词", conds), ("方向词", dirs)):
                if got:
                    col_posts[key] += 1
                    col_hits[key] += len(got)
        else:
            blank += 1

        # 时间词那条「N 天」正则：命中多少、被哪一道挡掉
        for s in sents:
            for m in lexicons._N_DAY_RE.finditer(s):
                n_day += 1
                if lexicons._MA_TAIL_RE.match(s, m.end()):
                    n_day_ma += 1
                elif m.start() > 0 and s[m.start() - 1] in "第前":
                    n_day_ord += 1

        # `has_cond`：现值，以及七类逐个停用之后多认几句
        n_sent_cond += len(sents)
        cond_now += sum(1 for s in sents if lexicons.has_cond(s))
        for _, field in CLASSES:
            with _off([field]):
                cond_off[field] += sum(1 for s in sents if lexicons.has_cond(s))

    print(f"语料：{len(names)} 位 · {n_post} 帖\n")

    print("断句")
    print(f"  含分号（现役）  {n_sent} 句 · 超过 {LONG_UNIT} 字的 {long_semi} 个")
    print(f"  只按句末        {n_sent_plain} 句 · 超过 {LONG_UNIT} 字的 {long_plain} 个")
    print(f"  分号多切        {n_sent - n_sent_plain} 句\n")

    print("清单（一帖一行，四栏）")
    for key in ("时间词", "对象词", "条件词", "方向词"):
        print(f"  {key}  {col_posts[key]:>6} 帖（{_pct(col_posts[key], n_post)}）"
              f"  {col_hits[key]:>7} 处")
    print(f"  一行都不摆  {blank:>6} 帖（{_pct(blank, n_post)}）\n")

    print("时间词的「N 天」正则")
    print(f"  命中              {n_day}")
    print(f"  后面是均线名挡掉    {n_day_ma}")
    print(f"  前面是「第／前」    {n_day_ord}（已知多认，定的先不修）\n")

    print("has_cond")
    print(f"  现值        {cond_now} 句（{_pct(cond_now, n_sent_cond)}）")
    # 七类全停用要重走一遍语料 —— 和上面那一轮同一个量级，单列
    with _off([f for _, f in CLASSES]):
        all_off = sum(1 for _, post in _posts()
                      for s in _units(post, hints.SENT_END) if lexicons.has_cond(s))
    print(f"  七类全停用  {all_off} 句（{_pct(all_off - cond_now, cond_now)} 于现值）")
    print("  逐类停用后多认几句：")
    for label, field in CLASSES:
        d = cond_off[field] - cond_now
        print(f"    {label:<12}{field:<14}{d:>+6}")


# ── 二、清单的作用面有多大 ──────────────────────────────────────────────

def headroom() -> None:
    """一帖里时间词／对象词有几个，查出的值一样不一样。

    **只有「≥2 个且值不全同」的帖，清单才在做模型自己做不了的事** —— 只有一个词、或者
    几个词查出来是同一个档／同一个指数，模型自己查也对。这类帖占多少，就是清单作用面的上界。
    """
    n_post = 0
    time_bucket = Counter()
    obj_bucket = Counter()
    either = 0

    for _, post in _posts():
        n_post += 1
        sents = _units(post, hints.SENT_END)
        tw = [v for s in sents for _, _, v in lexicons.find_time_words(s)]
        ow = [v for s in sents for _, _, v in lexicons.find_objects(s)]

        def bucket(vals: list[str]) -> str:
            if not vals:
                return "没有"
            if len(vals) == 1:
                return "只有一个"
            return "≥2 个、值全同" if len(set(vals)) == 1 else "≥2 个、值不全同"

        bt, bo = bucket(tw), bucket(ow)
        time_bucket[bt] += 1
        obj_bucket[bo] += 1
        if bt == "≥2 个、值不全同" or bo == "≥2 个、值不全同":
            either += 1

    order = ["没有", "只有一个", "≥2 个、值全同", "≥2 个、值不全同"]
    print(f"一帖里的时间词／对象词有几个，查出的值一样不一样（{n_post} 帖）\n")
    for key, c in (("时间词", time_bucket), ("对象词", obj_bucket)):
        print(key)
        for b in order:
            mark = "   ← 清单在这儿替模型做了它自己做不了的事" if b == order[-1] else ""
            print(f"  {b:<16}{c[b]:>6} 帖（{_pct(c[b], n_post)}）{mark}")
        print()
    print(f"两者任一   {either} 帖（{_pct(either, n_post)}）—— **清单作用面的上界**")


# ── 三、拿一份产出离线重算 ──────────────────────────────────────────────

def load_run(path: str) -> dict:
    p = Path(path)
    if not p.exists() and not path.endswith(".json"):
        p = Path(path + ".json")
    return json.loads(p.read_text(encoding="utf-8"))


def _posts_of(names: list[str]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for name in names:
        f = paths.posts_file(name)
        if not f.exists():
            continue
        for post in (json.loads(f.read_text(encoding="utf-8")).get("posts") or []):
            out[(name, post["post_id"])] = post
    return out


def _rows_of(doc: dict) -> list[tuple[str, str, dict]]:
    """`(博主, post_id, 行)` —— 把产出摊平。"""
    out = []
    for name, per in doc.items():
        if name.startswith("__"):
            continue
        for pid, rec in per.items():
            if pid.startswith("__"):
                continue
            for s in rec.get("signals") or []:
                out.append((name, pid, s))
    return out


def adopted(path: str) -> None:
    """模型落的 `spec`／`idx`，跟帖里那些词查出来的一样不一样。

    **帖级**核：不问这一行是从哪一句摘的，只问这一帖里有没有哪个时间词查得出同一个档。
    「对不上」= 模型自己落的档，清单帮不上；「帖里一个时间词都没有」= 更谈不上帮。
    """
    doc = load_run(path)
    posts = _posts_of([n for n in doc if not n.startswith("__")])
    rows = _rows_of(doc)

    spec_ok = spec_no = spec_noword = 0
    idx_ok = idx_no = idx_noword = 0
    miss_spec, miss_idx = [], []

    for name, pid, s in rows:
        post = posts.get((name, pid))
        if post is None:
            continue
        sents = _units(post, hints.SENT_END)
        tvals = {v for x in sents for _, _, v in lexicons.find_time_words(x)}
        ovals = {v for x in sents for _, _, v in lexicons.find_objects(x)}

        if not tvals:
            spec_noword += 1
        elif s["spec"] in tvals:
            spec_ok += 1
        else:
            spec_no += 1
            miss_spec.append((name, pid, s["spec"], sorted(tvals), s["quote"]))

        if not ovals:
            idx_noword += 1
        elif s["idx"] in ovals:
            idx_ok += 1
        else:
            idx_no += 1
            miss_idx.append((name, pid, s["idx"], sorted(ovals), s["quote"]))

    print(f"产出 {len(rows)} 行\n")
    print("周期档位（spec）对得上帖里的时间词吗")
    print(f"  对得上    {spec_ok:>5}")
    print(f"  对不上    {spec_no:>5}  ← 模型自己落的档，清单帮不上")
    print(f"  帖里没有时间词 {spec_noword:>5}")
    print("\n对象（idx）对得上帖里的对象词吗")
    print(f"  对得上    {idx_ok:>5}")
    print(f"  对不上    {idx_no:>5}")
    print(f"  帖里没有对象词 {idx_noword:>5}")

    for tag, rows_ in (("spec 对不上", miss_spec), ("idx 对不上", miss_idx)):
        if not rows_:
            continue
        print(f"\n{tag} —— 举 15 条")
        for name, pid, got, have, quote in rows_[:15]:
            print(f"  {name} {pid} 落的「{got}」·帖里有 {have}")
            print(f"    {quote[:60]}")


# ── 四、金标 ────────────────────────────────────────────────────────────

GOLD = Path(__file__).resolve().parents[2] / "archive" / "20260916-四段流程" / "semparse" / "gold.py"


def _gold_module():
    """按路径加载 —— 归档目录名以数字开头，`import` 不了，只能这样拿。"""
    spec = importlib.util.spec_from_file_location("regex_ab_gold", GOLD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gold_on(path: str) -> None:
    """金标 42 条逐条核这一份产出。**只核精度，核不了召回。**"""
    gold = _gold_module()
    doc = load_run(path)
    bad, evaluated, skipped = [], 0, []

    for row in gold.rows():
        if row["作废"]:
            continue
        per = doc.get(row["博主"]) or {}
        rec = per.get(row["post_id"])
        if rec is None or row["post_id"].startswith("__"):
            skipped.append(row)
            continue
        evaluated += 1
        v = gold.judge(row, rec.get("signals") or [])
        if v["违规"]:
            bad.append((row, v))

    print(f"可评 {evaluated} 条｜违规 {len(bad)} 条｜这次没判到 {len(skipped)} 条")
    for row, v in bad:
        what = []
        if v["命中禁止"]:
            what.append(f"命中禁止 {v['命中禁止']}")
        if v["缺应有"]:
            what.append(f"缺应有 {v['缺应有']}")
        if v["空集破了"]:
            what.append("空集破了")
        if v["引文命中"]:
            what.append("引文命中")
        print(f"  {row['轮']} {row['编号']} {row['博主']} {row['post_id']}｜{'·'.join(what)}")
    if skipped:
        c = Counter(r["博主"] for r in skipped)
        print("  没判到的落在：" + "、".join(f"{n} {v}" for n, v in c.most_common()))
