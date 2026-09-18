# -*- coding: utf-8 -*-
"""量正则辅助这一层值多少。

    python -m research.regex_ab arms                      # 七个臂都是什么
    python -m research.regex_ab census                    # 不花调用：清单覆盖、断句、has_cond
    python -m research.regex_ab headroom                  # 不花调用：清单的作用面有多大
    python -m research.regex_ab run <臂> [--out 路径]       # 跑一个臂（金标 6 位博主）
    python -m research.regex_ab cmp <产出A> <产出B>         # 两臂比，六组计数
    python -m research.regex_ab draft <产出A> <产出B> --out 路径   # 出判例草稿
    python -m research.regex_ab adopted <产出>              # 模型落的 spec／idx 对不对得上词典
    python -m research.regex_ab gold <产出>                 # 金标 42 条逐条核

**跑一个臂之前先量 `headroom`** —— 清单只在「一帖不止一个时间词／对象词、查出的值还不
一样」的帖上才有活干。那个数太小，七臂就不值得跑。

**`ablate` 已删**（2026-09-18）—— 它量的是条件句守门，而那一条整个撤掉了（见 `README.md` §五）。

**`blogger/` 一个字不改**：开关全在运行时装在模块属性上（见 `arms.py`），跑完就还原。
不抓帖、不写判断缓存、不碰 `data/`、不动调度。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from research.regex_ab import arms, offline
from research.semparse import jitter

# 金标 42 条里可评的那 6 位 —— 跑完可评数从 33 条升到 40 条
GOLD_BLOGGERS = ["云帆观市", "故乡的云ZYH", "江河之水终有入海之日",
                 "诸葛不亮", "爱生活的荷叶Rp", "知行合一"]


def cmd_run(arm: str, out: str) -> int:
    from blogger.common import paths

    missing = [n for n in GOLD_BLOGGERS if n not in paths.roster()]
    if missing:
        print(f"名册里没有这几位：{'、'.join(missing)} —— 核一下 paths.roster()")
        return 2

    # **断点续跑** —— 已经判成的那几位不重来。跑到一半被掐掉（后台任务重启、断网），
    # 再起一次就行，不白烧调用。判错的那几位（`__tally__` 里带 `出错`）会重来。
    doc: dict = _read(out)
    todo = [n for n in GOLD_BLOGGERS
            if not (doc.get(n) and "出错" not in (doc[n].get("__tally__") or {}))]
    if doc:
        print(f"续跑：已有 {len(doc)} 位，这次跑 {len(todo)} 位")

    print(f"臂 {arm} · {arms.title(arm)}｜{len(todo)} 位博主｜runs={jitter.extract.RUNS}")
    t0 = time.time()
    with arms.armed(arm):                       # 开关只在 `with` 里头有效
        for i, name in enumerate(todo, 1):
            t1 = time.time()
            print(f"\n[{i}/{len(todo)}] {name}")
            try:
                doc[name] = jitter.judge_once(name)
            except Exception as e:              # 一位跑不成不牵连其余
                print(f"  这一位没跑成：{e!r}")
                doc[name] = {"__tally__": {"出错": repr(e)}}
            # 跑一位写一次 —— 中途断了前面的不白跑（照抄 jitter.cmd_run 的节奏）
            _write(out, doc)
            print(f"  {time.time() - t1:.0f}s")
    if not todo:
        print("都跑过了，没动。")
    print(f"\n用时 {time.time() - t0:.0f}s → {out if out.endswith('.json') else out + '.json'}")
    return 0


def _path(out: str) -> Path:
    return Path(out if out.endswith(".json") else out + ".json")


def _read(out: str) -> dict:
    p = _path(out)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _write(out: str, doc) -> None:
    p = _path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_arms() -> int:
    print(f"金标 6 位：{'、'.join(GOLD_BLOGGERS)}\n")
    for a in arms.names():
        print(f"  {a:<3} {arms.title(a)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if not a:
        print(__doc__.strip())
        return 2

    verb, rest = a[0], a[1:]
    pos = [x for x in rest if not x.startswith("--")]
    opts = {rest[i]: rest[i + 1] for i in range(len(rest) - 1) if rest[i].startswith("--")}

    if verb == "arms":
        return cmd_arms()
    if verb == "census":
        offline.census()
        return 0
    if verb == "headroom":
        offline.headroom()
        return 0
    if verb == "run" and pos and pos[0] in arms.ARMS:
        return cmd_run(pos[0], opts.get("--out") or f"research/regex_ab/runs/{pos[0]}")
    if verb == "cmp" and len(pos) >= 2:
        return jitter.cmd_cmp(pos[0], pos[1])
    if verb == "draft" and len(pos) >= 2 and opts.get("--out"):
        return jitter.cmd_draft(pos[0], pos[1], opts["--out"])
    if verb == "adopted" and pos:
        offline.adopted(pos[0])
        return 0
    if verb == "gold" and pos:
        offline.gold_on(pos[0])
        return 0

    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main())
