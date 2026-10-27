"""规则层：用 YAML 写"谁的邮件怎么处理"，在 LLM 之前执行。

一条规则 = match（怎么命中）+ then（命中后怎么办）。规则按顺序匹配，第一条命中的生效。
then.llm 为 false（默认）时规则直接定性，不花模型调用；为 true 时仍交给 LLM 写摘要，
但 then 里给出的 needs_action / urgency / category / notify 会覆盖模型的判断。

示例见 rules.example.yaml。
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .models import Decision, MessageHeader, NeedsAction, NotifyMode, Urgency

DEFAULT_RULES_YAML = """
rules:
  - name: 验证码和一次性密码
    match:
      subject_regex:
        - "(?i)verification code"
        - "(?i)one[- ]time (pass)?code"
        - "(?i)\\\\bOTP\\\\b"
        - "验证码"
        - "(?i)security code"
        - "(?i)confirm your (email|sign)"
    then:
      category: 账单/验证码
      needs_action: "no"
      notify: never

  - name: 自动发送和订阅
    match:
      from_regex:
        - "(?i)no-?reply"
        - "(?i)do-?not-?reply"
        - "(?i)newsletter"
        - "(?i)notifications?@"
        - "(?i)mailer-daemon"
        - "(?i)digest@"
    then:
      category: 订阅/通知
      needs_action: "no"
      notify: digest
"""


def _listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _yaml_bool_to_answer(value: Any) -> Any:
    # YAML 1.1 会把 yes/no 读成布尔值，这里转回去
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return value


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


class Match(BaseModel):
    from_email: list[str] = Field(default_factory=list)  # 完整地址，不分大小写
    from_domain: list[str] = Field(default_factory=list)  # 域名后缀，mbzuai.ac.ae 也匹配 sub.mbzuai.ac.ae
    from_regex: list[str] = Field(default_factory=list)  # 对整个 From 字段（名字 + 地址）
    subject_contains: list[str] = Field(default_factory=list)  # 不分大小写
    subject_regex: list[str] = Field(default_factory=list)
    account: list[str] = Field(default_factory=list)  # 账号 id 或名字子串

    @field_validator("*", mode="before")
    @classmethod
    def _accept_single(cls, value: Any) -> list[str]:
        return _listify(value)

    @model_validator(mode="after")
    def _not_empty(self) -> "Match":
        if not any(getattr(self, name) for name in type(self).model_fields):
            raise ValueError("match 至少要有一个条件")
        for pattern in self.from_regex + self.subject_regex:
            try:
                _compile(pattern)  # 提前暴露写错的正则
            except re.error as exc:
                raise ValueError(f"正则写错了：{pattern!r}（{exc}）") from exc
        return self

    def matches(self, header: MessageHeader) -> bool:
        email = header.sender_email
        domain = header.sender_domain
        subject = header.subject or ""
        account = " ".join(filter(None, [header.account_id, header.account_name])).lower()
        checks = [
            (self.from_email, lambda: any(email == item.lower() for item in self.from_email)),
            (self.from_domain, lambda: any(_domain_match(domain, item) for item in self.from_domain)),
            (self.from_regex, lambda: any(_compile(p).search(header.author or "") for p in self.from_regex)),
            (self.subject_contains, lambda: any(item.lower() in subject.lower() for item in self.subject_contains)),
            (self.subject_regex, lambda: any(_compile(p).search(subject) for p in self.subject_regex)),
            (self.account, lambda: any(item.lower() in account for item in self.account)),
        ]
        return all(check() for values, check in checks if values)


def _domain_match(domain: str, wanted: str) -> bool:
    wanted = wanted.lower().lstrip("@")
    return domain == wanted or domain.endswith("." + wanted)


class Then(BaseModel):
    category: str | None = None
    who: str | None = None
    needs_action: NeedsAction | None = None
    urgency: Urgency | None = None
    notify: NotifyMode | None = None
    llm: bool = False
    note: str | None = None

    @field_validator("needs_action", mode="before")
    @classmethod
    def _bool_answer(cls, value: Any) -> Any:
        return _yaml_bool_to_answer(value)


class Rule(BaseModel):
    name: str
    match: Match
    then: Then

    @model_validator(mode="after")
    def _decidable(self) -> "Rule":
        if not self.then.llm and self.then.needs_action is None:
            raise ValueError(f"规则「{self.name}」没有 needs_action，也没有 llm: true，不知道该怎么定性")
        return self

    def decide(self, header: MessageHeader) -> Decision:
        """不经过 LLM，直接按规则定性。"""
        what = header.subject or "（无主题）"
        if header.preview:
            what = f"{what}：{header.preview[:80]}"
        return Decision(
            who=self.then.who or header.sender_name or header.sender_email,
            what=what,
            needs_action=self.then.needs_action or "no",
            urgency=self.then.urgency or "normal",
            category=self.then.category or "其他",
            confidence=1.0,
            decided_by="rule",
            rule_name=self.name,
            notify=self.then.notify,
            suggested_action=self.then.note or "",
        )

    def apply_overrides(self, decision: Decision) -> Decision:
        """LLM 判断完以后，把规则里写死的字段盖上去。"""
        updates: dict[str, Any] = {"rule_name": self.name}
        if self.then.needs_action:
            updates["needs_action"] = self.then.needs_action
        if self.then.urgency:
            updates["urgency"] = self.then.urgency
        if self.then.category:
            updates["category"] = self.then.category
        if self.then.who:
            updates["who"] = self.then.who
        if self.then.notify:
            updates["notify"] = self.then.notify
        return decision.model_copy(update=updates)

    def hints(self) -> dict[str, str]:
        """给 LLM 的提示（已知这是谁、属于哪一类）。"""
        hints = {}
        if self.then.who:
            hints["who"] = self.then.who
        if self.then.category:
            hints["category"] = self.then.category
        if self.then.note:
            hints["note"] = self.then.note
        return hints


class RuleSet(BaseModel):
    rules: list[Rule] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, text: str) -> "RuleSet":
        data = yaml.safe_load(text) or {}
        if isinstance(data, list):
            data = {"rules": data}
        return cls.model_validate(data)

    @classmethod
    def load(cls, path: Path | None) -> "RuleSet":
        if path is None:
            return cls.from_yaml(DEFAULT_RULES_YAML)
        return cls.from_yaml(Path(path).expanduser().read_text(encoding="utf-8"))

    def match(self, header: MessageHeader) -> Rule | None:
        for rule in self.rules:
            if rule.match.matches(header):
                return rule
        return None
