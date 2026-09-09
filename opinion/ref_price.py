# -*- coding: utf-8 -*-
"""共享参考价（SKILL §4 口径）+ 发帖时刻行情注记。

2026-09-09 报告链复核（L0/L2）：把 run_direction 内联的行情装载与 ref_price_at 收敛到本模块，
让「提取时注入模型的发帖现值」(pub_note) 与「打分时锚定的参考价」(ref_price_at) **严格同源**——
模型据以判 d 的数字 = 引擎据以打分/校验 d 的数字，杜绝两侧口径分叉（此前提取端完全没有现价，
点位句 d 靠模型凭旧记忆猜；打分端有价，两端对不上）。

语义（与 run_direction 旧实现一致，除整点边界修正 D2）：
- 交易时间中（9:30~11:30、13:00~15:00）→ 所处 30 分钟 K 线开盘价：取**首根 t > hhmm** 的 bar 的
  open（bar 时间=收盘时间）。用严格大于：恰好整点发帖（如 10:00:00）取的是该时刻**刚开盘**那根
  bar 的 open = 该时刻现价，不再回落上一根（旧 `t >= hhmm` 让 10:00 发帖拿到 09:30 价、10:01 反而
  拿到 10:00 价——10:00 比 10:01 还"旧"一档的反直觉怪癖）。
- 非交易时间 → 上一根 30 分钟 K 线收盘价（午休→11:30 close；盘后≥15:00→当日 15:00 close；
  盘前<9:30 / 非交易日→上一交易日 15:00 close）。

本模块只依赖 stdlib；导入即装载行情（data/market/market_data.json 日线 + intraday/*_30min.json），
与 run_direction 各载一份（本模块为提取端、run_direction 为打分端共享同一份取价逻辑）。
"""
import json
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # …/opinion → repo 根
MARKET_PATH = os.path.join(ROOT, 'data', 'market', 'market_data.json')
INTRADAY_DIR = os.path.join(ROOT, 'data', 'market', 'intraday')

IDX_ALIASES = {'上证综指': '上证指数', '上证': '上证指数', '综指': '上证指数'}

# 有 30 分钟线的指数（= market_data 7 主指数；无深证成指）。注记顺序：上证打头，创业板次之。
NOTE_INDICES = ["上证指数", "创业板指", "沪深300", "上证50", "中证500", "中证1000", "科创50"]


def normalize_idx(idx):
    return IDX_ALIASES.get(idx, idx)


def _load_market():
    with open(MARKET_PATH, encoding='utf-8') as f:
        return json.load(f)


def _load_intraday():
    """{idx: [(date, [(hhmm, bar), ...]), ...]}（按 date 升序；缺文件跳过）。"""
    out = {}
    for idx in NOTE_INDICES:
        p = os.path.join(INTRADAY_DIR, f'{idx}_30min.json')
        if not os.path.exists(p):
            continue
        with open(p, encoding='utf-8') as f:
            bars = (json.load(f) or {}).get('bars', [])
        bydate = {}
        for b in bars:
            day, hhmm = b['time'][:10], b['time'][11:16]
            bydate.setdefault(day, []).append((hhmm, b))
        out[idx] = sorted((day, sorted(rows)) for day, rows in bydate.items())
    return out


MARKET = _load_market()
CAL = sorted(r['日期'] for r in MARKET['上证指数'])   # 交易日历（上证指数为基准）
CAL_SET = set(CAL)
INTRADAY = _load_intraday()


def _prev_ok(pd_):
    """发帖日能否用「上一交易日收盘」做发帖现值锚。

    交易日历已覆盖范围内(≤数据末日)的非交易日 = 真实周末/假日 → ✓；数据末日之后若是周末 → ✓
    （博主周末谈的就是最新收盘）；数据末日之后的**工作日**无法确认是否交易日（可能已开盘）→
    宁缺勿锚陈旧价，不发注记让模型凭旧记忆判（与打分器同守这一边界）。"""
    if pd_ <= CAL[-1]:
        return True
    try:
        return date.fromisoformat(pd_).weekday() >= 5
    except ValueError:
        return False


def _hm(pub):
    """pub → 当日分钟数（10:06→606）；格式不对 → None。"""
    try:
        return int(pub[11:13]) * 60 + int(pub[14:16])
    except (TypeError, ValueError, IndexError):
        return None


def prev_td(d):
    """d 之前最近一个交易日（不含 d）"""
    for x in reversed(CAL):
        if x < d:
            return x
    return None


def next_td(d):
    """d 之后最近一个交易日（不含 d）"""
    for x in CAL:
        if x > d:
            return x
    return None


def _intraday_price(idx, pub):
    """单指数（不含双创）30 分钟口径参考价。返回 (price, kind, ok)。
    kind ∈ session/lunch/after/prev：分别=盘中当根开盘 / 午休 11:30 收盘 / 盘后 15:00 收盘 /
    上一交易日 15:00 收盘（盘前或非交易日）。kind 供 pub_note 标注快照性质。"""
    idx = normalize_idx(idx)
    days = INTRADAY.get(idx)
    if not days:
        return None, None, False
    pd_, hhmm = pub[:10], pub[11:16]
    hm = _hm(pub)
    if hm is None or len(hhmm) < 5:
        return None, None, False
    if pd_ not in CAL_SET or hm < 9 * 60 + 30:
        if pd_ not in CAL_SET and not _prev_ok(pd_):
            return None, None, False   # 数据末日后的工作日：宁缺勿锚陈旧价
        # 盘前（<9:30）或非交易日 → 上一交易日 15:00 bar 收盘价
        prev = prev_td(pd_)
        if prev is None:
            return None, None, False
        for day, rows in days:
            if day == prev:
                return rows[-1][1]['close'], 'prev', True
        return None, None, False
    for day, rows in days:
        if day != pd_:
            continue
        if (9 * 60 + 30 <= hm < 11 * 60 + 30) or (13 * 60 <= hm < 15 * 60):
            # 交易时间中 → 所处 bar 开盘价（首根 t > hhmm 的 bar；严格大于 = D2 整点边界修正）
            for t, b in rows:
                if t > hhmm:
                    return b['open'], 'session', True
            return None, None, False
        if 11 * 60 + 30 <= hm < 13 * 60:
            # 午休 → 11:30 bar 收盘价
            for t, b in rows:
                if t == '11:30':
                    return b['close'], 'lunch', True
            return None, None, False
        # 盘后（≥15:00）→ 当日 15:00 bar 收盘价（末根）
        return rows[-1][1]['close'], 'after', True
    return None, None, False


def ref_price_at(idx, pub):
    """SKILL §4 参考价：发帖时刻现值（与 eval/run_direction 同源同口径）。返回 (price, ok)。

    双创取创业板指/科创50 两指数均值（两 index 各 30 分钟口径）。"""
    if idx == '双创':
        p1, ok1 = ref_price_at('创业板指', pub)
        p2, ok2 = ref_price_at('科创50', pub)
        if ok1 and ok2:
            return (p1 + p2) / 2, True
        return None, False
    p, _kind, ok = _intraday_price(idx, pub)
    return (p, ok) if ok else (None, False)


def snapshot_label(pub):
    """发帖时刻快照性质（注记头）：盘中(当根开盘) / 午休(11:30收盘) / 盘后(15:00收盘) /
    盘前或休市(上一交易日收盘)。无法解析 → None。"""
    pd_, hhmm = pub[:10], pub[11:16]
    hm = _hm(pub)
    if hm is None or len(hhmm) < 5:
        return None
    if pd_ not in CAL_SET or hm < 9 * 60 + 30:
        if pd_ not in CAL_SET and not _prev_ok(pd_):
            return None   # 数据末日后的工作日：不发注记
        return "上一交易日收盘(盘前或休市)"
    if (9 * 60 + 30 <= hm < 11 * 60 + 30) or (13 * 60 <= hm < 15 * 60):
        return f"{hhmm}盘中(30分钟线当根开盘)"
    if 11 * 60 + 30 <= hm < 13 * 60:
        return "午休(11:30收盘)"
    return "盘后(15:00收盘)"


def pub_note(pub, indices=None):
    """发帖时刻 7 指数现值单行注记（给模型判 d/识别指数用）。与 ref_price_at 同源取价。

    全指数无数据 → None（不发注记，调用方 log 一次即可）。"""
    label = snapshot_label(pub)
    if label is None:
        return None
    vals = []
    for idx in (indices or NOTE_INDICES):
        p, ok = ref_price_at(idx, pub)
        if ok:
            vals.append(f"{idx}≈{p:.2f}")
    if not vals:
        return None
    return f"[行情@发帖 {pub[:16]}] {label}：" + " ".join(vals)


def target_d_check(target, ref, d):
    """目标位(终点目标)与参考价/方向的符号一致性——**只信息性 flag，永不改写 d**。

    语义（用户 2026-09-09 裁决）：target 只在"博主预测价格将移动到的终点目标位"句填（站上4250/
    跌至3880/目标3500）；条件/支撑/分水岭/区间锚不填 target，方向照取博主真实观点。故 target
    在场时 sign(target−ref) 应与 d 同号；异号 = 提取可疑（要么 target 张冠李戴、要么 d 判反），
    记 flag 给人审。返回 agree/conflict/flat/no_ref。"""
    try:
        t, r = float(target), float(ref)
    except (TypeError, ValueError):
        return 'no_ref'
    s = t - r
    if s == 0:
        return 'flat'
    return 'agree' if (s > 0) == (int(d) > 0) else 'conflict'
