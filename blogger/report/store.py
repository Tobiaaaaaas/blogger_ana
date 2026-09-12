# -*- coding: utf-8 -*-
"""结构化数据文件 —— `data/signals/<博主名>.json`。

**文件里永远只有 6 键**（`post_id`／`pub`／`d`／`spec`／`idx`／`quote`），博主名写在文件
顶层一次。事后验证算出来的那七样**不进来**（见 03§3）—— 所以这里的读写不认它们。

清库（§3.7）删的是**行**，删完文件还是 6 键。
"""

from __future__ import annotations

import json

from blogger.common import paths

KEYS = ("post_id", "pub", "d", "spec", "idx", "quote")


def load(blogger: str) -> list[dict]:
    """读这位博主的结构化数据。文件不在就是空的。"""
    p = paths.signals_file(blogger)
    if not p.exists():
        return []
    doc = json.loads(p.read_text(encoding="utf-8")) or {}
    return [pick(s) for s in (doc.get("signals") or [])]


def pick(sig: dict) -> dict:
    """只留 6 键 —— 万一旧文件里带了别的字段，在这里就剥掉。"""
    return {k: sig.get(k) for k in KEYS}


def save(blogger: str, signals: list[dict]) -> None:
    """整份写回。排序固定，便于人工比对与版本差异。

    顶层**只有两键**：`blogger` 与 `signals` —— 这份文件里不记任何「什么时候跑的」，
    那是帖子文件 `scrape_time` 的事。
    """
    rows = sorted((pick(s) for s in signals),
                  key=lambda s: (s["pub"] or "", s["idx"] or "", s["spec"] or ""))
    doc = {"blogger": blogger, "signals": rows}
    p = paths.signals_file(blogger)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


__all__ = ["load", "save", "pick", "KEYS"]
