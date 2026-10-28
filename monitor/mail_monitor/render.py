"""把判断结果渲染成推送：一份纯文本（终端、飞书 / Lark 文本消息直接显示），一份卡片用的标题和正文（notify-hub）。"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .models import Decision, MessageHeader
from .notify import Push

LABEL = {"yes": "需要处理", "unsure": "可能要管", "no": "知道就行"}
MARK = {"yes": "🔴", "unsure": "🟡", "no": "⚪"}
URGENCY = {"high": "紧急", "normal": "", "low": "不急"}

# 汇总要在手机上一眼扫完：一封最多两行。宽度按中文 2、英文 1 算，手机上一行大约 42
ITEM_WIDTH = 84
WHO_WIDTH = 26
FYI_MAX = 12  # 「知道就行」最多列几行，再多只写还剩几封
_PAREN = re.compile(r"\s*[（(][^（）()]*[）)]\s*")
_CLAUSE_END = re.compile(r"(?<=[，；。！？])|(?<=[,;.!?])(?=\s)")  # 英文标点后面要有空格才算断句，1,250 这样的数字不拆
_BRAND = {"gmail": "Gmail", "googlemail": "Gmail", "outlook": "Outlook", "hotmail": "Outlook", "live": "Outlook", "icloud": "iCloud", "me": "iCloud", "qq": "QQ"}


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
    """汇总（默认每天 8、12、18 点各发一次）。卡片标题写几封、有没有要处理的，手机通知里就看得到；正文是分好组的列表；按普通级别发。"""
    return Push(
        text=render_digest(rows, now=now, timezone_name=timezone_name),
        title=f"邮件汇总 · {_overview(rows)}",
        body="\n".join(_digest_groups(rows, now, timezone_name)).strip() or "没有新邮件。",
    )


def render_digest(rows: list[Mapping[str, Any]], *, now: datetime | None = None, timezone_name: str | None = None) -> str:
    """rows 是 state.pending_digest() 的结果（sqlite3.Row 或 dict）。"""
    now = now or datetime.now(timezone.utc)
    header = f"📮 邮件汇总 {fmt_time(now, timezone_name)} · {_overview(rows)}"
    if not rows:
        return header + "\n没有新邮件。"
    return "\n".join([header, *_digest_groups(rows, now, timezone_name)])


def _need(row: Mapping[str, Any]) -> str:
    return row["needs_action"] if row["needs_action"] in LABEL else "unsure"


def _overview(rows: list[Mapping[str, Any]]) -> str:
    """「11 封，都不用处理」「5 封，1 封要处理、2 封可能要管」"""
    if not rows:
        return "0 封"
    yes = sum(1 for row in rows if _need(row) == "yes")
    unsure = sum(1 for row in rows if _need(row) == "unsure")
    parts = []
    if yes:
        parts.append(f"{yes} 封要处理")
    if unsure:
        parts.append(f"{unsure} 封可能要管")
    return f"{len(rows)} 封，" + ("、".join(parts) or "都不用处理")


def _digest_groups(rows: list[Mapping[str, Any]], now: datetime | None, timezone_name: str | None) -> list[str]:
    """按要不要管分组，每组一个小标题，组和组之间空一行。要管的每封带期限、账号和时间；知道就行的同一个地址合成一行，最多列 FYI_MAX 行。"""
    now = now or datetime.now(timezone.utc)
    groups: dict[str, list[Mapping[str, Any]]] = {"yes": [], "unsure": [], "no": []}
    for row in rows:
        groups[_need(row)].append(row)

    lines: list[str] = []
    for key in ("yes", "unsure"):
        if groups[key]:
            lines.append(f"\n{MARK[key]} {LABEL[key]}（{len(groups[key])}）")
            for row in groups[key]:
                lines.append(_item(short_who(_who(row)), _what(row)))
                lines.append("　" + _meta(row, now, timezone_name))

    informational = [r for r in groups["no"] if r["decided_by"] != "rule"]
    ignored = [r for r in groups["no"] if r["decided_by"] == "rule"]
    if informational:
        lines.append(f"\n{MARK['no']} {LABEL['no']}（{len(informational)}）")
        lines.extend(_fyi_lines(informational))
    if ignored:
        counts: dict[str, int] = {}
        for row in ignored:
            counts[row["category"] or "其他"] = counts.get(row["category"] or "其他", 0) + 1
        lines.append("\n🔕 已忽略：" + "，".join(f"{cat} {n}" for cat, n in counts.items()))
    return lines


def _fyi_lines(rows: list[Mapping[str, Any]]) -> list[str]:
    by_sender: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_sender.setdefault((row["sender_email"] or "").lower() or row["id"], []).append(row)
    senders = list(by_sender.values())
    lines = []
    for same in senders[:FYI_MAX]:
        who = short_who(_who(same[-1])) + (f" ×{len(same)}" if len(same) > 1 else "")
        lines.append(_item(who, _what(same[-1])))  # 合并的显示最新一封
    rest = sum(len(same) for same in senders[FYI_MAX:])
    if rest:
        lines.append(f"　……还有 {rest} 封")
    return lines


def _who(row: Mapping[str, Any]) -> str:
    return row["who"] or row["sender_name"] or row["sender_email"] or "未知发件人"


def _what(row: Mapping[str, Any]) -> str:
    return row["what"] or row["subject"] or "（无主题）"


def _item(who: str, what: str) -> str:
    prefix = f"• {who}："
    return prefix + short_what(what, ITEM_WIDTH - text_width(prefix))


def _meta(row: Mapping[str, Any], now: datetime, timezone_name: str | None) -> str:
    """要管的那几封的第二行：「期限 10-29 · Gmail 09:12」。今天收的只写钟点。"""
    parts = []
    if row["urgency"] == "high":
        parts.append("紧急")
    if row["deadline"]:
        deadline = str(row["deadline"])
        parts.append("期限 " + (deadline[5:] if deadline[:4] == str(now.year) else deadline))
    received = fmt_time(row["received_at"], timezone_name)
    if received[:5] == fmt_time(now, timezone_name)[:5]:
        received = received[6:]
    parts.append(" ".join(x for x in (short_account(row["account"]), received) if x))
    return " · ".join(parts)


def text_width(text: str) -> int:
    """手机上占多宽：中文、全角符号、emoji 算 2，其余算 1。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _cut(text: str, width: int) -> str:
    """截到 width 以内并加「…」；截在英文单词中间就退到前一个空格。"""
    if text_width(text) <= width:
        return text
    used, end = 0, 0
    for end, ch in enumerate(text):
        used += text_width(ch)
        if used > width - 1:  # 留一格给 …
            break
    head = text[:end]
    in_word = head[-1:].isalnum() or (head[-1:] in ",." and head[-2:-1].isdigit())
    if in_word and head[-1:].isascii() and text[end].isascii() and text[end].isalnum():
        before, space, _ = head.rpartition(" ")
        if space and text_width(before) >= width // 2:
            head = before
    return head.rstrip(" ，,、；;：:") + "…"


def _drop_parens(text: str) -> str:
    """去掉括号里的补充说明。两边都是英文或数字时留一个空格，免得「2026-11-03（周二）11:30」粘成一串。"""

    def gap(match: re.Match[str]) -> str:
        before, after = text[match.start() - 1 : match.start()], text[match.end() : match.end() + 1]
        return " " if before.isascii() and before.isalnum() and after.isascii() and after.isalnum() else ""

    return " ".join(_PAREN.sub(gap, text).split())


def short_who(who: str, width: int = WHO_WIDTH) -> str:
    """发件人只留身份：「MBZUAI Nexus（学校 AI 学术活动通知）」→「MBZUAI Nexus」。"""
    text = _drop_parens(who) or " ".join(who.split())
    return _cut(text, width)


def short_what(what: str, width: int) -> str:
    """「什么事」放得下就原样；放不下先去掉括号里的补充，再按逗号、句号一段段往里装，第一段都装不下才硬截。"""
    text = " ".join(what.split())
    if text_width(text) > width:
        text = _drop_parens(text)
    if text_width(text) <= width:
        return text.rstrip("。")
    kept = ""
    for clause in _CLAUSE_END.split(text):
        if text_width((kept + clause).rstrip("，,；;。！？!? ")) > width:
            break
        kept += clause
    return kept.rstrip("，,；;。！？!? ") if kept else _cut(text, width)


def short_account(account: str | None) -> str:
    """账号名是邮箱地址时只留邮箱服务：yuhangl826@gmail.com → Gmail，x@mbzuai.ac.ae → MBZUAI。"""
    if not account or "@" not in account:
        return account or ""
    label = account.rsplit("@", 1)[1].split(".")[0].lower()
    return _BRAND.get(label) or (label.upper() if len(label) <= 6 else label)
