# -*- coding: utf-8 -*-
"""矛盾复核的两个动词里不花调用的那部分 —— 扫出「产出与引文对不上」的那几处。

    python -m research.crosscheck scan          # 不花调用
    python -m research.crosscheck run --out …   # 两个臂各跑一遍（要密钥）
    python -m research.crosscheck cmp …

**只读 `data/signals/` 与 `data/posts/`，一个字不写。** 不抓帖、不碰判断缓存、不动调度。
"""

from __future__ import annotations

import json

from blogger.common import paths
from blogger.parse import hints


def signals_of(name: str) -> list[dict]:
    """这位博主已落盘的行。"""
    p = paths.signals_file(name)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("signals") or []


def posts_of(name: str) -> dict[str, dict]:
    """`{post_id: 帖}` —— 复核要把整条帖摆回给模型。"""
    p = paths.posts_file(name)
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {x["post_id"]: x for x in (doc.get("posts") or [])}


def scan(names: list[str] | None = None) -> list[tuple[str, dict, dict, str]]:
    """全库跑一遍矛盾检查。返回 `[(博主, 帖, 行, 对不上的地方), …]`。

    **查的是 §10.5 那两栏**（`idx`／`spec`），方向那一栏不查 —— `hints.contradiction`
    里说清了为什么。
    """
    out: list[tuple[str, dict, dict, str]] = []
    for name in (names if names is not None else paths.roster()):
        posts = posts_of(name)
        for s in signals_of(name):
            why = hints.contradiction(s)
            if not why:
                continue
            post = posts.get(s["post_id"])
            if post is not None:
                out.append((name, post, s, why))
    return out


def triples(rows: list[dict]) -> str:
    """几行产出写成一行 —— 比「原来是什么、复核后成了什么」用。"""
    return "、".join(f"{s['d']:+d} {s['spec']} {s['idx']}" for s in rows) or "无"
