# 模型后端：API key 版和订阅版

**中文** | [English](model-backends_EN.md)

判断层只需要模型做一件事：给它一段提示词，它还回来一个 JSON（谁、什么事、要不要管……）。谁来回答这个问题，就是"模型后端"。计划支持两类：

- **API key 版**：程序拿你的 API key 直接调模型接口，按 token 付费。**已实现**，默认用 DeepSeek。
- **订阅版**：已经在付 ChatGPT 或 Claude 的月费，就用套餐里的额度，不用另开 API。**设计已定，代码还没写**。

## 一览

| | API key 版 | ChatGPT 订阅版 | Claude 订阅版 |
|---|---|---|---|
| 状态 | 已实现 | 设计已定，代码还没写 | 设计已定，代码还没写 |
| 需要什么 | 一个 API key（默认 DeepSeek） | ChatGPT 付费套餐，浏览器里授权一次 | Claude Pro / Max，Mac 上装好并登录 Claude Code |
| 怎么调 | 程序直接请求 `/chat/completions` | 程序直接请求 OpenAI 的 `/v1/responses`，带授权拿到的令牌 | 程序调用你电脑上的 `claude -p` 命令 |
| 花钱 | 按 token 计费，deepseek-flash 每封不到 0.1 美分 | 不另外花钱，算在套餐用量里 | 不另外花钱，算在套餐用量里 |
| 快慢 | 快 | 和 API 差不多 | 最慢：每次要启动一次 Claude Code |
| 官方态度 | 正常用法 | 2026 年 9 月起对开源项目和本地运行的个人项目开放 | 只允许你自己用官方的 Claude Code；第三方程序不能借用订阅 |
| 能不能给别人用 | 能 | 开源、本地运行可以；收费或托管的产品要先向 OpenAI 申请 | 不能 |

三种后端共用同一套提示词、同一个输出结构、同一套校验和保底，所以换后端不影响判断逻辑，只影响"问谁"。

## API key 版（现在能用）

在 `~/.mail-monitor/.env` 里填：

```bash
DEEPSEEK_API_KEY=sk-...
LLM_MODEL=deepseek-flash      # 可选，默认就是它
```

程序向 `{LLM_BASE_URL}/chat/completions` 发一个请求，用 JSON 模式（`response_format: {"type": "json_object"}`）要求只输出 JSON，温度 0，最多 800 个 token。没有用任何厂商的 SDK，一个 HTTP 请求就够了。

**DeepSeek 今年的两个变化**（以下都按 2026-10-17 的官方文档）：

1. `deepseek-chat` 和 `deepseek-reasoner` 两个老名字已经在 2026-07-24 停用。现在的模型是 `deepseek-flash`（便宜，分诊够用）和 `deepseek-v4-pro`。还写着老名字的话，`mail-monitor doctor` 会提示。
2. 思考模式默认打开。分诊用不着长推理，打开只会更慢、更贵，还可能把 800 个 token 的上限用在思考上、来不及输出 JSON。所以接 DeepSeek 时程序默认在请求里加 `"thinking": {"type": "disabled"}`。想自己控制，就设 `LLM_EXTRA_BODY`（一个 JSON 对象，原样并进请求体；写 `{}` 就什么都不加）。

**费用**：一封邮件连提示词、记忆和正文大约 1 千到 4 千 token，输出两三百 token。按 2026 年 10 月 deepseek-flash 的高峰价（输入每百万 0.3 美元，输出 1.2 美元），每封不到 0.1 美分，一天 50 封一个月不到 2 美元。验证码、订阅这类规则直接定性的邮件不调模型，实际更少。

**换别家**：改 `LLM_BASE_URL`、`LLM_MODEL`，key 填在 `LLM_API_KEY`。要求接口兼容 OpenAI 的 `/chat/completions`，并且支持 JSON 模式。目前只按 DeepSeek 的接口写过测试，各家对 `temperature`、`max_tokens` 这类参数的要求不完全一样，第一次用先跑 `mail-monitor run --dry-run` 看看；私有参数用 `LLM_EXTRA_BODY` 传。

**本地模型**（例如 Ollama 的 OpenAI 兼容接口 `http://localhost:11434/v1`）：邮件内容完全不出本机，适合不方便把内容发给外部服务的邮箱。判断质量取决于本机能跑多大的模型。

Claude 的 API key 也能接，但 Anthropic 有自己的接口和官方 SDK，需要另写一个后端，目前没做。

## 订阅版（设计已定，代码还没写）

### 为什么不能"直接调两家内部的模型"

ChatGPT Plus / Pro、Claude Pro / Max 这些订阅本身不带 API，是给两家自己的 App 用的。程序想用订阅额度，只能走两家明确允许的路，而两家允许的路不一样：

- **OpenAI** 在 2026 年 9 月开放了"Sign in with ChatGPT"的套餐额度功能，对象是开源项目、本地运行的个人项目和少数审核过的私有应用：用户在浏览器里授权以后，程序可以直接调 OpenAI 的 Responses API，算在用户自己的套餐里。本项目开源、跑在你自己的电脑上，正好在范围内。
- **Anthropic** 的规定是：订阅账号的登录只用于 Claude Code 和 Anthropic 自己的应用；开发产品（包括用 Agent SDK 做的）要用 API key；第三方程序不能提供 Claude 账号登录、不能替用户走 Free / Pro / Max 的额度，也不能收集或保存 Claude 的登录凭证。但这不妨碍你用自己的订阅登录官方、未修改的 Claude Code。所以 Claude 版不碰任何令牌，只调用你自己装好、登录好的 `claude` 命令。

两家的规则今年都变过，用之前再看一眼文末的原文链接。

### ChatGPT 订阅版：Sign in with ChatGPT

1. **授权一次**：运行 `mail-monitor chatgpt-login`（计划中的命令）。程序在 `127.0.0.1` 上临时开一个回调端口，打开浏览器到 OpenAI 的登录页（OAuth，带 PKCE）。你登录 ChatGPT，同意这个程序使用你的套餐额度。OpenAI 在这一步给程序动态注册一个 client，不需要 client secret，也不需要 API key。
2. **保存令牌**：拿到的 access token 和会轮换的 refresh token 存进 `~/.mail-monitor/chatgpt-auth.json`，权限 600，不进仓库、不写日志。过期了程序自己用 refresh token 续，launchd 定时跑也不用再登录。
3. **判断一封邮件**：

   ```http
   POST https://api.openai.com/v1/responses
   Authorization: Bearer <授权拿到的 access token>

   {"model": "<你账号能用的模型>", "instructions": "<分诊提示词>", "input": "<这封邮件的元数据、记忆、正文>",
    "store": false, "stream": true}
   ```

   这条路要求 `store: false`（OpenAI 不保存这次对话）和 `stream: true`；不收 `system` 角色的消息，所以提示词放在 `instructions` 里；不支持 `temperature`、`max_output_tokens` 这类参数。可用的模型从 `/v1/models` 里查你的账号能用哪些。
4. **额度用完**：接口会返回 `subscription_sharing_usage_limit_exceeded` 一类的错误，程序和现在一样退回"拿不准"照常推送，不会漏邮件。在 ChatGPT 的 设置 → 用量 里可以给这个程序设每周上限。

写代码时还要实测一件事：这条路的文档没写支不支持用 JSON schema 约束输出。不支持也不要紧，提示词本来就要求只输出 JSON，程序会校验、重试一次、再不行退回"拿不准"。

**备选**：`codex exec --output-schema`（Codex CLI 用它保存的 ChatGPT 登录）也能做到。但它每次都启动一个带命令行工具的 Agent，还会加载 `~/.codex/config.toml` 里的 MCP 服务器（本仓库的 `setup-codex.sh` 会把邮件工具写进去，得用 `--ignore-user-config` 关掉），OpenAI 也说自动化场景默认该用 API key。所以只当备选。

### Claude 订阅版：调用本机已登录的 Claude Code

**只给你自己用**：你的 Mac、你自己的订阅、官方的 `claude` 命令。程序不读、不存任何 Claude 的令牌，也不能把它部署成给别人用的服务。Pro / Max 的额度按"普通个人使用"设计，所以每次巡检最多调用一次：把这一轮需要模型判断的邮件合成一批（最多 10 封）。

计划的调用方式：

```bash
cd ~/.mail-monitor/claude-run          # 一个空目录
claude -p \
  --model sonnet \
  --system-prompt-file <分诊提示词> \
  --output-format json --json-schema '<一批判断结果的 schema>' \
  --tools "" --strict-mcp-config --disallowedTools "mcp__*" \
  --permission-prompts none \
  --no-session-persistence \
  < <这批邮件>
```

结果在返回 JSON 的 `structured_output` 字段里，已经按 schema 校验过；程序再按编号把结果对回每封邮件。每个参数为什么要加：

| 参数 | 为什么 |
|---|---|
| `--system-prompt-file` | 整个替换 Claude Code 默认的编程助手提示词。官方文档的建议是：身份和权限都和编程无关、没人盯着的流水线，就该整个替换。也更省额度 |
| `--output-format json --json-schema` | 让结果按我们的结构输出，放在 `structured_output` 字段 |
| `--tools ""`、`--strict-mcp-config`、`--disallowedTools "mcp__*"` | 不给任何工具。本仓库的 `setup-claude-code.sh` 会把邮件工具装成用户级 MCP，不关的话，读邮件的这个 Claude 就能调发信、改邮件的工具；邮件内容是不可信的，"有人在邮件里写一句话让它转发收件箱"就成了真实风险 |
| `--permission-prompts none` | 没人在电脑前点"允许"，有权限请求就直接拒绝（需要 Claude Code v2.1.259 以上） |
| `--no-session-persistence` | 不把会话存进 `~/.claude/projects/`。那里默认明文保存 30 天，而会话里全是邮件内容 |
| 在空目录里运行 | 不加 `--bare` 时，`claude -p` 会执行当前目录项目里的 hooks、连接 `.mcp.json` 里的服务器，所以不能在 `~/mail-workspace` 或仓库目录里跑 |
| 不加 `--bare` | bare 模式不读订阅登录，只认 `ANTHROPIC_API_KEY` |
| 邮件从标准输入传 | 不出现在命令行参数里，别的程序用 `ps` 看不到邮件内容 |

`mail-monitor doctor` 会用 `claude auth status` 检查登录方式是不是订阅（`authMethod` 为 `claude.ai`）。

**合成一批的代价**：同一批里，一封邮件里的注入文字可能影响别的邮件的判断。因为没有任何工具可调，最坏结果是判错；每封邮件用编号和分隔符包起来，缺了或对不上的那封退回"拿不准"，仍然会推送。

### 统一的开关（计划）

```bash
MAIL_MONITOR_LLM=api        # api（默认）| chatgpt | claude
```

三种后端都只做"提示词进、JSON 出"，在程序里是同一个接口 `chat_json(system, user) -> dict`。提示词、输出结构、Pydantic 校验、失败重试、退回"拿不准"都在判断层，三种后端共用，`classify.py` 不用改。测试用假的 `claude` 命令和假的 Responses 接口，不需要真账号。

## 数据去哪了

三种后端发出去的内容一样：规则没定性的邮件的发件人、收件人、主题、时间、正文前 4000 字（`LLM_BODY_CHARS`）、相关记忆，以及你的画像。验证码、订阅这类规则直接定性的邮件不发给任何模型。区别在发给谁：

| 后端 | 发给谁 | 对方怎么处理（按官方文档） |
|---|---|---|
| API key 版（DeepSeek） | DeepSeek | 隐私政策（2026-02-10 版）写明数据在中国境内收集、处理和存储 |
| ChatGPT 订阅版 | OpenAI | 请求必须带 `store: false`；授权只让程序用你的套餐跑请求，看不到你的 ChatGPT 聊天记录 |
| Claude 订阅版 | Anthropic | 按你账号的"帮助改进 Claude"开关：开着会用于训练、保留 5 年，关着保留 30 天；本机不留会话记录（见上面的 `--no-session-persistence`） |
| 本地模型 | 不出本机 | |

机构邮箱（比如学校邮箱）的内容发给外部模型之前，先看看学校的数据规定。不想让某个邮箱的内容发出去，有两个办法：用 `MAIL_MONITOR_ACCOUNTS` 不看它；或者在 `rules.yaml` 的**最后**加一条按账号匹配、直接定性的规则，这个邮箱的新邮件就只按标题和预览推送，不经过模型：

```yaml
  - name: 学校邮箱不发给模型
    match:
      account: ["mbzuai"]       # 账号名或 id 的一部分
    then:
      needs_action: "unsure"    # 拿不准 → 即时推送
```

放在最后，前面的验证码、订阅规则对这个邮箱照样生效。

## 参考（2026-10-17 查阅）

- Claude Code：[法律与合规（认证和凭证的使用）](https://code.claude.com/docs/en/legal-and-compliance)、[非交互模式](https://code.claude.com/docs/en/headless)、[命令行参数](https://code.claude.com/docs/en/cli-reference)、[数据使用](https://code.claude.com/docs/en/data-usage)、[Agent SDK 概览](https://code.claude.com/docs/en/agent-sdk/overview)
- OpenAI：[在开源应用里接入 Sign in with ChatGPT](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt)、[套餐额度概览](https://developers.openai.com/siwc/token-sharing-open-source)、[登录和注册](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)、[模型和请求](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)、[预览期限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)、[帮助中心：在其他应用里使用 ChatGPT 套餐](https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites)、[Codex 非交互模式](https://developers.openai.com/codex/noninteractive)
- DeepSeek：[更新日志](https://api-docs.deepseek.com/updates/)、[模型和价格](https://api-docs.deepseek.com/quick_start/pricing/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)、[隐私政策](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)
