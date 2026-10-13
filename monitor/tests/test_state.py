from datetime import datetime, timezone

from mail_monitor.models import Decision, MessageHeader
from mail_monitor.state import State


def header(mid: str, author: str = "a@example.com") -> MessageHeader:
    return MessageHeader(id=mid, folderPath="f", author=author, subject=f"subject {mid}", date=datetime.now(timezone.utc), account_name="Gmail")


def test_seen_record_and_digest_roundtrip():
    state = State(":memory:")
    assert state.seen(["m1", "m2"]) == set()

    state.record(header("m1"), Decision(needs_action="yes", decided_by="llm", who="HR", what="面试"), notify_mode="instant", pushed=True)
    state.record(header("m2"), Decision(needs_action="no", decided_by="rule", category="订阅/通知"), notify_mode="digest", pushed=False)
    state.record(header("m3"), Decision(needs_action="no", decided_by="rule"), notify_mode="never", pushed=False)
    assert state.seen(["m1", "m2", "m3", "m4"]) == {"m1", "m2", "m3"}

    pending = state.pending_digest()
    assert [row["id"] for row in pending] == ["m2"]
    state.mark_digested(["m2"])
    assert state.pending_digest() == []

    stats = state.stats()
    assert stats["total"] == 3 and stats["pushed"] == 1 and stats["by_rule"] == 2 and stats["by_llm"] == 1


def test_mark_seen_is_idempotent_and_senders_count():
    state = State(":memory:")
    assert state.mark_seen([header("m1"), header("m2")]) == 2
    assert state.mark_seen([header("m1"), header("m3")]) == 1

    state.touch_sender(header("m1", "Prof <prof@example.edu>"))
    state.touch_sender(header("m2", "prof@example.edu"))
    row = state.sender("PROF@example.edu")
    assert row["message_count"] == 2 and row["name"] == "Prof" and row["domain"] == "example.edu"
    state.set_sender_relation("prof@example.edu", "导师")
    assert state.sender("prof@example.edu")["relation"] == "导师"


def test_run_bookkeeping():
    state = State(":memory:")
    run_id = state.start_run()
    state.finish_run(run_id, fetched=5, new=2, pushed=1, errors=["x"])
    row = state.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["fetched"] == 5 and row["errors"] == '["x"]' and row["finished_at"]
