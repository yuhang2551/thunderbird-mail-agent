# Changelog

[中文](CHANGELOG.md) | **English**

Recorded increment by increment: what each step added, how far it was verified on a real machine, and what comes next.

## Next

1. With the new scheduled job installed, check that digests arrive at 08:00, 12:00 and 18:00 Dubai time, that the 08:00 one carries what quiet hours held overnight, and whether the new card reads well on the phone.
2. Use it for a week: label with `review`, check the miss and noise rates with `eval`, and tune the rules and prompt from the results. Along the way, replace the example address in the advisor rule of `rules.yaml` (until then nothing is pushed at night, it all waits for 08:00) and set `MAIL_MONITOR_PROFILE`.
3. The ChatGPT subscription version (designed in [Model backends](docs/model-backends_EN.md), not urgent).

## 2026-10-28 · Digests follow the MAIL_MONITOR_TZ clock, and a new digest card

**Why**

- On 10-28 a digest arrived at 14:00 Dubai time, although digests were set for 08:00, 12:00 and 18:00. The Mac's time zone is the UAE and `MAIL_MONITOR_TZ` is Dubai too; the culprit is launchd, which reads the time zone only at boot. The Mac was most likely last booted on Beijing time and the zone changed afterwards without a restart, so launchd kept counting on Beijing time and the "18:00" digest arrived at 14:00 in Dubai. This is inferred: the arrival time matches exactly and there is [a report of the same thing](https://serpapi.com/blog/2025-ai-everywhere-yet-a-reboot-still-saves-the-day/), but launchd's time zone was not checked on the Mac itself. Left alone, the next day's digests would have come at 04:00, 08:00 and 14:00 Dubai time, the 04:00 one inside quiet hours.
- With a lot of mail the digest card was hard to read: three to five lines per message, long summaries, each trailed by the full mailbox address and time.

**Changed**

- The mail monitor now decides when a digest is due, on the `MAIL_MONITOR_TZ` clock. launchd wakes `digest --due` at the top of every hour: it sends only when a digest hour has passed that has not been sent yet, then records it in a new `meta` table; otherwise it does nothing and prints nothing. A digest hour missed during sleep is sent on wake, but not during quiet hours, when it waits for 08:00; if the push fails, the hour is not recorded and the next hour retries; right after installing, an hour that passed more than an hour ago is not caught up. `mail-monitor digest` without `--due` still sends right away.
- The digest hours moved from `DIGEST_HOURS` in `launchd.sh` to `MAIL_MONITOR_DIGEST_HOURS` in `.env` (default `8,12,18`), and changing them needs no reinstall; `launchd.sh` says so if `DIGEST_HOURS` is still passed. `doctor` shows one more line, such as "汇总：每天 8、12、18 点（Asia/Dubai）" (digest: daily at 8, 12 and 18).
- A new digest card: the title says how many messages there are and whether any need action, such as "邮件汇总 · 11 封，都不用处理" (mail digest · 11 messages, none need action), so the phone notification shows it; groups get a colored dot and a blank line between them; needs action and unsure get a second line with the due date, mailbox and time (mailboxes shortened to Gmail, MBZUAI and so on, just the time for today's mail); for your information shows only who and what, merges repeat mail from one address as ×N, and lists at most 12 lines before saying how many are left; long summaries lose parenthetical asides and are cut at a comma to fit two lines.
- Shorter instructions to the model: the sender is an identity or organization only, within 10 characters and without brackets; what the mail is about within 30 characters, without repeating the sender. New mail should then take one line in the digest.
- 144 tests. The new ones cover how digest hours are written, working out the digest hour in the configured time zone, sending each digest hour once, catching up after sleep, not sending during quiet hours, retrying at the next hour after a failed push, `digest --due` printing nothing when nothing is due, and the new card layout and shortening rules.

**Upgrading**

After `git pull`, run `./scripts/launchd.sh install` once to switch the digest to the new hourly job.

## 2026-10-28 · The mail monitor decides when to push

**Why**

notify-hub 0.2 kept time of its own: quiet hours, a digest and a scheduled job three times a day. The mail monitor had its own scheduled job and digest too. With two schedules, working out when a notification would arrive meant putting both sets of settings side by side. notify-hub 0.3 now only sends right away (see its [changelog](https://github.com/yuhang2551/notify-hub/blob/main/CHANGELOG_EN.md)), and all the timing is decided here.

**Changed**

- The digest now goes out three times a day by default, at 08:00, 12:00 and 18:00, instead of twice at 09:00 and 18:00. `DIGEST_HOURS` still changes it.
- New quiet hours, `MAIL_MONITOR_QUIET_HOURS`, default `23:00-08:00`, on the clock of `MAIL_MONITOR_TZ` (the computer's time zone when unset). During them only rules with `urgency: high` (your advisor, say) are pushed right away; everything else that would be pushed right away goes into the digest and arrives with the 08:00 one. `off` turns them off. The model's "urgent" does not count, because an email's wording can sway the model.
- Mail whose push fails goes into the next digest; notify-hub first retries a few times on the spot, and only then does it count as failed. When the digest itself cannot be sent, the mail stays queued, `digest` exits with an error, and the next digest carries it.
- Mail that was held for quiet hours or whose push failed still counts as "judged push right away", so the miss rate in `eval` measures only whether the verdict was right, not when the push arrived.
- notify-hub no longer gets `--key`: 0.3 does not deduplicate, and whether a message was pushed is already recorded in the database here. This version still works with the old notify-hub 0.2.1, and `doctor` suggests upgrading.
- `doctor` shows one more line, the quiet hours. `notify-test` now sends at normal level: it used urgent so that notify-hub's quiet hours would not hold it, and notify-hub no longer holds anything.
- 124 tests. The new ones cover how quiet hours are written and the check across midnight, only advisor-type mail being pushed at night, and no mail being lost when an instant push or the digest cannot be sent.

**Docs corrected**

- The README, architecture and FAQ no longer say that notify-hub handles quiet hours, deduplication and resending; the README has a new section, "When pushes arrive".
- Several places said "nothing runs while the Mac sleeps, one catch-up run happens on wake", which is wrong for the checks. According to [Apple's launchd documentation](https://developer.apple.com/library/mac/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html), an interval job (the check) skips the runs it missed during sleep and runs again at the next interval after waking; a calendar job (the digest) that fell during sleep runs once on wake. launchd also never wakes the computer for a job. Each check looks back two days, so mail that arrived during sleep is not missed, it just arrives up to an hour after waking.
- The top-level README still said the monitor checks every 5 minutes; it now says every hour.

**Tested on the real machine** (2026-10-28, Mac, times on the Mac's clock)

- Before the upgrade, the scheduled job was already doing real work in the background: the three checks from 11:36 to 13:37 found 12 new messages; rules settled 2 and the Claude subscription version judged 10. 1 was pushed right away (through notify-hub, still 0.2.1 then), 11 went into the digest, and 8 senders' identities were remembered. This is the first time Claude verdicts and pushes through notify-hub were seen working under launchd.
- At 13:45 notify-hub was upgraded to 0.3.0 in the order its README gives, and `launchctl list` no longer shows its old scheduled job.
- After `git pull` to this version, `doctor` passed every check: the push line shows notify-hub 0.3.0 and the quiet-hours line 23:00-08:00.
- `./scripts/launchd.sh install` reinstalled the job with digests at 08:00, 12:00 and 18:00; the check it ran on install exited 0 with 0 new messages.
- Not yet seen: the first digest at the new times (18:00 that day, carrying the 11 messages held during the day) and quiet hours at night.

## 2026-10-28 · The schedule checks hourly, running on the Mac

**Changed**

- `scripts/launchd.sh` now checks every hour by default instead of every 5 minutes. Job-search and university mail can usually wait an hour, so the background job need not run often; checking more often would not cost extra model usage either, since the model only sees new mail. `RUN_INTERVAL` still changes it.
- One check runs at install and at login, so there is no hour-long wait.
- `install` stops with a reminder if `mail-monitor init` has not been run: the first check starts right away, and without init it would push all mail from the last two days.
- launchd's PATH now includes `~/.local/bin`, where claude and notify-hub are installed.
- New `./scripts/launchd.sh print`: prints the plists without installing them; the tests use it to check what is generated.

**Tested on the real machine** (2026-10-28, Mac)

- `git pull` to this version, `.env` switched to `MAIL_MONITOR_LLM=claude` (the Claude subscription version) and `MAIL_MONITOR_NOTIFY=notify_hub`; `doctor` passed every check.
- `mail-monitor init` marked the 111 existing messages in the two inboxes as seen.
- `./scripts/launchd.sh install` ran one check right away, and `status` showed exit code 0: 35 messages fetched from the two inboxes, 0 new. So under launchd it finds node and reaches Thunderbird.
- Not verified yet: calling Claude for the verdict and pushing through notify-hub from the scheduled job; that waits for the first new mail.

**Found and fixed while testing**

- Through notify-hub, `notify-test` printed its result twice (once as a log line, once as the result). It now prints once; to see notify-hub's answers during a check, add `-v`.
- The line that `run` and `digest` print now starts with the time (for example `10-28 13:00 收件箱 2 个…`). `status` only shows the last lines of the logs, and before this you could not tell which run a line came from.
- The command blocks in the READMEs and docs no longer contain comments; the explanations moved outside the blocks. zsh, the default shell in the macOS terminal, does not treat `#` as a comment: a comment line reports `command not found: #`, and a trailing comment becomes arguments to the command. For example `mail-monitor doctor  # self-check` fails with extra arguments, and `./scripts/create-mail-workspace.sh  # creates ~/mail-workspace by default` would create a folder named `#`. A new test checks the command blocks in the docs.
- 105 tests.

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
- Tested on the Mac on 2026-10-28: after `git pull`, `doctor` with `MAIL_MONITOR_NOTIFY=notify_hub` showed notify-hub 0.2.1 on the push line, with both inboxes and the Claude subscription fine too; `notify-test` went out through notify-hub and Lark accepted it (message #7 in notify-hub).

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
