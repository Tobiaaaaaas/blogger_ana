# -*- coding: utf-8 -*-
"""简报生成：DeepSeek 抽取与收敛。

DeepSeek 调用底座（call_json / parse_response / watchdog 硬超时）2026-09-08 起委派顶层
opinion/ds——推送、报告、画像三场景同源（撤除对父脚本 extract_signals_direction.py 的
importlib file-load，_extract 已删）。分层判定由 LAYER prompt 散文迁进 opinion：单一共享逐帖
标注出规范行（rows）+ collapse_board 确定性坍缩（见 v17 节，extract_layers 签名不变）。

v13（2026-09-03 redesign：超短/波段拆两群两卡 + 盘中 30 分档）→ v14（2026-09-04 交易日窗口）→
v15（波段窗口 3→5 交易日）→ **v16（2026-09-08 分层分解单趟化，对齐 analyze-blogger skill §3 spec 口径）**：
  1. extract_layers(work, starts)：一位博主一窗帖**一次 DeepSeek 调用**，模型先按每条方向
     预测的**预测周期**（skill §3 spec 语义，非关键词）判层——周期=今天/明天 → 超短层、
     =2日+ 可计分波段周期（后天/未来几天/本周/下周/月底前/下月/具体日期…）→ 波段层、
     年度/远期/中长期/无时间承诺点位（spec=long/unscored 不计分）→ 丢弃。
     **预测周期只到 明天 的判断永不成波段**（口径同波段委员会 spec≠today/t1，卡 label
     波段(2日+)），根治 2026-09-08 子房论市"明天帖被 LLM 归成波段·近日"的误归。
     同一帖可同时产超短+波段两行，quote/summary 各引各层原句；混合帖/转述由 LLM 语义
     分解归位，不设内容正则闸门。带 rows_cache v3 增量：窗口帖集合（含正文指纹）未变
     且各所属层行未过期 → 跳过 DeepSeek 复用缓存行（row=None 也缓存省档）。
  2. resolve_anchors：按引文发帖日锚定绝对目标（超短剔已过/未指今明，波段剔目标周已过）。
  3. board_counts：单板块多空计数。
  4. summarize_board(board_key, …)：单板块快照 + 本板块计数 → 一段本板块收敛总结。
  rows_cache v2→v3：{"boards":{board:{博主:{row}}} → {"bloggers":{博主:{posts:[指纹],
     short:row|null, swing:row|null}}}；博主某所属层行过期 → 整博主同趟重抽（保口径一致）。
**v17（2026-09-08 共享模块委派）**：LAYER_SYSTEM_PROMPT / _row_from_layer / _fmt_window_posts
  / cache v3 移除——判层收敛为 opinion 单一共享逐帖标注（ANNOTATION_SYSTEM_PROMPT，输出 rows
  规范行：每帖每条方向预测一行，spec+horizon 双字段）+ opinion.annotate.collapse_board 确定性
  坍缩（窗口下界门 / 路过不抹旧行 / 层白名单 / spec↔horizon 自洽全部代码化）；rows_cache v4
  改存整博主规范行（opinion.cache）。extract_layers 签名与下游行形状不变，run_briefing 调用点不动。
**v18（2026-09-08 逐帖缓存）**：rows_cache v4（整博主规范行 + 窗口帖集合指纹：集合任一变化 →
  整博主含旧帖全量重抽）→ v5 **逐帖**——每帖按 (post_id, 内容hash) 键存各自规范行，每档只把
  窗口里新出现/正文回填变 content 的帖送一次标注（该博主新帖合成一个子批调用），旧帖（含跨
  交易日窗口滑动重叠帖）永不重评分；坍缩每档确定性重算、只取本次窗口帖的行。
**v19（2026-09-09 交易日相对再分类）**：v16"字面 今天/明天 永不成波段"只拦自然历法同词；
  周五~周日发帖的"下周一/下周首个交易日"（spec=nweek_first）实指**下一交易日**（预测周期=1）
  却带 swing 词下周 → 曾漏进波段卡（孙万林 09-04 案例）。extract_layers 现向 collapse_board
  传 cal=calendar，行归属板别由 _row_layer 按 horizon 词 + spec 单日钉解出的首个目标交易日
  判定：目标 == 发帖后首个交易日 → 降级超短；nweek（整周）观点不降级。行缓存/标注不变。
  **v20（2026-09-09 主结论对象门：纠错重抽而非弃推）**：衡山/诸葛复盘确认"idx=上证 但摘要/
  引文点名他指且无上证指向"的自相矛盾行是**标注指错**，不是该帖无观点——直接弃推会把两类失败
  混为一谈（idx 标错 / 摘要漏选帖内真实存在的上证观点）。恢复分三层：annotate_blogger 拒收矛盾
  行入缓存 + 带方向纠错重试（有上证观点 → 重选上证句；只谈他指 → idx 改真实指数）；extract_layers
  对本文件 v20 上线前已缓存进 rows_cache 的矛盾旧帖**作废整帖重抽**（自愈，见 extract_layers）；
  collapse_board 只留**渲染底限**——矛盾行永不上上证卡，但不越权修复（坍缩无帖子全文）。
v12 跨板块 summarize_boards / SUMMARY_SYSTEM_PROMPT 保留作 LEGACY（不再接线，供历史复刻）。
旧 v8 全板共识路径（POINTS_SYSTEM_PROMPT / SYNTH_SYSTEM_PROMPT / extract_points / synthesize）
亦 LEGACY；v9/v10 的 18 行名单路径已整段替换。
"""
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import calendar, config, paths

# 2026-09-08 共享模块重构：判层 prompt 收敛为 opinion 单一共享逐帖标注（ANNOTATION_SYSTEM_PROMPT），
# 读帖/清洗/DeepSeek 网关/标注缓存一并委派顶层 opinion/ 包（推送、报告、画像三场景同源）。
# briefing 是独立部署单元，兜底把父仓根（paths.REPO_ROOT）补进 sys.path 以便 `import opinion`。
try:
    from opinion import annotate as o_ann, cache as o_cache, ds as o_ds  # noqa: E402
    from opinion import prompts as o_prompts, schema as o_schema, text as o_text  # noqa: E402
    from opinion import verify as o_verify  # noqa: E402
except ImportError:
    if not any(os.path.abspath(p) == os.path.abspath(paths.REPO_ROOT) for p in sys.path):
        sys.path.insert(0, paths.REPO_ROOT)
    from opinion import annotate as o_ann, cache as o_cache, ds as o_ds  # noqa: E402
    from opinion import prompts as o_prompts, schema as o_schema, text as o_text  # noqa: E402
    from opinion import verify as o_verify  # noqa: E402

log = logging.getLogger("briefing")

MAX_POST_CHARS = 1200   # 单帖正文截断长度（足够承载一篇观点帖）
POINTS_BATCH = 8        # 抽点每批帖子数（LEGACY）
SYNTH_MAX_ATTEMPTS = 3  # 综合最大尝试次数（LEGACY）

ROW_MAX_ATTEMPTS = 3     # 行抽取 / 收敛总结最大尝试次数
BEIJING = timezone(timedelta(hours=8))

# 各层 horizon 展示/锚定词白名单：2026-09-08 收敛到 opinion.schema.PANEL_HORIZONS（与报告同源）。
# swing 的 更长/未提 只代表"可计分的近月窗口/当前波段阶段"；年度/跨年/超远期、中长期/长期
# 趋势断言、无时间承诺点位等 spec=long/unscored 不计分观点由共享 prompt 判 spec=long 不计分、
# 推送坍缩不落板（口径同打分引擎 / Swing_Timing spec≠today/t1）。
PANEL_HORIZONS = o_schema.PANEL_HORIZONS

# DeepSeek 网关单一共享（opinion.ds.call_json）；2026-09-08 撤除对父脚本 extract_signals_direction.py
# 的 importlib file-load（_extract）——模块无缓存复用、sys.modules 键名易冲突的坑一并消除。
call_json = o_ds.call_json


# ── LEGACY（v8 全板共识卡；2026-09 redesign 后不再被 run_briefing 调用，仅保留供历史复刻/回退）──
POINTS_SYSTEM_PROMPT = """你是财经自媒体内容分析助手。你会收到一批今日头条财经博主的帖子（每条含博主名、标题、正文），请逐条判断博主是否对大A大盘给出了**明确的方向观点**。

明确的观点指对未来的方向判断：看涨/看跌、收阳/收阴、点位目标、支撑/压力突破判断、明确条件后的方向倾向，且对象是上证指数/大盘/主要指数（不含具体个股、与大盘无关的板块行情）。
判断要点：
- 明确未来方向才算观点；只描述现状（"今天缩量震荡""进入调整期"）、复盘已发生行情、仓位自述、理念分享、新闻评论 → stance=中性。
- 带条件的方向判断（"站稳X才能看多""回踩X是机会"）按条件倾向判多/空，quote 引原句。
- 情绪极端词（"史诗级""崩盘""必涨""满仓""清仓"）→ extreme=true。
- 一条帖多个观点时，只记最明确的那个方向态度。
- 没有观点 → stance=中性，summary 留空字符串。

输出严格 JSON（points 数组长度必须等于输入帖子数，顺序一一对应）：
{"points": [{"post_n": 0, "blogger": "博主名", "stance": "多|空|中性", "strength": "强|中|弱", "horizon": "今天|明天|近日|本周|下周|更长|无周期|未提", "quote": "关键原文一句(≤40字，无观点留空)", "extreme": false, "summary": "一句话概括(≤30字，中性则留空)"}, ...]}
只输出 JSON，无其他文字。"""


SYNTH_SYSTEM_PROMPT = """你是股票市场观点综合分析助手。输入包含：
1) 当前时段与日期
2) 大盘行情（实时/最近收盘）
3) **上期板况**（【较上期】块：上期/本期多空计数与本期观点翻转名单——仅供共识开头一句"较上期"对比；**严禁照抄或复述**）
4) **博主画像**：部分博主的画像档案（**风格特征**与主攻周期；不含准确率/得分等量化指标）
5) **本期更新观点博主**：本次推送窗口内发过新帖、观点发生更新的博主名单
6) **全板近期观点**：所有追踪博主的当前近期观点（每人一条：立场/强度/周期/引文/发帖时间）

核心概念——全板观点模型：每个博主维护一个"近期观点"（其最新一篇有观点帖的立场），博主发新帖则其近期观点更新；没发新帖的博主，其近期观点保持不变。**全板** = 所有追踪博主近期观点的集合。统计与综合必须基于**全板**，而不是只看本期新帖。发帖超过 7 天的观点视为过时（该博主退出统计，只看时效内观点）。

任务：把**全板近期观点**综合成一份**全板简报**。读者要能一眼看出"现在全板观点版图如何、相对上期哪些博主变了、**我该关注什么**"。硬性要求：

【时间】
- 每条观点带发帖时间（输入已给），共识里点明本期时间背景（时段/窗口），不要脱离时间泛泛而谈。
- 只在时效内（发帖≤7 天）的观点上做统计与判断；过时博主的观点不出现、不参与。

【共识】（全板态势，重中之重）
- consensus.summary：**丰富的一段全板共识分析**（4~7 句，写成流畅段落，不要只给结论）。开头第一句按【本轮性质】二选一：
  · **首期** → 固定写"较上期：首期无基准"。
  · **增量** → 用【较上期】给的上期/本期多空与翻转名单写**一句真实对比**（如"较上期：全板偏空、空头占优；本期延续偏空，仅个别人转多"），一句话即可，不展开。
  之后正文只分析**本期**全板：① 本期时间背景（时段/窗口与行情状态）；② 多空力量对比与占优方；③ **本期更新观点的博主**带来的变化（点名谁新发观点、方向如何、代表观点——点名**只能出自【本期更新观点博主】名单**）；④ 中性观望者的态度；⑤ 整体风险偏好。
  **硬性要求：正文是本期全板的原创分析，必须基于【全板近期观点】与【本期更新观点博主】；严禁复述、转抄或沿用【较上期】/【上期板况】/上期卡片中的措辞、点名与引文。若本期结论与上期相近，用"较上期延续偏空"一笔带过，其余篇幅仍写本期。**
- 多空统计由系统按全板计算，**你不需要也不能输出数字**——只描述态势与演变。

【本期要点】（收尾总结，把整板凝结成读者该关注的若干点）
- takeaways 数组 **3~5 条**（通常 4 条），每条**一句总结句**（≤35字，完整成句、可独立读），像"全板偏空，空头占优，短期以防守为主"这样的收束句。**不拆分主题/说明/行动**，不堆博主名与风格后缀，可点名个别关键博主但以观点概括为主。
- 必须综合全板提炼，覆盖：整体共识结论（含短期操作取向）、最关键的多空对立、最重要的变化（谁转多转空）、明日/短期最关键的触发点或点位、最需警惕的风险。

【分歧】
- 分歧：全板观点冲突或逻辑矛盾，写成简短条目（可含本期更新观点的博主）。

【风险】
- 风险：全板极端预测、情绪化表态、与共识背离的强观点，标注博主与其风格画像备注。

【其他】
- 中性观点（当前无明确方向）计入全板活动但不算入多空力量。
- 不输出重点博主（重点博主由系统按总榜排名自动选取 Top 5），也不输出多空数字。

输出严格 JSON（divergences/risks 可为空数组，takeaways 至少 3 条）：
{
  "consensus": {"stance": "偏多|偏空|均衡|未明", "summary": "丰富全板共识段落(4~7句；首期开头写'较上期：首期无基准'，增量以'较上期'真实对比)"},
  "divergences": ["分歧1", "分歧2"],
  "risks": [{"blogger": "...", "desc": "风险观点", "note": "画像备注(风格)"}],
  "takeaways": ["总结句1(≤35字)", "总结句2", "总结句3", "总结句4"]
}
- 只输出 JSON，无其他文字"""


def _fmt_post(blogger, p):
    content = (p.get("content") or "").strip()
    if len(content) > MAX_POST_CHARS:
        content = content[:MAX_POST_CHARS] + "…（已截断）"
    title = p.get("title") or ""
    header = f"【博主】{blogger}\n"
    if title:
        header += f"【标题】{title}\n"
    header += f"【正文】{content}"
    return header


def extract_points(blogger_posts, batch_size=POINTS_BATCH):
    """blogger_posts: [(blogger, post), ...] → 返回 ({post_n: point}, activity_counts)。

    跳过视频帖（无文字正文）。抽点调用 DeepSeek，失败批次重试后仍失败的帖子记中性。
    """
    clean = []
    for blogger, p in blogger_posts:
        content = (p.get("content") or "").strip()
        if content == "[视频帖]" or len(content) < 5:
            continue
        clean.append((blogger, p))

    points = {}
    no_view = 0
    for i in range(0, len(clean), batch_size):
        chunk = clean[i:i + batch_size]
        user_msg = "\n\n----\n\n".join(
            f"[{j}] " + _fmt_post(b, p) for j, (b, p) in enumerate(chunk))
        result, raw = call_json(None, POINTS_SYSTEM_PROMPT, user_msg, "briefing:points")
        if result is None:
            log.warning("  抽点批次失败（%d 帖），按中性处理", len(chunk))
            for j, (b, p) in enumerate(chunk):
                # 全局索引 i+j，避免后一批覆盖前一批（2026-09-02 修复批覆盖 bug）
                points[i + j] = {"post_n": i + j, "blogger": b, "stance": "中性",
                                 "strength": "弱", "horizon": "未提", "quote": "",
                                 "extreme": False, "summary": "",
                                 "pub_ts": p.get("publish_time")}
                no_view += 1
            continue
        pts = result.get("points") or []
        for j, (b, p) in enumerate(chunk):
            d = pts[j] if j < len(pts) and isinstance(pts[j], dict) else {}
            stance = d.get("stance")
            if stance not in ("多", "空", "中性"):
                stance = "中性"
            if stance == "中性":
                no_view += 1
            # 全局索引 i+j，避免后一批覆盖前一批（2026-09-02 修复批覆盖 bug）
            # pub_ts：来源帖发布时间，全板模型用它取"每博主最新帖立场"并做 7 天时效过滤
            points[i + j] = {
                "post_n": i + j, "blogger": b, "stance": stance,
                "strength": d.get("strength") or "中",
                "horizon": d.get("horizon") or "未提",
                "quote": (d.get("quote") or "").strip()[:40],
                "extreme": bool(d.get("extreme")),
                "summary": (d.get("summary") or "").strip()[:30],
                "pub_ts": p.get("publish_time"),
            }
    return points, no_view


def _board_txt(board):
    """全板近期观点 → prompt 文本（按博主名排序；每条带发帖时间，供综合的时间锚点）。"""
    if not board:
        return "（暂无时效内观点）"
    lines = []
    for name in sorted(board):
        e = board[name]
        ts = e.get("pub_ts")
        t = ""
        if ts:
            from datetime import datetime, timezone, timedelta
            dt = datetime.fromtimestamp(int(ts), tz=timezone(timedelta(hours=8)))
            t = dt.strftime("%m-%d %H:%M")
        strength = "·强" if e.get("strength") == "强" else ""
        horizon = e.get("horizon") or "未提"
        desc = e.get("quote") or e.get("summary") or ""
        lines.append(f"▍{name}（发帖 {t}）")
        lines.append(f"  - {e['stance']}{strength}·{horizon}｜“{desc}”")
    return "\n".join(lines)


def _build_profile_subset(profiles, bloggers):
    """只取出本期发帖博主的画像片段，供综合 prompt 注入。

    只给风格特征与主攻周期（报告不展示准确率/得分等量化指标）。
    """
    out = []
    for b in bloggers:
        pf = (profiles or {}).get(b)
        if not pf:
            continue
        bits = [f"{b}: 主攻{pf.get('horizon')}"]
        if pf.get("style"):
            bits.append(f"风格：{pf['style']}")
        out.append("；".join(bits))
    return "\n".join(out) if out else "（本期博主无画像档案）"


def _normalize_synth_result(result):
    """模型偶发把 consensus 拍平到顶层（顶层就是 {stance, summary, evolution}，无 consensus 键）。

    包回标准结构；其余段若也在顶层则原样保留。
    """
    if isinstance(result, dict) and not isinstance(result.get("consensus"), dict) and "stance" in result:
        flat = result
        result = {
            "consensus": {"stance": flat.get("stance"), "summary": flat.get("summary"),
                          "evolution": flat.get("evolution")},
            "divergences": flat.get("divergences") or [],
            "risks": flat.get("risks") or [],
            "takeaways": flat.get("takeaways") or flat.get("focus") or [],
        }
    return result


def _synth_result_ok(card):
    """完整性检查：consensus 合法（dict + 合法 stance + summary），且除 consensus 外至少有一段实质内容。

    拍平到顶层 / 只有半截 consensus / 空 JSON 都会在此被拒，触发综合重试。
    """
    c = card.get("consensus")
    if not isinstance(c, dict):
        return False
    if c.get("stance") not in ("偏多", "偏空", "均衡", "未明") or not c.get("summary"):
        return False
    return bool(card.get("takeaways") or card.get("focus") or card.get("divergences") or card.get("risks"))


def _count_board(board):
    """全板多空计数（口径与 run_briefing._board_counts 一致，供【较上期】块现算）。"""
    bull = sum(1 for e in board.values() if e.get("stance") == "多")
    bear = sum(1 for e in board.values() if e.get("stance") == "空")
    neutral = sum(1 for e in board.values() if e.get("stance") == "中性")
    return bull, bear, neutral


def _nature_block(first_board):
    """本轮性质行：显式引导共识开头写法（首期 vs 增量），杜绝"首期无基准"被误带到增量档。"""
    if first_board:
        return "【本轮性质】首期建板：无上期基准，共识段落开头固定写\"较上期：首期无基准\"。"
    return "【本轮性质】增量更新：共识段落开头须用【较上期】真实对比上期结论，禁止写\"首期无基准\"。"


def _prev_block(board, board_prev, first_board):
    """【较上期】结构化块：只喂上期多空计数 + 本期全板计数 + 本期观点翻转名单。

    全部由账本（当前 board / 上期 board_prev 快照）现算，**不含任何上期散文**——模型无从照抄。
    board_prev 可能只有 counts（旧版迁移，无逐博主立场）→ 只给计数、无翻转名单。
    """
    if first_board:
        return "【较上期】（首期：无上期基准）"
    if not board_prev:
        return "【较上期】（无上期快照：勿编造上期数据；结论相近可用'延续上期'一笔带过）"
    date = board_prev.get("date") or ""
    slot = board_prev.get("slot") or ""
    when = f"{date} {slot}".strip() or "上期"
    views = board_prev.get("views") or {}
    if views:
        pb, pa, pn = _count_board(views)
        p_n = len(views)
    else:
        c = board_prev.get("counts") or {}
        pb, pa = int(c.get("bull") or 0), int(c.get("bear") or 0)
        pn = c.get("neutral")
        p_n = 0
    cb, ca, cn = _count_board(board)
    head = f"{pb}多/{pa}空"
    if pn is not None:
        head += f"/{pn}中性"
    if p_n:
        head += f"（{p_n} 位）"
    lines = [f"【较上期】上期（{when}）：{head}；本期全板：{cb}多/{ca}空/{cn}中性"]
    if views:
        flips = []
        for n, pe in views.items():
            ps = pe.get("stance")
            ce = board.get(n)
            cs = ce.get("stance") if ce else None
            if ps and cs and cs != ps:
                flips.append(f"{n}（{ps}→{cs}）")
        if flips:
            lines.append("本期观点翻转：" + "、".join(sorted(flips)))
        else:
            lines.append("本期观点翻转：无（更新博主维持原方向）")
    return "\n".join(lines)


def synthesize(board, updated, market_text, board_prev, profiles, slot_label, date_str,
               window_txt="", first_board=False):
    """全板综合 → 卡片 JSON。window_txt 描述本期窗口（如"自 12:52 以来 · 全板滚动更新"）。

    board:       全板近期观点 {博主: {stance, strength, horizon, quote, extreme, summary, pub_ts}}（已时效过滤）
    updated:     本期发新帖、观点更新的博主集合（首期 = 全板博主）
    board_prev:  上期推送时落盘的板况快照 {date, slot, views|counts}——只用于算"较上期"计数/翻转名单，
                 绝**不回灌上期散文**（2026-09-02 修：模型曾整段照抄上期卡片）。
    first_board: 首期建板（无上期基准，共识开头写"较上期：首期无基准"）。
    多空数字不在此定——由 run_briefing 按全板计数覆盖（全板口径，非本期增量）。
    """
    board_txt = _board_txt(board)
    updated_txt = "、".join(sorted(updated)) if updated else "（首期）"

    user_msg = f"""【时段】{date_str} {slot_label}（{window_txt or '本期'}）
【行情】{market_text}
{_nature_block(first_board)}
{_prev_block(board, board_prev, first_board)}
【博主画像】
{_build_profile_subset(profiles, sorted(board.keys()))}

【本期更新观点博主】{updated_txt}
【全板近期观点】（时效内 {len(board)} 位博主）
{board_txt}"""

    card = None
    for attempt in range(SYNTH_MAX_ATTEMPTS):
        result, raw = call_json(None, SYNTH_SYSTEM_PROMPT, user_msg, "briefing:synthesize", thinking=True)
        if result is None:
            if attempt < SYNTH_MAX_ATTEMPTS - 1:
                log.warning("综合调用无结果（attempt=%d），重试", attempt + 1)
                continue
            break
        norm = _normalize_synth_result(result)
        if _synth_result_ok(norm):
            card = norm
            break
        log.warning("综合输出不完整/格式异常（attempt=%d）：顶层 keys=%s，重试",
                    attempt + 1, list(result.keys()))
    if card is None:
        raise RuntimeError("综合调用多次失败或输出不完整，未能生成简报")
    card = _sanitize_card(card)
    return card, board_txt


def _sanitize_card(card):
    consensus = card.get("consensus") or {}
    stance = consensus.get("stance")
    if stance not in ("偏多", "偏空", "均衡", "未明"):
        stance = "未明"
    card["consensus"] = {
        "stance": stance,
        "bull": int(consensus.get("bull") or 0),
        "bear": int(consensus.get("bear") or 0),
        "neutral": int(consensus.get("neutral") or 0),
        "summary": (consensus.get("summary") or "").strip()[:400],
        "evolution": (consensus.get("evolution") or "").strip()[:120],
    }
    for key in ("divergences", "risks"):
        card[key] = [x for x in (card.get(key) or []) if isinstance(x, (str, dict))]
    card["takeaways"] = _norm_takeaways(card.get("takeaways") or card.get("focus") or [])
    card.pop("focus", None)  # 本期要点统一存 takeaways（旧 focus 结构在 _norm_takeaways 中压成一句）
    return card


def _norm_takeaways(items):
    """本期要点归一化为字符串数组（≤60字/条，最多 5 条）。兼容旧 {theme,detail,action} dict → 压成一句。"""
    out = []
    for x in items:
        if isinstance(x, dict):
            bits = [str(x.get("theme") or "").strip()]
            d = str(x.get("detail") or "").strip()
            a = str(x.get("action") or "").strip()
            if d:
                bits.append(d)
            text = "，".join(b for b in bits if b)
            if a and a not in text:
                text += f"；{a}"
        elif isinstance(x, str):
            text = x.strip()
        else:
            text = str(x).strip()
        if text:
            out.append(text[:60])
    return out[:5]


# =====================================================================
# v17（2026-09-08 共享模块委派）：判层从 LAYER prompt 散文迁进 opinion——单一共享逐帖标注
# ANNOTATION_SYSTEM_PROMPT（推送/报告同源）出**规范行**（每帖每条方向预测一行，spec+horizon
# 双字段、quote_ts/pub 由系统按帖回填），再由 opinion.annotate.collapse_board 确定性坍缩成
# 每博主每层最新表态：quote_ts≥该层窗口下界 门 + 该层 horizon 白名单 + spec↔horizon 自洽，
# 无观点帖只是路过、不抹旧行（子房/诸葛 12:00 类路过误判按规则意图纠正）。
# =====================================================================

# ── 行标注缓存（rows_cache.json v5，opinion.cache，逐帖粒度）──
# v4（整博主规范行 + 窗口帖集合指纹：集合任一变 → 整博主 ≤ROWS_MAX_POSTS 全量重抽，旧帖也
# 重评分）→ v5（逐帖）：每博主按帖键 (post_id, 内容hash) 存各自规范行，每档只把窗口内
# "新帖/正文回填变 content"的帖合并成一个子批送一次标注，旧帖（含跨交易日窗口滑动重叠帖）
# 永不重评分。坍缩仍每 tick 确定性重算：参与坍缩的行 = 仅本次窗口各帖缓存行并集，窗口滑动
# /行过期由 quote_ts≥该层窗口下界 门自动消化。版本或共享 prompt 指纹任一不符 → 整缓存作废
# 全量重抽（首档按博主新帖合批一次调用，量级同 v4）。
_ROWS_CACHE_VERSION = 5


def _annotate_rows(name, posts):
    """一位博主窗口帖 → 规范行（共享 ANNOTATION prompt）。None = 调用失败/结构异常（不缓存）。

    annotate_blogger 内部走 opinion.ds（3 次重试 + 硬超时）；外层 ROW_MAX_ATTEMPTS 兜底 JSON
    反复解析失败的偶发（与 v16 _call_group 同量级最坏 3×3）。失败 → None → 记 errors 下档重试。
    """
    for _attempt in range(ROW_MAX_ATTEMPTS):
        try:
            rows, _raw = o_ann.annotate_blogger(name, posts, label=f"briefing:layers:{name}")
        except Exception as e:
            log.warning("  %s 标注调用异常（attempt=%d）：%s", name, _attempt + 1, e)
            continue
        if rows is not None:
            return rows
    return None


def extract_layers(work, starts=None):
    """单趟分层抽取（v5 逐帖缓存版）：{博主: {"posts": [窗口帖 新→旧], "boards": [层,…]}} → (rows_by_board, errors)。

    每博主窗口内每帖已按 (post_id, 内容hash) 缓存其规范行（opinion.cache v5）——只有窗口里
    新出现/正文回填变 content 的帖走一次 DeepSeek（共享 ANNOTATION prompt，该博主新帖合成
    一个子批调用），旧帖永不重评分；每层 collapse_board 确定性坍缩。行为与 v16 同形：某博主
    该层无观点 → 不入 rows_by_board（不显示不计数）；无观点帖只是路过、不抹旧行（v16 prompt
    散文的意图落进代码）。Pillar C/D（2026-09-08 解析加固）：
    - 标注失败博主（annotate 返 None）→ **回退窗口内已缓存旧帖行**续显（quote_ts≥窗口下界
      门自动拦陈旧），不写缓存、记入 errors 下档重试——不再是失败即整档置空；
    - 坍缩后再对「本 tick 新标注帖产出、且真上卡」的少数行跑复核（opinion.verify
      keep/fix/drop，主结论句 doctrine），fix 改展示字段、drop 剔帖重坍缩续显更早行。
    同帖同层多行 → 目标日更近优先（collapse_board 内 HORIZON_RANK）。返回 rows_by_board =
    {board_key: {博主: 行}}，行 = {blogger, post_id, has_view, stance, horizon,
    summary(已剔相对词), quote, quote_ts}。
    """
    if not work:
        return {}, []
    layers_of = [b for v in work.values() for b in (v.get("boards") or [])]
    rows_by_board = {k: {} for k in dict.fromkeys(layers_of)}
    errors = []
    cache = o_cache.load(paths.ROWS_CACHE_FILE, _ROWS_CACHE_VERSION, o_prompts.ANNOTATION_SYSTEM_PROMPT)
    bloggers = cache.setdefault("bloggers", {})

    # ── 逐帖分类：窗口帖键命中即复用其缓存行；未命中 = 新帖/正文回填 → 只送该子批标注 ──
    todo, hits = [], 0               # todo: (name, boards, 需标注的新帖子集)
    win_rows = {}                    # name -> 本次窗口内各帖已缓存行的并集（供坍缩）
    fresh_posts = {}                 # name -> {post_id: post}：本 tick 新标注成功帖（Pillar C 触发记账）
    healed = False  # 主结论对象门（2026-09-09）缓存自愈：门上线前写入的矛盾旧帖作废重抽
    for name, v in work.items():
        posts = v.get("posts") or []
        ent = bloggers.get(name)
        have = {}
        if isinstance(ent, dict) and isinstance(ent.get("posts"), dict):
            # 快照键再判：逐帖自愈——缓存行里 idx=上证 但主结论点名他指的矛盾行是标注指错产物
            # （新产出已由 annotate_blogger 对象门拒收纠正；这里只清门上线前留下的旧行）。
            # 矛盾 ≠ 弃推：帖子可能真含被漏选的上证观点 → 作废整帖后下进 fresh 子批重抽恢复
            # （annotate 纠错门会重选上证句 / 纠正 idx），缓存不留矛盾行。
            for k in list(ent.get("posts") or {}):
                e = ent["posts"].get(k)
                if not (isinstance(e, dict) and isinstance(e.get("rows"), list)):
                    continue
                obj = o_ann.conflict_rows(e["rows"])
                if obj:
                    tok = o_ann._idx_object_conflict(obj[0])
                    log.warning("  %s 自愈作废缓存帖 %s：行 idx=上证 但主结论点名他指【%s】"
                                "（%s）→ 重抽恢复", name, k, tok,
                                (obj[0].get("summary") or "")[:24])
                    del ent["posts"][k]
                    healed = True
                    continue
                have[k] = e
        rows, fresh = [], []
        for p in posts:
            key = o_cache.post_key(p)
            e = have.get(key)
            if e is None:
                fresh.append(p)
            else:
                rows.extend(e["rows"])
        win_rows[name] = rows
        if fresh:
            todo.append((name, v.get("boards") or [], fresh))
        else:
            hits += 1
    if not todo:
        log.info("  行标注缓存：%d 位博主窗口帖全部命中（逐帖），跳过 DeepSeek", hits)
    elif hits:
        log.info("  行标注缓存：复用 %d / 需新抽（新增帖）%d", hits, len(todo))

    wrote = healed
    if todo:
        now_txt = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")

        def _worker(item):
            name, _boards, new_posts = item
            return name, new_posts, _annotate_rows(name, new_posts)

        with ThreadPoolExecutor(max_workers=config.ROWS_WORKERS) as pool:
            for name, new_posts, rows in pool.map(_worker, sorted(todo, key=lambda x: x[0])):
                if rows is None:
                    # Pillar D（2026-09-08）：标注失败 ≠ 本博主无观点——不抹 win_rows，坍缩回退
                    # 窗口内已缓存旧帖行续显（quote_ts≥窗口下界 门自动拦陈旧）；无缓存行则本档
                    # 置空。失败不写缓存，下档新帖自然重试。
                    errors.append(name)
                    log.warning("  %s 本档标注失败：回退窗口内已缓存旧行续显（无旧行则本档置空），"
                                "未写缓存下档重试", name)
                    continue
                # 拆回逐帖存储：rows[post_n] 指向 new_posts[post_n]（无观点帖存空列表防重抽）
                fresh_posts[name] = {str(p.get("post_id") or ""): p for p in new_posts}
                post_map = bloggers.setdefault(name, {}).setdefault("posts", {})
                per_post = {i: [] for i in range(len(new_posts))}
                for r in rows:
                    n = r.get("post_n")
                    if isinstance(n, int) and 0 <= n < len(new_posts):
                        per_post[n].append(r)
                for i, p in enumerate(new_posts):
                    key = o_cache.post_key(p)
                    post_map[key] = {"ts": o_cache.post_ts(p), "at": now_txt, "rows": per_post[i]}
                win_rows[name].extend(r for sub in per_post.values() for r in sub)
                wrote = True

    # 每博主每层确定性坍缩（纯命中零调用；新帖并入 win_rows 后同趟坍缩）
    for name, v in work.items():
        for b in (v.get("boards") or []):
            row = o_ann.collapse_board(b, name, win_rows.get(name) or [],
                                       window_start=(starts or {}).get(b),
                                       cal=calendar)  # 交易日相对再分类（2026-09-09）
            if row:
                rows_by_board[b][name] = row

    # ── Pillar C：推送复核——只复核「本 tick 新标注帖产出、坍缩后真上卡」的少数行 ──
    # 触发集 = 卡面某行 quote_ts/post_id 溯源到本 tick 新标注帖（fresh_ids）；纯缓存命中的
    # 旧行、窗口滑动/过期等确定性变化不触发。quote 非逐字/主结论取错已由 annotate 层两道门
    # 挡掉，这里只兜 idx 对象/周期与主结论句的一致性（报告侧 verify 同构 doctrine 轻量复核）。
    fresh_ids = {nm: set(fresh_posts[nm]) for nm in fresh_posts}  # 键即 str(post_id)
    candidates = []
    if fresh_ids:
        for b, m in rows_by_board.items():
            for name, disp in m.items():
                pid = str(disp.get("post_id") or "")
                if pid not in fresh_ids.get(name, ()):
                    continue                      # 出自旧帖缓存 → 非本 tick 新产出，不复核
                post = (fresh_posts.get(name) or {}).get(pid)
                if post is None:
                    continue
                # 定位坍缩选中的规范行（给复核方看 idx/spec/d/s/horizon/quote/summary 全字段）
                origin = None
                for r in (win_rows.get(name) or []):
                    if (str(r.get("post_id") or "") != pid
                            or r.get("quote_ts") != disp.get("quote_ts")
                            or r.get("horizon") != disp.get("horizon")):
                        continue
                    if (r.get("idx") != "上证指数" or r.get("cat") != "scored"):
                        continue
                    if not o_schema.horizon_spec_ok(disp.get("horizon"), str(r.get("spec") or "")):
                        continue
                    origin = r
                    break
                if origin is None:
                    continue                      # 溯源失败不硬复核（宁缺）
                # full_text = 模型当时可见的该帖文本（标题 + head 截断正文；微帖只标题）——
                # 复核 fix 的 quote 逐字校验用同一可见口径，防复核方拿截断外原文改卡
                _t, _b = o_text.resolve_post(post)
                full = (_t + "\n" + o_text.truncate(_b, limit=1200, style="head")
                        if _t and _b else (_t or _b or ""))
                candidates.append({"board": b, "blogger": name, "row": origin,
                                   "post_text": o_verify.post_text(post), "full_text": full})
    if candidates:
        decisions, vstats = o_verify.review_candidates(candidates, label="briefing:card")
        log.info("  推送复核 %d 条新帖上卡行 → keep=%d fix=%d drop=%d err=%d",
                 len(candidates), vstats["keep"], vstats["fix"], vstats["drop"], vstats["err"])
        drops = {}                                # (board, blogger) -> {post_id}
        for dec, cand in zip(decisions, candidates):
            b, nm, act = dec["board"], dec["blogger"], dec["action"]
            if act == "keep" or act == "err":
                log.info("    复核 %s/%s %s%s", b, nm, act,
                         "" if act == "keep" else f"（保留原行）：{dec['reason']}")
                continue
            disp = rows_by_board.get(b, {}).get(nm)
            if disp is None:
                continue
            if act == "fix" and dec.get("fix"):
                fx = dec["fix"]
                disp["stance"] = "多" if fx.get("d") == 1 else "空"
                disp["horizon"] = fx.get("horizon")
                disp["summary"] = o_text.strip_rel_time(fx.get("summary") or "")[:50]
                disp["quote"] = (fx.get("quote") or "").strip()[:60]
                log.info("    复核 fix %s/%s horizon→%s：%s", b, nm, disp["horizon"], dec["reason"])
            elif act == "drop":
                drops.setdefault((b, nm), set()).add(pid := str(cand["row"].get("post_id") or ""))
                log.info("    复核 drop %s/%s post_id=%s：%s", b, nm, pid, dec["reason"])
        # drop → 剔除该帖该板候选行后重坍缩，让更早仍在窗口的合格行按路过语义续显（无则置空）
        for (b, nm), pids in drops.items():
            kept = [r for r in (win_rows.get(nm) or [])
                    if str(r.get("post_id") or "") not in pids]
            alt = o_ann.collapse_board(b, nm, kept, window_start=(starts or {}).get(b),
                                       cal=calendar)  # 交易日相对再分类（2026-09-09）
            if alt:
                rows_by_board[b][nm] = alt
                log.info("    复核 drop 后 %s/%s 重坍缩续显更早窗口行 quote_ts=%s",
                         b, nm, alt.get("quote_ts"))
            else:
                rows_by_board[b].pop(nm, None)
                log.info("    复核 drop 后 %s/%s 无合格行，置空", b, nm)

    if wrote:
        # 安全修剪：含波段窗口的本档才做——早于波段窗口下界的帖永不回窗（窗口只前移），
        # 防逐帖缓存随交易日无限膨胀；纯超短档不修剪（删了波段仍在用但本档没算的帖）。
        swing_start = (starts or {}).get("swing")
        if swing_start is not None:
            for ent in bloggers.values():
                pm = ent.get("posts") if isinstance(ent, dict) else None
                if isinstance(pm, dict):
                    for k in [k for k, e in pm.items() if (e.get("ts") or 0) < swing_start]:
                        del pm[k]
        o_cache.save(paths.ROWS_CACHE_FILE, cache, o_prompts.ANNOTATION_SYSTEM_PROMPT)
        log.info("  行标注缓存已更新：共 %d 位博主", len(bloggers))
    return rows_by_board, errors


# =====================================================================
# v12：日期锚定——把博主帖子里的相对时间词换算成绝对目标日/周
# =====================================================================
# 行抽取拿到的是博主原话里的相对词（今天/明天；本周/下周），它们以
# **发帖日**为基准，卡片日一变就错位（"昨天说的明天"=今天却标成明天）。
# 这里统一按引文发帖时间换算成绝对目标：
#   - 超短：目标日 = 发帖日(今天) / 发帖日之下一交易日(明天)；只保留
#     目标日落在 {卡片日, 卡片日之下一交易日} 的表态（已兑现/过期自动剔除）。
#   - 波段：本周/下周 锚定到发帖日所在周（周一~周五）；目标周已整体过去 → 剔除。
#     anchor = 周词(相对卡片日) + 周一~周五日期段。
#   - 近日/更长/未提：无具体日期可锚，原词保留（未提 → 行头不打印周期）。
# 计数/渲染/总结都只基于解析后的 rows_by_board（本板块不显示即不计数）。

def _bj_date(ts):
    """epoch → 北京时日期；无/非法返回 None。"""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=BEIJING).date()
    except (TypeError, ValueError, OSError):
        return None


def _week_monday(d):
    """博主视角"本周"周一：周一~周五取当周周一；周六/日取下一周一（周末帖多预判将临一周）。"""
    m = d - timedelta(days=d.weekday())
    if d.weekday() >= 5:
        m += timedelta(days=7)
    return m


def _fmt_week_range(monday):
    """周展示段：周一~周五。"""
    return f"{monday:%m-%d}~{(monday + timedelta(days=4)):%m-%d}"


def next_trading_day(d):
    """d 之后最近一个交易日（委托 calendar；跨周末/节假日顺延）。"""
    return calendar.next_trading_day(d)


# 行摘要的相对时间词剥离 2026-09-08 委派 opinion.text.strip_rel_time（坍缩在 collapse_board
# 内系统侧兜底；见 v17 节与 v12 锚定注释：头行 anchor 与引文绝对时间已锚定博主相对词到具体
# 日期，摘要再出现 今天/明天/本周 只会制造"昨天说的明天"式错位 → 一律剔除）。


def _anchor_row(board_key, row, card):
    """把单条板块行按卡片日解析出绝对目标 anchor + 过期过滤。

    返回规整后的 row（带 anchor），或 None（该博主本板块不显示）。
    """
    horizon = row.get("horizon") or "未提"
    qd = _bj_date(row.get("quote_ts"))
    if board_key == "short":
        if qd is None:
            return None  # 无引文发帖时间无法解析目标日，不外显（防编造）
        target = qd if horizon == "今天" else next_trading_day(qd)  # 明天 = 下一交易日
        if target not in (card, next_trading_day(card)):
            log.info("  %s [short] %s(发帖 %s) 目标日 %s 不在今/下一交易日 → 不显示",
                     row.get("blogger"), horizon, qd, target)
            return None
        out = dict(row)
        out["anchor"] = target.strftime("%m-%d")
        return out
    # 波段
    if horizon in ("本周", "下周"):
        if qd is None:
            out = dict(row)
            out["anchor"] = horizon
            return out
        mon = _week_monday(qd) + (timedelta(days=7) if horizon == "下周" else timedelta())
        if mon + timedelta(days=4) < card:
            log.info("  %s [swing] %s 目标周 %s 已整体过去 → 不显示",
                     row.get("blogger"), horizon, _fmt_week_range(mon))
            return None
        cw = _week_monday(card)
        if mon == cw:
            word = "本周"
        elif mon == cw + timedelta(days=7):
            word = "下周"
        else:
            word = ""  # 极端情况只留日期段
        out = dict(row)
        out["anchor"] = f"{word} {_fmt_week_range(mon)}" if word else _fmt_week_range(mon)
        return out
    out = dict(row)
    out["anchor"] = horizon if horizon != "未提" else ""
    return out


def resolve_anchors(rows_by_board, now):
    """按卡片日对两板块行做日期锚定 + 过期剔除 → {key: {博主: 规整行(带 anchor)}}。

    now 为北京时 datetime（卡片日 = now.date()）。超短剔除目标已过/未指向今明者；
    波段剔除目标周已过者。
    """
    card = now.date()
    out = {}
    for key in config.PANEL_KEYS:
        live = {}
        for name, row in (rows_by_board.get(key) or {}).items():
            resolved = _anchor_row(key, row, card)
            if resolved is not None:
                live[name] = resolved
        out[key] = live
    return out


# =====================================================================
# v11/v12：双板块计数 + LEGACY 跨板块收敛总结（v13 单板块总结见文件尾）
# =====================================================================

def board_counts(rows_by_board):
    """双板块计数：每板块在成员名单内统计 多/空，shown=bull+bear，members=名单长度。

    rows_by_board: {key: {博主: row}}（仅 has_view 行，见 extract_layers）。
    未表态成员不计数（也不显示），无"合计=xx"断言。
    """
    out = {}
    for key in config.PANEL_KEYS:
        members = config.PANELS[key]
        rows = rows_by_board.get(key) or {}
        bull = sum(1 for n in members if (rows.get(n) or {}).get("stance") == "多")
        bear = sum(1 for n in members if (rows.get(n) or {}).get("stance") == "空")
        out[key] = {"bull": bull, "bear": bear, "shown": bull + bear,
                    "members": len(members)}
    return out


SUMMARY_SYSTEM_PROMPT = """你是财经观点收敛总结助手。给你当前推送的两板块博主方向观点快照：两板块各自成组（组内每行 = 一位博主在该板块周期内的最新表态：多/空 · 周期词 · 一句核心 · 引文发帖时间），外加**系统统计的分档权威计数**（每板块 几多几空、N/M 人表态）与大盘行情。

板块即两层：
- 「超短(0-1日)」= 博主对今天/明天的表态；「波段(2日+)」= 对近日/本周/下周/更远的表态。
- 开头 8 位博主两板块都上榜（同一人既给短线看法也给波段看法），属同一位作者的**跨周期分层**，不是观点翻转；他们在两块立场可能不同甚至相反，这是自洽的（短线反弹≠波段反转）。
- **跨板块方向相反不是对立而是层叠**：如"超短板块多人看今日/明日反弹 + 波段板块多人看调整未结束"——两层兼容，反弹常是波段调整中的反抽/减仓窗口。**严禁**用"多空对立/对峙/拉锯/分歧显著/阵营 X 比 X"描述跨板块组合。
- 只有**同板块内真反向**（同为超短板块：有人看反弹、有人看续跌）才算方向分歧，才可点出；某板块清一色同向、或仅 1~2 人表态时，直接陈述方向即可，不要为凑"分歧/反向"字样而硬造。
- 同板块同方向但操作取向相反（都看反弹、一个持有、一个反弹减仓）→ 写"反弹共识下的操作分化"，不算方向对立。
- **日期纪律**：卡片日见输入【日期锚点】。快照每行的 anchor/引文时间已是系统按引文发帖日换算好的绝对结果（如 ▍孙万林：空·09-03｜…｜引文 09-02 15:06 ＝ 该博主 09-02 帖里写的"明天"，实指 09-03）。涉及某位博主的目标日，**只能照抄该行 anchor 或引文日期，禁止自己再用 明天/今日/下周 等词做任何推算**（原话再怎么写也别展开）；拿不准就只讲方向/逻辑/应对，不写具体日期。板块级可写 今日/明日/本周，但必须对应【日期锚点】的卡片日/下一交易日/本周周段；结尾操作句不必带日期。

输出**一段收敛总结**（≤280 字，中文流畅一段；不要分点/列表/小标题）：
① 开头按板块陈述版图，用系统给的**分档计数**，不要合并总比数、不要重算（如：超短板块 X 多 Y 空、N 人表态，多数看今日/明日…；波段板块 U 多 V 空、M 人表态，多数认为…）。
② 中间每板块点 1~2 位代表博主（只点快照里出现过的）；两板块方向相反时解释它们的层叠关系；只在同板块真反向时用"分歧"；若 8 位双板块博主里有人短线与波段立场不同，可点名讲其分层自洽。
③ 结尾落到操作参考：超短(0-1日) 一句 + 波段(2日+) 一句。
禁止复述引文原话；禁止提快照之外的博主或内容；禁止编造计数。
输出严格 JSON：{"summary": "收敛总结一段(≤280字)"}。只输出 JSON，无其他文字。"""


def summarize_boards(rows_by_board, counts, market_text, slot_label, date_str,
                     window_txt="", now=None):
    """LEGACY（v12 跨板块两层收敛总结）：v13 已拆成单板块 summarize_board，
    本函数不再被 run_briefing 接线，仅保留供历史复刻/回退。

    两板块方向快照 + 系统计数 → 一段跨板块收敛总结（板块即两层）。
    rows_by_board/counts 形状见 extract_layers/board_counts（rows 应已过
    resolve_anchors 日期锚定）；now 为北京时 datetime（决定卡片日与"今天/明日"措辞）。
    失败兜底返回双板块计数行。
    """
    now = now or datetime.now(BEIJING)
    card = now.date()
    nm = calendar.next_trading_day(card)
    cw = _week_monday(card)
    wd = ("一", "二", "三", "四", "五", "六", "日")[card.weekday()]
    anchor_note = (f"卡片日={card:%m-%d}（周{wd}）｜下一交易日(明日)={nm:%m-%d}｜"
                   f"本周={_fmt_week_range(cw)}｜下周={_fmt_week_range(cw + timedelta(days=7))}")
    snap = []
    for key in config.PANEL_KEYS:
        c = counts.get(key) or {}
        meta = config.BOARD_META[key]
        lines = [f"【{meta['label']} · {c.get('bull', 0)}多/{c.get('bear', 0)}空"
                 f"（{c.get('shown', 0)}/{c.get('members', 0)} 表态）】"]
        rows = rows_by_board.get(key) or {}
        for b in config.PANELS[key]:
            r = rows.get(b)
            if not r:
                continue
            ts = r.get("quote_ts")
            t = datetime.fromtimestamp(int(ts), tz=BEIJING).strftime("%m-%d %H:%M") if ts else ""
            lab = r.get("anchor")
            if lab is None:  # 兜底：未锚定的历史行退回周期词
                h = r.get("horizon") or "未提"
                lab = "" if h == "未提" else h
            lines.append(f"▍{b}：{r['stance']}" + (f"·{lab}" if lab else "")
                         + f"｜{r.get('summary')}｜引文 {t}")
        snap.append("\n".join(lines))
    snapshot_txt = "\n".join(snap) if any(s.strip() for s in snap) else "（两板块均无方向观点）"
    counts_txt = config.format_board_counts(counts)
    user_msg = f"""【时段】{date_str} {slot_label}（{window_txt or '本期'}）
【日期锚点】{anchor_note}
【行情】{market_text}
【系统统计（权威，勿重算勿合并）】{counts_txt}
【两板块方向快照】
{snapshot_txt}"""
    for _attempt in range(ROW_MAX_ATTEMPTS):
        result, raw = call_json(None, SUMMARY_SYSTEM_PROMPT, user_msg, "briefing:summarize_boards")
        if result is None:
            continue
        s = (result.get("summary") or "").strip()
        if s:
            return s[:320]
    return f"多空版图：{counts_txt}"


# =====================================================================
# v13：单板块收敛总结（超短/波段 各推各群、各自一段，无跨板块层叠）
# =====================================================================
# 与 LEGACY 跨板块 prompt 的区别：快照只注入本板块名单行、计数用单板块
# format_board_count、日期纪律按板块收窄（short：今日/明日 = 卡片日/下一交易
# 日；swing：波段目标不可能是今明，本周/下周 周段见锚点）、无任何"板块即两层 /
# 前 8 位双板块博主 / 跨板块层叠禁对立"等跨板块句子。

SHORT_SUMMARY_SYSTEM_PROMPT = """你是财经观点收敛总结助手。给你「超短板块」博主的方向观点快照：每行 = 一位博主的最新**超短(0-1日)**表态 —— 多/空 · 目标日(anchor，如 ·09-03) · 一句核心 · 引文发帖时间；外加**系统统计的本板块权威计数**（X 多/Y 空、N/M 人表态）与大盘行情。

口径（本卡只有超短这一层，不存在另一板块）：
- 快照成员都是只对 今天/明天 做过方向表态、且目标日落在【日期锚点】的 卡片日/下一交易日 的博主；行头 anchor 即系统按发帖日换算的绝对目标日（如 ·09-03），引文时间为发帖时刻。
- 同板块内真反向（同对今/明：有人看反弹、有人看续跌）才算方向分歧、才可点出；清一色同向、或仅 1~2 人表态时直接陈述方向，不要为凑"分歧"而硬造。
- 同方向但操作取向相反（都看反弹、一个持有、一个反弹减仓）→ 写"反弹共识下的操作分化"，不算方向对立。
- **日期纪律**：卡片日与下一交易日见【日期锚点】。涉及某位博主的目标日**只能照抄该行 anchor 或引文日期**，禁止自己用 今天/明天/今日 等词推算任何博主表态所指的日子（原话再怎么写也别展开）；拿不准就只讲方向/逻辑/应对。板块整体措辞可写 今日/明日，但必须对应【日期锚点】的 卡片日/下一交易日；结尾操作句不必带日期。

输出**一段收敛总结**（≤240 字，中文流畅一段；不要分点/列表/小标题）：
① 开头用系统给的**本板块计数**陈述版图（如：超短板块 X 多 Y 空、N 人表态，多数看今日反弹…）；
② 中间点 1~2 位代表博主（只点快照里出现过的，讲观点要点与操作取向）；
③ 结尾一句超短(0-1日)操作参考。
禁止复述引文原话；禁止提快照之外的博主或内容；禁止编造计数。
输出严格 JSON：{"summary": "收敛总结一段(≤240字)"}。只输出 JSON，无其他文字。"""


SWING_SUMMARY_SYSTEM_PROMPT = """你是财经观点收敛总结助手。给你「波段板块」博主的方向观点快照：每行 = 一位博主的最新**波段(2日+)**表态 —— 多/空 · 目标周/周期(anchor，如 本周 08-31~09-04，或 近日/更长 原词) · 一句核心 · 引文发帖时间；外加**系统统计的本板块权威计数**（X 多/Y 空、N/M 人表态）与大盘行情。

口径（本卡只有波段这一层，不存在另一板块）：
- 快照成员都是对 近日/本周/下周/更长 做过方向表态、且目标周未整体过去的博主；行头 anchor 是系统按发帖日锚定的绝对周段（本周/下周 = 周一~周五日期段）或 近日/更长 原词。
- 同板块内真反向才算方向分歧、才可点出；清一色同向、或仅 1~2 人表态时直接陈述方向，不要为凑"分歧"而硬造。
- 同方向但操作取向相反（都看震荡调整、一个减仓、一个等待低吸）→ 写"共识下的操作分化"，不算方向对立。
- **日期纪律**：卡片日与 本周/下周 周段见【日期锚点】。波段目标不可能是 今天/明天 这类超短词——涉及某位博主的目标周**只能照抄该行 anchor 或引文日期**，禁止自己用 本周/下周/周X 推算；近日/更长 表态只讲方向逻辑、不补具体日期。板块整体可写 本周/下周，但必须对应【日期锚点】的周段；结尾操作句不必带日期。

输出**一段收敛总结**（≤240 字，中文流畅一段；不要分点/列表/小标题）：
① 开头用系统给的**本板块计数**陈述版图（如：波段板块 X 多 Y 空、N 人表态，多数认为…）；
② 中间点 1~2 位代表博主（只点快照里出现过的，讲观点要点）；
③ 结尾一句波段(2日+)操作参考。
禁止复述引文原话；禁止提快照之外的博主或内容；禁止编造计数。
输出严格 JSON：{"summary": "收敛总结一段(≤240字)"}。只输出 JSON，无其他文字。"""


PANEL_SUMMARY_PROMPT = {
    "short": SHORT_SUMMARY_SYSTEM_PROMPT,
    "swing": SWING_SUMMARY_SYSTEM_PROMPT,
}


def summarize_board(board_key, rows, counts, market_text, date_str,
                    window_txt="", now=None):
    """单板块方向快照 + 本板块计数 → 一段本板块收敛总结（v13 主路径）。

    rows = 该板块 {博主: 已过 resolve_anchors 的规整行}；counts = 该板块单键计数
    {bull,bear,shown,members}；now 为北京时 datetime（决定卡片日 / 本周周段措辞）。
    失败兜底返回 config.format_board_count 单板块计数行。
    """
    now = now or datetime.now(BEIJING)
    card = now.date()
    wd = ("一", "二", "三", "四", "五", "六", "日")[card.weekday()]
    if board_key == "short":
        nm = calendar.next_trading_day(card)
        anchor_note = f"卡片日={card:%m-%d}（周{wd}）｜下一交易日(明日)={nm:%m-%d}"
    else:
        cw = _week_monday(card)
        anchor_note = (f"卡片日={card:%m-%d}（周{wd}）｜"
                       f"本周={_fmt_week_range(cw)}｜下周={_fmt_week_range(cw + timedelta(days=7))}")
    meta = config.BOARD_META[board_key]
    c = counts or {}
    lines = [f"【{meta['label']} · {c.get('bull', 0)}多/{c.get('bear', 0)}空"
             f"（{c.get('shown', 0)}/{c.get('members', 0)} 表态）】"]
    for b in config.PANELS[board_key]:
        r = rows.get(b)
        if not r:
            continue
        ts = r.get("quote_ts")
        t = datetime.fromtimestamp(int(ts), tz=BEIJING).strftime("%m-%d %H:%M") if ts else ""
        lab = r.get("anchor")
        if lab is None:  # 兜底：未锚定的历史行退回周期词
            h = r.get("horizon") or "未提"
            lab = "" if h == "未提" else h
        lines.append(f"▍{b}：{r['stance']}" + (f"·{lab}" if lab else "")
                     + f"｜{r.get('summary')}｜引文 {t}")
    snapshot_txt = "\n".join(lines)
    counts_txt = config.format_board_count(board_key, c)
    user_msg = f"""【时段】{date_str}（{window_txt or '本期'}）
【日期锚点】{anchor_note}
【行情】{market_text}
【系统统计（权威，勿重算）】{counts_txt}
【{meta['label']}方向快照】
{snapshot_txt}"""
    prompt = PANEL_SUMMARY_PROMPT[board_key]
    for _attempt in range(ROW_MAX_ATTEMPTS):
        result, raw = call_json(None, prompt, user_msg, f"briefing:summarize:{board_key}")
        if result is None:
            continue
        s = (result.get("summary") or "").strip()
        if s:
            return s[:240]
    return f"多空版图：{counts_txt}"
