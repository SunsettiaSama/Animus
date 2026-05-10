from __future__ import annotations

from dataclasses import dataclass, field


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

    @classmethod
    def from_dict(cls, d: dict) -> HeartbeatConfig:
        return cls(
            interval=int(d.get("interval", 1800)),
            profile=d.get("profile", "with_memory"),
            llm_aux_name=d.get("llm_aux_name", "heartbeat"),
            light_context=bool(d.get("light_context", True)),
            max_escalations_per_day=int(d.get("max_escalations_per_day", 10)),
            heartbeat_file=d.get("heartbeat_file", ".react/scheduler/HEARTBEAT.md"),
            active_hours_start=d.get("active_hours_start", "07:00"),
            active_hours_end=d.get("active_hours_end", "22:00"),
            active_timezone=d.get("active_timezone", "Asia/Shanghai"),
            webhook_secret=d.get("webhook_secret", ""),
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
        }
