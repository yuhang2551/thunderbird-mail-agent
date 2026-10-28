import os
import plistlib
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = sorted([*REPO.glob("monitor/scripts/*.sh"), *REPO.glob("scripts/*.sh")])

# macOS 自带的 bash 3.2 在 UTF-8 环境下，会把紧跟在 $变量 后面的中文的第一个字节当成变量名的一部分：
# set -u 时报 "PY?: unbound variable"，否则变量直接变成空的。所以变量后面紧跟非 ASCII 字符时必须写成 ${变量}
BARE_VARIABLE_BEFORE_NON_ASCII = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*(?=[^\x00-\x7f])")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: str(path.relative_to(REPO)))
def test_variables_before_chinese_text_use_braces(script: Path):
    bad = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1)
        if BARE_VARIABLE_BEFORE_NON_ASCII.search(line)
    ]
    assert not bad, "\n".join(bad)


DOCS = sorted(
    path
    for path in REPO.rglob("*.md")
    if not any(part.startswith(".") or part == "node_modules" for part in path.relative_to(REPO).parts)
)
SHELL_FENCES = {"bash", "sh", "zsh", "shell", "console"}
SHELL_COMMENT = re.compile(r"^\s*#(?!!)|\s#(\s|$)")


def test_command_blocks_in_docs_have_no_comments():
    """macOS 终端默认的 zsh 不认 # 注释：整行注释报 command not found: #，行尾注释会变成命令的参数。
    命令块是整段粘进终端的，所以说明写在命令块外面。"""
    bad = []
    for doc in DOCS:
        fence = None
        for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                fence = None if fence is not None else line.strip("` \t")
            elif fence in SHELL_FENCES and SHELL_COMMENT.search(line):
                bad.append(f"{doc.relative_to(REPO)}:{number}: {line.strip()}")
    assert DOCS and not bad, "\n".join(bad)


LAUNCHD = REPO / "monitor" / "scripts" / "launchd.sh"


def launchd(tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    base = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "MAIL_MONITOR_BIN": "/opt/mm/mail-monitor"}
    return subprocess.run(["bash", str(LAUNCHD), *args], capture_output=True, text=True, env={**base, **env}, check=False)


def printed_plists(tmp_path: Path, **env: str) -> list[dict]:
    """launchd.sh print 打出来的两个 plist（run、digest）。"""
    result = launchd(tmp_path, "print", **env)
    assert result.returncode == 0, result.stderr
    return [plistlib.loads(("<?xml" + part).encode()) for part in result.stdout.split("<?xml")[1:]]


def test_launchd_checks_hourly_and_once_at_load(tmp_path: Path):
    run, digest = printed_plists(tmp_path)
    assert run["ProgramArguments"] == ["/opt/mm/mail-monitor", "run"]
    assert run["StartInterval"] == 3600
    assert run["RunAtLoad"] is True  # 装上、开机登录时先巡检一次，不用等一小时
    assert digest["RunAtLoad"] is False  # 汇总只在定好的时间发
    assert [(e["Hour"], e["Minute"]) for e in digest["StartCalendarInterval"]] == [(9, 0), (18, 0)]
    # claude 和 notify-hub 的官方装法都在 ~/.local/bin，launchd 默认的 PATH 里没有
    assert f"{tmp_path}/.local/bin" in run["EnvironmentVariables"]["PATH"].split(":")


def test_launchd_interval_and_digest_hours_can_be_changed(tmp_path: Path):
    run, digest = printed_plists(tmp_path, RUN_INTERVAL="1800", DIGEST_HOURS="8 13 20")
    assert run["StartInterval"] == 1800
    assert [e["Hour"] for e in digest["StartCalendarInterval"]] == [8, 13, 20]


def test_launchd_rejects_an_interval_that_is_not_seconds(tmp_path: Path):
    result = launchd(tmp_path, "print", RUN_INTERVAL="1h")
    assert result.returncode == 1
    assert "RUN_INTERVAL" in result.stderr


def test_launchd_install_refuses_before_init(tmp_path: Path):
    """装上就会先巡检一次：没 init 的话会把最近两天的邮件全推一遍，所以先拦下来。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "uname").write_text("#!/bin/sh\necho Darwin\n")
    (fake_bin / "uname").chmod(0o755)
    mail_monitor = fake_bin / "mail-monitor"
    mail_monitor.write_text("#!/bin/sh\n")
    mail_monitor.chmod(0o755)
    (tmp_path / ".mail-monitor").mkdir()
    (tmp_path / ".mail-monitor" / ".env").write_text("MAIL_MONITOR_NOTIFY=console\n")

    result = launchd(tmp_path, "install", PATH=f"{fake_bin}:{os.environ['PATH']}", MAIL_MONITOR_BIN=str(mail_monitor))
    assert result.returncode == 1
    assert "mail-monitor init" in result.stderr
    assert not (tmp_path / "Library").exists()  # 什么都没装
