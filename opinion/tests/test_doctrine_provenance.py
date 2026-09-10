# -*- coding: utf-8 -*-
"""教义引语溯源（2026-09-10 立，纯文本 + 语料比对，不调 API）。

## 为什么有这个测试

2026-09-10 实盘发现：教义 Q4 的"正例"「下周先抑后扬，整体看多」被标注为
**用户原句（智由智哉 09-06 帖）**，但该帖（id 7682259213178946087，740 字）
**通篇没有这句话**，也没有"看多/看涨"；该博主 127 帖里同样搜不到。全库 80815 帖中
"整体看多"只出现 3 次。即：那是模型捏造的一句，被当作真帖原话写进教义当正例，
随后作为**可照抄模板**被搬到别的帖子上 → 产出编造行（大盘蜂向标 09-07 帖被配上
d=1 与 summary"整体看多"，连续多档上卡）。

机制：**教义里的示例措辞会被模型逐字搬运**。所以标注为"博主原话/实证"的引语
必须能在语料里逐字搜到——本测试就是那道闸。

## 两层

1. `BANNED`（硬断言，任何机器都跑）：已知捏造句**不得**再出现在 prompts.py。
   不依赖语料，因此在没有语料的机器上也拦得住"把幽灵句写回去"。
2. `PROVENANCE`（语料在则硬断言，不在则该条标 SKIP）：
   教义里声称是真实博主原话的引语 → 必须能在指定博主、指定帖的正文里逐字找到。
   语料 `data/posts/` 缺失或不含该帖时打印 SKIP（不静默通过：结尾会汇总条数）。

新增/修改教义引语后**先跑本文件**。

直接 python3 运行。
"""
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
try:                      # Windows GBK 控制台：断言已全过，别让收尾 emoji 崩掉退出码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from opinion import prompts as o_prompts     # noqa: E402

POSTS_DIR = os.path.join(ROOT, "data", "posts")

# 拼成教义全文：任何一处出现都算（教义常量被多处插值）
DOCTRINE_ALL = "\n".join([
    o_prompts.DOCTRINE_NO_DIRECTION,
    o_prompts.DOCTRINE_REVIEW,
    o_prompts.ANNOTATION_SYSTEM_PROMPT,
])

# ── 1) 已知捏造句：硬断言不得再出现 ────────────────────────────────
# 全是"被当成博主原话引用过、但语料里查无此句"的措辞。动机见模块 docstring。
BANNED = [
    "下周先抑后扬，整体看多",     # Q4 旧正例：挂在智由智哉 09-06 帖名下，该帖无此句
    "整体看多/整体偏空，下周先抑后扬",
]

# ── 2) 声称是真实博主原话的引语：语料逐字比对 ──────────────────────
# (引语, 博主, post_id, 说明)。post_id 用字符串，与语料字段一致。
PROVENANCE = [
    ("对于下周周线个人看涨", "A股王", "1866055285835784",
     "Q4 正例：同周期独立无条件净方向句（2026-05-24 周日帖）"),
    ("个人认为下周先抑后扬", "A股王", "1866055285835784",
     "Q4 正例的形态半句（同上帖，验证「形态句与净方向句同帖」成立）"),
    ("所以回踩时注意机会", "A股王", "1866055285835784",
     "先抑后扬 放宽条的操作承诺半句（回踩买入 = 操作动词 = 方向）"),
]


def _load_posts(blogger):
    f = os.path.join(POSTS_DIR, blogger + ".json")
    if not os.path.exists(f):
        return None
    try:
        d = json.load(io.open(f, encoding="utf-8"))
    except Exception:
        return None
    posts = d.get("posts", d) if isinstance(d, dict) else d
    return posts if isinstance(posts, list) else None


def _body(x):
    return x.get("body") or x.get("text") or x.get("content") or ""


# ── BANNED ──
for ph in BANNED:
    assert ph not in DOCTRINE_ALL, (
        f"教义里出现已知捏造句 {ph!r}——它不存在于语料，会把模型引向编造；"
        f"如需讲述该教训，请转述而非复述原句")
print(f"[PASS] 已知捏造句未回流教义：{len(BANNED)} 条")

# ── PROVENANCE ──
checked = skipped = 0
for ph, blogger, pid, note in PROVENANCE:
    assert ph in DOCTRINE_ALL, f"教义里找不到引语 {ph!r}（{note}）——登记表与教义已漂移"
    posts = _load_posts(blogger)
    if posts is None:
        print(f"[SKIP] {blogger} 语料缺失 → 跳过语料比对：{ph!r}")
        skipped += 1
        continue
    hit = [x for x in posts if str(x.get("post_id") or x.get("id")) == pid]
    if not hit:
        print(f"[SKIP] {blogger} 未收录帖 {pid} → 跳过语料比对：{ph!r}")
        skipped += 1
        continue
    assert any(ph in _body(x) for x in hit), (
        f"{blogger} 帖 {pid} 正文里搜不到 {ph!r}——教义把非原话当原话引用（{note}）")
    checked += 1
    print(f"[PASS] 溯源 {blogger}/{pid}：{ph!r}")

total = len(PROVENANCE)
if skipped:
    print(f"[注意] 溯源 {checked}/{total} 条，SKIP {skipped} 条（语料不全，非通过）")
else:
    print(f"[PASS] 教义引语全部溯源到语料：{checked}/{total} 条")

print("\n全部教义引语溯源回归通过 ✅")
