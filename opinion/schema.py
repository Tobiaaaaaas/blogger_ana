# -*- coding: utf-8 -*-
"""规范标注行 schema + spec↔horizon↔层 映射（中心件）。

模型对一条帖子的每条**明确方向预测**产出一行（JSON 键 rows）。行内双字段承载两场景语义：
- spec    = 报告计分精确档（与打分引擎 run_direction / SKILL §3 同源：
            today|t1|t2|tN|week|nweek|nweek_first|month|nmonth|d:YYYY-MM-DD|long；
            cat=scored 参与计分，spec=long / unscored 单列不计分）
- horizon = 推送展示词（今天/明天/近日/本周/下周/更长/未提；卡面展示与锚定用）

**模型不写任何时间/身份字段**（pub/quote_ts/blogger/post_id 由系统按 post 回填）——避免模型
誊写时间/名字出错（坑：quote_post_n 越界、时间词错位）。模型同填 spec+horizon 并自检一致；
确定性坍缩(annotate.collapse_board)按 horizon 判层、按 spec 校验，冲突弃行并 log（不静默）。
horizon 留空串 = 该行只进报告、不上推送卡面（如"大趋势向上"被报告按 t5 计分、推送不展示——
双字段天然承载两 prompt 对模糊周期句的分歧，见重构记录）。

完整规范行（系统端）：{"blogger","post_n","post_id","pub","quote_ts","d","s","idx",
"spec","cat","horizon","quote","summary"}；模型端只需
{"post_n","d","s","idx","spec","cat","horizon","quote","summary"}。
"""
import calendar
import re

# ── 合法集（run_direction 直接消费，非法值会致引擎崩溃——与旧 extract 常量同源）──
VALID_IDX = {"上证指数", "上证50", "沪深300", "中证500", "中证1000", "创业板指", "科创50", "双创"}
IDX_ALIAS = {"上证综指": "上证指数", "上证": "上证指数", "综指": "上证指数"}
VALID_CAT = {"scored", "unscored"}
SPEC_RE = re.compile(r"^(today|week|nweek|nweek_first|month|nmonth|long|t\d+|d:\d{4}-\d{2}-\d{2})$")

# 无观点帖到案理由（2026-09-08 解析加固：逐帖契约——每条帖要么出 rows 要么进 no_view，
# 不许跳读；理由类别限本枚举，让人眼可审计"这帖为何不出观点"）
NO_VIEW_REASONS = ("复盘回顾", "状态描述", "转述他人", "仓位或理念",
                   "无明确方向", "仅他指或板块非大盘", "无实质内容")

_SPEC_T_NUM = re.compile(r"^t(\d+)$")
_SPEC_D = re.compile(r"^d:(\d{4})-(\d{2})-(\d{2})$")


def spec_sane(spec):
    """spec 语义域校验（在 SPEC_RE 语法之上）：tN 须 1≤N≤30（t0/t99 出域）；
    d:YYYY-MM-DD 须真实历法日期（月份 01-12、日按大小月/闰年）。today/week/.../long 语法即域内。

    2026-09-08 解析加固：SPEC_RE 只查形状，t0/t99/d:2026-13-99 之类"自洽但荒谬"此前静默入库。
    """
    if not isinstance(spec, str) or not SPEC_RE.match(spec):
        return False
    m = _SPEC_T_NUM.match(spec)
    if m:
        return 1 <= int(m.group(1)) <= 30
    m = _SPEC_D.match(spec)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not 1 <= mo <= 12:
            return False
        return 1 <= d <= calendar.monthrange(y, mo)[1]
    return True  # today/week/nweek/nweek_first/month/nmonth/long 等具名词汇


PANEL_KEYS = ("short", "swing")

# 各层 horizon 白名单（坍缩按词判层，取代 v16 LAYER prompt 的 LLM 判层散文）
PANEL_HORIZONS = {
    "short": ("今天", "明天"),
    "swing": ("近日", "本周", "下周", "更长", "未提"),
}
HORIZON_LAYER = {h: k for k, hs in PANEL_HORIZONS.items() for h in hs}

# 同层内"目标日更近优先"（用户 2026-09-08 定案）：坍缩同帖同层多行时取 rank 更小者
HORIZON_RANK = {"今天": 0, "明天": 1, "近日": 0, "本周": 1, "下周": 2, "更长": 3, "未提": 4}

_T_NUM_RE = re.compile(r"^t(\d+)$")


def _t_num(spec):
    """tN → N；非 tN 返回 None。"""
    if not isinstance(spec, str):
        return None
    m = _T_NUM_RE.match(spec)
    return int(m.group(1)) if m else None


def horizon_spec_ok(horizon, spec):
    """horizon 与 spec 是否同档自洽（坍缩校验用：不一致 → 弃行并 log，不静默）。

    horizon 是判层/展示权威，spec 是计分权威；两者冲突说明模型该行自检失败，弃行比硬塞安全。
    允许集从旧两 prompt 的映射表镜像：今天↔today、明天↔t1、本周↔week、下周↔nweek(下周一)、
    近日↔后天~未来几天(t2~t6，含"近期/马上"t5 宽口径)、更长↔月底前/下月/d:/较长 N 天后、
    未提↔无日历词但落当前波段(t4/t5 模糊档)。
    """
    if horizon == "今天":
        return spec == "today"
    if horizon == "明天":
        return spec == "t1"
    if horizon == "本周":
        return spec == "week"
    if horizon == "下周":
        return spec in ("nweek", "nweek_first")
    if horizon == "近日":
        n = _t_num(spec)
        return n is not None and 2 <= n <= 6
    if horizon == "更长":
        if spec in ("month", "nmonth") or (isinstance(spec, str) and spec.startswith("d:")):
            return True
        n = _t_num(spec)
        return n is not None and n >= 7
    if horizon == "未提":
        return spec in ("t4", "t5")
    return False


def default_horizon(spec, cat="scored"):
    """spec → 默认展示词（模型漏填 horizon 时的系统兜底；仅无歧义档兜底）。

    2026-09-09 A4-2：t5 兜底改「未提」——t5=近期/短期/无周期方向（"最近涨差不多减仓"类裸操作
    帖无日历词），落当前波段即 horizon=未提（horizon_spec_ok(未提,t5)=True、PANEL_HORIZONS swing
    白名单含未提），此前留空串被 collapse 静默弃行 → 无周期有方向的波段行不上卡。t6 无对应单值
    档（可能"大趋势向上"只进报告）留空串，宁可不上卡也不误显；long/unscored 无展示词。
    仅当模型评分行 horizon 为空才调用。
    """
    if cat != "scored" or spec == "long":
        return ""
    if spec == "today":
        return "今天"
    if spec == "t1":
        return "明天"
    if spec == "week":
        return "本周"
    if spec in ("nweek", "nweek_first"):
        return "下周"
    if spec in ("month", "nmonth"):
        return "更长"
    if isinstance(spec, str) and spec.startswith("d:"):
        return "更长"
    n = _t_num(spec)
    if n is not None and n >= 7:
        return "更长"
    if n is not None and 2 <= n <= 4:
        return "近日"
    if n == 5:
        return "未提"
    return ""


def disposition_errors(row_post_ns, no_view, n_posts):
    """逐帖到案校验（2026-09-08 解析加固：过程考虑充分——每条帖必须被交代去向）。

    row_post_ns: 模型 rows 里各条的 post_n（int 或数字字符串均可）；no_view: 模型 no_view
    列表 [{post_n, reason}]。返回错误文本列表（空 = 每条帖都已到案且不重叠）。缺到案 /
    rows∩no_view 重叠 / 理由不在 NO_VIEW_REASONS 枚举 → 各记一条。
    """
    def _pi(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    errors = []
    rset, nvset = set(), set()
    for v in row_post_ns:
        p = _pi(v)
        if p is not None and 0 <= p < n_posts:
            rset.add(p)
    seen_nv = set()
    for e in no_view or []:
        if not isinstance(e, dict):
            continue
        p = _pi(e.get("post_n"))
        if p is None or not (0 <= p < n_posts):
            errors.append(f"no_view 含非法 post_n：{e.get('post_n')!r}")
            continue
        if p in seen_nv:
            errors.append(f"帖子 {p} 在 no_view 重复到案")
            continue
        seen_nv.add(p)
        nvset.add(p)
        reason = str(e.get("reason") or "").strip()
        if reason not in NO_VIEW_REASONS:
            errors.append(f"帖子 {p} 的 no_view 理由不在枚举内：{reason!r}")
    overlap = rset & nvset
    if overlap:
        errors.append(f"帖子 {sorted(overlap)} 在 rows 与 no_view 重叠到案（结构错）")
    missing = [i for i in range(n_posts) if i not in (rset | nvset)]
    if missing:
        errors.append(f"帖子 {missing} 未到案（既不在 rows 也不在 no_view），须逐条交代")
    return errors
