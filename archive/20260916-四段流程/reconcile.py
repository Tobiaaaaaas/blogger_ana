# -*- coding: utf-8 -*-
"""第三轮 —— 两遍对不上的帖，逐条复核。**只判候选，不添新项。**

两遍跑完，逐帖比三元组：**一样的直接采信，不再调模型**；不一样的（一遍说算、另一遍不说，
或者方向／周期／对象给得不一样）才交到这里。复核问的不是「哪一遍对」，是**每一处候选
自己该不该算** —— 所以两遍各自挑出来的句子是**平看**的：

| 第三轮说 | 结果 |
|:---|:---|
| 算 | 留下（**不管是哪一遍挑出来的**） |
| 不算 | 丢掉，并归到 §6 的某一格 |

**并集就是从这个「逐条判」里自然出来的** —— 甲组那些「两遍都产了、其实都不该产」的被
拦下，而「一遍产、另一遍漏了」的那一句照样能留下。旧流程的第三次调用问的是「这两份哪份
对」，二选一，于是「两遍都漏」与「两遍都错」它一个都救不了；这里问的是「这一句本身算不
算」，两遍都错也拦得住、一边漏了也捞得回。

**候选名单只给句子编号，不给两遍的答案。** 这一条是实测定的：框定会压过规则 —— 把两遍
的 `d`／周期／对象摆在眼前，模型多半照着抄；只给句子，它就只剩「读原句」这一条路。

**候选之外的句子一句都不收**（记 `越界`）—— 否则这一轮就成了第三次独立跑，「复核」与
「再判一遍」的差别、以及它比第三遍多买到了什么，都量不出来了。
"""

from __future__ import annotations

from typing import NamedTuple

from blogger.common import ds, market

from research.semparse import annotate, assemble, prompts, segment

# 一次调用判几条分歧帖。判比跑轻（输出只有几处候选），但**输入省不下** ——
# 每一条候选都要连着整帖读，否则骑墙、跨句、模棱这些判不了。所以比 ① 的
# `parse.batch_size=15` 小，六条一调。
PER_CALL = 6

# 缺候选重问的次数。**沉默不重问、空壳重问** 是 ① 定的规矩；这里「缺候选」更像空壳
# —— 模型漏写一格，多半是这一次没写全，而不是判不出来。
MISS_RETRY = 2


class Round(NamedTuple):
    verdicts: list[dict]
    kept: list[dict]
    segs: list[dict[int, dict]]
    tally: dict
    ok: bool


# ── 找分歧 ──────────────────────────────────────────────────────────────

def triples(signals: list[dict]) -> list[tuple]:
    return sorted((s["d"], s["spec"], s["idx"]) for s in signals)


def split(docA: dict, docB: dict, name: str) -> tuple[list[str], list[str]]:
    """一位博主 → `(对上的帖, 对不上的帖)`。

    **只比三元组，不比引文。** 「同一处、引了帖里不同的那一句」不算分歧 —— 引文是代码按
    `dw` 从原句切出来的，两遍截在不同处而已，为它多调一次模型不值。三元组一样就是同一
    条信号，采信先来的那一遍。
    """
    A, B = docA.get(name) or {}, docB.get(name) or {}
    same, diff = [], []
    for pid in sorted(set(A) | set(B)):
        if pid.startswith("__"):
            continue
        a = (A.get(pid) or {}).get("signals") or []
        b = (B.get(pid) or {}).get("signals") or []
        (same if triples(a) == triples(b) else diff).append(pid)
    return same, diff


def sentences_of(posts: dict[str, dict]) -> dict[str, dict[str, int]]:
    """`{post_id: {原话: 句号}}` —— 审计行里记的是原话，复核要点名的是句号，靠这张表对。

    切句是纯函数、与 ① 用的是同一个，所以两边的句号必然对得上。
    """
    return {pid: {r["text"]: r["s"] for r in segment.segment_post(post)}
            for pid, post in posts.items()}


def candidates(docA: dict, docB: dict, name: str, pid: str,
               table: dict[str, int]) -> dict[int, str]:
    """这一帖的候选 → `{句号: 原话}`，**两遍挑出来的并集，按句号合**。

    两遍可以指着同一句给不同的方向／周期 —— 那算**一个**候选：句子是判的对象，三元组是
    判出来的结果，所以这里按句号合、不按三元组合。同一轮里同一句出两条（不同对象、不同
    周期）在实测的 793 条产出里一处都没有，所以「一个候选出一个三元组」这条前提成立。
    """
    texts: set[str] = set()
    for doc in (docA, docB):
        for r in (doc.get(name) or {}).get("__审计__") or []:
            if r["post_id"] == pid and r["处置"] == "产":
                texts.add(r["text"])
    return {table[t]: t for t in texts if t in table}


# ── 调用 ────────────────────────────────────────────────────────────────

def _render(posts: list[dict], cands: dict[str, dict[int, str]]
            ) -> tuple[str, list[dict], list[dict[int, dict]]]:
    """渲染一批分歧帖 —— 帖照 ① 的样子渲染，末尾多一行 `[候选]` 的句子编号。"""
    blocks, kept, segs = [], [], []
    for post in posts:
        note = market.pub_note(post["pub"])
        if note is None:
            continue
        rows = segment.segment_post(post)
        if not rows:
            continue
        n = len(kept)
        ids = " ／ ".join(f"{n}.{s}" for s in sorted(cands.get(post["post_id"]) or {}))
        blocks.append(segment.render_post(n, post, note, rows) + f"\n[候选] {ids}")
        kept.append(post)
        segs.append({r["s"]: r for r in rows})
    return "\n\n".join(blocks), kept, segs


def judge(posts: list[dict], cands: dict[str, dict[int, str]], label: str = "") -> Round:
    """判一批分歧帖。返回的形状跟 `annotate.Batch` 一样 —— 下游就是同一套组装。"""
    if not posts:
        return Round([], [], [], {}, True)

    text, kept, segs = _render(posts, cands)
    if not kept:
        return Round([], [], [], {"跳过": len(posts), "原因": "行情注记取不到"}, True)

    want = {(p, s) for p, post in enumerate(kept)
            for s in (cands.get(post["post_id"]) or {})}
    tally: dict = {"帖": len(kept), "候选": len(want), "越界": 0}
    verdicts: list[dict] = []

    attempt = 0
    while True:
        attempt += 1
        try:
            result = ds.call_json(prompts.RECONCILE_PROMPT, text,
                                  f"{label} 复核{attempt}" if attempt > 1 else f"{label} 复核")
        except ds.ModelError as e:
            tally["失败"] = str(e)
            return Round([], kept, segs, tally, False)

        got, st = annotate._parse_verdicts(result, len(kept), segs)
        verdicts = [v for v in got if (v["p"], v["s"]) in want]
        tally["越界"] = len(got) - len(verdicts)
        miss = want - {(v["p"], v["s"]) for v in verdicts}
        tally.update({k: v for k, v in st.items() if k != "沉默"})
        if not miss or attempt >= MISS_RETRY:
            break
        tally["补问"] = f"缺 {len(miss)} 处，第 {attempt} 次重问"

    # 缺候选 —— **记名，不整批丢掉**，与 ① 的「沉默」同一条规矩。缺的那一处**按「没表态」
    # 处理**（不进 `signals`、也不进 `zeros`），其余候选照常。缺一个候选就作废一整批，会
    # 让「一批失败不许牵连其余」这条白写：实测 `--scope all` 一次跑下来 24 帖就是这么没的
    # ——而它们丢的其实只是一处候选。
    tally["缺候选"] = len(miss)
    tally["缺候选帖"] = len({p for p, _ in miss})
    tally["表态"] = len(verdicts)
    tally["判算"] = sum(1 for v in verdicts if v["d"])
    tally["判不算"] = len(verdicts) - tally["判算"]
    tally["重试"] = attempt - 1
    return Round(verdicts, kept, segs, tally, True)


# ── 合并 ────────────────────────────────────────────────────────────────

def _tally(rows: list[dict], gaps: list[dict], base: dict, live_signals: list[dict],
           rec: dict) -> dict:
    """合并稿的总账 —— **从审计行重算**，不拿第一遍的账改。

    第一遍的账是按批累加的，换掉一帖之后没法从里面扣；审计行是**逐条**落的，哪一帖的
    贡献都数得清。口径与 ① 逐项对齐（`产` 数去重后、`待复核` 只数留下来的那些），
    对不上的话 `check` 那一栏看得出来。
    """
    from collections import Counter

    n = Counter(r["处置"] for r in rows)
    live = {(r["post_id"], r["idx"], r["spec"], r["d"]) for r in live_signals}
    t = {k: base.get(k, 0) for k in ("帖", "可判", "批", "沉默", "沉默批", "重试",
                                     "码外", "失败批")}
    t["产"] = n["产"] - n["去重"]
    t["丢"] = n["丢"]
    t["非信号"] = n["非信号"]
    t["无格"] = sum(1 for r in rows if r["处置"] == "非信号" and not r["说明"])
    t["待复核"] = sum(1 for r in rows if r["处置"] == "产" and "待复核" in r["说明"]
                      and (r["post_id"], r["idx"], r["spec"], r["d"]) in live)
    t["去重"] = n["去重"]
    t["缺口"] = len(gaps)
    t.update(rec)
    return t


# 从审计行重算得出来的那几项 —— 其余（沉默／重试／批）是调用侧的事，行里没有
_DERIVED = ("产", "丢", "非信号", "无格", "待复核", "去重", "缺口")


def verify(doc: dict, name: str) -> dict:
    """拿一位博主**自己的**审计行重算一遍总账，跟它存的对不对得上。

    这一步是合并稿那本账的**地基检查** —— 合并稿的账就是从审计行重算的，要是重算在
    第一遍自己的产物上就对不上，那合并稿的账也不可信。对不上的项原样报出来。
    """
    base = (doc.get(name) or {}).get("__tally__") or {}
    rows = (doc.get(name) or {}).get("__审计__") or []
    gaps = (doc.get(name) or {}).get("__缺口__") or []
    sigs = [s for pid, p in (doc.get(name) or {}).items() if not pid.startswith("__")
            for s in (p.get("signals") or [])]
    got = _tally(rows, gaps, base, sigs, {})
    return {k: (base.get(k, 0), got.get(k, 0)) for k in _DERIVED
            if base.get(k, 0) != got.get(k, 0)}


def run(docA: dict, docB: dict, name: str, posts: dict[str, dict], log=print,
        limit: int = 0, scope: str = "diff", per_call: int = PER_CALL
        ) -> tuple[dict, dict]:
    """一位博主的复核 —— 返回 `(合并稿的一位, 复核记录)`。

    `scope` 定**谁进第三轮**，其余一字不动：

    | scope | 送审的帖 | 那么 |
    |:---|:---|:---|
    | `diff` | 两遍三元组对不上的 | 对上的原样采信第一遍，一次模型都不调 |
    | `all` | **凡产过一条的帖都送** | 对上的也送 —— 逐条再查一遍 |

    `all` 是为了一件事：**两遍同向的错，`diff` 结构上碰不到**。两遍都读错同一句、给出
    同一个三元组，它在 `diff` 眼里就是「对上了」—— 实测判例里剩下的甲组几条全是这一类。
    代价是调用数翻倍（送审的帖从两成变成六成），换来的是「复核」这件事真的覆盖了产出。

    `limit` 只截**送第三轮的那一批**，试跑用。
    """
    same, diff = split(docA, docB, name)
    A = docA.get(name) or {}
    B = docB.get(name) or {}

    if scope == "all":
        # 产过至少一条的帖 —— 一条没产的帖，两遍都没什么可复核的
        todo = [pid for pid in same + diff
                if (A.get(pid) or {}).get("signals") or (B.get(pid) or {}).get("signals")]
        carry = [pid for pid in same + diff if pid not in set(todo)]
    else:
        todo = [pid for pid in diff]
        carry = list(same)

    gone = [pid for pid in todo if pid not in posts]
    todo = [pid for pid in todo if pid in posts]
    if gone:
        carry += gone
    if limit:                                # 试跑：没轮到的照第一遍搬过来，账才平
        carry, todo = carry + todo[limit:], todo[:limit]

    table = sentences_of({pid: posts[pid] for pid in todo})
    out: dict = {}
    audit: list[dict] = []
    gaps: list[dict] = []
    rec: dict = {"对上": len(same), "分歧": len(diff), "送审": len(todo), "采信": 0,
                 "第三轮批": 0, "失败批": 0, "失败帖": 0, "越界": 0, "缺候选": 0,
                 "缺候选帖": 0, "判算": 0, "判不算": 0, "逐帖": []}

    # 不送审的帖（`diff` 口径下就是对上的那些）：采信第一遍，审计行与缺口一起搬过来
    for pid in carry:
        hit = A.get(pid) or B.get(pid)
        if hit is not None:
            out[pid] = hit
    for r in A.get("__审计__") or []:
        if r["post_id"] in out and r["post_id"] not in set(todo):
            audit.append(r)
    for g in A.get("__缺口__") or []:
        if g["post_id"] in out and g["post_id"] not in set(todo):
            gaps.append(g)
    # 没送审、又确实产了东西的帖 —— **`diff` 口径下这就是「采信第一遍」**，是设计如此；
    # `all` 口径下它只剩「两遍都没产出」的帖，是 0。两个口径一比就知道覆盖面差多少。
    rec["采信"] = len([p for p in carry if (A.get(p) or {}).get("signals")
                      or (B.get(p) or {}).get("signals")])
    if gone:
        rec["失败帖"] += len(gone)          # 帖取不到 —— 判不了，也不许当成「不产」
    for i in range(0, len(todo), per_call):
        chunk = todo[i:i + per_call]
        cands = {pid: candidates(docA, docB, name, pid, table.get(pid) or {})
                 for pid in chunk}
        bi = i // per_call + 1
        n_batch = (len(todo) + per_call - 1) // per_call
        r = judge([posts[pid] for pid in chunk], cands, label=f"{name} 复核{bi}/{n_batch}")
        rec["第三轮批"] += 1
        rec["越界"] += r.tally.get("越界", 0)
        rec["缺候选"] += r.tally.get("缺候选", 0)
        rec["缺候选帖"] += r.tally.get("缺候选帖", 0)
        if not r.ok:
            rec["失败批"] += 1
            rec["失败帖"] += len(r.kept)
            log(f"    复核 {bi}/{n_batch} 没判成：{r.tally.get('失败', '')[:120]}")
            for p in r.kept:
                rec["逐帖"].append({"post_id": p["post_id"], "第三轮": "失败",
                                    "候选": len(cands.get(p["post_id"]) or {})})
            continue

        signals, rows, batch_gaps, at = assemble.assemble(r.verdicts, r.kept, r.segs)
        audit += rows
        gaps += batch_gaps
        rec["判算"] += r.tally.get("判算", 0)
        rec["判不算"] += r.tally.get("判不算", 0)
        by_post: dict[str, list[dict]] = {}
        for s in signals:
            by_post.setdefault(s["post_id"], []).append(s)
        for p in r.kept:
            pid = p["post_id"]
            out[pid] = {"pub": p["pub"], "signals": by_post.get(pid, [])}
            rec["逐帖"].append({
                "post_id": pid, "第三轮": "成",
                "候选": len(cands.get(pid) or {}),
                "第一遍": [f"{d:+d}/{s}/{i}" for d, s, i in
                          triples((A.get(pid) or {}).get("signals") or [])],
                "第二遍": [f"{d:+d}/{s}/{i}" for d, s, i in
                          triples((B.get(pid) or {}).get("signals") or [])],
                "复核": [f"{d:+d}/{s}/{i}" for d, s, i in triples(out[pid]["signals"])]})
        log(f"    复核 {bi}/{n_batch} → 判算 {r.tally.get('判算', 0)}"
            f"／判不算 {r.tally.get('判不算', 0)}（越界 {r.tally.get('越界', 0)}）")

    bad = verify(docA, name)
    if bad:
        rec["总账对不上"] = bad
        log(f"    ⚠ 第一遍自己的总账重算不上：{bad}")

    run_sig = [s for pid in out for s in (out[pid].get("signals") or [])]
    tid = (docA.get(name) or {}).get("__tally__") or {}
    merged = dict(out)
    merged["__tally__"] = _tally(audit, gaps, tid, run_sig, rec)
    merged["__审计__"] = audit
    merged["__缺口__"] = gaps
    merged["__复核__"] = rec
    return merged, rec


__all__ = ["Round", "judge", "split", "candidates", "triples", "sentences_of",
           "run", "verify", "PER_CALL", "MISS_RETRY"]
