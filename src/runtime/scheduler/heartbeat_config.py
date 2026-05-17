from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HeartbeatConfig:
    interval:                int   = 1800
    profile:                 str   = "with_memory"
    llm_aux_name:            str   = "heartbeat"
    light_context:           bool  = True
    max_escalations_per_day: int   = 10
    heartbeat_file:          str   = ".react/scheduler/HEARTBEAT.md"
    active_hours_start:      str   = "07:00"
    active_hours_end:        str   = "22:00"
    active_timezone:         str   = "Asia/Shanghai"
    webhook_secret:          str   = ""

    # Core heartbeat thread (agent.heartbeat.core_service.HeartbeatCoreService)
    core_service_enabled:         bool  = False
    core_service_poll_interval_sec: int = 1800
    clock_drives_heartbeat:       bool  = True
    inject_window_mode:           str   = "user"
    inject_window_start:          str   = ""
    inject_window_end:            str   = ""
    inject_timezone:              str   = ""
    inject_on_ok:                 bool  = False
    preflight_instruction:        str   = ""

    @classmethod
    def from_dict(cls, d: dict) -> HeartbeatConfig:
        _interval = int(d.get("interval", 1800))
        return cls(
            interval=_interval,
            profile=d.get("profile", "with_memory"),
            llm_aux_name=d.get("llm_aux_name", "heartbeat"),
            light_context=bool(d.get("light_context", True)),
            max_escalations_per_day=int(d.get("max_escalations_per_day", 10)),
            heartbeat_file=d.get("heartbeat_file", ".react/scheduler/HEARTBEAT.md"),
            active_hours_start=d.get("active_hours_start", "07:00"),
            active_hours_end=d.get("active_hours_end", "22:00"),
            active_timezone=d.get("active_timezone", "Asia/Shanghai"),
            webhook_secret=d.get("webhook_secret", ""),
            core_service_enabled=bool(d.get("core_service_enabled", False)),
            core_service_poll_interval_sec=int(d.get("core_service_poll_interval_sec", _interval)),
            clock_drives_heartbeat=bool(d.get("clock_drives_heartbeat", True)),
            inject_window_mode=d.get("inject_window_mode", "user"),
            inject_window_start=d.get("inject_window_start", ""),
            inject_window_end=d.get("inject_window_end", ""),
            inject_timezone=d.get("inject_timezone", ""),
            inject_on_ok=bool(d.get("inject_on_ok", False)),
            preflight_instruction=d.get("preflight_instruction", ""),
        )

    def to_dict(self) -> dict:
        return {
            "interval":                self.interval,
            "profile":                 self.profile,
            "llm_aux_name":            self.llm_aux_name,
            "light_context":           self.light_context,
            "max_escalations_per_day": self.max_escalations_per_day,
            "heartbeat_file":          self.heartbeat_file,
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
            "inject_on_ok":                 self.inject_on_ok,
            "preflight_instruction":        self.preflight_instruction,
        }
