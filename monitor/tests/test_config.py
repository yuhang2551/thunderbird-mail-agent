from datetime import datetime, time, timezone

import pytest

from mail_monitor.config import Settings, load_settings, parse_quiet_hours


@pytest.mark.parametrize(
    ("text", "window"),
    [
        ("23:00-08:00", (time(23), time(8))),
        ("7:30 - 22:00", (time(7, 30), time(22))),
        ("OFF", None),
    ],
)
def test_parse_quiet_hours(text, window):
    assert parse_quiet_hours(text) == window


@pytest.mark.parametrize(("text", "message"), [("23:00", "开始-结束"), ("25:00-08:00", "00:00 到 23:59"), ("08:00-08:00", "同一个时间")])
def test_bad_quiet_hours_are_explained(text, message):
    with pytest.raises(ValueError, match=message):
        parse_quiet_hours(text)


def _dubai(hour: int, minute: int = 0) -> datetime:
    """迪拜钟点 hour:minute 对应的 UTC 时间（迪拜比 UTC 早 4 小时）。"""
    return datetime(2026, 10, 13, (hour - 4) % 24, minute, tzinfo=timezone.utc)


@pytest.mark.parametrize(("hour", "minute", "quiet"), [(23, 0, True), (2, 0, True), (7, 59, True), (8, 0, False), (12, 0, False), (22, 59, False)])
def test_quiet_hours_follow_the_configured_time_zone(hour, minute, quiet):
    settings = Settings(timezone="Asia/Dubai")  # 默认 23:00-08:00，开始算在里面、结束不算
    assert settings.in_quiet_hours(_dubai(hour, minute)) is quiet


def test_a_window_within_one_day_and_off():
    assert Settings(timezone="Asia/Dubai", quiet_hours="13:00-14:00").in_quiet_hours(_dubai(13, 30))
    assert not Settings(timezone="Asia/Dubai", quiet_hours="13:00-14:00").in_quiet_hours(_dubai(23))
    assert not Settings(timezone="Asia/Dubai", quiet_hours="off").in_quiet_hours(_dubai(2))


def test_quiet_hours_from_the_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_MONITOR_QUIET_HOURS", raising=False)
    env = tmp_path / ".env"
    env.write_text("MAIL_MONITOR_QUIET_HOURS=22:30-7:00\n", encoding="utf-8")
    assert load_settings(env).quiet_hours == "22:30-07:00"
    env.write_text("MAIL_MONITOR_QUIET_HOURS=off\n", encoding="utf-8")
    assert load_settings(env).quiet_window is None
    env.write_text("MAIL_MONITOR_QUIET_HOURS=night\n", encoding="utf-8")
    with pytest.raises(ValueError, match="MAIL_MONITOR_QUIET_HOURS"):
        load_settings(env)
    assert load_settings(tmp_path / "none.env").quiet_window == (time(23), time(8))
