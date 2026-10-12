# 各脚本共用的函数。由其他脚本 source，不单独运行。
# shellcheck shell=bash

MCP_NAME="${MCP_NAME:-thunderbird-mail}"
THUNDERBIRD_MCP_DIR="${THUNDERBIRD_MCP_DIR:-$HOME/thunderbird-mcp}"
BRIDGE="$THUNDERBIRD_MCP_DIR/mcp-bridge.cjs"

die() { echo "❌ $*" >&2; exit 1; }

# 找到 node 的绝对路径，存到 NODE_BIN。可以用环境变量 NODE_BIN 指定。
find_node() {
  NODE_BIN="${NODE_BIN:-$(command -v node || true)}"
  if [ -z "$NODE_BIN" ]; then
    die "没找到 Node.js。请到 https://nodejs.org 下载 LTS 安装包安装后重新运行（macOS 用 .pkg）"
  fi
  case "$NODE_BIN" in
    /*) ;;
    *) die "NODE_BIN 需要是绝对路径，现在是：$NODE_BIN" ;;
  esac
  case "$NODE_BIN" in
    *"/.nvm/"*|*"/.fnm/"*|*"/fnm/"*|*"/.volta/"*|*"/.asdf/"*|*"/mise/"*)
      echo "⚠️  node 来自版本管理器：$NODE_BIN"
      echo "    切换 Node 版本后这个路径会失效，Agent 就连不上了。建议用 nodejs.org 的安装包，或用 NODE_BIN 指定一个固定路径。"
      ;;
  esac
}

check_bridge() {
  [ -f "$BRIDGE" ] || die "找不到 $BRIDGE。请先运行 ./scripts/install-thunderbird-mcp.sh"
}

# 备份文件，文件名后加时间戳；同名备份已存在时加序号，不覆盖旧备份
backup() {
  if [ -f "$1" ]; then
    local stamp bak n=1
    stamp="$(date +%Y%m%d-%H%M%S)"
    bak="$1.bak-$stamp"
    while [ -e "$bak" ]; do bak="$1.bak-$stamp-$n"; n=$((n + 1)); done
    cp -p "$1" "$bak"
    echo "🗂  已备份原配置：$bak"
  fi
}
