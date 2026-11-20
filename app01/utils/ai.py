"""
大模型客户端（T1）+ 输入防护（T6）
==================================

把大模型当成"会写字的接口"：给它 messages，它返回文字。
全项目只通过这里的 LLMClient 调用模型，好处是：

    1. 换模型/换服务商只改 .env，不改业务代码；
    2. 超时、鉴权失败、限流、断网都在这一处翻译成中文提示；
    3. 限流、长度校验这类安全逻辑也只写一次。

四个能力对应四个方法：
    chat()          单轮：一句话进，一段话出（招聘 JD、制度问答、数据点评）
    chat_messages() 多轮：带历史（对话助手 T5）
    stream()        流式：逐块吐字（SSE T7）
    available()     是否配好了 Key（页面据此提示"AI 未配置"）
"""
from __future__ import annotations

import logging
import re
import time

from django.conf import settings

logger = logging.getLogger("ai")


class LLMError(Exception):
    """
    所有模型调用异常的统一出口。

    视图层只需要 `except LLMError as e: return JsonResponse({"status": False, "msg": str(e)})`，
    不用关心底层是超时、Key 错还是 429 —— 那些翻译都在 LLMClient 里做完了。
    `str(e)` 就是给用户看的中文提示，不含 Key、不含堆栈。
    """


# ------------------------------------------------------------------
# 一、客户端封装
# ------------------------------------------------------------------
class LLMClient:
    """大模型调用入口（懒加载单例，整个进程共用一个连接池）。"""

    _client = None

    # ---- 是否可用 ----
    @classmethod
    def available(cls):
        """
        是否配置了 Key。

        为什么要单独判断：
          没配 Key 时如果直接发请求，用户会看到 "401 Token is invalid"，
          分不清是配置问题还是代码问题。这里提前拦下，提示更明确。
        """
        return bool(settings.AI_API_KEY)

    # ---- 懒加载客户端 ----
    @classmethod
    def _get_client(cls):
        if not cls.available():
            raise LLMError("AI 未配置：请先在项目根目录的 .env 里填写 AI_API_KEY")

        if cls._client is None:
            from openai import OpenAI   # 延迟导入：没装 openai 也能启动项目

            cls._client = OpenAI(
                api_key=settings.AI_API_KEY,
                base_url=settings.AI_BASE_URL,   # 换服务商只改这一行配置
                timeout=settings.AI_TIMEOUT,
                max_retries=0,                   # 不重试：宁可提示失败，也不让页面转圈
            )
        return cls._client

    # ---- 异常翻译 ----
    @classmethod
    def _translate(cls, exc):
        """
        把 SDK 抛出的异常翻译成用户能看懂的中文。

        为什么不让异常直接冒到页面：
          1. 原始报错含 url、请求头，可能带出 Key 片段；
          2. 英文报错对学生/演示观众不友好。
        """
        import openai

        name = type(exc).__name__
        if isinstance(exc, openai.AuthenticationError):
            return LLMError("AI Key 无效或已过期，请检查 .env 中的 AI_API_KEY")
        if isinstance(exc, openai.RateLimitError):
            return LLMError("当前调用人数较多（免费模型限流），请 10 秒后重试")
        if isinstance(exc, openai.APITimeoutError):
            return LLMError("模型响应超时，请重试；若持续超时请检查网络")
        if isinstance(exc, openai.APIConnectionError):
            return LLMError("连不上模型服务，请检查网络或代理设置")
        if isinstance(exc, openai.BadRequestError):
            return LLMError("请求被模型拒绝（可能是输入过长或模型名不对）")
        logger.exception("AI 调用失败：%s", name)
        return LLMError(f"AI 调用失败（{name}），请稍后重试")

    # ---- 单轮 ----
    @classmethod
    def chat(cls, prompt, system=None, temperature=0.7, max_tokens=1024):
        """
        单轮对话：一句提示词 → 一段回答。

        :param prompt:      用户任务（必填）
        :param system:      角色设定（三段式的第一段）
        :param temperature: 随机度，0.3 稳定 / 0.8 发散
        :param max_tokens:  回答长度上限，防止一次吐太多占额度
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return cls.chat_messages(messages, temperature=temperature, max_tokens=max_tokens)

    # ---- 多轮 ----
    @classmethod
    def chat_messages(cls, messages, temperature=0.7, max_tokens=1024):
        """多轮对话：messages 里已经排好 system / user / assistant 的顺序。"""
        if settings.AI_OFFLINE_DEMO:
            # 离线兜底：答辩断网时用预置文本，保证流程能走完（文档里会标注这是演示模式）
            return "【离线演示模式】当前未联网，这是一段预置的示例回答。"

        client = cls._get_client()
        started = time.time()
        try:
            resp = client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = (resp.choices[0].message.content or "").strip()
            logger.info("AI 调用成功 %.2fs model=%s", time.time() - started, settings.AI_MODEL)
            if not text:
                raise LLMError("模型返回了空内容，请重试")
            return text
        except LLMError:
            raise
        except Exception as exc:          # noqa: BLE001 —— 统一在这里收口，视图层不再写裸 except
            raise cls._translate(exc) from None

    # ---- 流式 ----
    @classmethod
    def stream(cls, messages, temperature=0.7, max_tokens=1024):
        """
        流式生成：生成器，逐块 yield 文本（T7 的 SSE 就靠它）。

        注意异常处理：生成器里的异常会发生在"已经开始响应之后"，
        这时 HTTP 头已经发出去了，没法再改状态码，
        所以流式接口的前端要能接收 data:{"error": "..."} 这种帧。
        """
        if settings.AI_OFFLINE_DEMO:
            for piece in ["【离线演示模式】", "当前未联网，", "这是一段预置的示例回答。"]:
                yield piece
                time.sleep(0.15)
            return

        client = cls._get_client()
        try:
            resp = client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in resp:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None)
                if piece:
                    yield piece
        except Exception as exc:          # noqa: BLE001
            err = cls._translate(exc)
            logger.warning("AI 流式失败：%s", err)
            raise err from None


# ------------------------------------------------------------------
# 二、输入防护（T6）
# ------------------------------------------------------------------
# 控制字符（\x00-\x1f 除换行/制表）会把终端和日志搞乱，直接清掉
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_input(text, max_len=None, field="内容"):
    """
    统一清洗用户输入：去控制字符、去首尾空白、长度校验。

    返回 (clean_text, error_msg)：
        error_msg 为 None 表示通过；否则直接把它回给前端。

    为什么长度不静默截断：
      截断后模型拿到的是一句不完整的话，答案会莫名其妙，
      用户还以为"AI 答错了"。明确提示"太长"反而更好排查。
    """
    text = (text or "").strip()
    text = _CONTROL_CHARS.sub("", text)
    max_len = max_len or settings.AI_MAX_INPUT

    if not text:
        return "", f"{field}不能为空"
    if len(text) < 2:
        return "", f"{field}至少 2 个字"
    if len(text) > max_len:
        return "", f"{field}过长（{len(text)} 字），请控制在 {max_len} 字以内"
    # 纯符号/纯空白：没有任何文字信息，调模型也是浪费额度
    if not re.search(r"[0-9A-Za-z\u4e00-\u9fa5]", text):
        return "", f"{field}需要包含文字或数字"
    return text, None


def check_rate_limit(request):
    """
    会话级限流：两次调用至少间隔 AI_MIN_INTERVAL 秒，且每天不超过 AI_DAILY_LIMIT 次。

    为什么放 session 而不放数据库：
      课设规模不需要分布式限流，session 已经能覆盖"同一个人连点按钮"；
      也避免为限流专门建表。

    返回 None 表示放行；返回字符串表示被拦下的原因。
    """
    from datetime import date

    now = time.time()
    today = date.today().isoformat()
    state = request.session.get("ai_rate", {})

    # 跨天重置计数
    if state.get("day") != today:
        state = {"day": today, "count": 0, "last": 0}

    if state.get("count", 0) >= settings.AI_DAILY_LIMIT:
        return f"今日 AI 调用次数已达上限（{settings.AI_DAILY_LIMIT} 次），请明天再试"

    elapsed = now - float(state.get("last", 0) or 0)
    if elapsed < settings.AI_MIN_INTERVAL:
        wait = settings.AI_MIN_INTERVAL - int(elapsed)
        return f"操作过快，请 {max(wait, 1)} 秒后再试"

    return None


def mark_rate_used(request):
    """调用成功后记账：次数 +1，记下时间戳。"""
    from datetime import date

    today = date.today().isoformat()
    state = request.session.get("ai_rate", {})
    if state.get("day") != today:
        state = {"day": today, "count": 0, "last": 0}
    state["count"] = state.get("count", 0) + 1
    state["last"] = time.time()
    request.session["ai_rate"] = state
