#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 自动提取 Direction 方向信号（替代 Claude 人工逐条标注）。

流程：读 data/posts/<博主>.json 的帖子 + <博主>_bodies_s*.json 的正文
      → 分批调 DeepSeek flash 按 SKILL.md §1~§8 规则逐条判断
      → 脚本强校验（spec/idx/cat/日期/去重，非法条目丢弃）
      → 自查：把「已提取信号 + 原文」回喂 DeepSeek 做独立审查（keep/fix/drop/补加）
      → 写 data/direction_signals/<博主>.json

用法：
  export DEEPSEEK_API_KEY="sk-..."      # 只经环境变量，绝不写入文件/提交
  python scripts/pipeline/extract_signals_direction.py <博主名>
  python scripts/pipeline/extract_signals_direction.py <博主名> --batch-size 25
  python scripts/pipeline/extract_signals_direction.py <博主名> --limit 30          # 冒烟：只处理前 30 条
  python scripts/pipeline/extract_signals_direction.py <博主名> --out /tmp/x.json   # 写指定路径（不动正式数据）
  python scripts/pipeline/extract_signals_direction.py <博主名> --runs 3            # 3 次运行共识合并（聚合更稳，推荐）
  python scripts/pipeline/extract_signals_direction.py <博主名> --no-verify         # 跳过自查（更快）
  python scripts/pipeline/extract_signals_direction.py <博主名> --dry-run           # 不调 API、不写文件
  python scripts/pipeline/extract_signals_direction.py <博主名> --no-disposition    # 关逐帖到案门（=旧行为，跑更快）
  # 2026-09-09 报告链复核起默认开：逐帖到案门 + 发帖现值注入 + 长帖全文喂给（spec_sane/target/到案详见下）。

稳定性：DeepSeek 同 prompt 下每次运行有少量批间随机差异（信号数 ±3 条量级）。
--runs N 会完整跑 N 次（提取+自查），只保留 ≥(N//2+1) 次运行都出现的信号，
直接压掉单次噪声，保证聚合结论稳定。运行元数据写入 data/direction_signals/_<名>_run.json
（以 _ 开头，已被 .gitignore 忽略，不会提交）。
"""

import argparse
import json
import math
import os
import sys
import time
from collections import Counter

from openai import OpenAI

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# REPO_ROOT 环境覆盖（与 briefing/paths.py、opinion/ref_price、eval/run_direction 同口径；
# 默认行为不变 = 以本文件位置推导仓库根）
PROJECT_ROOT = os.environ.get("REPO_ROOT") or os.path.dirname(os.path.dirname(SCRIPT_DIR))

# 2026-09-08 共享模块重构：本脚本的读帖/正文解析/DeepSeek 网关/逐帖标注 prompt 统一委派
# 顶层 opinion/（推送 briefing 同源）。回测消费的是本脚本产出的 direction_signals，不再走
# 读帖路径。打分链（run_direction.calc 等）不动。
sys.path.insert(0, PROJECT_ROOT)
from opinion import annotate as o_ann, ds as o_ds, posts as o_posts, prompts as o_prompts, ref_price as o_ref, schema as o_schema, text as o_text  # noqa: E402

# ── Configuration ──
# 网络/模型常量与 Direction schema 合法集统一收口到 opinion（单一共享源）；本文件只留编排常量。
DEFAULT_BATCH_SIZE = 15
VERIFY_BATCH_SIZE = 10  # 自查批次：每批审几帖

# 2026-09-09 报告链复核（D4 长帖全文 / 充分性门）：
# - 单帖渲染上限 PER_POST_LIMIT：≤ 此长度整帖喂给（text.truncate middle 语义：超限才按 ~6:4 保头保尾）
# - BATCH_CHAR_BUDGET：分批按字符预算打包，防 limit 抬高后单批过大（成本/上下文护栏）
PER_POST_LIMIT = 4000
BATCH_CHAR_BUDGET = 30000
_BATCH_OVERHEAD = 90  # 每帖 [i] 发帖/标题行 + 行情注记 的粗估长度

# 只提取 2026-01-01 及之后发布的信号（读帖过滤 + normalize 双重口径）
SIGNAL_START = o_posts.DEFAULT_SINCE

MODEL = o_ds.MODEL
BASE_URL = o_ds.BASE_URL
MAX_RETRIES = o_ds.MAX_RETRIES
RETRY_DELAY = o_ds.RETRY_DELAY
API_CALL_DEADLINE = o_ds.API_CALL_DEADLINE
call_json = o_ds.call_json  # 签名 (client, system_prompt, user_message, label, thinking=) 不变

# ── System Prompt（2026-09-08 起用单一共享逐帖标注 prompt，见 opinion/prompts.py——
# SKILL.md §1~§8 规则精简版 + LAYER quote 纪律；输出键 rows（含 horizon 展示词），
# 报告侧 normalize 只取 pub/d/s/idx/spec/summary/cat，horizon/quote 忽略）──
SYSTEM_PROMPT = o_prompts.ANNOTATION_SYSTEM_PROMPT

# 2026-09-09 报告链指令：周期交易日口径（D3）+ 发帖现值注记用法/指数识别（D5）+ target 语义收窄 +
# 报告侧无方向教义 spec 口径。无方向教义主体是单一同源常量 DOCTRINE_NO_DIRECTION（B3，见 opinion.prompts
# ——与共享 ANNOTATION_SYSTEM_PROMPT 同一文本），本后缀插值它（改教义 → 标注指纹变 → 推送 rows_cache
# 作废重抽，机制接受）；下方【加减仓…】段只补报告特有的 spec 落地口径。批间同文 → 利于 DeepSeek prompt 缓存。
_REPORT_EXTRACT_SUFFIX = """
【周期口径】spec 一律按**交易日**理解：t1=发帖后的第 1 个交易日（周末/假日发的"明天"仍记 t1，日历换算由系统做）；"后天/两日后"→t2；"N 天后/未来几天"这类自然日表述 → 填对应的 tN（系统按 N 个交易日计）。本周→week、下周→nweek（特指下周一才用 nweek_first）、月底前→month、下月→nmonth；今年/下半年/年度/长期/未来几个月 → long（unscored）。只填 spec 档位，不要写具体日期。

【发帖时刻行情注记】每条帖子下方可能附一行「[行情@发帖 …]」，列出该帖**发帖时刻**各指数现值（上证指数/创业板指/沪深300/上证50/中证500/中证1000/科创50）。用它做两件事：① 指数识别——某点位/方向句提到哪个指数，按注记里的指数现值对照（帖内未点名指数的，默认上证指数）；② 定多空——「博主所说点位 vs 注记里该指数现值」：说涨到/站上 4250 而现值 3940 → d=1 看多；说跌向/破位 3900 而现值 3940 → d=-1 看空。**用注记现值判断，不要凭旧记忆**；注记缺失（如行情数据未覆盖）的帖按正文语境推断。

【target 目标位（可选键，只加在 rows 的每条里）】系统标准键之外，你**可以在该行额外多输出一个 target 键**（值为数字，纯数值不带单位）——仅当该行是一句**方向性移动目标**，博主预测价格将**移动到**的具体点位（"站上4250""目标3500""跌至3880""反弹看到4000"）才填，且 d 与该移动方向一致（看多到高位 / 看空到低位）。**条件式/区间句 = 无方向、不产行（target 当然不填）**："守住3900看反弹""回踩3900企稳继续看多""3900是多空分水岭""在3900-3950区间震荡"——这些是条件式前提或区间锚，博主并未无条件承诺涨/跌（2026-09-09 教义：**一切条件式无方向**，不再照取分支观点安 d）→ 该句**不进 rows、不给 d、不填 target**；该帖若仅此内容 → no_view"无明确方向"。只有**无条件净方向移动目标**（"站上4250""跌至3880""反弹目标4200"）才成行填 d 并 target。拿不准就不填；宁可少填，绝不把条件位当方向行或 target。示例行（其他标准键照常）：{"post_n":0,"d":1,"s":1,"idx":"上证指数","spec":"t2","cat":"scored","horizon":"近日","quote":"反弹看到4200点以上","summary":"看多，反弹目标4200","target":4200}。

【无方向教义（单一同源，与共享 ANNOTATION prompt 同一文本，2026-09-09 B3）】
__DOCTRINE_NO_DIRECTION__

【加减仓与无时间词（报告侧 spec 落地口径，教义同上）】加减仓/清仓/止盈/重仓等**操作动词 = 方向同义**（减/清/止盈→看空，加/重/补/抄底→看多）：给 d；有明确时间词 → 按周期计分；**无时间词 → 按"无明确周期有方向"口径 spec=t5 计分**（不要给 long/unscored，那是年度/中长期用）；只有仓位**状态**自述不算方向。
""".replace("__DOCTRINE_NO_DIRECTION__", o_prompts.DOCTRINE_NO_DIRECTION)

# 报告批逐帖到案契约（L1 充分性门；同推送 DISPOSITION_SUFFIX 的结构，report 侧独立后缀）。
# 枚举复用 opinion/schema.NO_VIEW_REASONS。
_REPORT_DISPOSITION_SUFFIX = ("""
【本批次逐帖到案】批次里每一条帖子 [i] 都必须交代去向，不得遗漏任何一条：要么出现在 rows（含可提取的明确方向预测），要么出现在并列键 no_view（整帖无任何方向观点——只要该帖写了 rows 就绝不要再写进 no_view）。no_view 每条写 {post_n, reason}，reason 只能取：复盘回顾 / 状态描述 / 转述他人 / 仓位或理念 / 无明确方向 / 仅他指或板块非大盘 / 无实质内容。仍只输出一个 JSON 对象：{"rows": [...], "no_view": [...]}。""")

# ── 自查 System Prompt（对「已提取信号+原文」做独立审查）──
VERIFY_SYSTEM_PROMPT = """你是信号审查助手。你会收到「已提取信号 + 其原文帖子」，请审查信号是否被原文**明确支持**，并修正或补加。

帖子以「标题：…\\n正文：…」并列呈现，标题与正文同等重要——标题里的明确预测结论（"明天看涨"等）同样要审查、不可漏。

## 第一步：判定主结论句
先找到帖子的**主结论句**——形如「周三：大盘探底回升，我看涨」「明天：只卖不买」「下周一我看跌」等**带明确方向**的句子。主结论句是全帖最高优先级的预测：**任何条件句、风险提示、走势分类、点位预演都不能替代或覆盖主结论句**。若整帖唯一可提取内容就是条件句/先A后B形态（守/破/分水岭/冲高回落…）、并无带方向的独立无条件主结论 → 该帖无主结论（按第 2 条 drop，不把分支偏好当方向）。若提取信号与主结论句方向/周期不一致 → 必须 action=fix，改为主结论句的方向/周期。

## 教义（单一同源，与推送复核同一文本，2026-09-09 B3；编号沿用推送复核判定要点 6/7）
__DOCTRINE_REVIEW__

## 其他标准
1. **周期支持**：spec 必须对应原文**明确出现**的周期词。**原文无明确周期但有明确方向**（"随时""大趋势向上""肯定涨但不知道什么时候""上涨没结束"等结构/无时限表述）→ 不能给 long 单列，fix 为 spec=t5、cat=scored（验证终点=信号日之后第 5 个交易日，正常计分）。**目标点位无时间承诺**（"目标是X点""背驰点在4423"）→ fix 为 spec=long、cat=unscored（不填 s）。**有明确点位 + 明确周期**（"明天站上4100""下周回踩3800"）→ fix 为 scored 按周期计分，点位高于参考价=看涨 d=1、低于=看跌 d=-1。**年度预测**（"今年/下半年/全年/2026"）与**中长期/远期**（"未来几个月""三年""长期来看"）→ fix 为 spec=long、cat=unscored。**加减仓等操作动作**（见教义节 7：操作=方向、仓位状态≠方向）：有明确周期 → 按周期 fix 为 scored；无明确周期 → fix 为 spec=t5、cat=scored（既有无周期口径，不给 long/unscored）；只有仓位状态自述才 drop。
2. **可打分性**：只有形态描述（震荡/筑底/洗盘/冲高回落/支撑位）而无明确方向态度 → drop（"震荡下跌/震荡上涨"除外，属明确方向）；**模棱两可/方向不明（"可能涨也可能跌""边走边看""不好说""即将变盘"）→ drop（连单列都不记）；纯复盘/对过去的分析（回顾行情、评价已发生走势、事后总结）→ drop；状态描述（"已经进入调整阶段""顶背离已出现"）→ drop**；仓位状态自述 → drop。条件式/形态主句的硬凑 d 与形态句后的净方向句 → 一律按教义节 6/7 处置（硬凑 d 且帖无独立无条件主结论 → drop；有 → fix 到该部分；净方向句属主结论 → 按第一步 keep/fix、不 drop）。
3. **盘中/盘前"今天"**："今天/今日/下午/午后/尾盘"预测 → spec=today、cat=scored（**无论盘前/盘中/盘后/非交易日发布都保持**，是否过时由打分引擎自动判定，审查阶段不做无效判断）。
4. **补加**：原文有比已提取信号**更明确或被漏掉**的预测结论 → 放入 add。典型遗漏：① 同一帖子里还有**第二个观点**（不同方向或不同周期，如"短期看空、长期看多"只提取了短期看空 → add 长期看多那条：long/unscored）；② 应属 t5（无周期有方向）或 long/unscored 而未被提取。
5. **保留**：信号方向与周期都有原文支持、且就是主结论句 → action=keep。

## 输出 JSON（只输出 JSON，无其他文字）
**必须对「已提取信号」的每一条都给出 verdict（keep/fix/drop），不得遗漏任何一条**——漏掉任何一条都会被当作未评审而按原样保留；只有你明确 drop 的信号才会被删除。
{"verdicts": [{"vidx": <帖子编号>, "sig": <该帖已提取信号下标，0基>, "action": "keep"|"fix"|"drop", "d":1|-1, "s":1|2, "spec":"...", "cat":"...", "summary":"≤50字", "reason":"一句话"}],
 "add": [{"vidx": <帖子编号>, "d":1|-1, "s":1|2, "spec":"...", "cat":"...", "summary":"≤50字"}]}
- action=keep：只输出 vidx/sig/action/reason
- action=fix：输出修正后的完整字段（d/s/spec/cat/summary）
- action=drop：只输出 vidx/sig/action/reason
- cat=scored 时 spec、s 必填；cat=unscored 时 spec=long、不填 s
- 无修正 → verdicts 为空数组；无补加 → add 为空数组；都无 → {"verdicts":[],"add":[]}""".replace(
    "__DOCTRINE_REVIEW__", o_prompts.DOCTRINE_REVIEW)  # B3：复核教义条同源，与推送 REVIEW 共享


def load_posts_and_bodies(blogger):
    """读 data/posts/<名>.json 的帖子 + 合并 <名>_bodies_s*.json 正文，过滤 2026+。

    2026-09-08 委派 opinion.posts（读帖/正文分片合并与推送共用同源实现）。
    """
    posts_dir = os.path.join(PROJECT_ROOT, "data", "posts")
    posts_path = o_posts.blogger_file(blogger, posts_dir)
    if not os.path.exists(posts_path):
        print(f"ERROR: Posts file not found: {posts_path}")
        return None, None, None, None
    return o_posts.load_report_posts(blogger, posts_dir, since=SIGNAL_START)


def _fmt_verify_post(post, bodies, note=None):
    """自查输入的单帖文本：标题/正文并列（沿用 VERIFY prompt 的「标题：…\\n正文：…」约定），
    微帖只显一次。2026-09-09 D5 复核口径：与提取端同 limit（PER_POST_LIMIT，≤4000 全量、
    超限 middle 保头保尾）并附该帖「[行情@发帖 …]」现值注记——复核才有价可对（提取端注记
    若在复核端被截掉，d/target 判断又落回模型旧记忆）。标题/正文解析收口 opinion.text。"""
    title, body = o_text.resolve_post(post, bodies)
    if title and body:
        txt = o_text.truncate(f"标题：{title}\n正文：{body}", limit=PER_POST_LIMIT, style="middle")
    else:
        txt = o_text.truncate(body or title or (post.get("content") or "").strip(),
                              limit=PER_POST_LIMIT, style="middle")
    if note:
        txt += f"\n{note}"
    return txt


def _est_post_chars(post, bodies):
    """分批用的单帖渲染字符粗估（resolve_post 后按 PER_POST_LIMIT 封顶——渲染端 middle 截断
    后单帖 ≤ limit+注记，封顶让预算贴近真实上下文成本）。"""
    title, body = o_text.resolve_post(post, bodies)
    return min(len(title) + len(body), PER_POST_LIMIT) + _BATCH_OVERHEAD


def build_batches(posts, batch_size, bodies=None):
    """分批：字符预算打包（2026-09-09 D4——单帖 limit 抬高到 4000 后，固定帖数分批会让单批
    超上下文护栏，改按累计渲染字符 ≤ BATCH_CHAR_BUDGET 切批；batch_size 仍是每批帖数上限，
    兼容 --batch-size 语义）。极端长帖预算超限 → 自成一批。帖子保持 新→旧 顺序。"""
    batch, budget = [], 0
    for p in posts:
        est = _est_post_chars(p, bodies)
        if batch and (len(batch) >= batch_size or budget + est > BATCH_CHAR_BUDGET):
            yield batch
            batch, budget = [], 0
        batch.append(p)
        budget += est
    if batch:
        yield batch


def _parse_target(row):
    """target 可选字段（L4）：只收"博主预测价格将**移动**到的终点目标位"的数值。

    模型乱给（非数字/带单位文本解析失败/≤0/≥1e6/NaN/True）→ None——**弃字段不弃行**
    （目标位是附带信息，不该因它废掉一条方向本身成立的行；语义收窄靠 _REPORT_EXTRACT_SUFFIX，
    条件/支撑位句模型不许填）。返回有限正数 float 或 None。"""
    t = row.get("target") if isinstance(row, dict) else None
    if t is None or isinstance(t, bool):
        return None
    if isinstance(t, (int, float)):
        tf = float(t)
    else:
        s = str(t).strip().replace(",", "").replace("点", "").strip()
        if not s:
            return None
        try:
            tf = float(s)
        except ValueError:
            return None
    if not (0.0 < tf < 1e6) or not math.isfinite(tf):
        return None
    return tf


def normalize_signal(row, post):
    """把一条候选信号行归一化为 Direction schema。返回 (sig, None) 或 (None, 原因)。

    2026-09-09 B1：核心校验/归一（d/cat/idx 别名/spec 语义域/spec=long→unscored/s/summary）
    委派 opinion.schema.to_core——与推送侧 annotate.to_canonical **同判同改**（双链此前平行
    实现行校验，含本文件内联的 idx 别名表，有漂移风险）；本函数只保留报告独有富化：发布日
    ≥SIGNAL_START 过滤、target 可选字段（校验失败弃字段不弃行）、pub 全文回填。拒因标签来自
    to_core（D1 spec_sane 语义域在此一并拒绝，拒因 console/统计用，行是否拒由 to_core 定）。"""
    pub = (post.get("publish_date") or "").strip()
    if not pub or pub[:10] < SIGNAL_START:
        return None, "非 2026"
    core, reason = o_schema.to_core(row)
    if core is None:
        return None, reason
    sig = {"pub": pub, "d": core["d"], "idx": core["idx"],
           "summary": core["summary"], "spec": core["spec"], "cat": core["cat"]}
    if core["cat"] == "scored":
        sig["s"] = core["s"]
    target = _parse_target(row)
    if target is not None:
        sig["target"] = target
    return sig, None


def validate_signals(raw_signals, batch_posts):
    """把 DeepSeek 输出映射/校验成 Direction schema。返回
    (ok_signals, dropped_counter, posts_aligned, pns)。

    pns = 模型**给过行**的帖子号（含行未过 normalize 的帖）——与 opinion.annotate 的到案口径
    一致：到案 = 该帖至少被模型试图出过行；行本身非法仍算"已考虑"，不触发缺到案重试（重试只
    拦模型**整帖跳读**）。"""
    ok, dropped, posts_aligned = [], Counter(), []
    pns, seen_pn = [], set()
    for r in raw_signals:
        if not isinstance(r, dict):
            dropped["非对象"] += 1
            continue
        try:
            post_n = int(r.get("post_n", -1))
        except (TypeError, ValueError):
            post_n = -1
        if not (0 <= post_n < len(batch_posts)):
            dropped["post_n 越界"] += 1
            continue
        if post_n not in seen_pn:
            seen_pn.add(post_n)
            pns.append(post_n)
        post = batch_posts[post_n]
        sig, reason = normalize_signal(r, post)
        if sig is None:
            dropped[reason] += 1
            continue
        ok.append(sig)
        posts_aligned.append(post)
    return ok, dropped, posts_aligned, pns


def verify_signals(client, signals, posts, bodies, blogger):
    """自查：把「已提取信号 + 原文」回喂 DeepSeek 审查，返回 (final_signals, final_posts, stats)。"""
    # 按帖子分组合并（同一帖子的多条信号一起审）
    groups, seen = [], {}
    for sig, post in zip(signals, posts):
        gi = seen.get(id(post))
        if gi is None:
            gi = len(groups)
            seen[id(post)] = gi
            groups.append({"post": post, "signals": []})
        groups[gi]["signals"].append(sig)

    final_signals, final_posts = [], []
    stats = Counter()
    total_groups = len(groups)

    batch_lo = 0
    for start in range(0, total_groups, VERIFY_BATCH_SIZE):
        grp = groups[start:start + VERIFY_BATCH_SIZE]
        batch_hi = start + len(grp)
        lines = []
        for i, g in enumerate(grp):
            vidx = start + i
            sigs = []
            for s in g["signals"]:
                it = {"d": s["d"], "s": s.get("s"), "spec": s.get("spec"),
                      "cat": s.get("cat", "scored"), "summary": s["summary"]}
                if s.get("target") is not None:
                    it["target"] = s["target"]
                sigs.append(it)
            note = o_ref.pub_note((g["post"].get("publish_date") or "").strip())
            lines.append(f"[Post #{vidx}] {g['post'].get('publish_date', '?')}\n"
                         f"{_fmt_verify_post(g['post'], bodies, note=note)}\n"
                         f"已提取信号: {json.dumps(sigs, ensure_ascii=False)}\n")
        label = f"Verify {start // VERIFY_BATCH_SIZE + 1}/{(total_groups - 1) // VERIFY_BATCH_SIZE + 1}"
        print(f"  [{label}] 审查 {len(grp)} 帖...", end=" ", flush=True)
        user_message = (f"请审查以下 {len(grp)} 帖子的已提取信号是否被原文支持，并按规则修正（vidx 对应帖子编号，仅限本批次 {start}~{batch_hi - 1}）。\n\n"
                        + "\n".join(lines))
        try:
            result, _ = call_json(client, VERIFY_SYSTEM_PROMPT, user_message, label, thinking=False)
        except Exception as e:
            # 单批 API 拖死（3 次重试后仍超时）→ 保留该批原信号，不拖垮整位博主（2026-08-31 加固）
            print(f"FAILED({e}), 保留原信号")
            stats["verify 批次失败"] += 1
            for g in grp:
                for s in g["signals"]:
                    final_signals.append(s)
                    final_posts.append(g["post"])
            continue
        if result is None:
            print("FAILED, 保留原信号")
            stats["verify 批次失败"] += 1
            for g in grp:
                for s in g["signals"]:
                    final_signals.append(s)
                    final_posts.append(g["post"])
            continue

        # 处理 verdicts（vidx 必须落在本批次范围内，防跨批错配/重复）
        verdicts = result.get("verdicts") or []
        judged = set()  # (vidx, sigi) 已被明确评审（keep/fix/drop）
        for v in verdicts:
            vidx = v.get("vidx")
            sigi = v.get("sig")
            if not (isinstance(vidx, int) and batch_lo <= vidx < batch_hi):
                stats["vidx 越界"] += 1
                continue
            g = groups[vidx]
            if not (isinstance(sigi, int) and 0 <= sigi < len(g["signals"])):
                stats["sig 越界"] += 1
                continue
            judged.add((vidx, sigi))
            action = v.get("action")
            if action == "keep":
                stats["keep"] += 1
                final_signals.append(g["signals"][sigi])
                final_posts.append(g["post"])
            elif action == "drop":
                stats["drop"] += 1
            elif action == "fix":
                sig, reason = normalize_signal(v, g["post"])
                if sig is None:
                    stats[f"fix 非法({reason})"] += 1
                    final_signals.append(g["signals"][sigi])
                    final_posts.append(g["post"])
                else:
                    stats["fix"] += 1
                    final_signals.append(sig)
                    final_posts.append(g["post"])
            else:
                stats[f"action 非法: {action}"] += 1
                final_signals.append(g["signals"][sigi])
                final_posts.append(g["post"])

        # 处理补加（vidx 同样限制在本批次）
        adds = result.get("add") or []
        for a in adds:
            vidx = a.get("vidx")
            if not (isinstance(vidx, int) and batch_lo <= vidx < batch_hi):
                stats["add vidx 越界"] += 1
                continue
            g = groups[vidx]
            sig, reason = normalize_signal(a, g["post"])
            if sig is None:
                stats[f"add 非法({reason})"] += 1
                continue
            stats["add"] += 1
            final_signals.append(sig)
            final_posts.append(g["post"])

        # 默认保留：未被任何 verdict 覆盖的信号。verify 只负责「显式 drop 掉的误报」，
        # 未提及 ≠ 判为误报——静默丢弃会系统性丢失真实信号（鸟瞰股市 144→83 的根因）。
        for i, g in enumerate(grp):
            vidx = start + i
            for j, s in enumerate(g["signals"]):
                if (vidx, j) not in judged:
                    stats["未评默认保留"] += 1
                    final_signals.append(s)
                    final_posts.append(g["post"])

        batch_lo = batch_hi
        print(f"✓ keep={stats['keep']} fix={stats['fix']} drop={stats['drop']} add={stats['add']} "
              f"未评={stats['未评默认保留']} 越界={stats['vidx 越界'] + stats['sig 越界']}")

    return final_signals, final_posts, stats


def dedup_and_sort(signals):
    """去重：scored 同日同周期同方向同指数→1 条（保留当天最晚发布）；unscored 按
    (date, d, idx, summary) **精确**去重——同帖多条不同长线表述各自保留，不再按字面量
    "unscored" 塌成一桶（F1：此前同 d 的两条不同长线表述只留 1 条）。"""
    seen = {}
    for s in signals:
        date = s["pub"][:10]
        if s["cat"] == "scored":
            key = (date, "scored", s.get("spec"), s["d"], s["idx"])
        else:
            key = (date, "unscored", s["d"], s["idx"], s["summary"])
        cur = seen.get(key)
        if cur is None or s["pub"] > cur["pub"]:
            seen[key] = s
    return sorted(seen.values(), key=lambda s: s["pub"])


def consensus_key(sig):
    """多次运行共识的信号键：scored 用 (pub, spec, d, idx)；unscored 用 (pub, d, idx, summary)
    ——unscored 同一表述跨 run 重复自动消（summary 同），不同表述各自成键（F1 不再塌桶）。
    含 idx：同日同周期同方向的预测若针对不同指数是两条独立信号，不得合并。"""
    if sig["cat"] == "scored":
        return (sig["pub"], "scored", sig["spec"], sig["d"], sig["idx"])
    return (sig["pub"], "unscored", sig["d"], sig["idx"], sig["summary"])


def consensus_merge(runs_signals, min_votes):
    """合并多次运行结果：scored 只保留出现次数 ≥ min_votes 的信号，summary/target 取出现
    最多次的；unscored **不投票**——逐条 union（unscored 永不计分，跨 run 不同表述都是博主
    真实说过的长期观点，重复表述由末尾 dedup 收敛）。"""
    votes = {}
    for sig in runs_signals:
        k = consensus_key(sig)
        d = votes.setdefault(k, {"n": 0, "summaries": Counter(), "targets": Counter(),
                                 "template": sig})
        d["n"] += 1
        d["summaries"][sig["summary"]] += 1
        if sig.get("target") is None:
            d["targets"]["__absent__"] += 1
        else:
            d["targets"][sig["target"]] += 1
    merged = []
    for k, d in votes.items():
        if d["template"]["cat"] == "scored" and d["n"] < min_votes:
            continue
        sig = dict(d["template"])
        sig["summary"] = d["summaries"].most_common(1)[0][0]
        if d["targets"]:
            top_val, _top_n = d["targets"].most_common(1)[0]
            if top_val != "__absent__":
                sig["target"] = top_val  # 目标位多数一致才保留（平局偏缺席=不发明）
        merged.append(sig)
    return dedup_and_sort(merged)


def scan_target_flags(signals):
    """L4 代码验 d（只 flag、永不改写——target 语义按用户 2026-09-09 裁决已收窄，条件/支撑位
    句不填 target，故真 target 在场时 sign(target−ref) 应与 d 同号；异号 = 提取可疑，人审）。

    conflict   = sign(target−ref) ≠ d（target 张冠李戴 / d 判反）
    range_suspect = 方向一致但 |target−ref|/ref > 20%（量级可疑）
    no_ref     = 行情未覆盖发帖时刻（跳过不判）
    只打日志/控制台，不进 curated 行（样本 A/B diff 与复核队列用）。"""
    conflicts, range_sus = [], []
    no_ref = 0
    for s in signals:
        if s.get("cat") != "scored" or s.get("target") is None:
            continue
        ref, ok = o_ref.ref_price_at(s["idx"], s["pub"])
        if not ok:
            no_ref += 1
            continue
        v = o_ref.target_d_check(s["target"], ref, s["d"])
        if v == "conflict":
            conflicts.append((s, ref))
        elif v == "agree" and abs(float(s["target"]) - ref) / ref > 0.20:
            range_sus.append((s, ref))
    if not conflicts and not range_sus:
        if no_ref:
            print(f"  [代码验 d] 有 target 的 scored 行均与参考价同向（no_ref={no_ref} 条行情未覆盖未验）")
        return
    print(f"  [代码验 d] flag（只审不改，人工复核队列）: conflict={len(conflicts)} "
          f"range_suspect={len(range_sus)} no_ref={no_ref}")
    for s, ref in conflicts:
        print(f"    ⚠ conflict {s['pub']} {s['idx']} d={s['d']:+d} target={s['target']:g} "
              f"ref≈{ref:.0f} → {s['summary']}")
    for s, ref in range_sus[:5]:
        print(f"    ? range   {s['pub']} {s['idx']} d={s['d']:+d} target={s['target']:g} "
              f"ref≈{ref:.0f}（偏离 {abs(float(s['target']) - ref) / ref:.0%}）→ {s['summary']}")


def _batch_disposition(result, batch_posts):
    """报告批逐帖到案核算（L1/F2）：rows ∪ no_view == 全批。返回 (missing_post_ns, nv_clean)。

    rows 侧口径与 opinion.annotate 一致 = 模型**给过行**的帖号（取自原始 rows 的合法 post_n，
    行本身过不过 normalize 不影响——该帖已"被考虑"）；no_view 去冗余复用 _clean_no_view
    （rows∩no_view 重叠以 rows 为准 / 重复保首个 / 理由出枚举按覆盖处理，类别仅供人眼审计）。"""
    raws = result.get("rows")
    pns = []
    if isinstance(raws, list):
        for r in raws:
            if not isinstance(r, dict):
                continue
            try:
                pn = int(r.get("post_n", -1))
            except (TypeError, ValueError):
                continue
            if 0 <= pn < len(batch_posts):
                pns.append(pn)
    nv_raw = result.get("no_view")
    nv_clean, warns = o_ann._clean_no_view(nv_raw if isinstance(nv_raw, list) else [],
                                           pns, len(batch_posts))
    for w in warns:
        print(f"      …{w}")
    covered = set(pns) | {e["post_n"] for e in nv_clean}
    missing = [i for i in range(len(batch_posts)) if i not in covered]
    return missing, nv_clean


def extract_once(client, blogger, eval_posts, bodies, batch_size, no_verify, no_disposition,
                 run_label=""):
    """单次完整运行：分批提取（字符预算打包 + 发帖现值注记 + 逐帖到案门）+ 自查。

    到案门（L1/F2，默认开，--no-disposition 关）：批内每条 [i] 帖必须 rows ∪ no_view 全到案；
    缺 → 带错重试 1 次 → 仍缺 → **只丢未到案的帖、保留已到案帖的有效行** + loud log（旧代码
    本就静默跳读，保留有效行严格优于整批丢弃——不污染 curated 文件，缺口留在日志让人审）。

    返回 (signals, verify_stats, failed_batches, elapsed, dispo)。dispo 计数 到案无观点帖
    (no_view:<理由>) 与 重试后仍未到案 帖数，供充分性审计（A/B 列）。"""
    all_signals, all_posts_ref = [], []
    all_dropped = Counter()
    dispo = Counter()
    start_time = time.time()
    failed_batches = 0
    batches = list(build_batches(eval_posts, batch_size, bodies))
    for batch_num, batch_posts in enumerate(batches, 1):
        label = f"{run_label}Batch {batch_num}/{len(batches)}"
        print(f"  {label} {len(batch_posts)} 条...", end=" ", flush=True)
        # 发帖时刻现值注记（与打分器 ref_price 同源；行情未覆盖的帖 → None 不发）
        notes = [o_ref.pub_note((p.get("publish_date") or "").strip()) for p in batch_posts]
        msg = o_ann.render_batch(blogger, batch_posts, bodies, style="middle",
                                 limit=PER_POST_LIMIT, notes=notes)
        msg += _REPORT_EXTRACT_SUFFIX
        if not no_disposition:
            msg += _REPORT_DISPOSITION_SUFFIX

        ok, posts_aligned, dropped = [], [], Counter()
        missing = []
        result = None
        try:
            for attempt in (1, 2):
                user_message = msg
                if attempt == 2:
                    if not missing:
                        break
                    fb = ("\n\n[系统纠错] 上次输出未通过到案校验：帖子 %s 未到案（既不在 rows 也"
                          "不在 no_view），须逐条交代。请重新输出**整个** JSON（rows + no_view "
                          "全部重给，勿只给改动行）。" % ",".join(map(str, missing)))
                    user_message = msg + fb
                    print("缺到案 %d 帖，带错重试..." % len(missing), end=" ", flush=True)
                result, _ = call_json(client, SYSTEM_PROMPT, user_message, label, thinking=False)
                if result is None:
                    break  # 三连重试后仍失败 → 外层记 failed_batches
                raws = result.get("rows")
                if not isinstance(raws, list):
                    raws = []
                ok, dropped, posts_aligned, pns = validate_signals(raws, batch_posts)
                if no_disposition:
                    break
                missing, nv_clean = _batch_disposition(result, batch_posts)
                for e in nv_clean:
                    dispo[f"no_view:{e['reason']}"] += 1
                if not missing:
                    break
            else:
                # 重试仍缺到案：保留有效行、只丢未到案帖（loud——充分性缺口要人看得见）
                dispo["重试后仍缺到案"] += len(missing)
                print(f"!! 重试后仍 {len(missing)} 帖未到案，丢帖保留有效行: {missing}", end=" ")
        except Exception as e:
            result = None
            print(f"ERROR: {e}", end=" ")

        if result is None:
            failed_batches += 1
            print("FAILED after %d retries, skipping batch" % MAX_RETRIES)
            continue
        all_signals.extend(ok)
        all_posts_ref.extend(posts_aligned)
        all_dropped.update(dropped)
        print(f"✓ {len(ok)} 信号 | 累计 {len(all_signals)} | 批内丢 {sum(dropped.values())} 行")
        if batch_num < len(batches):
            time.sleep(0.5)

    if all_dropped:
        print(f"  行级丢弃(全 run): "
              + ", ".join(f"{k}={v}" for k, v in all_dropped.most_common(8)))
    extract_elapsed = time.time() - start_time
    verify_stats = None
    if not no_verify and all_signals:
        print(f"  {run_label}[自查] 回喂 {len(all_signals)} 条信号...", flush=True)
        t0 = time.time()
        all_signals, all_posts_ref, verify_stats = verify_signals(
            client, all_signals, all_posts_ref, bodies, blogger)
        print(f"  {run_label}[自查] 完成，耗时 {time.time() - t0:.0f}s")
    return all_signals, verify_stats, failed_batches, extract_elapsed, dispo


def main():
    parser = argparse.ArgumentParser(description="DeepSeek 自动提取 Direction 方向信号")
    parser.add_argument("blogger", help="博主名（data/posts/<名>.json）")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="每批帖子数")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条帖子（冒烟测试）")
    parser.add_argument("--since", default="",
                        help="只处理 YYYY-MM-DD 及之后发布的帖子（样本窗口；默认取 2026-01-01 起全量）")
    parser.add_argument("--out", default="", help="输出文件路径（默认 data/direction_signals/<名>.json）")
    parser.add_argument("--runs", type=int, default=1, help="完整运行次数（≥2 时按多数共识合并，推荐 3）")
    parser.add_argument("--no-verify", action="store_true", help="跳过信号自查")
    parser.add_argument("--no-disposition", action="store_true",
                        help="关逐帖到案门（不加到案契约后缀、不强制每帖 rows∪no_view，=旧行为）")
    parser.add_argument("--dry-run", action="store_true", help="不调 API、不写文件")
    args = parser.parse_args()

    blogger = args.blogger
    all_posts, eval_posts, pre_count, bodies = load_posts_and_bodies(blogger)
    if all_posts is None:
        sys.exit(1)
    if args.runs < 1:
        print("ERROR: --runs 至少为 1")
        sys.exit(1)

    if args.since:
        # 样本窗口：在 ≥2026-01-01 之上再收窄（A/B 用；文件序保持新→旧）
        eval_posts = [p for p in eval_posts
                      if (p.get("publish_date") or "").strip()[:10] >= args.since]
    if args.limit > 0:
        eval_posts = eval_posts[:args.limit]

    total_eval = len(eval_posts)
    total_batches = (total_eval + args.batch_size - 1) // args.batch_size  # 上限估（实为字符预算打包，≈此数）
    runs_count = args.runs if args.limit == 0 else 1  # 冒烟(--limit)只跑一次
    min_votes = (runs_count // 2) + 1 if runs_count > 1 else 1

    print("=" * 60)
    print(f"Direction 信号提取（DeepSeek {MODEL}）：{blogger}")
    print("=" * 60)
    print(f"帖子总数: {len(all_posts)} | 2026 前剔除: {pre_count} | 参与提取: {total_eval}"
          + (f"（窗口 ≥{args.since}）" if args.since else ""))
    print(f"批数(估): ≤{total_batches}（字符预算 {BATCH_CHAR_BUDGET}/帖上限 {PER_POST_LIMIT}）| "
          f"自查: {'开' if not args.no_verify else '关'} | 到案门: {'开' if not args.no_disposition else '关'} | "
          f"运行: {runs_count} 次")

    if args.dry_run:
        print(f"\n[DRY RUN] 将向 DeepSeek 发送 ≈{total_batches} 批帖子 × {args.runs} 次（不调 API、不写文件）")
        return

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY 环境变量未设置（只经环境变量传入，绝不写入文件）")
        print("  export DEEPSEEK_API_KEY='sk-...'")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=120.0)  # 120s 超时：防止 DeepSeek API 调用挂死整轮提取（2026-08-31 红红火火的老牛哥曾卡 99 分钟）

    start_time = time.time()
    all_candidates, all_verify, total_failed = [], [], 0
    all_dispo = Counter()

    print(f"\n[提取] {runs_count} 次运行（共识阈值 ≥{min_votes}/次）..." if runs_count > 1 else "\n[提取] 单次运行...")
    for r in range(1, runs_count + 1):
        if runs_count > 1:
            print(f"\n── 运行 {r}/{runs_count} ──")
        signals, vstats, failed, ee, dispo = extract_once(
            client, blogger, eval_posts, bodies, args.batch_size, args.no_verify,
            args.no_disposition, run_label=f"[Run {r}] " if runs_count > 1 else "")
        all_candidates.extend(signals)
        all_dispo.update(dispo)
        if vstats:
            all_verify.append(vstats)
        total_failed += failed
        if runs_count > 1:
            print(f"  Run {r} 完成: {len(signals)} 条（提取 {ee:.0f}s）")

    if runs_count > 1:
        print(f"\n[共识] {len(all_candidates)} 条候选 → scored 保留 ≥{min_votes} 次运行都出现的信号"
              f"（unscored 不投票、逐条 union）...")
        signals = consensus_merge(all_candidates, min_votes)
    else:
        signals = dedup_and_sort(all_candidates)

    cat_counts = Counter(s["cat"] for s in signals)
    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"✅ 提取完成: {blogger} | 总耗时 {elapsed:.0f}s | 失败批次 {total_failed}")
    print(f"参与提取: {total_eval} | 运行 {runs_count} 次 | 提取信号: {len(signals)}")
    print(f"  按 cat: {dict(cat_counts)}")
    if all_verify:
        k = sum(v.get("keep", 0) for v in all_verify)
        f_ = sum(v.get("fix", 0) for v in all_verify)
        d_ = sum(v.get("drop", 0) for v in all_verify)
        a = sum(v.get("add", 0) for v in all_verify)
        print(f"  自查合计(跨运行): keep={k} fix={f_} drop={d_} add={a}")
    if all_dispo and not args.no_disposition:
        nv_n = sum(v for k_, v in all_dispo.items() if k_.startswith("no_view:"))
        nv_detail = " ".join(f"{k_[8:]}×{v}" for k_, v in sorted(all_dispo.items())
                             if k_.startswith("no_view:"))
        print(f"  到案(逐帖): 无观点帖 {nv_n}（{nv_detail or '—'}）| "
              f"重试后仍缺 {all_dispo.get('重试后仍缺到案', 0)}")
    scan_target_flags(signals)

    partial = args.limit > 0
    if partial and not args.out:
        print("\n[部分运行] 仅处理前 %d 条，未写正式文件（加 --out 可写指定路径）" % args.limit)
        return

    out_path = args.out or os.path.join(PROJECT_ROOT, "data", "direction_signals", f"{blogger}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"blogger": blogger, "signals": signals}, f, ensure_ascii=False, indent=2)
    print(f"输出: {out_path}（{len(signals)} 条信号）")

    # ── 可复现性记录（gitignored，仅本地溯源）──
    try:
        meta_path = os.path.join(os.path.dirname(out_path), f"_{blogger}_run.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "blogger": blogger,
                "model": MODEL,
                "runs": runs_count,
                "min_votes": min_votes,
                "batch_size": args.batch_size,
                "verify": not args.no_verify,
                "posts_total": len(all_posts),
                "posts_eval": total_eval,
                "signals": len(signals),
                "cat": dict(cat_counts),
                "signals_with_target": sum(1 for s in signals if s.get("target") is not None),
                "disposition": not args.no_disposition,
                "no_view_posts": sum(1 for k_, v in all_dispo.items()
                                     if k_.startswith("no_view:") for _ in range(v)),
                "failed_batches": total_failed,
                "extracted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f, ensure_ascii=False, indent=2)
        print(f"运行记录: {meta_path}（gitignored，仅本地溯源）")
    except Exception as e:
        print(f"WARN: 写运行记录失败: {e}")


if __name__ == "__main__":
    main()
