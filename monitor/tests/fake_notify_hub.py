"""假的 notify-hub 命令：测 notify_hub 推送用，不联网，也不碰你真的 ~/.notify-hub。

只模仿用到的两种调用：notify-hub version、notify-hub send … --body - … -- 标题。
行为由环境变量控制：
- FAKE_NOTIFY_HUB_MODE：ok（默认）| down（重试完还是连不上 Lark，退出码 1）| bad（参数不对，退出码 2）| slow
- FAKE_NOTIFY_HUB_VERSION：notify-hub version 报的版本，默认 0.3.0
- FAKE_NOTIFY_HUB_LOG：每次 send 追加一行 JSON（参数、标准输入），给测试检查
"""
import json
import os
import sys
import time


def main() -> int:
    args = sys.argv[1:]
    if args == ["version"]:
        print(f"notify-hub {os.environ.get('FAKE_NOTIFY_HUB_VERSION', '0.3.0')}")
        return 0
    body = sys.stdin.read()
    log = os.environ.get("FAKE_NOTIFY_HUB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"args": args, "body": body}, ensure_ascii=False) + "\n")
    mode = os.environ.get("FAKE_NOTIFY_HUB_MODE", "ok")
    if mode == "slow":
        time.sleep(10)
    if mode == "bad":
        print("❌ 级别只能是 urgent 或 normal，不是 'loud'", file=sys.stderr)
        return 2
    if mode == "down":
        print("❌ 没发出去：发送消息：连不上 Lark（ConnectError）", file=sys.stderr)
        return 1
    print("✅ 已推送")
    return 0


if __name__ == "__main__":
    sys.exit(main())
