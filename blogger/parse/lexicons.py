# -*- coding: utf-8 -*-
"""02§10.1／§10.2 的家底 —— 五张词典与两个判据。**从 02 的现成表逐行翻出来，不新增事实源。**

这一层只干两件事，都不涉及语义判断：

- **查表** —— 时间词（§4.1）、对象词（§5.2）、方向词（§3.1）翻成编码，由 `hints.py` 摆到帖文
  旁边。**这是给模型减负**：它划表述的边界、落 `spec` 与 `idx`、抄引文，查表这一步不用它自己扛。
- **守门** —— `has_cond` 判一句是不是条件句（§3.2）。**全部家底里唯一一处会删行的判断。**

**词典永远有漏。** 模型答出表里没有的词，不是错 —— 那是缺口信号。所以这里宁缺毋滥：
**拿不准的词一律不收**，让缺口暴露出来，好过收一个似是而非的。

方向词是开放类（「高位反复筑顶」这类说法追不全），时间词与对象词是闭集。**方向词那一栏
只喂提示，不参与判决** —— 表里的值是词义层面的，句义层面的翻转（「不会大涨」）归模型，
所以 `hints.py` 只摆原话、不摆值。

**两条纪律。** `has_cond` 与它那七类排除正则**冻结** —— 改一次就是换一次守门口径，要走文档。
`TIME_WORDS`／`DIR_WORDS`／`_OBJ_WORDS` 从此只喂提示词，**已经不可能删任何一行**，
往后可以放心加宽：加错了最坏是把模型带偏，不会误杀。
"""

from __future__ import annotations

import re

from blogger.common import market

# ── T 时间词 → spec（02§4.1 全表）────────────────────────────────────────

# 固定词表。**同一位置取最长匹配**，所以这里不必按长度排。
TIME_WORDS: dict[str, str] = {
    # long
    "下半年": "long", "全年": "long", "今年": "long", "明年": "long",
    "中长期": "long", "未来几个月": "long", "长线": "long", "最终": "long",
    "始终": "long", "三年": "long",
    # nweek 一族（「下周X」）—— 长词在前只是好读，匹配按最长
    "下周一": "nmonday", "下周二": "ntuesday", "下周三": "nwednesday",
    "下周四": "nthursday", "下周五": "nfriday",
    "下周末": "nweek", "下周初": "nmonday", "下周": "nweek",
    # nmonth / month
    "下个月": "nmonth", "下月": "nmonth",
    "月底": "month", "月末": "month",
    # week
    "本周内": "week", "本周": "week", "这周": "week",
    # 周几（没说「下周」的「周几」是**本周**那一天，02§4.1）
    "本周初": "monday",
    "周一": "monday", "周二": "tuesday", "周三": "wednesday",
    "周四": "thursday", "周五": "friday",
    # today
    "今天": "today", "今日": "today", "当天": "today",
    "下午": "today", "午后": "today", "尾盘": "today",
    # t1 / t2
    "明天": "t1", "明日": "t1", "次日": "t1", "后天": "t2",
    # t5 —— 「没说周期」的默认档由 §4.4 落，不在这里
    "未来几天": "t5", "当前阶段": "t5", "接下来": "t5",
    "近期": "t5", "短期": "t5", "很快": "t5", "马上": "t5",
    "即将": "t5", "不久": "t5", "临近": "t5",
    # 节前／节后没有精确终点，02§4.1 归到 t5 行
    "春节前": "t5", "春节之前": "t5", "节前": "t5", "节后": "t5",
    "假期前": "t5", "假期之前": "t5", "假期后": "t5", "假期归来": "t5",
    # long 那一族的补充 —— 「未来」单用落 long，但「未来几天」按最长匹配压过它
    "未来": "long", "后市": "long", "后续": "long", "后期": "long",
}

# 「N 天后／N 日内」与「N 个交易日」—— 数字走正则，不列进词表
# **已知缺口：前面是「第／前」的也照样匹配** —— 「第二天」读成 `t2`、「前一天」读成 `t1`，
# 而 §4.1 的 `tN` 行只写了「N天后／N日内」，这两个写法本来不在档位表里。全库 13543 条帖里
# 712 条（5.3%）的清单会带上这样一个词（2026-09-16 实测）。**明知而不修**：那一栏只喂提示、
# 不参与判决，强校验还会兜一道。判例复核时见到清单里的 `t2` 与模型落的 `spec` 不符，先看
# 这里。要收窄就在 `find_time_words` 里对 `at - 1` 回看一个「第／前」。
_N_DAY_RE = re.compile(r"(\d+|[一二三四五六七八九十两])\s*(?:个)?\s*(?:交易)?\s*[天日](?:\s*(?:内|后|之后|以后))?")

# 均线名不是时间词。语料里「60 日均线」「20 日线」「十日线」遍地都是，`_N_DAY_RE`
# 会把里面的 60／20／十 抓成时间窗口 —— 三位博主那份语料上这个模式命中 469 处、落在
# 386 句，落成 `long`／`t10`／`t20` 都出现过。更坏的是标记 `T` 会打在这些字上，模型照着
# 抄进 `tw`（`'一旦60日均线失守'` 实测出现过），错就从词典漏进了模型。所以匹配完要回看
# 后面跟的是什么。
_MA_TAIL_RE = re.compile(r"\s*(?:均线|线|级别|周期|MA|ma)")
# 「未来 N 个月」这类 —— 一律 long
_FUTURE_MONTH_RE = re.compile(r"未来\s*(?:\d+|[一二三四五六七八九十两])\s*个?月")
# 「8 月 20 日」这类具体日期 —— 落 `d:`，年份由 `hints._fill_year` 按发帖日补
_MD_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

T_MAX = market.T_MAX          # 20 个交易日；超过落 long（02§4.1）

# 本周的周几 —— §4.1「明天压过周几」压的就是这一档。下周的周几（`nmonday`…）不在此列：
# 「明天」与「下周一」不是同一天，不冲突。
WEEKDAYS: tuple[str, ...] = ("monday", "tuesday", "wednesday", "thursday", "friday")


def _num(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    return _CN_NUM.get(s)


def find_time_words(sentence: str) -> list[tuple[int, str, str]]:
    """这一句里的时间词 —— `[(位置, 原话, spec), …]`，按位置排。

    **同一位置取最长匹配**（「下周末」压过「下周」）。`d:` 与 `tN` 这两类由正则出，
    原话就是正则匹配到的那一段。
    """
    hits: list[tuple[int, str, str]] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    for word, spec in sorted(TIME_WORDS.items(), key=lambda kv: -len(kv[0])):
        start = sentence.find(word)
        while start >= 0:
            if free(start, start + len(word)):
                hits.append((start, word, spec))
                taken.append((start, start + len(word)))
            start = sentence.find(word, start + 1)

    for m in _FUTURE_MONTH_RE.finditer(sentence):
        if free(m.start(), m.end()):
            hits.append((m.start(), m.group(0), "long"))
            taken.append((m.start(), m.end()))

    for m in _MD_RE.finditer(sentence):
        if free(m.start(), m.end()):
            # 年份留空，`hints._fill_year` 按发帖日补 —— 这里只标出「有个具体日期」
            hits.append((m.start(), m.group(0), f"d:{int(m.group(1)):02d}-{int(m.group(2)):02d}"))
            taken.append((m.start(), m.end()))

    for m in _N_DAY_RE.finditer(sentence):
        if not free(m.start(), m.end()):
            continue
        if _MA_TAIL_RE.match(sentence, m.end()):
            continue                                        # 均线名，不是时间窗口
        n = _num(m.group(1))
        if n is None:
            continue
        hits.append((m.start(), m.group(0), f"t{n}" if n <= T_MAX else "long"))
        taken.append((m.start(), m.end()))

    return sorted(hits)


def ma_artifact(sentence: str, word: str) -> bool:
    """`word` 在这一句里出现时，后面跟的是不是均线名（「60 日**均线**」）。

    模型有时会照着标记把均线名抄进 `tw`（`'一旦60日均线失守'` 实测出现过）——
    `resolve_time` 拿它查表前先过这一关。
    """
    at = sentence.find(word)
    return at >= 0 and bool(_MA_TAIL_RE.match(sentence, at + len(word)))


def spec_of_word(word: str) -> str | None:
    """把一个时间词翻成档位 —— 表里没有返回 `None`（**不猜**）。"""
    if word in TIME_WORDS:
        return TIME_WORDS[word]
    if _FUTURE_MONTH_RE.fullmatch(word):
        return "long"
    m = _MD_RE.fullmatch(word)
    if m:
        return f"d:{int(m.group(1)):02d}-{int(m.group(2)):02d}"    # 年份待补
    m = _N_DAY_RE.fullmatch(word)
    if m:
        n = _num(m.group(1))
        if n is not None:
            return f"t{n}" if n <= T_MAX else "long"
    return None


# ── D 方向词（02§3.1「算」那几行 ＋ §3.3 操作动词）─────────────────────

# 原话 → 方向。**只用来标记「这一句带方向词」，不用来直接产出** ——
# 「不看空」落 `1` 这种语义翻转仍归模型。
DIR_WORDS: dict[str, int] = {
    # §3.1
    "看多": 1, "偏多": 1, "看涨": 1, "上涨": 1, "大涨": 1, "收阳": 1,
    "看空": -1, "偏空": -1, "看跌": -1, "下跌": -1, "大跌": -1, "收阴": -1,
    "震荡上涨": 1, "震荡下跌": -1,
    "弱势震荡": -1, "震荡调整": -1, "高位震荡回调": -1, "调整": -1,
    "不看空": 1, "不看跌": 1, "不要悲观": 1, "不会深跌": 1, "不会跌破": 1,
    "不看多": -1, "不看涨": -1, "不会大涨": -1, "不会创新高": -1,
    "有望涨": 1, "还有反弹空间": 1, "反弹修复": 1,
    "需防备再次跳水": -1, "要小心杀跌": -1,
    "高位反复筑顶": -1, "反复的诱多": -1,
    # §3.3 操作动词
    "减仓": -1, "清仓": -1, "轻仓": -1, "止盈": -1, "逢高抛": -1, "卖出": -1,
    "加仓": 1, "重仓": 1, "补仓": 1, "逢低买": 1, "抄底": 1,
    # 单字与常用变体 —— 只作标记，不改语义
    "涨": 1, "跌": -1, "新高": 1, "新低": -1, "反弹": 1, "回调": -1,
    "突破": 1, "跌破": -1, "走强": 1, "走弱": -1, "企稳": 1, "跳水": -1,
    "杀跌": -1, "上攻": 1, "拉升": 1, "下探": -1, "回暖": 1, "承压": -1,
}

# ── x 负例词（02§6 各格）—— 标出来只是提醒，判不判仍归模型 ─────────────

NEG_WORDS: tuple[str, ...] = (
    # 路径形态（先 A 后 B）
    "先抑后扬", "先跌后涨", "先扬后抑", "冲高回落", "探底回升", "高开低走", "低开高走",
    # 开盘形态
    "高开", "低开", "平开",
    # 状态假设
    "的时候", "之后", "之前",
    # 观察句
    "先看", "要看", "关注",
    # 仓位状态自述
    "满仓", "重仓", "轻仓", "空仓", "还剩", "拿着不动", "持股不动",
    # 立场自述
    "看法不变", "观点不变", "维持观点", "维持判断",
    # 投资理念
    "长期持有", "价值投资",
    # 转述他人
    "机构认为", "券商认为", "机构觉得", "券商觉得",
)

# ── ~ 模棱词（02§6 模棱两可 ＋ 表态度不给动作）──────────────────────────

VAGUE_WORDS: tuple[str, ...] = (
    "可能", "也许", "或许", "边走边看", "不好说", "看市场情绪", "即将变盘",
    "多看少动", "观望", "控制好仓位", "控制仓位", "注意风险", "谨慎",
)

# ── ! 条件词（02§3.2）──────────────────────────────────────────────────

COND_WORDS: tuple[str, ...] = (
    "如果", "假如", "倘若", "要是", "一旦", "万一",
    "除非", "假设", "的话", "若",
)

# **`!` 的口径是「一定是条件句」，不是「像条件句」。** 这一层照 `!` 丢产出，只认字面，
# 所以它宁可筛不完（条件句读成方向、没被拦下的，实测有），也不许冤枉一条。下面几类是
# 实测出来的「看着像条件、其实不是」，逐类抠掉再匹配。
#
# 一、同形子串 —— `要是` 是 `主要是` 的子串，`主要是这几点` 会被读成条件句。
# 「只要是」不在此列，那本来就是个条件。
COND_DECOY: tuple[str, ...] = ("主要是", "重要是")

# 二、口头禅与撇开不论 —— 「不出意外的话」是副词短语，「抛开外围涨跌影响的话」是撇开不
# 论，「按照这个现象的话」是归纳承接，「如此的话」是承接。都不是前提。
COND_CLICHE = re.compile(r"(?:不出意外的|抛开[^，。；]{0,10}的|如此的|按照[^，。；]{0,8}的)话")

# **已知缺口**：只靠「的话」触发的这一类，上面收不全 —— 「拆分今天的行情走势**来看的话**」
# 是说话的角度、「**换做是你的话**」是冲读者说的、「**这样的话**」是承接指代，都不是前提，
# 照样算条件句。`COND_VIEW` 也盖不住：它要求句首先有条件词，而这几种写法句首没有。
# 全库量：方向词落在条件句上的 3943 句里，269 句只靠「的话」触发，抽读约四分之一不是条件句。
# **判据多认不等于守门错筛** —— 守门只在模型产出的引文正落在这句上时才动手，而真动手的
# 那一批实测过 37/37。2026-09-16 定的先不修。

# 三、假设视角 —— 「如果要站在今天的角度来看」不是方向的前提，是说话的角度。
COND_VIEW = re.compile(r"(?:如果|若|要是|倘若|假如|假设)(?:说|是)?[，,]?\s*(?:单纯)?"
                       r"(?:要|再|就)?(?:从|站在|按照|以)[^，。；]{0,16}?(?:来看|来讲|来说|看|讲|论)")

# 四、冲着读者说的 —— 「再如果看不懂这轮春季趋势行情的话」的前提不在行情上，在读者身上。
COND_READER = re.compile(r"(?:再|又)?如果[^，。；]{0,20}?(?:看不懂|不明白|不懂|错过|不信)")

# 五、条件挂在半句上 —— 「若技术上出现低开，还是容易被护盘力量拉回的，**所以我认为**今天的
# A股市场走独立行情」：条件管的是前一个分句，承诺落在「所以」后面那一句上，无条件。
COND_HALF = re.compile(r"(?:所以|因此|因而|故此)[^。；]{0,12}?(?:我认为|我觉得|我看|预判|我的看法)")

# 六、承诺在条件之前 —— 「我觉得指数继续创新高是没有什么意外了，**因为一旦**指数形成突破
# 的走势…」：无条件的那一句摆在前头，条件是用来解释它的。
COND_AFTER = re.compile(r"我认为|我觉得|我看|预判|我的看法|唯一确定的就是|是确定性的|是确定的|已成定局|没有悬念")

# 七、让步与惯常 —— 「今天即便收跌，明天依旧看开门红」的主句无条件，是被让出来的；
# 「每个月一旦缩量调整过后」的「一旦」是「每当」，不是前提。
COND_YIELD = re.compile(r"(?:即便|即使|就算|哪怕)[^。；]{0,40}?(?:也|依旧|仍然|还是|同样)")
COND_HABIT = re.compile(r"一旦[^，。；]{0,12}?(?:过后|之后|以后)")


def has_cond(sentence: str) -> bool:
    """这一句是不是**一定是条件句**（02§3.2）。抠掉上面七类「像条件、其实不是」的写法
    之后，还剩条件词才算。**宁可筛不完，不许冤枉** —— 判「像」的那份活归模型。"""
    for d in COND_DECOY:
        sentence = sentence.replace(d, "")
    sentence = COND_CLICHE.sub("", sentence)
    if (COND_VIEW.search(sentence) or COND_READER.search(sentence)
            or COND_YIELD.search(sentence) or COND_HABIT.search(sentence)):
        return False
    first = min((sentence.find(w) for w in COND_WORDS if w in sentence), default=-1)
    half = COND_HALF.search(sentence)
    if first >= 0 and half and first < half.start():     # 条件只管前半句，承诺在后半句
        return False
    after = COND_AFTER.search(sentence)
    if first >= 0 and after and after.start() < first:   # 承诺在条件之前，条件只用来解释它
        return False
    return first >= 0


# ── O 对象词（02§5.1／§5.2）────────────────────────────────────────────

# 别名表直接取 `market.IDX_ALIASES`，不另抄一份 —— 那份是 02§5.2 的正本。
# 本名（八个）也算对象词，`market.VALID_IDX` 里就是它们。
_OBJ_WORDS: tuple[str, ...] = tuple(
    sorted(set(market.IDX_ALIASES) | market.VALID_IDX, key=len, reverse=True))


# 「其余板块一律忽略」的那张单子（02§5.2 末行 ＋ §6③）。**它们不是反例词，是不算数**
# —— 一句里点了「创新药」又没点任何指数，落 §5.4 默认上证指数是错的：§5.4 管的是
# 「未点名板块或指数」，点了板块的走 §5.2 末行 → 这条预测作废。
# **半导体／芯片不在此列** —— §5.2 把这两个映射到科创50，是别名不是忽略。
_SECTOR_CANDIDATES: tuple[str, ...] = (
    "有色", "钢铁", "医药", "创新药", "恒科", "电池", "航天", "军工", "房地产", "地产",
    "券商", "银行", "保险", "白酒", "煤炭", "石油", "农业", "消费", "新能源", "光伏",
    "汽车", "传媒", "游戏", "旅游", "港口", "电力", "机械", "化工", "建材", "家电",
    "纺织", "养殖", "种业", "黄金", "稀土",
)

# 别名表认得的（券商／银行／保险／白酒 → 上证50，半导体／芯片 → 科创50）**不是忽略项**
# —— 从候选里剔掉，剩下的才进这张单子。这样 §5.2 改动时这里自动跟上。
IGNORED_SECTORS: tuple[str, ...] = tuple(
    w for w in _SECTOR_CANDIDATES if market.normalize_idx(w) not in market.VALID_IDX)


# 说的是**整个市场**、不是某一个板块的词。句子点了其中一个，对象就是它 ——
# §5.4 的默认照落，附带提到的板块只是论据（「支持 A 股延续趋势向上…主要是科技和
# 内需消费」讲的是 A 股，不是消费板块）。「大盘」「指数」不在此列 —— 它们在 §5.2 里
# 是上证指数的别名，`find_objects` 已经认了。
# 「行情」「盘面」**不收** —— 会撞上「大行情」「跨年行情」，那是子串，不是「整个市场」。
MARKET_WORDS: tuple[str, ...] = ("A股", "a股", "股市", "市场", "两市", "全市场")


def has_ignored_sector(sentence: str) -> str | None:
    """这一句里点到的第一个被忽略的板块词 —— 没有、或说的是整个市场，返回 `None`。"""
    if any(w in sentence for w in MARKET_WORDS):
        return None
    for word in IGNORED_SECTORS:
        if word in sentence:
            return word
    return None


def find_objects(sentence: str) -> list[tuple[int, str, str]]:
    """这一句里的对象词 —— `[(位置, 原话, 指数), …]`。

    **只认 02§5.2 的正本**（`market.IDX_ALIASES` ＋ 八个本名），其余板块词一律不算 ——
    §5.2 说「其余板块一律忽略」。所以「有色」「军工」在这里不是对象词，模型若据此产
    信号，`schema` 的强校验会把它挡下。
    """
    hits: list[tuple[int, str, str]] = []
    taken: list[tuple[int, int]] = []
    for word in _OBJ_WORDS:
        start = sentence.find(word)
        while start >= 0:
            if all(start + len(word) <= x or start >= y for x, y in taken):
                hits.append((start, word, market.normalize_idx(word)))
                taken.append((start, start + len(word)))
            start = sentence.find(word, start + 1)
    return sorted(hits)


# 抹尾时认的后缀 —— 同一个对象的写法不同，不是另一个对象。**「券商股」靠它归到上证50**
# （§5.2 的「券商」）；不抹的话它会一路落到 §5.4 的默认上证指数，那是另一个指数。
_OBJ_TAIL: tuple[str, ...] = ("指数", "板块", "股")


def obj_of_word(word: str) -> str | None:
    """把一个对象词翻成指数 —— 表里没有返回 `None`（**不猜**）。

    末尾多一个「指数」「板块」「股」的（「上证50指数」「证券板块」「券商股」）先抹掉再查
    —— 那是量词的写法不同，归一是形态活。「证券板块」抹掉后撞上 §5.2 的「证券」→ 上证50；
    「科技板块」抹掉后是「科技」，表里没有，走 `sector_word`。
    """
    tail = next((word[:-len(s)] for s in _OBJ_TAIL if word.endswith(s)), word)
    for w in (word, tail):
        idx = market.normalize_idx(w)
        if idx in market.VALID_IDX:
            return idx
    return None


def sector_word(word: str) -> str | None:
    """`word` 是不是「其余板块」的说法 —— §5.2 末行那张单子管的那些。

    两条判据：落在 `IGNORED_SECTORS` 具名单子里的（「创新药」「军工」），
    或以「板块」「股」收尾的（「低位板块」「科技板块」「硬科技股」—— 泛指某板块、
    又没说哪个）。

    **认得出的别名不在此列** —— 「券商股」「白酒股」「证券板块」由 `obj_of_word` 先认下，
    走的是 §5.2 的映射，不是忽略。

    **「指数」收尾的不在此列** —— 「各大指数」「全市场」是泛指大盘，走 §5.4 默认落上证
    指数是对的。点名了别的指数（「中证2000」）是 §5.1 的事，另说。

    **说的是整个市场的不在此列** —— 「A股」以「股」收尾纯是巧合，它归 §5.4 默认
    （`MARKET_WORDS`）。不排掉的话这一条会把「A股」判成板块，一次误伤一百多条。
    """
    if word in IGNORED_SECTORS:
        return word
    if word in MARKET_WORDS or obj_of_word(word):     # 整个市场、或认得出的别名
        return None
    return word if word.endswith(("板块", "股")) else None


def marks_of(sentence: str) -> str:
    """一句的标记串（`TD!` 这种）。标记是提示，不是判决。"""
    out = ""
    if find_time_words(sentence):
        out += "T"
    if any(w in sentence for w in DIR_WORDS):
        out += "D"
    if find_objects(sentence):
        out += "O"
    if has_cond(sentence):
        out += "!"
    if any(w in sentence for w in NEG_WORDS):
        out += "x"
    if any(w in sentence for w in VAGUE_WORDS):
        out += "~"
    return out


__all__ = ["TIME_WORDS", "DIR_WORDS", "NEG_WORDS", "VAGUE_WORDS", "COND_WORDS",
           "COND_DECOY", "has_cond", "WEEKDAYS", "T_MAX", "IGNORED_SECTORS",
           "MARKET_WORDS", "ma_artifact",
           "find_time_words", "find_objects", "spec_of_word", "obj_of_word",
           "sector_word", "has_ignored_sector", "marks_of"]
