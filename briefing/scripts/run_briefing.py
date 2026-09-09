# -*- coding: utf-8 -*-
"""简报编排器 v17：超短/波段两卡两群 · 节奏统一 · 单趟分层抽取 · 行缓存增量复用 · 交易日窗口。

v17（2026-09-08 共享模块委派）：分层判定由 LAYER prompt 迁进顶层 opinion/——extract_layers
内部改走 opinion 单一共享逐帖标注（ANNOTATION_SYSTEM_PROMPT，rows 规范行）+ collapse_board
确定性坍缩；窗口读帖委派 opinion.posts（_read_window_posts）。两板两卡行为与 v16 同形（路过
不抹旧行/取最新等散文意图落进代码，见 summarize.extract_layers / opinion.annotate 注释）。
v16（2026-09-08）：行抽取由"两板各自抽一层"改为**单趟分层分解**——请求板块的博主合集
一次 extract_layers（LAYER_SYSTEM_PROMPT）把每帖按预测周期（analyze-blogger skill §3 spec
语义）分层归位（今天/明天→超短层、2日+可计分→波段层、远期/中长期/无时限点位→丢弃），
再逐板锚定/计数/推卡；杜绝"预测周期只到明天的帖被归成波段"类误归（2026-09-08 子房论市）。
行为收敛：某博主单趟抽取失败 → 该轮两板同时不显示（原先两板各自独立、可能一板有另一板无）。

节奏与调度：
- **交易日**两板块同节奏：09:00–15:00 每 30 分钟（含午休与 09:00 盘前，13 档）+ 16:00–22:00
  每整点（7 档）→ 每档推 超短+波段 各一张。墙钟命中 config.in_trading_grid 才跑；
  门禁在抓取/锁之前（伪 tick 如 15:30/22:30 与 StartWhenAvailable 离节奏补跑
  → log 后 exit 0，不碰锁不碰状态）。
- **非交易日**只推波段卡：09:00–21:00 每 3 小时（09/12/15/18/21，config.in_restday_grid）——
  周末/节假日博主常发下周观点，波段卡照常出；超短群周末静默。
- 单趟抽取后逐板块 锚定→计数→收敛总结，各推各群（render.webhook_for 读
  config.WEBHOOK_ENV；该板块 webhook 缺失按失败处理，**不回落** FEISHU_WEBHOOK_URL——
  防波段卡误发超短群）。
- 窗口（v14 交易日口径；v15 波段 3→5）：超短 = 前一交易日 00:00 至 now、波段 = 前 5 个
  交易日 00:00 至 now（config.WINDOW_TRADING_DAYS；起点用 calendar.n_trading_days_ago，
  非自然日相减）。由此周一早晨窗口含上周五帖（消除 v13 自然日取舍）。
- 每档必发：板块有方向观点→全卡 + 本板块收敛总结；空→单板块最小卡（区分窗口
  无人发帖 / 有人发帖但无该板块方向观点）；内容没变也发；不加 🆕 标记。

状态 / 增量（2026-09 v13）：
- fetched_at（爬虫水位：抓取+merge 完成即写，不等待推送成败）与 last_run（推送水位：
  全板块推完才写）分离——避免推送失败下一档重抓已抓过的增量。
- rows_cache.json（行标注缓存 v5，opinion.cache，**逐帖**）：每博主每帖按 (post_id, 内容hash)
  键存各自规范行——每档只标注窗口里新出现/正文回填变 content 的帖（该博主新帖合成一个子批一次
  调用），旧帖（含跨交易日窗口滑动重叠帖）永不重评分；坍缩每 tick 确定性重算（quote_ts≥该层
  窗口下界 门，只取本次窗口帖的行）。版本或共享 prompt 指纹任一不符 → 整缓存作废全量重抽。
- 历史文件名 {wall:%Y%m%d}_{HHMM}_{board_key}.json（09:30 同秒双卡靠 board_key 互不覆盖；
  同档重跑幂等覆盖）。

用法：
  python -m briefing.scripts.run_briefing --push                          # 墙钟调度（auto 门禁+自动判板块）
  python -m briefing.scripts.run_briefing --push --time 09:30 --board both # 暖场/手动补推
  python -m briefing.scripts.run_briefing --dry-run --time 11:00 --board swing --no-scrape
  python -m briefing.scripts.run_briefing --dry-run --time 09:30 --board short --no-scrape --skip-calendar
  python -m briefing.scripts.run_briefing --push --board short --max-bloggers 3   # 冒烟

--time 只覆盖"决策时刻"（窗口/锚定/标题/总结措辞）；state/历史文件名/水位一律用真实
墙钟 wall —— 防止模拟档回拨爬虫水位或把假日期写进历史。
Windows：双任务 BriefingDay（Daily 09:00 + 30min×6h → 09:00–15:00）与 BriefingEvening
（Daily 16:00 + 1h×6h → 16:00–22:00）运行 --push，日型/节奏由代码门禁区分（见 DEPLOY.md）。
"""
import argparse
import atexit
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from . import calendar, config, market, paths, render, scrape_merge, state
from .summarize import (board_counts, extract_layers, resolve_anchors,
                        summarize_board)

# 2026-09-08 共享模块重构：窗口读帖委派 opinion.posts（同源读帖/可读性过滤）。summarize 导入时
# 已兜底把 REPO_ROOT 补进 sys.path（运行目录非父仓根时），此处再补一次保证 o_posts 可用。
try:
    from opinion import posts as o_posts  # noqa: E402
except ImportError:
    if not any(os.path.abspath(p) == os.path.abspath(paths.REPO_ROOT) for p in sys.path):
        sys.path.insert(0, paths.REPO_ROOT)
    from opinion import posts as o_posts  # noqa: E402

log = logging.getLogger("briefing")

WD = ["一", "二", "三", "四", "五", "六", "日"]
BEIJING_TZ = timezone(timedelta(hours=8))  # 时段/日期/窗口全用北京时，独立于宿主机时区


def _setup_logging():
    paths.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(paths.LOG_FILE, encoding="utf-8")],
    )


def _date_str(now: datetime) -> str:
    return f"{now.strftime('%m-%d')} 周{WD[now.weekday()]}"


def _parse_hhmm(s):
    """'HH:MM' → (h, m)；非法退出。"""
    try:
        h, m = s.strip().split(":", 1)
        return int(h), int(m)
    except Exception:
        raise SystemExit(f"--time 需 HH:MM 格式（收到 {s!r}）")


def _explicit_boards(word):
    if word == "short":
        return ["short"]
    if word == "swing":
        return ["swing"]
    if word == "both":
        return ["short", "swing"]
    raise SystemExit(f"--board 需 auto|short|swing|both（收到 {word!r}）")


def _resolve_boards(args, wall):
    """返回应推板块列表与决策时刻 now。auto 不在节奏 → exit 0（在锁/抓取之前）。

    now = wall，除非给 --time（只改决策时刻，改日期仍用墙钟当天）；模拟档同样过门禁，
    使 --time 15:30 / 22:30 / 10:13 等 off-grid（或非交易日 10:00）时刻也能复现"跳过"路径。
    """
    now = wall
    if args.time:
        h, m = _parse_hhmm(args.time)
        now = wall.replace(hour=h, minute=m, second=0, microsecond=0)
    if args.board and args.board != "auto":
        # 显式指定板块：不门禁（测试/暖场用）；非交易日强制真推危险 → 拒绝并 exit 0。
        if not (args.skip_calendar or calendar.is_trading_day(now.date())):
            if args.push:
                log.warning("非交易日 %s 强制 --board %s：拒绝真实推送", now.date(), args.board)
                raise SystemExit(0)
            log.info("非交易日 %s 强制 --board %s：dry-run 放行测试", now.date(), args.board)
        return _explicit_boards(args.board), now
    # auto：交易日两板块同节奏；非交易日只推波段（3 小时节奏）
    trading = True if args.skip_calendar else calendar.is_trading_day(now.date())
    if trading:
        if not config.in_trading_grid(now):
            log.info("时刻 %s 不在交易日推送节奏"
                     "（09:00–15:00 每30分 / 16:00–22:00 每整点），跳过",
                     now.strftime("%H:%M"))
            raise SystemExit(0)
    else:
        if not config.in_restday_grid(now):
            log.info("非交易日（%s）时刻 %s 不在 3 小时节奏（09:00–21:00），跳过",
                     now.date(), now.strftime("%H:%M"))
            raise SystemExit(0)
    return config.due_boards(trading), now


def _beijing_midnight_epoch(d) -> int:
    """某日期（北京时）00:00 的 epoch 秒。作展示窗口下界：下界当日 00:00 ≤ 帖子发帖时刻。"""
    return int(datetime(d.year, d.month, d.day, tzinfo=BEIJING_TZ).timestamp())


def _window_start_ts(key, now):
    """某板块展示窗口下界（v14 交易日口径）= 前一/前N个交易日 00:00（北京时 epoch 秒）。

    N = config.WINDOW_TRADING_DAYS[key]；起点日由 calendar.n_trading_days_ago 按交易日
    回看得到，上界仍 ≤ now。周末/盘前模拟（now 非交易日）按最近交易日取参考日。
    """
    start = calendar.n_trading_days_ago(now.date(), config.WINDOW_TRADING_DAYS[key])
    return _beijing_midnight_epoch(start)


def _window_txt(key, now):
    """某板块覆盖窗口说明（进卡/总结）。如 '超短板块 前1个交易日到现在（09-03 起）'。"""
    start = calendar.n_trading_days_ago(now.date(), config.WINDOW_TRADING_DAYS[key])
    return (f"{config.BOARD_WORD[key]}板块 前{config.WINDOW_TRADING_DAYS[key]}个交易日"
            f"到现在（{start:%m-%d} 起）")


def _read_window_posts(blogger, start_ts, now_ts):
    """现读合并主文件，返回该博主窗口内 [start_ts, now_ts] 的可读帖（新→旧）。

    2026-09-08 委派 opinion.posts.read_window_posts——[视频帖]/无正文短帖过滤、publish_time
    新→旧排序、ROWS_MAX_POSTS 截断与报告/离线抽取共用同源读帖；下标即引文来源语义不变。
    """
    return o_posts.read_window_posts(blogger, paths.POSTS_DIR, start_ts, now_ts,
                                     limit=config.ROWS_MAX_POSTS)


def _collect_layer_work(now, boards):
    """单趟分层抽取的前置：为请求板块的博主合集读【最大窗口】帖 → 分层 work。

    每位博主 posts = 其所属且本趟请求板块中的最大窗口（双板块→波段 5 交易日全集；仅
    超短→1 交易日）内最新 ROWS_MAX_POSTS 条可读帖（新→旧），boards = 该博主实际所属
    的请求板块（决定 LAYER prompt 只评哪些层；超短窗标记按 short 窗口下界在 extract_
    layers 内做，不必在此区分）。
    返回 (work, posters_by_board, starts)：
      posters_by_board[层] = 该层窗口内有帖的博主（空板文案区分"无人发帖 / 有人但无该
      板块方向观点"）；starts[层] = 该层窗口下界 epoch（extract_layers 缓存过期复查用）。
    """
    starts = {b: _window_start_ts(b, now) for b in boards}
    now_ts = int(now.timestamp())
    order, seen = [], set()
    for b in boards:                        # 双板块博主合集去重：short 名单序 + swing 新增
        for name in config.PANELS[b]:
            if name not in seen:
                seen.add(name)
                order.append(name)
    work, posters = {}, {b: set() for b in boards}
    for name in order:
        my_boards = [b for b in boards if name in config.PANELS[b]]
        start = min(starts[b] for b in my_boards)          # 最大窗口覆盖其全部所属层
        win = _read_window_posts(name, start, now_ts)
        if not win:
            continue
        work[name] = {"posts": win, "boards": my_boards}
        for b in my_boards:
            if any((p.get("publish_time") or 0) >= starts[b] for p in win):
                posters[b].add(name)       # 该层窗口内有帖（空板区分文案用）
    return work, posters, starts


def _migrate_state_v2(st):
    """旧 v8 state（recent_views/board_prev/previous）→ 新形状：只留 last_run/last_slot/seen。

    幂等，仅改内存态；落地由 _run 末尾统一原子写。
    """
    changed = False
    for k in ("recent_views", "board_prev", "previous"):
        if k in st:
            del st[k]
            changed = True
    return changed


def _migrate_state_v3(st):
    """v12→v13：爬虫水位 fetched_at 回填。幂等，仅改内存态。

    旧版只有 last_run（爬虫 since 与推送同源）：首跑 v13 若无 fetched_at 而 last_run
    非空 → 回填 fetched_at=last_run，既不漏抓 last_run 之前的旧帖也不重抓太多。
    """
    changed = False
    if not st.get("fetched_at") and st.get("last_run"):
        st["fetched_at"] = st["last_run"]
        changed = True
    return changed


def _save_history(wall, hm, board_key, payload, preview):
    """历史文件名 {wall:%Y%m%d}_{HHMM}_{board_key}.json（HHMM 无冒号，Windows 文件名安全）。"""
    fn = f"{wall:%Y%m%d}_{hm.replace(':', '')}_{board_key}.json"
    with open(os.path.join(paths.BRIEFINGS_HIST_DIR, fn), "w", encoding="utf-8") as f:
        json.dump({"date": f"{wall:%m-%d} 周{WD[wall.weekday()]}", "hm": hm,
                   "board": board_key, "payload": payload, "preview": preview},
                  f, ensure_ascii=False, indent=2)
    return os.path.join(paths.BRIEFINGS_HIST_DIR, fn)


def _pid_alive(pid):
    """跨平台进程存活探测。注意：Windows 上 os.kill(pid,0) 是『终止进程』而非探测，绝不能用于 Windows。"""
    if not pid or pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        pass
    if os.name == "nt":
        return False  # 无 psutil 时无法安全探测 → 交给 3h mtime 兜底接管
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_lock():
    """单实例锁：上一轮未结束则跳过；被杀/断电残留的锁自动接管（中断恢复）。

    规则：① 锁里 pid 存活且锁未超时 → 有进程在跑，跳过本轮；
          ② pid 已死（中断残留）→ 接管；
          ③ 锁超过 3 小时（pid 可能被复用）→ 无条件接管。
    """
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    lock = paths.LOCK_FILE
    try:
        if os.path.exists(lock):
            old_pid = 0
            try:
                old_pid = int(open(lock, encoding="utf-8").read().strip() or 0)
            except Exception:
                pass
            try:
                age_min = (time.time() - os.path.getmtime(lock)) / 60
            except Exception:
                age_min = 0
            if old_pid > 0 and _pid_alive(old_pid) and age_min < 180:
                log.info("简报进程仍在运行（pid=%s），跳过本轮", old_pid)
                return False
            log.info("接管残留锁（pid=%s，距今 %.0f 分钟）", old_pid, age_min)
        with open(lock, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        log.warning("锁操作异常 %s，放行本轮", e)
        return True


def _release_lock():
    try:
        if os.path.exists(paths.LOCK_FILE):
            os.remove(paths.LOCK_FILE)
    except Exception:
        pass


def _preview_lines(board_key, counts, rows, mkt_text, date_str, hm,
                   window_txt="", summary_text=""):
    """dry-run 预览：单板块标题 + 覆盖 + 行情 + 名单（与卡同构，_board_section_lines 单源）。"""
    from .render import _board_section_lines
    lines = [config.board_title(board_key, date_str, hm)]
    if window_txt:
        lines.append(f"🕐 覆盖：{window_txt}")
    lines.append("📈 " + mkt_text)
    lines.append("")
    lines.extend(_board_section_lines(board_key, rows, counts))
    if summary_text:
        lines.append("")
        lines.append(f"🧭 {summary_text}")
    return "\n".join(lines)


def _process_board(key, anchored, counts, posters, mkt_text, now, date_str, hm):
    """单板块推送件组装：已单趟抽取并锚定的行 + 计数 → 全卡/最小卡。返回 (payload, preview)。

    抽取（含读帖）在 _run 步骤 2.5 一次性完成（extract_layers 出两层行），resolve_anchors
    在 _run 步骤 3 已把该板块行重锚（目标日随卡片日变）；本函数只做计数日志与全卡/最小卡
    组装。空板区分 近窗口无人发帖 / 有人但无该板块方向观点（posters 由 _collect_layer_work
    给出）。
    """
    c = counts[key]
    log.info("[%s] %d多/%d空（%d/%d 表态）", key, c["bull"], c["bear"], c["shown"], c["members"])

    win_txt = _window_txt(key, now)
    if c["shown"] > 0:
        summary_text = summarize_board(key, anchored, c, mkt_text, date_str,
                                       window_txt=win_txt, now=now)
        payload = render.build_board_card_payload(key, anchored, c, mkt_text, date_str, hm,
                                                  window_txt=win_txt, summary_text=summary_text)
    else:
        summary_text = ""
        note = (f"前{config.WINDOW_TRADING_DAYS[key]}个交易日起窗口内无博主发帖"
                if not posters.get(key)
                else config.BOARD_META[key]["empty_note"])
        payload = render.build_minimal_card_payload(key, c, mkt_text, date_str, hm,
                                                    window_txt=win_txt, note_text=note)
    preview = _preview_lines(key, c, anchored, mkt_text, date_str, hm,
                             window_txt=win_txt, summary_text=summary_text)
    return payload, preview


def _run(args):
    paths.load_env()
    _setup_logging()
    # Windows 控制台默认 GBK，print(preview) 遇 emoji 会崩（dry-run 崩在落盘之后；push 不走 print）。
    # 重配 stdout 为 UTF-8 + 替换错误 → 重定向到文件得干净 UTF-8，交互控制台也不崩。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    wall = datetime.now(BEIJING_TZ)          # 真实墙钟：状态/历史名/水位一律用它
    boards, now = _resolve_boards(args, wall)  # 决策时刻：窗口/锚定/标题/措辞
    date_str = _date_str(now)
    hm = now.strftime("%H:%M")
    log.info("== 简报 v17(双卡·共享标注) %s %s 板块=%s ==", date_str, hm, ",".join(boards))

    if not _acquire_lock():
        return 0  # 已有进程在跑（防重叠）
    atexit.register(_release_lock)  # 正常退出删锁；被杀/断电残留由下一轮自动接管

    st = state.load_state()
    _migrate_state_v2(st)  # v8 残留键清理
    _migrate_state_v3(st)  # v13：无 fetched_at → 回填旧 last_run（内存态，落盘在末尾）

    # 1) 一次抓取（since=爬虫水位 fetched_at；无则回退最旧板块窗口下界）。
    #    merge 完成即写 fetched_at=wall——本档推送成败不影响下一档增量下界。
    if args.no_scrape:
        log.info("--no-scrape：不抓取，直接读已合并主文件")
    else:
        since_str = st.get("fetched_at")
        if not since_str:
            oldest = min(_window_start_ts(k, now) for k in config.PANEL_KEYS)
            since_str = datetime.fromtimestamp(oldest, tz=BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
        log.info("爬虫增量 since=%s", since_str)
        results, errors = scrape_merge.fetch_all_new_posts(
            config.ALL_BLOGGERS, since_str, max_bloggers=args.max_bloggers,
            per_timeout=args.timeout, workers=args.workers)
        if errors:
            log.warning("本轮抓取失败博主：%s", errors)
        if args.push:
            st["fetched_at"] = wall.strftime("%Y-%m-%d %H:%M")
            state.save_state(st)
            log.info("爬虫水位已推进 fetched_at=%s", st["fetched_at"])

    # 2) 行情一次（全板块共用同一份）
    quotes = market.fetch_quotes()
    mkt_text = market.market_line(quotes)
    log.info("行情: %s", mkt_text)

    # 2.5) 单趟分层抽取（v17 委派）：请求板块的博主合集**一次** DeepSeek 逐帖标注（opinion
    #      共享 ANNOTATION prompt → 规范行），再按层确定性坍缩（opinion.annotate.collapse_board：
    #      层窗口下界门 + horizon 白名单 + spec↔horizon 自洽；杜绝"明天帖被归成波段"式误归，
    #      路过帖不抹旧行），随后逐板块重锚/计数在 3) 做。单趟保证同一博主两层口径一致，不出
    #      现"同帖被两板各自独立判层判法打架"；某博主整趟标注失败 → 回退其窗口内已缓存旧行
    #      续显（无旧行才该轮不显示不计数）——见 2026-09-08 v16/v17/v18 记录。
    rows_raw, posters, extract_failed = {}, {}, False
    try:
        if boards:
            work, posters, starts = _collect_layer_work(now, boards)
            rows_raw, errs = extract_layers(work, starts=starts)
            if errs:
                log.warning("分层抽取标注失败博主（回退窗口内已缓存旧行，无旧行才该轮不显示不计数；"
                            "未写缓存下档重试）：%s", errs)
    except Exception as e:
        log.exception("单趟分层抽取异常：%s", e)
        extract_failed = True

    # 3) 逐板块 锚定→计数→组装推卡 + 各自 webhook 推送；单板块异常不拖垮另一板块。
    ok_all = True
    for key in boards:
        try:
            if extract_failed:
                raise RuntimeError("单趟分层抽取异常，见上文 log")
            anchored = resolve_anchors({key: (rows_raw.get(key) or {})}, now)[key]
            counts = board_counts({key: anchored})
            payload, preview = _process_board(key, anchored, counts, posters,
                                              mkt_text, now, date_str, hm)
        except Exception as e:
            log.exception("[%s] 板块处理异常：%s", key, e)
            if args.push:
                url = render.webhook_for(key)
                if url:
                    render.post_webhook(
                        render.build_board_error_payload(str(e), key, date_str, hm),
                        webhook_url=url)
                else:
                    log.error("[%s] 板块异常且未配置 webhook，无错误心跳", key)
            ok_all = False
            continue

        if args.push:
            url = render.webhook_for(key)
            if url is None:
                ok, resp = False, f"未配置 {config.WEBHOOK_ENV[key]}（不回落旧群）"
            else:
                ok, resp = render.post_webhook(payload, webhook_url=url)
                if not ok:
                    render.post_webhook(
                        render.build_board_error_payload(resp, key, date_str, hm),
                        webhook_url=url)
            log.info("[%s] 推送 %s: %s", key, "成功" if ok else "失败", resp)
            ok_all = ok_all and ok
            fp = _save_history(wall, hm, key, payload, resp if ok else "")
            log.info("[%s] 历史已存 %s", key, fp)
        else:
            fp = _save_history(wall, hm, key, payload, preview)
            print(preview)
            print("\n[预览已存]", fp)
            print("[dry-run 未推送、未改状态]")
            ok_all = ok_all and True

    # 4) 全板块推完推进推送水位（板块级失败已发错误心跳；下一档不再重发同一批增量）
    if args.push:
        st["last_run"] = wall.strftime("%Y-%m-%d %H:%M")
        st["last_slot"] = ",".join(boards)
        state.save_state(st)
        log.info("推送水位已推进 last_run=%s（boards=%s）", st["last_run"], st["last_slot"])
    return 0 if ok_all else 1


def main():
    ap = argparse.ArgumentParser(description="超短/波段 双群速览卡 → 飞书（v16 单趟分层抽取）")
    ap.add_argument("--push", action="store_true", help="真实推送到飞书并推进状态（调度用）")
    ap.add_argument("--dry-run", action="store_true", help="只落盘预览，不推送、不改状态")
    ap.add_argument("--time", default="", help="模拟决策时刻 HH:MM（跳过墙钟，只影响窗口/锚定/标题；不加则用墙钟）")
    ap.add_argument("--board", default="auto",
                    help="auto|short|swing|both（auto=按墙钟判板块；显式=强制，仅供测试/暖场）")
    ap.add_argument("--no-scrape", action="store_true", help="不爬取，直接读已合并主文件（试跑用）")
    ap.add_argument("--skip-calendar", action="store_true",
                    help="忽略交易日历，把今天当交易日跑（仅 dry-run 冒烟用）")
    ap.add_argument("--max-bloggers", type=int, default=None, help="只抓前 N 位博主（冒烟）")
    ap.add_argument("--timeout", type=int, default=240, help="单博主爬虫超时（秒）")
    ap.add_argument("--workers", type=int, default=5, help="博主并行抓取数（默认 5；1=串行）")
    args = ap.parse_args()
    if not args.push and not args.dry_run:
        args.dry_run = True
    sys.exit(_run(args))


if __name__ == "__main__":
    main()
