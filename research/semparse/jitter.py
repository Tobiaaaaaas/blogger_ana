# -*- coding: utf-8 -*-
"""同一份输入把全库判两遍，比出「多次判断不一致」的帖。

    python -m research.semparse.jitter run --out _pass1
    python -m research.semparse.jitter run --out _pass2
    python -m research.semparse.jitter cmp _pass1.json _pass2.json
    python -m research.semparse.jitter draft _pass1.json _pass2.json --out <草稿路径>

**量的就是 02§10.3 那条规矩**：同一条帖跑 `parse.runs` 遍、比三元组，对不上的才定夺。
两遍之间唯一的变量是模型自己，所以量出来的不一致率就是这套读法的**抖动下限** ——
它进不了模型的错，只量模型自己跟自己不一致。

**不抓帖、不动库、也不写判断缓存** —— 帖文与行情就是当前 `data/` 的那一份。取帖与分批
**照抄** `blogger.report.flow.judge_posts`：先按 `pub` 从新到旧排，再筛掉取不到行情注记的，
再切批。不照抄的话，「分批不同」会混进差异里，量出来的就不是模型的抖动。

**没判到的帖不算差异** —— 失败批里的帖、取不到注记的帖，两遍里都不出现。`cmp` 只比
两遍都在的帖，并把剔掉的条数报出来。
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter

from blogger.common import params, paths
from blogger.parse import extract
from blogger.report import flow

QUOTE_PAD_BEFORE = 200        # 引文窗口：往前留多少字
QUOTE_PAD_AFTER = 150         # 往后留多少字
FALLBACK_CHARS = 400          # 引文在正文里找不到时，退而取的开头长度

# 争议分组 —— 按「规则问的是哪个问题」分，不按博主
GROUPS = [
    ("甲", "一遍产、另一遍完全不产", "什么算一条观点信号（02§6 与 §3.1）"),
    ("乙", "两遍都产，但条数不同", "一条帖能出几条（02§7）"),
    ("丙1", "条数相同、周期不同", "02§4 的周期表与 §4.3"),
    ("丙2", "条数相同、对象不同", "02§5 的映射与「跟着这一处表述走」"),
    ("丙3", "条数相同、方向不同", "02§3 方向"),
    ("丁", "三元组相同、引文不同", "02§9 引文佐证"),
]


# ── 判一遍 ──────────────────────────────────────────────────────────────

def judge_once(name: str, log=print) -> dict:
    """判一位博主的一遍。返回 `{post_id: {"pub": …, "signals": [...]}}`。

    与 `judge_posts` 的唯一区别是**没有缓存** —— 这里的每一批都是空手起判。
    """
    posts = flow.load_posts(name)
    posts.sort(key=lambda p: p["pub"], reverse=True)
    ready = extract.ready_posts(posts)
    judged: dict[str, dict] = {}

    def remember(batch, signals, ok):
        # **失败的那批不记** —— 记了就是把「没判到」当成「判成不产」
        if not ok:
            return
        by_post: dict[str, list[dict]] = {}
        for s in signals:
            by_post.setdefault(s["post_id"], []).append(s)
        for p in batch:
            judged[p["post_id"]] = {"pub": p["pub"],
                                    "signals": by_post.get(p["post_id"], [])}

    _, tally = extract.extract(ready, on_judged=remember,
                               progress=lambda i, n, k: log(f"    批 {i}/{n} → {k} 条"))
    # **丢的账留着** —— 强校验丢的每一行，清单里都写着是哪条帖、哪句原话、丢的是哪一处，
    # 给人逐条读（§10.2）。验收标准是「有没有错筛」，不是覆盖率。
    judged["__tally__"] = {k: v for k, v in tally.items() if k != "失败帖"}
    judged["__tally__"]["失败帖数"] = len(tally.get("失败帖") or [])
    judged["__tally__"]["帖"] = len(posts)
    judged["__tally__"]["可判"] = len(ready)
    return judged


def cmd_run(out: str) -> int:
    names = paths.roster()
    if not names:
        print("库里一位博主都没有。")
        return 2

    print(f"全库 {len(names)} 位｜runs={extract.RUNS}｜模型 {params.get('parse.model', '')}")
    doc: dict[str, dict] = {}
    t0 = time.time()
    for i, name in enumerate(names, 1):
        print(f"\n[{i}/{len(names)}] {name}")
        try:
            doc[name] = judge_once(name)
        except Exception as e:                    # 一位跑不成不牵连其余
            print(f"  这一位没跑成：{e!r}")
            doc[name] = {"__tally__": {"出错": repr(e)}}
        # 跑一位写一次 —— 中途断了前面的不白跑
        _write(out, doc)
    print(f"\n用时 {time.time() - t0:.0f}s → {out}.json")
    return 0


def _write(stem: str, doc) -> None:
    from pathlib import Path
    Path(f"{stem}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


# ── 比两遍 ──────────────────────────────────────────────────────────────

def classify(a: list[dict], b: list[dict]) -> str:
    """两组信号属于哪一类争议。**完全一样返回空串**。

    条数与三个分量逐级判 —— 一条案例可能同时有几处不同，归到最靠前的那一类。
    """
    if not a and not b:
        return ""
    if not a or not b:
        return "甲"
    if len(a) != len(b):
        return "乙"
    if Counter(s["spec"] for s in a) != Counter(s["spec"] for s in b):
        return "丙1"
    if Counter(s["idx"] for s in a) != Counter(s["idx"] for s in b):
        return "丙2"
    if Counter(s["d"] for s in a) != Counter(s["d"] for s in b):
        return "丙3"
    if sorted(s["quote"] for s in a) != sorted(s["quote"] for s in b):
        return "丁"
    return ""


def cmd_cmp(f1: str, f2: str) -> int:
    p1, p2 = _load(f1), _load(f2)
    names = sorted(set(p1) | set(p2))

    cases, only, n_same = [], 0, 0
    for name in names:
        a_all = {k: v for k, v in (p1.get(name) or {}).items() if not k.startswith("__")}
        b_all = {k: v for k, v in (p2.get(name) or {}).items() if not k.startswith("__")}
        both = set(a_all) & set(b_all)
        only += len(set(a_all) ^ set(b_all))
        for pid in both:
            a, b = a_all[pid]["signals"], b_all[pid]["signals"]
            g = classify(a, b)
            if g:
                cases.append({"组": g, "博主": name, "post_id": pid,
                              "pub": a_all[pid]["pub"], "甲": a, "乙": b})
            else:
                n_same += 1

    done = n_same + len(cases)
    print(f"两遍都判到的帖 {done} 条"
          f"｜判得一样 {n_same} 条｜不一致 {len(cases)} 条"
          f"（{len(cases) * 100 / max(1, done):.1f}%）")
    print(f"只有一遍判到的帖 {only} 条（失败批／取不到注记）—— 不算差异，已剔除")
    for g, what, _ in GROUPS:
        print(f"  {g:<4}{what:<22}{sum(1 for c in cases if c['组'] == g)} 条")
    print()
    c = Counter((x["组"], x["博主"]) for x in cases)
    for g, what, _ in GROUPS:
        rows = [(n, v) for (gg, n), v in c.items() if gg == g]
        if rows:
            rows.sort(key=lambda r: -r[1])
            print(f"  {g}：" + "、".join(f"{n} {v}" for n, v in rows))
    return 0


def _load(path: str) -> dict:
    from pathlib import Path
    p = Path(path)
    if not p.exists() and not path.endswith(".json"):
        p = Path(path + ".json")
    return json.loads(p.read_text(encoding="utf-8"))


# ── 出草稿 ──────────────────────────────────────────────────────────────

def _window(text: str, quotes: list[str]) -> tuple[str, bool]:
    """引文周围那一段。返回 `(窗口, 引文找没找到)`。"""
    hits = [text.find(q) for q in quotes if q and q in text]
    if not hits:
        return text[:FALLBACK_CHARS], False
    i = min(hits)
    longest = max((len(q) for q in quotes if q and q in text), default=0)
    lo = max(0, i - QUOTE_PAD_BEFORE)
    hi = min(len(text), i + longest + QUOTE_PAD_AFTER)
    head = "…" if lo > 0 else ""
    tail = "…" if hi < len(text) else ""
    return head + text[lo:hi] + tail, True


def _sig_rows(label: str, sigs: list[dict]) -> list[str]:
    if not sigs:
        return [f"| {label} | — | — | — | （无） |"]
    rows = []
    for i, s in enumerate(sigs):
        first = label if i == 0 else ""
        q = s["quote"].replace("\n", " ").replace("|", "丨")
        rows.append(f"| {first} | {s['d']:+d} | {s['spec']} | {s['idx']} | {q} |")
    return rows


def cmd_draft(f1: str, f2: str, out: str) -> int:
    from pathlib import Path
    target = Path(out)
    if target.exists():
        # **不许覆盖** —— 这份文档要被人填进裁定，重跑一次就冲掉等于白填
        print(f"目标已存在，不覆盖：{target}")
        return 2

    p1, p2 = _load(f1), _load(f2)
    lib = _library()
    has_lib = bool(lib)          # `data/signals/` 不在时不出「库（参考）」那一行
    body, posts = [], {}

    cases = []
    for name in sorted(set(p1) | set(p2)):
        a_all = {k: v for k, v in (p1.get(name) or {}).items() if not k.startswith("__")}
        b_all = {k: v for k, v in (p2.get(name) or {}).items() if not k.startswith("__")}
        for pid in set(a_all) & set(b_all):
            a, b = a_all[pid]["signals"], b_all[pid]["signals"]
            g = classify(a, b)
            if g:
                cases.append({"组": g, "博主": name, "post_id": pid,
                              "pub": a_all[pid]["pub"], "甲": a, "乙": b})
        for p in flow.load_posts(name):
            posts[(name, p["post_id"])] = p

    for g, what, rule in GROUPS:
        mine = [c for c in cases if c["组"] == g]
        if not mine:
            continue
        mine.sort(key=lambda c: (c["博主"], c["pub"]))
        body.append(f"\n## {g} · {what}\n")
        body.append(f"**对应的规则**：{rule}｜{len(mine)} 条\n")
        for i, c in enumerate(mine, 1):
            body.append(_case_block(g, i, c, posts, lib, has_lib))

    target.write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"草稿 {len(cases)} 条 → {target}")
    return 0


def _case_block(g: str, i: int, c: dict, posts: dict, lib: dict, has_lib: bool) -> str:
    name, pid = c["博主"], c["post_id"]
    post = posts.get((name, pid)) or {}
    lib_sigs = (lib.get(name) or {}).get(pid, [])

    quotes = [s["quote"] for s in c["甲"] + c["乙"]]
    if has_lib:
        quotes += [s["quote"] for s in lib_sigs]
    content = post.get("content") or ""
    text, found = _window(content, quotes)
    title = (post.get("title") or "").strip()

    lines = [f"\n### {g}-{i} ｜ {name} ｜ {c['pub']} ｜ `{pid}`\n"]
    if title:
        lines.append(f"标题：{title}\n")
    lines.append("\n".join("> " + ln for ln in text.splitlines() or [""]))
    lines.append("")
    if not found:
        lines.append("（引文在正文里搜不到 —— 存疑，先看这里）\n")
    lines.append("| 遍 | d | spec | idx | 引文 |")
    lines.append("|:---|:---|:---|:---|:---|")
    lines += _sig_rows("第一遍", c["甲"])
    lines += _sig_rows("第二遍", c["乙"])
    if has_lib:
        lines += _sig_rows("库（参考）", lib_sigs)
    lines.append("")
    # **逐条**核 —— 只要有一条搜得到，`_window` 就不报警，剩下搜不到的那几条会不声不响
    missed = [q for q in dict.fromkeys(quotes) if q and q not in content]
    if missed:
        lines.append("**回正文搜不到**：" + "、".join(f"「{q}」" for q in missed)
                     + " —— 逐字对不上，多半是跨行拼接\n")
    lines.append("**裁定**")
    return "\n".join(lines) + "\n"


def _library() -> dict:
    """库里那一份（参考列）—— 读 `data/signals/`，**不参与一致／不一致的判定**。"""
    out: dict[str, dict[str, list[dict]]] = {}
    if not paths.SIGNALS_DIR.exists():
        return out
    for f in sorted(paths.SIGNALS_DIR.glob("*.json")):
        rows = json.loads(f.read_text(encoding="utf-8")).get("signals") or []
        per: dict[str, list[dict]] = {}
        for r in rows:
            per.setdefault(r["post_id"], []).append(r)
        out[f.stem] = per
    return out


# ── 入口 ────────────────────────────────────────────────────────────────

def _split(rest: list[str]) -> tuple[list[str], dict[str, str]]:
    """把 `--out x` 摘出去，剩下的是位置参数。"""
    pos, opts, i = [], {}, 0
    while i < len(rest):
        if rest[i].startswith("--"):
            opts[rest[i]] = rest[i + 1] if i + 1 < len(rest) else ""
            i += 2
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

    if a[0] == "run":
        return cmd_run(opts.get("--out") or "_pass")
    if a[0] == "cmp" and len(pos) >= 2:
        return cmd_cmp(pos[0], pos[1])
    if a[0] == "draft" and len(pos) >= 2 and opts.get("--out"):
        return cmd_draft(pos[0], pos[1], opts["--out"])
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main())
