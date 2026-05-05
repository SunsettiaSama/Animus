"""
Risk 子系统测试
===============
覆盖 react/action/risk/ 下全部组件：
  - RiskLevel        — 全序比较、from_str
  - OperationRisk    — dataclass 构造
  - RuleBasedAssessor — DEFAULT_RULES 查找、override、未知工具默认值
  - ExternalAPIAssessor — mock httpx.post
  - AllowList         — get / set / remove / to_dict
  - RiskGate          — 白名单优先、requires_approval 阈值联动

运行方式：
  cd E:/ReAct
  python -m pytest src/test/react/test_risk.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from config.react.risk_config import RiskConfig
from react.action.risk.level import OperationRisk, RiskLevel
from react.action.risk.allow_list import AllowList
from react.action.risk.assessor import (
    ExternalAPIAssessor,
    RuleBasedAssessor,
)
from react.action.risk.gate import RiskGate
import react.action.risk.assessor as _assessor_mod


# ═════════════════════════════════════════════════════════════════════════════
#  RiskLevel
# ═════════════════════════════════════════════════════════════════════════════

class TestRiskLevel:

    def test_values(self):
        assert RiskLevel.LOW.value    == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value   == "high"

    def test_ordering_le(self):
        assert RiskLevel.LOW    <= RiskLevel.LOW
        assert RiskLevel.LOW    <= RiskLevel.MEDIUM
        assert RiskLevel.LOW    <= RiskLevel.HIGH
        assert RiskLevel.MEDIUM <= RiskLevel.MEDIUM
        assert RiskLevel.MEDIUM <= RiskLevel.HIGH
        assert RiskLevel.HIGH   <= RiskLevel.HIGH

    def test_ordering_not_le(self):
        assert not (RiskLevel.HIGH   <= RiskLevel.LOW)
        assert not (RiskLevel.HIGH   <= RiskLevel.MEDIUM)
        assert not (RiskLevel.MEDIUM <= RiskLevel.LOW)

    def test_ordering_lt(self):
        assert RiskLevel.LOW    < RiskLevel.MEDIUM
        assert RiskLevel.LOW    < RiskLevel.HIGH
        assert RiskLevel.MEDIUM < RiskLevel.HIGH

    def test_ordering_not_lt(self):
        assert not (RiskLevel.LOW  < RiskLevel.LOW)
        assert not (RiskLevel.HIGH < RiskLevel.MEDIUM)

    def test_from_str_valid(self):
        assert RiskLevel.from_str("low")    is RiskLevel.LOW
        assert RiskLevel.from_str("medium") is RiskLevel.MEDIUM
        assert RiskLevel.from_str("high")   is RiskLevel.HIGH

    def test_from_str_case_insensitive(self):
        assert RiskLevel.from_str("LOW")    is RiskLevel.LOW
        assert RiskLevel.from_str("Medium") is RiskLevel.MEDIUM
        assert RiskLevel.from_str("HIGH")   is RiskLevel.HIGH

    def test_from_str_strips_whitespace(self):
        assert RiskLevel.from_str("  low  ") is RiskLevel.LOW

    def test_from_str_invalid_raises(self):
        with pytest.raises(ValueError, match="未知风险级别"):
            RiskLevel.from_str("critical")

    def test_from_str_empty_raises(self):
        with pytest.raises(ValueError):
            RiskLevel.from_str("")


# ═════════════════════════════════════════════════════════════════════════════
#  OperationRisk
# ═════════════════════════════════════════════════════════════════════════════

class TestOperationRisk:

    def test_fields(self):
        risk = OperationRisk(
            tool_name="calculator",
            args={"expression": "1+1"},
            level=RiskLevel.LOW,
            reason="safe",
        )
        assert risk.tool_name == "calculator"
        assert risk.args == {"expression": "1+1"}
        assert risk.level is RiskLevel.LOW
        assert risk.reason == "safe"


# ═════════════════════════════════════════════════════════════════════════════
#  RuleBasedAssessor
# ═════════════════════════════════════════════════════════════════════════════

class TestRuleBasedAssessor:

    def setup_method(self):
        self.assessor = RuleBasedAssessor()

    def test_python_run_is_high(self):
        risk = self.assessor.assess("python_run", {})
        assert risk.level is RiskLevel.HIGH

    def test_file_write_is_medium(self):
        risk = self.assessor.assess("file_write", {"path": "x.txt"})
        assert risk.level is RiskLevel.MEDIUM

    def test_web_search_is_low(self):
        risk = self.assessor.assess("web_search", {"query": "test"})
        assert risk.level is RiskLevel.LOW

    def test_calculator_is_low(self):
        risk = self.assessor.assess("calculator", {"expression": "2+2"})
        assert risk.level is RiskLevel.LOW

    def test_unknown_tool_defaults_to_medium(self):
        risk = self.assessor.assess("unknown_tool_xyz", {})
        assert risk.level is RiskLevel.MEDIUM

    def test_reason_not_empty(self):
        risk = self.assessor.assess("file_read", {})
        assert isinstance(risk.reason, str) and len(risk.reason) > 0

    def test_tool_name_preserved(self):
        risk = self.assessor.assess("calculator", {"x": 1})
        assert risk.tool_name == "calculator"

    def test_args_preserved(self):
        args = {"expression": "sqrt(4)"}
        risk = self.assessor.assess("calculator", args)
        assert risk.args == args

    def test_override_changes_level(self):
        assessor = RuleBasedAssessor(overrides={"web_search": "high"})
        risk = assessor.assess("web_search", {})
        assert risk.level is RiskLevel.HIGH

    def test_override_invalid_level_raises(self):
        with pytest.raises(ValueError):
            RuleBasedAssessor(overrides={"calculator": "extreme"})


# ═════════════════════════════════════════════════════════════════════════════
#  ExternalAPIAssessor
# ═════════════════════════════════════════════════════════════════════════════

class TestExternalAPIAssessor:

    def _make_response(self, level: str = "medium", reason: str = "外部评估") -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"level": level, "reason": reason}
        resp.raise_for_status = MagicMock()
        return resp

    def _patch_post(self, monkeypatch, fn):
        _httpx_mock = MagicMock()
        _httpx_mock.post = fn
        # assessor.py 在函数内部 `import httpx`，须通过 sys.modules 注入
        monkeypatch.setitem(sys.modules, "httpx", _httpx_mock)

    def test_calls_external_url(self, monkeypatch):
        resp = self._make_response("low", "safe by external")
        captured = {}

        def fake_post(url, *, json, timeout):
            captured["url"] = url
            captured["json"] = json
            return resp

        self._patch_post(monkeypatch, fake_post)
        assessor = ExternalAPIAssessor("https://risk.api/assess")
        assessor.assess("calculator", {"expression": "1+1"})
        assert captured["url"] == "https://risk.api/assess"
        assert captured["json"]["tool_name"] == "calculator"

    def test_parses_level(self, monkeypatch):
        resp = self._make_response("high", "dangerous")
        self._patch_post(monkeypatch, lambda *a, **kw: resp)
        assessor = ExternalAPIAssessor("http://localhost/assess")
        risk = assessor.assess("python_run", {})
        assert risk.level is RiskLevel.HIGH

    def test_parses_reason(self, monkeypatch):
        resp = self._make_response("medium", "write operation")
        self._patch_post(monkeypatch, lambda *a, **kw: resp)
        assessor = ExternalAPIAssessor("http://localhost/assess")
        risk = assessor.assess("file_write", {})
        assert "write operation" in risk.reason

    def test_missing_level_defaults_to_medium(self, monkeypatch):
        resp = MagicMock()
        resp.json.return_value = {"reason": "no level field"}
        resp.raise_for_status = MagicMock()
        self._patch_post(monkeypatch, lambda *a, **kw: resp)
        assessor = ExternalAPIAssessor("http://localhost/assess")
        risk = assessor.assess("tool", {})
        assert risk.level is RiskLevel.MEDIUM

    def test_http_error_propagates(self, monkeypatch):
        import httpx
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=resp
        )
        self._patch_post(monkeypatch, lambda *a, **kw: resp)
        assessor = ExternalAPIAssessor("http://localhost/assess")
        with pytest.raises(httpx.HTTPStatusError):
            assessor.assess("tool", {})


# ═════════════════════════════════════════════════════════════════════════════
#  AllowList
# ═════════════════════════════════════════════════════════════════════════════

class TestAllowList:

    def test_empty_returns_none(self):
        al = AllowList()
        assert al.get("calculator") is None

    def test_init_with_entries(self):
        al = AllowList({"calculator": "low", "python_run": "high"})
        assert al.get("calculator") is RiskLevel.LOW
        assert al.get("python_run") is RiskLevel.HIGH

    def test_set_and_get(self):
        al = AllowList()
        al.set("web_search", RiskLevel.LOW)
        assert al.get("web_search") is RiskLevel.LOW

    def test_remove_existing(self):
        al = AllowList({"tool": "medium"})
        al.remove("tool")
        assert al.get("tool") is None

    def test_remove_nonexistent_no_error(self):
        al = AllowList()
        al.remove("ghost")  # should not raise

    def test_to_dict(self):
        al = AllowList({"a": "low", "b": "high"})
        d = al.to_dict()
        assert d == {"a": "low", "b": "high"}

    def test_to_dict_empty(self):
        al = AllowList()
        assert al.to_dict() == {}

    def test_invalid_level_in_init_raises(self):
        with pytest.raises(ValueError):
            AllowList({"tool": "extreme"})

    def test_override_replaces_value(self):
        al = AllowList({"tool": "low"})
        al.set("tool", RiskLevel.HIGH)
        assert al.get("tool") is RiskLevel.HIGH


# ═════════════════════════════════════════════════════════════════════════════
#  RiskGate
# ═════════════════════════════════════════════════════════════════════════════

def _make_gate(
    auto_approve_level: str = "medium",
    allow_list: dict | None = None,
    rule_overrides: dict | None = None,
) -> RiskGate:
    cfg = RiskConfig(
        auto_approve_level=auto_approve_level,
        allow_list=allow_list or {},
        rule_overrides=rule_overrides or {},
    )
    return RiskGate(cfg)


class TestRiskGate:

    def test_allow_list_bypasses_assessor(self):
        gate = _make_gate(allow_list={"python_run": "low"})
        risk = gate.check("python_run", {})
        assert risk.level is RiskLevel.LOW
        assert "allow list" in risk.reason

    def test_assessor_used_when_not_in_allow_list(self):
        gate = _make_gate()
        risk = gate.check("python_run", {})
        assert risk.level is RiskLevel.HIGH

    def test_requires_approval_above_threshold(self):
        gate = _make_gate(auto_approve_level="medium")
        high_risk = OperationRisk(tool_name="t", args={}, level=RiskLevel.HIGH, reason="r")
        assert gate.requires_approval(high_risk) is True

    def test_no_approval_at_threshold(self):
        gate = _make_gate(auto_approve_level="medium")
        med_risk = OperationRisk(tool_name="t", args={}, level=RiskLevel.MEDIUM, reason="r")
        assert gate.requires_approval(med_risk) is False

    def test_no_approval_below_threshold(self):
        gate = _make_gate(auto_approve_level="medium")
        low_risk = OperationRisk(tool_name="t", args={}, level=RiskLevel.LOW, reason="r")
        assert gate.requires_approval(low_risk) is False

    def test_high_auto_approve_level(self):
        gate = _make_gate(auto_approve_level="high")
        high_risk = OperationRisk(tool_name="t", args={}, level=RiskLevel.HIGH, reason="r")
        assert gate.requires_approval(high_risk) is False

    def test_low_auto_approve_level_blocks_medium(self):
        gate = _make_gate(auto_approve_level="low")
        med_risk = OperationRisk(tool_name="t", args={}, level=RiskLevel.MEDIUM, reason="r")
        assert gate.requires_approval(med_risk) is True

    def test_allow_list_accessible(self):
        gate = _make_gate(allow_list={"calculator": "low"})
        assert gate.allow_list.get("calculator") is RiskLevel.LOW

    def test_rule_overrides_applied(self):
        gate = _make_gate(rule_overrides={"web_search": "high"})
        risk = gate.check("web_search", {})
        assert risk.level is RiskLevel.HIGH

    def test_from_config_classmethod(self):
        cfg = RiskConfig(auto_approve_level="low")
        gate = RiskGate.from_config(cfg)
        assert isinstance(gate, RiskGate)

    def test_check_returns_operation_risk(self):
        gate = _make_gate()
        risk = gate.check("calculator", {"expression": "1+1"})
        assert isinstance(risk, OperationRisk)
        assert risk.tool_name == "calculator"


# ═════════════════════════════════════════════════════════════════════════════
#  直接运行
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    suites = [
        TestRiskLevel,
        TestOperationRisk,
        TestRuleBasedAssessor,
        TestAllowList,
        TestRiskGate,
    ]
    passed = failed = 0
    for cls in suites:
        print(f"\n── {cls.__name__} ──")
        inst = cls()
        for m in sorted(x for x in dir(cls) if x.startswith("test_")):
            if hasattr(inst, "setup_method"):
                inst.setup_method()
            fn = getattr(inst, m)
            sig = fn.__code__.co_varnames[:fn.__code__.co_argcount]
            if "monkeypatch" in sig:
                print(f"  SKIP  {m}  (需要 monkeypatch)")
                continue
            try:
                fn()
                print(f"  PASS  {m}")
                passed += 1
            except Exception:
                print(f"  FAIL  {m}")
                traceback.print_exc()
                failed += 1

    print(f"\n{'='*50}")
    print(f"Result: {passed} passed, {failed} failed")
