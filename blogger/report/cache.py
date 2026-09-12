# -*- coding: utf-8 -*-
"""判过的帖 —— `data/state/parse_cache/<博主名>.json`。**不是产物，是辅助记录。**

它记一件事：**这条帖判过了，判出来的是这几行**。于是：

- 旧博主更新时**只判新帖** —— 判过的帖直接从缓存里取行，不再调模型（03§2.2）
- **规则文本一改，整批作废重判** —— 缓存里存着判的时候用的那版规则文本的指纹，
  对不上就整份丢掉（03§2.2）

**信号文件由本缓存派生**，不是反过来。所以一条帖重判后**从有信号变成没信号**，
旧行不会赖在文件里 —— 单纯「并入」是做不到这一点的。

缓存里存的也是 **6 键**，和信号文件里的行一模一样。顶层**只有三键**：
`blogger`／`rule`（规则指纹）／`judged` —— 不记「什么时候写的」，与信号文件同一条规矩。
"""

from __future__ import annotations

import hashlib
import json

from blogger.common import paths
from blogger.parse import prompts


def rule_fingerprint() -> str:
    """当前这版读帖规则的指纹。规则文本一改，指纹就变。"""
    blob = (prompts.ANNOTATION_SYSTEM_PROMPT + "\x00" + prompts.RECONCILE_SYSTEM_PROMPT)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load(blogger: str) -> dict:
    """读缓存。**指纹对不上就当没有** —— 整批作废，重判。"""
    p = paths.parse_cache_file(blogger)
    if not p.exists():
        return {"rule": rule_fingerprint(), "judged": {}}
    try:
        doc = json.loads(p.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {"rule": rule_fingerprint(), "judged": {}}
    if doc.get("rule") != rule_fingerprint():
        return {"rule": rule_fingerprint(), "judged": {}}
    return {"rule": doc["rule"], "judged": doc.get("judged") or {}}


def save(blogger: str, judged: dict) -> None:
    p = paths.parse_cache_file(blogger)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"blogger": blogger, "rule": rule_fingerprint(), "judged": judged}
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def pending(posts: list[dict], judged: dict) -> list[dict]:
    """这些帖里**还没判过的**。判过的帖即便正文变了也不再判（正文不会变）。"""
    return [p for p in posts if p["post_id"] not in judged]


def rows_of(judged: dict) -> list[dict]:
    """缓存里所有行，摊平。信号文件就是它排序后的样子。"""
    return [row for entry in judged.values() for row in (entry.get("signals") or [])]


__all__ = ["rule_fingerprint", "load", "save", "pending", "rows_of"]
