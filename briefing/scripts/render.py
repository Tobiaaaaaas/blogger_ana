# -*- coding: utf-8 -*-
"""飞书推送：板块卡片渲染 + webhook 发送。

自定义机器人 webhook：POST https://open.feishu.cn/open-apis/bot/v2/hook/<token>
卡为 msg_type=interactive（富文本分节）。心跳消息路径（v8 心跳卡/错误文本）与 v12 双板块
同卡、v8 全板共识卡等 LEGACY 已于 2026-09-09 C1 移除（git / archive 可恢复）。

v13（2026-09-03）：超短/波段拆两群两卡。每板块一张独立卡（标题含板块+时刻，
见 config.board_title），各推各群 webhook（webhook_for 读 config.WEBHOOK_ENV）——
webhook 未配置该板块按失败处理，**绝不回落** FEISHU_WEBHOOK_URL（防波段卡误发旧群）。
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from . import config

log = logging.getLogger("briefing")

BEIJING_TZ = timezone(timedelta(hours=8))
# 板块行 stance 只消费 多/空（坍缩只出方向行，中性已不入卡）；get(..., "") 兜底防未知值。
STANCE_EMOJI = {"多": "🔴", "空": "🟢"}
STANCE_TEXT = {"多": "看多", "空": "看空"}
# 行级周期词（spec，SKILL §3 周期词的板块展示口径）：每个博主观点行固定显示，
# 未提周期 → "周期未提"，绝不缺省。超短=今天/明天；波段=近日/本周/下周/更长/周期未提。
PERIOD_WORD = {"今天": "今天", "明天": "明天", "近日": "近日", "本周": "本周",
               "下周": "下周", "更长": "更长", "未提": "周期未提"}
HEADER_TEMPLATE = "blue"


def fmt_post_time(ts):
    """帖子的绝对时间标注：MM-DD HH:MM（北京时）。

    v12 起不再用 今日/昨日 相对速览——引文是昨天/前天的帖子，其相对词要靠
    真实日期才对得上（"昨天说的明天"）。一律按发帖真实日期标注。
    """
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts), tz=BEIJING_TZ)
    except (TypeError, ValueError, OSError):
        return ""
    return dt.strftime("%m-%d %H:%M")


# =====================================================================
# v13：webhook 路由 + 板块错误心跳（两群两卡）
# =====================================================================

def webhook_for(board_key):
    """本板块应推的飞书 webhook URL（config.WEBHOOK_ENV[key] 对应 env）。

    未配置 → 返回 None，调用方须按"该板块推送失败"处理；**绝不回落**
    FEISHU_WEBHOOK_URL——否则波段卡会误发到超短群。
    """
    env = config.WEBHOOK_ENV.get(board_key)
    url = os.environ.get(env) if env else None
    if not url:
        log.error("  webhook 未配置：env %s 缺失（板块 %s 不推送，也不回落旧群）", env, board_key)
    return url


def build_board_error_payload(err, board_key, date_str, hm):
    """某板块生成失败的文本心跳（走该板块自己的 webhook）。"""
    title = config.board_title(board_key, date_str, hm)
    return {
        "msg_type": "text",
        "content": {"text": f"⚠️ {title} 生成失败：{err}\n"
                            f"详情见服务器日志 briefing.log"},
    }


def post_webhook(payload, webhook_url=None, retries=3):
    """发送到飞书 webhook；返回 (ok, resp_text)。"""
    url = webhook_url or os.environ.get("FEISHU_WEBHOOK_URL")
    if not url:
        return False, "未配置 FEISHU_WEBHOOK_URL"
    last = ""
    for i in range(retries):
        try:
            r = requests.post(url, json=payload, timeout=20)
            body = r.text[:200]
            try:
                code = r.json().get("code")
                if code == 0:
                    return True, body
                last = f"飞书返回 code={code}: {body}"
            except Exception:
                last = f"非JSON响应 {r.status_code}: {body}"
        except Exception as e:
            last = f"请求异常: {e}"
        time.sleep(3 * (i + 1))
    return False, last


# =====================================================================
# 板块行渲染原语（_fmt_board_row/_board_section_lines/_chunk_lines）：供 v13 单板块卡
# （build_board_card_payload / build_minimal_card_payload）与 LEGACY 双板块版共用，
# 单一来源防漂移。
# =====================================================================

_MAX_MD_BYTES = 30000  # 单 markdown 元素上限粗估；超长按行拆成多段


def _fmt_board_row(name, row):
    """板块内单博主行（无编号）：标题行 + 重点原话(发帖时间) + 摘要。

    row 字段见 summarize：blogger/has_view/stance/horizon/anchor/summary/quote/
    quote_ts（anchor 由 resolve_anchors 日期锚定：超短=目标日 MM-DD；波段=周词+
    周日期段）。行头固定显示**行级周期词 spec**（绝不缺省，见 PERIOD_WORD）：
    超短行 = 今天/明天 并列锚定目标日（如 `看多 · 明天(09-04)`）；波段行 anchor 已
    含周词/周期词（本周 09-07~09-11 / 近日 / 更长）→ 直接沿用；周期未提（horizon=
    未提 / 无 anchor）→ 显示 `周期未提`，不再空着。

    2026-09-10（用户需求②）：行头再追加**验证终点与 spec 编码**（`· 终点 MM-DD 收盘
    · spec <code>`，由 resolve_anchors 算好的 endpoint 提供；无终点（long/无法推算）
    则省去终点段）——让每条推送自带"这句话按什么口径、什么时候被验证"。

    2026-09-10（用户：周期段冗余）：**有终点就不显示周期段**（超短的「今天/明天(MM-DD)」
    与终点恒同一天；波段「下周 09-14~09-18」的终点即该周最后一个交易日，同为重复陈述）
    ——行头统一为「方向 · 终点 MM-DD 收盘 · spec」，只保留这两个可核验标注。周期段仅在
    **无终点**（long/无法推算）时回落显示，避免行头彻底失去日期/周期。
    """
    emoji = STANCE_EMOJI.get(row.get("stance"), "")
    stext = STANCE_TEXT.get(row.get("stance"), row.get("stance") or "")
    line1 = f"{emoji} **{name}** {stext}"
    period = PERIOD_WORD.get(row.get("horizon")) or "周期未提"
    anchor = row.get("anchor")
    ep = row.get("endpoint")
    # 2026-09-10（用户）：超短行的「今天(09-10)/明天(09-10)」与验证终点是**同一天**
    # （spec today/t1 的终点定义即发帖日/次日收盘），纯冗余 → 有终点时不再显示该段，
    # 行头直接给「方向 · 终点 MM-DD 收盘 · spec」，终点+spec 已完整表达"哪天验证、什么口径"。
    # 仅当**无终点**（long/无法推算）时回落显示周期词，避免行头彻底失去日期。
    if ep:
        line1 += f" · 终点 {ep:%m-%d} 收盘"
    else:
        # 无终点（long / 无法推算）才回落显示周期段，避免行头彻底失去日期/周期
        if anchor:
            # 超短兜底：anchor 只是目标日 MM-DD，词+日期并列；波段：anchor 已含周词/
            # 周期词（本周/下周/近日/更长）→ 直接用 anchor（避免“下周 · 本周 …”式重复/矛盾）
            label = f"{period}({anchor})" if period in ("今天", "明天") else anchor
        else:  # 周期未提 / 无 anchor 的历史行 → 固定给周期词，未提也给 周期未提
            label = period
        if label:
            line1 += f" · {label}"
    if row.get("spec"):
        line1 += f" · spec {row['spec']}"
    lines = [line1]
    if row.get("quote"):
        t = fmt_post_time(row.get("quote_ts"))
        lines.append(f"　重点原话：“{row['quote']}”" + (f"（{t}）" if t else ""))
    if row.get("summary"):
        lines.append(f"　摘要：{row['summary']}")
    return "\n".join(lines)


def _board_section_lines(board_key, rows, counts):
    """单个板块渲染块序列（v11）：计数头行 + 按名单序的成员行 / 空板块提示。

    rows: 该板块 {博主: row}（仅 has_view）；counts: board_counts[board_key]。
    同一块序列同时供卡 payload 与 dry-run 预览（run_briefing._preview_text）调用，
    单一来源防漂移。未表态成员不占行。
    """
    meta = config.BOARD_META[board_key]
    c = counts or {}
    head = (f"{meta['emoji']} **{meta['label']}**"
            f" · {c.get('bull', 0)}多/{c.get('bear', 0)}空"
            f"（{c.get('shown', 0)}/{c.get('members', 0)} 表态）")
    lines = [head]
    shown = 0
    for name in config.PANELS[board_key]:
        row = rows.get(name)
        if not row:
            continue
        lines.append(_fmt_board_row(name, row))
        shown += 1
    if not shown:
        lines.append(meta["empty_note"])
    return lines


def _chunk_lines(lines, cap=_MAX_MD_BYTES):
    """行序列按 UTF-8 字节上限切成若干块（每块单独成 markdown 元素）。"""
    if not lines:
        return []
    joined = "\n\n".join(lines)
    if len(joined.encode("utf-8", "replace")) <= cap:
        return [joined]
    chunks, cur, cur_bytes = [], [], 0
    for ln in lines:
        nb = len(ln.encode("utf-8", "replace")) + 2
        if cur and cur_bytes + nb > cap:
            chunks.append("\n\n".join(cur))
            cur, cur_bytes = [], 0
        cur.append(ln)
        cur_bytes += nb
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def _board_card_elements(board_key, rows, counts, market_text, window_txt, summary_text):
    """单板块卡主体元素（覆盖→行情→本板块名单→🧭 本板块总结）。

    与 LEGACY 双板块版不同：只渲染 board_key 一块名单（_board_section_lines 单块）、
    总结降级用单板块 format_board_count —— 杜绝双板块计数混入单板块卡。
    """
    elements = []
    if window_txt:
        elements.append({"tag": "note", "elements": [
            {"tag": "plain_text", "content": f"🕐 覆盖：{window_txt}"}]})
    elements.append({"tag": "markdown", "content": f"📈 {market_text}"})
    elements.append({"tag": "hr"})
    for chunk in _chunk_lines(_board_section_lines(board_key, rows, counts)):
        elements.append({"tag": "markdown", "content": chunk})
    elements.append({"tag": "hr"})
    if not summary_text:
        summary_text = f"多空版图：{config.format_board_count(board_key, counts or {})}"
    elements.append({"tag": "markdown", "content": f"🧭 {summary_text}"})
    return elements


def build_board_card_payload(board_key, rows, counts, market_text, date_str, hm,
                             window_txt="", summary_text=""):
    """v13 单板块主卡：header(板块+时刻) + 覆盖窗口 + 行情 + 本板块名单 + 🧭 本板块总结。

    rows = 该板块 {博主: row}（仅 has_view，已 resolve_anchors）；counts = 该板块单键
    计数 {bull,bear,shown,members}；hm='HH:MM'（与 date_str 一起进标题，config.board_title）。
    summary_text 空 → 降级为单板块计数行。
    """
    elements = _board_card_elements(board_key, rows, counts, market_text, window_txt, summary_text)
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"template": HEADER_TEMPLATE,
                       "title": {"tag": "plain_text",
                                  "content": config.board_title(board_key, date_str, hm)}},
            "elements": elements,
        },
    }


def build_minimal_card_payload(board_key, counts, market_text, date_str, hm,
                               window_txt="", note_text=""):
    """v13 单板块零方向最小卡：确认存活 + 本板块计数一行，不渲染空名单。

    note_text 区分空档原因（近窗口无人发帖 / 有人发帖但无该板块方向观点）。
    """
    counts_txt = config.format_board_count(board_key, counts or {})
    elements = []
    if window_txt:
        elements.append({"tag": "note", "elements": [
            {"tag": "plain_text", "content": f"🕐 覆盖：{window_txt}"}]})
    elements.append({"tag": "markdown", "content": f"📈 {market_text}"})
    if note_text:
        elements.append({"tag": "markdown", "content": f"💤 {note_text}"})
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": counts_txt}]})
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"template": HEADER_TEMPLATE,
                       "title": {"tag": "plain_text",
                                  "content": config.board_title(board_key, date_str, hm)}},
            "elements": elements,
        },
    }
