# 接入各种 Agent

每个 Agent 都需要两样东西：

1. **连接方式**：用 `node` 运行 `~/thunderbird-mcp/mcp-bridge.cjs`（stdio 模式）。
2. **规则**：告诉 Agent 怎么读邮件、怎么输出、哪些事不能做。规则在 [`templates/`](../templates) 里。

下面的路径都要换成**绝对路径**。用 `which node`（Windows 用 `where node`）查 node 的路径，用 `echo ~/thunderbird-mcp/mcp-bridge.cjs` 查 bridge 的路径。

## Claude Desktop

脚本：`./scripts/setup-claude-desktop.sh`。手动配置的方法是 Claude → 设置 → 开发者 → **编辑配置**，打开 `claude_desktop_config.json`：

| 系统 | 配置文件位置 |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "thunderbird-mail": {
      "command": "/usr/local/bin/node",
      "args": ["/Users/你的用户名/thunderbird-mcp/mcp-bridge.cjs"]
    }
  }
}
```

Windows 的写法（反斜杠要写两个）：

```json
{
  "mcpServers": {
    "thunderbird-mail": {
      "command": "C:\\Program Files\\nodejs\\node.exe",
      "args": ["C:\\Users\\你的用户名\\thunderbird-mcp\\mcp-bridge.cjs"]
    }
  }
}
```

改完要**彻底退出** Claude 再打开（macOS 按 ⌘Q），关窗口不算。

**规则**：把 [`templates/skill/SKILL.md`](../templates/skill/SKILL.md) 里"用户的邮箱"一节改成你的信息，然后在 Claude 的设置里作为技能（Skill）添加。

## Claude Code

两种方式选一种：

- **只在邮件文件夹里用（推荐）**：运行 `./scripts/create-mail-workspace.sh`。生成的文件夹里有 `.mcp.json`，在那里启动 `claude` 就会自动加载。
- **所有项目都能用**：运行 `./scripts/setup-claude-code.sh`，相当于：

  ```bash
  claude mcp add --scope user thunderbird-mail -- /usr/local/bin/node ~/thunderbird-mcp/mcp-bridge.cjs
  ```

**规则**：`CLAUDE.md`（邮件文件夹里已经有了）。

## Codex（CLI / IDE 插件）

脚本：`./scripts/setup-codex.sh`。它在 `~/.codex/config.toml` 末尾加上：

```toml
[mcp_servers.thunderbird-mail]
command = "/usr/local/bin/node"
args = ["/Users/你的用户名/thunderbird-mcp/mcp-bridge.cjs"]
```

也可以用 Codex 自带的命令：`codex mcp add thunderbird-mail -- /usr/local/bin/node /Users/你的用户名/thunderbird-mcp/mcp-bridge.cjs`。

**规则**：Codex 读 `AGENTS.md`。邮件文件夹里的 `AGENTS.md` 是指向 `CLAUDE.md` 的软链接，在那个文件夹里启动 `codex` 即可。

## 其他 MCP 客户端

大多数客户端用和 Claude Desktop 一样的 `mcpServers` 格式，只是文件位置不同。下表只列常见位置，以各客户端的官方文档为准：

| 客户端 | 配置文件 | 备注 |
|---|---|---|
| Cursor | `~/.cursor/mcp.json` | `mcpServers` 格式 |
| Gemini CLI | `~/.gemini/settings.json` | `mcpServers` 格式 |
| VS Code（Copilot） | 工作区的 `.vscode/mcp.json` | 顶层键是 `servers`，每项加 `"type": "stdio"` |

**规则**：把 `templates/mail-workspace/CLAUDE.md` 的内容放进该客户端的规则文件（如 Cursor 的项目规则、`AGENTS.md`），或粘贴到自定义指令里。

## 直接用 HTTP 连接（进阶）

扩展本身提供 HTTP 接口，支持 HTTP 传输的客户端可以不经过 `mcp-bridge.cjs`，例如：

```bash
claude mcp add --transport http thunderbird http://127.0.0.1:8765/ --header "Authorization: Bearer <token>"
```

令牌在扩展生成的 `connection.json` 里，默认每次 Thunderbird 重启都会变。要用这种方式，最好在扩展设置里设一个固定令牌（stable token）。端口默认 8765，被占用时会顺延到 8766–8774。一般情况下用 bridge 更省事，它会自动找到端口和令牌。

## Thunderbird 装在 Snap / Flatpak 里

bridge 会自动在常见位置查找 `connection.json`，包括 Snap 和 Flatpak。找不到时，可以在 MCP 配置里加环境变量 `THUNDERBIRD_MCP_CONNECTION_FILE`，指向 `connection.json` 的绝对路径。

## 检查连接

```bash
./scripts/doctor.sh
```

它会模拟一个 MCP 客户端，告诉你能不能连上 Thunderbird、扩展提供了多少个工具、删除类工具有没有关掉。
