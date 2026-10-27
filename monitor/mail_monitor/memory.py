"""记忆：判断一封新邮件之前，从数据库里捞出"这个发件人是谁、之前来过什么、同一话题之前说了什么"。

这是 Agent 的"记忆"环节：把 SQLite 里的历史整理成一小段文字喂给模型，模型就能看出"这封是在催上次那件事"、
"这是导师不是陌生人"。记忆只是参考，要不要管仍以这封邮件自己的内容为准（见 classify.SYSTEM_PROMPT）。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .models import MessageHeader
from .render import fmt_time
from .state import State

LABEL = {"yes": "需要处理", "no": "知道就行", "unsure": "拿不准"}
SOURCE_LABEL = {"user": "你设定", "rule": "规则设定", "llm": "模型判断"}


@dataclass
class HistoryItem:
    id: str
    received_at: str | None
    who: str
    what: str
    needs_action: str | None
    subject: str
    decided_by: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "HistoryItem":
        return cls(
            id=row["id"], received_at=row["received_at"], who=row["who"] or "", what=row["what"] or "",
            needs_action=row["needs_action"], subject=row["subject"] or "", decided_by=row["decided_by"],
        )

    def line(self, timezone_name: str | None = None) -> str:
        stamp = fmt_time(self.received_at, timezone_name)
        if self.decided_by == "init" or not self.needs_action:
            return f"{stamp} {self.subject or '（无主题）'}（登记时未判断）"
        label = LABEL.get(self.needs_action, self.needs_action)
        summary = self.what or self.subject or "（无主题）"
        prefix = f"{self.who}：" if self.who else ""
        return f"{stamp} {prefix}{summary}（{label}）"


@dataclass
class SenderMemo:
    email: str
    name: str | None
    relation: str | None
    relation_source: str | None
    total: int  # 之前一共几封（含首次登记的）
    needs_action: int  # 其中几封需要处理
    recent: list[HistoryItem] = field(default_factory=list)


@dataclass
class Memory:
    sender: SenderMemo | None = None
    thread: list[HistoryItem] = field(default_factory=list)

    @property
    def relation(self) -> str | None:
        return self.sender.relation if self.sender else None

    def is_empty(self) -> bool:
        sender_blank = self.sender is None or (not self.sender.relation and self.sender.total == 0)
        return sender_blank and not self.thread

    def render(self, timezone_name: str | None = None) -> str:
        """给模型看的文字。空记忆返回空字符串。"""
        if self.is_empty():
            return ""
        lines = ["记忆（我们之前的记录，仅供参考）："]
        sender = self.sender
        if sender and (sender.relation or sender.total):
            bits = []
            if sender.relation:
                bits.append(f"身份={sender.relation}（{SOURCE_LABEL.get(sender.relation_source or '', '来源不明')}）")
            if sender.total:
                bits.append(f"之前 {sender.total} 封，其中 {sender.needs_action} 封需要处理")
            lines.append(f"- 发件人 {sender.email}：" + "；".join(bits))
            lines.extend("  · " + item.line(timezone_name) for item in sender.recent)
        if self.thread:
            lines.append("- 同一话题之前的邮件：")
            lines.extend("  · " + item.line(timezone_name) for item in self.thread)
        return "\n".join(lines)


def recall(state: State, header: MessageHeader, *, limit: int = 3) -> Memory:
    """从数据库里取出和这封邮件有关的记忆。"""
    memory = Memory()
    thread_rows = state.thread_history(header, limit=limit)
    memory.thread = [HistoryItem.from_row(row) for row in reversed(thread_rows)]  # 按时间正序
    thread_ids = {item.id for item in memory.thread}

    email = header.sender_email
    if email:
        row = state.sender(email)
        total, needs_action = state.sender_counts(email, exclude_id=header.id)
        if row is not None or total:
            recent = [HistoryItem.from_row(r) for r in reversed(state.sender_history(email, limit=limit, exclude_id=header.id))]
            memory.sender = SenderMemo(
                email=email,
                name=row["name"] if row else None,
                relation=row["relation"] if row else None,
                relation_source=row["relation_source"] if row else None,
                total=total,
                needs_action=needs_action,
                recent=[item for item in recent if item.id not in thread_ids],  # 同一话题里已经列过的不重复
            )
    return memory
