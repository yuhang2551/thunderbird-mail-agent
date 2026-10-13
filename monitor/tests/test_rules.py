import pytest
from pydantic import ValidationError

from mail_monitor.models import MessageHeader
from mail_monitor.rules import RuleSet


def header(author: str, subject: str = "", account: str | None = None) -> MessageHeader:
    return MessageHeader(id="x", folderPath="f", author=author, subject=subject, account_name=account)


def test_default_rules_cover_otp_and_noreply():
    rules = RuleSet.load(None)
    otp = rules.match(header("no-reply@accounts.example.com", "Your verification code is 1234"))
    assert otp and otp.name == "验证码和一次性密码"
    assert otp.decide(header("no-reply@x.example", "Your verification code is 1234")).notify_mode == "never"

    news = rules.match(header("ArXiv Daily <newsletter@arxiv-daily.example>", "Today's papers"))
    assert news and news.name == "自动发送和订阅"
    decision = news.decide(header("newsletter@x.example", "Today's papers"))
    assert decision.needs_action == "no" and decision.notify_mode == "digest" and decision.decided_by == "rule"

    assert rules.match(header("Prof. Example <prof@example.edu>", "Re: progress")) is None


def test_first_match_wins_and_yaml_booleans():
    rules = RuleSet.from_yaml(
        """
rules:
  - name: 导师
    match: { from_email: PROF@example.edu }
    then: { category: 导师/课题组, needs_action: yes, urgency: high, llm: true, who: 导师 }
  - name: 学校域名
    match: { from_domain: example.edu }
    then: { category: 学校行政, needs_action: no }
"""
    )
    prof = rules.match(header("Prof. Example <prof@example.edu>", "Re: progress"))
    assert prof and prof.name == "导师"
    assert prof.then.needs_action == "yes"  # YAML 的 yes 会被读成 True，规则层要转回来
    assert prof.then.llm is True
    assert prof.hints() == {"who": "导师", "category": "导师/课题组"}

    registrar = rules.match(header("Registrar <registrar@sub.example.edu>", "Registration"))
    assert registrar and registrar.name == "学校域名"
    assert registrar.decide(header("registrar@sub.example.edu")).needs_action == "no"


def test_regex_subject_and_account_are_anded():
    rules = RuleSet.from_yaml(
        """
rules:
  - name: 学校活动
    match:
      account: School
      subject_regex: ["(?i)seminar|workshop"]
    then: { category: 活动, needs_action: unsure, notify: instant }
"""
    )
    assert rules.match(header("events@example.edu", "[Seminar] talk", account="School")) is not None
    assert rules.match(header("events@example.edu", "[Seminar] talk", account="Gmail")) is None
    assert rules.match(header("events@example.edu", "Lunch menu", account="School")) is None


def test_apply_overrides_keeps_llm_summary():
    rules = RuleSet.from_yaml(
        """
rules:
  - name: HR
    match: { from_domain: quantfirm.example }
    then: { needs_action: yes, urgency: high, llm: true, notify: instant }
"""
    )
    from mail_monitor.models import Decision

    rule = rules.rules[0]
    llm_decision = Decision(who="某公司 HR", what="约面试", needs_action="unsure", urgency="normal", decided_by="llm")
    merged = rule.apply_overrides(llm_decision)
    assert merged.what == "约面试" and merged.decided_by == "llm"
    assert merged.needs_action == "yes" and merged.urgency == "high" and merged.notify_mode == "instant"
    assert merged.rule_name == "HR"


def test_invalid_rules_are_rejected():
    with pytest.raises(ValidationError, match="needs_action"):
        RuleSet.from_yaml("rules:\n  - name: 坏规则\n    match: { from_domain: a.example }\n    then: { category: 其他 }\n")
    with pytest.raises(ValidationError, match="至少要有一个条件"):
        RuleSet.from_yaml("rules:\n  - name: 空条件\n    match: {}\n    then: { needs_action: no }\n")
    with pytest.raises(ValidationError):
        RuleSet.from_yaml("rules:\n  - name: 坏正则\n    match: { subject_regex: '(' }\n    then: { needs_action: no }\n")
