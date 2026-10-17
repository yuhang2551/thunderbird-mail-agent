"""流水线：拉新邮件 → 去重 → 规则 → 取记忆 → 判断 → （可选）打标签 → 推送 → 记录（含更新发件人记忆）。

一次 run_once 就是一次完整的巡检。调度交给 launchd / cron，每几分钟跑一次。
这里故意写成一条直线，没有上框架：流程是线性的，状态就是一个 RunReport。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .classify import Classifier, FallbackClassifier, LLMClassifier
from .config import Settings
from .llm import LLMClient
from .mailbox import Mailbox, MailboxError
from .memory import recall
from .models import Decision, MessageHeader
from .notify import ConsoleNotifier, Notifier, NotifyError, build_notifier
from .render import render_digest, render_instant
from .rules import Rule, RuleSet
from .state import State

log = logging.getLogger(__name__)

# 模型猜的发件人身份至少要这么有把握才写进记忆
RELATION_MIN_CONFIDENCE = 0.6


@dataclass
class RunReport:
    inboxes: int = 0
    fetched: int = 0
    new: int = 0
    by_rule: int = 0
    by_llm: int = 0
    by_fallback: int = 0
    pushed: int = 0
    digest_pending: int = 0
    ignored: int = 0
    tagged: int = 0
    relations: int = 0  # 这次新记住（或更新）了几个发件人的身份
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"收件箱 {self.inboxes} 个，拉到 {self.fetched} 封，新邮件 {self.new} 封"
            f"（规则 {self.by_rule}，模型 {self.by_llm}，保底 {self.by_fallback}）；"
            f"即时推送 {self.pushed}，待汇总 {self.digest_pending}，忽略 {self.ignored}"
            + (f"，打标签 {self.tagged}" if self.tagged else "")
            + (f"，记住发件人身份 {self.relations} 个" if self.relations else "")
            + (f"；错误 {len(self.errors)} 个" if self.errors else "")
        )


def make_classifier(settings: Settings) -> Classifier:
    if settings.llm_enabled:
        client = LLMClient(
            api_key=settings.llm_api_key or "",
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            extra_body=settings.resolved_llm_extra_body,
        )
        return LLMClassifier(client, timezone=settings.timezone, body_chars=settings.llm_body_chars, profile=settings.profile)
    log.warning("没有配置 LLM key，所有规则没覆盖的邮件都会按「拿不准」推送")
    return FallbackClassifier()


async def fetch_new_headers(mailbox: Mailbox, settings: Settings, state: State, report: RunReport) -> list[MessageHeader]:
    inboxes = await mailbox.list_inboxes(settings.accounts)
    report.inboxes = len(inboxes)
    if not inboxes:
        report.errors.append("没有找到任何收件箱（账号过滤是不是写错了？）")
        return []
    headers: list[MessageHeader] = []
    for inbox in inboxes:
        try:
            rows = await mailbox.recent(inbox, days_back=settings.days_back, max_results=settings.max_results)
        except MailboxError as exc:
            report.errors.append(f"读取 {inbox.account_name}/{inbox.name} 失败：{exc}")
            continue
        headers.extend(rows)
    # 同一封邮件可能出现在多个账号的收件箱（抄送给自己），按 id 去重
    unique: dict[str, MessageHeader] = {}
    for header in headers:
        unique.setdefault(header.id, header)
    report.fetched = len(unique)
    seen = state.seen(unique.keys())
    new = [h for h in unique.values() if h.id not in seen]
    new.sort(key=lambda h: h.date or datetime.min.replace(tzinfo=timezone.utc))
    report.new = len(new)
    return new


async def run_once(
    settings: Settings,
    *,
    dry_run: bool = False,
    notifier: Notifier | None = None,
    classifier: Classifier | None = None,
    rules: RuleSet | None = None,
    state: State | None = None,
) -> RunReport:
    report = RunReport()
    rules = rules or RuleSet.load(settings.resolved_rules_path)
    # dry-run 用内存数据库：不记录、不推送，代价是没有记忆可参考
    state = state or State(":memory:" if dry_run else settings.resolved_db_path)
    notifier = notifier or (ConsoleNotifier() if dry_run else build_notifier(settings))
    classifier = classifier or make_classifier(settings)
    run_id = state.start_run()

    try:
        async with Mailbox(settings.mailbox_command) as mailbox:
            new = await fetch_new_headers(mailbox, settings, state, report)

            # 先过规则，分成"规则直接定性"和"要读正文交给模型"两堆
            decided: list[tuple[MessageHeader, Decision, Rule | None]] = []
            need_llm: list[tuple[MessageHeader, Rule | None]] = []
            for header in new:
                rule = rules.match(header)
                if rule and not rule.then.llm:
                    decided.append((header, rule.decide(header), rule))
                else:
                    need_llm.append((header, rule))

            bodies = {}
            if need_llm and settings.llm_enabled:
                try:
                    bodies = await mailbox.fetch_bodies([(h.id, h.folder_path) for h, _ in need_llm])
                except MailboxError as exc:
                    report.errors.append(f"读取正文失败，改用预览判断：{exc}")
            for header, rule in need_llm:
                body = bodies.get(header.id)
                text = body.body if body and not body.error else None
                memory = recall(state, header)
                decision = await classifier.classify(header, text, rule.hints() if rule else None, memory)
                if rule:
                    decision = rule.apply_overrides(decision)
                decided.append((header, decision, rule))

            decided.sort(key=lambda item: item[0].date or datetime.min.replace(tzinfo=timezone.utc))
            for header, decision, rule in decided:
                await _settle(header, decision, rule, settings, state, mailbox, notifier, report)
    except MailboxError as exc:
        report.errors.append(f"连不上 Thunderbird：{exc}")
    finally:
        state.finish_run(run_id, fetched=report.fetched, new=report.new, pushed=report.pushed, errors=report.errors)
    return report


def _remember_sender(state: State, header: MessageHeader, decision: Decision, rule: Rule | None) -> bool:
    """更新发件人记忆：规则写明了"这是谁"就按规则记；否则模型猜得够有把握也记下来。"""
    email = header.sender_email
    if not email:
        return False
    if rule and rule.then.who:
        return state.set_sender_relation(email, rule.then.who, source="rule")
    if decision.decided_by == "llm" and decision.relation and decision.confidence >= RELATION_MIN_CONFIDENCE:
        return state.set_sender_relation(email, decision.relation, source="llm")
    return False


async def _settle(
    header: MessageHeader,
    decision: Decision,
    rule: Rule | None,
    settings: Settings,
    state: State,
    mailbox: Mailbox,
    notifier: Notifier,
    report: RunReport,
) -> None:
    report.by_rule += decision.decided_by == "rule"
    report.by_llm += decision.decided_by == "llm"
    report.by_fallback += decision.decided_by == "fallback"
    state.touch_sender(header)
    report.relations += _remember_sender(state, header, decision, rule)

    # 行动：默认只读。打标签要显式打开，而且只给"需要处理"的
    if settings.action_tag and decision.needs_action == "yes":
        try:
            await mailbox.add_tags(header.id, header.folder_path, [settings.action_tag_key])
            report.tagged += 1
        except MailboxError as exc:
            report.errors.append(f"打标签失败（{header.subject[:30]}）：{exc}")

    mode = decision.notify_mode
    pushed = False
    if mode == "instant":
        try:
            await notifier.send(render_instant(header, decision, settings.timezone))
            pushed = True
            report.pushed += 1
        except NotifyError as exc:
            # 推送失败就转成待汇总，下次 digest 还能带上，不会丢
            report.errors.append(f"推送失败，转入汇总：{exc}")
            mode = "digest"
    if mode == "digest":
        report.digest_pending += 1
    elif mode == "never":
        report.ignored += 1
    state.record(header, decision, notify_mode=mode, pushed=pushed)


async def send_digest(settings: Settings, *, notifier: Notifier | None = None, state: State | None = None) -> int:
    """把攒着的邮件合成一条发出去。返回这次汇总了几封。"""
    state = state or State(settings.resolved_db_path)
    notifier = notifier or build_notifier(settings)
    rows = state.pending_digest()
    if not rows:
        return 0
    await notifier.send(render_digest(rows, timezone_name=settings.timezone))
    state.mark_digested([row["id"] for row in rows])
    return len(rows)


async def init_seen(settings: Settings, *, days_back: int | None = None, state: State | None = None) -> RunReport:
    """首次运行：把现有邮件登记为已见，不判断不推送，避免一上来推几十条旧邮件。"""
    report = RunReport()
    state = state or State(settings.resolved_db_path)
    if days_back:
        settings = settings.model_copy(update={"days_back": days_back})
    async with Mailbox(settings.mailbox_command) as mailbox:
        new = await fetch_new_headers(mailbox, settings, state, report)
        state.mark_seen(new)
    return report
