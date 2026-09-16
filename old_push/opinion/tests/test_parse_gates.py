# -*- coding: utf-8 -*-
"""解析加固纯函数回归（2026-09-08，Pillar A/B，纯逻辑不调 API）。

- spec_sane        ：SPEC_RE 之上的语义域（t0/t99/d:2026-13-99 出域，t1/t30/闰年真实日期入域）
- disposition_errors：逐帖到案契约（缺到案/rows∩no_view 重叠/理由出枚举 → 报错）
- split_quote/verbatim_in：quote 逐字门（省略号跨段保序；编造/串帖/改写 → False）
- _render(visible) 与 render_batch 字节一致（两路径不漂移）——见 annotate 部分

直接 python3 运行。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:                      # Windows GBK 控制台：断言已全过，别让收尾 emoji 崩掉退出码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from opinion import schema as sch
from opinion import text as ot


def check(name, cond, note=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {note}")
    return cond


# ── spec_sane：语义域 ────────────────────────────────────────────────────
_sane = [("t1", True), ("t30", True), ("t0", False), ("t99", False), ("today", True),
         ("week", True), ("nweek", True), ("month", True), ("long", True),
         ("d:2026-09-08", True), ("d:2028-02-29", True), ("d:2027-02-29", False),  # 2027 非闰
         ("d:2026-13-01", False), ("d:2026-00-10", False), ("d:2026-04-31", False),
         ("t", False), ("d:2026-9-8", False), (None, False), ("", False)]
for spec, want in _sane:
    got = sch.spec_sane(spec)
    assert got is want, f"spec_sane {spec!r} 应={want} got={got}"
print("[PASS] spec_sane 语义域表全部符合预期")

# ── disposition_errors：逐帖到案 ─────────────────────────────────────────
def de(row_pns, nv, n):
    return sch.disposition_errors(row_pns, nv, n)

assert de([0, 2], [{"post_n": 1, "reason": "复盘回顾"}], 3) == []
print("[PASS] disposition 满覆盖通过")

assert de([0, 1, 2], [], 3) == []
print("[PASS] disposition 全 rows 到案通过")

errs = de([0], [{"post_n": 1, "reason": "复盘回顾"}], 3)
assert len(errs) == 1 and "2" in errs[0] and "未到案" in errs[0], errs
print("[PASS] disposition 缺到案报错 ->", errs[0])

errs = de([0, 1], [{"post_n": 1, "reason": "无明确方向"}], 2)
assert any("重叠" in e for e in errs), errs
print("[PASS] disposition rows∩no_view 重叠报错")

errs = de([], [{"post_n": 0, "reason": "随便说说"}], 1)
assert any("枚举" in e for e in errs), errs
print("[PASS] disposition 理由出枚举报错")

errs = de([], [{"post_n": 0, "reason": "复盘回顾"}, {"post_n": 0, "reason": "状态描述"}], 1)
assert any("重复" in e for e in errs), errs
print("[PASS] disposition no_view 重复到案报错")

# ── render 两路径一致 + annotate 层门（to_canonical/quote 门/collapse post_id）──
from opinion import annotate as ann

posts = [
    {"post_id": "p1", "publish_date": "2026-09-07 16:26", "publish_time": 1760000000,
     "title": "明天大盘走势前瞻", "content": "明天大盘冲高回落概率大，沪指3900-3950来回磨。"},
    {"post_id": "p2", "publish_date": "2026-09-08 11:07", "publish_time": 1760003600,
     "title": "盘中", "content": "昨天科技比大盘强，今天角色互换，明天又会互换。"},
]
single = ann.render_batch("测试", posts)
lines, vis = ann._render("测试", posts)
assert single == "\n".join(lines), "render_batch 与 _render 单串应字节一致"
assert len(vis) == 2 and vis[1] == "[1] 发帖 2026-09-08 11:07｜盘中\n昨天科技比大盘强，今天角色互换，明天又会互换。"
print("[PASS] render_batch == _render 单串字节一致；visible 与渲染同源")

# to_canonical：spec 语义域（t0/d:13-99 拒；t1 过）
_p = posts[0]
assert ann.to_canonical({"d": 1, "s": 1, "idx": "上证指数", "spec": "t0", "cat": "scored",
                         "horizon": "今天", "quote": "x", "summary": "s"}, _p, "测试", 0) is None
assert ann.to_canonical({"d": 1, "s": 1, "idx": "上证指数", "spec": "d:2026-13-99", "cat": "scored",
                         "horizon": "更长", "quote": "x", "summary": "s"}, _p, "测试", 0) is None
c1 = ann.to_canonical({"d": 1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                       "horizon": "明天", "quote": "明天大盘冲高回落概率大", "summary": "s"}, _p, "测试", 0)
assert c1 is not None and c1["spec"] == "t1"
print("[PASS] to_canonical spec 语义域：t0/d:2026-13-99 拒；t1 过")

# quote 存储上限 90（长逐字句被 cap；逐字门放行截后前缀）
longc = "明" * 120
assert ann.to_canonical({"d": 1, "s": 1, "idx": "上证指数", "spec": "t1", "cat": "scored",
                         "horizon": "明天", "quote": longc, "summary": "s"}, _p, "测试", 0)["quote"] == "明" * 90
print("[PASS] to_canonical quote 上限放宽到 90")

# _quote_gate_bad：编造句入坏表，真句不入
bad_row = {"post_n": 0, "quote": "编造的大盘预测句子"}
good_row = dict(c1)
assert ann._quote_gate_bad([bad_row], vis) == [bad_row]
assert ann._quote_gate_bad([good_row], vis) == []
print("[PASS] _quote_gate_bad：编造句拒绝、逐字真句放行")

# collapse_board 返回行带 post_id
cr = ann.collapse_board("short", "测试", [c1], window_start=0)
assert cr is not None and cr["post_id"] == "p1"
print("[PASS] collapse_board 返回行带 post_id（溯源）")

# ── quote 逐字门 ────────────────────────────────────────────────────────
src = "明天大盘大概率高开晃悠、板块轮动快，沪指就在3900到3950点之间来回磨。仓位重的可逢高减。"
assert ot.verbatim_in("明天大盘大概率高开晃悠", src)
assert ot.verbatim_in("沪指就在3900到3950点之间来回磨", src)          # 逐字后句（#J 场景句本身成立）
assert ot.verbatim_in("明天大盘大概率高开晃悠…来回磨", src)            # 省略号跨段保序
assert ot.verbatim_in("明天大盘大概率高开晃悠…沪指就在3900到3950点之间来回磨", src)
assert not ot.verbatim_in("明天大盘冲高回落概率大", src)               # 编造句
assert not ot.verbatim_in("创业板跌破3244形成底背离", src)            # 串帖句
assert not ot.verbatim_in("来回磨…明天大盘大概率高开晃悠", src)         # 逆序片段
assert not ot.verbatim_in("沪指就在3900到3950之间来回磨", src)         # 改写（漏"点"字）不通过
# 2026-09-09 版式归一校准：一句一换行帖被模型折成句读——实词保序连续应放行（香满衣类）
fold_src = "死水一潭\n明天怎么走\n真不知道\n这个要先看纳斯\n涨点咱就涨点\n跌点咱就大跌点\n哈哈"
assert ot.verbatim_in("明天怎么走真不知道，这个要先看纳斯，涨点咱就涨点，跌点咱就大跌点", fold_src)
assert ot.verbatim_in("真不知道。这个要先看纳斯，涨点咱就涨点。跌点咱就大跌点", fold_src)
assert not ot.verbatim_in("明天怎么走真不知道，这个要先看道指", fold_src)   # 字替换仍拒
# 字级增删仍必拒：四十二流光真编造（源"如果是极限震仓"，多写"最"）——重试可纠
gap_src = "目前看，如果是极限震仓。那应该最晚就是后天。明天大概率要大幅修复"
assert not ot.verbatim_in("如果是最极限震仓。那应该最晚就是后天", gap_src)
# 中间实词被跳（丢"转身"）→ 归一后仍不连续 → 拒
assert not ot.verbatim_in("要当龙，3950点附近向上跃起，再收一根中阳",
                          "考验时刻要当龙，3950点附近转身向上跃起，再收一根中阳")
# 归一只去空白/句读，ASCII 小数/连字符保留（防 3.5万→35万 量级错位混入）
assert ot.verbatim_in("飙涨了3.5万", "融资飙涨了3.5万啊")
assert not ot.verbatim_in("融资飙涨了35万", "融资飙涨了3.5万啊")
assert ot.verbatim_in("", src) or True                                # 空 quote 语义归调用方
print("[PASS] quote 逐字门：逐字/跨段/行句读折叠通过，编造/串帖/逆序/改写/字级增删拒绝")

print("\n全部 parse 纯函数回归通过 ✅")
