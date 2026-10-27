# Changelog

[中文](CHANGELOG.md) | **English**

Recorded increment by increment: what each step added, how far it was verified on a real machine, and what comes next.

## Next

1. On the Mac, `git pull`, switch push in `.env` to `notify_hub`, and get `mail-monitor notify-test` onto the phone.
2. Mark existing mail as seen with `mail-monitor init`, install the launchd jobs, and let it run for real. How often to check is decided then (the script currently defaults to every 5 minutes).
3. Use it for a week: label with `review`, check the miss and noise rates with `eval`, and tune the rules and prompt from the results.
4. The ChatGPT subscription version (designed in [Model backends](docs/model-backends_EN.md), not urgent).

## 2026-10-27 · Pushes can go through notify-hub

**Added**

- A new push option, `MAIL_MONITOR_NOTIFY=notify_hub`: instant pushes and the morning and evening digest are handed to the local notification gateway [notify-hub](https://github.com/yuhang2551/notify-hub), which owns the Lark credentials, quiet hours at night, deduplication, rate limiting and retries. The terminal, group bot and app bot options still work.
- Besides its plain text, every push now carries a card title, body and level. An instant push is titled "who: what", readable at a glance in the phone notification; the digest is one "邮件汇总 · N 封" (mail digest · N messages) card.
- Levels: rules with `urgency: high` (your advisor, say) are sent as urgent and delivered at night too; everything else is normal, held during quiet hours and sent as one combined card when they end. A model-judged "urgent" is shown on the card but does not wake you at night.
- Each mail is handed to notify-hub with its own id, so even if the same mail were handed over twice it would be pushed once.
- If notify-hub is not installed, cannot be found or gives no answer within 60 seconds, the mail moves into the digest and is not lost. When the command is not on PATH it is looked up in `~/.local/bin`, or `MAIL_MONITOR_NOTIFY_HUB_BIN` can give the full path.
- `doctor` shows the notify-hub version; `notify-test` sends as urgent (a test message should not be held by quiet hours) and prints notify-hub's answer as is.
- 99 tests, using a fake notify-hub command.

**How far it was verified**

- In the cloud, one full check ran against the real notify-hub (pushing to the terminal, not to Lark): the advisor's mail went out as urgent, and the rest was held by notify-hub during quiet hours.
- Not yet tried on the Mac with real Lark; that is step 1 of Next.

## 2026-10-27 · Lark push working

**Real-machine test**

- Created the app bot 「通知助手」 in the Lark developer console: turned on the `im:message:send_as_bot` and `im:chat:readonly` permissions, published a version, and added it to a group with only the user in it.
- `mail-monitor lark-chats` found the chat id, and `mail-monitor notify-test` delivered the test message to the phone.

**Found and fixed during the test**

- With only a chat id filled in and `LARK_RECEIVE_ID_TYPE` left empty, the program treated the id as a personal open_id and Lark rejected it. Now an empty type is worked out from the id's prefix: `oc_` goes to the chat, `ou_` as a direct message; a type you fill in still wins.
- 88 tests.

## 2026-10-27 · Claude subscription backend, first read-only dry run on a real machine

**Real-machine test** (Apple Silicon Mac, read-only: nothing recorded, nothing pushed, mailbox untouched)

- Setup: Python 3.13 (installed into the home folder with uv), Claude Code 2.1.311 (signed in with a Claude subscription), Thunderbird + thunderbird-mcp.
- `mail-monitor doctor` passed every check: both inboxes (Gmail and the school mailbox) connected, and claude signed in with the subscription.
- `mail-monitor run --dry-run --days 1`: 15 new messages from the last day; rules settled 8, Claude judged 7, and none fell back; 1 would be pushed at once and 14 would go to the digest.

**Added**

- Claude subscription backend: set `MAIL_MONITOR_LLM=claude` and each message is sent through one call of the official `claude -p` signed in on the Mac, no key needed. Tools, MCP, hooks and CLAUDE.md are all off, the mail goes in on stdin, and the session is not saved. When claude is not signed in, out of allowance, too old or timing out, the rest of the round is pushed as "unsure" as usual, and the reason goes in the run report.
- `doctor` checks the claude version and sign-in method without calling the model.
- A dry run now ends by listing the mail that would go to the digest, in digest format, instead of showing only the instant pushes.
- 79 tests, using a fake thunderbird-mcp and a fake `claude` command.

**Found and fixed during the test**

- The Mac's built-in Python is 3.9: `install.sh` now looks for an installed python3.10 to 3.14 on its own, and when there is none it names three ways to install one (python.org, Homebrew, uv).
- The bash 3.2 that ships with macOS swallows Chinese text that directly follows `$VAR` into the variable name and fails with "unbound variable": every script now writes `${VAR}`, with a test to keep it that way.
- No `claude` command in the terminal: doctor now gives the official install command and `claude auth login`, and when claude is not on the PATH the program uses `~/.local/bin/claude`.

## 2026-10-17 · Documentation, catching up with DeepSeek

- `docs/` gained the architecture guide, model backends and FAQ, in Chinese and English.
- DeepSeek retired `deepseek-chat`: the default is now `deepseek-flash` with its default thinking mode turned off; other vendors' private parameters go in `LLM_EXTRA_BODY`.
- With Thunderbird closed, the program says it cannot reach Thunderbird instead of crashing.

## 2026-10-13 · Skeleton, memory, schedule, evaluation

- Checking: reads new mail from every inbox through thunderbird-mcp, deduplicated in SQLite.
- Judging: rules (`rules.yaml`) run first; mail they do not settle is read in full and given to the model, which returns fixed-structure JSON (who, what, whether to act, by when, suggestion), validated with Pydantic, retried once and then treated as "unsure".
- Pushing: mail to act on, or unsure, is pushed at once and the rest is collected into morning and evening digests; outputs are the terminal, a Lark group custom bot (webhook, optionally signed) and a Lark app bot, with `lark-chats` and `notify-test` to help set them up.
- Memory: remembers who each sender is (yours > rules > model) and includes earlier mail on the same topic when judging; view and edit with `senders` and `sender-set`.
- Schedule: `scripts/launchd.sh` checks every 5 minutes and sends a digest each morning and evening.
- Evaluation: label with `review`; `eval` computes the miss rate and the noise rate.
- Read-only: never sends, deletes or moves mail; the only mailbox write (tagging mail to act on) is off by default.
