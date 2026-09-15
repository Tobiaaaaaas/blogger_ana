# 2026-09-14 旧栈 skill 归档

`.claude/skills/analyze-blogger/` 的两份主档移入本目录。它是旧栈（`opinion/` ＋ `research/` ＋
`scripts/`）那套的**可读主档**，随重构作废 —— 与 `briefing/`、`opinion/`、`research/`、`scripts/`
同一批，只是当时落在 `.claude/` 下没跟着删。

| 文件 | 是什么 |
|:---|:---|
| `SKILL.md` | 旧栈的判读规则主档（§1 提取 ／ §2 字段 ／ §3 周期 ／ §4 参考价 ／ §5 打分 ／ §6–§8 汇总） |
| `Swing_Timing.md` | 旧栈研究侧的波段委员会口径，自称「早期版本，正在被新规格取代」 |

## 为什么挪走

**方向反了**。`SKILL.md` 第 8 行写着「Prompt和相关代码是基于 SKILL.md 生成，如语义或逻辑上有冲突，
应以本文为基准」，第 6 行自称「已冻结的上游真源，不接受自动篡改」—— 现在以 `docs/01`–`06` 为准，
代码同步那六份。

**它引的路径一个都不在了**。全文 22 处指向旧栈：

| 引用 | 现状 |
|:---|:---|
| `scripts/eval/run_direction.py`（5 处）、`scripts/eval/comparison_all.py`（2 处） | 旧栈脚本，已删 |
| `scripts/pipeline/scrape_toutiao.py`、`extract_signals_direction.py` | 同上，新栈是 `blogger/scrape`、`blogger/parse` |
| `scripts/utils/` 5 个（`fetch_market_data.py`、`fetch_bodies_shard.py` 等） | 同上 |
| `opinion/schema.py`、`opinion/text.resolve_post` | 同上，新栈字段与校验在 `blogger/parse/schema.py` |
| `data/market/market_data.json`（2 处） | **日线已砍**（2026-09-14），只留 30 分钟线 |
| `data/direction_signals/`（3 处） | 已随数据清场移入 `archive/20260913-data/` |
| `reports/<博主名>_direction.md`、`reports/comparison_direction.md` | 新产物是 `reports/per_blogger/<博主名>.md`、`reports/博主对比.md` |

**口径也对不上了**。举三处：① 信号字段由 `{pub, d, idx, spec, summary, cat}` 改成
`{pub, post_id, d, idx, spec, quote}`（`summary` → `quote`，`cat` 去掉，加 `post_id`）；
② 状态由 `cat` 一列（含 `unscored`）改成事后验证的 `note` 六态（计分／不计分／无效-过时／
待验证／报错 ＋「日内」附加标记，03§3.6）；③ 报告头「评估时间」改成「数据截止」。
判层本身也改过几轮：`nd` 档退役、验证终点不再顺延、参考价口径反转为「发帖时刻可获取的最新价格」。

## 已经确认过的事

- 库里**没有任何代码或文档读它** —— 两份都是纯文本，运行时不读（`grep` 全仓只有历史改动记录里
  提到过它们，那是记事，不是引用）
- `.claude/skills/` 随之空了 —— `/analyze-blogger` 这个 slash command 也就没了。新栈的入口是
  `python -m blogger.report`（03）与 `python -m blogger.compare_all`（04）
- 归档前那 7 处「文档与代码对不上」的遗留问题（`market_data.json`、「无 30 分钟数据时引擎退回
  日线口径」、`CAL = market_data.json 中"上证指数"的日期序列` 等）随归档一并消失

## 取回

```bash
git mv archive/20260914-analyze-blogger/SKILL.md .claude/skills/analyze-blogger/
git mv archive/20260914-analyze-blogger/Swing_Timing.md .claude/skills/analyze-blogger/
```

**平时不用取回。** 要挖旧栈当年的判读措辞时再看 —— 那些条文已经搬进 `docs/02-llm解析.md`
（改动记录 2026-09-12：「补入此前只在 `SKILL.md` 里的判读规则：先定位核心预测句、标题与正文
同等重要、周期词不救形态、投资理念不成条、信号日定义与顺延、语义理解正反例」），
`docs/03` 与 `docs/05` 也是从它立稿的。
