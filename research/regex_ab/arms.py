# -*- coding: utf-8 -*-
"""七个臂 —— 每个臂一组运行时要翻的开关，进出自动还原。

**`blogger/` 一个字不改。** 开关全装在模块属性上：`extract.render_post` 走的是
`hints.hints_of(post)` 这个模块属性，`lexicons.has_cond` 内部按裸名读那七个常量，
所以两处都 patch 得到。

| 臂 | 名字 | 翻什么 |
|:---|:---|:---|
| `0`  | 现役 | 不翻 —— 基线 |
| `0p` | 重跑 | 不翻，独立跑第二遍 —— 量模型的自然波动，其余各臂的差要明显大过它才算数 |
| `1`  | 无清单 | `hints_of` 返回空串，那一行根本不出现 |
| `2`  | 只留时间对象 | 渲染好的那一行只留前两栏 |
| `3`  | 只留条件方向 | 只留后两栏 |
| `4`  | 不给档位指数 | 四栏都在，去掉每一项后面的 `→值` |
| `5`  | 方向词取最短 | 换掉 `find_dir_words`：同一位置取最短，不取最长 |

臂 2／3／4 都是**改渲染好的那一行**，不改 `hints_of` 的算法 —— 那一行就是模型看到的
东西，改它等于改模型看到的东西，够了。臂 5 改的是算法本身：最长匹配是 `find_dir_words`
内部的判断，改渲染结果复现不出来。
"""

from __future__ import annotations

import contextlib

from blogger.parse import hints, lexicons

PREFIX = "[字面命中] "
COL_SEP = " ｜ "
ITEM_SEP = "、"
NOTHING = "无"

# ── 改渲染好的那一行 ────────────────────────────────────────────────────

def _cols(line: str) -> list[tuple[str, str]]:
    """`[字面命中] 时间词：a、b ｜ 对象词：无` → `[("时间词", "a、b"), ("对象词", "无")]`。"""
    out = []
    for part in line[len(PREFIX):].split(COL_SEP):
        name, _, items = part.partition("：")
        out.append((name, items))
    return out


def _render(cols: list[tuple[str, str]]) -> str:
    """照 `hints_of` 自己的规矩：**留下的几栏一个都查不出东西，就整行不摆**。"""
    if not any(items != NOTHING for _, items in cols):
        return ""
    return PREFIX + COL_SEP.join(f"{name}：{items}" for name, items in cols)


def _drop_values(items: str) -> str:
    """`明天→t1、今天→today` → `明天、今天`。值一定在 `→` 右边，词本身不含 `→`。"""
    if items == NOTHING:
        return items
    return ITEM_SEP.join(w.split("→", 1)[0] for w in items.split(ITEM_SEP))


def _rewrite(rewrite):
    """把 `hints_of` 包一层 —— 拿到那一行，改完再交出去。**空行原样放行。**"""
    def install(swap):
        original = hints.hints_of          # swap 里取的是同一个值，装之前先扣住

        def patched(post):
            line = original(post)
            return rewrite(line) if line else ""

        swap(hints, "hints_of", patched)
    return install


def only(*names: str):
    """只留这几栏。"""
    keep = set(names)
    return _rewrite(lambda line: _render([c for c in _cols(line) if c[0] in keep]))


def no_values():
    """四栏都在，把每一项后面的值去掉。"""
    return _rewrite(lambda line: _render([(n, _drop_values(it)) for n, it in _cols(line)]))


# ── 换掉算法 ────────────────────────────────────────────────────────────

def shortest_dir_words(text: str) -> list[tuple[int, str]]:
    """和 `hints.find_dir_words` 的唯一区别：**同一位置取最短匹配**。

    真版按词长从长到短摆、先占先得，所以「不会大涨」压过「大涨」压过「涨」；这一版反过来，
    同一处就只剩一个字 —— 「不会大涨」摆出去的是「涨」，方向正好反了。这正是那条纪律
    （`hints.find_dir_words` 的「不做这一步的话，一处会同时摆出三个词，其中两个方向相反」）
    要挡的事。
    """
    hits: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for word in sorted(lexicons.DIR_WORDS, key=len):        # 短 → 长
        start = text.find(word)
        while start >= 0:
            if all(start + len(word) <= x or start >= y for x, y in taken):
                hits.append((start, word))
                taken.append((start, start + len(word)))
            start = text.find(word, start + 1)
    return sorted(hits)


# ── 臂表 ────────────────────────────────────────────────────────────────

def _blank(post) -> str:
    return ""


ARMS: dict[str, tuple[str, list]] = {
    "0":  ("现役", []),
    "0p": ("重跑", []),
    "1":  ("无清单", [lambda swap: swap(hints, "hints_of", _blank)]),
    "2":  ("只留时间对象", [only("时间词", "对象词")]),
    "3":  ("只留条件方向", [only("条件词", "方向词")]),
    "4":  ("不给档位指数", [no_values()]),
    "5":  ("方向词取最短", [lambda swap: swap(hints, "find_dir_words", shortest_dir_words)]),
}


def names() -> list[str]:
    return list(ARMS)


def title(arm: str) -> str:
    return ARMS[arm][0]


@contextlib.contextmanager
def armed(arm: str):
    """进出装／还原这个臂的开关。**还原按倒序** —— 同一处被翻两次也退得回来。"""
    if arm not in ARMS:
        raise KeyError(f"没有这个臂：{arm}（有：{'、'.join(ARMS)}）")

    saves: list[tuple] = []

    def swap(mod, attr, value):
        saves.append((mod, attr, getattr(mod, attr)))
        setattr(mod, attr, value)

    try:
        for item in ARMS[arm][1]:
            item(swap)
        yield
    finally:
        for mod, attr, old in reversed(saves):
            setattr(mod, attr, old)
