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
