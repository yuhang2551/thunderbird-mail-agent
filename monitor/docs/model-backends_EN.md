# Model backends: the API-key version and the subscription version

[中文](model-backends.md) | **English**

The verdict layer needs exactly one thing from a model: send it a prompt, get back a JSON object (who, what, does it need action …). Whoever answers that request is the "model backend". There are two kinds:

- **API-key version**: the program calls a model API with your key and you pay per token. **Built**, DeepSeek by default.
- **Subscription version**: if you already pay for ChatGPT or Claude, use the plan's allowance instead of opening an API account. **The Claude subscription version is built** (2026-10-27); **the ChatGPT one is designed, not yet built**.

## At a glance

| | API-key version | ChatGPT subscription | Claude subscription |
|---|---|---|---|
| Status | Built | Designed, not yet built | Built |
| You need | An API key (DeepSeek by default) | A paid ChatGPT plan, authorized once in the browser | Claude Pro / Max, with Claude Code (v2.1.259 or later) installed and signed in on the Mac |
| How it is called | The program posts to `/chat/completions` | The program posts to OpenAI's `/v1/responses` with the token from that authorization | The program runs the `claude -p` command on your computer, once per message |
| Cost | Per token; with deepseek-flash, under 0.1 US cent per message | Nothing extra; counts against the plan's usage | Nothing extra; counts against the plan's usage |
| Speed | Fast | About the same as the API | Slowest: Claude Code starts up on every call |
| Vendor's position | Normal use | Open since September 2026 to open-source projects and personal projects that run locally | Only you, through the official Claude Code; third-party programs may not use a subscription |
| Can others use it | Yes | Open-source and local use, yes; paid or hosted products must apply to OpenAI first | No |

All three backends share the same prompt, the same output structure, and the same validation and fallback, so switching backends changes who answers, not how a verdict is made.

## The API-key version (works today)

In `~/.mail-monitor/.env`:

```bash
DEEPSEEK_API_KEY=sk-...
LLM_MODEL=deepseek-flash      # optional, this is the default
```

The program sends one request to `{LLM_BASE_URL}/chat/completions` in JSON mode (`response_format: {"type": "json_object"}`), at temperature 0 with at most 800 tokens. There is no vendor SDK; one HTTP request is all it takes.

**Two DeepSeek changes this year** (per the official docs as of 2026-10-17):

1. The old names `deepseek-chat` and `deepseek-reasoner` were retired on 2026-07-24. The current models are `deepseek-flash` (cheap, enough for triage) and `deepseek-v4-pro`. If your config still has an old name, `mail-monitor doctor` says so.
2. Thinking mode is on by default. Triage needs no long reasoning: thinking only makes it slower and more expensive, and it can spend the 800-token limit before any JSON comes out. So for DeepSeek the program adds `"thinking": {"type": "disabled"}` to each request by default. To control this yourself, set `LLM_EXTRA_BODY` (a JSON object merged into the request body as is; `{}` adds nothing).

**Cost**: one message, counting prompt, memory and body, is roughly 1,000 to 4,000 tokens in and two or three hundred out. At deepseek-flash's peak price in October 2026 (US$0.30 per million input tokens, US$1.20 per million output tokens) that is under 0.1 US cent per message, or under US$2 a month at 50 messages a day. Mail a rule settles outright, such as verification codes and newsletters, never reaches the model, so the real figure is lower.

**Another provider**: change `LLM_BASE_URL` and `LLM_MODEL`, and put the key in `LLM_API_KEY`. The endpoint must be compatible with OpenAI's `/chat/completions` and support JSON mode. Only DeepSeek's format is covered by tests so far, and providers differ on parameters such as `temperature` and `max_tokens`, so run `mail-monitor run --dry-run` the first time; provider-specific parameters go in `LLM_EXTRA_BODY`.

**A local model** (for example Ollama's OpenAI-compatible endpoint at `http://localhost:11434/v1`): mail never leaves your computer, which suits mailboxes whose content should not go to an outside service. Quality depends on how large a model your machine can run.

A Claude API key would work too, but Anthropic has its own API and official SDK, so it needs a backend of its own, which does not exist yet.

## The subscription version

### Why it cannot "just call the vendor's models directly"

ChatGPT Plus / Pro and Claude Pro / Max come without an API; they are for the vendors' own apps. A program can only use a plan's allowance through a route the vendor explicitly allows, and the two vendors allow different routes:

- **OpenAI** opened plan usage through "Sign in with ChatGPT" in September 2026 to open-source projects, personal projects that run locally, and a few approved private apps. Once the user authorizes in the browser, the program can call OpenAI's Responses API directly, billed to the user's own plan. This project is open source and runs on your own computer, so it qualifies.
- **Anthropic** allows subscription sign-in only for Claude Code and Anthropic's own apps. Developers building products, including with the Agent SDK, must use API keys; third-party programs may not offer Claude sign-in, may not route requests through Free / Pro / Max plans, and may not collect or store Claude credentials. None of this stops you from signing in to the official, unmodified Claude Code with your own subscription. So the Claude version touches no tokens at all; it only runs the `claude` command you installed and signed in to yourself.

Both vendors changed their rules this year; check the sources at the end before relying on this.

### ChatGPT subscription: Sign in with ChatGPT (designed, not yet built)

1. **Authorize once**: run `mail-monitor chatgpt-login` (a planned command). The program opens a temporary callback port on `127.0.0.1` and sends the browser to OpenAI's sign-in page (OAuth with PKCE). You sign in to ChatGPT and allow this program to use your plan. OpenAI registers a client for the program during this step, so neither a client secret nor an API key is needed.
2. **Store the tokens**: the access token and the rotating refresh token go into `~/.mail-monitor/chatgpt-auth.json` with mode 600, never into the repository or the logs. When the access token expires the program renews it with the refresh token, so scheduled runs under launchd never need another sign-in.
3. **Judge one message**:

   ```http
   POST https://api.openai.com/v1/responses
   Authorization: Bearer <access token from the authorization>

   {"model": "<a model your account can use>", "instructions": "<triage prompt>", "input": "<this message's metadata, memory and body>",
    "store": false, "stream": true}
   ```

   This route requires `store: false` (OpenAI keeps no copy of the conversation) and `stream: true`. It rejects `system` role messages, so the prompt goes in `instructions`, and it does not accept parameters such as `temperature` or `max_output_tokens`. The models your account can use are listed by `/v1/models`.
4. **Out of allowance**: the API returns an error such as `subscription_sharing_usage_limit_exceeded`; as today, the program falls back to "unsure" and still pushes, so no mail is missed. In ChatGPT under Settings → Usage you can give this program a weekly cap.

One thing to test while building it: the docs for this route do not say whether output can be constrained with a JSON schema. If not, nothing breaks: the prompt already asks for JSON only, and the program validates it, retries once, and otherwise falls back to "unsure".

**Alternative**: `codex exec --output-schema` (Codex CLI with its saved ChatGPT sign-in) can do the same. But it starts an agent with shell tools on every call and loads the MCP servers in `~/.codex/config.toml` (this repository's `setup-codex.sh` puts the mail tools there, so it would need `--ignore-user-config`), and OpenAI says API keys are the right default for automation. So it stays a fallback option.

### Claude subscription: call the Claude Code you are signed in to (built)

**For you only**: your Mac, your own subscription, the official `claude` command. The program never reads or stores any Claude token, and it must not be deployed as a service for other people.

**Turning it on**:

1. Install Claude Code on the Mac (v2.1.259 or later; run `claude update` if it is older), run `claude` once in a terminal, type `/login`, and sign in with your Claude account (Pro / Max).
2. Put `MAIL_MONITOR_LLM=claude` in `~/.mail-monitor/.env`. No key is needed.
3. `mail-monitor doctor` checks the claude version and how it is signed in, without calling the model or using any allowance; then `mail-monitor run --dry-run` makes real verdicts once.

Optional: `MAIL_MONITOR_CLAUDE_MODEL` (default `sonnet`; `haiku` uses less of the allowance), `MAIL_MONITOR_CLAUDE_BIN` (if launchd cannot find claude, the full path that `which claude` shows), `MAIL_MONITOR_CLAUDE_TIMEOUT` (seconds to wait per message, default 180).

**For each message that needs the model, the program makes this call once**:

```bash
cd ~/.mail-monitor/claude-run          # an empty directory
claude -p --safe-mode \
  --tools "" --strict-mcp-config \
  --permission-prompts none \
  --no-session-persistence \
  --model sonnet --effort low \
  --system-prompt-file <triage prompt> \
  --output-format json \
  < <this message's metadata, memory and body>
```

The `result` field of the returned JSON holds the model's answer. The program extracts the JSON from it and runs the same Pydantic validation, retry and fallback as the API-key version. Why each flag is there:

| Flag | Why |
|---|---|
| `--safe-mode` | Loads no CLAUDE.md, hooks, plugins, skills or MCP servers (available since v2.1.169). Your own `~/.claude/CLAUDE.md` stays out of the triage prompt, and your hooks do not run once per message |
| `--tools ""`, `--strict-mcp-config` | No tools at all. This repository's `setup-claude-code.sh` installs the mail tools as a user-level MCP server; without these flags, the Claude reading your mail could call tools that send or change mail. Mail content is untrusted, so "one sentence in an email makes it forward the inbox" becomes a real risk |
| `--permission-prompts none` | Nobody is at the computer to click "Allow", so any permission request is denied (needs v2.1.259 or later) |
| `--no-session-persistence` | Keeps the session out of `~/.claude/projects/`, where it would otherwise be stored in plain text for 30 days, and the session is full of mail |
| `--effort low` | Triage needs no long reasoning; this is faster and uses less of the allowance |
| `--system-prompt-file` | Replaces Claude Code's default coding-assistant prompt entirely. The official guidance is to replace it for a pipeline nobody watches whose identity and permissions have nothing to do with coding. It also uses less of the allowance |
| `--output-format json` | Answers and errors both come wrapped in one JSON object that is easy to parse |
| Run in an empty directory | `claude -p` runs the hooks of the project in the current directory and connects the servers in its `.mcp.json`, so it must not run in `~/mail-workspace` or the repository |
| No `--bare` | Bare mode ignores the subscription sign-in and only accepts `ANTHROPIC_API_KEY` |
| `ANTHROPIC_API_KEY` removed | With this variable set, claude switches to the API key and per-token billing. The program removes it and `ANTHROPIC_AUTH_TOKEN` from the environment before each call |
| Mail goes in on standard input | It never appears in the command line, so other programs cannot see it with `ps` |

**Two changes from the October 17 design**:

- **One call per message, no batching.** The plan was to put a round's messages into one batch and call once, to save allowance. Batching only saves the repeated prompt, and the price is that injected text in one message could sway the verdicts of the others in the batch. Now, as with the API-key version, each message gets its own call and the verdicts are independent; a round usually has zero to a few messages that need the model.
- **No `--json-schema`.** Claude Code implements structured output with an internal tool (StructuredOutput), and this call turns every tool off; the official docs do not say whether the two work together reliably. So, as with the API-key version, the prompt asks for JSON only and the program validates it.

**When something goes wrong**:

| Situation | What the program does |
|---|---|
| claude is not signed in, or the sign-in expired | Stops calling claude for the rest of the round; mail the rules do not settle is pushed as "unsure" as usual; the `run` output and the log say to run claude in a terminal and type /login |
| The subscription allowance is used up for now | Same; once the allowance resets, the next round works again |
| claude is not found, or is too old | Same, with a hint to install Claude Code or run `claude update` |
| Timeout (180 seconds by default) | Same; if it hangs once it will probably hang again, for example when the network is down, so the round stops waiting |
| No JSON in the answer | One retry, then that message is pushed as "unsure" |

`mail-monitor doctor` checks with `claude --version` and `claude auth status`: whether the version is new enough, and whether the sign-in is a subscription (`authMethod` is `claude.ai`, or `oauth_token` for a long-lived token from `claude setup-token`). An API-key sign-in or a third-party cloud (Bedrock and the like) is reported as an error.

**Usage**: one call per message that needs a verdict. The input is the prompt, memory and the first 4,000 characters of the body; the output is a JSON object of a few hundred characters. It counts against your subscription and shares the allowance with your own use of Claude. To use less: write more rules (mail the rules settle never reaches the model), or switch the model to `haiku`.

### Switching backends

```bash
MAIL_MONITOR_LLM=api        # api (default) | claude; chatgpt is not built yet
```

Both backends sit behind one interface in the code, `chat_json(system, user) -> dict`: the API-key version in `llm.py`, the Claude subscription version in `claude_cli.py`. The prompt, output structure, Pydantic validation, retry and fallback all live in the verdict layer (`classify.py`) and are shared; the only new thing the verdict layer knows is that errors such as "not signed in" or "allowance used up" are not worth retrying. Tests use a fake `claude` command (`tests/fake_claude.py`), with no real account.

## Where your data goes

All backends send the same thing: for mail the rules do not settle, the sender, recipients, subject, time, the first 4,000 characters of the body (`LLM_BODY_CHARS`), related memory, and your profile. Mail a rule settles outright, such as verification codes and newsletters, goes to no model. What differs is who receives it:

| Backend | Sent to | How they handle it (per their official docs) |
|---|---|---|
| API key (DeepSeek) | DeepSeek | The privacy policy (2026-02-10 version) says data is collected, processed and stored in the People's Republic of China |
| ChatGPT subscription | OpenAI | Requests must carry `store: false`; the authorization only lets the program run requests on your plan and gives it no access to your ChatGPT conversations |
| Claude subscription | Anthropic | Follows your account's "Help improve Claude" setting: on means it may be used for training and kept 5 years, off means kept 30 days; nothing stays on your computer (see `--no-session-persistence` above) |
| Local model | Stays on your computer | |

Before sending an institutional mailbox (a university account, say) to an outside model, check the institution's data rules. To keep one mailbox's content from going out, either leave it out with `MAIL_MONITOR_ACCOUNTS`, or add a rule at the **end** of `rules.yaml` that matches the account and settles its mail outright; new mail there is then pushed with only the subject and preview, never passing through the model:

```yaml
  - name: University mail stays away from the model
    match:
      account: ["mbzuai"]       # part of the account name or id
    then:
      needs_action: "unsure"    # unsure → pushed right away
```

Putting it last keeps the earlier rules (verification codes, newsletters) working for that mailbox too.

## Sources (checked 2026-10-17; the Claude part rechecked 2026-10-27)

- Claude Code: [Legal and compliance (authentication and credential use)](https://code.claude.com/docs/en/legal-and-compliance), [Run Claude Code programmatically](https://code.claude.com/docs/en/headless), [CLI reference](https://code.claude.com/docs/en/cli-reference), [Data usage](https://code.claude.com/docs/en/data-usage), [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Structured outputs](https://code.claude.com/docs/en/agent-sdk/structured-outputs), [v2.1.169 release notes (--safe-mode)](https://github.com/anthropics/claude-code/releases/tag/v2.1.169)
- OpenAI: [Integrating Sign in with ChatGPT in your open-source app](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt), [ChatGPT plan usage overview](https://developers.openai.com/siwc/token-sharing-open-source), [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in), [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference), [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations), [Help center: using your ChatGPT plan in other apps and sites](https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites), [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive)
- DeepSeek: [Change log](https://api-docs.deepseek.com/updates/), [Models and pricing](https://api-docs.deepseek.com/quick_start/pricing/), [Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/), [Privacy policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)
