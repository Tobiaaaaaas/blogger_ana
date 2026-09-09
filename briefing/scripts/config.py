# -*- coding: utf-8 -*-
"""简报系统配置：双板块名单、板块口径、盘中 30 分网格、双 webhook、窗口常量。

v14（2026-09-04）：展示窗口由自然日改为**交易日口径**（用户修正）——窗口起点 = 前一/前N个
交易日 00:00（calendar.n_trading_days_ago），周一早晨天然含上周五帖（消除 v13 自然日取舍）。
v15（2026-09-07）：推送节奏**两板块统一**（用户指示）：
  - 超短板块（21，2026-09-07 换名单）：扫 WINDOW_TRADING_DAYS["short"]=1 → 前一交易日 00:00
    起至现在的 今天/明天 表态，只显示 目标日∈{卡片日,下一交易日} 者。
  - 波段板块（30）：扫 WINDOW_TRADING_DAYS["swing"]=5 → 前 5 个交易日 00:00 起至现在的
    帖子内的**可计分**波段表态（近日/本周/下周/更长/未提；口径同打分引擎——年度/跨年/超远期、
    中长期/长期趋势断言、无时间承诺点位等 spec=long/unscored 不计分观点直接判无表态，见
    summarize_board 单板块口径），本周/下周 锚定发帖日所在周一~五周、目标周已过剔除；
    无明确周期的表态（近日/更长/未提）如实标注、不编造目标日期。
  - 交易日**两板块同节奏**：09:00–15:00 每 30 分钟（含午休与盘前，13 档）+ 16:00–22:00
    每整点（7 档）→ 每档两卡都推；**非交易日只推波段**：09:00–21:00 每 3 小时
    （09/12/15/18/21 五档）。卡标题中性「板块+时刻」（config.in_trading_grid/in_restday_grid）。
  - 两板块各自一张卡、各自收敛总结，各推各的飞书群（WEBHOOK_ENV）。
名单口径：
  - 超短板块（21，2026-09-07 更新）：超短档（0-1 交易日）质量筛选——胜率>50% 且 平均分>0.1 且
    n≥10（打分链 = scripts/eval/run_direction.calc 同源，数据截止 2026-09-05），按平均分降序即
    展示顺序。旧 17 人名单（reports/top20_值得关注博主.md 超短榜）已注释保留在 PANEL_SHORT 下
    方，备日后参考。
  - 波段板块（30，2026-09-06 更新，未变）：波段档（信号日→验证终点≥2 交易日）三条件全严格达标者
    28 人（均分>0.2 且 夏普>0.1 且 胜率>50%，数据截止 2026-09-04）按均分降序 + 原委员会保留
    刘海娃娃/顺应周期 殿后；剔除 红红火火的老牛哥、微风3241。完整筛选口径见
    reports/comparison_direction.md 与当期《波段达标名单》。顺序即板块内展示顺序。
"""
from datetime import datetime

# ── 超短板块（21）：只看 今天/明天 方向观点 ──
# 旧名单（17 人 · reports/top20_值得关注博主.md 超短榜 · 2026-09-07 下线，注释保留备查）：
#   "云帆观市", "红红火火的老牛哥", "白猫财眼", "大盘蜂向标", "一只小小牛",
#   "孙万林", "顺应周期", "山顶望星空的诗人",
#   "入竹风拂面画船听雨眠", "大白白", "龙五", "三粒光", "麟老哥",
#   "波段研究师", "纽约音乐厨房", "股傲", "要有心态",
PANEL_SHORT = [
    "星哥投研", "大白白", "故乡的云ZYH", "入竹风拂面画船听雨眠", "道术合一",
    "股往金来oo", "云帆观市", "龙五", "钱眼", "红红火火的老牛哥",
    "股指看盘", "三粒光", "麟老哥", "波段研究师", "期指作手",
    "纽约音乐厨房", "A股老黎实战操盘手", "要有心态", "博股思金", "股傲",
    "子房论市",
]

# ── 波段板块（30）：只看 波段(近日/本周/下周/更长) 方向观点 ──
PANEL_SWING = [
    "一只小小牛", "股往金来oo", "家有高中生2", "故乡的云ZYH", "子房论市",
    "选对时机买对股", "香满衣", "知行合一", "智由智哉", "股评老陈",
    "云帆观市", "赵红力", "趋势巡航", "孙万林", "大盘蜂向标",
    "谭阿坤", "白猫财眼", "禅壹", "爱生活的荷叶Rp", "时间轨迹",
    "四十二流光", "我觉醒了", "中国技术玩家", "山顶望星空的诗人", "衡山佛曰论股",
    "诸葛不亮", "江河之水终有入海之日", "时空鹰眼", "刘海娃娃", "顺应周期",
]

PANEL_KEYS = ("short", "swing")
PANELS = {"short": PANEL_SHORT, "swing": PANEL_SWING}
BOARD_WORD = {"short": "超短", "swing": "波段"}  # 卡标题用词（区别于 label 里的括号周期说明）

# 板块展示元信息（标题/emoji/空板块提示；v14 空板文案随交易日窗口口径）
BOARD_META = {
    "short": {"label": "超短(0-1日)", "emoji": "⏱️",
              "empty_note": "（前一交易日起的表态无指向今/下一交易日的超短方向）"},
    "swing": {"label": "波段(2日+)", "emoji": "🌊",
              "empty_note": "（前5个交易日起无人给出波段方向观点）"},
}

# 抓取/读帖全集：两板块去重（超短板块原序 + 波段板块新增第 9 位起）
ALL_BLOGGERS = PANEL_SHORT + [b for b in PANEL_SWING if b not in PANEL_SHORT]

# ── 展示窗口（v14 交易日口径；v15 波段 3→5）：交易日回看天数 → 窗口起点 = 前一/前N个交易日 00:00 ──
# 窗口内容面 = 前 N 个交易日的全天帖 + 今日盘中至 now；now 非交易日按最近交易日取参考日。
# 由此周一早晨的窗口天然含上周五帖（消除 v13 自然日口径的"周一漏上周五帖"取舍）。
WINDOW_TRADING_DAYS = {"short": 1, "swing": 5}

# ── 推送节奏（v15 统一，取代 v13 超短 30 分网格 + 波段 SWING_TICKS 三档的不对称）──
# 交易日两板块同节奏 20 档：09:00–15:00 每 30 分钟（含午休 12:00/12:30 与 09:00 盘前，13 档）
#   + 16:00–22:00 每整点（7 档）；非交易日只推波段 5 档：09:00–21:00 每 3 小时（09/12/15/18/21）。
# 命中判定见 in_trading_grid / in_restday_grid（:00/:30 算术，不另设 tick 常量）。

# ── 双 webhook（v13）：各板块推各群的飞书机器人 ──
WEBHOOK_ENV = {"short": "FEISHU_WEBHOOK_URL",     # 旧群（原综合卡群 → 现收超短卡）
               "swing": "FEISHU_WEBHOOK_URL_SWING"}  # 新群（波段卡）

# ── 行抽取常量 ──
ROWS_MAX_POSTS = 8              # 每博主喂给 LLM 的窗口内帖子上限（最新 N 条，新→旧）
ROWS_BATCH_BLOGGERS = 2         # summarize 每次 DeepSeek 调用放进几位博主
ROWS_WORKERS = 3                # 行抽取并行线程数


def in_trading_grid(dt: datetime) -> bool:
    """交易日节奏命中：09:00–15:00 的 :00/:30（含午休与盘前），或 16:00–22:00 的整点 :00。

    用于调度挡板：墙钟/StartWhenAvailable 唤醒不在节奏上（含伪 tick 如 15:30/22:30）
    都在抓取/锁之前由此 exit 0（本函数不自行 exit，交给调用方判断）。
    """
    if dt.minute not in (0, 30):
        return False
    m = dt.hour * 60 + dt.minute
    if 540 <= m <= 900:                      # 09:00–15:00（:00/:30 全覆盖）
        return True
    return dt.minute == 0 and 960 <= m <= 1320   # 16:00–22:00 整点 :00


def in_restday_grid(dt: datetime) -> bool:
    """非交易日节奏命中：09:00–21:00 每 3 小时（:00，即 09/12/15/18/21）。"""
    return dt.minute == 0 and dt.hour in (9, 12, 15, 18, 21)


def due_boards(trading: bool) -> list:
    """应推板块：交易日两板块同节奏（每档 short+swing）；非交易日只推波段。"""
    return ["short", "swing"] if trading else ["swing"]


def board_title(board_key: str, date_str: str, hm: str) -> str:
    """单板块卡标题（v15 中性：板块 + 时刻）。如 '📊 超短 10:00 · 09-03 周四' /
    '📊 波段 14:30 · 09-03 周四'。hm = 'HH:MM'。"""
    return f"📊 {BOARD_WORD[board_key]} {hm} · {date_str}"


def format_board_count(board_key: str, c: dict) -> str:
    """单板块计数行（v13 全链路唯一文案源之一）：板块头行见 render._board_section_lines。

    c 形如 {bull,bear,shown,members}（summarize.board_counts 单板块子集）。
    例：'⏱️ 超短(0-1日) 3多/2空（5/21 表态）'
    """
    meta = BOARD_META[board_key]
    return (f"{meta['emoji']} {meta['label']} "
            f"{c.get('bull', 0)}多/{c.get('bear', 0)}空"
            f"（{c.get('shown', 0)}/{c.get('members', 0)} 表态）")


