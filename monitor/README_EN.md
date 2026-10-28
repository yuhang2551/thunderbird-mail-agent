# Mail-monitor agent

[中文](README.md) | **English**

The rest of this repository waits for you to ask ("what came in this week?") before the agent reads anything. This directory turns it into **hands-off monitoring**: on a schedule (hourly by default) it checks every inbox, and for each new message it decides who it is from, what it wants, whether you need to act and by when, then pushes the result to Feishu / Lark.

```
launchd every hour ──► mail-monitor run
                         │ 1 call thunderbird-mcp over MCP: listFolders → getRecentMessages
                         │ 2 dedupe (SQLite remembers every message already handled)
                         │ 3 rules (rules.yaml: never push verification codes, digest newsletters, advisor is always urgent …)
                         │ 4 anything the rules did not settle: read the body + recall memory (who this sender is, what the same thread said before) → LLM verdict (JSON with a fixed schema)
                         │ 5 optional: tag "needs action" mail in Thunderbird (off by default)
                         │ 6 push: needs action / unsure → right away; the rest → morning and evening digest (mail-monitor digest)
                         └ 7 record: the verdict and the sender's identity go back into SQLite as memory for next time
```

It **only reads mail; it never sends or deletes**. The one action that writes to the mailbox (tagging) is off by default.

## Docs

| Doc | Contents |
|---|---|
| [Architecture](docs/architecture_EN.md) | The parts, one check from start to finish, how a verdict is made, memory, design choices, where data goes, safety boundaries |
| [Model backends](docs/model-backends_EN.md) | The API-key version and the Claude subscription version (both work today) and the ChatGPT subscription version (designed, not yet built): setup, each vendor's rules, cost and data handling |
| [FAQ and troubleshooting](docs/faq_EN.md) | Install problems, no connection, no push, too many or too few pushes |
| [Changelog](CHANGELOG_EN.md) | Increment by increment: what each step added, real-machine test results, what comes next |

## Install

Prerequisites: steps 1–3 of the main README are done (Thunderbird signed in to your mailboxes, the thunderbird-mcp add-on installed, Node available).

```bash
cd ~/thunderbird-mail-agent/monitor
./scripts/install.sh     # creates .venv, installs dependencies, writes ~/.mail-monitor/.env and rules.yaml (needs Python 3.10+)
source .venv/bin/activate
# then edit ~/.mail-monitor/.env (pick a model: DEEPSEEK_API_KEY, or MAIL_MONITOR_LLM=claude for a Claude subscription; both optional; keep push on console at first) and adjust ~/.mail-monitor/rules.yaml

mail-monitor doctor      # self-check: can it reach Thunderbird, which inboxes, are push and model configured. Changes nothing
mail-monitor init        # first run: register existing mail as seen so old mail is not pushed
mail-monitor run --dry-run   # show how it would judge, without recording or pushing (and without memory)
mail-monitor run         # one real check
mail-monitor digest      # send the batched mail as one digest
mail-monitor senders     # which senders it remembers and who decided their identity
mail-monitor sender-set prof@example.edu advisor   # tell it who someone is (highest priority)
mail-monitor review      # go through its verdicts one by one and mark whether the mail really needed action
mail-monitor eval        # accuracy from those labels: how many were missed, how many were noise
```

### Running on a schedule

On macOS use launchd (sturdier than a daemon: nothing runs while the Mac sleeps, one catch-up run happens on wake, and one run happens at login):

```bash
./scripts/launchd.sh install     # run once right away, then hourly; digest at 09:00 and 18:00
./scripts/launchd.sh status      # installed or not, last exit code, last lines of the logs
./scripts/launchd.sh uninstall
```

Interval and hours are configurable, for example a check every 30 minutes and digests at 08:00, 13:00 and 20:00: `RUN_INTERVAL=1800 DIGEST_HOURS="8 13 20" ./scripts/launchd.sh install`. Checking more often costs no extra model usage: the model only sees new mail, once per message. `./scripts/launchd.sh print` only prints what would be installed. Logs are in `~/.mail-monitor/logs/`.

Run `mail-monitor init` once before installing, or the first check pushes all mail from the last two days; `install` stops and reminds you if it has not been run.

On Linux use cron:

```
0 * * * *    ~/thunderbird-mail-agent/monitor/.venv/bin/mail-monitor run    >> ~/.mail-monitor/logs/run.log 2>&1
0 9,18 * * * ~/thunderbird-mail-agent/monitor/.venv/bin/mail-monitor digest >> ~/.mail-monitor/logs/digest.log 2>&1
```

## Configuration

| Item | Environment variable | Notes |
|---|---|---|
| Model | `MAIL_MONITOR_LLM`, `DEEPSEEK_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_EXTRA_BODY`, `MAIL_MONITOR_CLAUDE_MODEL` | `api` (default) calls any OpenAI-compatible endpoint; by default DeepSeek's `deepseek-flash`, with its default thinking mode turned off. `claude` runs the Claude Code already signed in on your Mac and uses your Claude Pro / Max subscription, no key needed; the model defaults to `sonnet`. Works with neither: mail the rules do not settle is pushed as "unsure". See [Model backends](docs/model-backends_EN.md) |
| Profile | `MAIL_MONITOR_PROFILE` | One sentence about you (what you study, what job you are looking for, who your advisor is), added to the prompt. Without it the model only knows "a graduate student who is also job hunting" |
| Push | `MAIL_MONITOR_NOTIFY` = `console` / `notify_hub` / `lark_app` / `lark_webhook` | Start with `console` to watch it in the terminal. If you have [notify-hub](https://github.com/yuhang2551/notify-hub) installed, use `notify_hub`: the Lark settings live there, so nothing to fill in here (set `MAIL_MONITOR_NOTIFY_HUB_BIN` to the full path if the command is not found). Pushing directly, an app bot needs `LARK_APP_ID`, `LARK_APP_SECRET`, `LARK_RECEIVE_ID`; a group custom bot only needs `LARK_WEBHOOK_URL` (optional `LARK_WEBHOOK_SECRET`) |
| Rules | `MAIL_MONITOR_RULES` (default `~/.mail-monitor/rules.yaml`) | See [rules.example.yaml](rules.example.yaml) |
| Accounts | `MAIL_MONITOR_ACCOUNTS` | Watch only some accounts; default is every inbox |
| Actions | `MAIL_MONITOR_ACTION_TAG` | Tag "needs action" mail in Thunderbird, default `false` |

The full list is in [.env.example](.env.example). Secrets live only in `~/.mail-monitor/.env`, never in the repository.

### Pushing to Feishu / Lark

Three routes, pick one:

**A. Hand it to notify-hub (recommended)**: [notify-hub](https://github.com/yuhang2551/notify-hub) is a local notification gateway. Lark credentials, night-time quiet hours, de-duplication and retries are set up there once, and the mail monitor just hands its messages over. Install it following its README until `notify-hub test` reaches your phone, then put `MAIL_MONITOR_NOTIFY=notify_hub` in `.env`; when `mail-monitor doctor` shows the notify-hub version, it is connected. Then:

- Each instant push is a card titled "who: what", so the phone notification tells you at a glance.
- Rules with `urgency: high` (your advisor, say) are sent as urgent: a red card, delivered at night too. Everything else, including mail the model judged urgent, is held during quiet hours (23:00–08:00 by default) and arrives as one combined card at 08:00.
- The morning and evening digest is still sent by `mail-monitor digest`, as one "邮件汇总 · N 封" (mail digest · N messages) card.
- A message that cannot be delivered stays in notify-hub's outbox and is retried automatically. If notify-hub itself cannot run (not installed, command not found), the mail moves into the digest, so nothing is lost, just as with direct pushes.

**B. Group custom bot (simplest, but some tenants do not offer it)**: in desktop Lark open a group → Settings → Bots → Add bot → Custom bot → copy the webhook. In `.env`: `MAIL_MONITOR_NOTIFY=lark_webhook`, `LARK_WEBHOOK_URL=…`, optionally `LARK_WEBHOOK_SECRET=…` (signature check).

**C. App bot (through the developer console; can message you directly)**:

1. [open.larksuite.com](https://open.larksuite.com) (open.feishu.cn for Feishu) → Developer console → create a custom app and name it. If you already have an app of your own (a bridge bot, say), reuse it and skip to step 3.
2. App page → Add capability → **Bot**.
3. Under **Permissions** enable `im:message:send_as_bot` (send as the app) and `im:chat:readonly` (list the chats the bot is in); add `contact:user.id:readonly` if you want to look up your own open_id by email.
4. **Version management & release** → create a version → publish (you approve it yourself in your own tenant).
5. Copy the App ID and App Secret from **Credentials & basic info** into `.env`: `LARK_APP_ID=…`, `LARK_APP_SECRET=…`.
6. Create a group in Lark (just you is fine), add a bot → choose this app. Then:

```bash
mail-monitor lark-chats                     # list the chats the bot is in, with chat_id
mail-monitor lark-chats --email you@example.com   # also look up your open_id (for direct messages)
```

Put the result in `.env`: `MAIL_MONITOR_NOTIFY=lark_app`, `LARK_RECEIVE_ID=…`. A chat id starting with `oc_` is sent to that chat and an open_id starting with `ou_` as a direct message, so `LARK_RECEIVE_ID_TYPE` can stay empty.

Finally `mail-monitor notify-test` sends a test message; when it shows up on your phone, the push works.

## What a push looks like

Instant (needs action or unsure); the text is in Chinese by default because the prompts are:

```
📬 需要处理 · 紧急 · Gmail                ← needs action · urgent · account
谁：量化公司 HR                            ← who: HR at a quant firm
事：约下周二 10 点线上面试，明天前确认     ← what: online interview next Tuesday 10:00, confirm by tomorrow
期限：2026-10-14                           ← deadline
建议：回复确认时间                         ← suggested action: reply to confirm the time
主题：Interview invitation - AI Agent Engineer | 10-13 15:02
```

Through notify-hub it is a card with the same content, with "who: what" moved into the title:

```
量化公司 HR：约下周二 10 点线上面试，明天前确认      ← title: who: what
──────────────────────────
需要处理 · 紧急 · Gmail
期限：2026-10-14
建议：回复确认时间
主题：Interview invitation - AI Agent Engineer | 10-13 15:02
```

Digest (morning and evening):

```
📮 邮件汇总 10-13 18:00 · 共 12 封          ← digest · 12 messages

需要处理（1）                              ← needs action (1)
• 导师：要周五前交更新后的数字（期限 2026-10-17） [School 10-13 14:02]

知道就行（3）                              ← for your information (3)
• 学校活动办公室：周四 4 点讲座，周三中午前报名 [School 10-12 19:10]
…

已忽略：订阅/通知 8                        ← ignored: 8 newsletters / notifications
```

## How a verdict is made

1. **Rules first** (free and predictable): `rules.yaml` matches on sender, domain and subject. A hit either settles the mail outright or only adds hints before handing it to the model.
2. **The model as fallback**: mail the rules do not settle is read in full and the model returns JSON with a fixed schema (who, what, needs action, urgency, deadline, suggested action, category, confidence). The output is validated with Pydantic: off-schema values are corrected, guessed deadlines are dropped, a broken answer is retried once and then falls back to "unsure".
3. **Judging with memory**: before each verdict two things are pulled from SQLite and given to the model: who the sender is (how many messages before, how many needed action, what the latest few said) and earlier mail in the same thread (same thread id in the same folder, or the same subject once Re:/Fwd: is stripped). That is how the model sees that "this one is chasing the thing from last time".
4. **Sender identities improve with use**: with every verdict the model also labels the sender's relation to you (advisor, HR / recruiter, school admin …); when it is confident enough (≥ 0.6) that goes into the `senders` table. A `who` written in a rule is remembered too, and `mail-monitor sender-set` lets you override. Priority: what you set > rules > the model; a lower source never overwrites a higher one. `mail-monitor senders` shows who decided each identity.
5. **Better one push too many than one missed**: anything unsure is pushed right away. A failed push is moved into the digest, so nothing is lost.
6. **Mail content is untrusted data**: the prompt tells the model never to follow instructions found in mail, and the body wins when it contradicts the remembered identity; the program never opens links, sends or deletes.

Why each step is designed this way, and what happens when something fails, is in [Architecture](docs/architecture_EN.md).

## Where your data goes

- Mail the rules do not settle (sender, subject, time, the first 4,000 characters of the body, related memory) goes to the model you configured; mail a rule settles outright, such as verification codes and newsletters, does not.
- A push to Lark carries only the one-line summary, never the body. Through notify-hub, these summaries are also kept in notify-hub's local outbox (`~/.notify-hub/outbox.db`).
- Verdicts are stored locally in `~/.mail-monitor/state.db`, without bodies; secrets live only in `~/.mail-monitor/.env`.

Who each model backend sends data to, and how to keep one mailbox away from the model entirely, is in [Model backends](docs/model-backends_EN.md#where-your-data-goes).

## Evaluation: how accurate is it

An agent project without numbers does not hold up, so a minimal evaluation loop is built in:

1. `mail-monitor review` lists the latest verdicts one by one (the verdict and who made it) and you answer y / n: did the mail really need action? The answers are stored in the same database.
2. `mail-monitor eval` turns those answers into
   - **Recall on "needs action"**: of the mail you say needed action, how much was pushed right away (and how many were missed). This is the number that matters most: an extra push is cheap, a missed one is not.
   - **Precision of instant pushes**: how many instant pushes really needed action (and how many were noise).
   - Strict precision and recall (counting only verdicts that explicitly say yes), and how often rules, the model and the fallback were right.

Use it for a week or two and label a few dozen messages and you have numbers for a CV; change a rule or the prompt and run `eval` again to see whether they improved.

## Development

```bash
pytest            # tests/fake_server.py stands in for thunderbird-mcp, fake_claude.py for claude and fake_notify_hub.py for notify-hub, so no Thunderbird or account is needed
```

| Path | Contents |
|---|---|
| `mail_monitor/mailbox.py` | Mail layer: MCP client that starts `mcp-bridge.cjs` and wraps the 5 tools the monitor needs |
| `mail_monitor/rules.py` | Rules layer: YAML rules evaluated before the model |
| `mail_monitor/memory.py`, `state.py` | Memory: handled mail, sender identities, thread history and your labels, all in SQLite |
| `mail_monitor/classify.py`, `llm.py`, `claude_cli.py` | Verdicts: prompt, fixed-schema JSON output, Pydantic validation, fallback; `llm.py` is the API-key version, `claude_cli.py` the Claude subscription version |
| `mail_monitor/pipeline.py` | One complete check from fetch to record |
| `mail_monitor/notify.py`, `render.py` | Push: console / notify-hub / group-bot webhook / app bot; message text and card title and body |
| `mail_monitor/cli.py` | Command line |
| `scripts/` | `install.sh` (environment), `launchd.sh` (scheduling) |
| `tests/` | The fake thunderbird-mcp (`fake_server.py`), a bridge whose Thunderbird is closed (`dead_bridge.py`), a fake `claude` command (`fake_claude.py`), a fake `notify-hub` command (`fake_notify_hub.py`) and 99 tests |
| `docs/` | Architecture, model backends, FAQ |

`tests/fake_server.py` copies the tool names, parameters and return shapes of upstream v0.9.2, so the whole pipeline runs in the cloud or in CI; switching to the real bridge is only a different start command.

## How it relates to the rest of the repository

- The mail layer is still the `thunderbird-mcp` add-on plus `mcp-bridge.cjs`; this program is just another MCP client of it, on the same path Claude Desktop uses.
- The safety rules follow [templates/mail-workspace/CLAUDE.md](../templates/mail-workspace/CLAUDE.md): never send or delete, never open links, treat mail content as untrusted.
- Like the repository's `scripts/doctor.sh`, `mail-monitor doctor` only checks and changes nothing.
