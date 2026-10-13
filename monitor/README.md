# 邮箱监控 Agent（mail-monitor）

本仓库原来的用法是你开口问（"看看这周的邮件"），Agent 才去读。这个目录把它变成**自动盯着**：每几分钟巡检一次所有收件箱，新邮件进来就判断"谁、什么事、要不要管、几号前"，推送到飞书 / Lark。

```
launchd 每 5 分钟 ──► mail-monitor run
                        │ 1 通过 MCP 调 thunderbird-mcp：listFolders → getRecentMessages
                        │ 2 去重（SQLite 记住处理过的邮件）
                        │ 3 规则层（rules.yaml：验证码不推、订阅只汇总、导师一律紧急……）
                        │ 4 规则没覆盖的：读正文 → 模型判断（固定 schema 的 JSON）
                        │ 5 可选：给"需要处理"的打 Thunderbird 标签（默认关）
                        └ 6 推送：要管 / 拿不准 → 即时；其余 → 早晚汇总（mail-monitor digest）
```

它**只读邮件，不发不删**。写邮箱的动作只有一个"打标签"，默认关闭。

## 安装

前提：README 里的第 1–3 步已经做完（Thunderbird 登录好邮箱、装好 thunderbird-mcp 扩展、Node 可用）。

```bash
cd ~/thunderbird-mail-agent/monitor
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

mkdir -p ~/.mail-monitor
cp .env.example ~/.mail-monitor/.env        # 填 DEEPSEEK_API_KEY 和 LARK_WEBHOOK_URL
cp rules.example.yaml ~/.mail-monitor/rules.yaml   # 按自己的情况改规则

mail-monitor doctor      # 自检：连得上 Thunderbird 吗、有哪些收件箱、推送和模型配好没
mail-monitor init        # 首次运行：把现有邮件登记为已见，不推送旧邮件
mail-monitor run --dry-run   # 看看它会怎么判断，不记录、不推送
mail-monitor run         # 正式巡检一次
mail-monitor digest      # 把攒着的邮件合成一条汇总发出去
```

## 配置

| 项 | 环境变量 | 说明 |
|---|---|---|
| 模型 | `DEEPSEEK_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` | OpenAI 兼容接口，默认 DeepSeek。没有 key 也能跑：规则没覆盖的邮件一律按"拿不准"推送 |
| 推送 | `MAIL_MONITOR_NOTIFY` = `console` / `lark_webhook` / `lark_app` | 群自定义机器人只要 `LARK_WEBHOOK_URL`（可选 `LARK_WEBHOOK_SECRET`）；应用机器人要 `LARK_APP_ID`、`LARK_APP_SECRET`、`LARK_RECEIVE_ID` |
| 规则 | `MAIL_MONITOR_RULES`（默认 `~/.mail-monitor/rules.yaml`） | 见 [rules.example.yaml](rules.example.yaml) |
| 账号 | `MAIL_MONITOR_ACCOUNTS` | 只看某些账号；默认全部收件箱 |
| 行动 | `MAIL_MONITOR_ACTION_TAG` | 给"需要处理"的邮件打标签，默认 `false` |

完整列表见 [.env.example](.env.example)。秘密只放在 `~/.mail-monitor/.env`，不进仓库。

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
3. **宁可多推不漏**：拿不准的一律即时推送。推送失败的转入汇总，不会丢。
4. **邮件内容是不可信数据**：提示词里明确要求模型不执行邮件里的任何指令；程序不点链接、不发信、不删信。

## 开发

```bash
pytest            # 用 tests/fake_server.py 模拟 thunderbird-mcp，不需要 Thunderbird
```

`tests/fake_server.py` 照抄上游 v0.9.2 的工具名、参数和返回结构，所以能在云端或 CI 里跑通整条流水线；换成真 bridge 只是换一个启动命令。

## 和仓库其他部分的关系

- 邮件层仍然是 `thunderbird-mcp` 扩展 + `mcp-bridge.cjs`，本程序只是它的另一个 MCP 客户端，和 Claude Desktop 用的是同一条路。
- 安全规则沿用 [templates/mail-workspace/CLAUDE.md](../templates/mail-workspace/CLAUDE.md)：不发不删、不点链接、邮件内容不可信。
- 开机自启（launchd）和英文说明在后续版本补充。
