"""推送层：把一条消息发出去。四种后端：终端、notify-hub、飞书 / Lark 群自定义机器人（webhook）、飞书 / Lark 应用机器人。

- notify-hub 是本机的通知网关（https://github.com/yuhang2551/notify-hub）：Lark 卡片、夜里免打扰、去重、失败重发都归它管。
- 自定义机器人最简单：群里加一个机器人就有 webhook，可选签名校验。
- 应用机器人需要 app_id / app_secret，可以直接私聊发给你，不用建群。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from .config import resolve_binary

log = logging.getLogger(__name__)

Level = Literal["urgent", "normal"]


class NotifyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Push:
    """要推的一条消息。终端和 Lark 文本消息发 text；notify-hub 用 title、body 做卡片，按 level 分级、按 key 去重。"""

    text: str
    title: str
    body: str = ""
    level: Level = "normal"  # urgent：红色卡片，夜里也发；normal：notify-hub 免打扰时段先攒着，结束后合成一张发
    key: str | None = None

    @classmethod
    def plain(cls, text: str, *, level: Level = "normal") -> Push:
        """只有一段文字时（比如 notify-test）：第一行当标题，其余当正文。"""
        title, _, body = text.strip().partition("\n")
        return cls(text=text, title=title, body=body.strip(), level=level)


class Notifier(Protocol):
    name: str

    async def send(self, push: Push) -> None: ...


class ConsoleNotifier:
    name = "console"

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.pushes: list[Push] = []

    async def send(self, push: Push) -> None:
        self.sent.append(push.text)
        self.pushes.append(push)
        print("─" * 40)
        print(push.text)


_INSTALL_HINT = (
    "先装 notify-hub（~/.local/bin/uv tool install git+https://github.com/yuhang2551/notify-hub），"
    "或者在 .env 里把 MAIL_MONITOR_NOTIFY_HUB_BIN 写成完整路径"
)


class NotifyHubNotifier:
    """交给 notify-hub：调用它的命令行，正文从标准输入传。推不出去时它先把消息存进发件箱、之后自己重发，
    所以它正常退出就算交出去了；只有它没装、参数不对、配置坏了才算失败。"""

    name = "notify_hub"
    source = "mail"  # 在 notify-hub 里分组、限流用的来源名

    def __init__(self, binary: str = "notify-hub", *, timeout: float = 60.0):
        self.binary = resolve_binary(binary)
        self.timeout = timeout
        self.last_output = ""  # notify-hub 最后一次说了什么，notify-test 打印给你看

    def command(self, push: Push) -> list[str]:
        command = [self.binary, "send", "--body", "-", "--level", push.level, "--source", self.source]
        if push.key:
            command += ["--key", push.key]
        return [*command, "--", push.title]  # 标题放在 -- 后面，以 - 开头也不会被当成选项

    async def send(self, push: Push) -> None:
        env = {**os.environ, "PYTHONUTF8": "1"}  # launchd 下没有 LANG，中文照样按 UTF-8 传
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command(push),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            raise NotifyError(f"运行不了 {self.binary}：{exc}。{_INSTALL_HINT}") from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(push.body.encode("utf-8")), self.timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise NotifyError(f"notify-hub {self.timeout:.0f} 秒没有返回") from None
        self.last_output = (stdout + stderr).decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise NotifyError(f"notify-hub 退出码 {process.returncode}：{self.last_output[:200]}")
        log.info("notify-hub：%s", self.last_output)

    def version(self) -> str:
        """doctor 用：notify-hub 装好了没有，是哪个版本。不联网。"""
        try:
            result = subprocess.run([self.binary, "version"], capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotifyError(f"运行不了 {self.binary}：{exc}。{_INSTALL_HINT}") from exc
        if result.returncode != 0:
            raise NotifyError(f"{self.binary} version 退出码 {result.returncode}：{(result.stderr or result.stdout).strip()[:200]}")
        return result.stdout.strip()


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

    async def send(self, push: Push) -> None:
        try:
            response = await self._client.post(self.url, json=self.payload(push.text))
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

    async def send(self, push: Push) -> None:
        if not self.receive_id:
            raise NotifyError("没有设置 LARK_RECEIVE_ID（用 mail-monitor lark-chats 查群 id，或 --email 查 open_id）")
        token = await self._tenant_token()
        try:
            response = await self._client.post(
                "/open-apis/im/v1/messages",
                params={"receive_id_type": self.receive_id_type},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": self.receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": push.text}, ensure_ascii=False),
                },
            )
        except httpx.HTTPError as exc:
            raise NotifyError(f"发送消息失败：{exc}") from exc
        _check_lark_response(response, "im/v1/messages")

    async def list_chats(self) -> list[dict[str, Any]]:
        """机器人所在的群（需要权限 im:chat:readonly）。把机器人拉进一个群以后用它拿 chat_id。"""
        token = await self._tenant_token()
        chats: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            try:
                response = await self._client.get(
                    "/open-apis/im/v1/chats", params=params, headers={"Authorization": f"Bearer {token}"}
                )
            except httpx.HTTPError as exc:
                raise NotifyError(f"获取群列表失败：{exc}") from exc
            data = _check_lark_response(response, "im/v1/chats").get("data", {})
            chats.extend({"chat_id": item.get("chat_id"), "name": item.get("name")} for item in data.get("items", []))
            page_token = data.get("page_token") if data.get("has_more") else None
            if not page_token:
                return chats

    async def lookup_open_id(self, email: str) -> str | None:
        """按邮箱查 open_id（需要权限 contact:user.id:readonly）。查不到返回 None。"""
        token = await self._tenant_token()
        try:
            response = await self._client.post(
                "/open-apis/contact/v3/users/batch_get_id",
                params={"user_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
                json={"emails": [email]},
            )
        except httpx.HTTPError as exc:
            raise NotifyError(f"查 open_id 失败：{exc}") from exc
        data = _check_lark_response(response, "contact/v3/users/batch_get_id").get("data", {})
        for item in data.get("user_list", []):
            if item.get("user_id"):
                return item["user_id"]
        return None

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


def infer_receive_id_type(receive_id: str | None) -> str:
    """没写 LARK_RECEIVE_ID_TYPE 时按 id 的样子判断：oc_ 是群，ou_ 是个人 open_id，on_ 是 union_id，带 @ 的是邮箱。"""
    rid = (receive_id or "").strip()
    if rid.startswith("oc_"):
        return "chat_id"
    if rid.startswith("on_"):
        return "union_id"
    if "@" in rid:
        return "email"
    return "open_id"


def build_notifier(settings: Any) -> Notifier:
    backend = settings.notify_backend
    if backend == "console":
        return ConsoleNotifier()
    if backend == "notify_hub":
        return NotifyHubNotifier(settings.notify_hub_bin)
    if backend == "lark_webhook":
        if not settings.lark_webhook_url:
            raise NotifyError("MAIL_MONITOR_NOTIFY=lark_webhook 但没有设置 LARK_WEBHOOK_URL")
        return LarkWebhookNotifier(settings.lark_webhook_url, settings.lark_webhook_secret)
    if backend == "lark_app":
        missing = [k for k in ("lark_app_id", "lark_app_secret", "lark_receive_id") if not getattr(settings, k)]
        if missing:
            raise NotifyError("MAIL_MONITOR_NOTIFY=lark_app 还缺：" + ", ".join(m.upper() for m in missing))
        return build_lark_app(settings)
    raise NotifyError(f"不认识的推送后端：{backend}")


def build_lark_app(settings: Any) -> LarkAppNotifier:
    """只要 app_id / app_secret 就能建，receive_id 可以后补（lark-chats 查 id 时用）。"""
    if not (settings.lark_app_id and settings.lark_app_secret):
        raise NotifyError("需要 LARK_APP_ID 和 LARK_APP_SECRET（开发者后台 → 应用 → 凭证与基础信息）")
    return LarkAppNotifier(
        domain=settings.lark_domain,
        app_id=settings.lark_app_id,
        app_secret=settings.lark_app_secret,
        receive_id=settings.lark_receive_id or "",
        receive_id_type=settings.lark_receive_id_type or infer_receive_id_type(settings.lark_receive_id),
    )
