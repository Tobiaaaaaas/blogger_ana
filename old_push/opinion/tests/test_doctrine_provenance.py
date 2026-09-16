# -*- coding: utf-8 -*-
"""教义引语溯源（2026-09-10 立，纯文本 + 语料比对，不调 API）。

## 为什么有这个测试

2026-09-10 实盘发现：教义 Q4 的"正例"「下周先抑后扬，整体看多」被标注为
**用户原句（智由智哉 09-06 帖）**，但该帖（id 7682259213178946087）
**通篇没有这句话**，也没有"看多/看涨"；该博主名下同样搜不到，全库语料里
"整体看多"这一措辞也近乎不出现（实际命中数见下方 L3 现算输出）。
即：那是模型捏造的一句，被当作真帖原话写进教义当正例，随后作为**可照抄模板**
被搬到别的帖子上 → 产出编造行（大盘蜂向标 09-07 帖被配上 d=1 与
summary"整体看多"，连续多档上卡）。

机制：**教义里的示例措辞会被模型逐字搬运**。所以标注为"博主原话/实证"的引语
必须能在语料里逐字搜到——本测试就是那道闸。

## 三层

1. `BANNED`（硬断言，任何机器都跑）：已知捏造句**不得**再出现在 prompts.py。
   不依赖语料，因此在没有语料的机器上也拦得住"把幽灵句写回去"。
2. `PROVENANCE`（语料在则硬断言，不在则该条标 SKIP）：
   教义里声称是真实博主原话的引语 → 必须能在指定博主、指定帖的正文里逐字找到。
   语料 `data/posts/` 缺失或不含该帖时打印 SKIP（不静默通过：结尾会汇总条数）。
3. `L3 量级现算`（语料在则现算并打印）：教义里**只用文字表述的量级判断**
   （"高频表述""近乎检索不到""绝大多数"）在此**从语料现算成实际计数**并断言量级。
   教义文本本身**不写死任何计数**——2026-09-10 之前它写着「775 帖」「80815 帖中仅
   3 帖」「987/309/286/223 条」，语料一长就失真（实测已漂到 814 / 8）且无人察觉。
   计数只活在这里（每次运行现算），`test_prompt_doctrine.py` 立闸禁止写死计数回流。

新增/修改教义引语后**先跑本文件**。

直接 python3 运行。
"""
import glob
import io
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
try:                      # Windows GBK 控制台：断言已全过，别让收尾 emoji 崩掉退出码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from opinion import prompts as o_prompts     # noqa: E402

# L3 现算用交易日历（research 镜像实现，与 push/canonical 全网格等值——由
# test_endpoint_consistency.py 钉死）。装载失败只 SKIP L3，不影响 L1/L2 的守门。
try:
    from research import trading_cal as TC   # noqa: E402
except Exception as _e:                      # pragma: no cover
    TC = None
    _TC_ERR = _e

POSTS_DIR = os.path.join(ROOT, "data", "posts")
SIGNALS_DIR = os.path.join(ROOT, "data", "direction_signals")

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

# ── 3) L3 量级现算：教义只写文字判断（"高频""近乎检索不到"），计数在此现算 ────
# 每条 = (措辞, 下限或 None, 教义里对应的说法)。下限 = 该说法成立所需的量级；
# None = 只打印不设卡（"近乎检索不到"没有天然阈值，变常见与否该由人判、不该让测试替人定）。
POSTS_COUNTS = [
    ("先抑后扬", 100,
     "「先抑后扬」放宽条称其为**高频表述**／「语料里的主流用法」"),
    ("整体看多", None,
     "溯源纪律条称其**在全库语料里近乎检索不到**（旧教义写死 80815 帖中仅 3 帖）"),
]


def _blogger_files():
    """data/posts 下的博主语料文件。

    排除两类：下划线开头项（如 `_backup/`）；`{blogger}_bodies_s*.json` 正文分片——
    分片形如 `{post_id: body}`（不是 `{posts:[…]}`），是主页文件的正文外置存储，
    计帖时必须跳过，否则同一帖会被数两次。
    """
    out = []
    for f in sorted(glob.glob(os.path.join(POSTS_DIR, "*.json"))):
        b = os.path.basename(f)
        if b.startswith("_") or "_bodies_s" in b:
            continue
        out.append(f)
    return out


def _iter_posts(f):
    try:
        d = json.load(io.open(f, encoding="utf-8"))
    except Exception:
        return
    posts = d.get("posts", d) if isinstance(d, dict) else d
    if not isinstance(posts, list):
        return
    for x in posts:
        if isinstance(x, dict):
            yield x


_files = _blogger_files()
if not _files:
    print("[SKIP] L3 量级现算：语料 data/posts 缺失 → 跳过（非通过）")
else:
    _hits = {ph: 0 for ph, _lo, _n in POSTS_COUNTS}
    _nposts = 0
    for _f in _files:
        for _x in _iter_posts(_f):
            _nposts += 1
            _b = _body(_x)
            for _ph in _hits:
                if _ph in _b:
                    _hits[_ph] += 1
    print(f"[INFO] L3 语料现算：{len(_files)} 个博主文件 / {_nposts} 帖")
    for _ph, _lo, _note in POSTS_COUNTS:
        print(f"[INFO]   「{_ph}」命中 {_hits[_ph]} 帖 —— {_note}")
        if _lo is not None:
            assert _hits[_ph] >= _lo, (
                f"「{_ph}」全库仅命中 {_hits[_ph]} 帖（< {_lo}）——教义称其「高频/主流」，"
                f"量级已不成立，请复核教义措辞（改措辞或改本阈值，两者只留一处）")
    print(f"[PASS] L3 量级现算：{len(POSTS_COUNTS)} 条措辞的量级与教义说法相符")

# ── 3b) L3b curated 回溯：「本周」已走完条的"绝大多数 / 又有大部分"量级 ──────
# 教义口径：非交易日发布的 `week` 行，终点**绝大多数**落在发帖日之前（报告侧判"无效-过时"）；
# 其中**又有大部分**的摘要原话写的就是"下周"（= 编码错，不是博主在复盘）。按同一口径现算。
# 注：curated 行只有 summary、**无 quote 字段** → 教义说的"摘要/引文原话"在这里只能核到摘要。
if TC is None:
    print("[SKIP] L3b curated 回溯：交易日历不可用 → 跳过（非通过）")
else:
    _rows = []
    for _f in sorted(glob.glob(os.path.join(SIGNALS_DIR, "*.json"))):
        if os.path.basename(_f).startswith("_"):     # `_*_run.json` 运行清单，其 signals 是整数计数
            continue
        try:
            _d = json.load(io.open(_f, encoding="utf-8"))
        except Exception:
            continue
        _sigs = _d.get("signals") if isinstance(_d, dict) else _d
        if isinstance(_sigs, list):
            _rows.extend(x for x in _sigs if isinstance(x, dict))

    _week = [r for r in _rows if r.get("spec") == "week"]
    _nontd = _stale = _stale_nw = 0
    for _r in _week:
        _pub = str(_r.get("pub") or "")[:10]
        try:
            _pd = date.fromisoformat(_pub)
        except ValueError:
            continue
        if TC.is_trading_day(_pd):
            continue
        _nontd += 1
        _ep = TC.endpoint_of(_pd, "week")
        if _ep is not None and _ep < _pd:
            _stale += 1
            if "下周" in str(_r.get("summary") or ""):
                _stale_nw += 1
    if not _week:
        print("[SKIP] L3b curated 回溯：语料里没有 week 行 → 跳过（非通过）")
    else:
        print(f"[INFO] L3b curated 现算：{len(_rows)} 行信号 / week 行 {len(_week)} 条")
        print(f"[INFO]   非交易日发布 {_nontd} 条；其中终点早于发帖日（过时）{_stale} 条；"
              f"过时行里摘要含「下周」{_stale_nw} 条")
        assert _nontd > 0 and _stale * 10 >= _nontd * 8, (
            f"非交易日 week 行 {_nontd} 条里仅 {_stale} 条终点过时——教义称「绝大多数」，"
            f"量级已不成立：请复核周口径是否被改回「非交易日顺延到下一周」")
        assert _stale_nw * 10 >= _stale * 6, (
            f"过时行 {_stale} 条里仅 {_stale_nw} 条摘要含「下周」——教义称「又有大部分」，量级已不成立")
        print("[PASS] L3b curated 回溯：过时占比与「下周」占比支撑教义量级")

print("\n全部教义引语溯源回归通过 ✅")
