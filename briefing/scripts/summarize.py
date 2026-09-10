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
  2. resolve_anchors：按引文发帖日锚定绝对目标 + 验证终点时效门（2026-09-10：两板统一
     剔除**验证终点已过**者 + 超短只认 spec∈{today,t1}；超短另剔目标日不指今明、波段另剔
     目标周已过）。
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
**v21（2026-09-09 Pillar C 复核裁决固化逐帖缓存）**：fix/drop 不再只是当档内存展示 patch（fix 只
  改 display 行、drop 只剔本档 win_rows 重坍缩——从不置 wrote、不落缓存 → 下一档坍缩从复核前原始
  行把旧观点捞回，恰好制造跨档反转/缩水）。复核裁决现 mutate 逐帖缓存行（fix 就地覆写源行 d/s/idx/
  spec/horizon/quote/summary；drop 剔该帖**被复核板层**全部行、余空保 entry 不整删防重抽复活），随后
  对全部板重坍缩 → 修正后缓存行成为后续所有档的坍缩输入（T1 复核档输出 == T2 后续档输出，I1 无新增
  不反转 / I2 无变化不缩水 结构性成立）。idx≠上证 的 fix 持久化后 collapse 自动挡在上证 卡外 → 持久
  删除式效果（相较此前"显示一档后回弹"是有意语义升级）。复核触发集不变（仍只对本 tick 新标注帖产出的
  上卡行）；不改缓存格式，无需 bump _ROWS_CACHE_VERSION。
v12 跨板块 summarize_boards / SUMMARY_SYSTEM_PROMPT 与旧 v8 全板共识路径（POINTS_SYSTEM_PROMPT /
SYNTH_SYSTEM_PROMPT / extract_points / synthesize）已于 2026-09-09 C1 一并移除（git 历史与
archive/20260909-legacy 可恢复）；v9/v10 的 18 行名单路径已整段替换。
"""
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import calendar, config, endpoint, paths

# 2026-09-08 共享模块重构：判层 prompt 收敛为 opinion 单一共享逐帖标注（ANNOTATION_SYSTEM_PROMPT），
# 读帖/清洗/DeepSeek 网关/标注缓存一并委派顶层 opinion/ 包（推送、报告、画像三场景同源）。
# briefing 是独立部署单元，兜底把父仓根（paths.REPO_ROOT）补进 sys.path 以便 `import opinion`。
try:
    from opinion import annotate as o_ann, cache as o_cache, ds as o_ds  # noqa: E402
    from opinion import schema as o_schema  # noqa: E402
    from opinion import verify as o_verify  # noqa: E402
except ImportError:
    if not any(os.path.abspath(p) == os.path.abspath(paths.REPO_ROOT) for p in sys.path):
        sys.path.insert(0, paths.REPO_ROOT)
    from opinion import annotate as o_ann, cache as o_cache, ds as o_ds  # noqa: E402
    from opinion import schema as o_schema  # noqa: E402
    from opinion import verify as o_verify  # noqa: E402

log = logging.getLogger("briefing")

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


# ── LEGACY（v8 全板共识卡 + v12 跨板块收敛）2026-09-09 C1 整段移除：git / archive/20260909-legacy 可恢复 ──
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
# /行过期由 quote_ts≥该层窗口下界 门自动消化。版本或**标注期指纹**（opinion.annotate.
# annotation_fp_input() = 共享 ANNOTATION prompt + 到案后缀，2026-09-09 A3）任一不符 →
# 整缓存作废全量重抽（首档按博主新帖合批一次调用，量级同 v4）。坍缩/复核是读时确定性步骤，
# 改它们**不**作废缓存。v6：default_horizon t5 兜底改「未提」（A4-2）影响已缓存行语义。
_ROWS_CACHE_VERSION = 6


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


def _origin_matches(board, disp, r, downgrade_ok=False):
    """Pillar C 溯源：候选规范行 r 是否坍缩展示行 disp 的来源（2026-09-09 A4-1）。

    展示行 disp = collapse_board 输出（2026-09-10 起带 spec/anchor/endpoint，本函数只用
    post_id/quote_ts/horizon，与新增键无关），源行 r 为窗口缓存规范行。精确 pass
    (downgrade_ok=False)：post_id/quote_ts 相等 + idx=上证 + cat=scored + horizon 逐字相等 +
    horizon_spec_ok(disp.horizon, r.spec)。降级豁免 pass (downgrade_ok=True)：仅放行 short 板
    展示归一「明天」的交易日再分类行——周五~周日发帖 spec=nweek_first 的规范行（horizon=下周）
    被坍缩按下一交易日降级到 short，展示词归一一为明天，精确 pass 永不匹配 → 最需复核的再分类
    新行逃复核。返回 True/False。
    """
    if (str(r.get("post_id") or "") != str(disp.get("post_id") or "")
            or r.get("quote_ts") != disp.get("quote_ts")):
        return False
    if r.get("idx") != "上证指数" or r.get("cat") != "scored":
        return False
    spec = str(r.get("spec") or "")
    if downgrade_ok:
        return (board == "short" and disp.get("horizon") == "明天"
                and spec == "nweek_first" and r.get("horizon") == "下周")
    if r.get("horizon") != disp.get("horizon"):
        return False
    return o_schema.horizon_spec_ok(disp.get("horizon"), spec)


def _row_board_layer(r, cal):
    """缓存规范行归属板别（2026-09-09 v21：复核 drop 剔层行用，判层同 collapse_board 的 _row_layer 门）。"""
    horizon = r.get("horizon")
    if not isinstance(horizon, str) or not horizon:
        return None
    return o_ann._row_layer(horizon, str(r.get("spec") or ""),
                            o_ann._quote_date(r.get("quote_ts")), cal)


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
      keep/fix/drop，主结论句 doctrine）；fix/drop 裁决**固化进逐帖缓存**（v21：fix 覆写源行、
      drop 剔该板层行、余空保 entry），随后统一重坍缩——修正后缓存行成为后续所有档的坍缩输入，
      杜绝"无新增却反转 / 该在的少了"的跨档闪变。
    同帖同层多行 → 目标日更近优先（collapse_board 内 HORIZON_RANK）。返回 rows_by_board =
    {board_key: {博主: 行}}，行 = {blogger, post_id, has_view, stance, horizon,
    summary(已剔相对词), quote, quote_ts}。
    """
    if not work:
        return {}, []
    layers_of = [b for v in work.values() for b in (v.get("boards") or [])]
    rows_by_board = {k: {} for k in dict.fromkeys(layers_of)}
    errors = []
    cache = o_cache.load(paths.ROWS_CACHE_FILE, _ROWS_CACHE_VERSION, o_ann.annotation_fp_input())
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

    # 每博主每层确定性坍缩（纯命中零调用；新帖并入 win_rows 后同趟坍缩）。Pillar C 复核裁决固化
    # （v21）后重跑同趟：fix/drop mutate 的源行与 win_rows/缓存条目是同一批 dict 对象，重坍缩即让
    # 当档卡面 == 后续档坍缩输入；未受影响博主输入未变 → 逐位复现同一行，零副作用。
    def _collapse_all():
        for _name, _v in work.items():
            for _b in (_v.get("boards") or []):
                _row = o_ann.collapse_board(_b, _name, win_rows.get(_name) or [],
                                            window_start=(starts or {}).get(_b),
                                            cal=calendar)  # 交易日相对再分类（2026-09-09）
                if _row:
                    rows_by_board[_b][_name] = _row
                else:
                    rows_by_board[_b].pop(_name, None)

    _collapse_all()

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
                # 定位坍缩选中的规范行（给复核方看 idx/spec/d/s/horizon/quote/summary 全字段）。
                # 两段溯源（A4-1）：先精确命中（horizon 逐字相等，防降级豁免误抓到同帖真 t1 行）；
                # 不中再放行降级豁免——short 板展示归一「明天」的交易日再分类行（源行 spec=nweek_first、
                # horizon=下周，collapse_board 把展示词归一为明天）否则永不匹配、最需复核的行逃复核。
                origin = None
                for r in (win_rows.get(name) or []):
                    if _origin_matches(b, disp, r):
                        origin = r
                        break
                if origin is None:
                    for r in (win_rows.get(name) or []):
                        if _origin_matches(b, disp, r, downgrade_ok=True):
                            origin = r
                            break
                if origin is None:
                    continue                      # 溯源失败不硬复核（宁缺）
                # full_text = 出处帖文本（o_verify.post_text = 标题 + middle 1200 正文，与给复核
                # 方看的口径**完全同一**）——复核 fix 的 quote 逐字校验用同口径，防 head/middle 截断
                # 分叉：复核方依 middle 文本引了中后部原话，却拿 head 截断文本逐字比对被误拒
                pt = o_verify.post_text(post)
                candidates.append({"board": b, "blogger": name, "row": origin,
                                   "post_text": pt, "full_text": pt})
    if candidates:
        decisions, vstats = o_verify.review_candidates(candidates, label="briefing:card")
        log.info("  推送复核 %d 条新帖上卡行 → keep=%d fix=%d drop=%d err=%d",
                 len(candidates), vstats["keep"], vstats["fix"], vstats["drop"], vstats["err"])
        # v21（2026-09-09 复核裁决固化逐帖缓存）：fix/drop mutate 源规范行——源行与 win_rows /
        # 缓存条目 rows 是**同一批 dict 对象**，随 wrote→save 持久化。不再只 patch 当档展示行，
        # 否则下一档坍缩从复核前原始行把旧观点捞回 → 恰是"无新增却反转 / 该在的少了"。
        applied = 0
        for dec, cand in zip(decisions, candidates):
            b, nm, act = dec["board"], dec["blogger"], dec["action"]
            if act in ("keep", "err"):
                log.info("    复核 %s/%s %s%s", b, nm, act,
                         "" if act == "keep" else f"（保留原行）：{dec['reason']}")
                continue
            origin = cand["row"]
            disp = rows_by_board.get(b, {}).get(nm)
            # 防御：复核定位的源行须与卡面展示行同帖同时刻（防裁决套到错补的行上丢 fix/drop）
            if (disp is None
                    or str(disp.get("post_id") or "") != str(origin.get("post_id") or "")
                    or disp.get("quote_ts") != origin.get("quote_ts")):
                log.warning("  %s 复核 %s/%s 展示行与源行失配（post_id/quote_ts），跳过裁决",
                            nm, b, act)
                continue
            if act == "fix":
                fx = dec.get("fix")
                if not fx:
                    continue
                fixed = dict(origin)
                fixed.update(fx)      # 覆写 d/s/idx/spec/cat/horizon/quote/summary；blogger/post_id/pub/quote_ts 保留
                if o_ann.conflict_rows([fixed]):
                    # 硬化：fix 后成 idx=上证 但主结论点名他指的矛盾行 → 不落缓存（否则下档坍缩
                    # 自愈会作废整帖重抽、撤销本复核）。按原行保留（同 keep），log 供追溯。
                    log.warning("  %s 复核 fix(%s/%s) 将成 idx=上证×点名他指 矛盾行，不落缓存按原行保留",
                                nm, b, fixed.get("idx"))
                    continue
                origin.update(fx)     # 就地改：origin ∈ win_rows 且 ∈ 缓存条目 rows（同对象引用）
                applied += 1
                if fixed.get("idx") != "上证指数":
                    log.info("    复核 fix %s/%s → idx=%s（上证 卡外，持久不再上卡）：%s",
                             b, nm, fixed.get("idx"), dec["reason"])
                else:
                    log.info("    复核 fix %s/%s horizon→%s d=%s：%s",
                             b, nm, origin.get("horizon"), origin.get("d"), dec["reason"])
            else:                     # act == "drop"（review_candidates 只出 keep/fix/drop/err）
                # 定位含源行的缓存条目：源行必为本 tick 新标注写入（fresh 门），按身份找免 key 重算
                posts_map = (bloggers.get(nm) or {}).get("posts") or {}
                entry = next((e for e in posts_map.values()
                              if any(r is origin for r in (e.get("rows") or []))), None)
                if entry is None:
                    log.warning("  %s 复核 drop %s/%s 找不到源行缓存条目，跳过裁决", nm, b)
                    continue
                # 剔该帖**被复核板 b 层**的全部行（判层同 collapse 的 _row_layer 门）——整帖该板
                # 主张不可取信，防同层未复核兄弟行胜出复活；其它层行保留（跨层观点不因本层 drop 消失）。
                # 余空保 entry rows=[]，**绝不整删条目**——整删会 cache-miss 当新帖重抽复活。
                drop_rows = [r for r in (entry.get("rows") or [])
                             if _row_board_layer(r, calendar) == b]
                if not drop_rows:
                    continue
                drop_ids = {id(r) for r in drop_rows}
                win_rows[nm] = [r for r in (win_rows.get(nm) or []) if id(r) not in drop_ids]
                entry["rows"] = [r for r in (entry.get("rows") or []) if id(r) not in drop_ids]
                pid = str(origin.get("post_id") or "")
                applied += 1
                log.info("    复核 drop %s/%s post_id=%s 剔该板 %d 行：%s",
                         b, nm, pid, len(drop_rows), dec["reason"])
        if applied:
            _collapse_all()           # 用 mutate 后的 win_rows（缓存同对象）重坍缩全部板
            wrote = True
            log.info("  复核裁决 %d 条已固化进逐帖缓存并重坍缩（后续档坍缩输入 = 修正后行）", applied)

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
        o_cache.save(paths.ROWS_CACHE_FILE, cache, o_ann.annotation_fp_input())
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
    """d 所在自然周（ISO 周）的周一（委托 calendar.iso_week_monday）。

    锚定展示与验证终点**必须**同一周定义，否则卡面出现"下周 09-14~09-18 · 终点 09-11
    收盘"式自相矛盾（详见 calendar.iso_week_monday 与 endpoint 模块注释）。
    2026-09-10 周口径修正：不再对周六/日前瞻加 7 天——周末行说"本周"指的是**刚结束**
    那一周（该周已过 → 下方目标周已过门剔除）；真在预判即将到来那一周的，判层编 nweek。
    """
    return calendar.iso_week_monday(d)


def _fmt_week_range(monday):
    """周展示段：周一~周五。"""
    return f"{monday:%m-%d}~{(monday + timedelta(days=4)):%m-%d}"


def next_trading_day(d):
    """d 之后最近一个交易日（委托 calendar；跨周末/节假日顺延）。"""
    return calendar.next_trading_day(d)


# 行摘要的相对时间词剥离 2026-09-08 委派 opinion.text.strip_rel_time（坍缩在 collapse_board
# 内系统侧兜底；见 v17 节与 v12 锚定注释：头行 anchor 与引文绝对时间已锚定博主相对词到具体
# 日期，摘要再出现 今天/明天/本周 只会制造"昨天说的明天"式错位 → 一律剔除）。


def _anchor_row(board_key, row, card, now):
    """把单条板块行按卡片日解析出绝对目标 anchor + 验证终点 + 过期过滤。

    返回规整后的 row（带 anchor / endpoint），或 None（该博主本板块不显示）。

    v18（2026-09-10 用户需求）两道**时效门**，两板块统一：
    ① **验证终点过期门**：行的 spec → 验证终点日（`endpoint.endpoint_of`），终点时刻 =
       该日 15:00 收盘；已 ≤ 现在 → 该预测的验证时点已经发生，不再显示
       （"9月9日晚上发的、预测 9.9 下午三点收盘"即此类）。`long`（不计分/无期限）无终点、
       不过此门（不编造日期）。
    ② **超短 spec 门**：超短板只认 `spec ∈ {today, t1}`（1 个交易日内的预测能力），
       其余档位即使 horizon 被归到 今天/明天 也不上超短卡。
    通过的行带 endpoint（date），供 render 行头标注与 summarize 快照引用。
    """
    horizon = row.get("horizon") or "未提"
    spec = row.get("spec")
    qd = _bj_date(row.get("quote_ts"))
    # ── 门①（两板统一）：验证终点已过 → 不显示 ──
    ep, ep_dt = None, None
    if qd is not None and spec:
        try:
            ep = endpoint.endpoint_of(qd, spec)
            ep_dt = endpoint.endpoint_dt(qd, spec)
        except ValueError:
            log.warning("  %s [%s] 未知 spec=%r，无法推算验证终点（行不过期门，放行）",
                        row.get("blogger"), board_key, spec)
    if ep_dt is not None and ep_dt <= now:
        log.info("  %s [%s] %s spec=%s 验证终点 %s 15:00 已过（卡 %s %s）→ 不显示",
                 row.get("blogger"), board_key, horizon, spec,
                 ep.strftime("%m-%d"), card, now.strftime("%H:%M"))
        return None
    if board_key == "short":
        # ── 门②：超短只认 today/t1（预测能力 = 1 个交易日内）──
        if spec not in ("today", "t1"):
            log.warning("  %s [short] spec=%r 不在 {today,t1} → 不上超短卡",
                        row.get("blogger"), spec)
            return None
        if qd is None:
            return None  # 无引文发帖时间无法解析目标日，不外显（防编造）
        target = qd if horizon == "今天" else next_trading_day(qd)  # 明天 = 下一交易日
        if target not in (card, next_trading_day(card)):
            log.info("  %s [short] %s(发帖 %s) 目标日 %s 不在今/下一交易日 → 不显示",
                     row.get("blogger"), horizon, qd, target)
            return None
        out = dict(row)
        out["anchor"] = target.strftime("%m-%d")
        if ep is not None:
            out["endpoint"] = ep
        return out
    # 波段
    if horizon in ("本周", "下周"):
        if qd is None:
            out = dict(row)
            out["anchor"] = horizon
            return out
        # 目标周 = 发帖日所在周（本周）/ 发帖日 +7 天所在周（下周）——与 endpoint_of 同口径。
        # 周末发帖的「本周」= 刚结束那一周 → 下面"目标周已整体过去"门必然命中剔除
        # （真在预判即将到来那一周的，判层编 nweek，走 +7 分支）。
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
        if ep is not None:
            out["endpoint"] = ep
        return out
    out = dict(row)
    out["anchor"] = horizon if horizon != "未提" else ""
    if ep is not None:
        out["endpoint"] = ep
    return out


def resolve_anchors(rows_by_board, now):
    """按卡片日对两板块行做日期锚定 + 时效过滤 → {key: {博主: 规整行(带 anchor/endpoint)}}。

    now 为北京时 datetime（卡片日 = now.date()）。两板块统一：验证终点已过者剔除
    （见 _anchor_row 门①）；超短另剔非 today/t1 档与目标日不指向今明者；波段另剔目标周已过者。
    """
    card = now.date()
    out = {}
    for key in config.PANEL_KEYS:
        live = {}
        for name, row in (rows_by_board.get(key) or {}).items():
            resolved = _anchor_row(key, row, card, now)
            if resolved is not None:
                live[name] = resolved
        out[key] = live
    return out


# =====================================================================
# v11/v12：双板块计数（board_counts）；v13 单板块收敛总结见文件尾
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

# =====================================================================
# v13：单板块收敛总结（超短/波段 各推各群、各自一段，无跨板块层叠）
# =====================================================================
# 与 LEGACY 跨板块 prompt 的区别：快照只注入本板块名单行、计数用单板块
# format_board_count、日期纪律按板块收窄（short：今日/明日 = 卡片日/下一交易
# 日；swing：波段目标不可能是今明，本周/下周 周段见锚点）、无任何"板块即两层 /
# 前 8 位双板块博主 / 跨板块层叠禁对立"等跨板块句子。

SHORT_SUMMARY_SYSTEM_PROMPT = """你是财经观点收敛总结助手。给你「超短板块」博主的方向观点快照：每行 = 一位博主的最新**超短(0-1日)**表态 —— 多/空 · 目标日(anchor，如 ·09-03) · 验证终点(如 终点 09-03 收盘) · 一句核心 · 引文发帖时间；外加**系统统计的本板块权威计数**（X 多/Y 空、N/M 人表态）与大盘行情。

口径（本卡只有超短这一层，不存在另一板块）：
- 快照成员都是只对 今天/明天 做过方向表态、且目标日落在【日期锚点】的 卡片日/下一交易日 的博主；行头 anchor 即系统按发帖日换算的绝对目标日（如 ·09-03），引文时间为发帖时刻。
- 同板块内真反向（同对今/明：有人看反弹、有人看续跌）才算方向分歧、才可点出；清一色同向、或仅 1~2 人表态时直接陈述方向，不要为凑"分歧"而硬造。
- 同方向但操作取向相反（都看反弹、一个持有、一个反弹减仓）→ 写"反弹共识下的操作分化"，不算方向对立。
- **日期纪律**：卡片日与下一交易日见【日期锚点】。涉及某位博主的目标日**只能照抄该行 anchor 或引文日期**，禁止自己用 今天/明天/今日 等词推算任何博主表态所指的日子（原话再怎么写也别展开）；拿不准就只讲方向/逻辑/应对。板块整体措辞可写 今日/明日，但必须对应【日期锚点】的 卡片日/下一交易日；结尾操作句不必带日期。行头 `终点 MM-DD 收盘` 是系统算好的**验证终点**（该预测兑现/结算的时刻），**可照抄引用、禁止自行推算或改写**，不得把它写成别的日期。

输出**一段收敛总结**（≤240 字，中文流畅一段；不要分点/列表/小标题）：
① 开头用系统给的**本板块计数**陈述版图（如：超短板块 X 多 Y 空、N 人表态，多数看今日反弹…）；
② 中间点 1~2 位代表博主（只点快照里出现过的，讲观点要点与操作取向）；
③ 结尾一句超短(0-1日)操作参考。
禁止复述引文原话；禁止提快照之外的博主或内容；禁止编造计数。
输出严格 JSON：{"summary": "收敛总结一段(≤240字)"}。只输出 JSON，无其他文字。"""


SWING_SUMMARY_SYSTEM_PROMPT = """你是财经观点收敛总结助手。给你「波段板块」博主的方向观点快照：每行 = 一位博主的最新**波段(2日+)**表态 —— 多/空 · 目标周/周期(anchor，如 本周 08-31~09-04，或 近日/更长 原词) · 验证终点(如 终点 09-04 收盘) · 一句核心 · 引文发帖时间；外加**系统统计的本板块权威计数**（X 多/Y 空、N/M 人表态）与大盘行情。

口径（本卡只有波段这一层，不存在另一板块）：
- 快照成员都是对 近日/本周/下周/更长 做过方向表态、且目标周未整体过去的博主；行头 anchor 是系统按发帖日锚定的绝对周段（本周/下周 = 周一~周五日期段）或 近日/更长 原词。
- 同板块内真反向才算方向分歧、才可点出；清一色同向、或仅 1~2 人表态时直接陈述方向，不要为凑"分歧"而硬造。
- 同方向但操作取向相反（都看震荡调整、一个减仓、一个等待低吸）→ 写"共识下的操作分化"，不算方向对立。
- **日期纪律**：卡片日与 本周/下周 周段见【日期锚点】。波段目标不可能是 今天/明天 这类超短词——涉及某位博主的目标周**只能照抄该行 anchor 或引文日期**，禁止自己用 本周/下周/周X 推算；近日/更长 表态只讲方向逻辑、不补具体日期。板块整体可写 本周/下周，但必须对应【日期锚点】的周段；结尾操作句不必带日期。行头 `终点 MM-DD 收盘` 是系统算好的**验证终点**（该预测兑现/结算的时刻），**可照抄引用、禁止自行推算或改写**，不得把它写成别的日期。

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
        ep = r.get("endpoint")
        ep_txt = f"·终点 {ep:%m-%d} 收盘" if ep else ""
        lines.append(f"▍{b}：{r['stance']}" + (f"·{lab}" if lab else "") + ep_txt
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
