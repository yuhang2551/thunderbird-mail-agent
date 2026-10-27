"""把判断结果渲染成推送文本。只做纯文本，飞书 / Lark 的文本消息和终端都能直接显示。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .models import Decision, MessageHeader

LABEL = {"yes": "需要处理", "unsure": "可能要管", "no": "知道就行"}
URGENCY = {"high": "紧急", "normal": "", "low": "不急"}


def _tz(timezone_name: str | None):
    return ZoneInfo(timezone_name) if timezone_name else datetime.now().astimezone().tzinfo


def fmt_time(value: datetime | str | None, timezone_name: str | None = None) -> str:
    if not value:
        return "时间未知"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_tz(timezone_name)).strftime("%m-%d %H:%M")


def render_instant(header: MessageHeader, decision: Decision, timezone_name: str | None = None) -> str:
    head = f"📬 {LABEL[decision.needs_action]}"
    if decision.urgency == "high":
        head += " · 紧急"
    if header.account_name:
        head += f" · {header.account_name}"
    lines = [head, f"谁：{decision.who or header.sender_name or header.sender_email}", f"事：{decision.what or header.subject}"]
    if decision.deadline:
        lines.append(f"期限：{decision.deadline}")
    if decision.suggested_action:
        lines.append(f"建议：{decision.suggested_action}")
    lines.append(f"主题：{header.subject or '（无主题）'} | {fmt_time(header.date, timezone_name)}")
    if decision.decided_by == "fallback":
        lines.append("（没有模型判断，按「拿不准」推送）")
    return "\n".join(lines)


def render_digest(rows: list[Mapping[str, Any]], *, now: datetime | None = None, timezone_name: str | None = None) -> str:
    """rows 是 state.pending_digest() 的结果（sqlite3.Row 或 dict）。"""
    now = now or datetime.now(timezone.utc)
    header = f"📮 邮件汇总 {fmt_time(now, timezone_name)} · 共 {len(rows)} 封"
    if not rows:
        return header + "\n没有新邮件。"

    groups: dict[str, list[Mapping[str, Any]]] = {"yes": [], "unsure": [], "no": []}
    for row in rows:
        groups.setdefault(row["needs_action"] or "unsure", groups["unsure"]).append(row)

    lines = [header]
    for key in ("yes", "unsure"):
        if groups[key]:
            lines.append(f"\n{LABEL[key]}（{len(groups[key])}）")
            for row in groups[key]:
                lines.append(_digest_line(row, timezone_name, with_deadline=True))

    informational = [r for r in groups["no"] if r["decided_by"] != "rule"]
    ignored = [r for r in groups["no"] if r["decided_by"] == "rule"]
    if informational:
        lines.append(f"\n知道就行（{len(informational)}）")
        for row in informational:
            lines.append(_digest_line(row, timezone_name))
    if ignored:
        counts: dict[str, int] = {}
        for row in ignored:
            counts[row["category"] or "其他"] = counts.get(row["category"] or "其他", 0) + 1
        lines.append("\n已忽略：" + "，".join(f"{cat} {n}" for cat, n in counts.items()))
    return "\n".join(lines)


def _digest_line(row: Mapping[str, Any], timezone_name: str | None, *, with_deadline: bool = False) -> str:
    who = row["who"] or row["sender_name"] or row["sender_email"] or "未知发件人"
    what = row["what"] or row["subject"] or "（无主题）"
    line = f"• {who}：{what}"
    if with_deadline and row["deadline"]:
        line += f"（期限 {row['deadline']}）"
    account = row["account"]
    stamp = fmt_time(row["received_at"], timezone_name)
    line += f" [{account} {stamp}]" if account else f" [{stamp}]"
    return line
