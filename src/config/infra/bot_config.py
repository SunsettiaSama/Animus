from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BotConfig:
    # ── 通用 ──────────────────────────────────────────────────────────────────
    enabled: bool = False            # 是否在启动时自动连接
    transport: str = "forward_ws"   # "forward_ws" | "qq_official"
    # Whitelist keys — semantics depend on transport:
    #   forward_ws  → QQ number strings, e.g. ["1219584142"]
    #   qq_official → raw openid strings from QQ Open Platform
    # Empty list = deny all (most restrictive).
    allowed_private_users: list[str] = field(default_factory=list)
    allowed_groups: list[str] = field(default_factory=list)
    command_prefix: str = ""
    max_sessions: int = 100
    session_ttl_hours: float = 24.0

    # ── forward_ws 专用（NapCat / go-cqhttp 等 OneBot 11 WebSocket 服务） ──
    ws_url: str = "ws://127.0.0.1:3001"
    access_token: str = ""
    reconnect_interval_sec: float = 5.0

    # ── qq_official 专用（QQ 开放平台官方机器人 API） ──────────────────────
    appid: str = ""
    secret: str = ""
    is_sandbox: bool = False
    # 出站代理（留空则直连）。格式：http://host:port 或 socks5://host:port
    # 本地开发时可填 Clash/V2Ray 等代理地址，使 botpy 走代理 IP 访问 QQ 平台。
    proxy: str = ""

    # ── 邀请码自动入白名单 ─────────────────────────────────────────────────
    # 用户向 bot 发送此字符串即可自动加入白名单（留空则禁用此功能）。
    # 每自然日最多允许 invite_daily_limit 个新用户通过邀请码入网。
    invite_code: str = ""
    invite_daily_limit: int = 4

    # ── Bot 回复详细程度 ────────────────────────────────────────────────────
    # show_step_progress: 每个工具步骤完成后向用户发一条进度通知，格式：
    #   ⚙️ 步骤 N：action_name
    #   💭 thought 摘要（最多 120 字）
    #   📎 observation 前 80 字…
    # 旧字段 show_thought / show_intermediate_output 已废弃，load() 自动迁移。
    show_step_progress: bool = False
    # 消息聚合窗口：同一会话内 message_debounce_secs 秒内的多条短消息合并为一条后
    # 再入队处理；设为 0 则禁用（每条消息立即入队）。
    message_debounce_secs: float = 2.0

    def to_yaml(self, path: str | Path) -> None:
        import yaml
        import os
        path = Path(path)
        os.makedirs(path.parent, exist_ok=True)
        data = {
            "enabled":                self.enabled,
            "transport":              self.transport,
            "allowed_private_users":  self.allowed_private_users,
            "allowed_groups":         self.allowed_groups,
            "command_prefix":         self.command_prefix,
            "max_sessions":           self.max_sessions,
            "session_ttl_hours":      self.session_ttl_hours,
            # forward_ws
            "ws_url":                 self.ws_url,
            "access_token":           self.access_token,
            "reconnect_interval_sec": self.reconnect_interval_sec,
            # qq_official
            "appid":                  self.appid,
            "secret":                 self.secret,
            "is_sandbox":             self.is_sandbox,
            "proxy":                  self.proxy,
            # invite
            "invite_code":            self.invite_code,
            "invite_daily_limit":     self.invite_daily_limit,
            "show_step_progress":     self.show_step_progress,
            "message_debounce_secs":  self.message_debounce_secs,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)

    @classmethod
    def load(cls, path: str | Path | None = None) -> BotConfig:
        import yaml

        if path is None:
            from config import paths
            path = paths.root / "config" / "infra" / "bot_config.yaml"

        path = Path(path)
        if not path.exists():
            return cls()
        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            transport=str(data.get("transport", "forward_ws")),
            allowed_private_users=[
                str(x) for x in data.get("allowed_private_users") or []
            ],
            allowed_groups=[
                str(x) for x in data.get("allowed_groups") or []
            ],
            command_prefix=str(data.get("command_prefix", "")),
            max_sessions=int(data.get("max_sessions", 100)),
            session_ttl_hours=float(data.get("session_ttl_hours", 24.0)),
            # forward_ws
            ws_url=str(data.get("ws_url", "ws://127.0.0.1:3001")),
            access_token=str(data.get("access_token", "")),
            reconnect_interval_sec=float(data.get("reconnect_interval_sec", 5.0)),
            # qq_official
            appid=str(data.get("appid", "")),
            secret=str(data.get("secret", "")),
            is_sandbox=bool(data.get("is_sandbox", False)),
            proxy=str(data.get("proxy", "")),
            # invite
            invite_code=str(data.get("invite_code", "")),
            invite_daily_limit=int(data.get("invite_daily_limit", 4)),
            # verbosity — backward compat: if show_step_progress absent, fall back
            # to the old show_intermediate_output / show_thought flags.
            show_step_progress=bool(data.get(
                "show_step_progress",
                data.get("show_intermediate_output", False) or data.get("show_thought", False),
            )),
            message_debounce_secs=float(data.get("message_debounce_secs", 2.0)),
        )
