# 常见问题和排错

**中文** | [English](faq_EN.md)

先跑一次 `mail-monitor doctor`。它只检查、不改动，大部分问题它能直接指出来。用 launchd 定时跑时，日志在 `~/.mail-monitor/logs/`。

## 安装

**install.sh 说 Python 版本太低，或者没找到 Python**

macOS 自带的 `python3` 常常是 3.9，而这个程序要 3.10 以上。脚本会自己找装过的 `python3.13`、`python3.12` 这类新版本，都没有才报错。任选一种装法，装好后重新运行 `./scripts/install.sh`：

- 官方安装包（不需要 Homebrew）：到 [python.org](https://www.python.org/downloads/macos/) 下载 Python 3.13 的 macOS 安装包，双击安装。
- Homebrew：`brew install python@3.13`。
- uv（装在你的用户目录里，不要管理员密码）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv python install 3.13
PYTHON="$(~/.local/bin/uv python find 3.13)" ./scripts/install.sh
```

**提示 `mail-monitor: command not found`**

没激活虚拟环境。先 `source ~/thunderbird-mail-agent/monitor/.venv/bin/activate`，或者直接用完整路径 `~/thunderbird-mail-agent/monitor/.venv/bin/mail-monitor`。

## 连接 Thunderbird

**doctor 显示"连不上 Thunderbird"**

- Thunderbird 没开，或者 Thunderbird MCP 扩展被禁用了。
- 刚装完扩展，还没重启 Thunderbird。
- bridge 不在默认位置 `~/thunderbird-mcp/mcp-bridge.cjs`：在 `.env` 里写 `MAIL_MONITOR_BRIDGE=实际路径`。
- 找不到 `node`：在 `.env` 里写 `MAIL_MONITOR_NODE_BIN=node 的完整路径`（`which node` 能查到）。用 launchd 跑时，`launchd.sh install` 会把当时 node 所在的目录写进 PATH，换过 Node 版本要重新 install 一次。
- 仓库根目录的 `./scripts/doctor.sh` 能检查扩展本身装得对不对。

**doctor 显示"缺少必需工具"**

在扩展的 Tool Access 里打开 `listAccounts`、`listFolders`、`getRecentMessages`、`getMessages`。

**少了某个邮箱，或者"没有找到任何收件箱"**

多半是 `MAIL_MONITOR_ACCOUNTS` 写错了。它按账号 id 或名字的一部分匹配，删掉这一行就是看全部。

## 推送

**第一次 run 推了一大堆旧邮件**

装好后要先跑一次 `mail-monitor init`，把现有的邮件登记为已见。现在没跑过 init 的话，`./scripts/launchd.sh install` 会停下来提醒你。

**手机上没收到**

- 先跑 `mail-monitor notify-test`，看它报什么错。
- 用 notify_hub 的：先跑 `notify-hub test`，它通了邮件监控才会通。`mail-monitor doctor` 里看不到 notify-hub 的版本，就是找不到这个命令：终端里 `which notify-hub` 看它装在哪，写进 `.env` 的 `MAIL_MONITOR_NOTIFY_HUB_BIN`。`notify-test` 说"没发出去，留在发件箱里"，是 notify-hub 连不上 Lark，它会自己重发，`notify-hub status` 能看到发件箱里还有几条。
- 应用机器人：权限开了没有（`im:message:send_as_bot`），版本发布了没有，机器人在不在那个群里，`LARK_RECEIVE_ID` 对不对（`oc_` 开头是群，`ou_` 开头是你本人）；另外写了 `LARK_RECEIVE_ID_TYPE` 的话，要和 id 对得上（`chat_id` 配群 id，`open_id` 配你的用户 id），不确定就删掉这一行让程序自己判断。
- 群自定义机器人：群里开了签名校验的话，`LARK_WEBHOOK_SECRET` 要填。
- 飞书国内版要把 `LARK_DOMAIN` 改成 `https://open.feishu.cn`。
- 推送失败的邮件不会丢，会转进下一次汇总。

**夜里来的邮件，早上才收到**

用 notify_hub 推送时，这是 notify-hub 的免打扰：23:00 到 08:00 之间的普通消息先存着，08:00 合成一张卡发。规则里写了 `urgency: high` 的（`rules.example.yaml` 里导师那条）按紧急发，夜里也推；想让某个人的邮件夜里也推，就给他写一条这样的规则。模型判断的"紧急"不算，因为它会被邮件措辞带偏。免打扰时段在 notify-hub 的 `.env` 里改：`NOTIFY_HUB_QUIET_HOURS=23:00-08:00`，写 `off` 关掉。

另外 notify-hub 对同一个来源一小时最多推 20 条，再多的进它每天 18:00 的汇总，一般碰不到；要改是 `NOTIFY_HUB_RATE_LIMIT`。

**推得太多**

- 拿不准的一律即时推送，这是故意的：漏掉一封要紧的邮件，比多看一条推送糟糕。
- 用一两周后跑 `mail-monitor review` 标一标，再看 `mail-monitor eval` 里噪声都是哪些邮件，给它们写规则，比如某个通知地址写 `needs_action: "no"`、`notify: digest`。改完用 `mail-monitor rules --from "某某 <x@example.com>" --subject "…"` 试一下命中了哪条。
- 在 `.env` 里写 `MAIL_MONITOR_PROFILE`，模型知道你是谁、在找什么工作，判断会准一些。
- 用 `mail-monitor sender-set 地址 身份` 告诉它某个人是谁。

**漏推**

在 `review` 里把漏掉的标成 y，`eval` 会算出漏推了几封。找到规律后写规则，比如导师的地址写 `needs_action: "yes"`、`notify: instant`。

## 模型

**doctor 说 DeepSeek 已经停用某个模型名**

DeepSeek 在 2026-07-24 停用了 `deepseek-chat` 和 `deepseek-reasoner`。在 `.env` 里改成 `LLM_MODEL=deepseek-flash`。

**推送末尾写着"没有模型判断，按「拿不准」推送"**

这封邮件没有经过模型：要么 `.env` 里既没填 key、也没开 Claude 订阅版，要么模型出错了。`mail-monitor run` 的输出和日志里的"LLM 判断失败"会写原因。DeepSeek 常见的几种：

| 报错 | 原因 |
|---|---|
| HTTP 401 | key 不对 |
| HTTP 402 | 账户余额不足 |
| HTTP 400 或 422 | 请求或参数不对，比如模型名写错了 |
| HTTP 429 | 请求太快 |
| 模型没有返回 JSON | 偶尔会有，重试一次通常就好；经常出现的话把日志贴出来 |

**用 Claude 订阅版时，doctor 说运行不了 claude（No such file or directory）**

终端里还没有 `claude` 命令。装 Claude Code 的命令行版，再登录：

```bash
curl -fsSL https://claude.ai/install.sh | bash
~/.local/bin/claude auth login
```

PATH 里没有 `claude` 时，程序会自己去 `~/.local/bin/claude` 找；装在别处的话，把完整路径写进 `.env` 的 `MAIL_MONITOR_CLAUDE_BIN`。

**用 Claude 订阅版时，doctor 说 claude 没登录、或者用的是 API key**

在终端运行 `claude`，输入 `/login`，选用 Claude 账号（Pro / Max）登录，再跑一次 `mail-monitor doctor`。用 API key 登录会按量计费，不算订阅。

**用 Claude 订阅版时，日志说订阅额度用完了**

订阅额度和你平时用 Claude 是共用的。用完的这段时间，规则没定性的邮件照常按「拿不准」推送，不会漏；额度恢复后自动恢复。想少用一点：多写规则，或者在 `.env` 里设 `MAIL_MONITOR_CLAUDE_MODEL=haiku`。

**终端里能跑，launchd 定时跑时说找不到 claude**

launchd 的 PATH 和终端不一样。用 `which claude` 看完整路径，写进 `.env` 的 `MAIL_MONITOR_CLAUDE_BIN`；或者重新运行 `./scripts/launchd.sh install`，它会把当时 claude 所在的目录写进 PATH。

**想换别家模型、本地模型，或者用 ChatGPT 订阅代替 API key**

见 [模型后端](model-backends.md)。ChatGPT 订阅版的设计已经定了，代码还没写。

## 定时运行

**launchd 装了但好像没跑**

- `./scripts/launchd.sh status` 能看到装没装、上次的退出码和日志最后几行。
- Mac 睡眠时不跑，醒来后会补跑一次。
- 电脑关了或合盖超过 2 天，更早的邮件不会再自动判断，可以手动补一次：`mail-monitor run --days 7`。

**想改频率或汇总时间**

```bash
RUN_INTERVAL=120 DIGEST_HOURS="8 13 20" ./scripts/launchd.sh install
```

## 数据和隐私

**它会改我的邮箱吗？**

默认不会。唯一的写操作是给要管的邮件打一个 Thunderbird 标签，要在 `.env` 里写 `MAIL_MONITOR_ACTION_TAG=true` 才会开。程序里没有任何调用发信、删信工具的代码。

**哪些内容会发出去？**

规则没定性的邮件会发给模型，推送到 Lark 的只有一句话摘要。完整的表见 [架构说明](architecture.md#7-数据去哪了)；各个模型后端分别发给谁、对方怎么处理，见 [模型后端](model-backends.md#数据去哪了)。不想让某个邮箱的内容发给模型，那一页也写了怎么用一条规则做到。

**数据库在哪？想从头来怎么办？**

在 `~/.mail-monitor/state.db`。删掉它，再跑一次 `mail-monitor init`，就是从头开始。发件人身份和你标的答案也会一起没掉，要留的话先备份这个文件。

**推送里让我点链接、付款、给验证码**

推送是模型写的摘要，模型会被邮件内容影响。凡是要你点链接、付钱、给密码或验证码的，回原邮件看清楚发件人再说。
