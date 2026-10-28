"""把判断结果渲染成推送：一份纯文本（终端、飞书 / Lark 文本消息直接显示），一份卡片用的标题和正文（notify-hub）。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .models import Decision, MessageHeader
from .notify import Push

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


def instant_push(header: MessageHeader, decision: Decision, timezone_name: str | None = None, *, urgent: bool = False) -> Push:
    """即时推送。卡片标题是「谁：什么事」，手机通知里一眼就看到；正文是其余几行。"""
    head = LABEL[decision.needs_action]
    if decision.urgency == "high":
        head += " · 紧急"
    if header.account_name:
        head += f" · {header.account_name}"
    who = decision.who or header.sender_name or header.sender_email or "未知发件人"
    what = decision.what or header.subject or "（无主题）"
    details = []
    if decision.deadline:
        details.append(f"期限：{decision.deadline}")
    if decision.suggested_action:
        details.append(f"建议：{decision.suggested_action}")
    details.append(f"主题：{header.subject or '（无主题）'} | {fmt_time(header.date, timezone_name)}")
    if decision.decided_by == "fallback":
        details.append("（没有模型判断，按「拿不准」推送）")
    # 模型写的摘要短，直接放进标题；规则和保底的「什么事」是主题加正文开头，标题只放主题，完整的写在正文里
    brief = what if decision.decided_by == "llm" else header.subject or "（无主题）"
    return Push(
        text="\n".join([f"📬 {head}", f"谁：{who}", f"事：{what}", *details]),
        title=f"{who}：{brief}",
        body="\n".join([head, *([f"事：{what}"] if brief != what else []), *details]),
        level="urgent" if urgent else "normal",
    )


def render_instant(header: MessageHeader, decision: Decision, timezone_name: str | None = None) -> str:
    return instant_push(header, decision, timezone_name).text


def digest_push(rows: list[Mapping[str, Any]], *, now: datetime | None = None, timezone_name: str | None = None) -> Push:
    """汇总（launchd 默认每天 8、12、18 点各发一次）。卡片标题是「邮件汇总 · N 封」，正文是分好组的列表；按普通级别发。"""
    return Push(
        text=render_digest(rows, now=now, timezone_name=timezone_name),
        title=f"邮件汇总 · {len(rows)} 封",
        body="\n".join(_digest_groups(rows, timezone_name)).strip() or "没有新邮件。",
    )


def render_digest(rows: list[Mapping[str, Any]], *, now: datetime | None = None, timezone_name: str | None = None) -> str:
    """rows 是 state.pending_digest() 的结果（sqlite3.Row 或 dict）。"""
    now = now or datetime.now(timezone.utc)
    header = f"📮 邮件汇总 {fmt_time(now, timezone_name)} · 共 {len(rows)} 封"
    if not rows:
        return header + "\n没有新邮件。"
    return "\n".join([header, *_digest_groups(rows, timezone_name)])


def _digest_groups(rows: list[Mapping[str, Any]], timezone_name: str | None) -> list[str]:
    """按要不要管分组，每组一个小标题，组和组之间空一行。"""
    groups: dict[str, list[Mapping[str, Any]]] = {"yes": [], "unsure": [], "no": []}
    for row in rows:
        groups.setdefault(row["needs_action"] or "unsure", groups["unsure"]).append(row)

    lines: list[str] = []
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
    return lines


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
