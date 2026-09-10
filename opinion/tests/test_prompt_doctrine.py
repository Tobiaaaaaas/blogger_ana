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
try:                      # Windows GBK 控制台：断言已全过，别让收尾 emoji 崩掉退出码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
D_NO = o_prompts.DOCTRINE_NO_DIRECTION
D_REV = o_prompts.DOCTRINE_REVIEW


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

# ── 一帖多周期各产一行（R1）＋ 周期词不救形态（R2）：共享 prompt 与报告后缀同达 ──
_has(P,
     "每个周期各产一行（必做）", "不得只取近端周期句",   # R1：一帖多周期各行
     "不得丢弃远端周期",
     "周期词不救形态", "有周期词的形态句仍是形态句",      # R2：周期词不救形态
     "这周高开低走", "今天冲高回落", "下周探底回升",      # R2 反例（周期词+形态）
     "今天市场会大涨", "综合看这周市场启动的判断不变",    # R1/R2/输出区正例共用原句
     "一帖两周期各产一行",                              # 输出区正例
     label="共享 prompt R1/R2 多周期各行 + 输出区正例")
_has(SUFFIX, "周期词不救形态", "每个周期各产一行（必做）", label="报告后缀 R1/R2 同达")

# ── 2026-09-10 裁决①：同期形态 + 泛净方向句 = 产行（灰区判死，不再摇摆）──
_has(P,
     "同期形态 + 泛净方向句 = 产行", "2026-09-10 裁决", "定死不摇摆",
     "下周先抑后扬，整体看多",                   # 用户原句（智由智哉 09-06 帖）
     "必须含净方向词", "不得**只截",              # quote 纪律：不许只截形态半句
     "全帖再无该周期方向句",                      # 反例：只有形态仍不产行
     label="共享 prompt 灰区产行（Q4 裁决）")
_has(P, "整体看多", "下周探底回升", label="共享 prompt 灰区正例/反例并存")

# ── 2026-09-10 编码纠正②：「下周一」按是否为发帖后首个交易日分叉 t1 / nweek_first ──
_has(P,
     "按该日是否为发帖日之后的首个交易日判定", "2026-09-10 编码纠正",
     "周五/周六/周日发帖说", "语义等于", "周一~周四发帖",
     label="共享 prompt 「下周一」编码分叉")
_not_has(P, '"下周一" → nweek_first', label="共享 prompt 无「下周一」一律 nweek_first 旧编码")

# ── 2026-09-10 周口径修正③：非交易日「本周」——先自问回顾还是前瞻；非交易日不得产 week ──
# 引擎侧：week = 发帖日所在 ISO 周最后交易日（周末发帖 → 该周已收盘 → 终点早于发帖日）。
# 判层侧（2026-09-10 提升为**共享教义**，四处同达）：引导模型对非交易日帖里的"本周/这周"
# 先自问"博主说的是刚走完的那一周（复盘）还是马上要开盘的那一周（预测）" → 复盘不产行 /
# 前瞻编 nweek；复核侧同源（week→nweek fix / 复盘 drop）。此前只写在 ANNOTATION prompt 与
# 报告后缀两处手写拷贝里、复核侧完全缺失 → 错编的 week 行既不会被修成 nweek 也不会被 drop。
_has(D_NO,                                   # 共享教义 → 自动同达 ANNOTATION prompt 与报告后缀
     "先自问是\"刚结束的那一周\"还是\"即将到来的那一周\"", "2026-09-10 周口径",
     "博主说的是刚走完、已经结束的那一周（复盘），还是马上要开盘的那一周（预测）",
     "不产行", "必须编码 `nweek`", "此时产 `week` 必有错",
     "286 条", "223 条",                       # 实证：curated 语料回溯（987 week 行）
     label="共享教义「本周」已走完时的自问分叉")
# 反过度应用：周中假日（如周一休市但本周之后仍有交易日）的 "本周" 是正常 week 行 —— 缺这条
# 会把 14 条合法行（curated 实测 02-23 / 04-06 / 05-04 / 05-05）误杀。
_has(D_NO, "别过度应用（反例）", "周中假日", "本周**尚未**走完",
     label="共享教义 反过度应用（周中假日仍正常 week）")
_has(P, "先分清是\"回顾\"还是\"前瞻\"", "本周已走完（典型：周六/周日发帖）时不得产 `week`",
     label="共享 prompt §周期编码 指针句")
_has(SUFFIX, "「本周」已走完时发帖说\"本周\"", "该行不得产 `week`",
     "回顾句不产行、前瞻句编 `nweek`", "本周尚未走完",
     label="报告后缀「本周」已走完时同口径")
_has(D_REV,                                  # 复核镜像：fix→nweek / 复盘与存疑 drop / 反过度应用
     "9. **「本周」已走完时发的 `week` 行", "spec→`nweek`", "不得 drop", "复盘刚结束那一周",
     "无从判断", "死行", "别过度应用",
     label="DOCTRINE_REVIEW 条目 9「本周」已走完时 week 复核")
_has(V_PUSH, "「本周」已走完时发的 `week` 行", label="推送 verify 条目 9 同达")
_has(V_REPORT, "「本周」已走完时发的 `week` 行", label="报告 verify 条目 9 同达")

# ── 具体日期口径（D3 一致）：不产 d:YYYY-MM-DD，自然日差落 tN / 远期 long ──
_has(P, "不写 d:YYYY-MM-DD", "自然日差", "t10", label="共享 prompt 具体日期落档位")
_not_has(P, "→ d:YYYY-MM-DD", label="共享 prompt 无具体日期→d: 旧指令")
_has(SUFFIX, "不写 d:YYYY-MM-DD", "自然日差", label="报告后缀具体日期同口径")

# ── 推送复核：条件/形态主句硬凑 d → drop/fix；净方向 keep；操作 vs 状态 ──
_has(V_PUSH,
     "仓位状态自述/无明确方向",                  # 判定要点1 drop 桶（不再一刀切仓位自述）
     "条件式与先A后B形态不硬凑 d", "无条件**主结论",
     "净方向 vs 操作句 vs 状态句",
     "减/清/止盈→空", "加/重/补/抄底→多",
     "还剩4成",
     label="推送 verify 新教义")
_not_has(V_PUSH, "仓位自述/无明确方向", label="推送 verify 无旧一刀切桶")

# ── 2026-09-10 复核镜像：灰区产行行必须 keep/fix、不得被复核 drop（不镜像=新行当档即被 drop）──
_has(V_PUSH,
     "同期形态 + 泛净方向句（2026-09-10 裁决）", "下周先抑后扬，整体看多",
     "该行**成立**", "**不 drop**",
     label="推送 verify 灰区镜像（Q4 keep 分支）")
_has(V_REPORT, "下周先抑后扬，整体看多", label="报告 verify 灰区镜像同达")
assert "同期形态 + 泛净方向句" in o_prompts.DOCTRINE_REVIEW, \
    "DOCTRINE_REVIEW 应含 2026-09-10 灰区 keep 条目"
print("[PASS] 同源：2026-09-10 灰区裁决已镜像进 DOCTRINE_REVIEW（双复核同达）")

# ── 推送复核判定要点 1 按行周期限定：一帖多周期各行独立，不 cross-fix ──
_has(V_PUSH,
     "该行所载周期",                             # 主结论句 doctrine 限定到该行所载周期
     "见教义节 8",                              # 一帖多周期各行独立
     label="推送 verify 要点1 按行周期")
_not_has(V_PUSH, "行必须与之一致", label="推送 verify 无旧一刀切措辞")

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

# ── 报告 VERIFY 第一步：主结论限定该行周期，去 cross-fix；多周期按教义节 8 ──
_has(V_REPORT,
     "该行所载周期", "互不构成不一致",           # 一帖多周期各自独立评审
     "复核教义节 8",                            # 只影响本行、不 cross-fix 其它周期行
     label="报告 verify 第一步按行周期")
_not_has(V_REPORT, "改为主结论句的方向/周期", label="报告 verify 无旧 cross-fix 指令")

# ── B3 教义单一同源：标注/报告后缀嵌 DOCTRINE_NO_DIRECTION，双复核嵌 DOCTRINE_REVIEW，
#    哨兵零泄漏（改 prompts 常量一处 → 四处文本同变，杜绝逐地手改漂移）──
assert D_NO in P, "共享 ANNOTATION prompt 必须内嵌 DOCTRINE_NO_DIRECTION"
assert D_NO in SUFFIX, "报告 extract 后缀必须插值 DOCTRINE_NO_DIRECTION"
assert D_REV in V_PUSH and D_REV in V_REPORT, "推送 REVIEW 与报告 VERIFY 必须同嵌 DOCTRINE_REVIEW"
assert '8. **多周期各行独立评审' in D_REV, "DOCTRINE_REVIEW 应含条目 8（多周期各行独立评审）"
for _t, _n in [(P, "共享 prompt"), (V_PUSH, "推送 verify"), (V_REPORT, "报告 verify"), (SUFFIX, "报告后缀")]:
    assert "__DOCTRINE" not in _t, f"{_n} 残留教义哨兵（replace 未生效）"
assert o_prompts.ANNOTATION_SYSTEM_PROMPT.count("## 无方向：条件式与先A后B形态") == 1
print("[PASS] B3 同源：DOCTRINE_NO_DIRECTION/REVIEW 插值四处 + 哨兵零泄漏")

print("\n全部方向教义文本回归通过 ✅")
