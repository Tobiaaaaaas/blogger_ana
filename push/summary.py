# -*- coding: utf-8 -*-
"""06§6.2 底部那段总结 —— **整条推送链里第二次、也是最后一次用模型**。

喂给它的是**本档已经算好的分布与计数**，它一个数都不许自己算。写失败 → **兜底成一行计数**，
不整张卡报废（06§7）。
"""

from __future__ import annotations

from blogger.common import ds

SYSTEM_PROMPT = """你在给一条「博主观点分布」的推送卡片写结尾的一句话总结。

**规矩**：

1. **只准用给到你的名单与计数，一个数都不许自己算、自己估、自己补。** 没给到的不写。
2. 讲的是**这张卡上呈现出来的多空对立**：分歧在哪、方向偏向哪边、有没有明显一致的地方。
3. **不写投资建议** —— 不写「建议关注」「注意风险」「仅供参考」这类。
4. **不写套话** —— 不写「综上所述」「总体来看」。
5. 中文，不要 emoji，不要标题，**就一句话**。
6. 篇幅不超过 {limit} 字。

**输出格式**：一个 JSON 对象，只有一键 —— `{{"总结": "那一句话"}}`。除了这个 JSON 什么都不要输出。"""


def fallback(counts: tuple[int, int]) -> str:
    """模型调不通时的那一行计数（06§6.2）。"""
    return f"多空版图：{counts[0]}多{counts[1]}空"


def write(cfg: dict, picked: list[dict], counts: tuple[int, int], log=print) -> str:
    """写总结。**调不通不算这一档失败** —— 兜底成一行计数，卡照发。"""
    n_long, n_short = counts
    body = [f"板块：{cfg['name']}板块", f"计数：{n_long}多 / {n_short}空", ""]
    body.append("上卡的条数（按池子顺序）：")
    for rec in picked:
        side = "看多" if rec["d"] > 0 else "看空"
        ep = (rec.get("ep") or "")[5:10] or "（终点算不出）"      # 与卡上同写 MM-DD
        body.append(f"- {rec['name']}：{side}，终点 {ep}")
    try:
        got = ds.call_json(SYSTEM_PROMPT.replace("{limit}", str(cfg["summary_limit"])),
                           "\n".join(body), label="推送总结")
    except ds.ModelError as e:
        log(f"  总结没写出来：{e}")
        return fallback(counts)

    text = ((got or {}).get("总结") or (got or {}).get("text") or "").strip()
    if not text:
        log("  总结没写出来：模型没给出可用的正文")
        return fallback(counts)
    return text[:cfg["summary_limit"]]


__all__ = ["write", "fallback"]
