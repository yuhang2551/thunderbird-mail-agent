#!/usr/bin/env bash
# 自检：Node、扩展文件、Thunderbird 连接是否正常。不修改任何东西。
# 用法：./scripts/doctor.sh
set -uo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

ok=1
NODE_BIN="${NODE_BIN:-$(command -v node || true)}"
if [ -n "$NODE_BIN" ]; then
  echo "✅ Node.js：${NODE_BIN}（$("$NODE_BIN" -v)）"
else
  echo "❌ 没找到 Node.js"; exit 1
fi

if [ -f "$BRIDGE" ]; then
  echo "✅ 转接程序：$BRIDGE"
else
  echo "❌ 找不到 ${BRIDGE}，请先运行 ./scripts/install-thunderbird-mcp.sh"; exit 1
fi

if [ -d "$THUNDERBIRD_MCP_DIR/.git" ]; then
  echo "ℹ️  thunderbird-mcp 版本：$(git -C "$THUNDERBIRD_MCP_DIR" describe --tags --always 2>/dev/null)"
fi

# 模拟一个 MCP 客户端：初始化 + 列出工具
RESULT="$(printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"doctor","version":"0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | "$NODE_BIN" "$BRIDGE" 2>&1 | tail -n 1)"

SUMMARY="$(printf '%s' "$RESULT" | "$NODE_BIN" -e '
let s = ""; process.stdin.on("data", (d) => (s += d)).on("end", () => {
  try {
    const r = JSON.parse(s);
    if (r.result && Array.isArray(r.result.tools)) {
      const names = r.result.tools.map((t) => t.name);
      const del = names.filter((n) => /^(delete|empty)/.test(n));
      console.log("OK " + names.length + " " + (del.join(",") || "-"));
    } else {
      console.log("ERR " + ((r.error && r.error.message) || s).slice(0, 300));
    }
  } catch (e) { console.log("ERR " + s.slice(0, 300)); }
});')"

case "$SUMMARY" in
  OK*)
    read -r _ TOOL_COUNT DELETE_TOOLS <<<"$SUMMARY"
    echo "✅ 已连上 Thunderbird，扩展提供 $TOOL_COUNT 个工具"
    if [ "$DELETE_TOOLS" != "-" ]; then
      echo "⚠️  这些删除类工具还开着：$DELETE_TOOLS"
      echo "    建议在扩展设置的 Tool Access 里关掉（见 README 第 3 步）"
      ok=2
    else
      echo "✅ 删除类工具已关闭"
    fi ;;
  *)
    ok=0
    echo "❌ 连不上 Thunderbird：${SUMMARY#ERR }"
    echo "   请确认：Thunderbird 已打开；扩展已安装并启用；扩展安装后 Thunderbird 重启过一次。" ;;
esac

echo
case "$ok" in
  1) echo "一切正常。" ;;
  2) echo "连接正常，但上面有一条安全建议还没做。" ;;
  *) exit 1 ;;
esac
