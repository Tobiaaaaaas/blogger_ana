# old_push —— 旧栈推送（已停用，留作参照）

从 git 还原的旧推送，快照取在 `9bf5db1^` —— 2026-09-13 那一笔「删旧栈、产物收进 reports/」
删掉之前的一版。代码最后改动是 `ad3ccfa`（假帖事故修复）。

---

## 这是什么

旧栈四条线里的一条。推送的闭环在 `briefing/`，但它运行时还要两样，一并还原了：

| 目录 | 文件 | 是什么 |
|:---|:---|:---|
| `briefing/` | 20 | 推送本体 —— 抓帖合并、分层标注、渲染、推飞书、落状态。v17（双卡·共享标注） |
| `opinion/` | 28 | 共享标注模块 —— 读帖、清洗、DeepSeek 网关、逐帖标注、复核。`briefing` 运行时 import 它 |
| `scripts/` | 10 | `scrape_toutiao.py`、`fetch_bodies_shard.py`、`merge_bodies_to_posts.py` 等 —— `briefing` 用 subprocess 调它们抓帖、补正文 |

原来的 `research/`（产 `data/direction_signals` 的那条线）**没有还原** —— 推送不 import 它。

另有四样不是从 `9bf5db1^` 来的：本文件、`.gitignore`（挡 `data/` 与 `reports/`）、
`data/market/market_data.json`（现抓的日线）、`data/posts/*.json`（播种用的空壳，见「数据」）。

---

## 怎么跑

`old_push/` 本身就是它的仓库根：`briefing/scripts/paths.py` 把 `REPO_ROOT` 定成 `briefing/` 的上一层，
`scripts/utils/fetch_market_data.py` 反过来从自己的位置往上数两层 —— 两个算法在这里指向同一处。
所以从 `old_push/` 里跑就行，不用设环境变量：

```bash
cd old_push
python -m briefing.scripts.run_briefing --push --board swing --time 14:30
```

| 参数 | 干什么 |
|:---|:---|
| `--time HH:MM` | 模拟决策时刻。不加就用墙钟，而墙钟不在推送节奏上会直接跳过（实跑：14:56 那次就跳过了） |
| `--push` | 真推飞书并推进状态（调度用）。不给它就必须给 `--dry-run`，否则直接报错退出 |
| `--dry-run` | 只落盘预览，不推、不改状态 |
| `--no-scrape` | 不抓帖，读现成的。**试跑用** —— 空库时带上它必然出一张全 0 的卡 |
| `--board` | `short`／`swing`／`auto`（默认）。超短没配 webhook，带 `auto` 会连超短一起报失败 |
| `--max-bloggers N` | 只抓前 N 位（冒烟用） |

---

## 密钥与群

密钥从 `briefing/.env` 与 `REPO_ROOT/.deepseek_keys.env` 读（`paths.load_env`），先读到的优先。
`old_push/briefing/.env` **已经放好了**，被 `briefing/.gitignore` 挡住，绝不提交。

| 变量 | 配了没有 | 发到哪 |
|:---|:---|:---|
| `DEEPSEEK_API_KEY` | 配了 | —— 标注网关 |
| `FEISHU_WEBHOOK_URL_SWING` | 配了 | **旧推送专用群**（`42c6f105…`），与现在 live 的波段群是两个群 |
| `FEISHU_WEBHOOK_URL` | **故意空着** | 超短卡。配了会把旧栈的超短卡推进 live 那个群（＝双推），所以留空 |

旧栈的规矩是「本板块 webhook 缺失 → 该板块记失败，**绝不回落** `FEISHU_WEBHOOK_URL`」（`render.py:79`），
所以空着只会让超短卡报失败，不会误发。要单独试超短卡，临时往 `.env` 里补一行、跑完删掉。

---

## 数据

**帖要有个种子才能抓。** 主文件是硬门 —— [scrape_merge.py:107](briefing/scripts/scrape_merge.py#L107)：

```python
main_file = os.path.join(paths.POSTS_DIR, f"{blogger}.json")
if not os.path.exists(main_file):
    return [], f"缺主文件 data/posts/{blogger}.json"
```

过不去就**立刻返回**，连浏览器都不起。而且种子 URL 正是从主文件里读的（`_seed_url`）——
**它不能从零自举**，没有文件就不知道该抓谁。

种子可以极小。`_seed_url` 在没有帖子时退回读 `source_url`，所以 80 字节就够：

```json
{"source_url": "https://www.toutiao.com/w/1870592724492295/", "posts": []}
```

| 要什么 | 从哪来 |
|:---|:---|
| 种子（`data/posts/<博主名>.json`） | 该博主**任意一条**帖子链接当 `source_url`。归档 `archive/20260913-data/posts/` 里 47 位都有 |
| 帖 | 起爬器自己抓：解出博主 token → 拉 `profile_all` 信息流 → 并进主文件 |
| 行情 | `briefing/scripts/market.py: _fetch_sina` 现拿新浪接口 |
| `reports/` | 空目录即可 |

**种子帖多旧都行。** 爬虫拿到帖子链接会先解博主 token 再拉他的信息流（[scrape_toutiao.py:276](scripts/pipeline/scrape_toutiao.py#L276)
优先从 URL 直解，就是防着跳到别人主页），与那条帖本身的日期无关。

**归档不供内容，只供种子。** 波段窗口是最近 5 个交易日、归档止于 2026-09-08 —— 一条都用不上。
另外两份量归档数据这一路**都不读**（逐模块核过运行期 import 闭包）：

| 归档里的 | 谁读 | 推送读不读 |
|:---|:---|:---|
| `direction_signals/` | 报告链（`scripts/eval/run_direction.py`、`briefing/scripts/profiles.py`） | **不读** —— 实测 `import run_briefing` 后 `sys.modules` 里没有 `profiles` |
| `data/market/intraday/` | 报告链的 `opinion/ref_price.py` | **不读** —— `ref_price` 只被 `run_direction.py` 和自己的测试 import；[annotate.py:127](opinion/annotate.py#L127) 的 docstring 写明注记「推送调用不带 → 零影响」 |

`data/market/market_data.json` 只有一处用到 —— `market.py: _fallback_from_repo`，新浪接口全挂时的兜底。

**不要用符号链接把 `data/posts/` 指到归档。** 旧推送**会往主文件回写**（备份 → 重写 → 补正文），
符号链接会让它顺着写进归档。要历史就拷真副本。

**只抓某一个板块**：`fetch_all_new_posts` 走的是两板块并集（`ALL_BLOGGERS`，47 位），没有按板块的开关。
但只播种你要的那个板块、其余留空即可 —— 没种子的那些会立刻以「缺主文件」失败，零开销。

---

## 两件必须知道的事

**一、帖档是旧格式，与现在的仓库不兼容。** 旧栈认 `publish_date`／`publish_time`／`title`；现在的
`data/posts/` 是 `pub` 那六个键（01§7）。两边不能互读。

**二、运行时状态找不回来了。** `briefing/data/`（`state.json`、`profiles.json`、`rows_cache.json`、
历史卡档）被 `briefing/.gitignore` 排除，从来没入过库 ——「上次推到哪一档、判过哪些帖」
这些是从零开始的。状态里的 `fetched_at` 是抓帖水位，**空着时起抓下界 = 最旧板块窗口下界**
（`min` 跨两个板块取，所以是波段那个更早的）。

**水位只在真抓成功那一步推进。** 抓取全失败的那一轮照样会把它推到墙钟（`if args.push:` 那段不看成败），
所以跑砸过一次之后 `since` 会变成「刚刚」，把中间整段永久跳过 —— 出了这种事就把 `state.json` 删掉重来。

---

## 旧栈自己的文档

`briefing/README.md` 与 `briefing/DEPLOY.md`（Windows 任务计划部署，`runners/` 里是 .bat 与 .ps1）
都是旧栈自己写的，一并还原了。
