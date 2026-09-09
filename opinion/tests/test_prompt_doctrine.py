# -*- coding: utf-8 -*-
"""方向教义回归（2026-09-09，纯文本断言不调 API）。

2026-09-09 教义纠正（用户裁决）：条件式/先A后B形态 → 无方向不硬凑 ±1；
加减仓等操作动词 = 方向同义（动作=方向、状态=无方向）；净方向照提；不明确就无方向。
强制机制 = 仅指令 + 复核（无确定性代码门）——因此指令文本是唯一能落地的层，
本测试防止未来有人回退/覆盖四处指令（共享 prompt / 推送 verify / 报告后缀 / 报告 verify）。

- 共享 prompt（opinion/prompts.ANNOTATION_SYSTEM_PROMPT，双链共用）
- 推送复核（opinion.verify.REVIEW_SYSTEM_PROMPT）
- 报告 extract 后缀 + 报告 verify（scripts/pipeline/extract_signals_direction.py）

直接 python3 运行。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from opinion import prompts as o_prompts     # noqa: E402
from opinion import verify as o_verify       # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "report_extract", os.path.join(ROOT, "scripts", "pipeline", "extract_signals_direction.py"))
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

P = o_prompts.ANNOTATION_SYSTEM_PROMPT
V_PUSH = o_verify.REVIEW_SYSTEM_PROMPT
V_REPORT = ex.VERIFY_SYSTEM_PROMPT
SUFFIX = ex._REPORT_EXTRACT_SUFFIX


def _has(txt, *subs, label):
    for s in subs:
        assert s in txt, f"[{label}] 应含 {s!r}"
    print(f"[PASS] {label}：含 {len(subs)} 条锚句")


def _not_has(txt, *subs, label):
    for s in subs:
        assert s not in txt, f"[{label}] 不应含旧反教义 {s!r}"
    print(f"[PASS] {label}：无旧反教义 {len(subs)} 条")


# ── 共享 prompt：无条件限定 + 条件式/形态无方向 + 净方向照提 + 加减仓同义 + 示例对反例 ──
_has(P,
     "无条件明确方向预测",                       # 任务句
     "## 无方向：条件式与先A后B形态", "2026-09-09 教义",
     "条件式不提取", "分水岭", "否则转震荡",
     "先A后B日内路径形态不提取", "冲高回落/高开低走/探底回升",
     "净方向照提（唯一例外）", "反弹结束重新二次探底",
     "减仓/清仓/轻仓/止盈/逢高抛/卖出", "加仓/重仓/补仓/逢低买/抄底",   # 同义（空→/多→）
     "无时间词", "破了3900就减仓",              # 无时间口径 + 条件内嵌操作仍无方向
     "不产行（该帖若仅此一句",                   # 输出区反例（旧示例改判）
     label="共享 prompt 新教义")
_not_has(P,
         "看空，沪指3900-3950震荡",              # 旧示例：冲高回落→d=-1 摘要
         '仓位自述（"还剩4成仓"',                 # 旧：仓位自述整类丢（已拆状态/动作）
         label="共享 prompt 无旧反教义")

# ── 推送复核：条件/形态主句硬凑 d → drop/fix；净方向 keep；操作 vs 状态 ──
_has(V_PUSH,
     "仓位状态自述/无明确方向",                  # 判定要点1 drop 桶（不再一刀切仓位自述）
     "条件式与先A后B形态不硬凑 d", "无条件**主结论",
     "净方向 vs 操作句 vs 状态句",
     "减/清/止盈→空", "加/重/补/抄底→多",
     "还剩4成",
     label="推送 verify 新教义")
_not_has(V_PUSH, "仓位自述/无明确方向", label="推送 verify 无旧一刀切桶")

# ── 报告 extract 后缀：条件式/区间句无方向不产行（target 段落反转）──
_has(SUFFIX,
     "条件式/区间句 = 无方向、不产行", "一切条件式无方向",
     "守住3900看反弹",                          # 现在只作"不进 rows"的反例出现
     "该帖若仅此内容 → no_view", "反弹目标4200",  # target 仍保留给无条件移动目标
     "无条件净方向", "操作动词 = 方向同义",
     "spec=t5 计分",                            # 报告侧无时间词口径
     label="报告 extract 后缀新教义")
_not_has(SUFFIX, "守住3900看反弹\"→d=1", "方向照取博主真实观点", label="报告后缀无旧照取教义")

# ── 报告 verify：条件式硬凑 drop；净方向句 keep；操作=方向、状态才 drop ──
_has(V_REPORT,
     "并无带方向的独立无条件主结论",             # 第一步：整帖只有条件/形态 → 无主结论
     "条件式硬凑的方向", "无条件净方向句",
     "操作动作本身是方向", "减/清/止盈→空",
     "仓位状态自述", "还剩几成/满仓持股",
     label="报告 verify 新教义")

# ── B3 教义单一同源：标注/报告后缀嵌 DOCTRINE_NO_DIRECTION，双复核嵌 DOCTRINE_REVIEW，
#    哨兵零泄漏（改 prompts 常量一处 → 四处文本同变，杜绝逐地手改漂移）──
D_NO = o_prompts.DOCTRINE_NO_DIRECTION
D_REV = o_prompts.DOCTRINE_REVIEW
assert D_NO in P, "共享 ANNOTATION prompt 必须内嵌 DOCTRINE_NO_DIRECTION"
assert D_NO in SUFFIX, "报告 extract 后缀必须插值 DOCTRINE_NO_DIRECTION"
assert D_REV in V_PUSH and D_REV in V_REPORT, "推送 REVIEW 与报告 VERIFY 必须同嵌 DOCTRINE_REVIEW"
for _t, _n in [(P, "共享 prompt"), (V_PUSH, "推送 verify"), (V_REPORT, "报告 verify"), (SUFFIX, "报告后缀")]:
    assert "__DOCTRINE" not in _t, f"{_n} 残留教义哨兵（replace 未生效）"
assert o_prompts.ANNOTATION_SYSTEM_PROMPT.count("## 无方向：条件式与先A后B形态") == 1
print("[PASS] B3 同源：DOCTRINE_NO_DIRECTION/REVIEW 插值四处 + 哨兵零泄漏")

print("\n全部方向教义文本回归通过 ✅")
