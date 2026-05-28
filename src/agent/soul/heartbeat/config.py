from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SoulHeartbeatConfig:
    """Soul 心跳专用配置（与 runtime.scheduler.HeartbeatConfig 解耦）。"""

    poll_interval_sec: int = 300
    active_hours_start: str = "08:00"
    active_hours_end: str = "22:00"
    active_timezone: str = "Asia/Shanghai"
    console_log_enabled: bool = True
    inject_window_mode: str = "user"
    inject_window_start: str = ""
    inject_window_end: str = ""
    inject_timezone: str = ""
    preflight_instruction: str = ""
    llm_aux_name: str = "heartbeat"
    webhook_secret: str = ""

    @classmethod
    def from_soul_config(cls, cfg) -> SoulHeartbeatConfig:
        hb = getattr(cfg, "heartbeat", None)
        scan = getattr(cfg, "heartbeat_scan_interval_sec", None)
        if scan is None and hb is not None:
            scan = getattr(hb, "scan_interval_sec", None)
        if scan is None and isinstance(hb, dict):
            scan = hb.get("scan_interval_sec")
        poll = int(scan if scan is not None else 300)

        def _hb_attr(name: str, default):
            if hasattr(cfg, name):
                val = getattr(cfg, name)
                if val not in (None, ""):
                    return val
            if hb is None:
                return default
            if hasattr(hb, name):
                val = getattr(hb, name)
                if val not in (None, ""):
                    return val
            if isinstance(hb, dict):
                val = hb.get(name)
                if val not in (None, ""):
                    return val
            return default

        return cls(
            poll_interval_sec=poll,
            active_hours_start=str(_hb_attr("active_hours_start", "08:00")),
            active_hours_end=str(_hb_attr("active_hours_end", "22:00")),
            active_timezone=str(_hb_attr("active_timezone", "Asia/Shanghai")),
            console_log_enabled=bool(_hb_attr("console_log_enabled", True)),
            inject_window_mode=str(_hb_attr("inject_window_mode", "user")),
            inject_window_start=str(_hb_attr("inject_window_start", "")),
            inject_window_end=str(_hb_attr("inject_window_end", "")),
            inject_timezone=str(_hb_attr("inject_timezone", "")),
            preflight_instruction=str(_hb_attr("preflight_instruction", "")),
            llm_aux_name=str(_hb_attr("llm_aux_name", "heartbeat")),
            webhook_secret=str(_hb_attr("webhook_secret", "")),
        )
