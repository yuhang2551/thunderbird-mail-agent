"""邮箱监控 Agent（mail-monitor）。

流程：拉新邮件 → 去重 → 规则层 → LLM 判断 → （可选）打标签 → 推送。
邮件层是 thunderbird-mcp 扩展 + mcp-bridge.cjs，本包只是它的一个 MCP 客户端。
"""

__version__ = "0.1.0"
