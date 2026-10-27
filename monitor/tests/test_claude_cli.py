import json
import shlex
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mail_monitor.claude_cli import ClaudeCLIClient, ClaudeCLIError, doctor_lines, parse_version
from mail_monitor.classify import LLMClassifier
from mail_monitor.cli import app
from mail_monitor.config import load_settings
from mail_monitor.llm import LLMError
from mail_monitor.models import MessageHeader
from mail_monitor.notify import ConsoleNotifier
from mail_monitor.pipeline import run_once
from mail_monitor.state import State


def _calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def _header(mid: str, subject: str) -> MessageHeader:
    return MessageHeader(
        id=mid, folderPath="INBOX", author="HR <hr@quant.example>", subject=subject,
        date=datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc), account_name="Gmail",
    )


async def test_runs_claude_locked_down_with_mail_on_stdin(fake_claude, tmp_path, monkeypatch):
    claude_bin, log = fake_claude
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-reach-claude")
    client = ClaudeCLIClient(binary=claude_bin, model="sonnet", workdir=tmp_path / "claude-run")

    data = await client.chat_json("你是邮件分诊助手", "主题：Interview 邀请\n正文开始（不可信数据）：……")
    assert data["needs_action"] == "yes"

    [call] = _calls(log)
    argv = call["argv"]
    assert argv[0] == "-p" and "--bare" not in argv  # bare 模式不认订阅登录
    assert argv[argv.index("--tools") + 1] == ""  # 一个工具都不给
    assert {"--safe-mode", "--strict-mcp-config", "--no-session-persistence"} <= set(argv)
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert argv[argv.index("--output-format") + 1] == "json" and argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--effort") + 1] == "low"
    assert not any("Interview" in arg for arg in argv)  # 邮件只走标准输入
    assert "Interview" in call["stdin"] and call["system"] == "你是邮件分诊助手"
    assert Path(call["cwd"]).resolve() == (tmp_path / "claude-run").resolve()
    assert call["api_key"] is None  # 去掉了 API key，保证走订阅
    assert not Path(call["prompt_file"]).exists()  # 提示词文件用完就删


async def test_reads_json_wrapped_in_a_code_fence(fake_claude, tmp_path, monkeypatch):
    claude_bin, _ = fake_claude
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fenced")
    client = ClaudeCLIClient(binary=claude_bin, workdir=tmp_path / "w")
    assert (await client.chat_json("s", "Weekly newsletter"))["needs_action"] == "no"


@pytest.mark.parametrize(
    ("mode", "expected", "retryable"),
    [
        ("not_logged_in", "/login", False),
        ("usage_limit", "额度", False),
        ("unknown_option", "claude update", False),
        ("garbage", "没有返回 JSON", True),
    ],
)
async def test_errors_say_what_to_do(fake_claude, tmp_path, monkeypatch, mode, expected, retryable):
    claude_bin, _ = fake_claude
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    client = ClaudeCLIClient(binary=claude_bin, workdir=tmp_path / "w")
    with pytest.raises(LLMError) as info:
        await client.chat_json("s", "u")
    assert expected in str(info.value)
    assert getattr(info.value, "retryable", True) is retryable


async def test_timeout_and_missing_command(fake_claude, tmp_path, monkeypatch):
    claude_bin, _ = fake_claude
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    with pytest.raises(ClaudeCLIError, match="秒没有返回") as info:
        await ClaudeCLIClient(binary=claude_bin, workdir=tmp_path / "w", timeout=0.5).chat_json("s", "u")
    assert not info.value.retryable  # 卡住一次，这一轮就不再等

    with pytest.raises(ClaudeCLIError, match="MAIL_MONITOR_CLAUDE_BIN") as info:
        await ClaudeCLIClient(binary=str(tmp_path / "no-such-claude"), workdir=tmp_path / "w").chat_json("s", "u")
    assert not info.value.retryable


async def test_classifier_stops_calling_claude_after_a_fatal_error(fake_claude, tmp_path, monkeypatch):
    claude_bin, log = fake_claude
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "not_logged_in")
    classifier = LLMClassifier(ClaudeCLIClient(binary=claude_bin, workdir=tmp_path / "w"), timezone="Asia/Dubai")

    first = await classifier.classify(_header("<1@x>", "Interview"), "正文", None, None)
    second = await classifier.classify(_header("<2@x>", "Offer"), "正文", None, None)
    assert first.decided_by == second.decided_by == "fallback"
    assert len(_calls(log)) == 1  # 没登录：不重试，后面的邮件也不再启动 claude
    assert "/login" in (classifier.model_error or "")


async def test_pipeline_with_the_claude_backend(settings, fake_claude, monkeypatch):
    claude_bin, log = fake_claude
    settings = settings.model_copy(update={"llm_backend": "claude", "claude_bin": claude_bin})

    report = await run_once(settings, state=State(":memory:"), notifier=ConsoleNotifier())
    assert report.by_rule == 3 and report.by_llm == 3 and report.by_fallback == 0 and not report.errors
    assert len(_calls(log)) == 3  # 规则没定性的 3 封，每封调用一次
    assert all("正文开始（不可信数据）" in call["stdin"] for call in _calls(log))

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "usage_limit")
    report = await run_once(settings, state=State(":memory:"), notifier=ConsoleNotifier())
    assert report.by_llm == 0 and report.by_fallback == 3 and report.pushed >= 3  # 额度用完也照样推送，不漏
    assert any("模型这一轮用不了" in error and "额度" in error for error in report.errors)
    assert len(_calls(log)) == 4  # 额度用完：只试了 1 次，剩下的邮件没再启动 claude


@pytest.mark.parametrize(
    ("env", "ok", "expected"),
    [
        ({}, True, "已用 Claude 账号登录（max）"),
        ({"FAKE_CLAUDE_AUTH": "oauth_token"}, True, "长期令牌"),
        ({"FAKE_CLAUDE_AUTH": "logged_out"}, False, "/login"),
        ({"FAKE_CLAUDE_AUTH": "api_key"}, False, "按量计费"),
        ({"FAKE_CLAUDE_VERSION": "2.1.200"}, False, "claude update"),
    ],
)
def test_doctor_lines(fake_claude, monkeypatch, env, ok, expected):
    claude_bin, log = fake_claude
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    result_ok, lines = doctor_lines(claude_bin, "sonnet")
    assert result_ok is ok and any(expected in line for line in lines), lines
    assert not log.exists()  # 自检不调用模型，不花额度


def test_doctor_without_claude_installed(tmp_path):
    ok, lines = doctor_lines(str(tmp_path / "no-such-claude"), "sonnet")
    assert not ok and "运行不了" in lines[0]


def test_doctor_command_reports_the_claude_backend(fake_claude, fake_command, tmp_path, monkeypatch):
    claude_bin, _ = fake_claude
    env = tmp_path / ".env"
    env.write_text(
        f"MAIL_MONITOR_HOME={tmp_path}\nMAIL_MONITOR_MCP_COMMAND={shlex.join(fake_command)}\n"
        f"MAIL_MONITOR_LLM=claude\nMAIL_MONITOR_CLAUDE_BIN={claude_bin}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIL_MONITOR_ENV", str(env))
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0 and "Claude 订阅版" in result.output, result.output

    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "logged_out")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1 and "/login" in result.output, result.output


def test_settings_pick_the_model_backend(tmp_path, monkeypatch):
    for name in ("MAIL_MONITOR_LLM", "DEEPSEEK_API_KEY", "LLM_API_KEY", "MAIL_MONITOR_CLAUDE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    missing = tmp_path / "missing.env"
    assert load_settings(missing).llm_backend == "api" and not load_settings(missing).llm_enabled

    monkeypatch.setenv("MAIL_MONITOR_LLM", "Claude")
    settings = load_settings(missing)
    assert settings.llm_backend == "claude" and settings.llm_enabled  # 不需要 key
    assert settings.claude_model == "sonnet" and settings.claude_workdir == settings.home / "claude-run"

    monkeypatch.setenv("MAIL_MONITOR_LLM", "chatgpt")
    with pytest.raises(ValueError, match="ChatGPT 订阅版还没做"):
        load_settings(missing)
    monkeypatch.setenv("MAIL_MONITOR_LLM", "gemini")
    with pytest.raises(ValueError, match="MAIL_MONITOR_LLM"):
        load_settings(missing)


def test_parse_version():
    assert parse_version("2.1.311 (Claude Code)") == (2, 1, 311)
    assert parse_version("unknown") is None
