# 常见问题排查

先运行一次自检，大部分问题它都能指出来：

```bash
./scripts/doctor.sh
```

## Agent 说找不到邮件工具

- **Claude Desktop**：改完配置后要彻底退出再打开（macOS 按 ⌘Q）。在设置 → 开发者里能看到 `thunderbird-mail` 的状态和报错。
- **Claude Code**：在会话里输入 `/mcp` 查看连接状态。在邮件文件夹里用的话，确认 `.mcp.json` 和 `.claude/settings.json` 都在。
- **Codex**：运行 `codex mcp list` 看有没有 `thunderbird-mail`。
- **node 路径失效**：用 nvm 等版本管理器装的 Node，切换版本后路径会变。重新运行对应的 setup 脚本，或改用 nodejs.org 的安装包。

## 工具在，但调用失败（连接被拒绝、Connection discovery failed）

- Thunderbird 没开，或者扩展被禁用了。打开 Thunderbird，在 附加组件和主题 里确认 Thunderbird MCP 已启用。
- 刚装完扩展：重启一次 Thunderbird。
- Thunderbird 装在 Snap / Flatpak 里且路径特殊：见 [agents.md](agents.md#thunderbird-装在-snap--flatpak-里)。

## 存草稿失败

- 机构邮箱没有订阅"草稿"文件夹。见 [thunderbird.md](thunderbird.md#订阅文件夹机构邮箱一定要做)。
- 账户设置 → 副本和文件夹 里，草稿的保存位置要指向这个账户的"草稿"文件夹。
- 扩展的 Tool Access 里要保持 `saveDraft` 开启（`replyToMessage` 存草稿时依赖它）。

## 总结时漏了邮件

- 先看 Thunderbird 里有没有这封邮件。没有的话，是 Thunderbird 还没同步：检查网络、账户是否需要重新登录、文件夹是否订阅。
- 规则默认只看 INBOX 和垃圾邮件。被服务器规则自动移到其他文件夹的邮件，需要在 `CLAUDE.md` 里加上那个文件夹。
- 总结第一行会写"共 N 封，已全部读完"。数量对不上时，让 Agent 列出没读成功的邮件。

## 结果太长，Agent 说内容被存成了文件

一次拉的邮件太多时会这样。模板规则已经要求 Agent 分段把文件读完。仍有问题的话，让它缩小时间范围，或把 `maxResults` 调小。

## Microsoft 365 登录提示"需要管理员批准"

你的机构不允许 Thunderbird 访问邮箱，只能联系 IT。这种情况本方案用不了。

## 日期或星期算错

在 `CLAUDE.md` 的"我的邮箱"一节写明你的时区（如"我在 UTC+4"）。

## 手机上连不上

见 [mobile.md](mobile.md#常见问题)。
