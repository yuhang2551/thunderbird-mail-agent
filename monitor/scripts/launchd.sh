#!/usr/bin/env bash
# 把 mail-monitor 装成 macOS 的定时任务（launchd）：每小时 run 一次，早 9 点和晚 6 点各 digest 一次。
# 用法：./scripts/launchd.sh install | uninstall | status | print（只打印要装的 plist，不安装）
# 可选环境变量：MAIL_MONITOR_BIN（默认 monitor/.venv/bin/mail-monitor）、RUN_INTERVAL（秒，默认 3600）、
#              DIGEST_HOURS（默认 "9 18"）、MAIL_MONITOR_HOME（默认 ~/.mail-monitor）
# 电脑睡眠时任务不跑，醒来后 launchd 会补跑一次；装上和开机登录时 run 也先跑一次，所以不会漏邮件。
set -euo pipefail

MONITOR_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${MAIL_MONITOR_BIN:-$MONITOR_DIR/.venv/bin/mail-monitor}"
HOME_DIR="${MAIL_MONITOR_HOME:-$HOME/.mail-monitor}"
LOG_DIR="$HOME_DIR/logs"
AGENTS="$HOME/Library/LaunchAgents"
PREFIX="com.thunderbird-mail-agent.mail-monitor"
RUN_INTERVAL="${RUN_INTERVAL:-3600}"
DIGEST_HOURS="${DIGEST_HOURS:-9 18}"
NODE_DIR="$(dirname "$(command -v node 2>/dev/null || echo /usr/local/bin/node)")"
# Claude 订阅版（MAIL_MONITOR_LLM=claude）要调用 claude；官方安装器默认装在 ~/.local/bin
CLAUDE_DIR="$(dirname "$(command -v claude 2>/dev/null || echo "$HOME/.local/bin/claude")")"
DOMAIN="gui/$(id -u)"

die() { echo "❌ $*" >&2; exit 1; }
need_macos() { [ "$(uname)" = "Darwin" ] || die "launchd 只有 macOS 有。Linux 请用 cron，README 里有例子"; }
case "$RUN_INTERVAL" in
  ''|*[!0-9]*|0) die "RUN_INTERVAL 要写成秒数，比如 3600（每小时）、1800（每 30 分钟）" ;;
esac

every() {  # 3600 → 每小时，7200 → 每 2 小时，1800 → 每 30 分钟，90 → 每 90 秒
  if [ "$1" -eq 3600 ]; then
    echo "每小时"
  elif [ $(( $1 % 3600 )) -eq 0 ]; then
    echo "每 $(( $1 / 3600 )) 小时"
  elif [ $(( $1 % 60 )) -eq 0 ]; then
    echo "每 $(( $1 / 60 )) 分钟"
  else
    echo "每 $1 秒"
  fi
}

# 每个任务共用的环境：PATH 里要有 node（bridge 用）、claude（Claude 订阅版用）和 notify-hub（notify_hub 推送用），
# 后两个的官方装法都装在 ~/.local/bin；配置文件固定指向 HOME_DIR/.env
env_xml() {
  cat <<XML
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$NODE_DIR:$CLAUDE_DIR:$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
    <key>PYTHONUTF8</key><string>1</string>
    <key>MAIL_MONITOR_ENV</key><string>$HOME_DIR/.env</string>
  </dict>
XML
}

plist_head() {  # $1 = Label，$2 = 子命令，$3 = 装上和开机登录时先跑一次（true / false）
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
  <key>RunAtLoad</key><$3/>
XML
  env_xml
}

run_plist() {
  # 间隔是一小时的话，开机后要等一小时才第一次巡检，所以装上和开机登录时先跑一次
  plist_head "$PREFIX.run" run true
  cat <<XML
  <key>StartInterval</key><integer>$RUN_INTERVAL</integer>
</dict>
</plist>
XML
}

digest_plist() {
  plist_head "$PREFIX.digest" digest false
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

seen_count() {  # 数据库里登记过几封邮件（init 或正式巡检过才有）；看不了时输出 ?
  [ -f "$HOME_DIR/state.db" ] || { echo 0; return; }
  command -v sqlite3 >/dev/null 2>&1 || { echo "?"; return; }
  sqlite3 "$HOME_DIR/state.db" "SELECT COUNT(*) FROM messages" 2>/dev/null || echo "?"
}

install() {
  need_macos
  [ -x "$BIN" ] || die "找不到 ${BIN}。先运行 ./scripts/install.sh（或把 MAIL_MONITOR_BIN 指向 mail-monitor）"
  [ -f "$HOME_DIR/.env" ] || die "没有 $HOME_DIR/.env。先按 README 配置好，并跑通 mail-monitor doctor"
  # 装上就会先巡检一次，没 init 的话会把最近两天的邮件全当成新邮件推一遍
  [ "$(seen_count)" != 0 ] || die "还没跑过 mail-monitor init：先跑它把现有邮件登记为已见，再装定时任务"
  mkdir -p "$AGENTS" "$LOG_DIR"
  run_plist > "$AGENTS/$PREFIX.run.plist"
  digest_plist > "$AGENTS/$PREFIX.digest.plist"
  plutil -lint -s "$AGENTS/$PREFIX.run.plist" "$AGENTS/$PREFIX.digest.plist" || die "生成的 plist 不合法"
  for label in "$PREFIX.run" "$PREFIX.digest"; do
    unload "$label"
    load "$label"
  done
  echo "✅ 已安装：$(every "$RUN_INTERVAL")巡检一次，刚装上先跑一次（${PREFIX}.run）；每天 $(echo "$DIGEST_HOURS" | sed 's/ /、/g') 点汇总（${PREFIX}.digest）"
  echo "   日志：$LOG_DIR/run.log 和 digest.log；过一会儿用 ./scripts/launchd.sh status 看结果"
}

uninstall() {
  need_macos
  for label in "$PREFIX.run" "$PREFIX.digest"; do
    unload "$label"
    rm -f "$AGENTS/$label.plist"
  done
  echo "✅ 已卸载定时任务（配置和数据库 $HOME_DIR 保留）"
}

status() {
  need_macos
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
  print) run_plist; digest_plist ;;
  *) echo "用法：$0 install | uninstall | status | print"; exit 1 ;;
esac
