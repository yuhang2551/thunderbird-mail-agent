#!/usr/bin/env bash
# 用 claude mcp add 把 thunderbird-mail 加到 Claude Code（用户级，所有项目可用）。
# 只想在邮件工作文件夹里用的话，可以不运行这个，create-mail-workspace.sh 生成的 .mcp.json 已经够了。
# 可选环境变量：MCP_NAME、NODE_BIN、THUNDERBIRD_MCP_DIR
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

find_node
check_bridge
command -v claude >/dev/null 2>&1 || die "没找到 claude 命令。安装方法见 https://code.claude.com/docs"

if claude mcp get "$MCP_NAME" >/dev/null 2>&1; then
  echo "ℹ️  Claude Code 里已经有名为 $MCP_NAME 的 MCP 服务器："
  claude mcp get "$MCP_NAME" || true
  echo
  echo "要重新配置，先运行：claude mcp remove --scope user $MCP_NAME"
  exit 0
fi

claude mcp add --scope user "$MCP_NAME" -- "$NODE_BIN" "$BRIDGE"
echo "✅ 已添加。新开一个 claude 会话，输入 /mcp 可以看到 $MCP_NAME 的连接状态。"
