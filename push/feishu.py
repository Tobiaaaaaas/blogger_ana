# -*- coding: utf-8 -*-
"""06§5.10 发卡 —— 重试、失败提醒。**地址从环境变量读，不写进仓库**（06§9）。

| 板块 | 环境变量 |
|:---|:---|
| 超短 | `FEISHU_WEBHOOK_URL` |
| 波段 | `FEISHU_WEBHOOK_URL_SWING` |

**某板块没配地址 → 该板块失败** —— 不回落另一个群，也不发提醒（提醒也得有地址才能发）（06§7）。
"""

from __future__ import annotations

import os
import time

OK = 0                      # 飞书成功返回的 code


def address(cfg: dict) -> str:
    """本板块的推送地址。没配就是空串。"""
    return os.environ.get(cfg["webhook"]) or ""


def send(cfg: dict, text: str, log=print) -> bool:
    """把卡片发到**本板块自己的群**。失败重试 `push.retries` 次，间隔从 `retry_delay` 秒起递增。

    **重试仍失败 → 不补发**：本档就丢了，下一档带的是最新的分布（06§5.10）。
    发提醒这件事由调用方决定（`alert`）。
    """
    url = address(cfg)
    if not url:
        log(f"  {cfg['webhook']} 没配 —— 本板块发不出去")
        return False

    payload = {"msg_type": "interactive",
               "card": {"config": {"wide_screen_mode": True},
                        "elements": [{"tag": "div",
                                      "text": {"tag": "lark_md", "content": text}}]}}
    delay, last = cfg["retry_delay"], None
    for attempt in range(1, cfg["retries"] + 1):
        try:
            code, msg = _post(url, payload, cfg["timeout"])
            if code == OK:
                return True
            last = f"code={code} {msg}"
        except Exception as e:               # 网络问题也算一次，接着重试
            last = repr(e)
        log(f"  发卡第 {attempt} 次没成：{last}")
        if attempt < cfg["retries"]:
            time.sleep(delay)
            delay *= 2
    log(f"  发卡连着 {cfg['retries']} 次没成：{last}")
    return False


def alert(cfg: dict, text: str) -> None:
    """失败的纯文本提醒 —— 往**同一个群**发。**不检查这条提醒自己是否成功**（06§5.10）。"""
    url = address(cfg)
    if not url:
        return
    try:
        _post(url, {"msg_type": "text", "content": {"text": text}}, cfg["timeout"])
    except Exception:
        pass


def _post(url: str, payload: dict, timeout: int) -> tuple[int, str]:
    """POST 一次，返回飞书的 `(code, msg)`。"""
    import requests

    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    doc = r.json() or {}
    return int(doc.get("code") or 0), str(doc.get("msg") or "")


__all__ = ["address", "send", "alert"]
