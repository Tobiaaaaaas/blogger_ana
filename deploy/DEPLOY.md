# 部署 —— Windows 生产机

波段推送跑在这台机器上 —— 按时刻表起档，抓帖、判帖、推卡、写状态全在本地。旧栈（`old_push/`）
的代码、数据、任务都留着，但**停役中**，任务保持 Disabled（见「旧栈」一节）。

| 栈 | 代码 | 数据 | 卡去哪 | 任务 | 当前 |
|:---|:---|:---|:---|:---|:---|
| 新栈（06 推送） | 仓库根 | 仓库根 `data/` | 波段群 | `PushDay` · `PushEvening` | 在跑 |
| 旧栈（briefing） | `old_push/` | `old_push/data/` · `old_push/briefing/data/` | 旧推送专用群 | `BriefingDay` · `BriefingEvening` | Disabled |

| 项 | 值 |
|:---|:---|
| 机器 | `ssh windows-server`（Tailscale `100.64.70.12`，端口 2222，用户 `24966`） |
| Python | `C:\Users\24966\AppData\Local\Programs\Python\Python311\python.exe` |
| 代码根 | `C:\Users\24966\blogger_ana` |
| 时区 | `China Standard Time` |

本文命令里的 `python` 一律指 `C:\Users\24966\AppData\Local\Programs\Python\Python311\python.exe`
（**不在 PATH 上**，照抄时补全路径）。

**只跑波段板块。** 新栈由 `run_push.bat` 把板块钉死成 `swing`；旧栈由
`old_push/briefing/scripts/config.py` 的 `due_boards()` 一律返回 `["swing"]`。超短板块的
webhook（`FEISHU_WEBHOOK_URL`）**故意不配** —— 真被唤起来也只会记失败，绝不误发。

**代码从 Mac 来，数据在 Windows 上长。** 上线那一次把 Mac 的 `data/` 整份搬过来当起点
（省掉重抓重判），此后 Windows 的 `data/` 就是它自己的活数据 —— 日常同步**只传代码**（见下）。
帖库、判断缓存、水位都在这台机器上往前走，Mac 那份停在上线那天。

---

## 目录

```
C:\Users\24966\blogger_ana\      新栈 —— Mac 仓库根的镜像
├─ deploy\                       部署层：本文件 · run_push.bat · register_tasks.ps1 · logs\
├─ data\                         新栈的库与状态
└─ old_push\                     旧栈整体（旧栈的仓库根）
   ├─ briefing\                  旧栈代码 + briefing\data\（state · rows_cache · 历史卡）
   └─ data\                      旧栈的帖子与行情
```

**没有 `.git`** —— 整仓 549M，同步时排除。这台机器是运行环境，不是开发机；要看差异回 Mac。

---

## 密钥

scp 单独传，绝不入库。

| 文件 | 给谁 | 装什么 |
|:---|:---|:---|
| `blogger_ana\.deepseek_keys.env` | 新栈 | `DEEPSEEK_API_KEY` · `FEISHU_WEBHOOK_URL_SWING`（波段群） |
| `blogger_ana\old_push\briefing\.env` | 旧栈 | `DEEPSEEK_API_KEY` · `FEISHU_WEBHOOK_URL_SWING`（旧推送专用群） |

两个文件里的 `FEISHU_WEBHOOK_URL_SWING` **是两个不同的群** —— 这是有意的，不是配错。

- 新栈读裸 `os.environ`（自己不带 .env 加载器），由 `deploy\run_push.bat` 把 env 喂进进程。
- 旧栈自己 `paths.load_env()`：先读 `briefing\.env`、**先到先得**，所以它拿到旧群那个。
- 两边都是**进程级**变量。绝不用 `setx` 写机器级／用户级环境变量 —— 那会让新栈读到旧群那个 webhook。

`.deepseek_keys.env` 里**不放** `FEISHU_WEBHOOK_URL` —— 放了就等于给超短卡留一条能误发的路。

---

## 同步代码与数据（Mac → Windows）

**第一次上线**：Windows 上还摆着重建前的老仓（根级 `briefing/ opinion/ knowledge/ scripts/ data/ .git`），
那些都要先搬开 —— tar 只覆盖不删除，不搬开就成了新旧混在一起。

```bash
scp deploy/move_aside_legacy.ps1 windows-server:C:/Users/24966/move_aside.ps1
ssh windows-server "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\24966\\move_aside.ps1"
```

**是移动不是删除** —— 全部落进 `_superseded_20260916\`，能原样搬回来。核对无误后自行删掉。

**第一次同步**（带数据，一次性 bootstrap）：

```bash
cd /Users/potato/MyDoc/Study/MF/quant
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    --exclude='.git' --exclude='archive' \
    --exclude='blogger_ana/.deepseek_keys.env' \
    --exclude='blogger_ana/old_push/briefing/.env' \
    -cf - blogger_ana | ssh windows-server "cd C:\\Users\\24966 && tar -xf -"
```

约 33 MB、435 个条目。排除 `archive/`（369M 的历史归档，机器上不需要）与两个密钥文件。
**`opinion/` 不能排除** —— 旧栈运行时 import 它（`old_push/opinion/`）。

**日常更新代码**（只传代码，**不带 `data/`**）：

```bash
cd /Users/potato/MyDoc/Study/MF/quant
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    --exclude='.git' --exclude='archive' \
    --exclude='blogger_ana/data' \
    --exclude='blogger_ana/old_push/data' \
    --exclude='blogger_ana/old_push/briefing/data' \
    --exclude='blogger_ana/reports' \
    --exclude='blogger_ana/.deepseek_keys.env' \
    --exclude='blogger_ana/old_push/briefing/.env' \
    -cf - blogger_ana | ssh windows-server "cd C:\\Users\\24966 && tar -xf -"
```

> **⚠️ 日常同步必须排掉三份 `data/`。** Windows 上线后自己也在抓帖、判帖、推卡 —— 它的
> `data/`、`old_push/data/`（帖与行情）、`old_push/briefing/data/`（state · rows_cache · 历史卡）
> 都比 Mac 的新。整树覆盖会把水位（`scrape_time`、`fetched_at`）拽回旧点，白重抓一轮。
> Mac 的 `data/` 只在**第一次 bootstrap** 时用一次，之后它就是一份历史快照，不再是真源。
> 排掉 `reports/` 是同一回事 —— 报告由报告链写，Windows 不产报告，那份也没在更新。

搬开的老仓留在 `_superseded_20260916\`，核对无误后可自行删掉。

---

## 第一次上线（顺序不能换）

1. **搬开老根** —— 上面那条 `move`。
2. **同步** —— 上面那条 tar。
3. **传密钥** —— 两处，见上表。
4. **冒烟** —— 在 Windows 上：
   ```
   cd C:\Users\24966\blogger_ana
   python -m compileall -q blogger push backtest old_push\briefing
   deploy\run_push.bat --force --dry-run
   cd old_push
   python -m briefing.scripts.run_briefing --dry-run --no-scrape --time 15:00
   ```
   新栈必须带 `--force` —— 不带就只看时刻表，档外直接「不在档上」退出，什么也没验到。
   `--dry-run` 抓帖与行情照走（会写 `data\`），**不发卡、不落档、不推进状态**。
   两条都看到卡面打出来、末行不报错即可。
5. **手动真发一档** —— 确认波段群收到：
   ```
   deploy\run_push.bat --force
   ```
   `--force` 跳过档位门（不看时刻表），但**照过交易日历**。
6. **启用任务** —— 两个：
   ```
   powershell -NoProfile -Command "foreach($n in 'PushDay','PushEvening'){Enable-ScheduledTask -TaskName $n}"
   ```

**任务注册脚本一律把四个任务建成 Disabled**，启用是单独一步、由人点头。
`register_tasks.ps1` 幂等，可反复跑。
**旧栈那两个不启用** —— 旧栈已停役，`BriefingDay` · `BriefingEvening` 保持 Disabled。

---

## 日常

| 想干什么 | 怎么做 |
|:---|:---|
| 更新代码 | 跑上面那条 tar（会自动覆盖，不用停任务）—— **但改到 `blogger/parse/prompts.py` 那种契约文件要挑档间空档，见下表** |
| 看日志 | `deploy\logs\push_swing.log`（`run_push.bat` 追加写，`PYTHONIOENCODING=utf-8`） |
| 看任务状态 | `schtasks /query /fo list \| findstr /i "Push Briefing"` |
| 手动补一档 | `deploy\run_push.bat --force` |
| 停掉推送 | `foreach($n in 'PushDay','PushEvening'){Disable-ScheduledTask -TaskName $n}` |

**日志只在 `run_push.bat` 里落** —— 推送自己不写日志文件（输出全走 `print`），
任务计划不重定向就是全丢。所以**别绕过这个 .bat 直接调 `python -m push`**。

---

## 旧栈（停役）

代码、数据、任务都在这台机器上，`BriefingDay` · `BriefingEvening` **一律保持 Disabled**。

| 项 | 值 |
|:---|:---|
| 代码 | `C:\Users\24966\blogger_ana\old_push\` |
| 密钥 | `old_push\briefing\.env` —— `FEISHU_WEBHOOK_URL_SWING` 指向旧推送专用群 |
| 日志 | `old_push\briefing\data\briefing.log` |
| 手动发一档 | `cd old_push` 后 `python -m briefing.scripts.run_briefing --push --time 15:00` |
| 启用 | `foreach($n in 'BriefingDay','BriefingEvening'){Enable-ScheduledTask -TaskName $n}` |

`run_briefing` 没有 `--force` —— 用 `--time` 把决策时刻摆到一个档上。**别加 `--board`**：显式板块
会绕过日历门，非交易日还会直接拒绝推送；auto 这条路才走 `due_boards` → 只出波段。

---

## 已知注意

| 事 | 说明 |
|:---|:---|
| **旧栈复役后同档并发抓头条** | 那时同一分钟两栈各抓一遍（新栈 29 位串行、旧栈 46 位 `--workers 5`）。头条风控是 IP 级的，真触发「网络环境无法查看」就考虑错开或换网络 |
| **执行时限** | 新栈 30 分钟；旧栈 20 分钟（照旧，复役时才用得上）。`IgnoreNew` 下挂住的那一档会占着锁，中间几档直接退出 |
| **锁** | 一把，OS 级（走 `msvcrt`）—— 进程被杀锁自动放，不留僵尸锁 |
| **控制台是 GBK** | 带 emoji 的输出直接 print 会 `UnicodeEncodeError`（断言全过却非 0 退出）。新栈靠 `PYTHONIOENCODING=utf-8` + 重定向绕开 |
| **密钥文件是 UTF-8，cmd 按 GBK 读** | `run_push.bat` 的加载循环**必须先过 `findstr` 筛出赋值行** —— 直读整个文件时，中文注释的尾字节被 GBK 当成第二字节、连行尾换行一起吞掉，紧跟其后的 `KEY=value` 并进注释里丢掉。2026-09-16 第一次真发就是这么丢的 `FEISHU_WEBHOOK_URL_SWING`：推送照跑到 `[⑨ 推送]`，卡一张没发，日志里只留一行「没配」。旧栈走 `paths.load_env()`（Python 按 UTF-8 读），不受这条影响 |
| **密钥文件别拿 PowerShell 直读** | 上面那条 GBK 坑在**读**的一侧同样成立：`Get-Content` 默认按系统 ANSI 解码，中文注释的尾字节连行尾换行一起吞掉，紧跟的 `KEY=value` 并进注释 —— **打出来就像那一行不存在**。核对密钥用 `Get-Content -Encoding UTF8`，或 `scp` 回 Mac 看 |
| **⚠️ 不在推送时段内同步判读契约** | **新栈**：改 `blogger/parse/prompts.py` 会改规则指纹 → `data\state\parse_cache\` 整批作废。指纹变后的**第一跑**才并得进窗口内全部，那一跑要是落在 `--dry-run` 或中途报错，`push_swing.json` 里留的就还是旧读法的行，往后每档都并不进新的 —— 所以改完读法要**紧接着跑一次 `--init` 重建分布**（06§4）<br>**旧栈**（复役时）：改 `opinion/prompts.py` 会改 `annotation_fp_input()` 指纹 → `rows_cache` 全量作废、下一档整窗重抽，同一帖在新旧契约下可能给出不同判定（2026-09-09 连续三次同步，导致智由智哉的波段行一天内闪变三次） |
| **`matplotlib` 没装** | 只有 `backtest/render.py` 用它，而推送不跑回测。要在 Windows 上跑回测才需 `pip install matplotlib` |
| 交易日历 | akshare 拉取失败时回退内置规则；跨年需更新 |
