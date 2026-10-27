import json
import sys
from pathlib import Path

import httpx

from mail_monitor.classify import LLMClassifier
from mail_monitor.llm import LLMClient
from mail_monitor.notify import ConsoleNotifier
from mail_monitor.pipeline import init_seen, run_once, send_digest
from mail_monitor.rules import RuleSet
from mail_monitor.state import State


async def test_first_run_pushes_then_second_run_is_quiet(settings):
    state = State(":memory:")
    notifier = ConsoleNotifier()

    report = await run_once(settings, state=state, notifier=notifier)
    # 7 封里有 1 封超过 2 天；没有 LLM key：3 封规则定性，3 封保底"拿不准"
    assert report.inboxes == 2 and report.fetched == 6 and report.new == 6
    assert report.by_rule == 3 and report.by_fallback == 3 and report.by_llm == 0
    assert report.pushed == 3 and report.digest_pending == 2 and report.ignored == 1
    assert report.errors == []
    pushed_text = "\n".join(notifier.sent)
    assert "Interview invitation" in pushed_text and "DoAtlas-2" in pushed_text
    assert "verification code" not in pushed_text  # 验证码：never
    assert "ArXiv" not in pushed_text  # 订阅：进汇总

    again = await run_once(settings, state=state, notifier=notifier)
    assert again.fetched == 6 and again.new == 0 and again.pushed == 0

    count = await send_digest(settings, state=state, notifier=notifier)
    assert count == 2
    digest = notifier.sent[-1]
    assert digest.startswith("📮 邮件汇总") and "已忽略：订阅/通知 2" in digest
    assert await send_digest(settings, state=state, notifier=notifier) == 0


async def test_init_marks_existing_mail_as_seen(settings):
    state = State(":memory:")
    report = await init_seen(settings, state=state)
    assert report.new == 6
    notifier = ConsoleNotifier()
    after = await run_once(settings, state=state, notifier=notifier)
    assert after.new == 0 and notifier.sent == []


async def test_dry_run_does_not_touch_state(settings, capsys):
    report = await run_once(settings, dry_run=True)
    assert report.new == 6
    # 数据库没建在 home 下
    assert not settings.resolved_db_path.exists()
    # 即时推送的之外，会进汇总的也打出来
    out = capsys.readouterr().out
    assert "Interview invitation" in out and "📮 邮件汇总" in out and "已忽略：订阅/通知 2" in out


async def test_llm_path_with_rule_overrides_and_tagging(settings, tmp_path):
    rules = RuleSet.from_yaml(
        """
rules:
  - name: 导师
    match: { from_email: prof@example.edu }
    then: { category: 导师/课题组, who: 导师, needs_action: yes, urgency: high, llm: true }
  - name: 验证码
    match: { subject_regex: "(?i)verification code" }
    then: { needs_action: no, notify: never }
  - name: 订阅
    match: { from_regex: ["(?i)newsletter", "(?i)notifications?@"] }
    then: { category: 订阅/通知, needs_action: no, notify: digest }
"""
    )
    bodies_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][1]["content"]
        bodies_seen.append(user)
        if "DoAtlas" in user:
            verdict = {"who": "模型以为是同学", "what": "要周五前交更新后的数字", "needs_action": "unsure", "urgency": "normal", "deadline": None, "category": "导师/课题组", "confidence": 0.7}
        elif "Interview" in user:
            verdict = {"who": "量化公司 HR", "what": "约下周二面试，明天前确认", "needs_action": "yes", "urgency": "high", "deadline": None, "suggested_action": "回复确认", "category": "求职/HR", "confidence": 0.9}
        else:
            verdict = {"who": "学校活动办公室", "what": "周四 4 点讲座，周三中午前报名", "needs_action": "no", "urgency": "low", "deadline": None, "category": "活动", "confidence": 0.8}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(verdict, ensure_ascii=False)}}]})

    settings = settings.model_copy(update={"llm_api_key": "test", "action_tag": True})
    classifier = LLMClassifier(LLMClient(api_key="k", base_url="https://api.deepseek.com", model="m", transport=httpx.MockTransport(handler)), timezone="Asia/Dubai")
    state = State(":memory:")
    notifier = ConsoleNotifier()

    report = await run_once(settings, state=state, notifier=notifier, classifier=classifier, rules=rules)
    assert report.by_rule == 3 and report.by_llm == 3 and report.by_fallback == 0
    assert any("send me the updated extraction numbers" in u for u in bodies_seen)  # 读了正文
    assert any("已知信息：who=导师" in u for u in bodies_seen)  # 规则提示传给了模型

    rows = {row["id"]: row for row in state.conn.execute("SELECT * FROM messages").fetchall()}
    prof = rows["<prof-1@example.edu>"]
    assert prof["who"] == "导师" and prof["needs_action"] == "yes" and prof["urgency"] == "high"  # 规则覆盖了模型
    assert prof["what"] == "要周五前交更新后的数字" and prof["decided_by"] == "llm"  # 摘要来自模型
    assert rows["<seminar-1@example.edu>"]["notify_mode"] == "digest"
    assert report.pushed == 2 and report.digest_pending == 3 and report.ignored == 1
    assert report.tagged == 2  # 两封"需要处理"的打了标签

    digest_count = await send_digest(settings, state=state, notifier=notifier)
    assert digest_count == 3
    assert "知道就行（1）" in notifier.sent[-1] and "已忽略：订阅/通知 2" in notifier.sent[-1]


async def test_memory_feeds_the_next_run(settings, fake_command, tmp_path):
    """第一次 run 记住发件人身份和判断，第二次 run 同一话题的回信和同一发件人的新邮件都能带着记忆去判断。"""
    rules = RuleSet.from_yaml(
        """
rules:
  - name: 导师
    match: { from_email: prof@example.edu }
    then: { category: 导师/课题组, who: 导师, needs_action: yes, urgency: high, llm: true }
  - name: 验证码
    match: { subject_regex: "(?i)verification code" }
    then: { needs_action: no, notify: never }
  - name: 订阅
    match: { from_regex: ["(?i)newsletter", "(?i)notifications?@"] }
    then: { category: 订阅/通知, needs_action: no, notify: digest }
"""
    )
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][1]["content"]
        prompts.append(user)
        if "主题：Re: DoAtlas-2 progress numbers" in user and "Attached are the numbers" in user:
            verdict = {"who": "导师", "relation": "导师", "what": "确认收到数字，周五组会再讨论", "needs_action": "no", "confidence": 0.9}
        elif "DoAtlas" in user:
            verdict = {"who": "导师", "relation": "导师", "what": "要周五前交更新后的数字", "needs_action": "yes", "urgency": "high", "confidence": 0.9}
        elif "Interview confirmed" in user:
            verdict = {"who": "量化公司 HR", "relation": "HR/招聘方", "what": "面试确认在周二 10 点，附会议链接", "needs_action": "no", "confidence": 0.9}
        elif "Interview" in user:
            verdict = {"who": "量化公司 HR", "relation": "HR/招聘方", "what": "约下周二面试，明天前确认", "needs_action": "yes", "urgency": "high", "confidence": 0.9}
        else:
            verdict = {"who": "学校活动办公室", "relation": "学校行政", "what": "周四 4 点讲座", "needs_action": "no", "confidence": 0.4}  # 把握不够，不记身份
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(verdict, ensure_ascii=False)}}]})

    settings = settings.model_copy(update={"llm_api_key": "test"})
    classifier = LLMClassifier(LLMClient(api_key="k", base_url="https://api.deepseek.com", model="m", transport=httpx.MockTransport(handler)), timezone="Asia/Dubai")
    state = State(":memory:")
    notifier = ConsoleNotifier()

    first = await run_once(settings, state=state, notifier=notifier, classifier=classifier, rules=rules)
    assert first.new == 6 and first.by_llm == 3
    assert first.relations == 2  # 导师（规则写的）+ HR（模型猜的）；活动办公室把握不够
    assert state.sender("prof@example.edu")["relation_source"] == "rule"
    assert state.sender("hr@quantfirm.example")["relation"] == "HR/招聘方" and state.sender("hr@quantfirm.example")["relation_source"] == "llm"
    assert state.sender("events@example.edu")["relation"] is None
    assert not any("记忆（" in p for p in prompts)  # 第一次什么都不知道

    # 第二次巡检：同一话题来了回信，HR 又来了一封新主题
    fixture = json.loads(Path("tests/fixtures/mailbox.json").read_text(encoding="utf-8"))
    fixture["messages"] += [
        {
            "id": "<prof-2@example.edu>", "threadId": 4242,
            "folderPath": "imap://student%40example.edu@outlook.office365.com/INBOX",
            "author": "Prof. Example <prof@example.edu>", "recipients": "student@example.edu", "ccList": "",
            "subject": "Re: DoAtlas-2 progress numbers", "age_hours": 0.5,
            "body": "Attached are the numbers I meant. Let's discuss at Friday's group meeting.",
        },
        {
            "id": "<hr-2@quantfirm.example>",
            "folderPath": "imap://student%40example.com@imap.gmail.com/INBOX",
            "author": "Talent Team <hr@quantfirm.example>", "recipients": "student@example.com", "ccList": "",
            "subject": "Interview confirmed - Tuesday 10:00", "age_hours": 0.2,
            "body": "Your interview is confirmed for Tuesday 10:00. Meeting link below.",
        },
    ]
    path = tmp_path / "round2.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    settings2 = settings.model_copy(update={"mcp_command": fake_command + [str(path)]})
    prompts.clear()

    second = await run_once(settings2, state=state, notifier=notifier, classifier=classifier, rules=rules)
    assert second.new == 2 and second.by_llm == 2 and second.relations == 0  # 身份没变，不重复记
    prof_prompt = next(p for p in prompts if "prof-2" in p or "Attached are the numbers" in p)
    assert "身份=导师（规则设定）；之前 1 封，其中 1 封需要处理" in prof_prompt
    assert "同一话题之前的邮件：\n  · " in prof_prompt and "导师：要周五前交更新后的数字（需要处理）" in prof_prompt
    hr_prompt = next(p for p in prompts if "Interview confirmed" in p)
    assert "身份=HR/招聘方（模型判断）；之前 1 封，其中 1 封需要处理" in hr_prompt
    assert "量化公司 HR：约下周二面试，明天前确认（需要处理）" in hr_prompt
    assert "同一话题" not in hr_prompt  # 新主题，没有话题历史
    # 规则仍然盖过模型：导师的回信即使模型说不用管，也按规则推紧急
    prof_row = state.conn.execute("SELECT * FROM messages WHERE id = '<prof-2@example.edu>'").fetchone()
    assert prof_row["needs_action"] == "yes" and prof_row["what"] == "确认收到数字，周五组会再讨论"


async def test_run_reports_error_when_thunderbird_is_closed(settings):
    dead = settings.model_copy(update={"mcp_command": [sys.executable, str(Path(__file__).parent / "dead_bridge.py")]})
    report = await run_once(dead, notifier=ConsoleNotifier())
    assert report.fetched == 0 and report.pushed == 0
    assert any("连不上 Thunderbird" in error for error in report.errors)
