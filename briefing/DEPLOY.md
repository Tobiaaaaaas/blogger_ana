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
- **C 上卡复核**（`opinion/verify.py` + `summarize.py`）：复核**上卡行** keep/fix/drop；drop → 剔该帖该板行重坍缩续显更早合格行，无则置空；复核调用失败/超时 → **保留候选行**不吞正常行。计数入 log：`推送复核 N 条新帖上卡行 → keep=… fix=… drop=… err=…`。**触发集有两个（v22，2026-09-10）**：① 本档**新标注帖**产出且真上卡的行（原集）；② **盲区回填**——最终上卡的冠军行若出自**旧帖缓存**（触发集①看不到它）且源行无 `rv` 标记（= 从未裁决过）→ 补一轮复核，log `回填复核 N 条未复核过的上卡行 → …`。① 才是常态（本档改卡的行）；② 每档上限 `REVIEW_BACKFILL_MAX=6` 条，超出 loud log 下档续，`err` 记 `rv_try`、两次仍不可用即放弃（log 里可见）。**回填不改缓存格式、不进 `annotation_fp_input` 指纹 → 同步它不作废 `rows_cache`**（新增键 `rv`/`rv_try` 落在缓存行上，旧缓存无此键＝未复核，首档起逐档收敛）。
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
- **⚠️ 验证终点既有三份实现，改一处必同步**（2026-09-10）：`scripts/eval/run_direction.py`
  （canonical/打分）/ `research/trading_cal.py`（mirror）/ `briefing/scripts/endpoint.py`（推送）。
  `opinion/tests/test_endpoint_consistency.py` 702 组网格三方比对钉死，改任一份即红。
  **2026-09-10 起三份已完全归一、无任何豁免格**（此前 `周六/日 × nweek` 有一处有意分歧：
  push 走"博主视角周+7"前瞻式、canonical/mirror 走 `pub+7`，导致周末"本周"与"下周"撞成
  同一天）。现行**统一周口径**（自然周，非交易日不顺延）：
  - `week` = **发布自然日所在** ISO 周最后交易日 → 周末/节假日发帖时该周已收盘，终点落在
    发布日之前 → 报告侧 `无效-过时`、推送侧过期门剔除、research 侧 `target < 投票日` 不投票；
  - `nweek` = **发布日 +7 天**所在 ISO 周最后交易日（周末说"下周"= 即将到来那一周）；
  - `nweek_first` = 发布日 +7 天所在 ISO 周首个交易日（周五~周日发帖时 ≡ `t1`）。

  非交易日的「回顾 vs 前瞻」之分**不在引擎而在判层**（前瞻 → `nweek`；回顾 → 不产行，
  `opinion/prompts.py` §3 周期词表 + `SKILL.md` §3），引擎不再替模型猜"周末说的本周是哪一周"。
  **对既有语料的量化影响**：全量 `data/direction_signals`（251 文件 / 27,094 条）中
  `spec=week` 985 条 → 293 条终点位移、其中 286 条转为 `无效-过时`（冻结语料不重抽，
  等于这 286 条退出计分）；`nweek` 零位移（canonical/mirror 本来就对）。推送侧 live
  `rows_cache` 周末帖产出的是 `nweek`/`nweek_first`/`t1`/`long`、**零条 `week`**，故卡面
  变化只有：周末 `nweek` 行的终点与锚定周段**各前移一周**（09-18 → 09-11）。
- **⚠️ 不在推送时段内同步标注契约**（2026-09-10 教训，务必遵守）：改 `opinion/prompts.py`
  的判读文本（`DOCTRINE_NO_DIRECTION` / `DOCTRINE_REVIEW` / ANNOTATION prompt）会改变
  `annotation_fp_input()` 指纹 → 推送侧 `rows_cache` **全量作废、下一档整窗重抽**。重抽是
  LLM 调用，同一帖在新旧契约下**可能给出不同判定**（灰区帖尤甚）。2026-09-09 白天到晚间
  连续三次同步契约，导致同一位博主（智由智哉）的波段行在一天内"有→无→有"闪变三次，事后
  排查花了一整轮——**契约同步/暖场请在任务 Disabled 或非档位时段做**，做完再看效果。
  本轮（2026-09-10 周口径修正）同样含 `opinion/prompts.py` 补条 → **指纹会变**，同步须等
  `BriefingDay`（09:00–15:00 每 30 分）/`BriefingEvening`（16:00–22:00 每整点）档位之外。
  **本轮实测记录（2026-09-10 13:12 部署，取 13:00 档跑完后的档间空档）**：
  - 同步方式改为**只传改动文件清单**（`git show --name-only <commit>` → `tar -cf - -T 清单`，
    86 个文件），不整仓打包——整仓打包会把未提交的假帖 WIP 一并带上生产机。传完逐个核对
    SHA256 与 Mac 一致（86/86 ✓）。
  - **随后补齐存量漂移**：再按 `git ls-files`（排除 `data/`、`briefing/data/`、`research/signals`
    与 `*/reports/` 与 4 项假帖 WIP）取 146 个文件全量对齐，`0 / 146` 差异。清掉的漂移里有
    **`research/config.py`**（Windows 侧陈旧，仍在 `TRADING_TICKS = list(_bcfg.TRADING_TICKS)`，
    而 `briefing/scripts/config.py` 早已删掉该常量 → `test_watermark_coverage.py` 在 Windows 上
    `AttributeError`）、`opinion/tests/test_*.py` 13 个从未同步过的测试、`archive/` 旧路径残留 10 个。
    对齐后该测试在 Windows 上 **5 项断言全 PASS、退出码 0**。
  - 随即暖场 `--dry-run --no-scrape --time 13:15 --board both`（约 2 分钟）：全量重抽 40 位
    博主 + 复核 5 条裁决，缓存指纹落到 `75944d77`；**未推送、未改水位**。
  - **本轮契约文件时间线**（说明为什么今天指纹动了两次）：`opinion/annotate.py` 10:53:46 →
    第一版契约在 ~10:58 同步，指纹 `64693e11 → f9efdd23`；`opinion/prompts.py` 12:48:28 定稿
    （补「回顾 vs 前瞻」之分＝用户本轮的核心要求），随 13:12 的 86 文件包同步，指纹
    `f9efdd23 → 75944d77`。**即 13:00 档是在第一版契约下推的，13:30 档起才是定稿契约**——
    盘中改了两次契约正是上一段警告的情形，本轮无法避免（修订指令本身是盘中和用户对齐的），
    但**以后请把契约修订攒到非档位时段一次到位**。
  - **周口径的可见效果符合预期**：周末帖的 `nweek` 行终点与锚定周段各前移一周（家有高中生2 /
    知行合一 / 爱生活的荷叶Rp：终点 09-18 → **09-11**，anchor 下周 09-14~09-18 → 本周
    09-07~09-11）；周中 `week` 行（赵红力 / 大盘蜂向标 / 我觉醒了）终点不变；**零条**周末
    `week` 行——判层没有把周末"本周"误编成 `week`。
  - **但卡面变化不止于此**：全量重抽连带把灰区/复核的判定也重掷了一次（上一段的机制），
    当日波段卡上卡集合因此换掉 4 位（智由智哉、山顶望星空的诗人 下卡；四十二流光、诸葛不亮
    换帖上卡），short 卡多 1 位（云帆观市）。**这与周口径无关，是"契约变更 = 全量重抽 =
    判定重掷"的必然代价**，不是本次修正的缺陷——换口径就得接受它重掷一次。
  - **⚠️ Windows 控制台是 GBK**：`opinion/tests/test_*.py` 17 个文件收尾都 print ✅/🔴/🟢，
    在 GBK 控制台上会抛 `UnicodeEncodeError: 'gbk' codec can't encode character '✅'`——
    **断言已全过，却让进程以非 0 退出**（假失败）。已在这 17 个文件的 `sys.path.insert` 之后统一加
    `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 守卫；加后 Windows 上中文与
    emoji 均正常输出、退出码 0。**新增测试文件请照抄这两行**。

---

**本轮实测记录（2026-09-10 13:48 部署，取 13:30 档跑完后的档间空档）——判层补正：禁编造 + 教义引语溯源**

触发：13:30 档核验时发现**一条编造方向的行正在每档上卡**——博主「大盘蜂向标」09-07 12:49 帖
（原文全文仅"本周会怎么走?我觉得会先抑后扬。"，**通篇无任何方向词**）却产出 `d=+1`、`spec=week`，
`summary` 写"本周先抑后扬，整体看多"。自 09-09 18:00 起每一档 swing 卡都带它。

- **根因不是"判读过宽"，是教义里埋了一句伪造的原话**：`summary` 里的"整体看多"逐字来自 Q4 教义的
  正例「下周先抑后扬，整体看多」——该句被登记为**用户原句（智由智哉 09-06 帖）**，但逐字核对：
  该帖（id 7682259213178946087，740 字）**不含**"先抑后扬""整体看多""看多""看涨"；该博主 127 帖
  全都搜不到；全库 80,815 帖中"整体看多"**只出现 3 次**（"先抑后扬"775 次）。即：那句是模型捏造的，
  被当成真帖原话写进教义当正例，随后作为**可照抄模板**被搬到别的帖上 → 编造行。
  **教训：教义里的示例措辞会被模型逐字搬运。**
- 处置（判层，纯文本）：① `DOCTRINE_NO_DIRECTION` 加硬约束「**净方向词必须出自原帖**——拿去原帖正文里搜，
  搜不到即不产行；严禁替博主补他没说的方向词，严禁把教义示例措辞搬进 quote/summary」；
  ② Q4 正例换成语料核验真句（2026-05-24 周日 A股王 帖 id=1866055285835784：形态句"个人认为下周先抑后扬"
  ＋同周期独立无条件净方向句"对于下周周线个人看涨"）；③ **旧幽灵句不再在教义里复述**（复述＝重新播种）；
  ④ 「先抑后扬」补进形态枚举并立专条，同时**放宽**：该周期若另有独立净方向句**或明确逢跌买入承诺**
  （回踩就是机会/回踩大胆进——操作动词=方向）→ 以那句成行（语料里 775 帖"先抑后扬"绝大多数是
  "形态半句+回踩买入半句"的看多路径表述，不得整条漏掉）；⑤ `DOCTRINE_REVIEW` 加**条目 10**
  （行内方向词原帖找不到 = 编造 → 一律 drop，首查"先抑后扬类形态被读成方向"）——此前复核侧无此条，
  故一路放行。
- 新增回归 **`opinion/tests/test_doctrine_provenance.py`**（18 个测试）：`BANNED` 硬断言已知捏造句不得回流教义
  （不依赖语料）；`PROVENANCE` 把教义里声称的博主原话拿去 `data/posts` 逐字比对（语料缺失/未收录该帖则 SKIP
  并汇总条数，不静默通过）。**新增/修改教义引语先跑它。**
- 实测（13:48 暖场，`--dry-run --no-scrape`）：`prompt_fp` 75944d77 → c4c20efe → **e4fc9d8e**；缓存 97→105→**107** 行；
  复核 `23 条新帖上卡行 → keep=16 fix=0 drop=7`（此前 drop=4/5）。**编造行审计：`整体看X` 类原帖找不到的方向词
  = 0 条**（修前 1 条）；quote 非原文照抄 2 条，均为孙万林用「……」连接两段真实原文（**非编造**，属引用省略，
  待定是否收紧）。大盘蜂向标该行已彻底消失，当日其冠军换成 09-08 帖 `spec=t5`。
- **别把"改判层"当成"只改措辞"**：本轮三次契约变更（10:53 第一版 / 12:48 定稿 / 13:38+13:47 补正）每次都
  全量重抽、重掷判定。档间空档做，别在推送时段做。

---

**本轮变更（2026-09-10）——B8：上卡行复核盲区回填（`briefing/scripts/summarize.py`）**

修上一条里**编造行为什么能连续多档上卡**的机制性缺口，不是文本补丁。

- **盲区**：复核触发集（v21）只认「本档新标注帖产出且坍缩后真上卡」的行。于是两类行**永不复核**：
  ① 本档复核 drop / 被新帖顶替后**顶上来的旧帖缓存行**；② 新帖当档未夺冠、后续档因冠军过期才顶上的行。
  大盘蜂向标那条编造行正是①：它出自 09-07 旧帖，一旦顶上来就再也没进过复核触发集 → 判层补正
  （条目 10）**只对新抽的行生效**，缓存里已有的行仍要靠这道门兜。
- **修法**：`extract_layers` 在「本档复核 + 重坍缩」之后，对**最终上卡的冠军行**逐条查「是否复核过」——
  源规范行带 `rv` 标记（随逐帖缓存持久化；keep/fix/drop 都算已裁决）即跳过，未标记的补一轮复核
  （同一 `review_candidates` 通道、同 v21 固化语义：fix 就地覆写源行、drop 剔该板层行重坍缩）。
- **两个上限**：`REVIEW_BACKFILL_MAX = 6`（每档最多补几条——上线首档存量上卡行全都无 `rv`，无上限会在
  一个档里串行补审数十条、直接拖长推送档；有上限则逐档收敛，log 里会打"本档待补 N 条，本档补 6 条"）；
  `REVIEW_BACKFILL_ATTEMPTS = 2`（同一行 `err` 两次即放弃 + loud log，防某行永久占住每档名额）。
  **单轮不级联**：本档回填重坍缩后新顶上的行留给下档（档位延迟有界，每档最多两轮复核调用）。
- **不作废缓存**：`rv`/`rv_try` 是缓存行新增键，不在 `annotation_fp_input()` 指纹域、不 bump
  `_ROWS_CACHE_VERSION`（维持 v6）→ **可以任意档间空档同步，不需要暖场重抽**。
- **上线后看这几行 log**（首档起几档内）：`上卡行复核盲区回填：本档待补 N 条，本档补 6 条（余 N-6 条下档续）`
  → `回填复核 6 条未复核过的上卡行 → keep/fix/drop` → `回填复核裁决 K 条已固化进逐帖缓存并重坍缩`。
  待补数逐档递减到 0（此后该行不再出现）即为收敛；若某行反复出现 `复核连续 2 次不可用 → 放弃回填`，
  说明复核侧（DeepSeek）在故障，看当时 `推送复核 … err=` 是否同时升高。
- **测试**：`opinion/tests/test_review_persist.py` 新增场景 6/7/8（盲区顶上→当档补复核并固化；err 保行 + 两次
  放弃；存量 8 条分两档收敛后零调用），并给旧场景的预置缓存行标 `rv=1`；`test_extract_wiring.py` 相应更新
  （标注失败回退的旧行、drop 顶上来的旧行现在各多一次回填复核调用）。Mac 全量 `opinion/tests/test_*.py`
  **18/18 绿**。
