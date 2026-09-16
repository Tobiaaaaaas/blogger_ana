# 20260916-四段流程 —— 换套读法，量出来更差

**这一份放着 02 那一代「四段流程」的全部代码与实验**：代码切句打标、模型逐句表态、代码核出处落档、代码定失败粒度。模型只给 `d` 与三个指针（`dw`／`ow`／`tw`），从不自己写 `spec`／`idx`／`quote`。

**上线当天退回链条式。** 换套读法的理由是「逐句表态能把判断拆小、更稳」，实测反过来：

| 量什么 | 四段流程 | 链条式 |
|:---|---:|---:|
| 帖级两遍不一致（扣丁） | **17.2%** | **12.8%** |
| 语料 | 三位博主、1834 帖 | 三位博主、1834 帖 |

**根因在服务端，不在读法。** `temperature=0` 下两遍是同一个函数调两次，系统性错误同向 —— 复读、二选一投票，一次也救不了。拆小判断这件事，改不了「同一个函数调两次」。

**只有一处留了下来**：六类标记里的**条件句**守门（37/37 不冤枉），随流程回到 `blogger/parse/hints.py`。其余五类（路径词 258/6、「先…后…」47/4、机制推演词 97/5、观察句 6/1）实测都会冤枉，一律不用 —— 见 [semparse/README.md](semparse/README.md) §六。

## 目录里有什么

| 文件 | 是什么 |
|:---|:---|
| `annotate.py` | ② 逐句表态 —— 模型只给 `d` 与指针，第 2 遍看得见第 1 遍的答案 |
| `assemble.py` | ③ 核与组装 —— 指针回原句核出处，落 `spec`／`idx`／`quote` |
| `segment.py` | ① 切与标 —— 断句、打六类标记 |
| `reconcile.py` | 第三轮的复核实验 —— 两遍对不上的帖逐条判该不该算，结论见 [semparse/reports/](semparse/reports/) |
| `semparse/` | 那一轮的实验层、全部产物（[reports/](semparse/reports/)）与结论 [README.md](semparse/README.md) |

**这一份是快照，读得懂、跑不起来** —— 它 import 的 `blogger.report.flow` 已按链条式改回，四段那套调用面没有了。**要跑快照，先回到它还在的那个提交**：

```bash
git checkout 2edd161 -- blogger/parse research/semparse
```

**它还 import `blogger.parse.lexicons` 的 `marks_of`／`has_ignored_sector`／`sector_word`** —— 那三个名字链条式下没人调，但**别删**：删了这一份就连读都读不成了。
