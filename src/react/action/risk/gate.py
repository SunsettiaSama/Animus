from __future__ import annotations

from config.react.risk_config import RiskConfig
from react.action.risk.allow_list import AllowList
from react.action.risk.assessor import BaseRiskAssessor, ExternalAPIAssessor, RuleBasedAssessor
from react.action.risk.level import OperationRisk, RiskLevel


class RiskGate:
    """
    Unified risk governance entry point.

    Resolution order:
    1. If the tool name is in the allow list, use that level (bypass assessor).
    2. Otherwise, delegate to the configured assessor.
    3. Compare result level against auto_approve_level to determine if human
       approval is required.
    """

    def __init__(self, cfg: RiskConfig) -> None:
        self._cfg = cfg
        self._allow_list = AllowList(cfg.allow_list)
        self._auto_level = RiskLevel.from_str(cfg.auto_approve_level)

        if cfg.assessor_type == "external" and cfg.external_url:
            self._assessor: BaseRiskAssessor = ExternalAPIAssessor(
                cfg.external_url, cfg.external_timeout_secs
            )
        else:
            self._assessor = RuleBasedAssessor(cfg.rule_overrides)

    @property
    def cfg(self) -> RiskConfig:
        return self._cfg

    @property
    def allow_list(self) -> AllowList:
        return self._allow_list

    def check(self, tool_name: str, args: dict) -> OperationRisk:
        forced = self._allow_list.get(tool_name)
        if forced is not None:
            return OperationRisk(
                tool_name=tool_name,
                args=args,
                level=forced,
                reason=f"allow list 强制级别: {forced.value}",
            )
        return self._assessor.assess(tool_name, args)

    def requires_approval(self, risk: OperationRisk) -> bool:
        """Return True when the risk level exceeds the auto-approve threshold."""
        return not (risk.level <= self._auto_level)

    @classmethod
    def from_config(cls, cfg: RiskConfig) -> "RiskGate":
        return cls(cfg)
