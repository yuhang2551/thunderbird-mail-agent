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


def test_normalize_subject():
    from mail_monitor.models import normalize_subject

    assert normalize_subject("Re: RE: Fwd: 回复：  Hello   World ") == "hello world"
    assert normalize_subject("[Seminar] LLM agents") == "[seminar] llm agents"
    assert normalize_subject("Re[2]: ping") == "ping"
    assert normalize_subject(None) == "" and normalize_subject("Re:") == ""


def test_migrates_old_schema(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE messages (id TEXT PRIMARY KEY, account TEXT, folder_path TEXT, thread_id TEXT, sender_email TEXT,
             sender_name TEXT, subject TEXT, received_at TEXT, first_seen_at TEXT NOT NULL, category TEXT, needs_action TEXT,
             urgency TEXT, deadline TEXT, who TEXT, what TEXT, suggested_action TEXT, decided_by TEXT, rule_name TEXT,
             notify_mode TEXT, pushed_at TEXT, digest_pending INTEGER NOT NULL DEFAULT 0, digested_at TEXT);
           CREATE TABLE senders (email TEXT PRIMARY KEY, name TEXT, domain TEXT, relation TEXT, notes TEXT,
             first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, message_count INTEGER NOT NULL DEFAULT 0);
           INSERT INTO messages (id, account, subject, first_seen_at, decided_by) VALUES ('m1', 'Gmail', 'Re: Fwd: Hello world', 'x', 'llm');"""
    )
    conn.commit()
    conn.close()

    state = State(path)
    columns = {row["name"] for row in state.conn.execute("PRAGMA table_info(messages)")}
    assert "subject_key" in columns
    assert state.conn.execute("SELECT subject_key FROM messages WHERE id = 'm1'").fetchone()[0] == "hello world"
    sender_columns = {row["name"] for row in state.conn.execute("PRAGMA table_info(senders)")}
    assert {"relation_source", "relation_updated_at"} <= sender_columns
    State(path).close()  # 再开一次不会报错（迁移是幂等的）


def test_relation_source_precedence():
    state = State(":memory:")
    assert state.set_sender_relation("X@a.b", "HR/招聘方", source="llm")
    assert state.sender("x@a.b")["relation_source"] == "llm"
    assert state.set_sender_relation("x@a.b", "公司/合作方", source="llm")  # 模型可以改模型自己猜的
    assert state.set_sender_relation("x@a.b", "导师", source="rule")
    assert not state.set_sender_relation("x@a.b", "陌生人", source="llm")  # 模型改不了规则写的
    assert state.sender("x@a.b")["relation"] == "导师"
    assert not state.set_sender_relation("x@a.b", "导师", source="rule")  # 没变化
    assert state.set_sender_relation("x@a.b", "师兄", source="user", notes="同组")
    assert not state.set_sender_relation("x@a.b", "导师", source="rule")  # 规则改不了你设的
    row = state.sender("x@a.b")
    assert row["relation"] == "师兄" and row["notes"] == "同组" and row["message_count"] == 0
    assert [r["email"] for r in state.list_senders()] == ["x@a.b"]
    assert state.stats()["senders_with_relation"] == 1


def test_sender_and_thread_history():
    from datetime import timedelta

    base = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)

    def h(mid, folder, thread, subject, author="Prof <prof@example.edu>", hours=0):
        return MessageHeader(id=mid, folderPath=folder, threadId=thread, author=author, subject=subject, date=base + timedelta(hours=hours), account_name="School")

    state = State(":memory:")
    state.record(h("t1", "INBOX", 7, "DoAtlas numbers"), Decision(who="导师", what="要数字", needs_action="yes", decided_by="llm"), notify_mode="instant", pushed=True)
    state.record(h("t0", "INBOX", 1, "Group meeting", hours=-5), Decision(who="导师", what="周三组会", needs_action="no", decided_by="llm"), notify_mode="digest", pushed=False)
    state.mark_seen([h("x1", "INBOX", 9, "Unrelated", author="Someone <s@example.com>")])

    reply = h("t2", "INBOX", 7, "Re: DoAtlas numbers", hours=2)
    assert [r["id"] for r in state.sender_history("prof@example.edu", exclude_id="t2")] == ["t1", "t0"]
    assert state.sender_counts("prof@example.edu", exclude_id="t2") == (2, 1)
    assert [r["id"] for r in state.thread_history(reply)] == ["t1"]  # 同一文件夹同一 thread_id
    forwarded = h("t3", "OTHER", 99, "Fwd: DoAtlas numbers", hours=3)
    assert [r["id"] for r in state.thread_history(forwarded)] == ["t1"]  # 换了文件夹，按归一化主题找到
    assert state.thread_history(h("x1", "INBOX", 9, "Unrelated")) == []  # 自己不算
    assert state.sender_counts("nobody@example.com") == (0, 0)
