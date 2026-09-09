# 2026-09-09 架构整改·移除清单（C1）

阶段 C1（2026-09-09 提交）从 live 代码移除的死代码/一次性脚本档案。git 历史即第一档案；
本目录保留一次性脚本实体，便于需要时取回。**凡从 `scripts/` 移除的脚本，运行前先读各文件头
注释确认入参约定已随数据 schema 变化（09-09 教义 / migrate 已退役的 nd 档均已变化）。**

## 一次性脚本 → `scripts/`（git mv 到本目录）

| 脚本 | 原职责 | 状态 |
|---|---|---|
| `migrate_nd_to_t5.py` | 把旧 `nd`(无周期) 信号迁到 `t5` | 目标档已随 09-09 口径退役，**勿再跑** |
| `migrate_t10_to_nd.py` | 把 t10 归入 nd | 同上，**勿再跑** |
| `restore_bodies_from_backup.py` | 从正文备份恢复被压扁的帖子正文 | 需要手工重建语料时取回 |
| `phase2_refresh.py` | 语料 phase2 批量刷新 | 全量重抽新博主走 `run_direction --runs 1`，非本脚本 |
| `phase2d_bodies.py` | phase2d 正文分片回填 | 同上 |
| `phase3_extract_all.py` | phase3 全量方向提取 | 125 博主全量 LLM 重抽仍门控后置；届时不用此脚本 |

取回示例：`git mv archive/20260909-legacy/scripts/restore_bodies_from_backup.py scripts/utils/`

## 代码内移除（git 历史可 diff）

**`briefing/scripts/summarize.py`**（992 → 575 行）— v8 全板共识链 + v12 跨板块收敛整段移除：
- 常量 `POINTS_BATCH / SYNTH_MAX_ATTEMPTS / MAX_POST_CHARS`
- prompts `POINTS_SYSTEM_PROMPT / SYNTH_SYSTEM_PROMPT / SUMMARY_SYSTEM_PROMPT`
  （POINTS prompt 内「带条件按倾向判多空」是与 09-09 教义冲突的旧文本，一并消灭）
- 函数 `extract_points / synthesize / summarize_boards / _fmt_post / _board_txt /
  _build_profile_subset / _normalize_synth_result / _synth_result_ok / _count_board /
  _nature_block / _prev_block / _sanitize_card / _norm_takeaways`

**`briefing/scripts/render.py`**（486 → 251 行）— v8 共识卡/心跳/错误文本 + v12 双板块同卡：
- `build_card_payload / build_heartbeat_payload / build_error_payload /
  build_boards_card_payload_LEGACY / build_minimal_card_payload_LEGACY / select_key_bloggers /
  _fmt_key_blogger / _fmt_takeaway / _rank_of / _date_header` + 常量 `HORIZON_BADGE /
  KEY_BLOGGERS_TOP / STANCE_BADGE`；`STANCE_EMOJI/STANCE_TEXT` 去「中性」键（live 只消费 多/空）

**`briefing/scripts/config.py`**：删 `format_board_counts`（双板块合并计数）；删 `TRACKED`
（profiles 改用 `ALL_BLOGGERS`）；顶注失效引用 `SWING_ROW_SYSTEM_PROMPT` → `summarize_board`

**`briefing/scripts/state.py`**：删 `seen`（旧 v8 只写不读键）读写与 docstring
**`briefing/scripts/market.py`**：删 `heartbeat_line`（心跳路径 v9 起已停）
**`briefing/scripts/profiles.py`**：`_horizon_of` 删 `nd` 死分支
**`opinion/__init__.py` / `opinion/cache.py`**：缓存版本注释 v4/v5 → 随调用方 v6

恢复任一函数：`git show <commit>^:path | grep -n 'def NAME'` 或整文件 `git checkout <commit> -- path`。
