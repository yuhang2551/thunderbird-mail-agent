"""邮件层：作为 MCP 客户端启动 thunderbird-mcp 的 bridge（或测试用的假服务器），调它的工具。

只封装监控需要的几个工具：listAccounts、listFolders、getRecentMessages、getMessages、updateMessage。
每个工具的返回都是一段 JSON 文本，这里解析成模型；返回 {"error": ...} 时抛 MailboxError。
Thunderbird 没开时 bridge 照样能握手，但之后每个请求都回 JSON-RPC 错误（MCPError），这里也统一转成 MailboxError。
"""
from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError

from .models import Folder, MessageBody, MessageHeader

GET_MESSAGES_BATCH = 10  # 扩展默认每次最多 10 封


class MailboxError(RuntimeError):
    pass


class Mailbox:
    """用法：async with Mailbox(command) as mb: ..."""

    def __init__(self, command: list[str], *, env: dict[str, str] | None = None, call_timeout: float = 120.0):
        if not command:
            raise ValueError("command 不能为空")
        self.command = command
        self.env = env or {}
        self.call_timeout = call_timeout
        self.session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None

    async def __aenter__(self) -> "Mailbox":
        self._stack = AsyncExitStack()
        try:
            params = StdioServerParameters(
                command=self.command[0],
                args=self.command[1:],
                # bridge 要靠 HOME 等变量找 Thunderbird 写的 connection.json，所以把整个环境传给它
                env={**os.environ, **self.env},
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self.session = await self._stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
        except (OSError, MCPError) as exc:  # OSError：比如找不到 node 或 bridge
            await self._stack.aclose()
            raise MailboxError(f"启动邮件层失败（{' '.join(self.command)}）：{exc}") from exc
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._stack:
            await self._stack.aclose()
        self.session = None

    # ---- 底层调用 ----

    async def list_tools(self) -> list[str]:
        assert self.session
        try:
            result = await self.session.list_tools()
        except MCPError as exc:
            raise MailboxError(f"listTools: {exc}") from exc
        return [tool.name for tool in result.tools]

    async def call(self, name: str, **arguments: Any) -> Any:
        assert self.session, "Mailbox 还没进入 async with"
        args = {k: v for k, v in arguments.items() if v is not None}
        try:
            result = await self.session.call_tool(name, args, read_timeout_seconds=self.call_timeout)
        except MCPError as exc:
            raise MailboxError(f"{name}: {exc}") from exc
        content = getattr(result, "content", None) or []
        text = next((block.text for block in content if getattr(block, "type", "") == "text"), None)
        if getattr(result, "isError", False) or getattr(result, "is_error", False):
            raise MailboxError(f"{name}: {text or '工具调用失败'}")
        if text is None:
            raise MailboxError(f"{name}: 没有返回文本内容")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MailboxError(f"{name}: 返回的不是 JSON：{text[:200]}") from exc
        if isinstance(data, dict) and data.get("error"):
            raise MailboxError(f"{name}: {data['error']}")
        return data

    # ---- 监控用到的工具 ----

    async def list_accounts(self) -> list[dict[str, Any]]:
        data = await self.call("listAccounts")
        return data if isinstance(data, list) else []

    async def list_inboxes(self, accounts: list[str] | None = None) -> list[Folder]:
        """所有账号的收件箱。accounts 非空时只保留 id 或名字包含这些字符串的账号。"""
        names = {acc.get("id"): acc.get("name") or acc.get("id") for acc in await self.list_accounts()}
        folders = await self.call("listFolders")
        if isinstance(folders, dict):  # table 格式不会出现，防御一下
            folders = folders.get("rows", [])
        inboxes: list[Folder] = []
        for raw in folders:
            folder = Folder.model_validate(raw)
            if folder.type != "inbox":
                continue
            folder.account_name = names.get(folder.account_id) or folder.account_id
            if accounts and not _account_selected(folder, accounts):
                continue
            inboxes.append(folder)
        return inboxes

    async def recent(
        self, folder: Folder, *, days_back: int, max_results: int, unread_only: bool = False
    ) -> list[MessageHeader]:
        data = await self.call(
            "getRecentMessages",
            folderPath=folder.path,
            daysBack=days_back,
            maxResults=max_results,
            unreadOnly=unread_only,
            includeSubfolders=False,
        )
        rows = data.get("messages", []) if isinstance(data, dict) else data
        headers: list[MessageHeader] = []
        for raw in rows:
            header = MessageHeader.model_validate(raw)
            header.account_id = folder.account_id
            header.account_name = folder.account_name
            headers.append(header)
        return headers

    async def fetch_bodies(self, refs: list[tuple[str, str]], *, body_format: str = "text") -> dict[str, MessageBody]:
        """refs 是 (messageId, folderPath) 列表；按 10 封一批读全文。返回 messageId → MessageBody。"""
        bodies: dict[str, MessageBody] = {}
        for start in range(0, len(refs), GET_MESSAGES_BATCH):
            chunk = refs[start : start + GET_MESSAGES_BATCH]
            data = await self.call(
                "getMessages",
                messages=[{"messageId": mid, "folderPath": path} for mid, path in chunk],
                bodyFormat=body_format,
            )
            for raw in data.get("messages", []):
                body = MessageBody.model_validate(raw)
                if body.key:
                    bodies[body.key] = body
        return bodies

    async def add_tags(self, message_id: str, folder_path: str, tags: list[str]) -> None:
        await self.call("updateMessage", messageId=message_id, folderPath=folder_path, addTags=tags)


def _account_selected(folder: Folder, accounts: list[str]) -> bool:
    haystack = " ".join(filter(None, [folder.account_id, folder.account_name])).lower()
    return any(needle.lower() in haystack for needle in accounts)
