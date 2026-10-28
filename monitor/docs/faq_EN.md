# FAQ and troubleshooting

[中文](faq.md) | **English**

Run `mail-monitor doctor` first. It only checks and changes nothing, and it points straight at most problems. When launchd runs the monitor, the logs are in `~/.mail-monitor/logs/`.

## Installing

**install.sh says Python is too old, or cannot find Python**

The `python3` that ships with macOS is often 3.9, and this program needs 3.10 or later. The script looks for newer interpreters such as `python3.13` or `python3.12` on its own and stops only when it finds none. Install one in any of these ways, then run `./scripts/install.sh` again:

- Official installer (no Homebrew needed): download the Python 3.13 macOS installer from [python.org](https://www.python.org/downloads/macos/) and double-click it.
- Homebrew: `brew install python@3.13`.
- uv (installs into your home folder, no admin password):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv python install 3.13
PYTHON="$(~/.local/bin/uv python find 3.13)" ./scripts/install.sh
```

**`mail-monitor: command not found`**

The virtual environment is not active. Run `source ~/thunderbird-mail-agent/monitor/.venv/bin/activate`, or use the full path `~/thunderbird-mail-agent/monitor/.venv/bin/mail-monitor`.

## Connecting to Thunderbird

**doctor says it cannot reach Thunderbird**

- Thunderbird is closed, or the Thunderbird MCP add-on is disabled.
- The add-on was just installed and Thunderbird has not been restarted.
- The bridge is not at the default `~/thunderbird-mcp/mcp-bridge.cjs`: set `MAIL_MONITOR_BRIDGE=<actual path>` in `.env`.
- `node` cannot be found: set `MAIL_MONITOR_NODE_BIN=<full path to node>` in `.env` (`which node` tells you). Under launchd, `launchd.sh install` writes the directory node was in at that moment into PATH, so install again after switching Node versions.
- The repository's `./scripts/doctor.sh` checks the add-on itself.

**doctor says required tools are missing**

Turn on `listAccounts`, `listFolders`, `getRecentMessages` and `getMessages` under the add-on's Tool Access.

**A mailbox is missing, or "no inboxes found"**

Usually `MAIL_MONITOR_ACCOUNTS` is wrong. It matches part of an account id or name; delete the line to watch everything.

## Pushes

**The first run pushed a pile of old mail**

After installing, run `mail-monitor init` once to register existing mail as seen. `./scripts/launchd.sh install` now stops and reminds you if it has not been run.

**Nothing arrives on my phone**

- Run `mail-monitor notify-test` first and read the error.
- With notify_hub: run `notify-hub test` first; the mail monitor can only get through once that does. If `mail-monitor doctor` shows no notify-hub version, the command cannot be found: run `which notify-hub` in a terminal to see where it is and put that path in `MAIL_MONITOR_NOTIFY_HUB_BIN` in `.env`. If `notify-test` reports "没发出去" (not sent) followed by notify-hub's own words: "cannot reach Lark" means a network or Lark problem, and notify-hub has already retried a couple of times on the spot; a missing `LARK_APP_ID` or the like means notify-hub's configuration is not filled in.
- App bot: is the permission on (`im:message:send_as_bot`), is the version published, is the bot in that group, and is `LARK_RECEIVE_ID` right (`oc_` is a chat, `ou_` is you)? If you also set `LARK_RECEIVE_ID_TYPE`, it must match the id (`chat_id` goes with a group id, `open_id` with your user id); when unsure, delete that line and the program works it out.
- Group custom bot: if the group has signature checks on, `LARK_WEBHOOK_SECRET` must be set.
- For Feishu (the China edition) set `LARK_DOMAIN` to `https://open.feishu.cn`.
- Mail whose push failed is not lost; it goes into the next digest.

**Mail that arrived at night only reaches me in the morning**

That is the mail monitor's quiet hours: between 23:00 and 08:00, mail that would be pushed right away goes into the digest instead and arrives with the 08:00 one. Rules with `urgency: high` (the advisor rule in `rules.example.yaml`) are still pushed right away at night; to get someone's mail at night, write such a rule for them. The model's "urgent" does not count, because an email's wording can sway it. Change the quiet hours in `~/.mail-monitor/.env`: `MAIL_MONITOR_QUIET_HOURS=23:00-08:00`, or `off` to turn them off.

**Too many pushes**

- Anything unsure is pushed right away on purpose: missing an important email is worse than reading one extra push.
- After a week or two, label with `mail-monitor review`, see in `mail-monitor eval` which mail is noise, and write rules for it, for example `needs_action: "no"` and `notify: digest` for a notification address. Afterwards, `mail-monitor rules --from "Someone <x@example.com>" --subject "…"` shows which rule a message hits.
- Set `MAIL_MONITOR_PROFILE` in `.env`: once the model knows who you are and what job you want, its verdicts improve.
- Use `mail-monitor sender-set <address> <identity>` to tell it who someone is.

**Missed pushes**

Mark the missed ones y in `review`, and `eval` counts the misses. Once you see a pattern, write a rule, for example `needs_action: "yes"` and `notify: instant` for your advisor's address.

## The model

**doctor says DeepSeek retired a model name**

DeepSeek retired `deepseek-chat` and `deepseek-reasoner` on 2026-07-24. Set `LLM_MODEL=deepseek-flash` in `.env`.

**A push ends with "没有模型判断，按「拿不准」推送" (no model verdict, pushed as unsure)**

That message never went through the model: either `.env` has neither a key nor the Claude subscription version turned on, or the model failed. The output of `mail-monitor run` and the "LLM 判断失败" (LLM verdict failed) lines in the log say why. Common DeepSeek cases:

| Error | Cause |
|---|---|
| HTTP 401 | Wrong key |
| HTTP 402 | Insufficient balance |
| HTTP 400 or 422 | Bad request or parameter, for example a misspelled model name |
| HTTP 429 | Requests too fast |
| The model returned no JSON | Happens occasionally and one retry usually fixes it; if it keeps happening, share the log |

**With the Claude subscription version, doctor cannot run claude (No such file or directory)**

There is no `claude` command in the terminal yet. Install the Claude Code command line, then sign in:

```bash
curl -fsSL https://claude.ai/install.sh | bash
~/.local/bin/claude auth login
```

When `claude` is not on the PATH, the program looks for `~/.local/bin/claude` on its own; if it is installed somewhere else, put the full path in `MAIL_MONITOR_CLAUDE_BIN` in `.env`.

**With the Claude subscription version, doctor says claude is not signed in, or is using an API key**

Run `claude` in a terminal, type `/login`, sign in with your Claude account (Pro / Max), then run `mail-monitor doctor` again. An API-key sign-in is billed per token and does not count as the subscription.

**With the Claude subscription version, the log says the allowance is used up**

The allowance is shared with your own use of Claude. While it is used up, mail the rules do not settle is still pushed as "unsure", so nothing is missed; once the allowance resets it works again. To use less: write more rules, or set `MAIL_MONITOR_CLAUDE_MODEL=haiku` in `.env`.

**It works in the terminal, but under launchd it cannot find claude**

launchd has a different PATH from your terminal. Find the full path with `which claude` and put it in `MAIL_MONITOR_CLAUDE_BIN` in `.env`, or run `./scripts/launchd.sh install` again, which writes the directory claude is in at that moment into PATH.

**Another provider, a local model, or a ChatGPT subscription instead of an API key**

See [Model backends](model-backends_EN.md). The ChatGPT subscription version is designed but not yet built.

## Running on a schedule

**When do pushes arrive?**

The mail monitor decides all the timing, whether pushes go through notify-hub or straight to Lark:

- Rules with `urgency: high` (your advisor, say): as soon as the hourly check finds them, at night too.
- Needs action or unsure: as soon as the hourly check finds them; during quiet hours (23:00 to 08:00) they go into the digest and arrive with the 08:00 one.
- Everything else worth knowing: one "邮件汇总" (mail digest) card at 08:00, 12:00 and 18:00.

To change it: both live in `.env`, quiet hours as `MAIL_MONITOR_QUIET_HOURS` and the digest hours as `MAIL_MONITOR_DIGEST_HOURS`, both on the `MAIL_MONITOR_TZ` clock.

**The digest arrives at the wrong hour**

First check that the hours and time zone on the "汇总" (digest) line of `mail-monitor doctor` are right; the time zone is `MAIL_MONITOR_TZ` in `.env`. Older versions had launchd run the digest at 08:00, 12:00 and 18:00 directly, and launchd reads the time zone only at boot: after the Mac changes time zone without a restart, the digest follows the old zone's clock (a Mac booted on Beijing time and then taken to Dubai sends the "18:00" digest at 14:00 Dubai time). Now launchd wakes it at the top of every hour and the mail monitor decides on the `MAIL_MONITOR_TZ` clock whether a digest is due. If your scheduled job was installed before 2026-10-28, run `./scripts/launchd.sh install` once after `git pull` to switch to the new one.

**launchd is installed but nothing seems to run**

- `./scripts/launchd.sh status` shows whether it is installed, the last exit code and the last lines of the logs.
- Nothing runs while the Mac sleeps, and the Mac is not woken for it. Missed checks are skipped and the next one comes within the hour after waking; a digest that fell during sleep is sent once on wake, or at 08:00 if the Mac wakes during quiet hours (see [Apple's launchd documentation](https://developer.apple.com/library/mac/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html)).
- If the computer was off or closed for more than 2 days, older mail is no longer judged automatically; catch up once by hand with `mail-monitor run --days 7`.

**Changing the interval or the digest hours**

The check interval is set when installing the scheduled job:

```bash
RUN_INTERVAL=120 ./scripts/launchd.sh install
```

The digest hours go in `.env`, for example `MAIL_MONITOR_DIGEST_HOURS=8,13,20`, without reinstalling the job.

## Data and privacy

**Will it change my mailbox?**

Not by default. The one write is a Thunderbird tag on mail that needs action, and only with `MAIL_MONITOR_ACTION_TAG=true` in `.env`. Nothing in the code calls a tool that sends or deletes mail.

**What gets sent out?**

Mail the rules do not settle goes to the model; a push to Lark carries only a one-line summary. The full table is in [Architecture](architecture_EN.md#7-where-your-data-goes); who each model backend sends to and how they handle it is in [Model backends](model-backends_EN.md#where-your-data-goes), which also shows how to keep one mailbox away from the model with a single rule.

**Where is the database, and how do I start over?**

At `~/.mail-monitor/state.db`. Delete it and run `mail-monitor init` again to start from scratch. Sender identities and your labels go with it, so back the file up if you want to keep them.

**A push asks me to open a link, pay, or give a code**

Pushes are summaries written by the model, and mail content can sway the model. Whenever a push asks you to open a link, pay, or give a password or code, check the original message and its sender first.
