# Changelog

[中文](CHANGELOG.md) | **English**

Recorded increment by increment: what each step added, how far it was verified on a real machine, and what comes next.

## Next

1. Connect the Lark app-bot push and receive a test message on the phone with `mail-monitor notify-test`.
2. Mark existing mail as seen with `mail-monitor init`, install the launchd jobs, and let it run for real.
3. Use it for a week: label with `review`, check the miss and noise rates with `eval`, and tune the rules and prompt from the results.
4. The ChatGPT subscription version (designed in [Model backends](docs/model-backends_EN.md), not urgent).

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
