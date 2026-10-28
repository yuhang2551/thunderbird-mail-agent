"""命令行入口：mail-monitor doctor | init | run | digest | rules | stats | senders | sender-set | review | eval | lark-chats | notify-test"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import typer

from . import __version__
from .claude_cli import doctor_lines as claude_doctor_lines
from .config import RETIRED_MODELS, Settings, load_settings
from .mailbox import Mailbox, MailboxError
from .models import MessageHeader
from .memory import SOURCE_LABEL
from .notify import NotifyError, NotifyHubNotifier, Push, build_notifier
from .render import LABEL, fmt_time
from .rules import RuleSet
from .state import State

app = typer.Typer(
    help="邮箱监控 Agent：盯着 Thunderbird 里的邮箱，判断新邮件要不要管，推送到飞书 / Lark。",
    no_args_is_help=True,
    add_completion=False,
)


def _settings() -> Settings:
    return load_settings()


def _stamp(settings: Settings) -> str:
    """每次运行输出的开头写上时间：定时任务的日志攒了一周，也分得清哪行是哪次跑的。"""
    return fmt_time(datetime.now(timezone.utc), settings.timezone)


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

    if settings.llm_backend == "claude":
        claude_ok, lines = claude_doctor_lines(settings.claude_bin, settings.claude_model)
        ok = ok and claude_ok
        for line in lines:
            typer.echo(line)
    elif settings.llm_enabled:
        typer.echo(f"✅ 模型：{settings.llm_model} @ {settings.llm_base_url}")
        if settings.llm_model in RETIRED_MODELS and "deepseek.com" in settings.llm_base_url:
            ok = False
            typer.echo(f"❌ DeepSeek 已经停用 {settings.llm_model} 这个模型名，改成 LLM_MODEL={RETIRED_MODELS[settings.llm_model]}")
        if settings.resolved_llm_extra_body:
            typer.echo(f"   请求里额外带上：{json.dumps(settings.resolved_llm_extra_body, ensure_ascii=False)}")
    else:
        typer.echo("⚠️  没有 LLM key（DEEPSEEK_API_KEY），也没开 Claude 订阅版（MAIL_MONITOR_LLM=claude）：规则没覆盖的邮件会按「拿不准」全部推送")
    if settings.profile:
        typer.echo(f"✅ 画像：{settings.profile}")
    else:
        typer.echo("⚠️  没有 MAIL_MONITOR_PROFILE：模型只知道你是「在读研究生，同时在找工作」")

    try:
        notifier = build_notifier(settings)
        if isinstance(notifier, NotifyHubNotifier):
            hub_version = notifier.version()
            typer.echo(f"✅ 推送：notify_hub（{hub_version}，{notifier.binary}）")
            if re.search(r"\b0\.[0-2]\.\d", hub_version):
                typer.echo("⚠️  notify-hub 还是 0.2 版：它自己还有一套免打扰和定时任务。按它 README 里「从 0.2 升级」的步骤升到 0.3")
        else:
            typer.echo(f"✅ 推送：{notifier.name}")
    except NotifyError as exc:
        ok = False
        typer.echo(f"❌ 推送：{exc}")
    if settings.quiet_window:
        typer.echo(f"✅ 免打扰：{settings.quiet_hours}，这段时间只即时推送规则写了 urgency: high 的，其余的进汇总")
    else:
        typer.echo("✅ 免打扰：关（MAIL_MONITOR_QUIET_HOURS=off），要紧的邮件夜里也马上推")

    typer.echo(f"数据库：{settings.resolved_db_path}")
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def init(days: int = typer.Option(7, help="把最近几天的邮件登记为已见")) -> None:
    """首次运行：把现有邮件登记为已见，不判断不推送。之后 run 只处理新来的。"""
    from .pipeline import init_seen

    settings = _settings()
    try:
        report = asyncio.run(init_seen(settings, days_back=days))
    except MailboxError as exc:
        typer.echo(f"❌ 连不上 Thunderbird：{exc}")
        raise typer.Exit(code=1)
    typer.echo(f"已登记 {report.new} 封（收件箱 {report.inboxes} 个，共 {report.fetched} 封）")
    for error in report.errors:
        typer.echo(f"⚠️  {error}")


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="只判断、打印（即时推送的和会进汇总的都打出来），不记录、不推送"),
    days: int | None = typer.Option(None, help="覆盖 days_back"),
) -> None:
    """巡检一次：拉新邮件、判断、推送。配合 launchd / cron 定时跑（默认每小时）。"""
    from .pipeline import run_once

    settings = _settings()
    if days:
        settings = settings.model_copy(update={"days_back": days})
    report = asyncio.run(run_once(settings, dry_run=dry_run))
    typer.echo(f"{_stamp(settings)} {report.summary()}")
    for error in report.errors:
        typer.echo(f"⚠️  {error}")
    raise typer.Exit(code=1 if report.errors and report.new == 0 and report.fetched == 0 else 0)


@app.command()
def digest() -> None:
    """把攒着的邮件合成一条汇总推送出去。配合 launchd 每天 8、12、18 点各跑一次。"""
    from .pipeline import send_digest

    settings = _settings()
    try:
        count = asyncio.run(send_digest(settings))
    except NotifyError as exc:
        typer.echo(f"{_stamp(settings)} ❌ 汇总没推出去，邮件都还攒着，下次汇总再带上：{exc}")
        raise typer.Exit(code=1)
    typer.echo(f"{_stamp(settings)} " + ("没有待汇总的邮件" if count == 0 else f"已汇总 {count} 封"))


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


@app.command()
def senders(limit: int = typer.Option(30, help="最多显示几个")) -> None:
    """看看记住了哪些发件人：是谁、来过几封、身份是怎么定的（你设定 / 规则设定 / 模型判断）。"""
    settings = _settings()
    state = State(settings.resolved_db_path)
    rows = state.list_senders(limit=limit)
    if not rows:
        typer.echo("还没有记住任何发件人（先跑一次 init 或 run）")
        return
    for row in rows:
        if row["relation"]:
            relation = f"{row['relation']}（{SOURCE_LABEL.get(row['relation_source'] or '', '来源不明')}）"
        else:
            relation = "身份未知"
        name = row["name"] or ""
        typer.echo(f"{row['email']}  {name + '  ' if name else ''}{relation}  {row['message_count']} 封，最近 {fmt_time(row['last_seen_at'], settings.timezone)}")
    typer.echo("\n改身份：mail-monitor sender-set 邮箱 身份")


@app.command("sender-set")
def sender_set(
    email: str = typer.Argument(..., help="发件人地址"),
    relation: str = typer.Argument(..., help="这是谁，例如 导师、师兄、HR"),
    note: str | None = typer.Option(None, help="备注，会一起给模型看"),
) -> None:
    """手动告诉它某个发件人是谁。你设的优先级最高，规则和模型都不会再改。"""
    settings = _settings()
    state = State(settings.resolved_db_path)
    state.set_sender_relation(email, relation, source="user", notes=note)
    typer.echo(f"已记住：{email.strip().lower()} = {relation}")


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "—"


@app.command()
def review(
    limit: int = typer.Option(20, help="最多核对几封"),
    all_: bool = typer.Option(False, "--all", help="已经标过的也再看一遍"),
) -> None:
    """逐条核对最近的判断：这封到底要不要管？你的答案存下来，mail-monitor eval 用它算准确率。"""
    settings = _settings()
    state = State(settings.resolved_db_path)
    rows = state.recent_decisions(limit=limit, unlabeled_only=not all_)
    if not rows:
        typer.echo("没有待核对的邮件（先跑几次 run，或加 --all 重看标过的）")
        return
    typer.echo("每封回答：y = 需要处理，n = 不需要，s = 跳过，q = 退出\n")
    labeled = 0
    for row in rows:
        verdict = LABEL.get(row["needs_action"], row["needs_action"] or "?")
        source = row["decided_by"] + (f"·{row['rule_name']}" if row["rule_name"] else "")
        who = row["who"] or row["sender_name"] or row["sender_email"] or "未知发件人"
        typer.echo(f"[{verdict} · {source}] {who}：{row['what'] or row['subject'] or '（无主题）'}")
        stamp = fmt_time(row["received_at"], settings.timezone)
        previous = f" | 你标过：{LABEL.get(row['label'], row['label'])}" if row["label"] else ""
        typer.echo(f"   主题：{row['subject'] or '（无主题）'} | {row['account'] or ''} {stamp}{previous}")
        answer = typer.prompt("   要管吗？[y/n/s/q]", default="s", show_default=False).strip().lower()
        if answer in ("q", "quit", "退出"):
            break
        if answer in ("y", "yes", "是", "要"):
            state.set_label(row["id"], "yes")
            labeled += 1
        elif answer in ("n", "no", "否", "不要"):
            state.set_label(row["id"], "no")
            labeled += 1
    typer.echo(f"\n已标注 {labeled} 封。看结果：mail-monitor eval")


@app.command("eval")
def evaluate() -> None:
    """用你在 review 里标的答案算准确率：需要处理的漏了几封、即时推送里有多少是噪声。"""
    settings = _settings()
    state = State(settings.resolved_db_path)
    e = state.evaluation()
    if not e["labeled"]:
        typer.echo("还没有标注数据，先跑 mail-monitor review")
        return
    typer.echo(f"已标注 {e['labeled']} 封，其中你认为需要处理的 {e['actual_yes']} 封")
    typer.echo(f"需要处理的召回：{e['caught']}/{e['actual_yes']}（{_pct(e['caught'], e['actual_yes'])}）被即时推送；漏推 {e['missed']} 封")
    typer.echo(f"即时推送的精确：{e['pushed_yes']}/{e['pushed']}（{_pct(e['pushed_yes'], e['pushed'])}）真的需要处理；噪声 {e['noise']} 封")
    typer.echo(
        f"严格口径（只算 needs_action=yes）：精确 {_pct(e['strict_tp'], e['predicted_yes'])}，"
        f"召回 {_pct(e['strict_tp'], e['actual_yes'])}；拿不准 {e['unsure']} 封"
    )
    typer.echo("按来源：")
    for source, stat in e["by_source"].items():
        decided = stat["n"] - stat["unsure"]
        typer.echo(f"  {source}：{stat['n']} 封，判对 {stat['correct']}/{decided}（{_pct(stat['correct'], decided)}），拿不准 {stat['unsure']}")


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
                typer.echo("\n写进 ~/.mail-monitor/.env：\nMAIL_MONITOR_NOTIFY=lark_app\nLARK_RECEIVE_ID=<上面的 chat_id>（oc_ 开头会自动按群发，类型不用填）")
            if email:
                open_id = await notifier.lookup_open_id(email)
                if open_id:
                    typer.echo(f"\n{email} 的 open_id={open_id}（想让机器人私聊你，就把它填进 LARK_RECEIVE_ID）")
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

    async def go() -> str:
        notifier = build_notifier(settings)
        try:
            await notifier.send(Push.plain(text))
            return getattr(notifier, "last_output", "")
        finally:
            close = getattr(notifier, "aclose", None)
            if close:
                await close()

    try:
        output = asyncio.run(go())
    except NotifyError as exc:
        typer.echo(f"❌ {exc}")
        raise typer.Exit(code=1)
    # 用 notify-hub 时把它的原话打出来：重试过几次也写在里面
    typer.echo(f"notify-hub：{output}" if output else f"✅ 已通过 {settings.notify_backend} 发送")


if __name__ == "__main__":  # pragma: no cover
    app()
