# -*- coding: utf-8 -*-
"""抽取水位线 extract_through 与覆盖率前沿回归（2026-09-10，纯逻辑、不调 API）。

背景（为什么需要水位线）：
`research/poll.CorpusIndex.uncovered()` 决定"某个决策日该板块的窗口是否被方向抽取完整覆盖"，
没盖满的成员当日**整档判不干净**（保守取向：宁可少计也不把可能的漏抽当弃权）。原判据拿
`LS`（该博主**最后一条信号**的 pub 日）当"抽取前沿"的代理，用 `LP > LS` 判右侧漏抽。

代理在"尾巴那几帖本来就没有方向观点"时会说谎：脚本判 无实质内容/无明确方向 → 不产信号 →
LS 原地不动 → 已抽取却被判成漏抽。实例（本轮实测）：道术合一尾段 4 帖抽出 0 条 →
short 回测样本窗 158→140 日、终点从 08-27 退到 08-03。

修法 = 把「抽取**跑到**哪天」显式记下来，与「抽到几条」解耦：

    提取脚本 extract_signals_direction.py  写 data/direction_signals/<名>.json 的 extract_through
    research/corpus.py                     透传到 research/signals/<名>.json + _manifest.json
    research/poll.py                       CorpusIndex.XT ← 它；前沿 = XT 若有、否则 LS（回退）

本测试钉死三件事：
1. 全链路透传（源 → 归一化语料 → manifest）；
2. XT 在场时，`LP ≤ XT` 判覆盖（代理的假阳性被消除）；
3. XT 缺席时回退 LS（旧文件行为不变）；XT 在场但其后**确有新帖**时仍判漏抽（真漏抽不被掩盖）。

全部在临时目录内构造语料，不读也不写真实 research/signals。
直接 python3 运行。
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
try:                      # Windows GBK 控制台：断言已全过，别让收尾 emoji 崩掉退出码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from research import config, corpus, poll as pollmod   # noqa: E402

B = "测试博主"
OTHER = "旁证博主"
ROW = {"pub": "2026-08-03 12:35", "d": 1, "idx": "上证指数", "summary": "下周看多",
       "spec": "nweek", "cat": "scored"}


def _row(pub, **kw):
    r = dict(ROW)
    r.update(kw)
    r["pub"] = pub
    return r


def _posts(dates):
    return {"posts": [{"publish_date": d + " 10:00"} for d in dates]}


def _setup(tmp, sig_doc, post_dates, xt_absent=False):
    """写一个临时源语料 + 帖文件，返回 (src_dir, posts_dir)。"""
    src = os.path.join(tmp, "src")
    posts = os.path.join(tmp, "posts")
    os.makedirs(src, exist_ok=True)
    os.makedirs(posts, exist_ok=True)
    src_doc = {"blogger": B, "signals": sig_doc["signals"]}
    if not xt_absent:
        src_doc["extract_through"] = sig_doc.get("extract_through")
    with open(os.path.join(src, B + ".json"), "w", encoding="utf-8") as f:
        json.dump(src_doc, f, ensure_ascii=False)
    with open(os.path.join(posts, B + ".json"), "w", encoding="utf-8") as f:
        json.dump(_posts(post_dates), f, ensure_ascii=False)
    return src, posts


def _build_and_index(tmp, src, posts):
    """把 config 指向临时目录 → corpus.build() → CorpusIndex()。"""
    out = os.path.join(tmp, "out")
    config.DATA_SIGNALS_DIR = src
    config.POSTS_DIR = posts
    config.SIGNALS_OUT_DIR = out
    config.REPORTS_DIR = os.path.join(tmp, "reports")
    config.PANELS = {"short": [B], "swing": []}
    corpus.build()
    return pollmod.CorpusIndex(), out


# ── 用例：LS 停在 08-03（尾巴无信号），真实发帖到 08-21，抽取已跑到 08-21 ──────────
SIGS = {"signals": [_row("2026-08-03 12:35")], "extract_through": "2026-08-21"}
POSTS = ["2026-08-03", "2026-08-15", "2026-08-21"]
D = date(2026, 8, 10)     # 决策日：LS(08-03) < D，且 LP(08-21) ≥ 窗口下界

tmp = tempfile.mkdtemp(prefix="wm_test_")
try:
    # ── 1. 全链路透传 ────────────────────────────────────────────────────────
    src, posts = _setup(tmp, SIGS, POSTS)
    idx, out = _build_and_index(tmp, src, posts)

    norm = json.load(open(os.path.join(out, B + ".json"), encoding="utf-8"))
    assert norm.get("extract_through") == "2026-08-21", f"归一化语料未透传水位线：{norm.get('extract_through')!r}"
    man = json.load(open(os.path.join(out, "_manifest.json"), encoding="utf-8"))
    assert man["by_blogger"][B].get("extract_through") == "2026-08-21", "manifest 未记水位线"
    assert man.get("extract_through", {}).get(B) == "2026-08-21", "manifest 未汇总水位线"
    assert idx.XT.get(B) == date(2026, 8, 21), f"CorpusIndex.XT 未取到水位线：{idx.XT.get(B)}"
    assert idx.LS.get(B) == date(2026, 8, 3), f"LS 应为最后一条信号日：{idx.LS.get(B)}"
    assert idx.LP.get(B) == date(2026, 8, 21), f"LP 应为帖库最新发帖日：{idx.LP.get(B)}"
    print("[PASS] 透传链路：提取脚本字段 → corpus 归一化语料 + manifest → CorpusIndex.XT")

    # ── 2. 水位线在场：LP ≤ XT → 覆盖（代理的假阳性被消除）──────────────────
    assert idx.uncovered("short", D) == [], \
        f"水位线在场仍判漏抽（假阳性未消除）：{idx.uncovered('short', D)}"
    print(f"[PASS] 水位线在场：LS={idx.LS[B]} < LP={idx.LP[B]} 但 XT={idx.XT[B]} ≥ LP → "
          f"{D} 判覆盖（旧代理会误判漏抽、整档不干净）")

    # ── 3. 水位线缺席：回退 LS（旧文件行为不变）──────────────────────────────
    tmp2 = tempfile.mkdtemp(prefix="wm_test_nofield_")
    try:
        src2, posts2 = _setup(tmp2, SIGS, POSTS, xt_absent=True)
        idx2, out2 = _build_and_index(tmp2, src2, posts2)
        assert B not in idx2.XT, "无字段时不应产生 XT"
        assert idx2.uncovered("short", D) == [B], \
            "无水位线时未回退到 LS 代理口径（旧行为被改变）"
        norm2 = json.load(open(os.path.join(out2, B + ".json"), encoding="utf-8"))
        assert norm2.get("extract_through") is None, "无字段时归一化语料应写 None"
        print(f"[PASS] 水位线缺席：回退 LS 代理（前沿={idx2.LS[B]}），旧文件行为逐字不变")
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    # ── 4. 前沿越过决策日 → 覆盖（本轮修复的主场景：窗口得以延伸到 LS 之后）────
    # 旧代理（前沿=LS=08-03）对任何 d > 08-03 都判不干净 → 样本窗被截在 08-03。
    # 水位线（08-21）在场时，08-21 之前的决策日全部判干净 → 窗口延伸。
    LATER = date(2026, 8, 20)      # 决策日仍在前沿之内（08-21 之前）
    assert idx.uncovered("short", LATER) == [], \
        f"前沿 {idx.XT[B]} 未覆盖 {LATER} —— 窗口未延伸到 LS 之后"
    tmp3 = tempfile.mkdtemp(prefix="wm_test_later_")
    try:
        src3, posts3 = _setup(tmp3, SIGS, POSTS, xt_absent=True)
        idx3, _ = _build_and_index(tmp3, src3, posts3)
        assert idx3.uncovered("short", LATER) == [B], \
            "无水位线时 08-20 应仍判漏抽（旧口径截断样本窗的机制）"
        print(f"[PASS] 窗口延伸：同一决策日 {LATER} —— 有水位线判覆盖、无水位线判漏抽"
              f"（旧口径正是这样把样本窗截在 LS={idx.LS[B]}）")
    finally:
        shutil.rmtree(tmp3, ignore_errors=True)

    # ── 5. 水位线在场但其后确有新帖且落入窗口 → 仍判漏抽（真漏抽不被掩盖）────
    # 决策日必须晚于前沿（前沿 < d），否则窗口整体在前沿之内、新帖进不了窗口。
    LEAK_DAY = date(2026, 9, 9)    # 窗口 = 前一交易日 09-08 → 恰盖住 09-08 的新帖
    tmp4 = tempfile.mkdtemp(prefix="wm_test_leak_")
    try:
        src4, posts4 = _setup(tmp4, SIGS, POSTS + ["2026-09-08"])
        idx4, _ = _build_and_index(tmp4, src4, posts4)
        assert idx4.LP.get(B) == date(2026, 9, 8), idx4.LP.get(B)
        assert idx4.XT.get(B) == date(2026, 8, 21), idx4.XT.get(B)
        assert idx4.uncovered("short", LEAK_DAY) == [B], \
            "XT(08-21) 之后出现新帖(09-08) 却未判漏抽 —— 水位线掩盖了真漏抽"
        print("[PASS] 真漏抽仍被捕获：XT=08-21 而后有 09-08 新帖落入 09-09 的窗口 → 判漏抽"
              "（水位线不掩盖尚未抽取的帖）")
    finally:
        shutil.rmtree(tmp4, ignore_errors=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n全部抽取水位线回归通过 ✅")
