# -*- coding: utf-8 -*-
"""量「矛盾复核」（02§10.5）这一层值多少。

    python -m research.crosscheck scan                        # 不花调用：扫出对不上的那几处
    python -m research.crosscheck run --out research/crosscheck/run.json    # 两个臂各跑一遍
    python -m research.crosscheck cmp research/crosscheck/run.json          # 比两臂

**跑在手上 `data/signals/` 的活产出上，不重跑全库。** 矛不矛盾是拿**已经落盘的行**跟引文
对的，不是重新判一遍 —— 重判出来的东西跟库里那份不是一回事，量不了「复核改对了没有」。

**两个臂，差别只有一样：摆不摆「存疑的几处」。**

| 臂 | 系统提示 | 喂帖文本 |
|:---|:---|:---|
| A 带提示 | `CHECK_SYSTEM_PROMPT` | 帖 ＋「存疑的几处」 |
| B 对照 | 同上 | 只有帖 |

**对照臂是必须的** —— 没有它，分不清「改对了」是提示挣来的，还是模型自己重读一遍就会改。
两臂的系统提示完全相同，唯一的变量就是那条提示。

**一律不写 `data/`、不碰判断缓存、不动调度。** 要调模型，先 `set -a && source
./.deepseek_keys.env && set +a`。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from blogger.common import ds, market, params
from blogger.parse import extract, prompts, schema
from research.crosscheck import offline

ARMS = (("A", "带矛盾提示"), ("B", "对照：不带提示"))


def _user_text(post: dict, sig: dict | None, why: str) -> str:
    """喂帖文本。`sig` 为 `None` 就是对照臂 —— 只有帖，不摆任何提示。"""
    note = market.pub_note(post["pub"]) or ""
    body = extract.render_post(0, post, note)
    if sig is None:
        return body
    items = [{"post_n": 0, "d": sig["d"], "spec": sig["spec"], "idx": sig["idx"],
              "quote": sig["quote"], "疑问": why}]
    return f"{body}\n\n## 存疑的几处\n{json.dumps({'items': items}, ensure_ascii=False, indent=1)}"


def _reread(post: dict, sig: dict | None, why: str, label: str) -> tuple[list[dict], str]:
    """让模型重读这一帖，返回 `(这一帖的最终产出, 出错说明)`。"""
    try:
        result = ds.call_json(prompts.CHECK_SYSTEM_PROMPT, _user_text(post, sig, why),
                              label=label, need="signals")
    except ds.ModelError as e:
        return [], f"{type(e).__name__}: {e}"
    rows = []
    for raw in (result.get("signals") or []):
        one, _ = schema.to_signal(raw, post)
        if one is not None:
            rows.append(one)
    return schema.dedup(rows, [post]), ""


def cmd_scan() -> int:
    hits = offline.scan()
    print(f"命中 {len(hits)} 处\n")
    for name, post, s, why in hits:
        print(f"  {name} {s['pub']} {s['d']:+d} {s['spec']} {s['idx']}")
        print(f"    引文　{s['quote']}")
        print(f"    {why}")
    return 0


def cmd_run(out: str) -> int:
    hits = offline.scan()
    if not hits:
        print("一处都没命中。")
        return 0

    doc: dict = {"meta": {"model": params.get("parse.model", ""), "命中": len(hits)},
                 "hits": [], "arms": {a: {} for a, _ in ARMS}}
    for name, post, s, why in hits:
        doc["hits"].append({"name": name, "post_id": s["post_id"], "pub": s["pub"],
                            "quote": s["quote"], "why": why})

    for arm, title in ARMS:
        print(f"\n══ 臂 {arm}（{title}）══")
        for i, (name, post, s, why) in enumerate(hits, 1):
            before = [r for r in offline.signals_of(name) if r["post_id"] == s["post_id"]]
            rows, err = _reread(post, s if arm == "A" else None, why,
                                label=f"复核{arm} {i}/{len(hits)} {name}")
            print(f"  [{i}/{len(hits)}] {name} {s['pub']}")
            print(f"    {offline.triples(before)}  →  {offline.triples(rows) if not err else err}")
            doc["arms"][arm][f"{name}|{s['post_id']}"] = {
                "name": name, "pub": s["pub"], "why": why,
                "before": before, "after": rows, "err": err}
            time.sleep(1)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {out}")
    return 0


def cmd_cmp(path: str) -> int:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    keys = list(doc["arms"]["A"])
    print(f"命中 {len(keys)} 处｜模型 {doc['meta'].get('model', '')}\n")

    print("| 臂 | 改了 | 维持 | 没跑成 |")
    print("|:---|---:|---:|---:|")
    for arm, title in ARMS:
        rows = doc["arms"][arm]
        changed = sum(1 for k in keys
                      if offline.triples(rows[k]["before"]) != offline.triples(rows[k]["after"]))
        err = sum(1 for k in keys if rows[k]["err"])
        print(f"| {arm} {title} | {changed} | {len(keys) - changed - err} | {err} |")

    for arm, title in ARMS:
        print(f"\n══ 臂 {arm}（{title}）改过的 ══")
        for k in keys:
            r = doc["arms"][arm][k]
            if offline.triples(r["before"]) == offline.triples(r["after"]):
                continue
            print(f"  {r['name']} {r['pub']}")
            print(f"    原　{offline.triples(r['before'])}")
            print(f"    改　{offline.triples(r['after'])}")
            if r["after"]:
                print(f"    新引文　{r['after'][0]['quote']}")

    print("\n══ 两臂对不上的 ══")
    n = 0
    for k in keys:
        a, b = doc["arms"]["A"][k], doc["arms"]["B"][k]
        if offline.triples(a["after"]) == offline.triples(b["after"]):
            continue
        n += 1
        print(f"  {a['name']} {a['pub']}｜A {offline.triples(a['after'])}"
              f"　B {offline.triples(b['after'])}")
    if not n:
        print("  一处都没有")
    return 0


def main(argv: list[str] | None = None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if not a:
        print(__doc__.strip())
        return 2
    verb, rest = a[0], a[1:]
    pos = [x for x in rest if not x.startswith("--")]
    opts = {rest[i]: rest[i + 1] for i in range(len(rest) - 1) if rest[i].startswith("--")}

    if verb == "scan":
        return cmd_scan()
    if verb == "run" and opts.get("--out"):
        return cmd_run(opts["--out"])
    if verb == "cmp" and pos:
        return cmd_cmp(pos[0])

    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main())
