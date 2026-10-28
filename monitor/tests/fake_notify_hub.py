"""假的 notify-hub 命令：测 notify_hub 推送用，不联网，也不碰你真的 ~/.notify-hub。

只模仿用到的两种调用：notify-hub version、notify-hub send … --body - … -- 标题。
行为由环境变量控制：
- FAKE_NOTIFY_HUB_MODE：ok（默认）| queued（推不出去，存着之后重发，退出码仍是 0）| bad（参数不对，退出码 2）| slow
- FAKE_NOTIFY_HUB_LOG：每次 send 追加一行 JSON（参数、标准输入），给测试检查
"""
import json
import os
import sys
import time


def main() -> int:
    args = sys.argv[1:]
    if args == ["version"]:
        print("notify-hub 0.2.1")
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
        print("❌ 级别只能是 urgent、normal 或 digest", file=sys.stderr)
        return 2
    if mode == "queued":
        print("⏳ 没发出去，留在发件箱里，之后自动重发（#3）：连不上 Lark", file=sys.stderr)
        return 0
    print("✅ 已推送（#1）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
