# -*- coding: utf-8 -*-
"""06§4 的状态文件 —— `data/state/push_<板块>.json`。每板块一份，与「两条独立的线」一致。

**只记两样**：初始化标记、分布本身。

| 不记什么 | 为什么 |
|:---|:---|
| **「上次推送时刻」** | 窗口起点每档现算（06§3），不依赖上次跑没跑过。停机几天再恢复，不需要对账 |
| **`ep` / `span`** | 从 `pub` + `spec` 推得，**不写死推导值** —— 日历一补，结论跟着变。与 03§3 同一条规矩 |

分布里的每一条就是**信号文件里那 6 键**，形状与 `data/signals/<博主名>.json` 一模一样。
**存的是「窗口内还在有效期的那几条」，不是每位一条** —— 最新那条过期时要能退回次新那条
（06§5.6）。
"""

from __future__ import annotations

import json

from blogger.common import paths
from blogger.report import store


def path(board: str):
    return paths.STATE_DIR / f"push_{board}.json"


def load(board: str) -> dict:
    """读状态。文件不在就是「没建过」——`ready` 为 False、分布为空。"""
    p = path(board)
    if not p.exists():
        return {"ready": False, "book": {}}
    try:
        doc = json.loads(p.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {"ready": False, "book": {}}
    book = {}
    for name, rows in (doc.get("book") or {}).items():
        book[name] = [store.pick(r) for r in (rows or [])]
    return {"ready": bool(doc.get("ready")), "book": book}


def save(board: str, book: dict) -> None:
    """整份写回。每位的条目按 `pub` 排 —— 固定下来，便于人工比对与版本差异。"""
    rows = {name: sorted((store.pick(r) for r in rs), key=lambda r: (r["pub"] or "",
                                                                    r["spec"] or "",
                                                                    r["d"] or 0))
            for name, rs in book.items()}
    p = path(board)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"board": board, "ready": True, "book": rows},
                            ensure_ascii=False, indent=1), encoding="utf-8")


__all__ = ["path", "load", "save"]
