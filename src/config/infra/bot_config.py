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

    # ── 邀请码自动入白名单 ─────────────────────────────────────────────────
    # 用户向 bot 发送此字符串即可自动加入白名单（留空则禁用此功能）。
    # 每自然日最多允许 invite_daily_limit 个新用户通过邀请码入网。
    invite_code: str = ""
    invite_daily_limit: int = 4

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
            # invite
            "invite_code":            self.invite_code,
            "invite_daily_limit":     self.invite_daily_limit,
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
            # invite
            invite_code=str(data.get("invite_code", "")),
            invite_daily_limit=int(data.get("invite_daily_limit", 4)),
        )
