# -*- coding: utf-8 -*-
"""共享「读帖/解析/DeepSeek 标注」模块：推送、报告、回测三场景同源的"提取观点"步骤。

2026-09-08 重构：把三处各自实现的读帖/清洗/DeepSeek 判层 prompt 收敛为单一共享模块与单一
共享 prompt（ANNOTATION_SYSTEM_PROMPT 逐帖标注），产出统一结构化规范行（双字段 spec+horizon）
后，聚合由代码完成（推送 = collapse_board 确定性坍缩；报告 = 各自 normalize/verify/consensus；
回测 = 直接消费报告已产出的 direction_signals，不走本模块读帖路径）。打分链
（run_direction.calc/endpoint_of/…）不在此模块内，留在 scripts/eval/run_direction.py。

子模块只依赖 stdlib + openai，不 import briefing——离线裸脚本可 `sys.path.insert(0, repo_root)`
后 `import opinion` 干净使用；briefing 以 `from opinion import …` 同源接线。

公开 API：posts（读帖）/ text（清洗截断）/ ds（DeepSeek 网关）/ prompts（共享 prompt）/
schema（规范行 + spec↔horizon 映射）/ cache（推送标注缓存 v4）/ annotate（render_batch /
annotate_blogger / collapse_board）。
"""
from . import annotate, cache, ds, posts, prompts, schema, text  # noqa: F401
from .annotate import annotate_blogger, collapse_board, render_batch  # noqa: F401
from .prompts import ANNOTATION_SYSTEM_PROMPT  # noqa: F401
