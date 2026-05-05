from __future__ import annotations

from abc import ABC, abstractmethod

from react.action.risk.level import OperationRisk, RiskLevel

DEFAULT_RULES: dict[str, RiskLevel] = {
    "python_run":              RiskLevel.HIGH,
    "file_delete":             RiskLevel.HIGH,
    "file_write":              RiskLevel.MEDIUM,
    "http_request":            RiskLevel.MEDIUM,
    "note_write":              RiskLevel.LOW,
    "note_delete":             RiskLevel.MEDIUM,
    "file_read":               RiskLevel.LOW,
    "file_list":               RiskLevel.LOW,
    "file_exists":             RiskLevel.LOW,
    "note_read":               RiskLevel.LOW,
    "web_search":              RiskLevel.LOW,
    "web_fetch":               RiskLevel.LOW,
    "calculator":              RiskLevel.LOW,
    "get_datetime":            RiskLevel.LOW,
    "get_weekday":             RiskLevel.LOW,
    "unit_converter":          RiskLevel.LOW,
    "word_count":              RiskLevel.LOW,
    "string_transform":        RiskLevel.LOW,
    "base64":                  RiskLevel.LOW,
    "hash":                    RiskLevel.LOW,
    "random_number":           RiskLevel.LOW,
    "random_choice":           RiskLevel.LOW,
    "generate_uuid":           RiskLevel.LOW,
    "memory_recall":           RiskLevel.LOW,
    "tool_search":             RiskLevel.LOW,
    "json_query":              RiskLevel.LOW,
    "regex_extract":           RiskLevel.LOW,
    "text_diff":               RiskLevel.LOW,
    "knowledge_hybrid_search": RiskLevel.LOW,
    "knowledge_list":          RiskLevel.LOW,
    "knowledge_save":          RiskLevel.MEDIUM,
    "scheduler_add":           RiskLevel.MEDIUM,
    "scheduler_cancel":        RiskLevel.MEDIUM,
    "scheduler_list":          RiskLevel.LOW,
    "domain_learning":         RiskLevel.MEDIUM,
    "web_research":            RiskLevel.LOW,
    "document_summary":        RiskLevel.LOW,
}

_DEFAULT_LEVEL = RiskLevel.MEDIUM


class BaseRiskAssessor(ABC):
    @abstractmethod
    def assess(self, tool_name: str, args: dict) -> OperationRisk:
        raise NotImplementedError


class RuleBasedAssessor(BaseRiskAssessor):
    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self._rules: dict[str, RiskLevel] = dict(DEFAULT_RULES)
        if overrides:
            for name, level_str in overrides.items():
                self._rules[name] = RiskLevel.from_str(level_str)

    def assess(self, tool_name: str, args: dict) -> OperationRisk:
        level = self._rules.get(tool_name, _DEFAULT_LEVEL)
        reasons = {
            RiskLevel.LOW:    "常规只读或无副作用操作，自动放行",
            RiskLevel.MEDIUM: "有状态写入操作，记录日志",
            RiskLevel.HIGH:   "高权限操作，需要用户审批后执行",
        }
        return OperationRisk(
            tool_name=tool_name,
            args=args,
            level=level,
            reason=reasons[level],
        )


class ExternalAPIAssessor(BaseRiskAssessor):
    def __init__(self, url: str, timeout_secs: int = 5) -> None:
        self._url = url
        self._timeout = timeout_secs

    def assess(self, tool_name: str, args: dict) -> OperationRisk:
        import httpx
        payload = {"tool_name": tool_name, "args": args}
        response = httpx.post(self._url, json=payload, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()
        level = RiskLevel.from_str(data.get("level", "medium"))
        reason = data.get("reason", "外部评估结果")
        return OperationRisk(tool_name=tool_name, args=args, level=level, reason=reason)
