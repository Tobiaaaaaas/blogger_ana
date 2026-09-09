# -*- coding: utf-8 -*-
"""共享文本层：帖子标题/正文解析、登录墙识别、可读性过滤、相对时间词剥离、博主名规整。

把两份旧实现收敛为单一版本，供 推送(briefing) / 报告(scripts/pipeline/extract_signals_direction)
同源使用：
- extract_signals_direction.py 的 _truncate / post_text（登录墙 / 标题正文并列 / 微帖只显一次）
- briefing/scripts/summarize.py 的 _norm_blogger / _strip_rel_time / MAX_POST_CHARS 头部截断

本模块只依赖 stdlib，不 import briefing——离线裸脚本可干净导入。
"""
import re

# 相对日周词剥离（v12 系统侧兜底，不靠模型自觉）：头行 anchor 与引文绝对时间已把博主
# 相对词锚定到具体日期，摘要再出现 今天/明天/本周 只会制造"昨天说的明天"式错位 → 一律剔除。
# 周X（周五）、周初/周中/周内等"锚定周内"表述与纯数字日期保留（周由头行 anchor 钉住）。
_REL_TIME_RE = re.compile(
    r"(今天|今日|明天|明日|昨天|昨日|后天|本周|下周|上周|近日|当周)"
    r"(?![一二三四五六日末初内天])"
)

_LOGIN_WALL_MARKS = ("登录", "验证码")  # 手机登录/扫码登录/获取验证码 占位，非真实正文


def strip_rel_time(s):
    """剔除文本里的相对日周词（今天/明天/本周/下周/近日…），防"昨天说的明天"式错位。"""
    if not s:
        return s
    s = _REL_TIME_RE.sub("", s)
    s = s.lstrip("，。；、 ")
    s = re.sub(r"[，。；]{2,}", lambda m: m.group(0)[0], s)  # 剔除后"，，"→"，"
    return re.sub(r"\s+", " ", s).strip()


def norm_blogger(s):
    """把模型/行头回填的博主名规整成 panel 原名：剥行头残余的（所属板块…）注解前缀/后缀。"""
    s = (s or "").strip()
    s = s.split("（")[0].split("(")[0].strip()
    s = s.removeprefix("【博主】").strip()
    return s


def is_login_wall(body):
    """登录墙占位（手机登录/扫码登录/获取验证码）非真实正文。"""
    return bool(body) and all(m in body for m in _LOGIN_WALL_MARKS)


def is_drop_content(content):
    """可读性过滤：视频帖占位 / 无正文短帖（推送窗口读帖与摘要共用口径）。"""
    c = (content or "").strip()
    return c == "[视频帖]" or len(c) < 5


def truncate(text, limit=1200, style="head"):
    """正文截断。

    - style="head"（推送）：从头截前 limit 字（足够承载一篇观点帖）加"已截断"标注。
    - style="middle"（报告/自查，整语料）：**≤ limit 全量返回**；超过 limit 中间省略、保头保尾，
      头 ~60% 尾 ~40%（合计≈limit）——2026-09-09 D4 长帖全文口径：报告把 limit 提到 4000 后，
      1200~4000 字帖不再被截，>4000 才按比例保头保尾（长文结论常落在中后段，40% 尾比旧 250 字多留）。
    """
    if not text or len(text) <= limit:
        return text
    if style == "middle":
        head = int(limit * 0.6)
        return text[:head] + "\n...[省略中间内容]...\n" + text[-(limit - head):]
    return text[:limit] + "…（已截断）"


# ── quote 逐字校验（2026-09-08 解析加固：结果强制标准——quote 必须是帖子原文逐字片段，
# 模型只许用省略号跨段，不许改写/润色/拼凑/编造。此前代码从不校验 quote 真伪，模型截断
# 拼接丢掉 明天/本周 也能通过全部校验上卡（子房 3900-3950 #J/#N）。）
#
# 2026-09-09 版式归一校准（Mac dry-run 实发发现）：微博/雪球常见"一句一换行"散文帖，源文
# 每分句一行（\n 分隔），模型引成一句时自然把换行折成逗号/顿号——字一个没少、顺序没动，
# 字节级逐字却判编造，重试也救不回（模型不明白错在哪，3 次外层同样失败 → 整博主按失败置空）。
# 故匹配前对两侧做**版式归一**：空白与 CJK 句读标点视为透明（不算原文差异），只验实词保序
# 连续——门的能力边界仍是"字级增删/改写/串帖/逆序"必拒（字符真伪归这门），"句首时间词被截"
# 属 #J/#N 类由 prompt 句首纪律 + Pillar C 兜（漏字后剩余片段仍连续，本门照旧放行，同验证用例）。
# 注意归一**不含** ASCII 点号/连字符（3.5万 3900-3950）——防 量级/区间 错位混入。──
_QUOTE_ELLIPSIS = re.compile(r"…+|\.{3,}")
# 透明字符 = 全部空白（含全角） + CJK 句读标点/引号/括号/破折。ASCII 数字/小数/连字符不归。
_VERBATIM_TRANSPARENT = re.compile(
    r"[\s　，。、；：？！“”‘’「」『』《》〈〉（）【】〔〕…—～]+")


def split_quote(quote):
    """按省略号把 quote 切成逐字片段（…/... 视为模型跨段标记，不计入原文校验）。"""
    if not quote:
        return []
    return [p for p in _QUOTE_ELLIPSIS.split(quote) if p]


def _verbatim_norm(s):
    """逐字校验前版式归一：只去 空白 + CJK 句读（见 _VERBATIM_TRANSPARENT）。"""
    return _VERBATIM_TRANSPARENT.sub("", s or "")


def verbatim_in(quote, text):
    """quote 是否由 text 的**逐字保序片段**构成：每片段（按省略号切）归一空白/句读后须为
    text 同归一的**连续**子串，片段按序、之间允许省略号桥接任意间隔。任一片段匹配不上 →
    编造/改写/串帖，False。字级差异（增删/改写/逆序）必拒；行与句读折叠不视为改写。"""
    t = _verbatim_norm(text)
    cursor = 0
    for chunk in split_quote(quote):
        c = _verbatim_norm(chunk)
        if not c:
            continue
        pos = t.find(c, cursor)
        if pos < 0:
            return False
        cursor = pos + len(c)
    return True


def resolve_post(post, bodies=None):
    """一帖 → (title, body) 供共享标注输入（标题正文并列，微帖只显一次）。

    优先级：
    - 标题：正文分片 bodies[post_id].title → 合并后 post.title
    - 正文：正文分片 bodies[post_id].body（剔除登录墙占位）→ 已合并 post.content
    微帖（正文即标题，一句话预测）正文去重——标题由行头「｜标题」呈现，正文不再重复。
    """
    b = {}
    if bodies and isinstance(bodies, dict):
        raw = bodies.get(str(post.get("post_id", "")))
        if isinstance(raw, dict):
            b = raw
    btitle = (b.get("title") or "").strip()
    bbody = (b.get("body") or "").strip()
    if is_login_wall(bbody):
        bbody = ""
    title = btitle or (post.get("title") or "").strip()
    body = bbody or (post.get("content") or "").strip()
    if title and body and title == body:
        body = ""  # 微帖：标题即正文，只显示一次
    return title, body
