# -*- coding: utf-8 -*-
"""DeepSeek 调用网关：call_json / parse_response / 守护线程硬超时。

自 scripts/pipeline/extract_signals_direction.py 原样迁出（call_json / parse_response /
_call_with_deadline + 网络常量），让 推送(briefing) / 报告(extract) / 画像(profiles) 共用
同一稳定链路；消除 summarize._extract() 对父脚本的 file-load（importlib file-load 的坑：
模块无缓存复用、sys.modules 键名易冲突——见 2026-09-08 重构记录）。
"""
import json
import os
import re
import threading
import time

from openai import OpenAI

# ── 网络/模型常量 ──
MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
# 硬性 wall-clock 超时（秒）。DeepSeek 服务端偶尔会拖拽连接/维持连接不响应，OpenAI SDK 的
# timeout 只对"完全无数据"生效——服务端持续发字节会重置读超时 → 无限挂起（2026-08-31 连挂
# 4 位博主）。用守护线程强制放弃：单次调用绝不超 API_CALL_DEADLINE，3 次重试最坏 ~9 分钟。
API_CALL_DEADLINE = 180


def _call_with_deadline(fn, deadline, label):
    """守护线程执行 fn，硬性 wall-clock 超时——服务端拖拽连接也强制放弃，绝不无限挂起。"""
    box = {}

    def runner():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 —— 守护线程里任何异常都应装盒上报，不能杀主流程
            box["error"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(deadline)
    if t.is_alive():
        raise TimeoutError(f"{label}: 超过 {deadline}s 硬性超时，放弃本次调用")
    if "error" in box:
        raise box["error"]
    return box["value"]


def call_json(client, system_prompt, user_message, label, thinking=False):
    """调 DeepSeek，返回 (parsed_dict, raw) 或 (None, None)。

    thinking=False：关推理（标注/抽取阶段，省 token）；thinking=True：开推理（综合/审查，
    更仔细）。client 参数仅保留旧签名兼容（两场景调用方都传 None/客户端——本网关每次都建
    全新 client，不复用被拖拽的毒连接）。

    每次 attempt 用全新 client + 硬性 wall-clock 超时：服务端偶尔拖拽连接不响应，SDK
    timeout 不生效（读超时被字节流重置），必须守护线程硬切，否则单次调用可挂死整轮。
    """
    for attempt in range(MAX_RETRIES):
        c = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=BASE_URL, timeout=API_CALL_DEADLINE)
        try:
            response = _call_with_deadline(
                lambda c=c: c.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0,
                    max_tokens=8192,
                    extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}},
                ),
                API_CALL_DEADLINE,
                f"{label} attempt {attempt + 1}",
            )
            raw = response.choices[0].message.content
            result = parse_response(raw)
            if result is not None:
                return result, raw
            print(f"  {label} attempt {attempt + 1}: JSON parse failed, retrying...")
            time.sleep(RETRY_DELAY * (attempt + 1))
        except Exception as e:
            print(f"  {label} attempt {attempt + 1}: API error: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise
    return None, None


def parse_response(raw):
    """解析 LLM 返回的 JSON（任意顶层 dict），处理 markdown 代码块与截断 JSON。"""
    if not raw:
        return None

    text = raw.strip()

    # 去 markdown 代码块
    if text.startswith("```"):
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # 直接解析
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 括号配对扫描：找最外层对象
    for m in re.finditer(r"\{", text):
        start = m.start()
        depth, end = 0, -1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            try:
                data = json.loads(text[start:end])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue

    # 兜底：补全未闭合括号
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    if open_braces > 0 or open_brackets > 0:
        try:
            data = json.loads(text + "]" * open_brackets + "}" * open_braces)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None
