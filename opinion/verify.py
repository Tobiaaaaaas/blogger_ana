# -*- coding: utf-8 -*-
"""推送复核（Pillar C，2026-09-08）：对"本 tick 新标注且将上卡"的规范行做一次 LLM 复核。

报告侧（extract_signals_direction）早有 verify_signals（keep/fix/drop）+ runs 共识；推送侧单遍
裸奔却喂实时卡——鲁棒性倒挂。这里给推送补一道**轻量复核**：只复核「由本 tick 新帖产出、坍缩后
会真正改动卡面」的少数行（逐帖缓存下每 tick 量 = 实际改卡的新表态），复用报告侧 verify 的
keep/fix/drop 结构与主结论句 doctrine，字段用 canonical（idx/spec/horizon/quote 齐）。

- keep ：原样上卡。
- fix  ：按修正字段替换（quote 须逐字、horizon 须在该板白名单内且与 spec 自洽等，不满足 → 弃 fix 保原行）。
- drop ：该行不取信 → 由调用方对该帖行降权后重坍缩（让更早仍在窗口的有效行按路过语义续显）。
- 调用失败/超时/未评审 → 默认 keep 候选行（复核故障不吞正常行）。
"""
import logging

from . import ds, schema, text

log = logging.getLogger("opinion.verify")

REVIEW_SYSTEM_PROMPT = """你是金融内容复核助手。你会收到「一条将被推送的表态行」和它的出处帖子原文。请判断该行是否被帖子原文**明确支持**，只依据该帖原文判断，返回一个 JSON verdict。

## 行字段含义
- idx：该行预测对象指数（上证指数/上证50/沪深300/中证500/中证1000/创业板指/科创50/双创）
- horizon：卡面展示周期（今天/明天/近日/本周/下周/更长/未提）——未提 = 无日历时间词但方向落当前波段（2026-09-09 A4-4，与 PANEL_HORIZONS swing 白名单同口径）
- spec：计分周期档（today/t1/tN/week/nweek/month/d:日期…）
- 方向：多=看涨、空=看跌；quote：博主原话摘录（必须逐字来自帖子，可省略号跨段）；summary：一句话概括

## 判定要点
1. **主结论句 doctrine**：帖子若有明确主结论（方向+时段），行必须与之一致；疑问/假设/条件/风险/点位预演不能覆盖主结论句。若整帖只是状态描述/复盘回顾/转述他人/仓位状态自述/无明确方向（如窄幅震荡、方向待定）而没有对 idx 所指指数的明确方向预测 → **drop**。
2. **对象**：idx=上证指数 时主结论预测对象必须是 大盘/上证/沪指；若帖子实际只预测另一指数（按名称或现价带宽判断：创业板 3400 区、深成 13700 区、中证1000 约 6000、科创50 约 1500、上证50 约 2700）→ 可明确改指已跟踪指数则 **fix idx/quote**；指向不可跟踪指数/未提指数 → **drop**。
3. **周期/时间词**：horizon 与 quote 时间词须一致（明天→quote 含 明天/明日 或明确次日；本周→本周；近日→未来几天等）。quote 丢时间词却标 明天 → 能逐字补成载时间词的原文句则 **fix quote**（补原话勿改写）；无法逐字补 → **drop**。
4. **quote 逐字**：quote 必须逐字来自帖子（可 … 跨段）；改写/润色/拼凑/编造 → **fix** 为原文逐字片段；fix 后仍非逐字 → **drop**。
5. summary ≤50 字、忠于主结论。
6. **条件式与先A后B形态不硬凑 d（2026-09-09）**：行的方向若是从条件式（守/破/分水岭/"放量就…否则…"）或先A后B路径形态（冲高回落/高开低走/探底回升…）里压出来的 ±1，而帖内无独立**无条件**主结论 → **drop**；帖内有独立无条件主结论 → **fix** 摘要/引文到那部分（条件/形态只是背景，不承载 d）。
7. **净方向 vs 操作句 vs 状态句（2026-09-09）**：句首带形态词但后接**无条件净方向/收法承诺**（"反弹结束重新二次探底"→空、"低开高走收大阳"→多、"冲高回落不改波段向上"→波段向上）→ 属明确主结论，按主结论句 doctrine keep/fix，d 取净方向。原文是加减仓/清仓/止盈/重仓等**操作动作**（减/清/止盈→空，加/重/补/抄底→多）→ 方向成立，keep（无时间词的按无明确周期口径：horizon=未提 归波段）；原文只是仓位**状态**自述（"还剩4成""满仓持股"）却产了 d 行 → **drop**。

## 输出
只返回一个 JSON 对象：
{"verdict": {"action": "keep"|"fix"|"drop", "d": 1|-1, "s": 1|2, "idx": "...", "spec": "...", "horizon": "...", "quote": "(fix 时必填，逐字)", "summary": "(fix 时必填)", "reason": "一句话"}}
- action=keep：d/s/idx/spec/horizon 回填原值即可，quote/summary 可不给。
- action=drop：只给 action/reason。
无任何其他文字。"""


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def post_text(post, bodies=None, limit=1200):
    """复核喂给 LLM 的出处帖文本（标题/正文并列，与标注 render 同源 resolve_post）。"""
    title, body = text.resolve_post(post, bodies)
    body = text.truncate(body, limit=limit, style="middle")
    if title and body:
        return f"标题：{title}\n正文：{body}"
    return title or body or (post.get("content") or "").strip()


def _fix_valid(fix, board, full_text):
    """复核 fix 字段 → 规范化 fix dict 或 None（字段不合法/quote 非逐字/周期与该板不符 → 无效）。"""
    if not isinstance(fix, dict):
        return None
    d = _int(fix.get("d"))
    if d not in (1, -1):
        return None
    cat = "scored"
    spec = str(fix.get("spec") or "").strip()
    if not (schema.SPEC_RE.match(spec) and schema.spec_sane(spec)):
        return None
    idx = str(fix.get("idx") or "上证指数").strip()
    idx = schema.IDX_ALIAS.get(idx, idx)
    if idx not in schema.VALID_IDX:
        return None
    horizon = str(fix.get("horizon") or "").strip()
    if horizon not in schema.PANEL_HORIZONS.get(board, ()):
        return None
    if not schema.horizon_spec_ok(horizon, spec):
        return None
    s = _int(fix.get("s"))
    if s not in (1, 2):
        s = 1
    quote = (fix.get("quote") or "").strip()
    summary = (fix.get("summary") or "").strip()
    if not summary:
        return None
    if quote and not text.verbatim_in(quote, full_text):
        return None
    return {"d": d, "s": s, "idx": idx, "spec": spec, "cat": cat,
            "horizon": horizon, "quote": quote[:90], "summary": summary[:50]}


def _review_one(candidate, label):
    """candidate: {board, blogger, row(canonical), post_text, full_text} → (action, fix|None, reason|None)。

    action ∈ keep/fix/drop/err——err = 复核本身不可用（调用失败/结构异常/未知 action/fix 不合法），
    语义 = 默认保留候选行，但计为"未真正复核"，供日志区分。
    """
    row = candidate["row"]
    msg = (f"【博主】{candidate['blogger']}（{candidate['board']} 板候选行）\n"
           f"行：{row!r}\n\n出处帖子：\n{candidate['post_text']}")
    result, _raw = ds.call_json(None, REVIEW_SYSTEM_PROMPT, msg,
                                label or f"opinion:verify:{candidate['blogger']}")
    if result is None:
        return "err", None, "复核调用失败，默认保留候选行"
    v = result.get("verdict") if isinstance(result, dict) else None
    if not isinstance(v, dict):
        return "err", None, "verdict 结构异常，默认保留候选行"
    action = str(v.get("action") or "").strip()
    if action == "keep":
        return "keep", None, str(v.get("reason") or "")[:120]
    if action == "drop":
        return "drop", None, str(v.get("reason") or "")[:120]
    if action == "fix":
        fx = _fix_valid(v, candidate["board"], candidate["full_text"])
        if fx is not None:
            return "fix", fx, str(v.get("reason") or "")[:120]
        # fix 不合法（quote 非逐字/周期错板…）→ 不因复核方乱改吞掉已过确定性门的候选 → 保原行
        log.warning("  %s 复核 fix 字段不合法（quote 非逐字或周期与 %s 板不符），保留原行",
                    candidate["blogger"], candidate["board"])
        return "err", None, "fix 不合法，保留候选行"
    return "err", None, f"未知 action={action!r}，默认保留候选行"


def review_candidates(candidates, label=""):
    """对候选行逐条复核。candidates: [{board, blogger, row, post_text, full_text}, …]。

    返回 (decisions, stats)：decisions = [{board, blogger, action, fix, reason}]，
    action=err 表示复核不可用、调用方应按 keep 对待（保留候选行）；
    stats = {keep, fix, drop, err}。
    """
    stats = {"keep": 0, "fix": 0, "drop": 0, "err": 0}
    decisions = []
    for c in candidates:
        action, fix, reason = _review_one(c, label)
        stats[action] += 1
        decisions.append({"board": c["board"], "blogger": c["blogger"],
                          "action": action, "fix": fix, "reason": reason})
    return decisions, stats
