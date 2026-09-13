# 2026-09-13 数据归档（重构前清空数据根）

六份规格文档重写 + 基于文档重构期间的清场：`data/` 下**除 `market/` 外的全部数据**移入本目录，
给新栈一个干净的数据根 —— 既能做重构测试，也能直接当正式环境用。

**行情不归档**：`data/market/`（日线 + 30 分钟线）是客观外部数据，重构前后同一份，留下。

## 移入清单

| 原位置 | 体积 | 是什么 | 状态 |
|:---|:---|:---|:---|
| `data/posts/` | 358M | 273 个文件：162 位博主的帖子 + 9 个空/坏的 `_bodies_*` + `_backup/` 102 份人工备份 | **旧格式**，见下 |
| `data/direction_signals/` | 6.3M | 251 个文件：125 位博主的方向信号 + 126 个 `_<名>_run.json` 运行元数据 | 旧栈产物，已被新栈取代 |
| `data/pipeline_phase2.log` 等 3 个 | — | 旧流水线日志 | 无 |

## 为什么 `data/posts/` 留着也没用

**它是旧格式**：键为 `post_id`／`content`／`publish_time`（unix 秒）／`publish_date`／`url`／
`digg_count`／`comment_count`／`read_count`，**没有 `pub`、没有 `title`**。

新栈读 `p["pub"]`，所以对任何一份现有博主文件都会在解析的排序处直接报 KeyError ——
也就是说这 162 份存档**一份都进不了新栈**。要跑新栈，只能重新抓。

## 取回

```bash
git mv archive/20260913-data/posts data/posts
git mv archive/20260913-data/direction_signals data/direction_signals
```

**平时不用取回**：读 `data/direction_signals/` 的是 `research/`（`corpus.py`、`quality/`、
`combo/`）—— 那整套和 `briefing/`、`opinion/`、`scripts/` 一样**都属旧栈，之后要从零重建**，
不会再读这份语料。

取回只有一种情形：**要挖历史**。这 93,047 条帖是 2026-09-13 之前抓下来的唯一一份，
新栈读不了它（旧格式），重新抓又只能拿到头条给的近期 —— 想把它们灌进新栈，
得先写一个旧格式 → 新格式的转换。

## 已经确认过的事

- 本机**没有** crontab，`~/Library/LaunchAgents/` 里也没有本项目的定时任务 —— 移走不会打断任何 live 链路
- 新栈的写入方全部 `mkdir(parents=True, exist_ok=True)`，`data/posts/`、`data/signals/`、
  `data/state/` **不需要预建空目录**，第一次跑会自己建
- `data/state/video_posts.json`（旧「已完成记录」）**本来就不存在**，本次没有波及
