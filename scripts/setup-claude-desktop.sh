#!/usr/bin/env bash
# 把 thunderbird-mail 写进 Claude Desktop 的 MCP 配置。会先备份原配置，可以重复运行。
# 可选环境变量：MCP_NAME（默认 thunderbird-mail）、NODE_BIN、THUNDERBIRD_MCP_DIR、CLAUDE_DESKTOP_CONFIG
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

find_node
check_bridge

case "$(uname -s)" in
  Darwin) DEFAULT_CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json" ;;
  Linux)  DEFAULT_CFG="${XDG_CONFIG_HOME:-$HOME/.config}/Claude/claude_desktop_config.json" ;;
  *)
    cat <<EOF
这个系统（$(uname -s)）请手动配置：
  1. 打开 Claude Desktop → 设置 → 开发者 → 编辑配置（Windows 上通常是 %APPDATA%\\Claude\\claude_desktop_config.json）
  2. 在 "mcpServers" 里加入（路径换成你自己的，反斜杠要写两个）：
     "$MCP_NAME": { "command": "C:\\\\Program Files\\\\nodejs\\\\node.exe",
                    "args": ["C:\\\\Users\\\\你的用户名\\\\thunderbird-mcp\\\\mcp-bridge.cjs"] }
  3. 彻底退出 Claude 再打开
详见 docs/agents.md
EOF
    exit 0 ;;
esac
CFG="${CLAUDE_DESKTOP_CONFIG:-$DEFAULT_CFG}"

mkdir -p "$(dirname "$CFG")"

# shellcheck disable=SC2016  # 单引号里是 JavaScript，不需要 shell 展开
CFG="$CFG" NAME="$MCP_NAME" NODE_CMD="$NODE_BIN" BRIDGE="$BRIDGE" "$NODE_BIN" -e '
const fs = require("fs");
const { CFG, NAME, NODE_CMD, BRIDGE } = process.env;
let cfg = {};
if (fs.existsSync(CFG)) {
  const raw = fs.readFileSync(CFG, "utf8");
  if (raw.trim()) {
    try { cfg = JSON.parse(raw); }
    catch (e) { console.error("❌ 现有配置不是合法的 JSON，没有改动：" + e.message); process.exit(1); }
  }
}
if (typeof cfg !== "object" || cfg === null || Array.isArray(cfg)) {
  console.error("❌ 现有配置的格式不对（顶层应该是一个对象），没有改动"); process.exit(1);
}
cfg.mcpServers = cfg.mcpServers || {};
const entry = { command: NODE_CMD, args: [BRIDGE] };
const old = cfg.mcpServers[NAME];
if (old && JSON.stringify(old) === JSON.stringify(entry)) {
  console.log("ℹ️  配置里已经有 " + NAME + "，内容一样，不需要改");
  process.exit(0);
}
if (fs.existsSync(CFG)) {
  // 只有真的要改时才备份；同名备份已存在时加序号
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
  let bak = `${CFG}.bak-${stamp}`;
  for (let i = 1; fs.existsSync(bak); i++) bak = `${CFG}.bak-${stamp}-${i}`;
  fs.copyFileSync(CFG, bak);
  console.log("🗂  已备份原配置：" + bak);
}
if (old) console.log("ℹ️  更新已有的 " + NAME + " 配置");
cfg.mcpServers[NAME] = entry;
fs.writeFileSync(CFG, JSON.stringify(cfg, null, 2) + "\n");
console.log("✅ 已写入 Claude Desktop 配置：" + CFG);
'

echo "   node：$NODE_BIN"
echo "   bridge：$BRIDGE"
echo
echo "下一步：彻底退出 Claude（macOS 按 ⌘Q，不是关窗口）再打开，然后在对话里说\"列出我的邮箱账户\"试试。"
