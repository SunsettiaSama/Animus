from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HeartbeatConfig:
    interval:                int   = 300
    check_interval_sec:      int   = 300
    flush_interval_sec:      int   = 21600
    active_hours_start:      str   = "08:00"
    active_hours_end:        str   = "22:00"
    active_timezone:         str   = "Asia/Shanghai"
    webhook_secret:          str   = ""

    # Core heartbeat thread (agent.soul.heartbeat.core_service.HeartbeatCoreService)
    core_service_enabled:         bool  = False
    core_service_poll_interval_sec: int = 1800
    clock_drives_heartbeat:       bool  = True
    inject_window_mode:           str   = "user"
    inject_window_start:          str   = ""
    inject_window_end:            str   = ""
    inject_timezone:              str   = ""
    preflight_instruction:        str   = ""

    # 主进程 stdout/stderr 是否输出 heartbeat 链路日志（tick_log.jsonl 不受影响）
    console_log_enabled:          bool  = True

    @classmethod
    def from_dict(cls, d: dict) -> HeartbeatConfig:
        _check = int(d.get("check_interval_sec", d.get("interval", 300)))
        _interval = int(d.get("interval", _check))
        return cls(
            interval=_interval,
            check_interval_sec=_check,
            flush_interval_sec=int(d.get("flush_interval_sec", 21600)),
            active_hours_start=d.get("active_hours_start", "08:00"),
            active_hours_end=d.get("active_hours_end", "22:00"),
            active_timezone=d.get("active_timezone", "Asia/Shanghai"),
            webhook_secret=d.get("webhook_secret", ""),
            core_service_enabled=bool(d.get("core_service_enabled", False)),
            core_service_poll_interval_sec=int(d.get("core_service_poll_interval_sec", _check)),
            clock_drives_heartbeat=bool(d.get("clock_drives_heartbeat", True)),
            inject_window_mode=d.get("inject_window_mode", "user"),
            inject_window_start=d.get("inject_window_start", ""),
            inject_window_end=d.get("inject_window_end", ""),
            inject_timezone=d.get("inject_timezone", ""),
            preflight_instruction=d.get("preflight_instruction", ""),
            console_log_enabled=bool(d.get("console_log_enabled", True)),
        )

    def to_dict(self) -> dict:
        return {
            "interval":                self.interval,
            "check_interval_sec":      self.check_interval_sec,
            "flush_interval_sec":      self.flush_interval_sec,
            "active_hours_start":      self.active_hours_start,
            "active_hours_end":        self.active_hours_end,
            "active_timezone":         self.active_timezone,
            "webhook_secret":          self.webhook_secret,
            "core_service_enabled":         self.core_service_enabled,
            "core_service_poll_interval_sec": self.core_service_poll_interval_sec,
            "clock_drives_heartbeat":       self.clock_drives_heartbeat,
            "inject_window_mode":           self.inject_window_mode,
            "inject_window_start":          self.inject_window_start,
            "inject_window_end":            self.inject_window_end,
            "inject_timezone":              self.inject_timezone,
            "preflight_instruction":        self.preflight_instruction,
            "console_log_enabled":          self.console_log_enabled,
        }
