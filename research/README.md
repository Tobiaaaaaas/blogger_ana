# research

**这一层不是产品代码，是实验。** 里面的东西可以不合家法、可以随时推翻；跑出来的数据
要能回答一个问题，才算没白写。

| 目录 | 在试什么 | 结论 |
|:---|:---|:---|
| [semparse/](semparse/) | 02 的读法稳不稳 —— 同一条帖判两遍，量对不上的占多少 | 见 [semparse/README.md](semparse/README.md) |
| [regex_ab/](regex_ab/) | 正则辅助那一层值多少 —— 摆清单、条件句守门、每条设置各值多少 | 见 [regex_ab/README.md](regex_ab/README.md) |
| [crosscheck/](crosscheck/) | 矛盾复核（02§10.5）值多少 —— 带不带提示、改动落在哪儿（量的是 `idx`／`spec` 那两栏） | 见 [crosscheck/README.md](crosscheck/README.md) |

**四段流程那一轮已结案归档**，产物见 [../archive/20260916-四段流程/](../archive/20260916-四段流程/)。

**规矩**：只读引用 `blogger/`，一个字不改；产物落各自的 `reports/`（`semparse` 那一轮的
`reports/` 已随归档，现在只往 stdout 与 `docs/判例/` 走）；不碰 `data/`、
不写判断缓存、不动调度。方案验证得过才谈部署。
