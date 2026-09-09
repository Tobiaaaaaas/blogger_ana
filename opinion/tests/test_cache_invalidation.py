# -*- coding: utf-8 -*-
"""rows_cache 作废路径单测（2026-09-09 A3 指纹域 / D-2）。

- save/load roundtrip：同 version + 同标注期指纹 → 命中；
- version 不符 / prompt_text（标注期指纹）不符 → load 返回空结构（全量重抽）；
- 指纹域：annotation_fp_input() = 共享 ANNOTATION prompt + DISPOSITION_SUFFIX——改到案后缀
  即 fp 变 → 旧缓存作废；坍缩/复核文本（读时步骤）不参与指纹（直接改它们不影响命中）。

直接 python3 运行（不调 API；cache 文件用 tempfile）。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from opinion import annotate as o_ann, cache as o_cache, prompts as o_prompts  # noqa: E402
from opinion import verify as o_verify  # noqa: E402

fp = o_cache.prompt_fp
tmp = tempfile.mkdtemp(prefix="rows_cache_test_")
CACHE_FILE = os.path.join(tmp, "rows_cache.json")

cur = o_ann.annotation_fp_input()
v = 6

# ── roundtrip：同 version + 同指纹 → 命中 ──
o_cache.save(CACHE_FILE, {"version": v, "bloggers": {"a": {"posts": {"p1:abc": {"ts": 1, "rows": []}}}}}, cur)
data = o_cache.load(CACHE_FILE, v, cur)
assert data["bloggers"]["a"]["posts"]["p1:abc"]["rows"] == [], data
assert data["prompt_fp"] == fp(cur)
print("[PASS] roundtrip：同 version+指纹 → 命中")

# ── version 不符 → 空结构 ──
data = o_cache.load(CACHE_FILE, v + 1, cur)
assert data["bloggers"] == {}, data
print("[PASS] version 不符 → load 空结构（全量重抽）")

# ── 标注期指纹不符（共享 prompt 或到案后缀任一改）→ 空结构 ──
data = o_cache.load(CACHE_FILE, v, cur + "x")          # 模拟共享 prompt 改动
assert data["bloggers"] == {}, data
data = o_cache.load(CACHE_FILE, v, o_prompts.ANNOTATION_SYSTEM_PROMPT)   # 旧口径只喂共享 prompt、没含到案后缀
assert data["bloggers"] == {}, data
print("[PASS] 标注期文本（含 DISPOSITION）任一变 → fp 变 → 作废重抽")

# ── 指纹域：到案后缀确在指纹内（改它必须让 fp 变）──
assert fp(cur) != fp(o_prompts.ANNOTATION_SYSTEM_PROMPT), "DISPOSITION_SUFFIX 必须进指纹"
print("[PASS] 指纹域：annotation_fp_input ⊇ 共享 prompt + 到案后缀")

print("\ncache 作废路径全部通过 ✅")
