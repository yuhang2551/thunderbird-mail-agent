"""假的 thunderbird-mcp：用固定数据模拟上游扩展的几个工具，让流水线在没有 Thunderbird 的地方也能跑测试。

工具名、参数名、返回结构照抄上游 v0.9.2（extension/mcp_server/api.js），所以换成真 bridge 时代码不用改。
用法：python tests/fake_server.py [fixture.json]（stdio），不传参数时用 FAKE_MAILBOX_FIXTURE 指向的 JSON，默认 fixtures/mailbox.json。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

# 数据来源：命令行第一个参数 > FAKE_MAILBOX_FIXTURE 环境变量 > fixtures/mailbox.json
FIXTURE = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FAKE_MAILBOX_FIXTURE", Path(__file__).parent / "fixtures" / "mailbox.json"))
NOW = datetime.now(timezone.utc)
HEADER_KEYS = ["id", "threadId", "subject", "author", "recipients", "ccList", "date", "folder", "folderPath", "read", "flagged", "tags", "preview"]


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load() -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for message in data["messages"]:
        # fixture 里写的是"几小时前"，这里换算成绝对时间，测试才不会过期
        message["date"] = _iso(NOW - timedelta(hours=float(message.pop("age_hours", 1))))
        message.setdefault("tags", [])
        message.setdefault("read", False)
        message.setdefault("flagged", False)
        message.setdefault("preview", (message.get("body") or "")[:200].replace("\n", " "))
    return data


DATA = _load()
UPDATES: list[dict[str, Any]] = []
server = MCPServer("thunderbird-mcp-fake")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _header(message: dict[str, Any]) -> dict[str, Any]:
    row = {key: message.get(key) for key in HEADER_KEYS}
    folder = next((f for f in DATA["folders"] if f["path"] == message["folderPath"]), None)
    row["folder"] = folder["name"] if folder else "Inbox"
    row["threadId"] = message.get("threadId", abs(hash(message["id"])) % 100000)
    return row


@server.tool()
def listAccounts() -> str:
    return _dump(DATA["accounts"])


@server.tool()
def listFolders(
    accountId: str | None = None, folderPath: str | None = None, format: str | None = None, favoritesOnly: bool | None = None
) -> str:
    folders = DATA["folders"]
    if accountId:
        folders = [f for f in folders if f["accountId"] == accountId]
    if folderPath:
        folders = [f for f in folders if f["path"].startswith(folderPath)]
    return _dump(folders)


@server.tool()
def getRecentMessages(
    folderPath: str | None = None,
    daysBack: float | None = None,
    maxResults: int | None = None,
    offset: int | None = None,
    unreadOnly: bool | None = None,
    flaggedOnly: bool | None = None,
    includeSubfolders: bool | None = None,
) -> str:
    days = daysBack if daysBack and daysBack > 0 else 7
    cutoff = NOW - timedelta(days=days)
    rows = []
    for message in DATA["messages"]:
        if folderPath and message["folderPath"] != folderPath:
            continue
        if datetime.fromisoformat(message["date"].replace("Z", "+00:00")) < cutoff:
            continue
        if unreadOnly and message.get("read"):
            continue
        if flaggedOnly and not message.get("flagged"):
            continue
        rows.append(_header(message))
    rows.sort(key=lambda r: r["date"], reverse=True)
    limit = min(int(maxResults) if maxResults and maxResults > 0 else 50, 200)
    if offset is not None:
        page = rows[offset : offset + limit]
        return _dump({"messages": page, "totalMatches": len(rows), "offset": offset, "limit": limit, "hasMore": offset + limit < len(rows)})
    return _dump(rows[:limit])


def _full(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": message["id"],
        "subject": message.get("subject"),
        "author": message.get("author"),
        "recipients": message.get("recipients"),
        "ccList": message.get("ccList"),
        "date": message["date"],
        "tags": message.get("tags", []),
        "body": message.get("body", ""),
        "bodyIsHtml": False,
        "attachments": [],
    }


@server.tool()
def getMessage(messageId: str, folderPath: str, saveAttachments: bool | None = None, bodyFormat: str | None = None, rawSource: bool | None = None) -> str:
    found = next((m for m in DATA["messages"] if m["id"] == messageId and m["folderPath"] == folderPath), None)
    if not found:
        return _dump({"error": "Message not found"})
    return _dump(_full(found))


@server.tool()
def getMessages(
    messages: list[dict[str, Any]], saveAttachments: bool | None = None, bodyFormat: str | None = None, rawSource: bool | None = None
) -> str:
    if not messages:
        return _dump({"error": "messages must be a non-empty array of { messageId, folderPath } objects"})
    if len(messages) > 10:
        return _dump({"error": "getMessages accepts at most 10 messages per call"})
    results = []
    for index, ref in enumerate(messages):
        message_id, folder_path = ref.get("messageId"), ref.get("folderPath")
        found = next((m for m in DATA["messages"] if m["id"] == message_id and m["folderPath"] == folder_path), None)
        if not found:
            results.append({"index": index, "messageId": message_id, "folderPath": folder_path, "error": "Message not found"})
            continue
        results.append({"index": index, "messageId": message_id, "folderPath": folder_path, **_full(found)})
    failed = sum(1 for r in results if r.get("error"))
    return _dump({"messages": results, "requested": len(messages), "succeeded": len(results) - failed, "failed": failed, "max": 10})


@server.tool()
def updateMessage(
    messageId: str | None = None,
    messageIds: list[str] | None = None,
    folderPath: str | None = None,
    read: bool | None = None,
    flagged: bool | None = None,
    addTags: list[str] | None = None,
    removeTags: list[str] | None = None,
) -> str:
    ids = messageIds or ([messageId] if messageId else [])
    if not ids or not folderPath:
        return _dump({"error": "messageId (or messageIds) and folderPath are required"})
    updated = 0
    for message in DATA["messages"]:
        if message["id"] in ids and message["folderPath"] == folderPath:
            if addTags:
                message["tags"] = sorted(set(message.get("tags", [])) | set(addTags))
            if removeTags:
                message["tags"] = [t for t in message.get("tags", []) if t not in removeTags]
            if read is not None:
                message["read"] = read
            if flagged is not None:
                message["flagged"] = flagged
            updated += 1
    UPDATES.append({"ids": ids, "folderPath": folderPath, "addTags": addTags, "removeTags": removeTags, "read": read, "flagged": flagged})
    return _dump({"success": True, "updated": updated})


@server.tool()
def _fakeUpdates() -> str:
    """测试用：返回 updateMessage 被调用的记录。真扩展没有这个工具。"""
    return _dump(UPDATES)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
