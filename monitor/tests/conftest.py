import sys
from pathlib import Path

import pytest

from mail_monitor.config import Settings

TESTS_DIR = Path(__file__).parent
FAKE_SERVER = TESTS_DIR / "fake_server.py"


@pytest.fixture
def fake_command() -> list[str]:
    """用当前解释器启动假邮件服务器（stdio MCP）。"""
    return [sys.executable, str(FAKE_SERVER)]


@pytest.fixture
def settings(tmp_path: Path, fake_command: list[str]) -> Settings:
    return Settings(mcp_command=fake_command, home=tmp_path, days_back=2, max_results=100, timezone="Asia/Dubai")
