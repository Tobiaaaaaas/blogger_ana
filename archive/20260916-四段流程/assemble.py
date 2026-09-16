# -*- coding: utf-8 -*-
"""③ 核与组装 —— 把模型的表态落成三元组。**零模型调用，也不改结论。**

这一层做的每一件事都是**机械的**：回原句里找字、查表翻档位、按句切引文。它不判断
「这一句该不该产」，那是模型判的；它只做 §10.2 说的**反向核对** —— 这一处的三元组
能不能由引文倒推出来。倒推不出来的丢掉，那正是 §3.4 定义的编造。

| 做什么 | 依据 | 越权了吗 |
|:---|:---|:---|
| `dw` 回**这一句**里找 | §3.4／§10.2 | 没有 —— 只判「在不在」 |
| `tw` 查 §4.1 表 | §4.1「引文里只有一个时间词时，这一格由代码查」 | 没有 |
| `ow` 查 §5.2 表 | 同上 | 没有 |
| 表里没有 → 采信模型给的档位／对象 | 有兜底，且**记一笔缺口** | 没有 |
| 表里也没有 → `t5`（§4.4）／上证指数（§5.4） | 02 的默认档，不是这里发明的 | 没有 |
| 守门 · 一：条件句产了方向 | §10.3「条件词 → 丢」 | 没有 —— **丢**，字面判得死 |
| 守门 · 二：负例词／模棱词、方向词表不一致、同帖骑墙 | §10.3「只丢，或标记待复核」 | 没有 —— 只标记 |

**守门的口径是「一定是错的」。** 代码这一层照字面砍，砍错了没有第二道能捞回来，所以
宁可筛不完，不许冤枉 —— 筛不掉的那几类（状态句、机制推演、观察句、否定翻转）照实留在
提示词里交给模型，不硬凑成规则。

**表里查不到时不许猜** —— 猜就是把「词典的漏」变成「信号的错」。这是这套设计与「完全靠
正则」的分界线：正则只用来**提示**，落档要么查表、要么采信模型、要么走 02 写明的默认档。
"""

from __future__ import annotations

from blogger.common import market
from blogger.parse import lexicons, schema

DEFAULT_SPEC_NO_TIME = "t5"       # §4.4：有方向、没给时间
DEFAULT_IDX_NO_OBJ = "上证指数"    # §5.4：没给点位、给了方向

QUOTE_LIMIT = schema.QUOTE_LIMIT


# ── 查表 ────────────────────────────────────────────────────────────────

def _fill_year(spec: str, pub: str) -> str:
    """`d:MM-DD` 补年份 —— 补出来早于发帖日的，是**明年**那一个（§4.3 的预测语境）。"""
    if not spec.startswith("d:") or len(spec) != 7:      # `d:09-20` 这个样子才是待补的
        return spec
    y, mmdd = pub[:4], spec[2:]
    cand = f"{y}-{mmdd}"
    return "d:" + (cand if cand >= pub[:10] else f"{int(y) + 1}-{mmdd}")


def resolve_time(tw: str, sentence: str, model_spec: str, pub: str) -> tuple[str, str]:
    """定 `spec`。返回 `(档位, 说明)`；说明非空表示这里是**有话说**的一处，进统计。

    先按 §4.1 由代码查 —— 模型指的 `tw` 命中表就采信；没指或表里没有，就看这一句自己有
    几个时间词：**一个**照表落（§4.1），**两个及以上**（区间、或「明天开始至本周五」）
    代码判不了，回模型给的 `spec`，它也没给才取**最后一个**（「区间的两头只算末」）。
    """
    note = ""
    if tw:
        spec = lexicons.spec_of_word(tw)
        if spec and tw in sentence and not lexicons.ma_artifact(sentence, tw):
            return _fill_year(spec, pub), ""
        if lexicons.ma_artifact(sentence, tw):
            note = f"`tw`『{tw}』后面跟的是均线名，不是时间窗口"
        else:
            note = f"时间词表里没有『{tw}』" if tw in sentence else f"`tw`『{tw}』不在这句里"

    hits = lexicons.find_time_words(sentence)
    # §4.1「明天压过周几」—— 同一处「明天」与「周五」指同一天时落 `t1`。兜底那句「取本句
    # 最后一个」会把「明天周五」判成 `friday`（实测 7 条里 4 条如此），所以先让 `t1` 把
    # 周几压掉，剩下的才轮到最后那个。
    if any(h[2] == "t1" for h in hits):
        rest = [h for h in hits if h[2] not in lexicons.WEEKDAYS]
        if rest:
            hits = rest
    if len(hits) == 1:
        return _fill_year(hits[0][2], pub), f"{note}；改按本句唯一时间词『{hits[0][1]}』" if tw else ""

    # 两个及以上（区间、或「明天开始至本周五」）代码判不了 → 回模型；它也没给才取最后一个
    if hits and model_spec and market.spec_ok(model_spec):
        return model_spec, f"{note}；本句 {len(hits)} 个时间词，采信模型给的『{model_spec}』"
    if hits:
        return _fill_year(hits[-1][2], pub), f"{note}；取本句最后一个时间词『{hits[-1][1]}』"
    if model_spec and market.spec_ok(model_spec):
        return model_spec, f"{note}；本句无时间词，采信模型给的『{model_spec}』"
    return DEFAULT_SPEC_NO_TIME, f"{note}；没给周期 → {DEFAULT_SPEC_NO_TIME}（§4.4）"


def resolve_obj(ow: str, sentence: str, model_idx: str) -> tuple[str, str]:
    """定 `idx`。同 `resolve_time` 的形状。**返回空串＝这一条不产。**

    模型指的 `ow` 命中 §5.2 表就采信；没指、或表里没有，就看这一句自己点名了哪个 ——
    **只点了一个**才由代码落，**点了两个及以上**（「上证明天涨，创业板这周看好」那样一句
    里并列）代码判不了，回模型给的 `idx`；都没有 → §5.4 默认上证指数。

    **点的是「其余板块」的不走 §5.4。** §5.4 管的是「未点名板块或指数」；一句里点了
    创新药／军工／有色，那是 §5.2 末行「其余板块一律忽略」＋ §6③「只谈行业板块」→
    这一条作废。落默认上证指数是把它抬成了对上证指数的预测，§6③ 明确说不要。
    """
    if ow:
        if ow in sentence:
            idx = lexicons.obj_of_word(ow)
            if idx:
                return idx, ""
            # 模型指的这个词本身就是「其余板块」（「低位板块」「硬科技股」）→ §5.2 末行，
            # 不产。**不能落到 §5.4 默认** —— §5.4 管的是「未点名板块或指数」，而这里是
            # 点了板块、只是点名的是一个不产的对象。落默认等于把它抬成了对上证的预测。
            sec = lexicons.sector_word(ow)
            if sec:
                return "", f"本句点的是板块『{sec}』、没点名指数 → 不产（§5.2 末行＋§6③）"
            note = f"对象词表里没有『{ow}』"
        else:
            note = f"`ow`『{ow}』不在这句里"
    else:
        note = ""

    hits = lexicons.find_objects(sentence)
    idxs = list(dict.fromkeys(i for _, _, i in hits))
    if len(idxs) == 1:
        return idxs[0], f"{note}；改按本句唯一对象词『{hits[0][1]}』" if note else ""

    if model_idx and market.normalize_idx(model_idx) in market.VALID_IDX:
        got = market.normalize_idx(model_idx)
        return got, f"{note}；本句 {len(idxs)} 个对象，采信模型给的『{got}』"
    if idxs:
        return idxs[0], f"{note}；取本句第一个对象词『{hits[0][1]}』"

    sec = lexicons.has_ignored_sector(sentence)
    if sec:
        return "", f"{note}；本句点的是板块『{sec}』、没点名指数 → 不产（§5.2 末行＋§6③）"
    return DEFAULT_IDX_NO_OBJ, f"{note}；没点名对象 → {DEFAULT_IDX_NO_OBJ}（§5.4）"


def quote_of(sentence: str, dw: str, limit: int = QUOTE_LIMIT) -> str:
    """引文 = 承载方向的那一句，超长时围着 `dw` 截一段。**截出来的仍是连着的原文**。"""
    if len(sentence) <= limit:
        return sentence
    i = sentence.find(dw) if dw else -1
    if i < 0:
        return sentence[:limit]
    mid = i + len(dw) // 2
    lo = max(0, mid - limit // 2)
    hi = min(len(sentence), lo + limit)
    return sentence[max(0, hi - limit):hi]


# ── 组装 ────────────────────────────────────────────────────────────────

def assemble(verdicts: list[dict], kept: list[dict], segs: list[dict[int, dict]]
             ) -> tuple[list[dict], list[dict], list[dict], dict]:
    """表态 → `(最终信号, 逐条审计行, 词典缺口, 计数)`。

    **审计行**是逐条表态的交代：产了没有、丢了是为什么、标记待复核的是哪一条。报告与
    `check` 的「零越权」断言都读它 —— 最终信号里看不到被丢掉的那些，只有这里说得清。
    """
    rows: list[dict] = []
    made: list[dict] = []        # 产出的那些行 —— 骑墙那道要回头看整帖
    gaps: list[dict] = []
    raw_signals: list[dict] = []
    tally = {"表态": len(verdicts), "产": 0, "丢": 0, "非信号": 0, "无格": 0,
             "待复核": 0, "缺口": 0}

    for v in verdicts:
        post, sent = kept[v["p"]], segs[v["p"]][v["s"]]
        base = {"p": v["p"], "s": v["s"], "post_id": post["post_id"], "pub": post["pub"],
                "text": sent["text"], "marks": sent["marks"], "d": v["d"],
                "dw": v["dw"], "ow": v["ow"], "tw": v["tw"], "why": v["why"],
                # 模型自己给的兜底值 —— 记下来，「零越权」断言要拿它复算
                "模型spec": v["spec"], "模型idx": v["idx"]}

        if v["d"] == 0:
            # `zeros` 那一栏 —— 模型把这一句归到了 §6 的哪一格。**不进信号，但格名要
            # 留痕**：这份按格名的分布就是提示词与词典的下一步（哪一格最多就攻哪一格）。
            tally["非信号"] += 1
            if not v["why"]:
                tally["无格"] += 1
            rows.append({**base, "处置": "非信号", "说明": v["why"]})
            continue

        # §3.4／§10.2：方向词必须回**这一句**里搜得到。搜不到 = 编造 → 丢掉
        if not v["dw"] or v["dw"] not in sent["text"]:
            tally["丢"] += 1
            rows.append({**base, "处置": "丢", "说明": "方向词不在这句里（§3.4 编造）"})
            continue

        spec, n1 = resolve_time(v["tw"], sent["text"], v["spec"], post["pub"])
        idx, n2 = resolve_obj(v["ow"], sent["text"], v["idx"])
        if not idx:                      # 点的是「其余板块」→ 这一条不产（§5.2 末行）
            tally["丢"] += 1
            rows.append({**base, "处置": "丢", "说明": n2, "spec": spec, "idx": ""})
            continue
        quote = quote_of(sent["text"], v["dw"])

        # 缺口 —— 模型答出表里没有的词，是**词典缺口的信号**，不是它的错
        for kind, word, table in (("时间词", v["tw"], lexicons.spec_of_word),
                                  ("对象词", v["ow"], lexicons.obj_of_word)):
            if word and word in sent["text"] and table(word) is None:
                gaps.append({"类": kind, "词": word, "post_id": post["post_id"],
                             "pub": post["pub"], "句": sent["text"]})
                tally["缺口"] += 1
        if v["dw"] not in lexicons.DIR_WORDS:
            gaps.append({"类": "方向词", "词": v["dw"], "post_id": post["post_id"],
                         "pub": post["pub"], "句": sent["text"]})
            tally["缺口"] += 1

        sig, why = schema.to_signal({"d": v["d"], "spec": spec, "idx": idx, "quote": quote}, post)
        if sig is None:
            tally["丢"] += 1
            rows.append({**base, "处置": "丢", "说明": why, "spec": spec, "idx": idx,
                         "quote": quote, "查表": "；".join(x for x in (n1, n2) if x)})
            continue

        # 守门 · 一 —— 条件句（§3.2）产了方向，**直接丢**。这一条是那张单子上唯一一条只靠
        # 认字面就判得死的。口径见 `lexicons.has_cond`：七类「像条件、其实不是」的写法
        # 逐类排除，**宁可筛不完，不许冤枉**。
        if "!" in sent["marks"]:
            tally["丢"] += 1
            rows.append({**base, "处置": "丢", "spec": spec, "idx": idx, "quote": quote,
                         "说明": "条件句 —— 方向挂在博主没承诺会发生的前提上（§3.2）",
                         "查表": "；".join(x for x in (n1, n2) if x)})
            continue

        # 守门 · 二 —— 剩下的几类**字面判不死，只标记，不改、不丢**
        notes = [x for x in (n1, n2) if x]
        if "x" in sent["marks"] or "~" in sent["marks"]:
            notes.append("带负例词／模棱词（§6）却产了方向 —— 待复核")
        if lexicons.DIR_WORDS.get(v["dw"], v["d"]) != v["d"]:
            notes.append(f"方向词『{v['dw']}』表里是 {lexicons.DIR_WORDS[v['dw']]:+d}、"
                         f"模型判的是 {v['d']:+d} —— 待复核")
        note = "；".join(notes).lstrip("；")
        if note:
            tally["待复核"] += 1
        row = {**base, "处置": "产", "说明": note, "spec": spec,
               "idx": idx, "quote": quote, "查表": ""}
        tally["产"] += 1
        raw_signals.append(sig)
        rows.append(row)
        made.append(row)

    # 骑墙 —— 同一帖、同一对象、同一周期，正反各产了一条（§6）。**只标记，不丢**
    seen_dir: dict[tuple, set] = {}
    for r in made:
        seen_dir.setdefault((r["post_id"], r["idx"], r["spec"]), set()).add(r["d"])
    for r in made:
        if len(seen_dir[(r["post_id"], r["idx"], r["spec"])]) > 1:
            if not r["说明"]:
                tally["待复核"] += 1
            r["说明"] = (r["说明"] + "；同帖同对象同周期正反都说了（§6 骑墙）—— 待复核").lstrip("；")

    signals, dups = schema.dedup_with_dropped(raw_signals, kept)
    tally["去重"] = len(dups)
    tally["产"] = len(signals)
    # `待复核` 数的是**留下来的那些** —— 逐行累加会出现「待复核 1927 > 产 1781」这种读不通
    # 的账。口径跟 `产` 对齐：都数去重后的。
    live = {schema.key_of(s) for s in signals}
    tally["待复核"] = sum(1 for r in made
                          if "待复核" in r["说明"] and (r["post_id"], r["idx"], r["spec"], r["d"]) in live)
    for s in dups:
        rows.append({"p": None, "s": None, "post_id": s["post_id"], "pub": s["pub"],
                     "text": "", "marks": "", "d": s["d"], "dw": "", "ow": "", "tw": "",
                     "why": "", "模型spec": "", "模型idx": "", "处置": "去重",
                     "说明": f"{s['idx']} {s['spec']}｜{s['quote'][:20]}…"})

    signals.sort(key=lambda s: (s["pub"], s["post_id"], s["idx"], s["spec"]))
    return signals, rows, gaps, tally


__all__ = ["assemble", "resolve_time", "resolve_obj", "quote_of",
           "DEFAULT_SPEC_NO_TIME", "DEFAULT_IDX_NO_OBJ"]
