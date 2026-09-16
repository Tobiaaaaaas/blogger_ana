# blogger/tests/ —— 端到端试跑

改完 `blogger/` 里的东西，用这一套跑一遍看有没有跑坏。**它不碰生产数据。**

**两条命令都必须带 `-m`** —— 直接 `python blogger/tests/xxx.py` 会因为 `blogger` 不在 `sys.path` 上而报 `ModuleNotFoundError`。

```bash
python -m blogger.tests.drive            # 默认跑 aniu24W
python -m blogger.tests.drive <博主名>
```

它把 `fixture/` 拷进一个临时数据根（系统临时目录下的 `blogger_selftest/`），
行情从仓库的 `data/market` 接过去，然后调 `blogger.report.flow` 里**真的那几个函数**
跑完 ②～⑦ 步 —— 只跳过 ① 抓取（不必开浏览器）。

结果留在那个临时目录里，每次跑重建，**仓库一个字节都不写**。

## fixture/ 是什么

一位博主（`aniu24W`）的一份真实切片：

| 文件 | 是什么 |
|:---|:---|
| `posts/aniu24W.json` | 抓下来的帖子（含 `pub`，是新格式） |
| `signals/aniu24W.json` | 上一次跑出来的观点信号（6 键） |

**这一趟会真调模型** —— 判断缓存没有随 `fixture/` 留下，所以跑 `drive` 必须有
`DEEPSEEK_API_KEY`，没有就直接报错退出。改的要是纯计算那几段（验证／统计／渲染），
跑它照样会调一次模型。

`drive.py` 跑完会顺手调 `invariant.py` —— 核对 **04§3.2 那条硬约束**：
榜上那五个数，必须与单博主报告里「预测对象＝上证指数」那一行**逐格相同**。
它是从报告正文里把那一行**读回来**比的，不是「两边调同一个函数」那种自己证明自己。
**两边都没有那一行**（这位博主本来就没有上证计分信号）算**一致**，不算「对不上」。

```bash
python -m blogger.tests.invariant            # 全库
python -m blogger.tests.invariant <博主名>
```

## 判两遍，比抖动

这一件**已随 02 换代退役、归档**：`archive/20260916-旧解析流程/jitter.py`，怎么跑、为什么退，见那里的 README。

## 现在还缺什么

- 只有一位博主、一份样本，**够不上跑 04 全博主对比**（榜单至少要 30 条计分信号）
- 01 抓取那一环不在这一套里 —— 它要开真浏览器
- 旧栈那 18 个 pytest 文件已随 `opinion/` 一并删掉 —— 本目录是现在唯一的测试入口
