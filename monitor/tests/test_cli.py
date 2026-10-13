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
