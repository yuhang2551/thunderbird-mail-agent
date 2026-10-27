# 更新记录

**中文** | [English](CHANGELOG_EN.md)

按增量记录：每一段做了什么、在真机上验证到哪一步、下一段做什么。

## 下一段

1. 接 Lark 应用机器人推送，用 `mail-monitor notify-test` 在手机上收到测试消息。
2. `mail-monitor init` 把现有邮件登记为已见，装 launchd 定时任务，真正跑起来。
3. 用一周：`review` 标注、`eval` 看漏推率和噪声率，按结果调规则和提示词。
4. ChatGPT 订阅版（做法已写在[模型后端](docs/model-backends.md)里，先不急）。

## 2026-10-27 · Claude 订阅版，真机跑通只读试跑

**真机实测**（Apple Silicon Mac，只读：没记录、没推送、没改邮箱）

- 环境：Python 3.13（用 uv 装在用户目录）、Claude Code 2.1.311（Claude 订阅登录）、Thunderbird + thunderbird-mcp。
- `mail-monitor doctor` 全部通过：两个收件箱（Gmail 和学校邮箱）都连上，claude 用订阅登录。
- `mail-monitor run --dry-run --days 1`：最近一天 15 封新邮件，规则定性 8 封，Claude 判断 7 封，退回保底 0 封；1 封即时推送，14 封进汇总。

**新增**

- Claude 订阅版后端：设 `MAIL_MONITOR_LLM=claude`，每封邮件调用一次 Mac 上已登录的官方 `claude -p`，不用 key。工具、MCP、hooks、CLAUDE.md 全部关掉，邮件走标准输入，会话不落盘。没登录、额度用完、版本太旧、超时的时候，这一轮剩下的邮件按「拿不准」照常推送，原因写进运行报告。
- `doctor` 检查 claude 的版本和登录方式，不调用模型。
- 试跑最后会把会进汇总的邮件也按汇总格式列出来，不再只看得到即时推送的那几封。
- 测试 79 个，用假的 thunderbird-mcp 和假的 claude 命令。

**实测中发现并修好**

- Mac 自带的 Python 是 3.9：`install.sh` 会自己找装过的 python3.10 到 3.14，找不到时给出 python.org、Homebrew、uv 三种装法。
- macOS 自带的 bash 3.2 会把紧跟在 `$变量` 后面的中文吃进变量名，报 "unbound variable"：所有脚本改成 `${变量}`，并加了测试防止再犯。
- 终端里没有 `claude` 命令：doctor 直接给出官方安装命令和 `claude auth login`；PATH 里找不到时自动用 `~/.local/bin/claude`。

## 2026-10-17 · 文档，跟上 DeepSeek 的变化

- `docs/` 加了中英文的架构说明、模型后端、常见问题。
- DeepSeek 停用了 `deepseek-chat`：默认改成 `deepseek-flash`，并关掉它默认开着的思考模式；别家的私有参数用 `LLM_EXTRA_BODY` 传。
- Thunderbird 没开时只提示"连不上 Thunderbird"，不再崩溃。

## 2026-10-13 · 骨架、记忆、定时任务、评测

- 巡检：通过 thunderbird-mcp 读所有收件箱的新邮件，SQLite 去重。
- 判断：先过规则（`rules.yaml`），规则没定性的读正文交给模型，输出固定结构的 JSON（谁、什么事、要不要管、几号前、建议），Pydantic 校验，失败重试一次再退回「拿不准」。
- 推送：要管或拿不准的即时推送，其余攒成早晚汇总；支持终端、Lark 群自定义机器人（webhook，可签名）和 Lark 应用机器人，`lark-chats`、`notify-test` 帮你配。
- 记忆：记住发件人是谁（你设的 > 规则 > 模型），判断时带上同一话题之前的邮件；`senders`、`sender-set` 查看和修改。
- 定时任务：`scripts/launchd.sh`，每 5 分钟巡检，早晚各一份汇总。
- 评测：`review` 标注，`eval` 算漏推率和噪声率。
- 只读：不发、不删、不移动；唯一写邮箱的动作（给要管的邮件打标签）默认关闭。
