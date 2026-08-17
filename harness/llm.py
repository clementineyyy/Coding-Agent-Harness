from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import openai
from openai import OpenAI

RETRY_BACKOFF = 1.0


class LLMError(Exception):
    """LLM 调用失败基类。"""


class LLMAuthError(LLMError):
    """认证失败（401）。"""


class LLMRateLimitError(LLMError):
    """限流（429），退避重试一次后仍失败。"""


class LLMNetworkError(LLMError):
    """网络连接异常。"""


@dataclass
class LLMResult:
    text: str
    tool_calls: list[dict]
    usage: dict


class LLM(ABC):
    @abstractmethod
    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResult:
        """发送消息与工具定义，返回聚合文本、工具调用与用量估算。"""


class OpenAILLM(LLM):
    """OpenAI 兼容 API（DeepSeek）流式客户端，注入 http_client 供测试。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        http_client: httpx.Client | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            max_retries=0,
        )

    def _create_stream(self, messages: list[dict], tools: list[dict]):
        try:
            return self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools or None,
                stream=True,
            )
        except openai.AuthenticationError as exc:
            raise LLMAuthError(str(exc)) from exc
        except openai.RateLimitError as exc:
            time.sleep(RETRY_BACKOFF)
            try:
                return self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools or None,
                    stream=True,
                )
            except openai.RateLimitError as exc2:
                raise LLMRateLimitError(str(exc2)) from exc2
        except openai.APIConnectionError as exc:
            raise LLMNetworkError(str(exc)) from exc
        except httpx.TransportError as exc:
            raise LLMNetworkError(str(exc)) from exc

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResult:
        stream = self._create_stream(messages, tools)
        text_parts: list[str] = []
        tool_acc: dict[int, dict] = {}
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    text_parts.append(delta.content)
                if delta and delta.tool_calls:
                    for call in delta.tool_calls:
                        slot = tool_acc.setdefault(
                            call.index, {"name": "", "arguments": ""}
                        )
                        if call.function and call.function.name:
                            slot["name"] += call.function.name
                        if call.function and call.function.arguments:
                            slot["arguments"] += call.function.arguments
        except openai.APIConnectionError as exc:
            raise LLMNetworkError(str(exc)) from exc
        except httpx.TransportError as exc:
            raise LLMNetworkError(str(exc)) from exc

        text = "".join(text_parts)
        tool_calls: list[dict] = []
        for index in sorted(tool_acc):
            slot = tool_acc[index]
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise LLMError(
                    f"tool call {index} arguments JSON parse failed: {exc}; "
                    f"raw arguments: {slot['arguments']!r}"
                ) from exc
            tool_calls.append({"name": slot["name"], "arguments": arguments})
        usage = {"approx_tokens": self._approx_tokens(text, tool_calls)}
        return LLMResult(text=text, tool_calls=tool_calls, usage=usage)

    def _approx_tokens(self, text: str, tool_calls: list[dict]) -> int:
        chars = len(text)
        for call in tool_calls:
            chars += len(call["name"])
            chars += len(json.dumps(call["arguments"], ensure_ascii=False))
        return chars // 4
