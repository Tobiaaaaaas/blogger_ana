# -*- coding: utf-8 -*-
"""端到端试跑 —— 跑一位博主的 ②～⑦ 步（跳过 ① 抓取与补行情）。

用的是 `blogger.report.flow` 里**真的那几个函数**，既不动生产数据，也不需要浏览器。

    python blogger/tests/drive.py [博主名]

跑法：把 `fixture/` 拷进一个临时数据根，行情从仓库的 `data/market` 接过去；
跑完结果留在那个临时目录里，**仓库一个字节都不写**。
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]                       # blogger/tests → 仓库根
SCRATCH = Path(tempfile.gettempdir()) / "blogger_selftest"


def build_root() -> Path:
    """把 fixture 铺成一个数据根：帖子／信号／缓存照搬，行情从仓库接过去。"""
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    shutil.copytree(HERE / "fixture", SCRATCH / "data")
    link = SCRATCH / "data" / "market"
    try:
        link.symlink_to(REPO / "data" / "market")
    except OSError:                          # Windows 上没权限就整份拷
        shutil.copytree(REPO / "data" / "market", link)
    return SCRATCH


os.environ["BLOGGER_ROOT"] = str(build_root())
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from blogger.common import market, paths                       # noqa: E402
from blogger.report import cache, flow, stats, store, verify   # noqa: E402

BLOGGER = sys.argv[1] if len(sys.argv) > 1 else "aniu24W"

print("数据根 =", paths.ROOT)
print("行情到 =", market.LAST_DATE)

posts = flow.load_posts(BLOGGER)
print("[② 解析]")
judged, tally, no_note = flow.judge_posts(BLOGGER, posts, print)

print("[③ 保存]")
ids = {p["post_id"] for p in posts}
rows = [r for r in cache.rows_of(judged) if r["post_id"] in ids]
store.save(BLOGGER, rows)
print("  %d 条 → %s" % (len(rows), paths.signals_file(BLOGGER)))

print("[④ 事后验证]")
evaluated = [verify.evaluate(r) for r in rows]

print("[⑤ 单列]")
unscored = [r for r in evaluated if r["note"] != verify.SCORED]
t = stats.tally(evaluated)
print("  信号 %d 条（计分 %d / 不计分 %d）｜不是信号 %d 条（行照留，不删）"
      % (t["signals"], t["scored"], t["unscored"], t["total"] - t["signals"]))

print("[⑥ 统计]")
flow._write_report(BLOGGER, evaluated, posts, print)

print("[⑦ 清单]")
flow._report_dropped(tally, no_note, unscored, print)

print("\n" + "=" * 70)
print("产出的 %d 行：" % len(evaluated))
for r in sorted(evaluated, key=lambda x: x["pub"]):
    ep = market.endpoint(r["pub"], r["spec"]) or "—"
    print("  %s %-8s %+d  %-22s 终点 %s  %s"
          % (r["pub"], r["spec"], r["d"], r["idx"], ep, r["quote"][:44].replace("\n", " ")))

print("\n[04§3.2 交叉核对]")
from blogger.tests import invariant                      # noqa: E402
invariant.main([BLOGGER])

print("\n解析统计：", {k: v for k, v in tally.items() if k not in ("丢弃清单", "去重清单")})
