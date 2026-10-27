"""配置：从 ~/.mail-monitor/.env（或 --env 指定的文件）和环境变量读取，环境变量优先。

所有秘密（API key、webhook）只放在 .env 里，不进仓库。
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field

DEFAULT_HOME = Path.home() / ".mail-monitor"
NotifyBackend = Literal["console", "lark_webhook", "lark_app"]
LLMBackend = Literal["api", "claude"]


class Settings(BaseModel):
    # 邮件层：默认用 node 跑 thunderbird-mcp 的 bridge；测试时可以换成假服务器
    node_bin: str = "node"
    bridge_path: Path = Path.home() / "thunderbird-mcp" / "mcp-bridge.cjs"
    mcp_command: list[str] | None = None
    accounts: list[str] = Field(default_factory=list)  # 只看这些账号（id 或名字子串）；空 = 全部
    days_back: int = 2
    max_results: int = 100

    # 状态、规则
    home: Path = DEFAULT_HOME
    db_path: Path | None = None
    rules_path: Path | None = None
    timezone: str | None = None  # 例如 Asia/Dubai；不填用系统时区

    # 模型后端：api = 拿 API key 调 OpenAI 兼容接口；claude = 调本机已登录的 Claude Code，用 Claude 订阅（只限自己用）
    llm_backend: LLMBackend = "api"

    # LLM（OpenAI 兼容接口，默认 DeepSeek）
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"  # deepseek-chat / deepseek-reasoner 已于 2026-07-24 停用
    llm_body_chars: int = 4000  # 正文送给模型前截断到这么多字符
    # 原样并进请求体的额外字段（JSON 对象），用来传各家的私有参数；不填时见 resolved_llm_extra_body
    llm_extra_body: dict[str, Any] | None = None
    # 一句话介绍收件人（在读什么、找什么工作、导师是谁），写进提示词，模型判断"谁、要不要管"更准
    profile: str | None = None

    # Claude 订阅版（MAIL_MONITOR_LLM=claude）
    claude_bin: str = "claude"  # launchd 下找不到时写完整路径（which claude）
    claude_model: str = "sonnet"  # 想省订阅用量可以换 haiku
    claude_timeout: float = 180.0  # 一封邮件最多等几秒

    # 推送
    notify_backend: NotifyBackend = "console"
    lark_domain: str = "https://open.larksuite.com"  # 飞书国内版改成 https://open.feishu.cn
    lark_webhook_url: str | None = None
    lark_webhook_secret: str | None = None
    lark_app_id: str | None = None
    lark_app_secret: str | None = None
    lark_receive_id: str | None = None
    lark_receive_id_type: str | None = None  # 不填就按 LARK_RECEIVE_ID 的前缀判断（oc_ 群、ou_ 个人）

    # 行动开关：写邮箱的动作默认全关
    action_tag: bool = False
    action_tag_key: str = "$label4"  # Thunderbird 内置标签 "To Do"

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path or self.home / "state.db"

    @property
    def resolved_rules_path(self) -> Path | None:
        if self.rules_path:
            return self.rules_path
        candidate = self.home / "rules.yaml"
        return candidate if candidate.exists() else None

    @property
    def mailbox_command(self) -> list[str]:
        return self.mcp_command or [self.node_bin, str(self.bridge_path)]

    @property
    def llm_enabled(self) -> bool:
        return self.llm_backend == "claude" or bool(self.llm_api_key)

    @property
    def claude_workdir(self) -> Path:
        # claude -p 在这个空目录里跑：它会执行当前目录项目里的 hooks、连 .mcp.json 里的服务器
        return self.home / "claude-run"

    @property
    def resolved_llm_extra_body(self) -> dict[str, Any]:
        if self.llm_extra_body is not None:
            return self.llm_extra_body
        # DeepSeek 现在默认开思考模式。分诊用不着：关掉更快、更省，max_tokens 也不会被思考过程用掉
        if "deepseek.com" in self.llm_base_url:
            return {"thinking": {"type": "disabled"}}
        return {}


# DeepSeek 2026-07-24 停用的旧模型名 → 现在该用的
RETIRED_MODELS = {"deepseek-chat": "deepseek-flash", "deepseek-reasoner": "deepseek-flash"}


# 环境变量名 → Settings 字段名
ENV_MAP: dict[str, str] = {
    "MAIL_MONITOR_NODE_BIN": "node_bin",
    "MAIL_MONITOR_BRIDGE": "bridge_path",
    "MAIL_MONITOR_MCP_COMMAND": "mcp_command",
    "MAIL_MONITOR_ACCOUNTS": "accounts",
    "MAIL_MONITOR_DAYS_BACK": "days_back",
    "MAIL_MONITOR_MAX_RESULTS": "max_results",
    "MAIL_MONITOR_HOME": "home",
    "MAIL_MONITOR_DB": "db_path",
    "MAIL_MONITOR_RULES": "rules_path",
    "MAIL_MONITOR_TZ": "timezone",
    "MAIL_MONITOR_LLM": "llm_backend",
    "DEEPSEEK_API_KEY": "llm_api_key",
    "LLM_API_KEY": "llm_api_key",
    "LLM_BASE_URL": "llm_base_url",
    "LLM_MODEL": "llm_model",
    "LLM_BODY_CHARS": "llm_body_chars",
    "LLM_EXTRA_BODY": "llm_extra_body",
    "MAIL_MONITOR_PROFILE": "profile",
    "MAIL_MONITOR_CLAUDE_BIN": "claude_bin",
    "MAIL_MONITOR_CLAUDE_MODEL": "claude_model",
    "MAIL_MONITOR_CLAUDE_TIMEOUT": "claude_timeout",
    "MAIL_MONITOR_NOTIFY": "notify_backend",
    "LARK_DOMAIN": "lark_domain",
    "LARK_WEBHOOK_URL": "lark_webhook_url",
    "LARK_WEBHOOK_SECRET": "lark_webhook_secret",
    "LARK_APP_ID": "lark_app_id",
    "LARK_APP_SECRET": "lark_app_secret",
    "LARK_RECEIVE_ID": "lark_receive_id",
    "LARK_RECEIVE_ID_TYPE": "lark_receive_id_type",
    "MAIL_MONITOR_ACTION_TAG": "action_tag",
    "MAIL_MONITOR_ACTION_TAG_KEY": "action_tag_key",
}

_LIST_FIELDS = {"accounts"}
_COMMAND_FIELDS = {"mcp_command"}
_BOOL_FIELDS = {"action_tag"}
_PATH_FIELDS = {"bridge_path", "home", "db_path", "rules_path"}
_JSON_FIELDS = {"llm_extra_body"}


def _coerce(field: str, raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return None
    if field in _LIST_FIELDS:
        return [item.strip() for item in value.split(",") if item.strip()]
    if field in _COMMAND_FIELDS:
        return shlex.split(value)
    if field in _BOOL_FIELDS:
        return value.lower() in ("1", "true", "yes", "on")
    if field in _PATH_FIELDS:
        return Path(value).expanduser()
    if field == "llm_backend":
        choice = value.lower()
        if choice == "chatgpt":
            raise ValueError("ChatGPT 订阅版还没做，先用 api 或 claude")
        if choice not in ("api", "claude"):
            raise ValueError("只能是 api 或 claude")
        return choice
    if field in _JSON_FIELDS:
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"不是合法的 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError('要写成 JSON 对象，例如 {"thinking": {"type": "disabled"}}')
        return data
    return value


def load_settings(env_file: Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    """读取 .env 和环境变量。优先级：overrides > 环境变量 > .env 文件 > 默认值。"""
    merged: dict[str, str] = {}
    path = env_file or Path(os.environ.get("MAIL_MONITOR_ENV", DEFAULT_HOME / ".env")).expanduser()
    if path.exists():
        merged.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    merged.update({k: v for k, v in os.environ.items() if k in ENV_MAP})

    values: dict[str, Any] = {}
    for env_name, field in ENV_MAP.items():
        if env_name in merged and merged[env_name] is not None:
            try:
                coerced = _coerce(field, merged[env_name])
            except ValueError as exc:
                raise ValueError(f"配置 {env_name} 有问题：{exc}") from exc
            if coerced is not None:
                values[field] = coerced
    if overrides:
        values.update({k: v for k, v in overrides.items() if v is not None})
    return Settings(**values)
