# 财经博主大盘分析能力量化评估

对今日头条财经博主的大盘预测能力进行系统性量化评估：

**博主分析系统**：爬取帖子 → LLM 逐条标注方向预测信号 → Direction 逐条验证打分（score = direction × return）→ 个体报告 + 横向对比

## 目录结构

```
ana/
├── README.md
├── .gitignore
├── .claude/                        Claude Code 技能定义
│   └── skills/analyze-blogger/
│       └── SKILL.md                博主分析主技能（Direction 方向预测评估）
│
├── knowledge/                      市场知识库（拐点目录）
│   └── market_analysis.md          2024.06~2026.08 上证 zigzag 拐点链
│
├── data/
│   ├── posts/                      爬取的原始帖子
│   ├── direction_signals/          Direction 信号标注（LLM 逐条标注，125 位博主）
│   ├── market/                     日线行情数据（7 指数）
│   └── (scores/signals/minute/positions/simulations 已随旧体系归档至 archive/20260817-pre-direction/)
│
├── scripts/
│   ├── eval/                       Direction 评估引擎（run_direction + comparison_all）
│   ├── pipeline/                   scrape_toutiao.py（爬虫）+ extract_signals_direction.py（DeepSeek 信号提取）
│   └── utils/                      行情获取、正文分片抓取等工具
│
├── opinion/                        共享「读帖/清洗/DeepSeek 标注」模块——prompts.py 为标注契约单一同源
│                                   （09-09 方向教义，briefing 推送与 extract 报告共用），另有
│                                   schema（规范行）/ annotate / verify / cache / ds / ref_price
│
├── briefing/                       推送卡片流水线（summarize/render/state…，独立短/波段面板，VSCode/Windows 定时跑）
│
├── reports/
│   ├── *_direction.md              博主逐条方向验证报告（run_direction.py 生成）
│   └── comparison_direction.md     横向对比总榜（comparison_all.py 生成）
│
└── archive/                        历史快照 & 临时文件
    ├── scratch/                    一次性调试输出
    ├── data_old/                   旧版 filtered posts
    ├── reports_v1/                 v1 版本报告
    ├── 20260730/                   2026-07-30 报告快照
    ├── 20260801-pre-14score/       14 分改制前快照
    ├── 20260803-pre-restructure/   目录重组前快照
    ├── 20260808-pre-v12/           v12 体系前快照
    ├── 20260817-pre-direction/     Direction 体系前快照（旧 v11/v12/v13 打分体系 + 仓位模拟 SIMULATE 子系统）
    ├── 20260909-manual-reports/    人工维护快照报告归档（Direction_结论报告 / top20 双榜 md+pdf，2026-09-09）
    ├── 20260909-legacy/            C1 死代码移除清单（phase2/3、migrate_*、restore_bodies 等）
    ├── knowledge_archive/          旧版打分公式差异说明
    └── skills/                     已归档技能（v13 拐点线段打分）
```

## 快速开始

### 主要入口：/analyze-blogger Skill

在 Claude Code 中直接使用 Skill 完成全流程分析（爬取→信号标注→Direction 验证打分→报告生成）：

```
/analyze-blogger <博主名称> <帖子链接>
```

Skill 定义见 `.claude/skills/analyze-blogger/SKILL.md`（判层规则的可读同步稿 + 博主画像 / 评估背景）。**标注契约（逐条判层 prompt、09-09 教义）以 `opinion/prompts.py` 为单一同源**，字段/spec 合法域以 `opinion/schema.py` 为准，推送（briefing）与报告（extract）共用——判层以 opinion/prompts.py 现行文本为准；SKILL.md §1~§8 是同一规则的同步稿，发现不一致以代码为准并回改 SKILL（改判层规则两处一起改）。

### 后台脚本流水线

Skill 内部调用以下 Python 脚本。如需单独运行某一步（调试/批量处理），可手动执行：

```bash
# 1. 爬取帖子（Playwright，需要 chromium）
python scripts/pipeline/scrape_toutiao.py "<帖子链接>" --name "<博主名>"

# 2. 刷新行情数据（7 指数，Direction 前置条件）
python scripts/utils/fetch_market_data.py --start 20240601

# 3. DeepSeek 自动提取信号 → data/direction_signals/<博主名>.json
export DEEPSEEK_API_KEY="sk-..."   # 只经环境变量，绝不写入文件/提交
python scripts/pipeline/extract_signals_direction.py <博主名> --runs 3
#    （DeepSeek flash 按 opinion/prompts.py 共享标注契约逐条标注 + 格式强校验 + 信号自查；
#      --runs 3 多次运行共识合并，保证聚合指标稳定；schema 见 opinion/schema.py）

# 4. Direction 验证打分并生成报告
python scripts/eval/run_direction.py <博主名>        # 单个博主
python scripts/eval/run_direction.py                 # 全部博主

# 5. 横向对比总榜
python scripts/eval/comparison_all.py
```

## 数据流（Direction 主流程）

```
Toutiao 帖子
    │
    ▼
scrape_toutiao.py ──► data/posts/<name>.json
    │
    ▼
extract_signals_direction.py（DeepSeek flash）
按 opinion/prompts.py 共享标注契约逐条标注
（pub/d/s/idx/spec/summary/cat，语义理解 + 板块→指数映射 + 格式强校验 + 信号自查）
    │
    ▼
data/direction_signals/<name>.json
    │
    ▼
run_direction.py ──► reports/<name>_direction.md
（逐条验证打分，score = direction × return；域外 spec 读库守卫 → unscored long / skip）
    │
    ▼
comparison_all.py ──► reports/comparison_direction.md
（总榜 + 周期/多空/指数/月份分档 + 覆盖率警告）
```

## 当前博主

> 125 位博主已完成 Direction 逐条方向评估（`reports/*_direction.md`），现行横向数字见 `reports/comparison_direction.md`（comparison_all.py 持续刷新）；早期人工快照 `Direction_结论报告.md`、`top20_值得关注博主.{md,pdf}`、`comparison_direction.pdf` 已归档 `archive/20260909-manual-reports/`，勿再按现行口径引用。
> 评估口径：2026-09-09 起方向教义（条件式/先A后B形态无方向、操作动词=方向同义）与 schema 以 `opinion/prompts.py` / `opinion/schema.py` 为准；curated `data/direction_signals/*.json` 为 09-09 前抽取的既有数据，个别域外 spec 行（t0/t34/t60/t90）在读库守卫下归 unscored、不入分（全量 125 博主 LLM 重抽按 09-09 口径仍门控后置）。

## 依赖

- **Python** ≥ 3.10
- **Playwright** + Chromium（爬虫）
- **akshare / pandas**（行情数据下载）
- **openai**（DeepSeek flash 自动信号提取，`pip install openai`）
- **Claude Code**（Direction 打分 / 报告生成）

## 注意事项

- **API Key 安全**：DeepSeek API Key 通过环境变量传入，不要写入脚本或上传到 GitHub
- **今日头条反爬**：爬虫使用 Playwright 浏览器内 API 调用，自带签名；风控与重爬校验见 SKILL.md §前置条件
- **拐点知识库**：所有拐点以 `knowledge/market_analysis.md` 为准，不重新识别
- **标注契约单一同源**：逐条判层以 `opinion/prompts.py` 为准（共享 prompt + 09-09 教义，改动会作废标注缓存指纹）；字段/spec 合法域以 `opinion/schema.py` 为准；SKILL.md §1~§8 是可读同步稿，改判层规则须连同 SKILL 一起改（推送与报告共用同源，勿只改一侧）
