# 更新记录

**中文** | [English](CHANGELOG_EN.md)

按增量记录：每一段做了什么、在真机上验证到哪一步、下一段做什么。

## 下一段

1. 在 Mac 上先按 notify-hub [README](https://github.com/yuhang2551/notify-hub#从-02-升级) 里「从 0.2 升级」的步骤把它升到 0.3：用 0.2 把存着的消息发掉、卸掉它的定时任务，再升级。然后这边 `git pull`，再运行一次 `./scripts/launchd.sh install`，汇总换成 8、12、18 点。
2. 等第一封新邮件进来，用 `./scripts/launchd.sh status` 看一眼：定时任务里调 Claude 判断、经 notify-hub 推送都正常。
3. 用一周：`review` 标注、`eval` 看漏推率和噪声率，按结果调规则和提示词。顺手把 `rules.yaml` 里导师那条的示例地址换成真的，写上 `MAIL_MONITOR_PROFILE`。
4. ChatGPT 订阅版（做法已写在[模型后端](docs/model-backends.md)里，先不急）。

## 2026-10-28 · 什么时候推，全由邮件监控定

**为什么改**

notify-hub 0.2 自己也管时间：免打扰、汇总、每天三次的定时任务。邮件监控也有定时任务和汇总。两边各一套时间表，一条通知几点到，要把两边的设置放在一起才算得出来。现在 notify-hub 0.3 只管马上发（见它的[更新记录](https://github.com/yuhang2551/notify-hub/blob/main/CHANGELOG.md)），什么时候推全在这边定。

**改动**

- 汇总默认每天 8、12、18 点三次，原来是 9 点和 18 点两次。想改用 `DIGEST_HOURS`。
- 新增免打扰时段 `MAIL_MONITOR_QUIET_HOURS`，默认 `23:00-08:00`，按 `MAIL_MONITOR_TZ` 的钟点算（不填就是本机时区）。这段时间里只即时推送规则写了 `urgency: high` 的（比如导师），其余本该马上推的进汇总，8 点那次一起发；写 `off` 关掉。模型判断的「紧急」不算，因为邮件的措辞能把模型带偏。
- 推送失败的邮件进汇总，下次汇总带上；notify-hub 会先当场重试几次，还发不出去才算失败。汇总本身推不出去时，邮件都还攒着，`digest` 报错退出，下次汇总再带上。
- 赶上免打扰或推送失败、最后进了汇总的邮件，记录里仍算「判断为即时推送」，所以 `eval` 的漏推率只看判断准不准，不受几点到的影响。
- 不再给 notify-hub 传 `--key`：0.3 不去重，一封邮件推没推过本来就记在这边的数据库里。这一版配旧的 notify-hub 0.2.1 也能发，`doctor` 会提醒升级。
- `doctor` 多显示一行免打扰时段。`notify-test` 改按普通级别发：以前按紧急发，是怕被 notify-hub 的免打扰攒着，现在它不攒了。
- 测试 124 个，新加的覆盖免打扰时段的写法和跨午夜的判断、夜里只推导师那类、即时推送和汇总推不出去时邮件都不丢。

**文档更正**

- README、架构说明、FAQ 里「notify-hub 管免打扰、去重、失败重发」的说法都改掉了，README 加了一节「什么时候推」。
- 原来几处写着「电脑睡眠时不跑，醒来补跑一次」，对巡检不对。按[苹果的 launchd 文档](https://developer.apple.com/library/mac/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html)，按间隔跑的任务（巡检）睡眠中错过的直接跳过，醒来后到下一个间隔才跑；按钟点跑的任务（汇总）赶上睡眠的，醒来补跑一次。launchd 也不会为任务叫醒电脑。巡检每次回看两天，所以睡眠期间的邮件不会漏，只是醒来后最多晚一小时。
- 根目录 README 还写着每 5 分钟巡检，改成了每小时。

## 2026-10-28 · 定时任务改成每小时一次，Mac 上跑起来了

**改动**

- `scripts/launchd.sh` 默认每小时巡检一次，原来是每 5 分钟。找工作和学校的邮件晚一小时看到一般不耽误事，后台不用跑得太勤；查得勤也不会多花模型额度，因为模型只看新邮件。想改用 `RUN_INTERVAL`。
- 装上和开机登录时先巡检一次，不用等一小时。
- 没跑过 `mail-monitor init` 时，`install` 会停下来提醒：装上就先巡检，没 init 的话会把最近两天的邮件全推一遍。
- launchd 的 PATH 加上 `~/.local/bin`，claude 和 notify-hub 都装在这里。
- 新增 `./scripts/launchd.sh print`：只打印要装的 plist，不安装；测试也用它检查生成的内容。

**真机实测**（2026-10-28，Mac）

- `git pull` 到这一版，`.env` 里改成 `MAIL_MONITOR_LLM=claude`（Claude 订阅版）和 `MAIL_MONITOR_NOTIFY=notify_hub`，`doctor` 全部通过。
- `mail-monitor init` 把两个收件箱里现有的 111 封登记为已见。
- `./scripts/launchd.sh install` 装上后马上巡检了一次，`status` 显示退出码 0：两个收件箱拉到 35 封，新邮件 0 封。说明 launchd 里找得到 node，也连得上 Thunderbird。
- 还没验证到的：定时任务里调 Claude 判断、经 notify-hub 推送，要等第一封新邮件。

**实测中发现并改好**

- `notify-test` 经 notify-hub 发的时候，结果打了两遍（日志一遍、结果一遍）。现在只打一遍；巡检时要看 notify-hub 的回答，加 `-v`。
- `run` 和 `digest` 输出的那一行开头带上时间（比如 `10-28 13:00 收件箱 2 个…`）。`status` 只显示日志最后几行，原来分不清是哪次跑的。
- README 和文档里的命令块去掉了注释，说明挪到命令块外面。macOS 终端默认的 zsh 不认 `#` 注释：整行注释会报 `command not found: #`，行尾注释会变成命令的参数，比如 `mail-monitor doctor  # 自检` 会报多了参数，`./scripts/create-mail-workspace.sh  # 默认生成 ~/mail-workspace` 会建出一个叫 `#` 的文件夹。加了一个测试检查文档里的命令块。
- 测试 105 个。

## 2026-10-27 · 推送可以交给 notify-hub

**新增**

- 新的推送方式 `MAIL_MONITOR_NOTIFY=notify_hub`：即时推送和早晚汇总都交给本机的通知网关 [notify-hub](https://github.com/yuhang2551/notify-hub)，Lark 凭证、夜里免打扰、去重、限流、失败重发归它管。终端、群机器人、应用机器人三种照旧能用。
- 每条推送除了纯文本，还带着卡片用的标题、正文和级别。即时推送的标题是「谁：什么事」，手机通知里一眼能看到；汇总是一张「邮件汇总 · N 封」的卡。
- 级别：规则里写了 `urgency: high` 的（比如导师）按紧急发，夜里也推；其余按普通发，免打扰时段先存着，结束后合成一张卡。模型判断的紧急只写在卡片上，不在夜里叫醒人。
- 每封邮件带着自己的 id 交给 notify-hub，万一同一封交了两次也只推一次。
- notify-hub 没装、找不到命令或者 60 秒没返回时，这封邮件转进汇总，不会丢。PATH 里找不到时会去 `~/.local/bin` 找，也可以用 `MAIL_MONITOR_NOTIFY_HUB_BIN` 写完整路径。
- `doctor` 显示 notify-hub 的版本；`notify-test` 按紧急发（测试消息不该被免打扰攒着），并把 notify-hub 的回答原样打出来。
- 测试 99 个，用假的 notify-hub 命令。

**验证到哪一步**

- 在云端用真的 notify-hub（推到终端，不推 Lark）跑了一遍完整巡检：导师的邮件按紧急发出，其余的在免打扰时段被 notify-hub 存了起来。
- 2026-10-28 在 Mac 上实测：`git pull` 后加上 `MAIL_MONITOR_NOTIFY=notify_hub` 跑 `doctor`，推送一行显示 notify-hub 0.2.1，两个收件箱和 Claude 订阅也都正常；`notify-test` 经 notify-hub 发出，Lark 收下了（notify-hub 里是第 7 条）。

## 2026-10-27 · Lark 推送测通

**真机实测**

- 在 Lark 开发者后台建了应用机器人「通知助手」：开了 `im:message:send_as_bot` 和 `im:chat:readonly` 两项权限，发布版本，拉进一个只有自己的群「通知」。
- `mail-monitor lark-chats` 查到群 id，`mail-monitor notify-test` 把测试消息发到了手机上。

**实测中发现并改好**

- 只填了群 id、没填 `LARK_RECEIVE_ID_TYPE` 时，程序默认把它当成个人 open_id 发，Lark 会报错。现在类型不填就按 id 前缀判断：`oc_` 按群发，`ou_` 按私聊发；填了就以填的为准。
- 测试加到 88 个。

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
