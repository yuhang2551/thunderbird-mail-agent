"""命令行入口：mail-monitor doctor | init | run | digest | rules | stats"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import typer

from . import __version__
from .config import Settings, load_settings
from .mailbox import Mailbox, MailboxError
from .models import MessageHeader
from .notify import NotifyError, build_notifier
from .rules import RuleSet
from .state import State

app = typer.Typer(
    help="邮箱监控 Agent：盯着 Thunderbird 里的邮箱，判断新邮件要不要管，推送到飞书 / Lark。",
    no_args_is_help=True,
    add_completion=False,
)


def _settings() -> Settings:
    return load_settings()


@app.callback()
def main(
    env: Path | None = typer.Option(None, "--env", help="配置文件路径，默认 ~/.mail-monitor/.env"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="打印调试日志"),
) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if env:
        os.environ["MAIL_MONITOR_ENV"] = str(env)


@app.command()
def version() -> None:
    typer.echo(f"mail-monitor {__version__}")


@app.command()
def doctor() -> None:
    """自检：能不能连上 Thunderbird、有哪些收件箱、推送和模型有没有配好。不改任何东西。"""
    settings = _settings()
    ok = True
    typer.echo(f"配置：{os.environ.get('MAIL_MONITOR_ENV', settings.home / '.env')}")
    typer.echo(f"邮件层命令：{' '.join(settings.mailbox_command)}")

    async def check_mailbox() -> None:
        async with Mailbox(settings.mailbox_command) as mailbox:
            tools = await mailbox.list_tools()
            typer.echo(f"✅ 已连上，扩展提供 {len(tools)} 个工具")
            missing = [t for t in ("listAccounts", "listFolders", "getRecentMessages", "getMessages") if t not in tools]
            if missing:
                typer.echo(f"❌ 缺少必需工具：{', '.join(missing)}（在扩展的 Tool Access 里打开）")
            inboxes = await mailbox.list_inboxes(settings.accounts)
            for inbox in inboxes:
                typer.echo(f"   📥 {inbox.account_name} / {inbox.name}：共 {inbox.total} 封，未读 {inbox.unread}")
            if not inboxes:
                typer.echo("❌ 没有找到收件箱")

    try:
        asyncio.run(check_mailbox())
    except (MailboxError, OSError) as exc:
        ok = False
        typer.echo(f"❌ 连不上 Thunderbird：{exc}")
        typer.echo("   请确认：Thunderbird 开着；扩展已安装；~/thunderbird-mcp/mcp-bridge.cjs 存在")

    rules_path = settings.resolved_rules_path
    try:
        ruleset = RuleSet.load(rules_path)
        typer.echo(f"✅ 规则：{len(ruleset.rules)} 条（{rules_path or '内置默认规则'}）")
    except Exception as exc:  # noqa: BLE001 - 把规则文件的任何错误都展示给用户
        ok = False
        typer.echo(f"❌ 规则文件有问题：{exc}")

    if settings.llm_enabled:
        typer.echo(f"✅ 模型：{settings.llm_model} @ {settings.llm_base_url}")
    else:
        typer.echo("⚠️  没有 LLM key（DEEPSEEK_API_KEY）：规则没覆盖的邮件会按「拿不准」全部推送")

    try:
        notifier = build_notifier(settings)
        typer.echo(f"✅ 推送：{notifier.name}")
    except NotifyError as exc:
        ok = False
        typer.echo(f"❌ 推送：{exc}")

    typer.echo(f"数据库：{settings.resolved_db_path}")
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def init(days: int = typer.Option(7, help="把最近几天的邮件登记为已见")) -> None:
    """首次运行：把现有邮件登记为已见，不判断不推送。之后 run 只处理新来的。"""
    from .pipeline import init_seen

    settings = _settings()
    report = asyncio.run(init_seen(settings, days_back=days))
    typer.echo(f"已登记 {report.new} 封（收件箱 {report.inboxes} 个，共 {report.fetched} 封）")
    for error in report.errors:
        typer.echo(f"⚠️  {error}")


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="只判断、打印，不记录、不推送"),
    days: int | None = typer.Option(None, help="覆盖 days_back"),
) -> None:
    """巡检一次：拉新邮件、判断、推送。配合 launchd / cron 每几分钟跑一次。"""
    from .pipeline import run_once

    settings = _settings()
    if days:
        settings = settings.model_copy(update={"days_back": days})
    report = asyncio.run(run_once(settings, dry_run=dry_run))
    typer.echo(report.summary())
    for error in report.errors:
        typer.echo(f"⚠️  {error}")
    raise typer.Exit(code=1 if report.errors and report.new == 0 and report.fetched == 0 else 0)


@app.command()
def digest() -> None:
    """把攒着的邮件合成一条汇总推送出去。配合 launchd 早晚各跑一次。"""
    from .pipeline import send_digest

    settings = _settings()
    count = asyncio.run(send_digest(settings))
    typer.echo("没有待汇总的邮件" if count == 0 else f"已汇总 {count} 封")


@app.command("rules")
def rules_check(
    sender: str = typer.Option(..., "--from", help='发件人，例如 "Prof. X <x@example.edu>"'),
    subject: str = typer.Option("", help="主题"),
    account: str = typer.Option("", help="账号名"),
) -> None:
    """测一下某个发件人 + 主题会命中哪条规则。"""
    settings = _settings()
    ruleset = RuleSet.load(settings.resolved_rules_path)
    header = MessageHeader(id="test", folderPath="test", author=sender, subject=subject, account_name=account or None)
    rule = ruleset.match(header)
    if not rule:
        typer.echo("没有命中任何规则 → 交给模型判断（没有模型时按「拿不准」推送）")
        return
    typer.echo(f"命中规则：{rule.name}")
    typer.echo(f"  then: {rule.then.model_dump(exclude_none=True)}")
    if not rule.then.llm:
        decision = rule.decide(header)
        typer.echo(f"  结果：{decision.needs_action} / {decision.urgency} / 推送方式 {decision.notify_mode}")


@app.command()
def stats() -> None:
    """看看数据库里的统计。"""
    settings = _settings()
    state = State(settings.resolved_db_path)
    for key, value in state.stats().items():
        typer.echo(f"{key}: {value}")


@app.command("lark-chats")
def lark_chats(email: str | None = typer.Option(None, help="顺便按这个邮箱查你的 open_id（需要 contact:user.id:readonly 权限）")) -> None:
    """用应用机器人的凭证列出它所在的群，拿到 chat_id 填进 LARK_RECEIVE_ID。"""
    from .notify import build_lark_app

    settings = _settings()

    async def go() -> None:
        notifier = build_lark_app(settings)
        try:
            chats = await notifier.list_chats()
            if not chats:
                typer.echo("机器人还没有加入任何群。在 Lark 里建一个群，把这个应用的机器人加进去，再运行一次。")
            for chat in chats:
                typer.echo(f"群：{chat['name'] or '（未命名）'}  chat_id={chat['chat_id']}")
            if chats:
                typer.echo("\n写进 ~/.mail-monitor/.env：\nMAIL_MONITOR_NOTIFY=lark_app\nLARK_RECEIVE_ID_TYPE=chat_id\nLARK_RECEIVE_ID=<上面的 chat_id>")
            if email:
                open_id = await notifier.lookup_open_id(email)
                if open_id:
                    typer.echo(f"\n{email} 的 open_id={open_id}（想私聊推送就用 LARK_RECEIVE_ID_TYPE=open_id）")
                else:
                    typer.echo(f"\n没查到 {email} 对应的用户（检查邮箱是不是这个租户里的，以及权限有没有开）")
        finally:
            await notifier.aclose()

    try:
        asyncio.run(go())
    except NotifyError as exc:
        typer.echo(f"❌ {exc}")
        raise typer.Exit(code=1)


@app.command("notify-test")
def notify_test(text: str = typer.Argument("邮箱监控 Agent 测试消息 ✅", help="要发的内容")) -> None:
    """用当前配置的推送后端发一条测试消息。"""
    settings = _settings()

    async def go() -> None:
        notifier = build_notifier(settings)
        try:
            await notifier.send(text)
        finally:
            close = getattr(notifier, "aclose", None)
            if close:
                await close()

    try:
        asyncio.run(go())
        typer.echo(f"✅ 已通过 {settings.notify_backend} 发送")
    except NotifyError as exc:
        typer.echo(f"❌ {exc}")
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
