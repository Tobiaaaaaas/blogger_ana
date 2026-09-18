# -*- coding: utf-8 -*-
"""02§10.1／§10.5 字面辅助层 —— 摆清单、找疑点。

**只摆不判、只报不改。** 这一层一个字都不改产出：`hints_of` 把代码认得出的字面特征摆在
帖文旁边，`suspects` 把这一帖里该复核的地方指出来（`contradiction` 是其中只用引文的那两条），
交模型自己判。**这一层没有一处按字面删行。**

**清单只摆不判，也不是全集。** 它一个字都不删不加；代码认不出不等于帖里没有 ——
§4.1 的档位表与 §5.2 的映射表仍要模型自己会查。

这一层替模型省下的是**查表**：时间词翻档位、对象词翻指数，都是闭集上的死查。
条件词那一栏只列**按 §3.2 判得死的**那几句里的词 —— 拿不准的一律不列，宁可漏，
不许把「一旦缩量调整过后」这种像条件、其实不是的写法摆上去带偏模型。

**方向词那一栏只列原话、不给方向。** 词表里的值是词义层面的，句义层面的翻转仍归模型；
把值摆出来，模型多半会拿它当判决，而「不会大涨」这类正是词表出不了手的地方。
"""

from __future__ import annotations

import re

from blogger.common import market
from blogger.common.text import SEP, normalize, split_quote
from blogger.parse import lexicons

# 断句点：句末标点 ＋ 句内分号，**省略号不断**。这两条都是实测定的 —— 分号两侧常各是
# 一处完整表述，而省略号两侧是同一处（「明天大盘大概率高开……来回磨」）。别简化回只按
# 句末标点切。
SENT_END = re.compile(r"(?<=[。！？!?；;])")

FIELDS = ("title", "content")


def sentences(text: str) -> list[str]:
    """按句末标点与句内分号断句 —— **省略号不断**。纯函数，同一份输入逐字节相同。"""
    return [s for s in SENT_END.split(text or "") if s.strip()]


def _fill_year(spec: str, pub: str) -> str:
    """`d:MM-DD` 补上年份（§4.1）—— **补出来早于发帖日的，是明年那一个**。

    不补的话，摆出去的就是个缺年份的半截编码，模型照抄或自己猜年份，猜成过去年就被
    强校验按「是回顾不是预测」丢掉（§10.2）—— 那是静默的冤枉。
    """
    if not spec.startswith("d:") or len(spec) != 7:      # `d:09-20` 这个样子才是待补的
        return spec
    y, mmdd = pub[:4], spec[2:]
    cand = f"{y}-{mmdd}"
    return "d:" + (cand if cand >= pub[:10] else f"{int(y) + 1}-{mmdd}")


# ── 清单 ────────────────────────────────────────────────────────────────

def find_dir_words(text: str) -> list[tuple[int, str]]:
    """这一段里的方向词 —— `[(位置, 原话), …]`，按位置排。

    **同一位置取最长匹配** —— 「不会大涨」压过「大涨」压过「涨」。不做这一步的话，
    一处「不会大涨」会同时摆出三个词，其中两个方向相反。
    """
    hits: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for word in sorted(lexicons.DIR_WORDS, key=len, reverse=True):
        start = text.find(word)
        while start >= 0:
            if all(start + len(word) <= x or start >= y for x, y in taken):
                hits.append((start, word))
                taken.append((start, start + len(word)))
            start = text.find(word, start + 1)
    return sorted(hits)


def _values(hits: list[tuple[int, str, str]], pub: str) -> list[str]:
    """`[(位置, 原话, 值), …]` → `原话→值`，同一个词只留一次，照首次出现的先后排。"""
    out, seen = [], set()
    for _, word, value in hits:
        if word in seen:
            continue
        seen.add(word)
        out.append(f"{word}→{_fill_year(value, pub)}")
    return out


def _words(hits: list[tuple[int, str]]) -> list[str]:
    """`[(位置, 原话), …]` → 原话，同一个词只留一次。**不给值。**"""
    out, seen = [], set()
    for _, word in hits:
        if word not in seen:
            seen.add(word)
            out.append(word)
    return out


def hints_of(post: dict) -> str:
    """一条帖的「字面命中」清单，一行。**四栏都空就返回空串** —— 不摆一行空的。"""
    sents = [s for f in FIELDS for s in sentences(post.get(f) or "")]
    body = "\n".join(post.get(f) or "" for f in FIELDS)
    pub = post.get("pub") or ""

    times: list[tuple[int, str, str]] = []
    objs: list[tuple[int, str, str]] = []
    conds, seen_c = [], set()
    for s in sents:
        times += lexicons.find_time_words(s)
        objs += lexicons.find_objects(s)
        # 条件词只在**判得死的**那几句里收 —— `has_cond` 已经把七类「像条件、其实不是」抠掉了
        if lexicons.has_cond(s):
            for w in lexicons.COND_WORDS:
                if w in s and w not in seen_c:
                    seen_c.add(w)
                    conds.append(w)

    cols = [("时间词", _values(times, pub)), ("对象词", _values(objs, pub)),
            ("条件词", conds), ("方向词", _words(find_dir_words(body)))]
    if not any(items for _, items in cols):
        return ""
    return "[字面命中] " + " ｜ ".join(
        f"{name}：{'、'.join(items) if items else '无'}" for name, items in cols)


# ── 定位：引文落在的那几句（§10.5）────────────────────────────────────

def _around(post: dict, frag: str) -> tuple[str, list[str]] | None:
    """`frag` 落在这条帖的哪个字段、落在了哪几句上 —— 两处都落不到返回 `None`。"""
    for field in FIELDS:
        raw = sentences(post.get(field) or "")
        parts = [normalize(s) for s in raw]
        if not parts:
            continue
        body, offs = "", []
        for p in parts:
            offs.append((len(body), len(body) + len(p)))
            body += p + SEP
        at = body.find(frag)
        if at < 0:
            continue
        end = at + len(frag)
        return field, [s for s, (a, b) in zip(raw, offs) if a < end and at < b]
    return None


def cond_sentence(post: dict, quote: str) -> str:
    """`quote` 落在的那几句，拼成一份 —— **有一段落不到就返回空串**。

    引文允许不连续的两段拼起来（§9），所以逐段定位、各取落到的句子，合起来才是这一处
    表述的范围。归一之后位置才对得上（全角半角、空白都不算改写）。

    **只取引文落在的那些句子，不取两段之间的那一片** —— 「……」（省略号）在语料里常跨好几
    句，按首段到末段整片取的话，会把中间无关句子里的条件词也认成这一处的条件，实测就是这么
    冤枉的。筛不完可以，冤枉不行。

    **落不到的一律放行**：某一段在帖里搜不到、或几段分处 `title` 与 `content`（那就不是
    一句话了），都返回空串。
    """
    frags = [normalize(f) for f in split_quote(quote)]
    if not frags:
        return ""

    field, picked = None, []
    for frag in frags:
        hit = _around(post, frag)
        if hit is None:
            return ""
        if field is None:
            field = hit[0]
        elif hit[0] != field:            # 分处两个字段 —— 拼起来不是一句话，放行
            return ""
        picked += hit[1]

    seen, out = set(), []
    for s in picked:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return "".join(out)


# ── 查矛盾：产出与引文对不上的地方（§10.5）────────────────────────────

def contradiction(sig: dict) -> str | None:
    """产出与引文里的字面对不上的地方 —— 对不上返回理由，对得上返回 `None`。

    **只查 `idx` 与 `spec` 两栏。方向那一栏不查** —— 引文里的方向词是词义层面的值，
    句义层面的翻转（「不会大涨」「急跌是低吸机会」）归模型，字面反了不算数。2026-09-18
    在手上 2629 行活产出上量：方向那栏命中 345 条，逐条读完一条真错也没有；`idx` 与
    `spec` 两栏共命中 13 条，3 条是真错。

    **引文里查不出值的不算矛盾** —— 那是查不着，不是对不上（65% 的行引文里没有对象词，
    39% 没有时间词）。**产出 `long` 不算矛盾** —— 它是「20 个交易日以上」的开区间，
    引文里查得出某一天不等于与它冲突。

    **查出来的值只是提示，不作结论** —— 它是字面查的，自己也会错（`idx` 那 5 条命中里
    4 条的正则值是错的）。理由原样摆给模型，改不改由它（§10.5）。
    """
    quote = sig["quote"]

    objs = {idx for _, _, idx in lexicons.find_objects(quote)}
    if objs and sig["idx"] not in objs:
        return (f"引文里的对象词是「{'、'.join(sorted(objs))}」，"
                f"与产出的 idx「{sig['idx']}」对不上")

    if sig["spec"] == "long":          # 开区间 —— 引文里查出某一天不算冲突
        return None
    words = lexicons.find_time_words(quote)
    if not words:
        return None

    pub = sig["pub"]
    try:
        want = market.endpoint(pub, sig["spec"])
        cand = {market.endpoint(pub, _fill_year(v, pub)) for _, _, v in words}
    except RuntimeError:
        return None                    # 日历不可用，日子算不出来 —— 不判，放行
    cand.discard(None)
    if want is None or not cand or want in cand:
        return None
    return (f"引文里的时间词是「{'、'.join(w for _, w, _ in words)}」，"
            f"与产出的 spec「{sig['spec']}」（{want}）对不上")


def suspects(post: dict, rows: list[dict]) -> list[tuple[dict, str]]:
    """这一帖里该复核的每一处（§10.5）—— `[(产出, 理由), …]`，没有就返回空表。

    四种查法，两种只用引文（`idx`／`spec`，走 `contradiction`），一种要帖文（条件句），
    一种比产出与产出（同帖互斥）。**一处查出几条就并成一行** —— 同一处摆两条疑问，模型会
    当两处答。

    **只报不改、只报不丢**：这里一个字都不动产出，也一条都不删。
    """
    found: list[list] = []                       # [[产出, [理由, …]], …]，照产出首次出现的先后

    def add(sig: dict, why: str) -> None:
        for row in found:
            if row[0] is sig:
                row[1].append(why)
                return
        found.append([sig, [why]])

    for s in rows:
        why = contradiction(s)
        if why:
            add(s, why)

        sent = cond_sentence(post, s["quote"])
        parts = sentences(sent)
        if parts and all(lexicons.has_cond(x) for x in parts):
            add(s, f"引文所在的那整句是条件句（{sent[:40]}…），这一处却产了方向（§3.2）")

    groups: dict[tuple[str, str], list[dict]] = {}
    for s in rows:
        groups.setdefault((s["idx"], s["spec"]), []).append(s)
    for grp in groups.values():
        if len({s["d"] for s in grp}) < 2:
            continue
        for s in grp:
            peer = next(x for x in grp if x["d"] != s["d"])
            add(s, f"同一帖里 {s['idx']} {s['spec']} 还有方向相反的一条"
                   f"（{peer['d']:+d}｜{peer['quote'][:20]}…）（§6）")

    return [(sig, "；".join(whys)) for sig, whys in found]


__all__ = ["SENT_END", "sentences", "find_dir_words", "hints_of",
           "contradiction", "cond_sentence", "suspects"]
