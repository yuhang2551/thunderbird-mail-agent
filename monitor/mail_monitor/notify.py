"""推送层：把一段文本发出去。三种后端：终端、飞书 / Lark 群自定义机器人（webhook）、飞书 / Lark 应用机器人。

- 自定义机器人最简单：群里加一个机器人就有 webhook，可选签名校验。
- 应用机器人需要 app_id / app_secret，可以直接私聊发给你，不用建群。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)


class NotifyError(RuntimeError):
    pass


class Notifier(Protocol):
    name: str

    async def send(self, text: str) -> None: ...


class ConsoleNotifier:
    name = "console"

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)
        print("─" * 40)
        print(text)


def lark_webhook_sign(secret: str, timestamp: int) -> str:
    """飞书 / Lark 自定义机器人的签名：以 "timestamp\\nsecret" 为 key、空串为消息做 HMAC-SHA256，再 base64。"""
    key = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(key, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class LarkWebhookNotifier:
    name = "lark_webhook"

    def __init__(self, url: str, secret: str | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        self.url = url
        self.secret = secret
        self._client = httpx.AsyncClient(timeout=15, transport=transport)

    def payload(self, text: str, *, timestamp: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"msg_type": "text", "content": {"text": text}}
        if self.secret:
            ts = timestamp or int(time.time())
            body["timestamp"] = str(ts)
            body["sign"] = lark_webhook_sign(self.secret, ts)
        return body

    async def send(self, text: str) -> None:
        try:
            response = await self._client.post(self.url, json=self.payload(text))
        except httpx.HTTPError as exc:
            raise NotifyError(f"webhook 请求失败：{exc}") from exc
        _check_lark_response(response, "webhook")

    async def aclose(self) -> None:
        await self._client.aclose()


class LarkAppNotifier:
    name = "lark_app"

    def __init__(
        self,
        *,
        domain: str,
        app_id: str,
        app_secret: str,
        receive_id: str,
        receive_id_type: str = "open_id",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.domain = domain.rstrip("/")
        self.app_id = app_id
        self.app_secret = app_secret
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type
        self._client = httpx.AsyncClient(base_url=self.domain, timeout=15, transport=transport)
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def _tenant_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        try:
            response = await self._client.post(
                "/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
        except httpx.HTTPError as exc:
            raise NotifyError(f"获取 tenant_access_token 失败：{exc}") from exc
        data = _check_lark_response(response, "tenant_access_token")
        self._token = data.get("tenant_access_token")
        self._token_expires_at = time.time() + float(data.get("expire", 7200))
        if not self._token:
            raise NotifyError("tenant_access_token 为空")
        return self._token

    async def send(self, text: str) -> None:
        token = await self._tenant_token()
        try:
            response = await self._client.post(
                "/open-apis/im/v1/messages",
                params={"receive_id_type": self.receive_id_type},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": self.receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                },
            )
        except httpx.HTTPError as exc:
            raise NotifyError(f"发送消息失败：{exc}") from exc
        _check_lark_response(response, "im/v1/messages")

    async def aclose(self) -> None:
        await self._client.aclose()


def _check_lark_response(response: httpx.Response, what: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise NotifyError(f"{what} 返回 HTTP {response.status_code}：{response.text[:200]}")
    try:
        data = response.json()
    except ValueError as exc:
        raise NotifyError(f"{what} 返回的不是 JSON：{response.text[:200]}") from exc
    # 新接口用 code，老的 webhook 接口用 StatusCode；0 表示成功
    code = data.get("code", data.get("StatusCode", 0))
    if code != 0:
        raise NotifyError(f"{what} 失败：code={code} msg={data.get('msg') or data.get('StatusMessage')}")
    return data


def build_notifier(settings: Any) -> Notifier:
    backend = settings.notify_backend
    if backend == "console":
        return ConsoleNotifier()
    if backend == "lark_webhook":
        if not settings.lark_webhook_url:
            raise NotifyError("MAIL_MONITOR_NOTIFY=lark_webhook 但没有设置 LARK_WEBHOOK_URL")
        return LarkWebhookNotifier(settings.lark_webhook_url, settings.lark_webhook_secret)
    if backend == "lark_app":
        missing = [k for k in ("lark_app_id", "lark_app_secret", "lark_receive_id") if not getattr(settings, k)]
        if missing:
            raise NotifyError("MAIL_MONITOR_NOTIFY=lark_app 还缺：" + ", ".join(m.upper() for m in missing))
        return LarkAppNotifier(
            domain=settings.lark_domain,
            app_id=settings.lark_app_id,
            app_secret=settings.lark_app_secret,
            receive_id=settings.lark_receive_id,
            receive_id_type=settings.lark_receive_id_type,
        )
    raise NotifyError(f"不认识的推送后端：{backend}")
