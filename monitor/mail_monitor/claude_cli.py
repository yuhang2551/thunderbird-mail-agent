"""Claude 订阅版后端：调用你电脑上已经登录的官方 claude 命令（Claude Code 的非交互模式 claude -p）。

只给自己用：程序不读、不存任何 Claude 的登录凭证，只是像你在终端里一样运行 claude，用量算在你的 Pro / Max 订阅里。
每封邮件单独调用一次，和 API 版一样"提示词进、JSON 出"，判断层不用区分后端。
邮件从标准输入传，不出现在命令行参数里；工具、MCP、hooks、CLAUDE.md 全部关掉，读邮件的这个 Claude 只能回答，什么也做不了。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .llm import LLMError, parse_json_object

log = logging.getLogger(__name__)

# --permission-prompts 从 v2.1.259 开始才有，更老的版本会报"不认识的参数"
MIN_VERSION = (2, 1, 259)

# 这两个变量会让 claude 改用 API key 或网关按量计费，而不是你的订阅，所以调用时去掉
BILLING_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

_UNKNOWN_OPTION = re.compile(r"unknown option|unrecognized option|unknown argument", re.IGNORECASE)
_LOGIN = re.compile(r"not logged in|/login|invalid api key|authentication|oauth token", re.IGNORECASE)
_LIMIT = re.compile(r"usage limit|limit reached|hit your [a-z -]*limit|rate limit|resets? (?:at )?\d", re.IGNORECASE)


class ClaudeCLIError(LLMError):
    """retryable=False：没登录、额度用完、找不到命令、版本太旧、超时。这类错误重试也没用，这一轮剩下的邮件直接走保底。"""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def resolve_binary(binary: str) -> str:
    """PATH 里找不到 claude 时，退回官方安装脚本的位置 ~/.local/bin/claude（刚装完的终端窗口、launchd 里常见）。"""
    if os.sep not in binary and shutil.which(binary) is None:
        native = Path.home() / ".local" / "bin" / "claude"
        if native.exists():
            return str(native)
    return binary


def claude_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in BILLING_ENV:
        env.pop(name, None)
    return env


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def _fmt(version: tuple[int, int, int]) -> str:
    return ".".join(map(str, version))


def _last_json_object(text: str) -> dict[str, Any] | None:
    """--output-format json 只输出一个 JSON 对象；万一前面混了别的行，取最后一个能解析的对象。"""
    candidates = [text.strip()] + [line.strip() for line in reversed(text.splitlines())]
    for candidate in candidates:
        if not candidate.startswith("{"):
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _failure(message: str) -> ClaudeCLIError:
    detail = " ".join(message.split())[:200]
    if _LIMIT.search(message):
        return ClaudeCLIError(f"Claude 订阅额度暂时用完了（{detail}），额度恢复前的邮件按「拿不准」推送", retryable=False)
    if _LOGIN.search(message):
        return ClaudeCLIError(f"claude 没有登录或登录失效（{detail}）：在终端运行 claude，输入 /login 用 Claude 账号登录", retryable=False)
    return ClaudeCLIError(f"claude 返回错误：{detail}")


class ClaudeCLIClient:
    def __init__(self, *, binary: str = "claude", model: str = "sonnet", timeout: float = 180.0, workdir: Path):
        self.binary = resolve_binary(binary)
        self.model = model
        self.timeout = timeout
        self.workdir = workdir  # 一个固定的空目录：claude -p 会执行当前目录项目里的 hooks、连 .mcp.json 里的服务器
        self._fatal: str | None = None  # 出过一次重试也没用的错误，这一轮剩下的邮件就不再启动 claude

    def command(self, system_prompt_file: Path) -> list[str]:
        return [
            self.binary,
            "-p",
            "--safe-mode",  # 不加载 CLAUDE.md、hooks、插件、技能、MCP 服务器
            "--tools", "",  # 一个工具都不给
            "--strict-mcp-config",  # 只用 --mcp-config 给的 MCP 服务器，这里一个没给
            "--permission-prompts", "none",  # 没人在电脑前点"允许"，有权限请求直接拒绝
            "--no-session-persistence",  # 会话不存进 ~/.claude/projects，那里会明文留下邮件内容
            "--model", self.model,
            "--effort", "low",  # 分诊用不着长推理，省时间也省额度
            "--system-prompt-file", str(system_prompt_file),  # 整个替换掉编程助手的默认提示词
            "--output-format", "json",
        ]

    async def chat_json(self, system: str, user: str, **_: Any) -> dict[str, Any]:
        if self._fatal:
            raise ClaudeCLIError(self._fatal, retryable=False)
        try:
            return await self._ask(system, user)
        except ClaudeCLIError as exc:
            if not exc.retryable:
                self._fatal = str(exc)
            raise

    async def _ask(self, system: str, user: str) -> dict[str, Any]:
        self.workdir.mkdir(parents=True, exist_ok=True)
        # 提示词写进系统临时目录里的一个文件（权限 600），用完就删
        fd, prompt_path = tempfile.mkstemp(prefix="mail-monitor-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(system)
            stdout, stderr, code = await self._run(self.command(Path(prompt_path)), user)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(prompt_path)
        return self._parse(stdout, stderr, code)

    async def _run(self, cmd: list[str], stdin: str) -> tuple[str, str, int]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.workdir,
                env=claude_env(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:  # 找不到命令、没有执行权限
            raise ClaudeCLIError(
                f"运行不了 {self.binary}（{exc}）：先装好 Claude Code 并登录，或者把 MAIL_MONITOR_CLAUDE_BIN 设成 claude 的完整路径",
                retryable=False,
            ) from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin.encode("utf-8")), self.timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            # 卡住一次，多半下一次也会卡（比如断网），这一轮就不再等了
            raise ClaudeCLIError(f"claude 超过 {self.timeout:g} 秒没有返回", retryable=False) from None
        return out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), proc.returncode or 0

    def _parse(self, stdout: str, stderr: str, code: int) -> dict[str, Any]:
        data = _last_json_object(stdout)
        if data is None:
            detail = " ".join((stderr or stdout).split())[:300] or f"退出码 {code}"
            if _UNKNOWN_OPTION.search(stderr):
                raise ClaudeCLIError(
                    f"这个版本的 claude 不认识要用的参数（{detail}）：运行 claude update 升级到 {_fmt(MIN_VERSION)} 以上", retryable=False
                )
            raise _failure(detail) if code else ClaudeCLIError(f"claude 没有返回结果：{detail}")
        result = str(data.get("result") or "")
        if data.get("is_error") or data.get("subtype", "success") != "success" or code:
            raise _failure(result or stderr or f"退出码 {code}")
        usage = data.get("usage") or {}
        log.debug(
            "claude 用时 %s ms，输入 %s token，输出 %s token",
            data.get("duration_ms"),
            usage.get("input_tokens"),
            usage.get("output_tokens"),
        )
        return parse_json_object(result)


def doctor_lines(binary: str, model: str) -> tuple[bool, list[str]]:
    """给 mail-monitor doctor 用：查 claude 装没装、版本够不够、是不是用订阅登录的。不调用模型，不花额度。"""
    lines: list[str] = []
    binary = resolve_binary(binary)

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([binary, *args], capture_output=True, text=True, timeout=60, env=claude_env())

    try:
        version_out = run("--version")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, [
            f"❌ 模型：Claude 订阅版，但运行不了 {binary}（{exc}）",
            "   先装 Claude Code 命令行版：curl -fsSL https://claude.ai/install.sh | bash，再运行 ~/.local/bin/claude auth login 用 Claude 账号登录",
            "   装在别处的话，把 claude 的完整路径写进 MAIL_MONITOR_CLAUDE_BIN",
        ]
    ok = True
    version = parse_version(version_out.stdout)
    lines.append(f"✅ 模型：Claude 订阅版（claude {_fmt(version) if version else '版本未知'}，模型 {model}），每封邮件调用一次 claude -p")
    if version is None:
        lines.append(f"⚠️  看不出 claude 的版本（{(version_out.stdout or version_out.stderr).strip()[:80]}），需要 {_fmt(MIN_VERSION)} 以上")
    elif version < MIN_VERSION:
        ok = False
        lines.append(f"❌ claude {_fmt(version)} 太旧，至少要 {_fmt(MIN_VERSION)}：运行 claude update")

    try:
        status = _last_json_object(run("auth", "status").stdout) or {}
    except (OSError, subprocess.TimeoutExpired):
        status = {}
    method, provider = status.get("authMethod"), status.get("apiProvider", "firstParty")
    if not status:
        lines.append("⚠️  看不出 claude 的登录状态：在终端运行 claude，确认已经用 Claude 账号登录")
    elif not status.get("loggedIn", method not in (None, "none")):
        ok = False
        lines.append("❌ claude 还没登录：在终端运行 claude，输入 /login，用你的 Claude 账号（Pro / Max）登录")
    elif method == "third_party" or provider != "firstParty":
        ok = False
        where = provider if provider != "firstParty" else "Bedrock、Vertex 之类"
        lines.append(f"❌ claude 配置成了第三方云（{where}），不走 Claude 订阅")
    elif method == "claude.ai":
        lines.append(f"✅ claude 已用 Claude 账号登录（{status.get('subscriptionType') or '订阅'}），用量算在订阅里")
    elif method == "oauth_token":
        lines.append("✅ claude 用长期令牌登录（claude setup-token），用量算在订阅里")
    elif method in ("api_key", "api_key_helper", "apiKeyHelper"):
        ok = False
        lines.append("❌ claude 现在用 API key 登录，会按量计费，不是订阅：运行 claude，输入 /login 改用 Claude 账号登录")
    else:
        lines.append(f"⚠️  claude 的登录方式是 {method}，不确定算不算订阅")
    if any(os.environ.get(name) for name in BILLING_ENV):
        lines.append("   环境里有 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN：调用 claude 时会去掉，保证走订阅")
    return ok, lines
