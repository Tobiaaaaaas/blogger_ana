# 部署（v19：两群两卡 · 共享标注模块 · 解析加固）

`briefing/` 是独立部署单元。实际生产运行在用户的 **Windows 电脑**（长期开机 + Tailscale SSH，别名 `windows-server`），镜像 `aws_options` 项目已验证的部署模式；下方 Linux 段仅作通用示意。

## v15 节奏速览

- **超短卡** → 旧群（env `FEISHU_WEBHOOK_URL`）：窗口 = 前一交易日 00:00 至 now（v14 交易日口径）。
- **波段卡** → 新群（env `FEISHU_WEBHOOK_URL_SWING`）：窗口 = **前 5 个交易日** 00:00 至 now（v15 波段 3→5）。
- **两板块同一节奏**（v15 统一）：交易日 **09:00–15:00 每 30 分钟**（含午休与 09:00 盘前，13 档）+ **16:00–22:00 每整点**（7 档）→ 每档**两卡都推**；**非交易日只推波段卡**：09:00–21:00 每 3 小时（09/12/15/18/21 五档）。
- 每档一次抓取 + 一次行情，然后按墙钟决定推哪些板块（交易日 `config.in_trading_grid` → 两板块 / 非交易日 `config.in_restday_grid` → 波段，`config.due_boards(trading)`）；每板块各读各窗、各自收敛总结、各推各群。
- 状态双水位：`fetched_at`（爬虫水位，抓完即写）/ `last_run`（推送水位，全板块推完才写）；行抽取缓存 `rows_cache.json`（v5：**逐帖**规范行 + 内容指纹，见下）。
- 板块 webhook 缺失 → 该板块记失败、错误心跳同群，**绝不回落** `FEISHU_WEBHOOK_URL`。

## v17（2026-09-08）共享标注模块

- 读帖/解析/DeepSeek 逐帖标注收敛进父仓库顶层 **`opinion/`** 包（`briefing/`、`scripts/` 旁），推送·报告·回测三场景同源；单一共享 `ANNOTATION_SYSTEM_PROMPT`。
- `briefing/` 现在依赖父仓库的 **`opinion/` 目录**（读帖/标注/DeepSeek 网关）。同步代码时须包含它——下方 Windows tar 整仓库打包**自动包含** `opinion/`，无需额外参数；若手动只拷 `briefing/` 会缺模块，部署前务必确认 `blogger_ana/opinion/` 已在服务器。
- `rows_cache.json` **v4→v5**（`_ROWS_CACHE_VERSION=5`，**逐帖粒度**）：v4 每博主缓存"整组规范行 + 窗口帖集合指纹"——集合任一变化（新帖/窗口滑动/正文回填）即整博主 ≤8 帖全量重抽、旧帖也重评分。v5 改为**每帖按 (post_id, 内容 hash) 键存各自的规范行**：每档只把窗口里新出现/正文回填变 content 的帖送一次标注（该博主新帖合成一个子批一次调用），**旧帖（含跨交易日窗口滑动重叠帖）永不重评分**；坍缩 `opinion.annotate.collapse_board` 每 tick 确定性重算、只取本次窗口帖的行（窗口滑动/行过期自动消化）。版本号或共享 prompt 指纹任一不符 → 整缓存作废全量重抽（上线首档按博主把窗口新帖合批，一次调用/博主、量级同 v4；档内超时 → 下档自动补，错误处理不变）。
- 缓存防膨胀：含波段窗口的档（含 `swing` 下界）在写缓存前修剪早于波段窗口下界的逐帖项——窗口只前移，这类帖永不回窗。
- **板上只认上证（2026-09-08）**：`collapse_board` 只取 `idx=上证指数` 行（他指行留缓存给报告/未来他指消费）；同一帖对不同指数的不同看法由共享标注拆成各 idx 行（prompts「同一帖多指数」节，上证状态/背景句不产生上证行）。prompt 变更 → prompt_fp 变，上线首档全量重抽一次（同 v5 上线量级）。

## v19（2026-09-08 定稿 / 09-09 quote 门校准）解析加固

LLM 解析是唯一有随机性的上游（打分/坍缩/锚定已全代码规范化）——v19 把解析过程「每条帖必须到案」、结果「每条字段强制进规范」。四柱细节见 `briefing/README.md`「解析加固」节，这里只留**部署相关**要点：

- **只动推送路径**：`opinion/`（annotate/schema/text/verify/cache/ds）+ `briefing/scripts/summarize.py`。报告侧不共享（自身有 verify+runs）。Windows 同步整仓库 tar 已含 `opinion/`，无额外参数。
- **A 到案契约**（user-message 后缀 `DISPOSITION_SUFFIX`，**不进**共享 prompt）：批内每条帖必须 `rows ∪ no_view` 到案；缺到案 → 带错重试 1 次 → 仍缺 → 该博主按**失败** → D 回退、下档重试。结构小错（重叠/重复/理由出枚举）`_clean_no_view` 自动化解，不拦成功。
- **B quote 逐字门**（`opinion/text.verbatim_in`）：字级增删/改写/串帖/逆序必拒（不符 → 带错重试 1 次 → 弃行，不弃博主）；**行/句读折叠放行**——2026-09-09 版式归一校准（Mac dry-run 实测：香满衣「一句一换行」散文帖被模型折成句读，字节级逐字反复误杀 → 整博主按失败置空；归一只去 空白+CJK 句读，ASCII 小数/连字符不归，防 `3.5万→35万` 量级错位）。canonical quote 上限 `[:60]→[:90]`（展示截断移到 collapse，不反噬缓存原文）。
- **C 上卡复核**（`opinion/verify.py` + `summarize.py`）：只复核本档**新标注帖**产出且真上卡的少数行 keep/fix/drop；drop → 剔该帖该板行重坍缩续显更早合格行，无则置空；复核调用失败/超时 → **保留候选行**不吞正常行。计数入 log：`推送复核 N 条新帖上卡行 → keep=… fix=… drop=… err=…`。
- **D 失败回退**：annotate 返 `None`（失败）≠ 无观点——不抹窗口缓存旧行，坍缩回退续显（`quote_ts≥窗口下界` 门拦陈旧），不写缓存下档重试；`rows==[]`（真无观点）→ 卡面空不变。
- **缓存兼容**：代码-only 改动（quote 门校准、到案清洗）**不失效**缓存（prompt_fp 不变）；本版对共享 prompt 做过必要澄清（quote 句首纪律等）→ **prompt_fp 已变**，warm-up 首档全量重抽一次（v5 量级）。上线顺序：同步 → compile 冒烟 → dry-run warm-up 全量重抽 → 卡面对照 → 开调度。

---

## Linux 部署（通用示意）

### 步骤

```bash
# 1) 拷贝代码（父仓库已在 /srv/blogger_ana；data 由脚本自建，不拷）
#    v17 起还需父仓库顶层 opinion/（共享读帖/标注模块）——一并 rsync：
rsync -az --exclude data ./briefing ./opinion 用户@服务器:/srv/blogger_ana/

# 2) 依赖
cd /srv/blogger_ana/briefing && python -m pip install -r requirements.txt
python -m playwright install chromium

# 3) 配置 briefing/.env（勿提交；DEEPSEEK 可复用父仓库 .deepseek_keys.env）
#    DEEPSEEK_API_KEY=sk-...
#    FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/<超短群 token>
#    FEISHU_WEBHOOK_URL_SWING=https://open.feishu.cn/open-apis/bot/v2/hook/<波段群 token>
#    REPO_ROOT=/srv/blogger_ana

# 4) 试跑（落盘预览，不推送不改状态；非交易日可加 --skip-calendar）
python -m briefing.scripts.run_briefing --dry-run --time 09:30 --board both --no-scrape

# 5) 暖场真实推送双群各一卡（人工确认两 webhook 都通）：
python -m briefing.scripts.run_briefing --push --time 09:30 --board both
```

### cron（近似；完整交易日历保真靠 Windows 双任务 + 代码门禁）

```bash
sudo timedatectl set-timezone Asia/Shanghai
# 交易日两板块节奏：09:00–15:00 每 30 分 + 16:00–22:00 每整点（工作日；离节奏伪 tick 脚本在抓取/锁之前 exit 0）
*/30 9-15 * * 1-5 cd /srv/blogger_ana && python -m briefing.scripts.run_briefing --push >> briefing/data/cron.log 2>&1
0 16-22 * * 1-5 cd /srv/blogger_ana && python -m briefing.scripts.run_briefing --push >> briefing/data/cron.log 2>&1
# 非交易日只推波段（3 小时节奏）：周末 09/12/15/18/21
0 9,12,15,18,21 * * 0,6 cd /srv/blogger_ana && python -m briefing.scripts.run_briefing --push >> briefing/data/cron.log 2>&1
```
> cron 只能按星期几近似（交易日 ≠ 工作日：法定节假日周一~五会空跑、调休周六会漏推短卡）；精确的交易日历判定在代码里，Windows 双任务每天全时段唤醒 + 代码门禁无此缺口。

---

## Windows 部署（生产）

### 环境（已建立）

- SSH：`ssh windows-server`（Tailscale IP `100.64.70.12`，端口 2222，用户 `24966`，Mac 密钥 `~/.ssh/id_ed25519_windows`）
- Python：`C:\Users\24966\AppData\Local\Programs\Python\Python311\python.exe`
- 依赖：`openai requests playwright akshare psutil` + `python -m playwright install chromium`
- 时区：`China Standard Time`（已确认；`schtasks` 按宿主机时区触发）

### 目录与密钥

- 代码：`C:\Users\24966\blogger_ana`（父仓库 + briefing，含 .git 便于更新）
- 密钥（勿提交，scp 单独传入）：
  - `C:\Users\24966\blogger_ana\briefing\.env` → `FEISHU_WEBHOOK_URL`（超短群）、`FEISHU_WEBHOOK_URL_SWING`（波段群）
  - `C:\Users\24966\blogger_ana\.deepseek_keys.env` → `DEEPSEEK_API_KEY`
  - `paths.load_env()` 两者都读，`briefing/.env` 优先
- 运行时数据：`briefing\data\`（state.json / rows_cache.json / run.lock / briefing.log / briefings\ 历史）——从 Mac 传输时已排除，由脚本自建
- `briefing_runner.bat` 已冻结不改（v9 起的 ASCII+CRLF 约束仍有效，仅作历史入口；v13 调度不再经它）

### 更新代码（Mac → Windows）

```bash
cd /Users/potato/MyDoc/Study/MF/quant
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='briefing/data' \
    --exclude='data/posts/_backup' --exclude='*_bodies_s*' \
    --exclude='.deepseek_keys.env' --exclude='briefing/.env' \
    -cf - blogger_ana | ssh windows-server "cd C:\\Users\\24966 && tar -xf -"
```
> v17：整仓库打包自动带上顶层 `opinion/`（共享读帖/标注模块，briefing 运行时 import）——**不要**在 exclude 里加 `opinion`。手动更新若只拷 briefing/ 会缺模块。

### 首次/版本切换运行（关键：先 warm-up 再开调度）

1. 传/更新密钥：`scp briefing/.env .deepseek_keys.env windows-server:...`（注意目标路径；`.env` 要含 `FEISHU_WEBHOOK_URL_SWING`）
2. **手动 warm-up**（真实双群各推一卡，人工盯两端都收到，别让它在调度里超时）：
   `python -m briefing.scripts.run_briefing --push --time 09:30 --board both`
   成功 → 双群各收一张（超短 09:30 / 波段 09:30），state 建立双水位基线。
   **v5 行缓存上线首档会全量重抽一次**（按博主把窗口新帖合批，一次调用/博主、约数分钟，见 v17/v18 节）——warm-up 正好充当这次重抽，别误以为卡死；重抽完成后后续档逐帖命中：只有新帖才触发标注，旧帖永不重评分。
   旧 v12 state 无需手动改——脚本首跑自动迁移：`_migrate_state_v2`（清 v8 残留键）+ `_migrate_state_v3`（无 `fetched_at` → 回填旧 `last_run`）。
3. 电源硬化：`powercfg /change standby-timeout-ac 0`、`powercfg /change hibernate-timeout-ac 0`
4. **建调度（双任务，v15）**：
   `powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\24966\blogger_ana\briefing\runners\register_tasks.ps1`
   - 注册 **BriefingDay**（Daily 09:00 + Repetition 每 30 分钟 × 6 小时 → 覆盖 09:00–15:00 13 档）与 **BriefingEvening**（Daily 16:00 + Repetition 每 1 小时 × 6 小时 → 覆盖 16:00–22:00 7 档）；两者都 Direct 调 `python.exe -m briefing.scripts.run_briefing --push`（WorkingDirectory=`C:\Users\24966\blogger_ana`，绕过 bat），Daily 含周末——**交易日历/节奏/板块全由代码门禁判定**（交易日 09/12/15 由 Day 任务唤醒、18/21 由 Evening 唤醒，非交易日只放行波段）。
   - 设置：StartWhenAvailable（错过补跑）+ ExecutionTimeLimit **20min（<30 分网格，防跨档）** + MultipleInstances IgnoreNew；Principal 24966 Interactive Limited。
   - 脚本幂等：先注销旧 `BriefingIntraday/Morning/Afternoon/Late` 再重建两任务，末尾打印 trigger 校验与旧任务清理确认。
   - 手动触发测试：`schtasks /run /tn BriefingDay`（在节奏时刻触发 = 真推；离节奏触发 = 脚本门禁 exit 0，result 仍 0）。

### Windows 监控

- 日志：`C:\Users\24966\blogger_ana\briefing\data\briefing.log`
- 任务：`schtasks /query /fo list | findstr Briefing`
- 每档都推卡：交易日每档超短+波段各一张（各群各卡，内容没变也发、无 🆕）；非交易日只推波段卡；空板发最小卡；板块失败发错误心跳（各自 webhook，不串群）

### Windows 已知注意

- **单实例锁**：`briefing/data/run.lock`（pid 存活检测 + 3h 过期接管），进程被杀/断电残留锁下一轮自动接管，不会双发。
- **时区**：代码钉 `BEIJING_TZ`（北京时间），独立于宿主机时区；调度触发时间仍按宿主机时区（当前已为北京时间）。
- **子进程编码**：`scrape_merge.py` 已给所有 subprocess 传 `encoding="utf-8"` + `PYTHONIOENCODING=utf-8`（Windows 管道默认 GBK 会崩中文/emoji）。
- **头条风控**：若 Windows IP 触发"网络环境无法查看"，考虑放缓节流或换网络。
- **窗口口径（v14 交易日，用户修正；v15 波段 3→5）**：超短 = 前一交易日 00:00 至 now、波段 = 前 5 个交易日 00:00 至 now（`config.WINDOW_TRADING_DAYS` + `calendar.n_trading_days_ago`），非自然日——周一早晨窗口天然含上周五帖，无 v13"周一漏帖"取舍。
- 交易日历：akshare 拉取失败时回退内置 2026 节假日规则；跨年需更新 `calendar.py`。
