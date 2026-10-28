from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from mail_monitor.config import (
    Settings,
    load_settings,
    parse_digest_hours,
    parse_quiet_hours,
)


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


@pytest.mark.parametrize(("text", "hours"), [("8,12,18", [8, 12, 18]), ("18 8 12 8", [8, 12, 18]), ("8:00、18:00", [8, 18]), ("0", [0])])
def test_parse_digest_hours(text, hours):
    assert parse_digest_hours(text) == hours


@pytest.mark.parametrize("text", ["", "8,25", "8:30", "早上"])
def test_bad_digest_hours_are_explained(text):
    with pytest.raises(ValueError, match="整点|至少"):
        parse_digest_hours(text)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=ZoneInfo("Asia/Dubai"))


@pytest.mark.parametrize(
    ("now", "slot"),
    [(_at(13, 8), _at(13, 8)), (_at(13, 13, 5), _at(13, 12)), (_at(13, 23, 59), _at(13, 18)), (_at(13, 7, 59), _at(12, 18))],
)
def test_latest_digest_slot_follows_the_configured_time_zone(now, slot):
    # 传进来的是 UTC 时间也一样：钟点按 MAIL_MONITOR_TZ 算
    assert Settings(timezone="Asia/Dubai").latest_digest_slot(now.astimezone(timezone.utc)) == slot


def test_digest_hours_from_the_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_MONITOR_DIGEST_HOURS", raising=False)
    env = tmp_path / ".env"
    env.write_text("MAIL_MONITOR_DIGEST_HOURS=21 9\n", encoding="utf-8")
    assert load_settings(env).digest_hour_list == [9, 21]
    env.write_text("MAIL_MONITOR_DIGEST_HOURS=9:30\n", encoding="utf-8")
    with pytest.raises(ValueError, match="MAIL_MONITOR_DIGEST_HOURS"):
        load_settings(env)
    assert load_settings(tmp_path / "none.env").digest_hour_list == [8, 12, 18]
