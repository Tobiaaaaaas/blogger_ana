# -*- coding: utf-8 -*-
"""模型网关 —— 全套只有这一个地方调模型。

环境变量 `DEEPSEEK_API_KEY`，缺了直接报错，不做静默降级。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

from openai import OpenAI

MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"
MAX_RETRIES = 3
RETRY_DELAY = 5

# 硬性 wall-clock 超时（秒）。服务端偶尔会拖着连接不回，SDK 自己的 timeout 只对「完全没数据」
# 生效 —— 服务端持续发字节会把读超时一次次重置，于是无限挂起。所以用守护线程硬切：
# 单次调用绝不超这个数。
CALL_DEADLINE = 180


class ModelError(RuntimeError):
    """调不通模型 —— 调用方自行决定是跳过这一批还是整轮中止。"""


def _with_deadline(fn, deadline: int, label: str):
    box: dict = {}

    def runner():
        try:
            box["value"] = fn()
        except BaseException as e:          # 守护线程里任何异常都要装盒上报，不能杀主流程
            box["error"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(deadline)
    if t.is_alive():
        raise TimeoutError(f"{label}：超过 {deadline}s 硬性超时，放弃本次调用")
    if "error" in box:
        raise box["error"]
    return box["value"]


def call_json(system_prompt: str, user_message: str, label: str = "call",
              thinking: bool = False) -> dict | None:
    """调模型，返回解析好的 dict。返回 None = 三次都没拿到合法 JSON。

    每次尝试都建全新的 client —— 不复用可能已被拖死的连接。
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ModelError("环境变量 DEEPSEEK_API_KEY 没设，无法调模型")

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=CALL_DEADLINE)
            response = _with_deadline(
                lambda: client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "system", "content": system_prompt},
                              {"role": "user", "content": user_message}],
                    temperature=0,
                    max_tokens=8192,
                    extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}},
                ),
                CALL_DEADLINE,
                f"{label} 第 {attempt} 次",
            )
            parsed = parse_json(response.choices[0].message.content)
            if parsed is not None:
                return parsed
            last_error = "返回的不是合法 JSON"
            print(f"  {label} 第 {attempt} 次：{last_error}")
        except Exception as e:
            last_error = e
            print(f"  {label} 第 {attempt} 次：{e}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)
    raise ModelError(f"{label} 连续 {MAX_RETRIES} 次失败：{last_error}")


def parse_json(raw: str | None) -> dict | None:
    """从模型返回里抠出那个 JSON 对象。容忍代码块围栏与截断。"""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 括号配对扫描：找最外层那个对象
    for m in re.finditer(r"\{", text):
        depth, end = 0, -1
        for i in range(m.start(), len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > m.start():
            try:
                data = json.loads(text[m.start():end])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue

    # 兜底：把没闭上的括号补上
    ob, ok = text.count("{") - text.count("}"), text.count("[") - text.count("]")
    if ob > 0 or ok > 0:
        try:
            data = json.loads(text + "]" * ok + "}" * ob)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None
