"""LLM 调用：OpenAI 兼容的 chat/completions 接口（默认 DeepSeek），只用 JSON 模式。

判断层只依赖 ChatClient 这一个接口：提示词进、JSON 对象出。Claude 订阅版在 claude_cli.py，实现的是同一个接口。

故意不引入厂商 SDK：一个 POST 就够，换模型只改 base_url 和 model。各家的私有参数（比如 DeepSeek 的思考开关）走 extra_body。
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

import httpx


class LLMError(RuntimeError):
    pass


class ChatClient(Protocol):
    async def chat_json(self, system: str, user: str) -> dict[str, Any]: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def parse_json_object(text: str) -> dict[str, Any]:
    """从模型输出里抠出一个 JSON 对象。容忍代码围栏和前后多余文字。"""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LLMError(f"模型没有返回 JSON：{text[:200]!r}")
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"模型返回的 JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("模型返回的 JSON 不是对象")
    return data


class LLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        extra_body: dict[str, Any] | None = None,
    ):
        self.model = model
        self.extra_body = dict(extra_body or {})
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_json(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 800
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self.extra_body,
        }
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"请求模型失败：{exc}") from exc
        if response.status_code != 200:
            raise LLMError(f"模型接口返回 HTTP {response.status_code}：{response.text[:300]}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"模型接口返回格式不对：{response.text[:300]}") from exc
        return parse_json_object(content or "")
