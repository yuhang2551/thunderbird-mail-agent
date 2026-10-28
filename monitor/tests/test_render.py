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


NOW = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)  # 迪拜 18:00


def row(id: str, who: str = "", what: str = "", needs: str = "no", **extra):
    base = {
        "id": id, "who": who, "what": what, "needs_action": needs, "deadline": None, "urgency": "normal", "decided_by": "llm",
        "category": "其他", "sender_name": "", "sender_email": f"{id}@x", "subject": "", "account": None, "received_at": None,
    }
    return {**base, **extra}


def test_render_digest_groups():
    rows = [
        row("1", "HR", "约面试", "yes", deadline="2026-10-14", account="Gmail", received_at="2026-10-13T08:00:00+00:00"),
        row("2", "活动办", "讲座", account="School", received_at="2026-10-13T07:00:00+00:00"),
        row("3", needs="no", decided_by="rule", category="订阅/通知", sender_name="ArXiv", subject="papers"),
        row("4", "学校财务处", "学费账单", "unsure", urgency="high", account="me@mbzuai.ac.ae", received_at="2026-10-12T15:00:00+00:00"),
    ]
    text = render_digest(rows, now=NOW, timezone_name="Asia/Dubai")
    assert text.split("\n\n") == [
        "📮 邮件汇总 10-13 18:00 · 4 封，1 封要处理、1 封可能要管",
        "🔴 需要处理（1）\n• HR：约面试\n　期限 10-14 · Gmail 12:00",  # 今天收的只写钟点
        "🟡 可能要管（1）\n• 学校财务处：学费账单\n　紧急 · MBZUAI 10-12 19:00",
        "⚪ 知道就行（1）\n• 活动办：讲座",  # 知道就行的不写账号和时间
        "🔕 已忽略：订阅/通知 1",
    ]
    assert render_digest([]).endswith("· 0 封\n没有新邮件。")


def test_digest_merges_repeat_senders_and_caps_the_fyi_list():
    from mail_monitor.render import FYI_MAX, digest_push

    bank = [row(f"b{i}", "某银行", f"第 {i} 笔交易提醒", sender_email="Alerts@Bank.example") for i in range(3)]
    others = [row(f"o{i}", f"订阅 {i}", "周报") for i in range(FYI_MAX + 2)]
    body = digest_push([*bank, *others], now=NOW, timezone_name="Asia/Dubai").body
    lines = body.splitlines()
    assert lines[0] == f"⚪ 知道就行（{FYI_MAX + 5}）"
    assert lines[1] == "• 某银行 ×3：第 2 笔交易提醒"  # 同一个地址合成一行，显示最新的一封
    assert len(lines) == 1 + FYI_MAX + 1
    assert lines[-1] == "　……还有 3 封"


def test_digest_shortens_long_who_and_what():
    from mail_monitor.render import ITEM_WIDTH, digest_push, text_width

    # 用户 10-28 那张汇总卡里的真实长摘要（逐字抄的）
    rows = [
        row("1", "Mashreq 银行（NEO 账户）交易提醒", "Mashreq NEO 账户有一笔交易通知，正文没有写金额、时间或商户等细节"),
        row("2", "MBZUAI Nexus（学校 AI 学术活动通知）", "通知 2026-11-03（周二）11:30-12:30 在 Classroom 6 举办讲座"),
        row("3", "学校校园运营与服务部门（订阅邮件）", "通知 ACTIVE Masdar Park 体育设施对 Masdar City 社区提供 15% 折扣，优惠码 MASDARCITY@2026，有效期至 2026-12-31，需在线预订时输入。"),
    ]
    lines = digest_push(rows, now=NOW, timezone_name="Asia/Dubai").body.splitlines()[1:]
    assert lines[0] == "• Mashreq 银行交易提醒：Mashreq NEO 账户有一笔交易通知"  # 括号去掉，按逗号截
    assert lines[1] == "• MBZUAI Nexus：通知 2026-11-03（周二）11:30-12:30 在 Classroom 6 举办讲座"  # 放得下就原样
    assert lines[2].startswith("• 学校校园运营与服务部门：通知 ACTIVE Masdar Park") and lines[2].endswith("…")
    assert all(text_width(line) <= ITEM_WIDTH for line in lines)


def test_short_helpers():
    from mail_monitor.render import short_account, short_what, short_who

    assert short_who("学校孵化与创业中心（IEC）群发邮件") == "学校孵化与创业中心群发邮件"
    assert short_who("（未知）") == "（未知）"
    # 去括号时两边是英文数字就留空格，不粘成 2026-11-0311:30
    assert short_what("通知 2026-11-03（周二）11:30 开会，地点 Room 5，带电脑", 30) == "通知 2026-11-03 11:30 开会"
    assert short_what("付款 AED 1,250，11-15 前", 20) == "付款 AED 1,250"  # 1,250 不从逗号拆开
    assert short_what("Please read the attached quarterly report carefully", 24) == "Please read the…"  # 不截在单词中间
    assert short_what("一句话说完。", 30) == "一句话说完"
    assert short_account("yuhangl826@gmail.com") == "Gmail"
    assert short_account("yuhang.liu@mbzuai.ac.ae") == "MBZUAI"
    assert short_account("someone@university.edu") == "university"
    assert short_account("School") == "School"
    assert short_account(None) == ""


def test_instant_push_card_puts_who_and_what_in_the_title():
    from mail_monitor.render import instant_push

    header = MessageHeader(
        id="<hr-1@x>", folderPath="f", author="Talent Team <hr@quantfirm.example>", subject="Interview invitation",
        date=datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc), account_name="Gmail",
    )
    decision = Decision(who="量化公司 HR", what="约面试", needs_action="yes", urgency="high", deadline="2026-10-14", decided_by="llm")
    push = instant_push(header, decision, "Asia/Dubai")
    assert push.title == "量化公司 HR：约面试"
    assert push.body.splitlines() == ["需要处理 · 紧急 · Gmail", "期限：2026-10-14", "主题：Interview invitation | 10-13 12:00"]
    assert push.level == "normal"  # 模型说紧急不算，规则写了才按紧急推
    assert push.text == render_instant(header, decision, "Asia/Dubai")
    assert instant_push(header, decision, urgent=True).level == "urgent"

    nobody = MessageHeader(id="n", folderPath="f", author="", subject="")
    assert instant_push(nobody, Decision(decided_by="fallback")).title == "未知发件人：（无主题）"

    # 没经过模型：「什么事」是主题加正文开头，标题只放主题，完整的进正文
    plain = MessageHeader(id="p", folderPath="f", author="Prof <prof@x.edu>", subject="Re: numbers", preview="Could you send them by Friday?")
    push = instant_push(plain, Decision(who="导师", what="Re: numbers：Could you send them by Friday?", needs_action="yes", decided_by="rule"))
    assert push.title == "导师：Re: numbers"
    assert push.body.splitlines()[:2] == ["需要处理", "事：Re: numbers：Could you send them by Friday?"]


def test_digest_push_card():
    from mail_monitor.render import digest_push

    rows = [
        row("1", "HR", "约面试", "yes", account="Gmail", received_at="2026-10-13T08:00:00+00:00"),
        row("2", decided_by="rule", category="订阅/通知", sender_name="ArXiv", subject="papers"),
    ]
    push = digest_push(rows, now=NOW, timezone_name="Asia/Dubai")
    assert push.title == "邮件汇总 · 2 封，1 封要处理" and push.level == "normal"
    assert push.body == "🔴 需要处理（1）\n• HR：约面试\n　Gmail 12:00\n\n🔕 已忽略：订阅/通知 1"
    assert push.text.startswith("📮 邮件汇总 10-13 18:00 · 2 封，1 封要处理\n\n🔴 需要处理（1）")
    assert digest_push([row("3", "活动办", "讲座")], now=NOW).title == "邮件汇总 · 1 封，都不用处理"
