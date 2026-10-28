import sys
from pathlib import Path

import pytest

from mail_monitor.config import Settings

TESTS_DIR = Path(__file__).parent
FAKE_SERVER = TESTS_DIR / "fake_server.py"
FAKE_CLAUDE = TESTS_DIR / "fake_claude.py"
FAKE_NOTIFY_HUB = TESTS_DIR / "fake_notify_hub.py"


@pytest.fixture
def fake_command() -> list[str]:
    """用当前解释器启动假邮件服务器（stdio MCP）。"""
    return [sys.executable, str(FAKE_SERVER)]


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    """一个叫 claude 的可执行文件，实际跑 fake_claude.py。返回（命令路径，调用记录文件）。"""
    script = tmp_path / "bin" / "claude"
    script.parent.mkdir()
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE}" "$@"\n', encoding="utf-8")
    script.chmod(0o755)
    log = tmp_path / "claude-calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    for name in ("FAKE_CLAUDE_MODE", "FAKE_CLAUDE_AUTH", "FAKE_CLAUDE_VERSION", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return str(script), log


@pytest.fixture
def fake_notify_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    """一个叫 notify-hub 的可执行文件，实际跑 fake_notify_hub.py。返回（命令路径，调用记录文件）。"""
    script = tmp_path / "hub-bin" / "notify-hub"
    script.parent.mkdir()
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_NOTIFY_HUB}" "$@"\n', encoding="utf-8")
    script.chmod(0o755)
    log = tmp_path / "notify-hub-calls.jsonl"
    monkeypatch.setenv("FAKE_NOTIFY_HUB_LOG", str(log))
    monkeypatch.delenv("FAKE_NOTIFY_HUB_MODE", raising=False)
    return str(script), log


@pytest.fixture
def settings(tmp_path: Path, fake_command: list[str]) -> Settings:
    # 免打扰默认关掉：巡检用的是真时间，夜里跑测试结果也要一样。测免打扰的测试自己打开，再传一个固定的 now
    return Settings(
        mcp_command=fake_command, home=tmp_path, days_back=2, max_results=100, timezone="Asia/Dubai", quiet_hours="off"
    )
