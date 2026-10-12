#!/usr/bin/env bash
# 生成邮件专用工作文件夹（Claude Code / Codex / 手机端 Remote Control 用）。
# 用法：./scripts/create-mail-workspace.sh [目标文件夹]   默认 ~/mail-workspace
# 已有文件不会被覆盖；要用新模板覆盖请加 FORCE=1（会先备份）。upcoming-events.md 是你的数据，任何情况下都不覆盖。
# 可选环境变量：MCP_NAME、NODE_BIN、THUNDERBIRD_MCP_DIR、FORCE
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"
TEMPLATES="$SCRIPT_DIR/../templates/mail-workspace"

find_node
check_bridge

DEST="${1:-$HOME/mail-workspace}"
FORCE="${FORCE:-0}"
mkdir -p "$DEST/.claude"
DEST="$(cd "$DEST" && pwd)"

# 文件不存在或 FORCE=1 时返回 0（可以写）
can_write() {
  if [ -L "$1" ] && [ "$FORCE" = "1" ]; then rm -f "$1"; return 0; fi   # 软链接直接重建，不用备份
  if [ -e "$1" ] || [ -L "$1" ]; then
    if [ "$FORCE" = "1" ]; then backup "$1"; rm -f "$1"; return 0; fi
    echo "⏭  已存在，跳过：$1"
    return 1
  fi
  return 0
}

# 1. 规则文件和活动清单
if can_write "$DEST/CLAUDE.md"; then
  cp "$TEMPLATES/CLAUDE.md" "$DEST/CLAUDE.md"; echo "✅ CLAUDE.md（规则，请填写\"我的邮箱\"一节）"
fi
if [ -e "$DEST/upcoming-events.md" ]; then
  echo "⏭  已存在，保留你的活动清单：$DEST/upcoming-events.md"
else
  cp "$TEMPLATES/upcoming-events.md" "$DEST/upcoming-events.md"; echo "✅ upcoming-events.md（活动清单）"
fi
# Codex 读 AGENTS.md。用软链接指向 CLAUDE.md，两边永远一致；不支持软链接时复制一份。
if can_write "$DEST/AGENTS.md"; then
  if ln -s CLAUDE.md "$DEST/AGENTS.md" 2>/dev/null; then
    echo "✅ AGENTS.md → CLAUDE.md（软链接，给 Codex 用）"
  else
    cp "$DEST/CLAUDE.md" "$DEST/AGENTS.md"
    echo "✅ AGENTS.md（CLAUDE.md 的副本，改规则时两个都要改）"
  fi
fi

# 2. .mcp.json：Claude Code 在这个文件夹里自动加载 thunderbird-mail
if can_write "$DEST/.mcp.json"; then
  OUT="$DEST/.mcp.json" NAME="$MCP_NAME" NODE_CMD="$NODE_BIN" BRIDGE="$BRIDGE" "$NODE_BIN" -e '
const { OUT, NAME, NODE_CMD, BRIDGE } = process.env;
const cfg = { mcpServers: { [NAME]: { command: NODE_CMD, args: [BRIDGE] } } };
require("fs").writeFileSync(OUT, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "✅ .mcp.json（连接方式）"
fi

# 3. .claude/settings.json：启用上面的服务器；只读工具免确认，写入类工具每次仍会询问
if can_write "$DEST/.claude/settings.json"; then
  # shellcheck disable=SC2016  # 单引号里是 JavaScript 模板字符串，不需要 shell 展开
  OUT="$DEST/.claude/settings.json" NAME="$MCP_NAME" "$NODE_BIN" -e '
const { OUT, NAME } = process.env;
const readOnly = ["listAccounts", "getAccountAccess", "listFolders", "getRecentMessages",
  "searchMessages", "getMessage", "getMessages", "searchContacts", "getContact",
  "listCalendars", "listEvents", "listTasks", "listCategories"];
const settings = {
  enabledMcpjsonServers: [NAME],
  permissions: {
    allow: [
      ...readOnly.map((t) => `mcp__${NAME}__${t}`),
      "Read(./upcoming-events.md)",
      "Edit(./upcoming-events.md)",
    ],
  },
};
require("fs").writeFileSync(OUT, JSON.stringify(settings, null, 2) + "\n");
'
  echo "✅ .claude/settings.json（只读工具免确认）"
fi

cat <<EOF

邮件工作文件夹：$DEST
下一步：
  1. 打开 $DEST/CLAUDE.md，填写"我的邮箱"一节（邮箱地址、回复语言、署名）
  2. 在这个文件夹里启动 Agent：
       cd "$DEST" && claude            # Claude Code，第一次会问是否信任这个文件夹和 .mcp.json
       cd "$DEST" && codex             # Codex（需要先运行 ./scripts/setup-codex.sh）
  3. 想在手机上用：见 docs/mobile.md
EOF
