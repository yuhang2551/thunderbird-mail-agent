#!/usr/bin/env bash
# 把 mail-monitor 装成 macOS 的定时任务（launchd）：每 5 分钟 run 一次，早 9 点和晚 6 点各 digest 一次。
# 用法：./scripts/launchd.sh install | uninstall | status
# 可选环境变量：MAIL_MONITOR_BIN（默认 monitor/.venv/bin/mail-monitor）、RUN_INTERVAL（秒，默认 300）、
#              DIGEST_HOURS（默认 "9 18"）、MAIL_MONITOR_HOME（默认 ~/.mail-monitor）
# 电脑睡眠时任务不跑，醒来后 launchd 会补跑一次，所以不会漏邮件。
set -euo pipefail

MONITOR_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${MAIL_MONITOR_BIN:-$MONITOR_DIR/.venv/bin/mail-monitor}"
HOME_DIR="${MAIL_MONITOR_HOME:-$HOME/.mail-monitor}"
LOG_DIR="$HOME_DIR/logs"
AGENTS="$HOME/Library/LaunchAgents"
PREFIX="com.thunderbird-mail-agent.mail-monitor"
RUN_INTERVAL="${RUN_INTERVAL:-300}"
DIGEST_HOURS="${DIGEST_HOURS:-9 18}"
NODE_DIR="$(dirname "$(command -v node 2>/dev/null || echo /usr/local/bin/node)")"
# Claude 订阅版（MAIL_MONITOR_LLM=claude）要调用 claude；官方安装器默认装在 ~/.local/bin
CLAUDE_DIR="$(dirname "$(command -v claude 2>/dev/null || echo "$HOME/.local/bin/claude")")"
DOMAIN="gui/$(id -u)"

die() { echo "❌ $*" >&2; exit 1; }
[ "$(uname)" = "Darwin" ] || die "launchd 只有 macOS 有。Linux 请用 cron，README 里有例子"

# 每个任务共用的环境：PATH 里要有 node（bridge 用）和 claude（Claude 订阅版用），配置文件固定指向 HOME_DIR/.env
env_xml() {
  cat <<XML
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$NODE_DIR:$CLAUDE_DIR:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
    <key>PYTHONUTF8</key><string>1</string>
    <key>MAIL_MONITOR_ENV</key><string>$HOME_DIR/.env</string>
  </dict>
XML
}

plist_head() {
  cat <<XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key>
  <array><string>$BIN</string><string>$2</string></array>
  <key>StandardOutPath</key><string>$LOG_DIR/$2.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/$2.log</string>
  <key>ProcessType</key><string>Background</string>
  <key>RunAtLoad</key><false/>
XML
  env_xml
}

run_plist() {
  plist_head "$PREFIX.run" run
  cat <<XML
  <key>StartInterval</key><integer>$RUN_INTERVAL</integer>
</dict>
</plist>
XML
}

digest_plist() {
  plist_head "$PREFIX.digest" digest
  echo "  <key>StartCalendarInterval</key>"
  echo "  <array>"
  for hour in $DIGEST_HOURS; do
    echo "    <dict><key>Hour</key><integer>$hour</integer><key>Minute</key><integer>0</integer></dict>"
  done
  echo "  </array>"
  echo "</dict>"
  echo "</plist>"
}

unload() {  # 没装过也不报错
  launchctl bootout "$DOMAIN/$1" >/dev/null 2>&1 || launchctl unload "$AGENTS/$1.plist" >/dev/null 2>&1 || true
}

load() {
  launchctl bootstrap "$DOMAIN" "$AGENTS/$1.plist" 2>/dev/null || launchctl load -w "$AGENTS/$1.plist"
}

install() {
  [ -x "$BIN" ] || die "找不到 ${BIN}。先运行 ./scripts/install.sh（或把 MAIL_MONITOR_BIN 指向 mail-monitor）"
  [ -f "$HOME_DIR/.env" ] || die "没有 $HOME_DIR/.env。先按 README 配置好，并跑通 mail-monitor doctor"
  mkdir -p "$AGENTS" "$LOG_DIR"
  run_plist > "$AGENTS/$PREFIX.run.plist"
  digest_plist > "$AGENTS/$PREFIX.digest.plist"
  plutil -lint -s "$AGENTS/$PREFIX.run.plist" "$AGENTS/$PREFIX.digest.plist" || die "生成的 plist 不合法"
  for label in "$PREFIX.run" "$PREFIX.digest"; do
    unload "$label"
    load "$label"
  done
  echo "✅ 已安装：每 $RUN_INTERVAL 秒巡检一次（$PREFIX.run），每天 $(echo "$DIGEST_HOURS" | sed 's/ /、/g') 点汇总（$PREFIX.digest）"
  echo "   日志：$LOG_DIR/run.log 和 digest.log"
  echo "   提醒：第一次先手动跑 mail-monitor init，不然会把现有邮件全推一遍"
}

uninstall() {
  for label in "$PREFIX.run" "$PREFIX.digest"; do
    unload "$label"
    rm -f "$AGENTS/$label.plist"
  done
  echo "✅ 已卸载定时任务（配置和数据库 $HOME_DIR 保留）"
}

status() {
  for label in "$PREFIX.run" "$PREFIX.digest"; do
    if [ -f "$AGENTS/$label.plist" ]; then
      line="$(launchctl list 2>/dev/null | awk -v l="$label" '$3 == l {print "pid=" $1 " 上次退出码=" $2}')"
      echo "✅ ${label}：已安装${line:+（${line}）}"
    else
      echo "⏹  ${label}：未安装"
    fi
  done
  for name in run digest; do
    if [ -f "$LOG_DIR/$name.log" ]; then
      echo "—— $LOG_DIR/$name.log 最后 5 行 ——"
      tail -n 5 "$LOG_DIR/$name.log"
    fi
  done
}

case "${1:-}" in
  install) install ;;
  uninstall) uninstall ;;
  status) status ;;
  *) echo "用法：$0 install | uninstall | status"; exit 1 ;;
esac
