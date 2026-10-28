import json
import re
import shlex
import sys
from pathlib import Path

from typer.testing import CliRunner

from mail_monitor.cli import app


def test_sender_set_then_senders_lists_it(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f"MAIL_MONITOR_HOME={tmp_path}\nMAIL_MONITOR_TZ=Asia/Dubai\n", encoding="utf-8")
    monkeypatch.setenv("MAIL_MONITOR_ENV", str(env))
    runner = CliRunner()

    result = runner.invoke(app, ["--env", str(env), "sender-set", "Prof@Example.edu", "导师", "--note", "课题组"])
    assert result.exit_code == 0, result.output
    assert "已记住：prof@example.edu = 导师" in result.output

    result = runner.invoke(app, ["senders"])
    assert result.exit_code == 0, result.output
    assert "prof@example.edu" in result.output and "导师（你设定）" in result.output

    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0 and "senders_with_relation: 1" in result.output


def test_review_then_eval(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from mail_monitor.models import Decision, MessageHeader
    from mail_monitor.state import State

    env = tmp_path / ".env"
    env.write_text(f"MAIL_MONITOR_HOME={tmp_path}\n", encoding="utf-8")
    monkeypatch.setenv("MAIL_MONITOR_ENV", str(env))
    state = State(tmp_path / "state.db")
    when = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)
    state.record(MessageHeader(id="r1", folderPath="f", author="HR <hr@x.y>", subject="Interview", date=when, account_name="Gmail"),
                 Decision(who="HR", what="约面试", needs_action="yes", decided_by="llm"), notify_mode="instant", pushed=True)
    state.record(MessageHeader(id="r2", folderPath="f", author="News <n@x.y>", subject="Weekly", date=when, account_name="Gmail"),
                 Decision(needs_action="no", decided_by="rule", rule_name="订阅"), notify_mode="digest", pushed=False)
    state.close()

    runner = CliRunner()
    result = runner.invoke(app, ["review"], input="y\nn\n")
    assert result.exit_code == 0, result.output
    assert "[需要处理 · llm] HR：约面试" in result.output and "[知道就行 · rule·订阅]" in result.output
    assert "已标注 2 封" in result.output

    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 0, result.output
    assert "已标注 2 封，其中你认为需要处理的 1 封" in result.output
    assert "需要处理的召回：1/1（100%）被即时推送；漏推 0 封" in result.output
    assert "即时推送的精确：1/1（100%）真的需要处理；噪声 0 封" in result.output
    assert "llm：1 封，判对 1/1（100%）" in result.output

    assert "没有待核对的邮件" in runner.invoke(app, ["review"]).output  # 都标过了


def test_doctor_and_init_explain_a_closed_thunderbird(tmp_path, monkeypatch):
    dead = shlex.join([sys.executable, str(Path(__file__).parent / "dead_bridge.py")])
    env = tmp_path / ".env"
    env.write_text(f"MAIL_MONITOR_HOME={tmp_path}\nMAIL_MONITOR_MCP_COMMAND={dead}\n", encoding="utf-8")
    monkeypatch.setenv("MAIL_MONITOR_ENV", str(env))
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1 and "连不上 Thunderbird" in result.output, result.output

    result = runner.invoke(app, ["init"])
    assert result.exit_code == 1 and "连不上 Thunderbird" in result.output, result.output


def test_doctor_shows_quiet_hours_and_spots_an_old_notify_hub(tmp_path, monkeypatch, fake_notify_hub):
    dead = shlex.join([sys.executable, str(Path(__file__).parent / "dead_bridge.py")])
    env = tmp_path / ".env"
    lines = f"MAIL_MONITOR_HOME={tmp_path}\nMAIL_MONITOR_MCP_COMMAND={dead}\nMAIL_MONITOR_NOTIFY=notify_hub\nMAIL_MONITOR_NOTIFY_HUB_BIN={fake_notify_hub[0]}\n"
    env.write_text(lines, encoding="utf-8")
    monkeypatch.setenv("MAIL_MONITOR_ENV", str(env))
    monkeypatch.delenv("MAIL_MONITOR_QUIET_HOURS", raising=False)
    monkeypatch.setenv("FAKE_NOTIFY_HUB_VERSION", "0.2.1")
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])
    assert "notify_hub（notify-hub 0.2.1" in result.output and "还是 0.2 版" in result.output, result.output
    assert "免打扰：23:00-08:00" in result.output

    monkeypatch.setenv("FAKE_NOTIFY_HUB_VERSION", "0.3.0")
    env.write_text(lines + "MAIL_MONITOR_QUIET_HOURS=off\n", encoding="utf-8")
    result = runner.invoke(app, ["doctor"])
    assert "notify-hub 0.3.0" in result.output and "还是 0.2 版" not in result.output
    assert "免打扰：关" in result.output


def test_a_digest_that_cannot_be_pushed_keeps_the_mail(tmp_path, monkeypatch, fake_notify_hub):
    from mail_monitor.models import Decision, MessageHeader
    from mail_monitor.state import State

    env = tmp_path / ".env"
    env.write_text(
        f"MAIL_MONITOR_HOME={tmp_path}\nMAIL_MONITOR_NOTIFY=notify_hub\nMAIL_MONITOR_NOTIFY_HUB_BIN={fake_notify_hub[0]}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIL_MONITOR_ENV", str(env))
    state = State(tmp_path / "state.db")
    state.record(MessageHeader(id="d1", folderPath="f", author="News <n@x.y>", subject="Weekly"),
                 Decision(needs_action="no", decided_by="rule", rule_name="订阅"), notify_mode="digest", pushed=False)
    state.close()
    runner = CliRunner()

    monkeypatch.setenv("FAKE_NOTIFY_HUB_MODE", "down")
    result = runner.invoke(app, ["digest"])
    assert result.exit_code == 1 and "汇总没推出去，邮件都还攒着" in result.output and "连不上 Lark" in result.output, result.output

    monkeypatch.setenv("FAKE_NOTIFY_HUB_MODE", "ok")
    result = runner.invoke(app, ["digest"])
    assert result.exit_code == 0 and "已汇总 1 封" in result.output, result.output


def test_run_and_digest_lines_start_with_the_time(tmp_path, monkeypatch):
    """定时任务的日志只留最后几行，每行开头带时间才看得出是哪次跑的。"""
    dead = shlex.join([sys.executable, str(Path(__file__).parent / "dead_bridge.py")])
    env = tmp_path / ".env"
    env.write_text(f"MAIL_MONITOR_HOME={tmp_path}\nMAIL_MONITOR_MCP_COMMAND={dead}\nMAIL_MONITOR_TZ=Asia/Dubai\n", encoding="utf-8")
    monkeypatch.setenv("MAIL_MONITOR_ENV", str(env))
    runner = CliRunner()
    stamp = r"\d\d-\d\d \d\d:\d\d "

    result = runner.invoke(app, ["run"])
    assert re.match(stamp + "收件箱 0 个", result.output), result.output
    assert "连不上 Thunderbird" in result.output

    result = runner.invoke(app, ["digest"])
    assert result.exit_code == 0 and re.match(stamp + "没有待汇总的邮件", result.output), result.output


def test_notify_test_through_notify_hub(tmp_path, monkeypatch, fake_notify_hub):
    binary, log = fake_notify_hub
    env = tmp_path / ".env"
    env.write_text(f"MAIL_MONITOR_HOME={tmp_path}\nMAIL_MONITOR_NOTIFY=notify_hub\nMAIL_MONITOR_NOTIFY_HUB_BIN={binary}\n", encoding="utf-8")
    monkeypatch.setenv("MAIL_MONITOR_ENV", str(env))
    runner = CliRunner()

    result = runner.invoke(app, ["notify-test"])
    assert result.exit_code == 0 and "notify-hub：✅ 已推送" in result.output, result.output
    call = json.loads(log.read_text(encoding="utf-8"))
    assert call["args"][3:5] == ["--level", "normal"]  # notify-hub 收到就发，测试消息不用标紧急
    assert call["args"][-1] == "邮箱监控 Agent 测试消息 ✅"

    monkeypatch.setenv("FAKE_NOTIFY_HUB_MODE", "bad")
    result = runner.invoke(app, ["notify-test"])
    assert result.exit_code == 1 and "退出码 2" in result.output

