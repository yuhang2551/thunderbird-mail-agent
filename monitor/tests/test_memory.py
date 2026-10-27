from datetime import datetime, timedelta, timezone

from mail_monitor.memory import recall
from mail_monitor.models import Decision, MessageHeader
from mail_monitor.state import State

BASE = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)


def header(mid: str, subject: str, *, thread: int = 7, author: str = "Prof. Example <prof@example.edu>", hours: float = 0) -> MessageHeader:
    return MessageHeader(id=mid, folderPath="INBOX", threadId=thread, author=author, subject=subject, date=BASE + timedelta(hours=hours), account_name="School")


def test_recall_renders_sender_and_thread_without_duplicates():
    state = State(":memory:")
    state.record(header("p1", "DoAtlas numbers"), Decision(who="导师", what="要周五前交数字", needs_action="yes", decided_by="llm"), notify_mode="instant", pushed=True)
    state.record(header("p0", "Group meeting", thread=1, hours=-30), Decision(who="导师", what="周三组会改到周四", needs_action="no", decided_by="llm"), notify_mode="digest", pushed=False)
    state.mark_seen([header("p-old", "Welcome", thread=2, hours=-200)])
    state.set_sender_relation("prof@example.edu", "导师", source="rule")

    memory = recall(state, header("p2", "Re: DoAtlas numbers", hours=5))
    assert memory.relation == "导师" and not memory.is_empty()
    assert memory.sender.total == 3 and memory.sender.needs_action == 1
    assert [item.id for item in memory.thread] == ["p1"]
    assert [item.id for item in memory.sender.recent] == ["p0"]  # p1 已经在话题里列过，不重复

    text = memory.render("Asia/Dubai")
    assert text.startswith("记忆（我们之前的记录，仅供参考）：")
    assert "发件人 prof@example.edu：身份=导师（规则设定）；之前 3 封，其中 1 封需要处理" in text
    assert "10-09 06:00 导师：周三组会改到周四（知道就行）" in text
    assert "同一话题之前的邮件：\n  · 10-10 12:00 导师：要周五前交数字（需要处理）" in text
    assert text.count("要周五前交数字") == 1


def test_recall_for_unknown_sender_is_empty():
    state = State(":memory:")
    memory = recall(state, header("n1", "Hello", author="New <new@example.org>"))
    assert memory.is_empty() and memory.render() == "" and memory.relation is None


def test_recall_counts_init_rows_and_marks_them_unjudged():
    state = State(":memory:")
    state.mark_seen([header("i1", "Old thread", thread=3, hours=-50)])
    memory = recall(state, header("i2", "Re: Old thread", thread=3))
    assert memory.sender.total == 1 and memory.sender.recent == []  # 登记的邮件没判断过，不进"最近几封"
    assert "（登记时未判断）" in memory.render("Asia/Dubai")
