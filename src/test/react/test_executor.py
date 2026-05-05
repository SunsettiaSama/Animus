"""
ActionExecutor 测试
===================
从 test_actions.py 修复迁移：
  - 修正 import 路径（actions.executor → react.action.executor）
  - 保留原有语义：注册、执行、模糊名称匹配、未知工具错误、JSON 解析错误

运行方式：
  cd E:/ReAct
  python -m pytest src/test/react/test_executor.py -v
"""
from __future__ import annotations

import importlib.machinery
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parent.parent.parent
REACT_DIR = SRC / "agent" / "react"


def _pkg_stub(dotted_name: str, path: Path | None = None) -> types.ModuleType:
    m = types.ModuleType(dotted_name)
    m.__package__ = dotted_name
    m.__spec__ = importlib.machinery.ModuleSpec(
        dotted_name, loader=None, is_package=True
    )
    if path is not None:
        m.__path__ = [str(path)]
        m.__spec__.submodule_search_locations = m.__path__
    sys.modules[dotted_name] = m
    return m


def _mod_stub(dotted_name: str) -> types.ModuleType:
    m = types.ModuleType(dotted_name)
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None)
    sys.modules[dotted_name] = m
    return m


_pkg_stub("agent.react", REACT_DIR)

# langchain_core stub — BaseTool 需要是真正的 Pydantic 模型，
# 否则 executor.py 读不到 model_fields["name"].default
_lc_core      = _pkg_stub("langchain_core")
_lc_tools_mod = _mod_stub("langchain_core.tools")
_lc_msgs_mod  = _mod_stub("langchain_core.messages")

from pydantic import BaseModel as _PydanticBase  # noqa: E402  (此时 pydantic 仍是真实版本)

class _BaseTool(_PydanticBase):
    model_config = {"arbitrary_types_allowed": True}
    name: str = ""
    description: str = ""

_lc_tools_mod.BaseTool = _BaseTool
for _cls in ("BaseMessage", "SystemMessage", "HumanMessage", "AIMessage"):
    setattr(
        _lc_msgs_mod, _cls,
        type(_cls, (), {"__init__": lambda self, content="", **kw: setattr(self, "content", content)})
    )
_lc_core.tools    = _lc_tools_mod
_lc_core.messages = _lc_msgs_mod

_lc_comm = _pkg_stub("langchain_community")
_lce = _mod_stub("langchain_community.embeddings")
_lcv = _mod_stub("langchain_community.vectorstores")
_lce.HuggingFaceBgeEmbeddings = MagicMock()
_lcv.FAISS = MagicMock()
_lc_comm.embeddings  = _lce
_lc_comm.vectorstores = _lcv

sys.path.insert(0, str(SRC))

import pytest
from agent.react.action.executor import ActionExecutor
from agent.react.action.tools.impl.weather import WeatherAction


# ═════════════════════════════════════════════════════════════════════════════
#  基本注册与执行
# ═════════════════════════════════════════════════════════════════════════════

def test_register_and_available_actions():
    executor = ActionExecutor()
    executor.register(WeatherAction)
    assert "weather" in executor.available_actions


def test_weather_basic():
    executor = ActionExecutor()
    executor.register(WeatherAction)
    result = executor.run('{"action": "weather"}')
    assert result == "7月1日，晴天，温度为30~35°"


def test_weather_with_extra_args():
    executor = ActionExecutor()
    executor.register(WeatherAction)
    result = executor.run('{"action": "weather", "args": {"city": "Beijing"}}')
    assert result == "7月1日，晴天，温度为30~35°"


def test_unknown_action_returns_error():
    executor = ActionExecutor()
    result = executor.run('{"action": "fly_to_moon"}')
    assert "未知工具" in result


def test_malformed_json_raises():
    executor = ActionExecutor()
    with pytest.raises(Exception):
        executor.run("not json")


# ═════════════════════════════════════════════════════════════════════════════
#  模糊名称匹配
# ═════════════════════════════════════════════════════════════════════════════

class _FakeAction:
    args_model = None
    model_fields = {"name": MagicMock(default="fake_tool")}

    def execute(self, **kwargs) -> str:
        return "fake result"


def test_fuzzy_match_typo():
    executor = ActionExecutor()
    action = _FakeAction()
    action.name = "web_search"
    executor._instances["web_search"] = action
    result = executor.run(json.dumps({"action": "web_serach", "args": {}}))
    assert result == "fake result"


def test_exact_name_match():
    executor = ActionExecutor()
    action = _FakeAction()
    action.name = "web_search"
    executor._instances["web_search"] = action
    result = executor.run(json.dumps({"action": "web_search", "args": {}}))
    assert result == "fake result"


def test_completely_unknown_returns_error():
    executor = ActionExecutor()
    result = executor.run(json.dumps({"action": "fly_to_moon"}))
    assert "未知工具" in result


def test_available_actions_lists_all():
    executor = ActionExecutor()
    a1 = _FakeAction(); a1.name = "tool_a"
    a2 = _FakeAction(); a2.name = "tool_b"
    executor._instances["tool_a"] = a1
    executor._instances["tool_b"] = a2
    assert "tool_a" in executor.available_actions
    assert "tool_b" in executor.available_actions


def test_registry_class_fuzzy_match():
    executor = ActionExecutor()

    class FakeTool(_FakeAction):
        model_fields = {"name": MagicMock(default="knowledge_save")}
        name = "knowledge_save"

        def execute(self, **kwargs):
            return "saved"

    executor._registry["knowledge_save"] = FakeTool
    result = executor.run(json.dumps({"action": "knowlege_save", "args": {}}))
    assert result == "saved"


# ═════════════════════════════════════════════════════════════════════════════
#  直接运行
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    tests = [
        test_register_and_available_actions,
        test_weather_basic,
        test_weather_with_extra_args,
        test_unknown_action_returns_error,
        test_malformed_json_raises,
        test_fuzzy_match_typo,
        test_exact_name_match,
        test_completely_unknown_returns_error,
        test_available_actions_lists_all,
        test_registry_class_fuzzy_match,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1

    print(f"\nResult: {passed} passed, {failed} failed")
