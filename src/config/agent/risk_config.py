from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskConfig:
    enabled: bool = True
    auto_approve_level: str = "medium"
    approval_timeout_secs: int = 60
    assessor_type: str = "rule"
    external_url: str = ""
    external_timeout_secs: int = 5
    allow_list: dict[str, str] = field(default_factory=dict)
    rule_overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str) -> RiskConfig:
        import yaml
        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            auto_approve_level=data.get("auto_approve_level", "medium"),
            approval_timeout_secs=int(data.get("approval_timeout_secs", 60)),
            assessor_type=data.get("assessor_type", "rule"),
            external_url=data.get("external_url", ""),
            external_timeout_secs=int(data.get("external_timeout_secs", 5)),
            allow_list=data.get("allow_list", {}),
            rule_overrides=data.get("rule_overrides", {}),
        )
