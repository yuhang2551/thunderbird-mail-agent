#!/usr/bin/env bash
# 下载锁定版本的 thunderbird-mcp，并校验提交哈希和 XPI 的 SHA-256。
# 用法：./scripts/install-thunderbird-mcp.sh
# 可选环境变量：THUNDERBIRD_MCP_DIR（默认 ~/thunderbird-mcp）
#
# 升级到新版本前请先读 docs/security.md 的"更新流程"，审查代码后再改下面三个值。
set -euo pipefail

TBMCP_VERSION="v0.9.2"
TBMCP_COMMIT="1ab10183a7ce914f3964d6c98fcc6265f3dc01d3"
TBMCP_XPI_SHA256="1f014b02c80897d05a44f0edb762c25840f84a6383ca3073549bc7506eab5868"

REPO_URL="https://github.com/TKasperczyk/thunderbird-mcp.git"
TARGET="${THUNDERBIRD_MCP_DIR:-$HOME/thunderbird-mcp}"
XPI="$TARGET/dist/thunderbird-mcp.xpi"

die() { echo "❌ $*" >&2; exit 1; }

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    die "找不到 shasum 或 sha256sum，无法校验文件"
  fi
}

command -v git >/dev/null 2>&1 || die "需要 git。macOS 可以运行 xcode-select --install 安装"

if [ -d "$TARGET/.git" ]; then
  echo "ℹ️  $TARGET 已存在，检查版本……"
elif [ -e "$TARGET" ]; then
  die "$TARGET 已存在但不是 git 仓库。请先移走它，或用 THUNDERBIRD_MCP_DIR 指定别的位置"
else
  echo "⬇️  下载 thunderbird-mcp $TBMCP_VERSION 到 $TARGET ……"
  git -c advice.detachedHead=false clone --quiet --branch "$TBMCP_VERSION" --depth 1 "$REPO_URL" "$TARGET"
fi

HEAD_COMMIT="$(git -C "$TARGET" rev-parse HEAD)"
if [ "$HEAD_COMMIT" != "$TBMCP_COMMIT" ]; then
  echo "⚠️  $TARGET 当前的提交是 $HEAD_COMMIT"
  echo "    不是本仓库审查过的 ${TBMCP_VERSION}（${TBMCP_COMMIT}）。"
  echo "    如果你是有意升级的，请按 docs/security.md 的更新流程审查后，再修改本脚本顶部的版本信息。"
  echo "    如果想回到审查过的版本：git -C \"$TARGET\" fetch --depth 1 origin tag $TBMCP_VERSION && git -C \"$TARGET\" checkout $TBMCP_VERSION"
  exit 2
fi
echo "✅ 提交哈希一致：$TBMCP_VERSION ($TBMCP_COMMIT)"

[ -f "$XPI" ] || die "找不到 $XPI"
ACTUAL_SHA="$(sha256_of "$XPI")"
if [ "$ACTUAL_SHA" != "$TBMCP_XPI_SHA256" ]; then
  echo "❌ XPI 的 SHA-256 不一致，不要安装这个文件！" >&2
  echo "   期望：$TBMCP_XPI_SHA256" >&2
  echo "   实际：$ACTUAL_SHA" >&2
  exit 3
fi
echo "✅ XPI 校验通过：$ACTUAL_SHA"

[ -f "$TARGET/mcp-bridge.cjs" ] || die "找不到 $TARGET/mcp-bridge.cjs"

cat <<EOF

下一步：在 Thunderbird 里安装扩展
  1. 菜单 工具 → 附加组件和主题（英文界面是 Tools → Add-ons and Themes）
  2. 点齿轮图标 → 从文件安装附加组件（Install Add-on From File）
  3. 选择：$XPI
  4. 装好后按 README"第 3 步"调整设置：保持 Block skipReview 开启、关闭删除类工具、关闭自动更新

然后运行接入脚本，例如：./scripts/setup-claude-desktop.sh
EOF
