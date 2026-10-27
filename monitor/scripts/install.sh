#!/usr/bin/env bash
# 准备 mail-monitor：建 .venv、装依赖、生成 ~/.mail-monitor/.env 和 rules.yaml（已有的不覆盖）。
# 用法：./scripts/install.sh
# 可选环境变量：PYTHON（不填就自动找 3.10 以上的 python3 或 python3.1x）、MAIL_MONITOR_HOME（默认 ~/.mail-monitor）
set -euo pipefail

MONITOR_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="${MAIL_MONITOR_HOME:-$HOME/.mail-monitor}"
# 提示文字里变量紧跟中文时一律写成 ${变量}：macOS 自带的 bash 3.2 会把中文的第一个字节当成变量名的一部分

die() { echo "❌ $*" >&2; exit 1; }
new_enough() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; }

# 没指定 PYTHON 时先看 python3；macOS 自带的常常是 3.9，就接着找装过的新版本
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  PY=python3
  for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1 && new_enough "$candidate"; then
      PY="$candidate"
      break
    fi
  done
fi
HOW="可以到 https://www.python.org/downloads/macos/ 下载 Python 3.13 安装包，或者 brew install python@3.13，装好后重新运行 ./scripts/install.sh（其他装法见 docs/faq.md）"
command -v "$PY" >/dev/null 2>&1 || die "没找到 ${PY}。需要 Python 3.10 或更新，${HOW}"
new_enough "$PY" || die "需要 Python 3.10 或更新，现在是 $("$PY" --version 2>&1)。${HOW}"
echo "✅ Python：$("$PY" --version 2>&1)（$(command -v "$PY")）"

cd "$MONITOR_DIR"
if [ ! -x .venv/bin/python ]; then
  echo "📦 创建虚拟环境 $MONITOR_DIR/.venv ……"
  "$PY" -m venv .venv
fi
echo "📦 安装依赖……"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e ".[dev]"
echo "✅ 已安装：$(.venv/bin/mail-monitor version)"

mkdir -p "$HOME_DIR"
if [ -e "$HOME_DIR/.env" ]; then
  echo "⏭  已存在，保留：$HOME_DIR/.env"
else
  cp .env.example "$HOME_DIR/.env"; chmod 600 "$HOME_DIR/.env"
  echo "✅ 生成 $HOME_DIR/.env（请选模型：填 DEEPSEEK_API_KEY，或设 MAIL_MONITOR_LLM=claude 用 Claude 订阅；再填推送配置）"
fi
if [ -e "$HOME_DIR/rules.yaml" ]; then
  echo "⏭  已存在，保留：$HOME_DIR/rules.yaml"
else
  cp rules.example.yaml "$HOME_DIR/rules.yaml"
  echo "✅ 生成 $HOME_DIR/rules.yaml（按自己的情况改规则）"
fi

cat <<MSG

下一步：
  1. 编辑 $HOME_DIR/.env
  2. $MONITOR_DIR/.venv/bin/mail-monitor doctor        # 自检
  3. $MONITOR_DIR/.venv/bin/mail-monitor run --dry-run # 看看它会怎么判断，不记录、不推送
  4. $MONITOR_DIR/.venv/bin/mail-monitor init          # 把现有邮件登记为已见
  5. ./scripts/launchd.sh install                      # 装成定时任务（macOS）
MSG
