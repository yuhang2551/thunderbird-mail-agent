from datetime import datetime, timezone

from mail_monitor.models import Decision, MessageHeader
from mail_monitor.render import render_digest, render_instant


def test_render_instant_lines():
    header = MessageHeader(
        id="x", folderPath="f", author="Talent Team <hr@quantfirm.example>", subject="Interview invitation",
        date=datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc), account_name="Gmail",
    )
    decision = Decision(who="量化公司 HR", what="约面试", needs_action="yes", urgency="high", deadline="2026-10-14", suggested_action="回复确认", decided_by="llm")
    text = render_instant(header, decision, "Asia/Dubai")
    assert text.splitlines()[0] == "📬 需要处理 · 紧急 · Gmail"
    assert "谁：量化公司 HR" in text and "期限：2026-10-14" in text and "建议：回复确认" in text
    assert "10-13 12:00" in text  # UTC 08:00 → 迪拜 12:00


def test_render_digest_groups():
    rows = [
        {"id": "1", "who": "HR", "what": "约面试", "needs_action": "yes", "deadline": "2026-10-14", "decided_by": "llm", "category": "求职/HR", "sender_name": "", "sender_email": "", "subject": "", "account": "Gmail", "received_at": "2026-10-13T08:00:00+00:00"},
        {"id": "2", "who": "活动办", "what": "讲座", "needs_action": "no", "deadline": None, "decided_by": "llm", "category": "活动", "sender_name": "", "sender_email": "", "subject": "", "account": "School", "received_at": "2026-10-13T07:00:00+00:00"},
        {"id": "3", "who": "", "what": "", "needs_action": "no", "deadline": None, "decided_by": "rule", "category": "订阅/通知", "sender_name": "ArXiv", "sender_email": "n@x", "subject": "papers", "account": None, "received_at": None},
    ]
    text = render_digest(rows, now=datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc), timezone_name="Asia/Dubai")
    assert text.startswith("📮 邮件汇总 10-13 18:00 · 共 3 封")
    assert "需要处理（1）\n• HR：约面试（期限 2026-10-14） [Gmail 10-13 12:00]" in text
    assert "知道就行（1）\n• 活动办：讲座 [School 10-13 11:00]" in text
    assert text.endswith("已忽略：订阅/通知 1")
    assert render_digest([]).endswith("没有新邮件。")
