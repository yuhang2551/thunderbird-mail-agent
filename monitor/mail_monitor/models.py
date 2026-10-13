"""数据模型。外部字段名和 thunderbird-mcp 的返回保持一致（alias），内部统一用下划线命名。"""
from __future__ import annotations

from datetime import datetime
from email.utils import parseaddr
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NeedsAction = Literal["yes", "no", "unsure"]
Urgency = Literal["high", "normal", "low"]
NotifyMode = Literal["instant", "digest", "never"]
DecidedBy = Literal["rule", "llm", "fallback", "init"]

# LLM 和规则共用的分类。规则里可以写别的类别，这里只是推荐集合。
CATEGORIES = ["导师/课题组", "求职/HR", "学校行政", "账单/验证码", "订阅/通知", "活动", "其他"]


class Folder(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str
    path: str
    type: str = "folder"
    account_id: str | None = Field(default=None, alias="accountId")
    account_name: str | None = None
    total: int = Field(default=0, alias="totalMessages")
    unread: int = Field(default=0, alias="unreadMessages")


class MessageHeader(BaseModel):
    """getRecentMessages 返回的一行，外加我们补上的账号信息。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    thread_id: str | None = Field(default=None, alias="threadId")
    subject: str = ""
    author: str = ""
    recipients: str = ""
    cc_list: str = Field(default="", alias="ccList")
    date: datetime | None = None
    folder: str = ""
    folder_path: str = Field(alias="folderPath")
    read: bool = False
    flagged: bool = False
    tags: list[str] = Field(default_factory=list)
    preview: str = ""
    account_id: str | None = None
    account_name: str | None = None

    @field_validator("thread_id", mode="before")
    @classmethod
    def _thread_to_str(cls, value: Any) -> str | None:
        # 扩展返回的是数字（文件夹内编号），存成字符串统一处理
        return None if value is None else str(value)

    @field_validator("subject", "author", "recipients", "cc_list", "preview", "folder", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        return "" if value is None else value

    @property
    def sender_name(self) -> str:
        name, addr = parseaddr(self.author)
        return name or addr

    @property
    def sender_email(self) -> str:
        return parseaddr(self.author)[1].lower()

    @property
    def sender_domain(self) -> str:
        email = self.sender_email
        return email.rsplit("@", 1)[-1] if "@" in email else ""


class MessageBody(BaseModel):
    """getMessages 返回的一项。读取失败时 error 有值、body 为空。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str | None = None
    message_id: str | None = Field(default=None, alias="messageId")
    folder_path: str | None = Field(default=None, alias="folderPath")
    subject: str = ""
    author: str = ""
    date: datetime | None = None
    body: str = ""
    body_is_html: bool = Field(default=False, alias="bodyIsHtml")
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None

    @field_validator("body", "subject", "author", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        return "" if value is None else value

    @property
    def key(self) -> str | None:
        return self.message_id or self.id


class Decision(BaseModel):
    """对一封邮件的判断：谁、什么事、要不要管、多急、几号前。"""

    who: str = ""
    what: str = ""
    needs_action: NeedsAction = "unsure"
    urgency: Urgency = "normal"
    deadline: str | None = None
    suggested_action: str = ""
    category: str = "其他"
    confidence: float = 0.5
    decided_by: DecidedBy = "fallback"
    rule_name: str | None = None
    # 规则可以强制推送方式；None 表示按默认策略（要管或拿不准 → 即时，其余 → 汇总）
    notify: NotifyMode | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.5
        return min(1.0, max(0.0, number))

    @property
    def notify_mode(self) -> NotifyMode:
        if self.notify:
            return self.notify
        return "instant" if self.needs_action in ("yes", "unsure") else "digest"
