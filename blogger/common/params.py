# -*- coding: utf-8 -*-
"""可调参数 —— 读仓库根的 `config.json`（见 04§8）。

**判据与阈值不写死在代码里。** 代码只从这里读，改参数只改那一份文件。

读法与容错：

| 情形 | 结果 |
|:---|:---|
| 数据根里有 `config.json` | 读它（测试时可以把整个数据根挪走） |
| 数据根里没有 | **退回仓库根那一份** |
| 键缺了、文件坏了 | 用调用方给的默认值，不报错 |

最后一条是刻意的：参数文件是给人改的，改坏一个键不该让整套跑不动。
"""

from __future__ import annotations

import json
from pathlib import Path

from blogger.common import paths

_REPO = Path(__file__).resolve().parents[2]


def _file() -> Path:
    p = paths.ROOT / "config.json"
    return p if p.exists() else _REPO / "config.json"


def _load() -> dict:
    p = _file()
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return doc if isinstance(doc, dict) else {}


DOC = _load()


def get(dotted: str, default=None):
    """按 `节.键` 取值 —— `get("compare.top_n", 20)`。取不到就用默认值。"""
    node = DOC
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return default if node is None else node


__all__ = ["DOC", "get"]
