# -*- coding: utf-8 -*-
"""探针 —— 同一个请求原样发 N 次，看服务端到底飘在哪一层。

这一跑回答两件事，两件都决定后面能走哪条路：

| 问的 | 看什么 | 决定了 |
|:---|:---|:---|
| 带同一个 `seed` 两次结果相同吗 | 逐字节相同的次数 | 采样层飘就加一行解决；内核／批调度层飘则采样参数全无效 |
| 每句的票型是 8:0 还是 5:3 | 逐句的表态分布 | 多数票压不压得住 —— **p≈0.5 的句子投票一点用没有** |

`ds.call_json` 不传 `seed`，也不该为一次实验去改 `blogger/` —— 所以这里自己建 client，
其余参数（`temperature=0`、`max_tokens=8192`、`thinking` 关、硬性超时）逐项照抄，
免得「参数不同」混进差异里。

**只读、只调模型，不写任何产物到 `data/`。**
"""

from __future__ import annotations

import time
from collections import Counter

from blogger.common import ds
from blogger.parse import annotate, prompts, segment

from research.semparse import runner


def _call(user_text: str, seed: int | None, label: str) -> tuple[str, dict | None]:
    """照抄 `ds.call_json` 的参数发一次，多一个可选的 `seed`。返回 `(原文, 解析后)`。"""
    from openai import OpenAI

    body: dict = {"thinking": {"type": "disabled"}}
    if seed is not None:
        body["seed"] = seed
    client = OpenAI(api_key=__import__("os").environ["DEEPSEEK_API_KEY"],
                    base_url=ds.BASE_URL, timeout=ds.CALL_DEADLINE)
    r = client.chat.completions.create(
        model=ds.MODEL,
        messages=[{"role": "system",
                   "content": prompts.ANNOTATION_SYSTEM_PROMPT},
                  {"role": "user", "content": user_text}],
        temperature=0,
        max_tokens=8192,
        extra_body=body,
    )
    raw = r.choices[0].message.content or ""
    return raw, ds.parse_json(raw)


def _verdicts(parsed: dict | None, n: int, segs) -> dict[tuple[int, int], str]:
    """一次返回 → `{(帖号, 句号): 表态}`。表态是 `产` 或 `不产/格名`。"""
    if not parsed:
        return {}
    rows, _ = annotate._parse_verdicts(parsed, n, segs)
    out: dict[tuple[int, int], str] = {}
    for r in rows:
        out[(r["p"], r["s"])] = f"产 {r['d']:+d}" if r["d"] else f"不产 {r['why'] or '无格'}"
    return out


def run(name: str, batch: int = 1, times: int = 8, seed: int = 20260916,
        log=print) -> dict:
    """一位博主的一批，发 `times` 次 —— 前半不带 `seed`、后半带同一个 `seed`。"""
    _, _, batches = runner._batches(name)
    if not batches:
        raise SystemExit(f"{name} 一批都没有")
    pick = batches[min(batch, len(batches)) - 1]
    user_text, kept, segs = segment.render_batch(pick)
    n = len(kept)
    half = times // 2

    log(f"{name} 第 {batch}/{len(batches)} 批：{n} 帖、{sum(len(x) for x in segs)} 句")
    log(f"不带 seed 发 {half} 次、带 seed={seed} 发 {times - half} 次\n")

    runs: list[dict] = []
    raws: list[str] = []
    for i in range(times):
        s = None if i < half else seed
        t0 = time.time()
        try:
            raw, parsed = _call(user_text, s, f"探针 {i + 1}")
        except Exception as e:
            log(f"  第 {i + 1} 次 seed={'无' if s is None else s} 没调通：{e!r}")
            continue
        runs.append({"seed": s, "v": _verdicts(parsed, n, segs),
                     "n产": sum(1 for x in (parsed or {}).get("signals") or [])})
        raws.append(raw)
        log(f"  第 {i + 1} 次 seed={'无' if s is None else s}"
            f" → 产 {runs[-1]['n产']} 条、表态 {len(runs[-1]['v'])} 句"
            f"、{len(raw)} 字、{time.time() - t0:.0f}s")

    return {"name": name, "批次": batch, "帖": n, "segs": segs,
            "句": sum(len(x) for x in segs), "runs": runs, "raws": raws}


def report(r: dict, log=print) -> None:
    runs, raws = r["runs"], r["raws"]
    if len(runs) < 2:
        log("跑成的次数不够两次，比不了。")
        return
    half = len(runs) // 2

    log("\n" + "═" * 62)
    log("① 原样重发：得到的回答一样吗")
    uniq = len(set(raws))
    log(f"  {len(raws)} 次回答里，逐字节不同的有 {uniq} 种"
        f"（每一种各出现 {sorted(Counter(raws).values(), reverse=True)} 次）")
    a = len(set(raws[:half]))
    b = len(set(raws[half:]))
    log(f"  不带 seed 的 {half} 次：{a} 种｜带同一 seed 的 {len(raws) - half} 次：{b} 种")
    if b == 1 and a > 1:
        log("  → **seed 管用**：同 seed 同输入得到同一份回答。")
    elif b > 1:
        log("  → **seed 不管用**：同 seed 也飘。飘在内核／批调度层，采样参数救不了。")
    else:
        log("  → 不带 seed 就稳定了 —— 与先前测到的相反，得复核。")

    log("\n" + "═" * 62)
    log("② 逐句票型：多数票压不压得住")
    keys = set()
    for x in runs:
        keys |= set(x["v"])
    vote: Counter = Counter()
    flip = 0
    for k in keys:
        vs = [x["v"].get(k) for x in runs]
        # 「产」的票数 —— 只有产/不产翻转才是投票要压的那一类
        p = sum(1 for v in vs if v and v.startswith("产"))
        vote[(p, len(runs))] += 1
        if p and p != len(runs):
            flip += 1
    tot = len(keys)
    log(f"  表态过的句 {tot}｜产／不产 投不一致的 {flip} 条（{flip * 100 / max(1, tot):.1f}%）")
    log(f"  {'产票':>4} / {len(runs)}  {'句数':>6}")
    for p in range(len(runs) + 1):
        c = vote[(p, len(runs))]
        if c:
            log(f"  {p:>4} / {len(runs)}  {c:>6}    {'█' * min(40, c)}")

    log("\n" + "═" * 62)
    log("③ 投票到底买多少 —— 按实测 p 算「两套独立投票之间仍不一致」的比例")
    log(f"  {'方案':<12}{'每句不一致':>10}{'相对单遍':>10}")
    base = 0.0
    table = []
    for k, m in ((1, 1), (3, 2), (5, 3), (7, 4)):
        tot_k = 0.0
        for (pv, _), cnt in vote.items():
            p = pv / len(runs)
            q = _at_least(k, m, p) if k > 1 else p
            tot_k += cnt * 2 * q * (1 - q)
        if k == 1:
            base = tot_k
        table.append((k, tot_k))
    for k, v in table:
        log(f"  {'单遍' if k == 1 else f'{k} 遍取多数':<12}{v:>10.2f}{'——' if k == 1 else f'{(v / base - 1) * 100:>+9.0f}%'}")

    log("\n" + "═" * 62)
    log("④ 不稳的是哪些句 —— 有没有共同的**字面特征**")
    segs = r["segs"]
    rows = []
    for k in sorted(keys):
        vs = [x["v"].get(k) for x in runs]
        p = sum(1 for v in vs if v and v.startswith("产"))
        if p and p != len(runs):
            sent = segs[k[0]].get(k[1]) or {}
            rows.append((p, k, sent.get("marks", ""), sent.get("text", "")))
    rows.sort(key=lambda x: x[0])
    for p, k, marks, text in rows:
        log(f"  {p}/{len(runs)}  帖{k[0]:>2}.{k[1]:<3} [{marks or '无标记':<6}] {text[:52]}")
    if not rows:
        return
    log("")
    m = Counter(mk for _, _, mk, _ in rows)
    log(f"  这些句的标记：{'／'.join(f'{k or chr(0x65e0)} {v}' for k, v in m.most_common())}")
    log(f"  同一批全部 340 句里，带标记的占 "
        f"{sum(1 for pp in segs for ss in pp.values() if ss['marks']) * 100 / max(1, tot):.0f}%")


def _at_least(k: int, m: int, p: float) -> float:
    """`P(X ≥ m)`，`X ~ Binom(k, p)` —— 多数票判「产」的概率。"""
    from math import comb
    return sum(comb(k, i) * p ** i * (1 - p) ** (k - i) for i in range(m, k + 1))


def voted(runs: list[dict], idx: list[int], m: int) -> dict[int, frozenset]:
    """`idx` 这几遍取多数（≥`m` 票算产）→ `{帖号: 产出的句号集合}`。

    **投票是纯代码，逐字节可复现** —— 给定这几遍的输入，出来的一定是同一份。
    所以它压的是「不同遍之间」的差，压不掉的是「p 就在半数附近」那些句。
    """
    out: dict[int, set] = {}
    keys = set()
    for i in idx:
        keys |= set(runs[i]["v"])
    for k in keys:
        if sum(1 for i in idx if runs[i]["v"].get(k, "").startswith("产")) >= m:
            out.setdefault(k[0], set()).add(k[1])
    return {p: frozenset(s) for p, s in out.items()}


def _pairs(n: int, k: int) -> list[tuple[list[int], list[int]]]:
    """从 `n` 遍里取**所有互不相交的 k 元组对** —— 两套独立投票。"""
    from itertools import combinations
    out = []
    for a in combinations(range(n), k):
        rest = [i for i in range(n) if i not in a]
        for b in combinations(rest, k):
            out.append((list(a), list(b)))
    return out


def vote_at_post(r: dict, log=print) -> None:
    """帖级：两套独立投票之间，有多少帖的输出集合不一样。**实测，不外推。**"""
    runs, n = r["runs"], len(r["runs"])
    segs = r["segs"]
    log("\n" + "═" * 62)
    log("⑤ 帖级：投票之后，两套独立投票之间还有多少帖对不上（实测）")
    log(f"  {'方案':<12}{'帖级不一致':>12}{'相对单遍':>10}{'对数':>8}")
    base = 0.0
    for k, m in ((1, 1), (2, 2), (3, 2), (4, 3)):
        ps = _pairs(n, k)
        bad = tot = 0
        for a, b in ps:
            va, vb = voted(runs, a, m), voted(runs, b, m)
            for p in set(va) | set(vb):
                tot += 1
                if va.get(p, frozenset()) != vb.get(p, frozenset()):
                    bad += 1
        rate = bad * 100 / max(1, tot)
        if k == 1:
            base = rate
        log(f"  {'单遍' if k == 1 else f'{k} 遍取多数':<12}{rate:>11.1f}%"
            f"{'——' if k == 1 else f'{(rate / base - 1) * 100:>+9.0f}%'}{len(ps):>8}")


__all__ = ["run", "report", "vote_at_post"]
