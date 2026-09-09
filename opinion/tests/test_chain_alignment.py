# -*- coding: utf-8 -*-
"""双链行校验对齐单测（2026-09-09 B1/B2，纯逻辑不调 API）。

B1 后两路核心校验统一委派 opinion.schema.to_core：推送 annotate.to_canonical 与报告
extract.normalize_signal 对同一模型行必须**同判同改**。本套以原始行电池直测三方：
- to_core 归一边界（spec=long→unscored、s 钳位、idx 别名、summary 截 50、拒因标签）；
- 对同一 raw row，to_canonical 与 normalize_signal 接受/拒绝一致，接受时核心键
  (d/s/idx/spec/cat/summary) 值全等（= 未来任一侧改动若破坏等价即刻红）；
- B2 idx 别名（上证综指/上证/综指）双路同归一，不再有各自内联表。

直接 python3 运行。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from opinion import annotate as o_ann      # noqa: E402
from opinion import schema as sch          # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "report_extract", os.path.join(ROOT, "scripts", "pipeline", "extract_signals_direction.py"))
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

POST = {"post_id": 1, "publish_date": "2026-09-07 10:00", "publish_time": 1760003600}

CORE = ("d", "s", "idx", "spec", "cat", "summary")


def _norm(row):
    return ex.normalize_signal(row, POST)


def _can(row):
    return o_ann.to_canonical(row, POST, "B", 0)


# ── to_core 归一边界 ──
core, _ = sch.to_core({"d": 1, "cat": "scored", "spec": "long", "summary": "x"})
assert (core["spec"], core["cat"], core["s"]) == ("long", "unscored", None), core
core, _ = sch.to_core({"d": -1, "idx": "上证", "spec": "t1", "s": 5, "summary": "x" * 60})
assert (core["idx"], core["spec"], core["cat"], core["s"]) == ("上证指数", "t1", "scored", 1), core
assert len(core["summary"]) == 50, core["summary"]
core, _ = sch.to_core({"d": "1", "cat": "unscored", "spec": "t2", "summary": "x"})
assert (core["spec"], core["cat"], core["s"]) == ("long", "unscored", None), core  # unscored 任意 spec→long
for bad_row, tag in [({"d": 0, "summary": "x"}, "d 非法"),
                     ({"d": 1, "cat": "zz", "summary": "x"}, "cat 非法"),
                     ({"d": 1, "idx": "纳斯达克", "summary": "x"}, "idx 非法"),
                     ({"d": 1, "summary": ""}, "summary 缺失"),
                     ({"d": 1, "spec": "", "summary": "x"}, "spec 非法"),
                     ({"d": 1, "spec": "t0", "summary": "x"}, "spec 语义域外"),
                     ({"d": 1, "spec": "d:2026-13-99", "summary": "x"}, "spec 语义域外")]:
    c, why = sch.to_core(bad_row)
    assert c is None and tag in why, (bad_row, why)
print("[PASS] to_core 单源：归一边界 + 拒因标签 7 类")

# ── B1 对齐：同一 raw row 双路接受/拒绝一致 + 接受时核心键全等 ──
BATTERY = [
    {"d": 1, "spec": "t1", "summary": "明天看涨"},
    {"d": "1", "s": "2", "idx": "上证综指", "spec": "t2", "summary": "两日看多"},
    {"d": -1, "idx": "上证", "spec": "t30", "summary": "一个月看空"},
    {"d": 1, "idx": "综指", "spec": "week", "summary": "本周上行"},
    {"d": 1, "spec": "long", "summary": "年度牛市"},                       # scored+long → unscored
    {"d": 1, "cat": "unscored", "spec": "t5", "summary": "长期偏好"},       # unscored 任意 spec
    {"d": 1, "spec": "nweek_first", "s": 2, "summary": "下周初企稳", "horizon": "下周"},
    {"d": 1, "spec": "d:2026-09-15", "summary": "九月中看多"},
    {"d": 1, "idx": "双创", "spec": "t1", "summary": "双创明天强"},
    {"d": 1, "summary": "很长" * 40},                                      # summary 截 50
    {"d": 0, "summary": "x"}, {"d": 1, "cat": "bad", "summary": "x"},
    {"d": 1, "idx": "道琼斯", "spec": "t1", "summary": "x"},
    {"d": 1, "spec": "t0", "summary": "x"}, {"d": 1, "spec": "t99", "summary": "x"},
    {"d": 1, "spec": "", "summary": "x"}, {"d": 1, "summary": ""},
    {"d": 1, "spec": "d:2025-02-29", "summary": "x"},
    {"d": 1, "spec": "x", "summary": "y", "s": 9},
]
for i, raw in enumerate(BATTERY):
    ns, why = _norm(raw)
    can = _can(raw)
    assert (ns is None) == (can is None), (i, raw, "normalize", why, "canonical", can)
    if ns is not None:
        for k in CORE:
            # normalize 对 unscored 不带 s 键、canonical 恒带 s:None → 语义等价按 .get 比
            assert ns.get(k) == can.get(k), (i, k, ns.get(k), can.get(k), raw)
        assert ns["pub"] == POST["publish_date"], ns
        if "target" in ns:                       # target 是报告独有富化，不进推送规范行
            assert "target" not in can, can
print(f"[PASS] B1 对齐：{len(BATTERY)} 条 raw 双路同判同改（接受/拒绝 + 核心键全等）")

# ── B2：别名不再有各自内联表——双路同走 schema.IDX_ALIAS，扩展别名一处生效 ──
assert sch.IDX_ALIAS == {"上证综指": "上证指数", "上证": "上证指数", "综指": "上证指数"}
assert ex.o_schema is sch, "extract 应复用 opinion.schema（无内联别名表残留）"
assert not hasattr(ex, "VALID_IDX"), "extract 不再留 VALID_IDX 本地副本（已单源化）"
print("[PASS] B2 idx 别名单源：schema.IDX_ALIAS，extract 内联表已删")

print("\n双链行校验对齐全部通过 ✅")
