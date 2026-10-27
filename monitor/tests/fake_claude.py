"""假的 claude 命令：测 Claude 订阅版后端用，不需要真账号，也不联网。

只模仿后端用到的三种调用：claude --version、claude auth status、claude -p … --output-format json。
行为由环境变量控制：
- FAKE_CLAUDE_MODE：ok（默认）| fenced | not_logged_in | usage_limit | garbage | unknown_option | slow
- FAKE_CLAUDE_AUTH：claude.ai（默认）| oauth_token | api_key | logged_out
- FAKE_CLAUDE_VERSION：默认 2.1.311
- FAKE_CLAUDE_LOG：每次 -p 调用追加一行 JSON（参数、工作目录、标准输入、提示词文件、有没有带 API key），给测试检查
"""
import json
import os
import sys
import time


def verdict_for(mail: str) -> dict:
    wanted = "Interview" in mail or "DoAtlas" in mail
    return {
        "who": "测试发件人",
        "relation": "",
        "what": "假模型的摘要",
        "needs_action": "yes" if wanted else "no",
        "urgency": "high" if wanted else "low",
        "deadline": None,
        "suggested_action": "回复确认" if wanted else "",
        "category": "其他",
        "confidence": 0.8,
    }


def result(text: str, *, error: bool = False) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": error,
            "result": text,
            "duration_ms": 1200,
            "usage": {"input_tokens": 900, "output_tokens": 120},
            "session_id": "fake-session",
        },
        ensure_ascii=False,
    )


def main() -> int:
    args = sys.argv[1:]
    if args == ["--version"]:
        print(f"{os.environ.get('FAKE_CLAUDE_VERSION', '2.1.311')} (Claude Code)")
        return 0
    if args[:2] == ["auth", "status"]:
        auth = os.environ.get("FAKE_CLAUDE_AUTH", "claude.ai")
        if auth == "logged_out":
            print(json.dumps({"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"}))
            return 1
        status = {"loggedIn": True, "authMethod": auth, "apiProvider": "firstParty"}
        if auth == "claude.ai":
            status["subscriptionType"] = "max"
        print(json.dumps(status))
        return 0

    mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
    if mode == "unknown_option":
        print("error: unknown option '--safe-mode'", file=sys.stderr)
        return 1
    prompt_file = args[args.index("--system-prompt-file") + 1]
    with open(prompt_file, encoding="utf-8") as fh:
        system = fh.read()
    mail = sys.stdin.read()
    log = os.environ.get("FAKE_CLAUDE_LOG")
    if log:
        call = {"argv": args, "cwd": os.getcwd(), "stdin": mail, "system": system, "prompt_file": prompt_file,
                "api_key": os.environ.get("ANTHROPIC_API_KEY")}
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(call, ensure_ascii=False) + "\n")

    if mode == "slow":
        time.sleep(10)
    if mode == "not_logged_in":
        print(result("Not logged in · Please run /login", error=True))
        return 1
    if mode == "usage_limit":
        print(result("You've hit your limit · resets 3pm (Asia/Dubai)", error=True))
        return 1
    if mode == "garbage":
        print(result("抱歉，我没法按要求回答。"))
        return 0
    text = json.dumps(verdict_for(mail), ensure_ascii=False)
    print(result(f"```json\n{text}\n```" if mode == "fenced" else text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
