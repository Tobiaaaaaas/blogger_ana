# -*- coding: utf-8 -*-
"""逐帖标注编排 + 确定性坍缩（共享模块的"提取观点"步骤）。

- render_batch    ：共享标注输入格式（标题正文并列，微帖只显一次）——推送/报告两端统一
- annotate_blogger：一位博主一组帖一次 DeepSeek 调用（共享 ANNOTATION prompt）→ 规范行
- collapse_board  ：把窗口内规范行**确定性**坍缩成某博主某层最新表态行（v16 由 LAYER prompt
  的"窗口判层/路过/取最新/quote 归属"散文承担——2026-09-08 子房/诸葛 12:00 曾违反路过规则，
  坍缩进代码后按规则意图顺带纠正），只认 quote_ts≥该层窗口下界 的行（等效原【超短窗内】门）。

规范行（to_canonical）：模型行 + 系统回填 pub/quote_ts/post_id/blogger。字段校验与报告侧
normalize_signal 同向（非法即弃，不静默）；长度/相对词剥离属系统兜底（报告侧 normalize 再
按计分口径裁剪 summary，本层只 cap 50——报告保留原话相对时间词，推送在 collapse 时剔除）。
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from . import ds, prompts, schema, text

log = logging.getLogger("opinion.annotate")

_BEIJING = timezone(timedelta(hours=8))

# 推送板只认上证观点：行主结论句点名他指时，按字段字面量门放行会把科创50主句错推成上证卡
# （2026-09-09 衡山/诸葛两卡复盘）。_SH_ALIAS 之外的指数名视为"他指"。注意上证50/沪深300
# 等虽带"上证/沪深"字样，仍是与上证指数并列的他指对象。
_OTHER_IDX_TOKENS = ("科创50", "科创100", "科创板", "创业板指", "创业板", "创指", "双创",
                     "上证50", "沪深300", "中证500", "中证1000", "北证50", "北证")
_SH_ALIAS_RE = re.compile(r"上证指数|上证|沪指|大盘|A股|两市|综指")
_DIR_WORD_RE = re.compile(r"看空|看多|看涨|看跌|偏空|偏多|下探|破位|回补|补缺|站上|目标|"
                          r"回落|企稳|跌破|失守|中阴")


def _idx_object_conflict(row):
    """idx=上证指数 的行，其主结论（summary+quote）是否自证对象是他指。

    判定：蒸馏文本点名任一他指（科创50/创业板指/上证50/沪深300/…）**且全文无上证系别称**
    （上证/沪指/大盘/A股/两市/综指）**且带方向词** → 该行主结论句不是上证观点，仅因字段
    字面量 idx=上证指数 才混入推送。返回命中的他指 token（供 loud log），无冲突返回 None。
    带上证别称的文本（如"科创50领跌拖累上证明日走弱看空"）视上证为主句对象，放行——
    只挡"摘要自证他指、毫无上证指向"的自相矛盾行，不做句法级猜测。
    注意本函数**不查行的 idx 字段**（调用方须先保证 idx=上证）；对整批行筛矛盾用
    conflict_rows()。
    """
    text_ = " ".join(str(x or "") for x in (row.get("summary"), row.get("quote")))
    if not text_:
        return None
    hit = next((t for t in _OTHER_IDX_TOKENS if t in text_), None)
    if hit is None or _SH_ALIAS_RE.search(text_) or not _DIR_WORD_RE.search(text_):
        return None
    return hit


def conflict_rows(rows):
    """rows 里 idx=上证 但主结论点名他指且无上证指向的自相矛盾行（[2026-09-09 主结论对象门）。

    2026-09-09 衡山/诸葛复盘后该门由「坍缩终态弃行」上移为「标注质量门」：
    - annotate_blogger 拒收这类行入缓存 + 带方向纠错重试（有上证观点→重选上证句；只谈他指→
      idx 改真实指数）——否则 idx=科创50 的合法行（摘要点名科创50 是自洽的）会被误伤，故先滤
      idx=上证指数；
    - extract_layers 缓存自愈：门上线前已写入缓存的矛盾旧帖 → 作废整帖重抽恢复；
    - collapse_board 只留渲染底限：无论行来自何处，矛盾行永不上上证卡（主结论对象不是上证）。

    返回命中的行列表（供上游判定该帖需纠错重抽），无 → []。行内既有点名他指又有上证别称的
    （如"科创50领跌拖累上证明日走弱看空"，上证才是主句对象）不算矛盾。
    """
    return [r for r in (rows or [])
            if (str(r.get("idx") or "上证指数") == "上证指数" and _idx_object_conflict(r))]


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _quote_date(ts):
    """quote_ts → 北京时自然日（无/非法 → None）。"""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), _BEIJING).date()
    except (OSError, OverflowError, ValueError, TypeError):
        return None


def _nweek_first_is_next_session(qd, cal):
    """spec=nweek_first（下一自然周首个交易日）是否 == 发帖日之后首个交易日。

    仅周五~周日发帖成立：周五说"下周一"、周末展望周一 → 目标就是下一交易日（超短）；
    周一~周四说"下周一"则隔了数日，仍是波段。cal 需暴露 next_trading_day(date)。
    """
    days = (7 - qd.weekday()) % 7 or 7          # 发帖日之后下一个自然周一
    nxt_mon = qd + timedelta(days=days)
    first = cal.next_trading_day(nxt_mon - timedelta(days=1))  # ≥该周一的首个交易日
    return first == cal.next_trading_day(qd)


def _row_layer(horizon, spec, qd, cal):
    """行归属板别：'short' | 'swing' | None（2026-09-09 交易日相对再分类后）。

    字面 horizon 词判层为基（PANEL_HORIZONS）；其上的修正——跨历法周的单日钉
    （spec=nweek_first 且目标 == 发帖后首交易日）虽带 swing 词「下周」，实为超短观点
    （预测周期 = 发帖后首个交易日）→ 降级 short。nweek/week/近日/更长/未提 等整段或多日
    观点**不**降级（周一~周四的 nweek_first 目标隔数日，仍 swing）。无法归属（horizon
    非法）返回 None。
    """
    if horizon in schema.PANEL_HORIZONS["short"]:
        return "short"
    if horizon not in schema.PANEL_HORIZONS["swing"]:
        return None
    if (spec == "nweek_first" and qd is not None and cal is not None
            and _nweek_first_is_next_session(qd, cal)):
        return "short"
    return "swing"


def _render(blogger, posts, bodies=None, style="head", limit=1200, notes=None):
    """共享标注输入分段构造（单一实现，2026-09-08 解析加固拆出 visible）。

    posts 约定新→旧（下标 i 即模型回填的 post_n 来源）。style/limit 只控制正文截断方式：
    - 推送走 head（前 1200 字，一帖观点可承载）
    - 报告走 middle（保留头尾，长文结论常在尾部；limit 提到 4000 即长帖全文口径）

    notes：与 posts 对齐的可选逐帖注记列表（None 或空项 → 不加），如 report 端注入的
    「[行情@发帖 …] 发帖时刻指数现值」（见 opinion.ref_price.pub_note）。注记追加在每帖段末，
    属**模型可见文本**（同时入 visible，与 quote 逐字门同源）。推送调用不带 → 零影响。

    返回 (lines, visible)：lines 为整块渲染行（【博主】头 + （N 条帖，新→旧） + 每帖段）；
    visible[i] = 第 i 帖的**模型可见整段**（[i] 发帖 pd｜标题\\n正文〔\\n注记〕）——quote 逐字门与
    render 用同一源，杜绝两处构造漂移。
    """
    lines = [f"【博主】{blogger}", f"（{len(posts)} 条帖，新→旧）"]
    visible = []
    for i, p in enumerate(posts):
        pd = (p.get("publish_date") or "").strip()[:16] or "?"
        title, body = text.resolve_post(p, bodies)
        body = text.truncate(body, limit=limit, style=style)
        seg = f"[{i}] 发帖 {pd}"
        if title:
            seg += f"｜{title}"
        if body:
            seg += "\n" + body
        if notes:
            n = notes[i] if i < len(notes) else None
            if n:
                seg += "\n" + str(n)
        lines.append(seg)
        visible.append(seg)
    return lines, visible


def render_batch(blogger, posts, bodies=None, style="head", limit=1200, notes=None):
    """共享标注输入块：单串（【博主】头 + 每帖 [i] 段）。quote 逐字校验的每帖可见文本见 _render。"""
    lines, _ = _render(blogger, posts, bodies=bodies, style=style, limit=limit, notes=notes)
    return "\n".join(lines)


def to_canonical(row, post, blogger, post_n):
    """模型行 → 规范行（系统回填身份/时间；字段校验同报告侧 normalize_signal 同向）。

    返回规范行 dict；非法返回 None（d 非 ±1、idx 非法、spec 缺失/非法、summary 缺失、
    spec=long 强制转 unscored）。pub/quote_ts 以帖子为准——模型不写时间（坑：引文时间错位）。
    """
    if not isinstance(row, dict):
        return None
    d = _int(row.get("d"))
    if d not in (1, -1):
        return None
    cat = row.get("cat") or "scored"
    if cat not in schema.VALID_CAT:
        return None
    spec = str(row.get("spec") or "").strip()
    summary = (row.get("summary") or "").strip()
    if not summary:
        return None
    idx = str(row.get("idx") or "上证指数").strip()
    idx = schema.IDX_ALIAS.get(idx, idx)
    if idx not in schema.VALID_IDX:
        return None
    # spec=long 恒不计分（SKILL §3：目标点位/年度/中长期）→ 强制转 unscored（同 normalize）
    if spec == "long" and cat == "scored":
        cat = "unscored"
    # spec 语法 + 语义域双关（SPEC_RE 之外再 reject t0/t99/d:2026-13-99 之类"自洽但荒谬"）
    if cat == "scored" and not (schema.SPEC_RE.match(spec) and schema.spec_sane(spec)):
        return None
    s = _int(row.get("s"))
    if cat == "scored":
        if s not in (1, 2):
            s = 1
    else:
        s = None
    horizon = str(row.get("horizon") or "").strip()
    if cat == "scored" and not horizon:
        horizon = schema.default_horizon(spec)  # 无歧义档兜底；t5 等模糊档留空（仅报告）
    # quote 存储上限 60→90：逐字保真后上限只是缓存预算；卡面展示截断由 collapse 单独做——
    # 展示截断不再反噬缓存原文（#J 根子：模型输出端把时间词截掉）
    return {
        "blogger": blogger,
        "post_n": post_n,
        "post_id": str(post.get("post_id") or ""),
        "pub": (post.get("publish_date") or "").strip(),
        "quote_ts": _int(post.get("publish_time"), 0),
        "d": d,
        "s": s,
        "idx": idx,
        "spec": spec if cat == "scored" else "long",
        "cat": cat,
        "horizon": horizon if cat == "scored" else "",
        "quote": (row.get("quote") or "").strip()[:90] if cat == "scored" else "",
        "summary": summary[:50],
    }


# 推送档逐帖到案契约（2026-09-08 解析加固）。只挂 annotate_blogger 的 user message 后缀，
# **不进 ANNOTATION_SYSTEM_PROMPT**：报告离线批（15 帖/批海量语料）不承担逐帖交代开销；
# system prompt 指纹不变 → 既有 rows_cache 不因此作废。
DISPOSITION_SUFFIX = ("\n\n【本批次逐帖到案（推送档）】批次里每一条帖子 [i] 都必须交代去向，不得遗漏任何一条："
                      "它要么出现在 rows（含可提取的明确方向预测——注意：**只要该帖写过 rows，就绝不要再把它写进 "
                      "no_view**，no_view 只留给整帖无任何方向观点的帖子），要么出现在并列键 no_view（无方向观点）。"
                      "no_view 每条写 {post_n, reason}，reason 只能取：复盘回顾 / 状态描述 / 转述他人 / "
                      "仓位或理念 / 无明确方向 / 仅他指或板块非大盘 / 无实质内容。仍只输出一个 JSON 对象："
                      "{\"rows\": [...], \"no_view\": [...]}。")


def _canonical_rows_and_pns(raw_rows, blogger, posts):
    """模型行 → (通过 to_canonical 的规范行, 合法域内模型 post_n 列表)。

    post_n 越界/字段非法的行不进 ok（与旧行为一致），但 pns 保留其帖号——到案口径上该帖
    "已试图出行"，若最终既无有效行又不在 no_view，disposition 仍会判未到案并纠错重试。
    """
    ok, pns = [], []
    for r in raw_rows or []:
        if not isinstance(r, dict):
            continue
        pn = _int(r.get("post_n"))
        if isinstance(pn, int) and 0 <= pn < len(posts):
            pns.append(pn)
            can = to_canonical(r, posts[pn], blogger, pn)
            if can is not None:
                ok.append(can)
    return ok, pns


def _quote_gate_bad(rows, visible):
    """quote 逐字门：quote 非空且不逐字 ∈ 该帖模型可见文本的行（编造/改写/拼接/串帖）。"""
    bad = []
    for r in rows:
        q = (r.get("quote") or "").strip()
        if not q:
            continue
        pn = r.get("post_n")
        if not (isinstance(pn, int) and 0 <= pn < len(visible)):
            bad.append(r)
        elif not text.verbatim_in(q, visible[pn]):
            bad.append(r)
    return bad


def _clean_no_view(nv_raw, pns, n_posts):
    """no_view 去冗余到案（2026-09-08 真实 DeepSeek 抽查 B/C 后定稿）。

    模型的硬契约是「每条帖都到案」；rows∩no_view 重叠/重复/理由出枚举都是**可纠正冗余**而非
    硬失败——智由智哉长帖两轮都在 rows 与 no_view 重叠，把它当失败会把真观点博主整批打回：
    - 同帖既有行又写 no_view → 以 rows 为准剔除该 no_view 条目（行在 = 有观点，冗余条目无信息）；
    - 重复 post_n → 保首个；非法 post_n → 丢弃；
    - 理由不在 NO_VIEW_REASONS 枚举 → 仍按覆盖处理（覆盖才是硬契约，类别只供人眼审计）。

    返回 (clean_no_view, warnings)：clean 每条 {post_n, reason}（reason 已保证在枚举内）。
    """
    covered = set(pns)
    out, seen, warns = [], set(), []
    for e in nv_raw or []:
        if not isinstance(e, dict):
            warns.append("no_view 含非对象条目，丢弃")
            continue
        p = _int(e.get("post_n"))
        if p is None or not (0 <= p < n_posts):
            warns.append(f"no_view 含非法 post_n {e.get('post_n')!r}，丢弃")
            continue
        if p in covered:
            warns.append(f"帖子 {p} 与 rows 重叠到案——no_view 冗余剔除（rows 为准）")
            continue
        if p in seen:
            warns.append(f"帖子 {p} 在 no_view 重复——保首个")
            continue
        seen.add(p)
        reason = str(e.get("reason") or "").strip()
        if reason not in schema.NO_VIEW_REASONS:
            warns.append(f"帖子 {p} no_view 理由 {reason!r} 不在枚举——仍按覆盖处理")
            reason = "无明确方向"
        out.append({"post_n": p, "reason": reason})
    return out, warns


def annotate_blogger(blogger, posts, bodies=None, prompt=None, style="head", limit=1200,
                     label="", disposition=True):
    """一位博主一组窗口帖 → 至多两次 DeepSeek 调用 → 规范行列表（共享 ANNOTATION prompt）。

    2026-09-08 解析加固（真实 DeepSeek 抽查 B/C/D 后定稿，硬契约只剩一条）：
    - 到案硬契约：每条渲染帖都必须出现在 rows ∪ no_view（不许跳读）；缺到案 → 带错重试 1 次
      → 仍缺 → 返回 None（按失败处理：不写缓存、推送端回退旧行）。rows∩no_view 重叠 / no_view
      重复 / 理由出枚举 属可纠正冗余 → _clean_no_view 自动化解 + log，不拦成功。
    - quote 逐字门：scored 行 quote 必须逐字 ∈ 该帖模型可见文本；不符 → 带错重试 1 次 →
      仍不符 → 弃坏行；弃后若某帖在 rows/no_view 双双缺席 → 仍按失败（防坏行全弃后缓存空 =
      sticky-[] 假阴性复发）。
    - 主结论对象门（2026-09-09 衡山/诸葛复盘）：idx=上证 的行，摘要/引文点名他指且无上证指向
      （conflict_rows 命中）→ 该行主结论对象不是上证、指数归属判错，**不写缓存** → 带方向纠错
      重试 1 次：重读该帖原文——帖子若确含上证/大盘/沪指/A股 方向观点，idx=上证、摘要/引文取
      上证那部分；只谈他指则 idx 改真实指数（他指行不进上证板，属正确）。仍不符 → 与 quote
      坏行同规则弃行复查到案。绝不把矛盾行当上证卡答案，也绝不让"漏选的上证观点"因矛盾行被弃
      而永久丢失：被弃行独占的帖若无到案 → 按失败不缓存、下轮重试（结合 extract_layers 对
      门上线前旧缓存的自愈作废重抽）。

    返回 (rows, raw)；rows=None = 调用失败/结构异常/到案仍缺（不缓存，调用方计入 errors）。
    rows 为 to_canonical 校验后的规范行（可空列表 = 该博主窗口真无方向观点，同样可缓存）。
    """
    prompt = prompt or prompts.ANNOTATION_SYSTEM_PROMPT
    msg_lines, visible = _render(blogger, posts, bodies=bodies, style=style, limit=limit)
    msg = "\n".join(msg_lines)
    if disposition:
        msg += DISPOSITION_SUFFIX
    label = label or f"opinion:annotate:{blogger}"
    n_posts = len(posts)

    def _process(result):
        """result(dict) → (rows, missing_post_ns, q_bad, obj_bad, nv_clean)。

        missing_post_ns = 在 rows ∪ no_view（已去冗余）都缺席的帖号——唯一的硬到案失败。
        rows=None = 结构异常（rows 非列表）。disposition=False 时不强制逐帖到案 → missing=[]。
        q_bad = quote 未逐字出自该帖可见文本的行；obj_bad = idx=上证 但主结论点名他指、
        无上证指向的自相矛盾行（conflict_rows）——两者都是**不入缓存**的坏行。
        """
        if not isinstance(result, dict):
            return None, [], [], [], []
        raws = result.get("rows")
        if not isinstance(raws, list):
            return None, [], [], [], []
        rows, pns = _canonical_rows_and_pns(raws, blogger, posts)
        nv_clean, warns = ([], [])
        if disposition:
            nv_raw = result.get("no_view")
            nv_clean, warns = _clean_no_view(nv_raw if isinstance(nv_raw, list) else [], pns, n_posts)
            for w in warns:
                log.warning("  %s %s", blogger, w)
        missing = [i for i in range(n_posts)
                   if i not in set(pns) and i not in {e["post_n"] for e in nv_clean}]
        q_bad = _quote_gate_bad(rows, visible)
        obj_bad = conflict_rows(rows)
        return rows, missing, q_bad, obj_bad, nv_clean

    def _drop_bad(rows, bad, nv_clean):
        """弃坏行（quote 非逐字 ∪ 主结论对象矛盾）后复查到案：被弃行独占的帖若不在
        no_view → 缺到案（防空缓存假阴性，绝不给 [] 粘住假阴性）。"""
        kept = [r for r in rows if id(r) not in {id(x) for x in bad}]
        kept_pns = {r.get("post_n") for r in kept}
        nv_pns = {e["post_n"] for e in nv_clean}
        still_missing = [i for i in range(n_posts)
                         if i not in kept_pns and i not in nv_pns]
        return kept, still_missing

    def _merge_bad(*groups):
        seen, out = set(), []
        for g in groups:
            for r in g or []:
                if id(r) not in seen:
                    seen.add(id(r))
                    out.append(r)
        return out

    def _feedback(missing, q_bad, obj_bad):
        lines = [f"帖子 {m} 未到案（既不在 rows 也不在 no_view），须逐条交代" for m in missing]
        lines += [f"行 post_n={r.get('post_n')} quote 未逐字出自该帖可见文本：{r.get('quote')!r}"
                  for r in q_bad]
        for r in obj_bad:
            pn = r.get("post_n")
            tok = _idx_object_conflict(r)
            lines.append(
                f"行 post_n={pn} idx=上证 但主结论点名他指【{tok}】且未提上证"
                f"（{(r.get('summary') or '')[:20]}）——主结论对象不是上证，指数归属判错。"
                f"请重读帖子 {pn} 原文后如实输出：帖子若确含上证/大盘/沪指/A股 的方向性观点，"
                f"该部分就标 idx=上证、摘要与引文取上证那部分的原文（他指结论如需可另起一行、"
                f"标其真实指数）；帖子若只谈【{tok}】、没有上证方向观点，就把该行 idx 改为 "
                f"{tok}（他指行不进上证板，属正确）。切勿编造原文里没有的上证观点。")
        return lines

    result, raw = ds.call_json(None, prompt, msg, label)
    if result is None:
        return None, raw
    rows, missing, q_bad, obj_bad, nv_clean = _process(result)
    if rows is None:
        return None, raw  # 结构异常（键名/形状不符）→ 不缓存，下轮重试
    if not missing and not q_bad and not obj_bad:
        return rows, raw
    # 带错重试 1 次：列出缺到案 / 坏 quote / 对象矛盾，要求整块重出（不是只给改动行）
    err_lines = _feedback(missing, q_bad, obj_bad)
    fb = ("\n\n[系统纠错] 上次输出未通过校验，请逐条修正后重新输出**整个** JSON"
          "（rows + no_view 全部重给，勿只给改动行）：\n- " + "\n- ".join(err_lines))
    log.warning("  %s 首次输出 %d 处未过门，带错重试：%s", blogger, len(err_lines), err_lines[:3])
    result2, raw2 = ds.call_json(None, prompt, msg + fb, f"{label} 纠错重试")
    if result2 is not None:
        rows2, missing2, q_bad2, obj_bad2, nv2 = _process(result2)
        if rows2 is not None:
            if not missing2 and not q_bad2 and not obj_bad2:
                return rows2, raw2
            if missing2:
                log.warning("  %s 纠错重试后仍 %d 帖缺到案，按失败处理（回退不缓存）",
                            blogger, len(missing2))
                return None, raw2
            bad2 = _merge_bad(q_bad2, obj_bad2)
            kept2, still2 = _drop_bad(rows2, bad2, nv2)
            if still2:
                log.warning("  %s 纠错重试后坏行弃尽致 %s 缺到案，按失败处理", blogger, still2)
                return None, raw2
            log.warning("  %s 纠错重试后仍剩 %d 条坏行（quote/对象矛盾），弃行保留其余",
                        blogger, len(rows2) - len(kept2))
            return kept2, raw2
    # 纠错重试调用失败/结构异常 → 回退第一批结果：缺到案 → 失败；纯坏行 → 弃行复查
    if missing:
        return None, raw
    bad = _merge_bad(q_bad, obj_bad)
    kept, still = _drop_bad(rows, bad, nv_clean)
    if still:
        log.warning("  %s 纠错重试不可用且坏行弃尽致 %s 缺到案，按失败处理", blogger, still)
        return None, raw
    if len(kept) < len(rows):
        log.warning("  %s 纠错重试不可用，弃 %d 条坏行保留其余", blogger, len(rows) - len(kept))
    return kept, raw


def collapse_board(board_key, blogger, rows, window_start=None, cal=None):
    """确定性坍缩：博主窗口规范行 → 该博主该层最新表态行（或 None=该层无观点）。

    v16 LAYER prompt「每层取最新」散文的代码化：无观点帖只是路过、不更新不覆盖不抹掉旧行；
    整窗无合格行才判无观点。合格行 = idx=上证指数、行归属板别（_row_layer：horizon 词为基 +
    交易日相对再分类）== board_key、cat=scored、spec 与 horizon 自洽、且（给了 window_start
    时）quote_ts≥该层窗口下界。推送板只认上证观点（2026-09-08）：他指行（创业板指/科创50/
    上证50/双创…）保留在缓存给报告侧、不进本层卡与计数。2026-09-09 追加主结论对象门（**渲染
    底限，非修复**）：idx 字段为上证、但摘要/引文点名他指且全文无上证指向的自相矛盾行——主结论
    对象不是上证——无论行来自何处都不得以上证卡渲染。坍缩只有行、无帖子全文，无法区分「idx 标
    错」与「摘要漏选上证句」，故本门**不越权修复**：矛盾的恢复在上游——annotate_blogger 拒收
    这类行入缓存并带方向纠错重试，extract_layers 对门上线前已缓存的矛盾旧帖作废整帖重抽（自愈）。
    本门只保证矛盾行永不上错卡，并把线索 loud log 供上游追溯；若帖子真含上证观点，由重抽找回，
    不会因本门丢卡。同帖同层多条 → 目标日更近优先（HORIZON_RANK 更小者）；同帖
    矛盾行以 rows 中先出现者为准。返回推送展示行（带 stance/horizon/summary/quote/quote_ts），
    summary 在此剔除相对日周词（系统侧兜底）。

    cal（可选）：暴露 next_trading_day(date) 的交易日历。给出时启用 2026-09-09 交易日相对
    再分类——周五~周日发帖、spec=nweek_first 的"下周一/下周首个交易日"实指下一交易日，
    行降级 short（预测周期 = 发帖后首交易日，超短），且整周/nweek 观点不降级。降级行在本层
    输出把 horizon 归一为「明天」（目标日就是下一交易日，避免卡面出现下周词+目标已过）。不给
    cal → 纯字面 horizon 词判层（原行为，报告/测试不受扰）。
    """
    best, best_key = None, None
    for r in rows or []:
        if (r.get("idx") or "上证指数") != "上证指数":
            continue  # 推送板只认上证观点；他指行不进卡（2026-09-08）
        obj = _idx_object_conflict(r)
        if obj is not None:
            # 2026-09-09 渲染底限：idx=上证 但主结论点名他指且无上证指向（衡山/诸葛案例）的自
            # 相矛盾行永不上上证卡——主结论对象不是上证。恢复在上游（annotate 对象门拒收入缓存 +
            # extract_layers 对旧缓存帖作废重抽）；这里只保证不渲染错卡 + loud log 供追溯，含真
            # 上证观点的帖由重抽找回、不因本门丢卡。
            log.warning("  %s 矛盾行点名他指【%s】（%s）不上上证卡——交上游重抽恢复",
                        blogger, obj, (r.get("summary") or "")[:40])
            continue
        horizon = r.get("horizon")
        if not isinstance(horizon, str) or not horizon:
            continue  # 无 horizon 判层（静默，同旧 whitelist 门）
        if r.get("cat") != "scored":
            continue
        ts = _int(r.get("quote_ts"), 0)
        if window_start is not None and ts < window_start:
            continue
        spec = str(r.get("spec") or "")
        if not schema.horizon_spec_ok(horizon, spec):
            log.warning("  %s [%s] horizon=%r 与 spec=%r 不自洽，弃行（不静默）",
                        blogger, board_key, horizon, spec)
            continue
        if _row_layer(horizon, spec, _quote_date(ts), cal) != board_key:
            continue
        key = (ts, -schema.HORIZON_RANK.get(horizon, 0))
        if best is None or key > best_key:
            best, best_key = r, key
    if best is None:
        return None
    out_horizon = best.get("horizon")
    if (board_key == "short" and out_horizon not in schema.PANEL_HORIZONS["short"]):
        out_horizon = "明天"  # 降级行：目标即下一交易日 → 展示归一为明天
    return {
        "blogger": blogger,
        "post_id": best.get("post_id"),   # 溯源（Pillar C：复核/失败回退按帖定位原文）
        "has_view": True,
        "stance": "多" if best.get("d") == 1 else "空",
        "horizon": out_horizon,
        "summary": text.strip_rel_time((best.get("summary") or "").strip())[:50],
        "quote": (best.get("quote") or "").strip()[:60],
        "quote_ts": best.get("quote_ts"),
    }
