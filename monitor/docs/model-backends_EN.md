# Model backends: the API-key version and the subscription version

[中文](model-backends.md) | **English**

The verdict layer needs exactly one thing from a model: send it a prompt, get back a JSON object (who, what, does it need action …). Whoever answers that request is the "model backend". Two kinds are planned:

- **API-key version**: the program calls a model API with your key and you pay per token. **Built**, DeepSeek by default.
- **Subscription version**: if you already pay for ChatGPT or Claude, use the plan's allowance instead of opening an API account. **Designed, not yet built**.

## At a glance

| | API-key version | ChatGPT subscription | Claude subscription |
|---|---|---|---|
| Status | Built | Designed, not yet built | Designed, not yet built |
| You need | An API key (DeepSeek by default) | A paid ChatGPT plan, authorized once in the browser | Claude Pro / Max, with Claude Code installed and signed in on the Mac |
| How it is called | The program posts to `/chat/completions` | The program posts to OpenAI's `/v1/responses` with the token from that authorization | The program runs the `claude -p` command on your computer |
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

## The subscription version (designed, not yet built)

### Why it cannot "just call the vendor's models directly"

ChatGPT Plus / Pro and Claude Pro / Max come without an API; they are for the vendors' own apps. A program can only use a plan's allowance through a route the vendor explicitly allows, and the two vendors allow different routes:

- **OpenAI** opened plan usage through "Sign in with ChatGPT" in September 2026 to open-source projects, personal projects that run locally, and a few approved private apps. Once the user authorizes in the browser, the program can call OpenAI's Responses API directly, billed to the user's own plan. This project is open source and runs on your own computer, so it qualifies.
- **Anthropic** allows subscription sign-in only for Claude Code and Anthropic's own apps. Developers building products, including with the Agent SDK, must use API keys; third-party programs may not offer Claude sign-in, may not route requests through Free / Pro / Max plans, and may not collect or store Claude credentials. None of this stops you from signing in to the official, unmodified Claude Code with your own subscription. So the Claude version touches no tokens at all; it only runs the `claude` command you installed and signed in to yourself.

Both vendors changed their rules this year; check the sources at the end before relying on this.

### ChatGPT subscription: Sign in with ChatGPT

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

### Claude subscription: call the Claude Code you are signed in to

**For you only**: your Mac, your own subscription, the official `claude` command. The program never reads or stores any Claude token, and it must not be deployed as a service for other people. Pro / Max limits assume ordinary individual use, so each check makes at most one call: the messages that need the model in that round go in one batch (at most 10).

The planned call:

```bash
cd ~/.mail-monitor/claude-run          # an empty directory
claude -p \
  --model sonnet \
  --system-prompt-file <triage prompt> \
  --output-format json --json-schema '<schema for a batch of verdicts>' \
  --tools "" --strict-mcp-config --disallowedTools "mcp__*" \
  --permission-prompts none \
  --no-session-persistence \
  < <this batch of mail>
```

The result is in the `structured_output` field of the returned JSON, already validated against the schema; the program matches results back to messages by number. Why each flag is there:

| Flag | Why |
|---|---|
| `--system-prompt-file` | Replaces Claude Code's default coding-assistant prompt entirely. The official guidance is to replace it for a pipeline nobody watches whose identity and permissions have nothing to do with coding. It also uses less of the allowance |
| `--output-format json --json-schema` | Returns the result in our structure, in the `structured_output` field |
| `--tools ""`, `--strict-mcp-config`, `--disallowedTools "mcp__*"` | No tools at all. This repository's `setup-claude-code.sh` installs the mail tools as a user-level MCP server; without these flags, the Claude reading your mail could call tools that send or change mail. Mail content is untrusted, so "one sentence in an email makes it forward the inbox" becomes a real risk |
| `--permission-prompts none` | Nobody is at the computer to click "Allow", so any permission request is denied (needs Claude Code v2.1.259 or later) |
| `--no-session-persistence` | Keeps the session out of `~/.claude/projects/`, where it would otherwise be stored in plain text for 30 days, and the session is full of mail |
| Run in an empty directory | Without `--bare`, `claude -p` runs the hooks of the project in the current directory and connects the servers in its `.mcp.json`, so it must not run in `~/mail-workspace` or the repository |
| No `--bare` | Bare mode ignores the subscription sign-in and only accepts `ANTHROPIC_API_KEY` |
| Mail goes in on standard input | It never appears in the command line, so other programs cannot see it with `ps` |

`mail-monitor doctor` will use `claude auth status` to check that the sign-in is a subscription (`authMethod` is `claude.ai`).

**The cost of batching**: injected text in one message could sway the verdicts of the others in the same batch. With no tools to call, the worst case is a wrong verdict; each message is wrapped in a number and delimiters, and a message whose result is missing or does not match falls back to "unsure" and is still pushed.

### One switch for all of them (planned)

```bash
MAIL_MONITOR_LLM=api        # api (default) | chatgpt | claude
```

Every backend only does "prompt in, JSON out", behind one interface in the code: `chat_json(system, user) -> dict`. The prompt, output structure, Pydantic validation, retry and fallback all live in the verdict layer and are shared, so `classify.py` does not change. Tests use a fake `claude` command and a fake Responses endpoint, with no real account.

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

## Sources (checked 2026-10-17)

- Claude Code: [Legal and compliance (authentication and credential use)](https://code.claude.com/docs/en/legal-and-compliance), [Run Claude Code programmatically](https://code.claude.com/docs/en/headless), [CLI reference](https://code.claude.com/docs/en/cli-reference), [Data usage](https://code.claude.com/docs/en/data-usage), [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- OpenAI: [Integrating Sign in with ChatGPT in your open-source app](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt), [ChatGPT plan usage overview](https://developers.openai.com/siwc/token-sharing-open-source), [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in), [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference), [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations), [Help center: using your ChatGPT plan in other apps and sites](https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites), [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive)
- DeepSeek: [Change log](https://api-docs.deepseek.com/updates/), [Models and pricing](https://api-docs.deepseek.com/quick_start/pricing/), [Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/), [Privacy policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)
