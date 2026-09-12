# 事故善后：时间轨迹 假"09-08 14:54 发帖" 清理 + 防复发验证（Windows/服务器部署副本）

> 触发：2026-09-09 波段推送卡显示 时间轨迹「09-08 14:54 发帖」，用户在手机上核实无此帖。
> 根因已定位（见文末），代码修复已落本仓库。**本文件只针对 Windows/服务器部署副本**——
> Mac 本仓库主数据干净（无 09-08 帖），无需清理。

---

## 0. 背景与判定

假帖特征（以它为准，勿猜时间戳）：
- 内容含原话 **`反弹从9月5号开始`**
- 被标注时间 **2026-09-08 14:54**

删除前先**停掉 Windows 计划任务**（BriefingIntraday / 旧 BriefingDaily 等），避免清理与定时推送并发写文件。

---

## 1. 同步修复代码到部署副本

部署副本（git pull 或直接覆盖复制）这 3 个文件：

| 文件 | 修复内容 |
|---|---|
| `scripts/pipeline/scrape_toutiao.py` | 发布时间只认 `publish_time→create_time`，禁用 `behot_time`（热度游标≈抓取时刻）冒充；`_filter_foreign_posts`：`--name` 指定抓取**严格只认本人帖**，无本人身份则用既有历史重叠背书，两者皆无 → 拒产出（exit 1） |
| `briefing/scripts/scrape_merge.py` | `_merge_window(..., blogger)` 二次兜底：window 帖带 `user` 且 ≠ 目标博主 → 一律不并入主文件 |
| `scripts/pipeline/test_scrape_identity.py` | 回归单测（Mac 已跑 **9 passed**，防回退） |

同步后快速自检（应无输出/或仅注释，证明已含修复）：

```bat
:: 应看不到 parse_items 里再引用 behot_time 作发布时间（只剩“0”回退）
findstr /n "behot_time" scripts\pipeline\scrape_toutiao.py
:: 应能看到 _merge_window 带 blogger 身份过滤
findstr /n "def _merge_window" briefing\scripts\scrape_merge.py
```

---

## 2. 从主文件删除假帖（含他人身份兜底清扫）

在**部署副本仓库根目录**（`data\posts\` 所在层）用 `python.exe` 跑：

```bat
python -X utf8 -c "import pathlib,json,datetime; fp=pathlib.Path('data/posts/时间轨迹.json'); p=fp.read_text(encoding='utf-8'); d=json.loads(p); posts=d.get('posts') or []; print('现有帖数',len(posts)); mark=[x for x in posts if '反弹从9月5号开始' in (x.get('content') or '')]; foreign=[x for x in posts if x.get('user') and x['user']!='时间轨迹']; print('--- 命中目标假帖(内容标记) ---'); [print(x.get('post_id'),x.get('user'),x.get('publish_date'),(x.get('content') or '')[:40]) for x in mark]; print('--- 显式他人身份帖(一并清扫) ---'); [print(x.get('post_id'),x.get('user'),x.get('publish_date'),(x.get('content') or '')[:30]) for x in foreign]; kill=set(id(x) for x in mark+foreign); new=[x for x in posts if id(x) not in kill]; removed=len(posts)-len(new); assert removed==len(mark)+len(foreign), '删除数异常，中止'; 
if not removed: print('未发现目标帖/他人帖，未改动文件'); raise SystemExit
bak=pathlib.Path('data/posts/_backup')/(fp.stem+'_cleanup_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.json'); bak.parent.mkdir(exist_ok=True); bak.write_text(p,encoding='utf-8'); d['posts']=new; d['total_posts']=len(new); fp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8'); print('已备份到',bak); print('删除',removed,'条，现剩',len(new),'条')"
```

输出应类似：命中目标假帖 **1** 条（内容标记）+ 可能的他人帖若干，最后打印「删除 N 条，现剩 M 条」。

---

## 3. 作废 rows_cache 中该博主的缓存行

行抽取缓存 `briefing\data\rows_cache.json` 里按博主存的逐帖规范行；主文件已删假帖后该行不会被窗口读到，但为彻底干净，删除 时间轨迹 整个缓存条目（下次波段档只需为它补一次标注调用）：

```bat
python -X utf8 -c "import pathlib,json; fp=pathlib.Path('briefing/data/rows_cache.json'); p=fp.read_text(encoding='utf-8'); d=json.loads(p); b=d.get('bloggers',{}); n=len(b.get('时间轨迹',{}).get('posts',{})) if '时间轨迹' in b else 0; b.pop('时间轨迹',None); fp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8'); print('已作废 时间轨迹 缓存行',n,'条')"
```

---

## 4. 本地验证（不推送）

**不推送**、**不抓取**（直接读已合并主文件），跑一次波段 dry-run，确认 时间轨迹 不再有 09-08 行：

```bat
cd /d <部署副本根目录>
python -X utf8 -m briefing.scripts.run_briefing --dry-run --time 11:00 --board swing --no-scrape
```

检查点：
- 预览落盘在 `briefing\data\briefings\<日期>_1100_swing.json`，用编辑器搜 **时间轨迹**：不应再出现「09-08 14:54」「反弹从9月5号开始」行。
- 无卡时段该博主为空窗（宁可空窗，不上假帖）。
- 若有 DeepSeek 标注报错，属网络/临时问题可重跑；rows_cache 会在成功时自动回填。

---

## 5. 恢复调度并观察

- 确认无误后**重新启用计划任务**。
- 下一真实推送（波段 09:30 / 11:00 / 14:30）留意 时间轨迹 是否回到正常节奏（它真实无新帖 → 应为空窗或旧观点，不再出现新时间戳假帖）。

---

## 6. 根因与防复发（为什么不会再发生）

事故链路（五处全堵）：
1. 博主长期无新帖时，头条 profile feed 会塞**跳转流 / 兜底他人财经内容**；
2. 旧抓取器用 `behot_time`（页面热度游标 ≈ **抓取时刻**）冒充发帖时间 → 假「09-08 14:54」；
3. 旧首屏「财经关键词密度」闸门对财经跳转流失灵；
4. 帖子级身份过滤只有 `user` 字段时才生效，且旧代码把 `user` 字段弹出不落盘；
5. `_merge_window` 合并时不校验作者，他人帖当本人新帖并入主文件 → 标注 → 上卡。

本次修复后：
- 抓取器只认真实 `publish_time→create_time`，无真实时间戳的条目一律 `0`（时间未知），**任何情况不再用游标当发帖时间**；
- `--name` 指定抓取严格只认 `user==本人` 的帖；feed 若被跳转成他人/兜底内容且无本人历史重叠 → **0 条本人帖 → 硬拒产出**（exit 1），绝不产当本人数据；
- 每帖 `user` 保留落盘，供 merge 侧二次身份校验与事后溯源；
- `_merge_window` 增加 author 闸门：window 帖显式 `user ≠ 博主` → 丢弃不入主文件。

回归测试：`python3 -m pytest scripts/pipeline/test_scrape_identity.py`（9 例，覆盖时间回退、身份过滤三分支、merge 兜底）。
