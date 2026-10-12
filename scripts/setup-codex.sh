#!/usr/bin/env bash
# 把 thunderbird-mail 写进 Codex 的配置（~/.codex/config.toml，CLI 和 IDE 插件共用）。
# 已存在同名配置时不改动；写入前先备份。
# 可选环境变量：MCP_NAME、NODE_BIN、THUNDERBIRD_MCP_DIR、CODEX_HOME
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

find_node
check_bridge

case "$MCP_NAME" in
  *[!A-Za-z0-9_-]*|"") die "MCP_NAME 只能包含字母、数字、下划线和连字符" ;;
esac

CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
CFG="$CODEX_DIR/config.toml"
mkdir -p "$CODEX_DIR"

if [ -f "$CFG" ] && grep -Eq "^[[:space:]]*\[mcp_servers\.(\"$MCP_NAME\"|$MCP_NAME)\][[:space:]]*$" "$CFG"; then
  echo "ℹ️  $CFG 里已经有 [mcp_servers.$MCP_NAME]，没有改动。需要修改的话请手动编辑这个文件。"
  exit 0
fi

# TOML 基本字符串：转义反斜杠和双引号
toml_str() { local s="${1//\\/\\\\}"; s="${s//\"/\\\"}"; printf '"%s"' "$s"; }

# 文件已有内容且不以换行结尾时，先补一个换行
NEEDS_NEWLINE=0
if [ -s "$CFG" ] && [ -n "$(tail -c 1 "$CFG")" ]; then NEEDS_NEWLINE=1; fi

backup "$CFG"
{
  if [ "$NEEDS_NEWLINE" = 1 ]; then echo; fi
  echo
  echo "[mcp_servers.$MCP_NAME]"
  echo "command = $(toml_str "$NODE_BIN")"
  echo "args = [$(toml_str "$BRIDGE")]"
} >> "$CFG"

echo "✅ 已写入 $CFG"
echo "   重新启动 Codex（CLI 新开会话，IDE 插件重载窗口）。运行 codex mcp list 可以确认 $MCP_NAME 已加载。"
