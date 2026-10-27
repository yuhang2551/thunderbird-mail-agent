"""模拟 Thunderbird 没开时的 mcp-bridge.cjs：握手照常成功，之后每个请求都回 JSON-RPC 错误。

照抄上游 v0.9.2 的行为：bridge 在本地处理 initialize（所以 Thunderbird 没开也能握手），
tools/list、tools/call 要转给 Thunderbird，找不到连接文件时回 {"error": {"code": -32700, "message": "Bridge error: ..."}}，
而不是工具报错（isError）。
"""
from __future__ import annotations

import json
import sys

MESSAGE = (
    "Bridge error: Connection discovery failed. Tried: macOS temp scan (/tmp/thunderbird-mcp): not found. "
    "Is Thunderbird running with the MCP extension?"
)


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        if "id" not in message or str(message.get("method", "")).startswith("notifications/"):
            continue
        if message.get("method") == "initialize":
            reply = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "protocolVersion": message["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "thunderbird-mcp", "version": "0.9.2"},
                },
            }
        else:
            reply = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32700, "message": MESSAGE}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
