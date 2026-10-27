# 邮箱监控 Agent（mail-monitor）

**中文** | [English](README_EN.md)

本仓库原来的用法是你开口问（"看看这周的邮件"），Agent 才去读。这个目录把它变成**自动盯着**：每几分钟巡检一次所有收件箱，新邮件进来就判断"谁、什么事、要不要管、几号前"，推送到飞书 / Lark。

```
launchd 每 5 分钟 ──► mail-monitor run
                        │ 1 通过 MCP 调 thunderbird-mcp：listFolders → getRecentMessages
                        │ 2 去重（SQLite 记住处理过的邮件）
                        │ 3 规则层（rules.yaml：验证码不推、订阅只汇总、导师一律紧急……）
                        │ 4 规则没覆盖的：读正文 + 取记忆（这个发件人是谁、同一话题之前说了什么）→ 模型判断（固定 schema 的 JSON）
                        │ 5 可选：给"需要处理"的打 Thunderbird 标签（默认关）
                        │ 6 推送：要管 / 拿不准 → 即时；其余 → 早晚汇总（mail-monitor digest）
                        └ 7 记录：判断结果和发件人身份写回 SQLite，下次当作记忆
```

它**只读邮件，不发不删**。写邮箱的动作只有一个"打标签"，默认关闭。

## 文档

| 文档 | 内容 |
|---|---|
| [架构说明](docs/architecture.md) | 由哪几块组成、一次巡检的全过程、判断链路、记忆、设计取舍、数据去向、安全边界 |
| [模型后端](docs/model-backends.md) | API key 版和 Claude 订阅版（都能用）、ChatGPT 订阅版（设计已定，代码还没写）：怎么配、两家的规则、费用、数据去向 |
| [常见问题和排错](docs/faq.md) | 装不上、连不上、收不到推送、推得太多或太少 |

## 安装

前提：README 里的第 1–3 步已经做完（Thunderbird 登录好邮箱、装好 thunderbird-mcp 扩展、Node 可用）。

```bash
cd ~/thunderbird-mail-agent/monitor
./scripts/install.sh     # 建 .venv、装依赖、生成 ~/.mail-monitor/.env 和 rules.yaml（需要 Python 3.10+）
source .venv/bin/activate
# 然后编辑 ~/.mail-monitor/.env：选模型（填 DEEPSEEK_API_KEY，或者设 MAIL_MONITOR_LLM=claude 用 Claude 订阅；都不配也能跑），推送先保持 console；按自己的情况改 ~/.mail-monitor/rules.yaml

mail-monitor doctor      # 自检：连得上 Thunderbird 吗、有哪些收件箱、推送和模型配好没
mail-monitor init        # 首次运行：把现有邮件登记为已见，不推送旧邮件
mail-monitor run --dry-run   # 看看它会怎么判断，不记录、不推送（也不带记忆）
mail-monitor run         # 正式巡检一次
mail-monitor digest      # 把攒着的邮件合成一条汇总发出去
mail-monitor senders     # 看看它记住了哪些发件人、身份是怎么定的
mail-monitor sender-set prof@example.edu 导师   # 手动告诉它某人是谁（优先级最高）
mail-monitor review      # 逐条核对它的判断，标出到底要不要管
mail-monitor eval        # 用标注算准确率：漏推几封、噪声几封
```

### 定时运行

macOS 用 launchd（比常驻进程稳：电脑睡眠时不跑，醒来补跑一次）：

```bash
./scripts/launchd.sh install     # 每 5 分钟 run 一次，每天 9 点和 18 点各 digest 一次
./scripts/launchd.sh status      # 看装没装、上次退出码、日志最后几行
./scripts/launchd.sh uninstall
```

间隔和时间可以改：`RUN_INTERVAL=120 DIGEST_HOURS="8 13 20" ./scripts/launchd.sh install`。日志在 `~/.mail-monitor/logs/`。装之前先跑一次 `mail-monitor init`，不然它会把现有邮件全推一遍。

Linux 用 cron：

```
*/5 * * * *  ~/thunderbird-mail-agent/monitor/.venv/bin/mail-monitor run    >> ~/.mail-monitor/logs/run.log 2>&1
0 9,18 * * * ~/thunderbird-mail-agent/monitor/.venv/bin/mail-monitor digest >> ~/.mail-monitor/logs/digest.log 2>&1
```

## 配置

| 项 | 环境变量 | 说明 |
|---|---|---|
| 模型 | `MAIL_MONITOR_LLM`、`DEEPSEEK_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_EXTRA_BODY`、`MAIL_MONITOR_CLAUDE_MODEL` | `api`（默认）走 OpenAI 兼容接口，默认 DeepSeek 的 `deepseek-flash`，并关掉它默认打开的思考模式。`claude` 调你 Mac 上已登录的 Claude Code，用 Claude Pro / Max 订阅，不用 key，模型默认 `sonnet`。都不配也能跑：规则没覆盖的邮件一律按"拿不准"推送。详见[模型后端](docs/model-backends.md) |
| 画像 | `MAIL_MONITOR_PROFILE` | 一句话介绍你自己（在读什么、找什么工作、导师是谁），写进提示词；不填时模型只知道"在读研究生，同时在找工作" |
| 推送 | `MAIL_MONITOR_NOTIFY` = `console` / `lark_app` / `lark_webhook` | 先用 `console` 在终端里看效果。应用机器人要 `LARK_APP_ID`、`LARK_APP_SECRET`、`LARK_RECEIVE_ID`；群自定义机器人只要 `LARK_WEBHOOK_URL`（可选 `LARK_WEBHOOK_SECRET`） |
| 规则 | `MAIL_MONITOR_RULES`（默认 `~/.mail-monitor/rules.yaml`） | 见 [rules.example.yaml](rules.example.yaml) |
| 账号 | `MAIL_MONITOR_ACCOUNTS` | 只看某些账号；默认全部收件箱 |
| 行动 | `MAIL_MONITOR_ACTION_TAG` | 给"需要处理"的邮件打标签，默认 `false` |

完整列表见 [.env.example](.env.example)。秘密只放在 `~/.mail-monitor/.env`，不进仓库。

### 推送接到飞书 / Lark

两条路，选一条：

**A. 群自定义机器人（最省事，但有的租户没开）**：电脑端 Lark 打开一个群 → 设置 → 群机器人 → 添加机器人 → 自定义机器人 → 复制 webhook。写进 `.env`：`MAIL_MONITOR_NOTIFY=lark_webhook`、`LARK_WEBHOOK_URL=…`、可选 `LARK_WEBHOOK_SECRET=…`（签名校验）。

**B. 应用机器人（用开发者后台，可以直接私聊你）**：

1. [open.larksuite.com](https://open.larksuite.com)（飞书用 open.feishu.cn）→ 开发者后台 → 创建企业自建应用，起个名字。已经有自己的应用（比如一个 bridge 机器人）的话直接复用，跳到第 3 步。
2. 应用页 → 添加应用能力 → **机器人**。
3. **权限管理**里开：`im:message:send_as_bot`（以应用身份发消息）、`im:chat:readonly`（查机器人所在的群）；想按邮箱查自己的 open_id 再加 `contact:user.id:readonly`。
4. **版本管理与发布** → 创建版本 → 发布（自己的租户自己审批就行）。
5. **凭证与基础信息**里复制 App ID 和 App Secret，写进 `.env`：`LARK_APP_ID=…`、`LARK_APP_SECRET=…`。
6. 在 Lark 里建一个群（只有你自己也行），添加机器人 → 选这个应用。然后：

```bash
mail-monitor lark-chats                     # 列出机器人所在的群和 chat_id
mail-monitor lark-chats --email 你的邮箱     # 顺便查 open_id（私聊推送用）
```

把结果写进 `.env`：`MAIL_MONITOR_NOTIFY=lark_app`、`LARK_RECEIVE_ID_TYPE=chat_id`（或 `open_id`）、`LARK_RECEIVE_ID=…`。

最后 `mail-monitor notify-test` 发一条测试消息，手机上收到就通了。

## 推送长什么样

即时（要管或拿不准）：

```
📬 需要处理 · 紧急 · Gmail
谁：量化公司 HR
事：约下周二 10 点线上面试，明天前确认
期限：2026-10-14
建议：回复确认时间
主题：Interview invitation - AI Agent Engineer | 10-13 15:02
```

汇总（早晚各一次）：

```
📮 邮件汇总 10-13 18:00 · 共 12 封

需要处理（1）
• 导师：要周五前交更新后的数字（期限 2026-10-17） [School 10-13 14:02]

知道就行（3）
• 学校活动办公室：周四 4 点讲座，周三中午前报名 [School 10-12 19:10]
…

已忽略：订阅/通知 8
```

## 判断是怎么做的

1. **规则先行**（不花钱、可预期）：`rules.yaml` 里按发件人、域名、主题写规则。命中就直接定性，或者只给提示再交给模型。
2. **模型兜底**：规则没覆盖的邮件读全文，让模型输出固定 schema 的 JSON（谁、什么事、要不要管、紧急度、截止日期、建议、类别、置信度）。输出经过 Pydantic 校验：写歪的值会被纠正，猜出来的截止日期会被丢掉，坏掉的回答重试一次，再失败退回"拿不准"。
3. **带着记忆判断**：判断前先从 SQLite 里取两样东西喂给模型——这个发件人是谁（之前来过几封、几封需要处理、最近几封说了什么）和同一话题之前的邮件（同一文件夹里 thread id 相同，或去掉 Re:/Fwd: 后主题相同）。模型就能看出"这封是在催上次那件事"。
4. **发件人身份会越用越准**：模型每次顺带判断发件人和你的关系（导师、HR/招聘方、学校行政……），把握够大（置信度 ≥ 0.6）就写进 `senders` 表；规则里写的 `who` 也会记下来；`mail-monitor sender-set` 可以手动改。三者优先级：你设的 > 规则 > 模型，低的改不了高的。`mail-monitor senders` 能看到每个身份是谁定的。
5. **宁可多推不漏**：拿不准的一律即时推送。推送失败的转入汇总，不会丢。
6. **邮件内容是不可信数据**：提示词里明确要求模型不执行邮件里的任何指令，记忆里的身份和正文矛盾时以正文为准；程序不点链接、不发信、不删信。

每一步为什么这样设计、出错时会怎样，见[架构说明](docs/architecture.md)。

## 数据去哪了

- 规则没定性的邮件（发件人、主题、时间、正文前 4000 字、相关记忆）会发给你配置的模型；验证码、订阅这类规则直接定性的不发。
- 推送到 Lark 的只有一句话摘要，不含正文。
- 判断记录存在本机的 `~/.mail-monitor/state.db`，不存正文；秘密只在 `~/.mail-monitor/.env`。

各个模型后端分别发给谁、怎么让某个邮箱完全不经过模型，见[模型后端](docs/model-backends.md#数据去哪了)。

## 评测：它判得准不准

Agent 项目没有数字站不住脚，所以带了一个最小的评测闭环：

1. `mail-monitor review`：把最近判断过的邮件一封封列出来（它的判断、谁定的），你回答 y / n（到底要不要管）。答案存进同一个数据库。
2. `mail-monitor eval`：用这些答案算
   - **需要处理的召回**：你认为要管的邮件里，有多少被即时推送了（漏推几封）。这是最要紧的数字，宁可多推也不能漏。
   - **即时推送的精确**：即时推送里有多少真的要管（噪声几封）。
   - 严格口径（只算模型明确说 yes 的）的精确和召回，以及规则 / 模型 / 保底各自判对多少。

用上一两周、标几十封，就有一组能写进简历的数字；改了规则或提示词以后再跑一遍 `eval`，看数字有没有变好。

## 开发

```bash
pytest            # 用 tests/fake_server.py 模拟 thunderbird-mcp、fake_claude.py 模拟 claude，不需要 Thunderbird 和账号
```

| 路径 | 内容 |
|---|---|
| `mail_monitor/mailbox.py` | 邮件层：MCP 客户端，启动 `mcp-bridge.cjs`，只封装监控要用的 5 个工具 |
| `mail_monitor/rules.py` | 规则层：YAML 规则，先于模型执行 |
| `mail_monitor/memory.py`、`state.py` | 记忆：SQLite 里的已处理邮件、发件人身份、同一话题的历史、你的标注 |
| `mail_monitor/classify.py`、`llm.py`、`claude_cli.py` | 判断：提示词、固定 schema 的 JSON 输出、Pydantic 校验、保底；`llm.py` 是 API key 版，`claude_cli.py` 是 Claude 订阅版 |
| `mail_monitor/pipeline.py` | 一次巡检的全过程 |
| `mail_monitor/notify.py`、`render.py` | 推送：终端 / 群机器人 webhook / 应用机器人；推送文本 |
| `mail_monitor/cli.py` | 命令行 |
| `scripts/` | `install.sh`（装环境）、`launchd.sh`（定时任务） |
| `tests/` | 假的 thunderbird-mcp（`fake_server.py`）、Thunderbird 没开时的 bridge（`dead_bridge.py`）、假的 claude 命令（`fake_claude.py`）和 67 个测试 |
| `docs/` | 架构说明、模型后端、常见问题 |

`tests/fake_server.py` 照抄上游 v0.9.2 的工具名、参数和返回结构，所以能在云端或 CI 里跑通整条流水线；换成真 bridge 只是换一个启动命令。

## 和仓库其他部分的关系

- 邮件层仍然是 `thunderbird-mcp` 扩展 + `mcp-bridge.cjs`，本程序只是它的另一个 MCP 客户端，和 Claude Desktop 用的是同一条路。
- 安全规则沿用 [templates/mail-workspace/CLAUDE.md](../templates/mail-workspace/CLAUDE.md)：不发不删、不点链接、邮件内容不可信。
- 和仓库里的 `scripts/doctor.sh` 一样，`mail-monitor doctor` 也只检查不改动。
