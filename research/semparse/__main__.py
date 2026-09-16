# -*- coding: utf-8 -*-
"""research.semparse —— 02 解析流程的那把尺子。

    python -m research.semparse run --out _new1            # 判一遍
    python -m research.semparse cmp _new1 _new2            # 两遍一致性
    python -m research.semparse probe --times 8            # 探针：同一请求原样发 8 次
    python -m research.semparse gold _new1 _new3           # 核判例的 42 条断言
    python -m research.semparse gaps _new1                 # 词典缺口
    python -m research.semparse check                      # 三条断言，不调模型

**流程一律从 `blogger.parse` 取，这里不另存一份实现** —— 尺子量的是上线的那份代码。
本目录只剩「怎么跑」与「怎么读」：`runner` 分批排序、`compare` 比与统计、`gold` 金标、
`probe` 探针。旧流程那两件（`jitter`／`reconcile`）已随读法换代归档，见
`archive/20260916-旧解析流程/`。

产物一律落 `research/semparse/reports/`。`run` 的 `--out`／后面几个子命令的参数都写
**名字**（不带 `.json`、不带路径）；要指别处的文件就直接给路径。

**不碰 `data/`、不写判断缓存、不改 `docs/`。**
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import time
from pathlib import Path

from blogger.common import paths
from blogger.parse import annotate, assemble, segment

from research.semparse import compare, runner

REPORTS = Path(__file__).resolve().parent / "reports"


def _path(arg: str) -> Path:
    """`_new1` → `reports/_new1.json`；给了路径就照给。"""
    if "/" in arg or arg.endswith(".json"):
        p = Path(arg)
        return p if p.suffix == ".json" else p.with_suffix(".json")
    return REPORTS / f"{arg}.json"


def _write(where: Path, text: str) -> None:
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text(text, encoding="utf-8")
    print(f"→ {where}")


# ── run ─────────────────────────────────────────────────────────────────

def cmd_run(out: str, only: str) -> int:
    names = [x for x in only.split(",") if x] if only else paths.roster()
    if not names:
        print("库里一位博主都没有。")
        return 2

    print(f"{len(names)} 位：{'、'.join(names)}")
    doc: dict = {}
    t0 = time.time()
    for i, name in enumerate(names, 1):
        print(f"\n[{i}/{len(names)}] {name}")
        try:
            doc[name] = runner.judge(name)
        except Exception as e:                 # 一位跑不成不牵连其余
            print(f"  这一位没跑成：{e!r}")
            doc[name] = {"__tally__": {"出错": repr(e)}}
        _write(_path(out), json.dumps(doc, ensure_ascii=False, indent=1))   # 跑一位写一次
    print(f"\n用时 {time.time() - t0:.0f}s")
    return 0


def cmd_cmp(f1: str, f2: str) -> int:
    """比两遍，并把逐字输出落成报告 —— 分组判定**原样抄自归档的那把尺子**，
    与判例、旧基线是同一份代码；只有「丁不算不一致」这一处口径不同（见 `compare`）。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = compare.cmd_cmp(str(_path(f1)), str(_path(f2)))
    text = buf.getvalue()
    print(text, end="")
    read = compare.groups_markdown(compare.load(str(_path(f1))),
                                   compare.load(str(_path(f2))))
    print(read)
    d1, d2 = compare.load(str(_path(f1))), compare.load(str(_path(f2)))
    _write(REPORTS / "第一轮-一致性.md",
           f"# 第一轮 · 内部一致性\n\n**口径**：逐帖比最终信号，只比两遍都判到的帖"
           f"（失败批与取不到注记的帖剔除）。**「丁」（三元组逐项一样、只有引文取哪一段"
           f"不同）不算不一致** —— 判断本身没有分歧；它与旧流程基线同一口径。\n\n"
           f"```\n{text.strip()}\n```\n\n"
           f"{compare.baseline_markdown(d1, d2)}{read}")
    return rc


def cmd_probe(only: str, batch: int, times: int, seed: int) -> int:
    """探针 —— 同一个请求原样发 N 次。**不落产物，只打印。**"""
    from research.semparse import probe

    names = [x for x in only.split(",") if x] if only else paths.roster()[:1]
    for i, name in enumerate(names, 1):
        if i > 1:
            print()
        r = probe.run(name, batch=batch, times=times, seed=seed)
        probe.report(r)
        probe.vote_at_post(r)
    return 0


def cmd_gold(files: list[str]) -> int:
    docs = {f: compare.load(str(_path(f))) for f in files}
    body = ["# 对判例 —— 42 条已裁定\n",
            "**金标只有精度那一半。** 判例是从「两遍不一致」里筛出来的，天然只含"
            "「至少一遍看见了」的帖，两遍一致漏掉的进不了判例 —— 所以下表的违规率是"
            "**能查出来的错**，不是全部错。\n",
            "## 几份跑各自的总账\n", compare.tally_markdown(docs)]

    # 几份跑共有的违规 —— 共有的才是**系统性**的，各跑各的是抖动
    if len(docs) > 1:
        hit = []
        for doc in docs.values():
            hit.append({r["编号"] for r in compare.eval_gold(doc) if r.get("违规")})
        common = set.intersection(*hit)
        body.append(f"\n**几份跑共有的违规 {len(common)} 条**："
                    f"{'、'.join(sorted(common)) or '（无）'} —— 共有的才是系统性的，"
                    f"改提示词与词典能改掉；只有一份跑犯的更像抖动。\n")

    for f, doc in docs.items():
        body.append("\n" + compare.gold_markdown(compare.eval_gold(doc), f"逐条 · {f}"))
    _write(REPORTS / "第二轮-对照.md", "\n".join(body))
    return 0


def cmd_gaps(files: list[str]) -> int:
    """两份东西落一处：**词典缺口**（模型答出表里没有的词）与 **归格分布**（模型把每个
    「不算」的句子归到了 §6 的哪一格）。两者都是「下一步该补什么」的输入，放一起看。"""
    docs = {f: compare.load(str(_path(f))) for f in files}
    body = ["# 词典缺口与归格\n",
            "两份表都是**下一步该补什么**的输入：缺口是「模型答出的词表里没有」，"
            "归格是「模型说这句不算、并说清了是哪一格拦下的」。\n"]
    for f, doc in docs.items():
        body.append("\n" + compare.gap_markdown(doc).replace("## 词典缺口",
                                                            f"## 缺口 · {f}", 1))
        body.append("\n" + compare.zeros_markdown(doc).replace(
            "## 归格 —— 为什么不算", f"## 归格 · {f}", 1))
    _write(REPORTS / "词典缺口.md", "\n".join(body))
    return 0


# ── check ───────────────────────────────────────────────────────────────

def _all_posts(limit: int = 0) -> list[dict]:
    out = []
    for name in paths.roster():
        from blogger.report import flow
        out += flow.load_posts(name)
        if limit and len(out) >= limit:
            break
    return out


def cmd_check(run: str) -> int:
    bad = 0

    # ① 确定性 —— 切句与标记重跑逐字节相同
    posts = _all_posts()
    n_sent = n_strong = 0
    for p in posts:
        a = segment.segment_post(p)
        b = segment.segment_post(p)
        if a != b:
            print(f"  切句不确定：{p['post_id']}")
            bad += 1
        body = [r for r in a if r["s"] >= 1]          # 已知数那个口径是**正文**，不含标题
        n_sent += len(body)
        n_strong += sum(1 for r in body if "T" in r["marks"] and "D" in r["marks"])
    share = n_strong * 100 / max(1, n_sent)
    print(f"① 确定性：全库 {len(posts)} 帖、正文 {n_sent} 句，重跑逐条相同")
    print(f"   复现已知数（正文口径，断句点 `。！？!?；;`）：切句 54515 句（±2%）、"
          f"强候选 19.2%（±2%）→ 实得 {n_sent} 句、{share:.1f}%")
    if not (0.98 * 54515 <= n_sent <= 1.02 * 54515):
        print("   切句口径对不上 —— 是切法写错了，不是数据变了")
        bad += 1
    if not (17.7 <= share <= 20.7):
        print("   强候选占比出带 —— 多半是词典写错了")
        bad += 1
    elif not (18.7 <= share <= 19.7):
        # 原型那份词典没进仓库，逐字复现不了；差一点是正常的，差多了才要看
        print("   强候选占比与原型差 1 个点上下 —— 原型词典不在仓库里，复现不了，只记数")

    # ② 不许沉默 —— 带 T／D 的句子缺表态，这一批算调用没成
    post = next((p for p in posts if segment.segment_post(p)), None)
    if post:
        segs = [{r["s"]: r for r in segment.segment_post(post)}]
        need = [s for s, r in segs[0].items() if "T" in r["marks"] or "D" in r["marks"]]
        full = {"zeros": [f"0.{s}" for s in need]}
        if need:
            _, s1 = annotate._parse_verdicts({"signals": [], "zeros": []}, 1, segs)
            _, s2 = annotate._parse_verdicts(full, 1, segs)
            print(f"② 不许沉默：该表态 {len(need)} 句 → 全缺时报沉默 {len(s1['沉默'])} 句、"
                  f"全给时报沉默 {len(s2['沉默'])} 句")
            if len(s1["沉默"]) != len(need) or s2["沉默"]:
                print("   沉默判定不对")
                bad += 1
        else:
            print("② 不许沉默：这条帖没有带 T／D 的句子，跳过")

    # ③ 零越权 —— 产出的 spec／idx／quote 可由 dw／ow／tw ＋ 原帖机械复算
    p = _path(run) if run else None
    if p and p.exists():
        doc = compare.load(str(p))
        by_id = {x["post_id"]: x for x in posts}
        n, miss = 0, 0
        for name in doc:
            if name.startswith("__"):
                continue
            for r in doc[name].get("__审计__") or []:
                if r["处置"] != "产":
                    continue
                n += 1
                post = by_id.get(r["post_id"])
                if post is None:
                    continue
                spec, _ = assemble.resolve_time(r["tw"], r["text"], r["模型spec"], post["pub"])
                idx, _ = assemble.resolve_obj(r["ow"], r["text"], r["模型idx"])
                quote = assemble.quote_of(r["text"], r["dw"])
                if (spec, idx) != (r["spec"], r["idx"]) or quote != r["quote"]:
                    miss += 1
                    print(f"   复算不上：{r['post_id']} {r['text'][:20]}")
        print(f"③ 零越权：去重前 {n} 条产出逐条复算，复算不上 {miss} 条")
        if miss:
            bad += 1
    else:
        print("③ 零越权：没给跑的文件，跳过（`check _new1` 会逐条复算）")

    print("\n通过" if not bad else f"\n{bad} 处不对")
    return 0 if not bad else 1


# ── 入口 ────────────────────────────────────────────────────────────────

def _split(rest: list[str]) -> tuple[list[str], dict[str, str]]:
    pos, opts, i = [], {}, 0
    while i < len(rest):
        if rest[i].startswith("--"):
            nxt = rest[i + 1] if i + 1 < len(rest) else ""
            if nxt.startswith("--"):          # 光杆开关，别把后面那个选项当成它的值吞掉
                opts[rest[i]], i = "", i + 1
            else:
                opts[rest[i]], i = nxt, i + 2
        else:
            pos.append(rest[i])
            i += 1
    return pos, opts


def main(argv: list[str] | None = None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if not a:
        print(__doc__.strip())
        return 2
    pos, opts = _split(a[1:])

    if a[0] == "run" and opts.get("--out"):
        return cmd_run(opts["--out"], opts.get("--only", ""))
    if a[0] == "cmp" and len(pos) >= 2:
        return cmd_cmp(pos[0], pos[1])
    if a[0] == "probe":
        return cmd_probe(opts.get("--only", ""), int(opts.get("--batch", 1) or 1),
                         int(opts.get("--times", 8) or 8),
                         int(opts.get("--seed", 20260916) or 20260916))
    if a[0] == "gold" and pos:
        return cmd_gold(pos)
    if a[0] == "gaps" and pos:
        return cmd_gaps(pos)
    if a[0] == "check":
        return cmd_check(pos[0] if pos else "")
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main())
