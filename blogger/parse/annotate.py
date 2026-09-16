# -*- coding: utf-8 -*-
"""② 逐句表态 —— **一批调用一次**。

这一层只做三件事：把批渲染出来、调模型、把「有没有沉默」查出来。

**「不许沉默」是这套流程的召回保险。** 带 `T` 或 `D` 的句子缺表态，这次调用就不算成 ——
先重试；重试后仍缺，就把缺的记下来、照常往下走，**不整批丢掉**。模型可以判错，但不能
假装没读到。

**跑几遍由调用方定**（02§10.2）。第 2 遍起把上一遍的表态原样接在批文本后面（`tail`），
让它在同一批原文上再判一次 —— 以最后一遍为准。`block()` 就是那个「接在后面的那一块」。
"""

from __future__ import annotations

from typing import NamedTuple

from blogger.common import ds
from blogger.parse import prompts, segment

# 因「沉默」重问整批的次数。**定为 1 ＝ 不重问**，是实测定的：一批 230 句该表态，
# 第一遍沉默 6 句，重问一遍沉默 23 句 —— 重问既没修好，又把调用翻了一倍，而那正是这
# 套流程要避免的。所以沉默**只记名、不重问**，当作一个可量化的质量指标报出去。
# 传输失败的重试在 `ds.call_json` 里，不占这个额度。
SILENCE_RETRY = 1

# 「空壳」—— 回来的 JSON 合法、却一条可用表态都没有（`{}`，或 `ds.parse_json` 从截断
# 文本里救出的那个**内层**对象）。这与沉默是两件事：沉默是模型判了、只是没写全，重问
# 没用；空壳是这次调用没成，再调一次有用。所以这里单独给一个额度。
EMPTY_RETRY = 2

D_VALUES = (1, -1, 0)


class Batch(NamedTuple):
    """一批跑完的产物。

    `kept`／`segs` 必须跟 `verdicts` 一起往回带 —— 表态里的 `p`／`s` 是**对着这一批编的
    号**，脱离这两样就没法回查原话。`ok=False` 表示这一批调不通（传输失败），此时
    `verdicts` 为空、调用方**不许**把批里的帖记成判过。
    """
    verdicts: list[dict]
    kept: list[dict]
    segs: list[dict[int, dict]]        # 句表按**句号**索引，不是按位置
    tally: dict
    ok: bool


def _zero_id(z) -> tuple[int, int] | None:
    """`zeros` 的一格 → `(帖号, 句号)`。收 `"0.3"` 这种字符串，也收 `{"p":0,"s":3}`。"""
    if isinstance(z, dict):
        p, s = z.get("p"), z.get("s")
        return (p, s) if isinstance(p, int) and isinstance(s, int) else None
    try:
        a, b = str(z).strip().split(".")
        return int(a), int(b)
    except ValueError:
        return None


def _slot(raw: dict, n_posts: int, segs: list[dict[int, dict]]
          ) -> tuple[int, int] | None:
    """一条表态的 `(帖号, 句号)` —— 越界或不是整数返回 `None`。"""
    p, s = raw.get("p"), raw.get("s")
    if not isinstance(p, int) or not isinstance(s, int):
        return None
    if not (0 <= p < n_posts) or s not in segs[p]:
        return None
    return (p, s)


def _blank(p: int, s: int, **kw) -> dict:
    base = {"p": p, "s": s, "d": 0, "dw": "", "ow": "", "tw": "", "why": "",
            "spec": "", "idx": ""}
    base.update(kw)
    return base


def _groups(z) -> list[tuple[str, str]]:
    """`zeros` 收成 `[(编号, 格名), …]`。**理由必须是必答项**。

    三种写法都认，首选是**扁平表**：

    | 写法 | 例 | 什么时候用 |
    |:---|:---|:---|
    | 扁平表 | `{"0.9": "路径", "0.12": "条件"}` | 提示词要模型写的这个 |
    | 分组表 | `{"路径": ["0.9", "0.12"]}` | 兼容；**实测模型做不了**，见下 |
    | 裸列表 | `["0.9", "0.12"]` | 老产物与手写输入，无格名 |

    **分组表那一版实测不可用。** 同一批（434 句、带 T/D 324 句）喂 `{"路径": [...]}`，
    模型把 `"0.1", "0.2", "0.3", …` 那一整串**原样抄进了每一个格**（板块、复盘、机制…
    开头都是同一串），1512 次编号去重只剩 433 个，输出冲到 8192 上限被截断，
    `finish_reason=length`。同一批换扁平表：413 条、**条条唯一**、4278 token 正常收尾。
    所以要的是「一句一个键」这个形状本身 —— 它让模型没有可以复读的结构。
    """
    if isinstance(z, dict):
        out: list[tuple[str, str]] = []
        for k, v in z.items():
            if isinstance(v, list):                       # 分组表
                out += [(str(x).strip(), str(k).strip()) for x in v]
            else:                                         # 扁平表
                out.append((str(k).strip(), str(v).strip()))
        return out
    if isinstance(z, list):
        return [(str(x).strip(), "") for x in z]
    return []


def _parse_verdicts(result: dict, n_posts: int,
                    segs: list[dict[int, dict]]) -> tuple[list[dict], dict]:
    """把模型的返回洗干净 —— 越界的编号丢掉、同一句给两次只留第一次。

    收**两栏**：

    | 栏 | 意思 | 落成 |
    |:---|:---|:---|
    | `signals` | 算一条观点信号 | `d` 有值 |
    | `zeros` | 不算 —— 按**拦下它的那一格**分组，值是编号 | `d=0`，`why` ＝ 格名 |

    **每一句 `d=0` 都要带格名**。不写格名就没有地方放这一句 —— 于是「本来就不产」与
    「漏了」在账上分得开。
    """
    out: list[dict] = []
    seen: set[tuple[int, int]] = set()
    bad_n = dup = 0
    why_out = 0

    for raw in (result.get("signals") or []):
        if not isinstance(raw, dict) or (ps := _slot(raw, n_posts, segs)) is None:
            bad_n += 1
            continue
        if ps in seen:
            dup += 1
            continue
        seen.add(ps)
        d = raw.get("d")
        out.append(_blank(ps[0], ps[1],
                          d=d if d in D_VALUES else 0,
                          dw=(raw.get("dw") or "").strip(),
                          ow=(raw.get("ow") or "").strip(),
                          tw=(raw.get("tw") or "").strip(),
                          why=(raw.get("why") or "").strip(),
                          spec=(raw.get("spec") or "").strip(),   # 兜底；表命中时被覆盖
                          idx=(raw.get("idx") or "").strip()))

    for z, code in _groups(result.get("zeros")):
        if code and code not in prompts.ZERO_WHY:
            why_out += 1                       # 码表外的格名 —— 逐句记数，不吞
        ps = _zero_id(z)
        if ps is None or not (0 <= ps[0] < n_posts) or ps[1] not in segs[ps[0]]:
            bad_n += 1
            continue
        if ps in seen:
            dup += 1
            continue
        seen.add(ps)
        out.append(_blank(ps[0], ps[1], why=code))

    # **带 T 或 D 的句子一律要有表态** —— 缺的记名，交上去决定要不要重试
    silent: list[str] = []
    for p, rows in enumerate(segs):
        for s, r in rows.items():
            if ("T" in r["marks"] or "D" in r["marks"]) and (p, s) not in seen:
                silent.append(f"{p}.{s}")

    return out, {"编号错": bad_n, "重复表态": dup, "沉默": silent, "码外": why_out}


def annotate(posts: list[dict], label: str = "", prompt: str = "",
             tail=None) -> Batch:
    """一批帖调**一次**模型。

    调不通（`ModelError`）返回 `ok=False` 而不是抛出去 —— **一批失败不许牵连其余的批**，
    也不许把这位博主这一轮已经判成的批全带走。

    `prompt` 换系统提示词、`tail(kept, segs)` 往批文本后面再接一段。**接在批后面而不是
    插进每条帖里**：上一遍的答案按批内编号写，与帖是同一个坐标系。
    """
    if not posts:
        return Batch([], [], [], {}, True)

    user_text, kept, segs = segment.render_batch(posts)
    if not kept:
        return Batch([], [], [], {"跳过": len(posts), "原因": "行情注记取不到"}, True)
    if tail:
        user_text = user_text + "\n\n" + tail(kept, segs)

    tally: dict = {"帖": len(kept), "句": sum(len(x) for x in segs)}
    verdicts: list[dict] = []

    attempt = 0
    while True:
        attempt += 1
        try:
            result = ds.call_json(prompt or prompts.ANNOTATION_SYSTEM_PROMPT, user_text,
                                  f"{label} 第{attempt}次" if attempt > 1 else label)
        except ds.ModelError as e:
            tally["失败"] = str(e)
            return Batch([], kept, segs, tally, False)

        verdicts, st = _parse_verdicts(result, len(kept), segs)
        # **零条可用表态 ＝ 这次调用没成**，不是「整批都不产」—— 这两件事在账上长得
        # 一模一样，含义正相反。回来的 dict 合法却一条都读不出，两条路都会：①
        # `ds.parse_json` 从截断文本里救出的是**内层**那个对象（顶层 `{` 的括号没配平，
        # 它退而求其次抓住 `{"p":0,"s":7,…}` 这样一个元素）② 模型直接回一个 `{}`。
        # 放过去，这一批会被记成「判过、无信号」，恰好伪装成 §6 的「这帖不该产」——
        # **假的好消息**。实测一批 321 句带 T/D 全成沉默就是这么来的。
        # 与「沉默」不同：沉默是判断分歧，重问没用；空壳是调用没成，**再调一次有用**。
        if not verdicts and st["沉默"]:
            tally["空壳"] = repr(result)[:200]
            if attempt < EMPTY_RETRY:
                continue
            tally["失败"] = f"连续 {attempt} 次返回空壳：{tally['空壳']}"
            return Batch([], kept, segs, tally, False)

        tally.update({k: v for k, v in st.items() if k != "沉默"})
        tally["沉默"] = st["沉默"]
        if not st["沉默"] or attempt >= SILENCE_RETRY:
            break

    tally["表态"] = len(verdicts)
    tally["沉默数"] = len(tally["沉默"])
    tally["重试"] = attempt - 1
    return Batch(verdicts, kept, segs, tally, True)


# ── 第二遍：把上一遍的表态摆回去（02§10.2）──────────────────────────────

# 上一遍的审计行里，这两类是**模型写进 `signals` 的**（`丢` 是代码事后丢的，但它确实是
# 模型上一遍的表态）；`非信号` 那一类是模型写进 `zeros` 的。`去重` 行没有句子编号，不收。
_WROTE = ("产", "丢")


def block(kept: list[dict], rows: list[dict]) -> str:
    """上一遍的表态渲染成一块 —— **原样摆回去**。

    按**批内帖号**写（`p.s`），与上面那批帖是同一个坐标系；上一遍没表态的帖照样列出来、
    写「（无）」，免得第二遍把「没写」读成「系统没给」。
    """
    made: dict[str, list[dict]] = {}
    zeros: dict[str, list[tuple]] = {}
    for r in rows or []:
        if r.get("处置") in _WROTE:
            made.setdefault(r["post_id"], []).append(r)
        elif r.get("处置") == "非信号":
            zeros.setdefault(r["post_id"], []).append((r["s"], r["说明"] or "（无格）"))

    lines = ["## 你上一遍的表态", ""]
    for p, post in enumerate(kept):
        pid = post["post_id"]
        sig = " ／ ".join(
            f"{p}.{r['s']} d={r['d']:+d} dw=\"{r['dw']}\""
            + (f" ow=\"{r['ow']}\"" if r["ow"] else "")
            + (f" tw=\"{r['tw']}\"" if r["tw"] else "")
            for r in sorted(made.get(pid) or [], key=lambda x: x["s"]))
        z = " ／ ".join(f"{p}.{s} {w}" for s, w in sorted(zeros.get(pid) or []))
        lines.append(f"[{p}]")
        lines.append(f"  signals: {sig or '（无）'}")
        lines.append(f"  zeros: {z or '（无）'}")
    return "\n".join(lines)


__all__ = ["annotate", "block", "Batch", "SILENCE_RETRY", "EMPTY_RETRY"]
