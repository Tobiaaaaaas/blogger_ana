# -*- coding: utf-8 -*-
"""抓取身份/时间诚实回归（2026-09-09）——纯单测不联网不启浏览器。

背景事故：时间轨迹 假"09-08 14:54 发帖"上波段卡——博主长期无新帖时，头条 profile
feed 以"跳转流/兜底他人内容"补位，抓取器把他人财经帖当本人新帖并入主文件、上卡。
修复三件套，本测试逐一钉死防止回退：
  1. parse_items 发布时间只认 publish_time→create_time，禁用 behot_time（热度游标≈抓取时刻）冒充；
  2. _filter_foreign_posts 指定抓取(explicit_name)严格只认本人身份，无身份用既有历史重叠背书，
     两者皆无 → 空（硬拒，绝不产当本人数据）；
  3. scrape_merge._merge_window 二次兜底：显式非本人 user 的帖绝不并入主文件。
"""
import importlib.util
import json
import os

from briefing.scripts import scrape_merge as sm

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "scrape_toutiao_uut", os.path.join(_HERE, "scrape_toutiao.py"))
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)


def _item(content="今天大盘震荡后企稳，我看短期还有上行动力", pid="10001",
          pub=None, ctime=None, btime=None, user=None):
    it = {"id": pid, "content": content}
    if pub is not None:
        it["publish_time"] = pub
    if ctime is not None:
        it["create_time"] = ctime
    if btime is not None:
        it["behot_time"] = btime
    if user:
        it["user"] = {"name": user}
    return it


def _parse(items):
    st.user_info.clear()
    return st.parse_items({"data": items})


# ── 1. 时间诚实：behot_time 不再当发帖时间 ──
def test_pub_time_prefers_publish_then_create():
    p = _parse([_item(pub=1700000000, ctime=1600000000, btime=1600000500)])[0]
    assert p["publish_time"] == 1700000000  # publish_time 优先


def test_pub_time_falls_back_to_create_only():
    p = _parse([_item(ctime=1600000000, btime=1600000500)])[0]
    assert p["publish_time"] == 1600000000


def test_pub_time_never_uses_behot_time():
    # 只有 behot_time（热度游标）→ 时间必须视为未知 0，绝不冒充抓取时刻
    p = _parse([_item(btime=1725785640)])[0]
    assert p["publish_time"] == 0
    assert p["publish_date"] == ""


def test_user_retained_on_parsed_post():
    p = _parse([_item(user="张三", pid="9")])[0]
    assert p["user"] == "张三"


# ── 2. 身份过滤：explicit_name 严格只认本人 ──
def _p(pid, user=None):
    return {"post_id": pid, "user": user, "content": "x" * 10}


def test_explicit_strict_keeps_only_own():
    feed = [_p("a", "时间轨迹"), _p("b", "别的博主"), _p("c", None)]
    out, note = st._filter_foreign_posts(feed, "时间轨迹", {"时间轨迹_old_1"}, "")
    assert [p["post_id"] for p in out] == ["a"]
    assert note  # 有提示


def test_explicit_no_identity_no_continuity_rejects():
    # 跳转流：他人/无身份 + 与本人历史 0 重叠 → 空（绝不当本人数据）
    feed = [_p("f1", None), _p("f2", "其它财经号")]
    out, note = st._filter_foreign_posts(feed, "时间轨迹", {"known_old_1"}, "")
    assert out == []
    assert note and "跳转流" in note


def test_explicit_no_identity_but_history_overlap_backs_feed():
    # 兼容 feed 本身不带 user 的账号（枫叶/时间合伙人型）：有 ≥1 条本人已知 id 则背书整个 feed
    feed = [_p("old_known", None), _p("brand_new", None)]
    out, _ = st._filter_foreign_posts(feed, "枫叶", {"old_known"}, "")
    assert len(out) == 2


def test_auto_mode_keeps_legacy_dominant_filter():
    feed = [_p("a", "时间轨迹"), _p("b", "别的博主"), _p("c", None)]
    out, _ = st._filter_foreign_posts(feed, "", {"x"}, "时间轨迹")
    assert [p["post_id"] for p in out] == ["a", "c"]  # 旧口径：留本人+无身份，弃他人


# ── 3. merge 二次兜底：显式非本人 user 不入主文件 ──
def _write(fp, posts):
    with open(fp, "w", encoding="utf-8") as f:
        json.dump({"posts": posts}, f, ensure_ascii=False)


def test_merge_window_skips_explicit_foreign(tmp_path):
    main_f = tmp_path / "main.json"
    win_f = tmp_path / "win.json"
    _write(main_f, [{"post_id": "old", "publish_time": 1}])
    _write(win_f, [
        {"post_id": "old", "publish_time": 1},                  # 已有 → 跳过
        {"post_id": "own", "user": "时间轨迹", "publish_time": 2},  # 本人 → 并入
        {"post_id": "for", "user": "别家号", "publish_time": 3},    # 他人 → 弃
        {"post_id": "empty", "user": None, "publish_time": 4},      # 无身份（爬虫侧已背书）→ 并入
    ])
    new_posts, main, _ = sm._merge_window(str(main_f), str(win_f), "时间轨迹")
    ids = {p["post_id"] for p in new_posts}
    assert ids == {"own", "empty"}
    assert "for" not in {p["post_id"] for p in main["posts"]}
