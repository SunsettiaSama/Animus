"""
SoulMemorySearchAction 单元测试
================================
覆盖 soul_memory_search 工具对 SoulService.search_memory 的委托与边界。

运行方式：
  python src/test/memory/test_memory_recall.py
"""

from __future__ import annotations

import importlib.machinery
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import BaseModel as _PydanticBase

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

_lc_core = _pkg_stub("langchain_core")
_lc_core_msgs = _mod_stub("langchain_core.messages")
_lc_core_tools = _mod_stub("langchain_core.tools")


class _BaseTool(_PydanticBase):
    name: str = ""
    description: str = ""

    def _run(self, *args, **kwargs):
        raise NotImplementedError

    async def _arun(self, *args, **kwargs):
        return self._run(*args, **kwargs)


_lc_core_tools.BaseTool = _BaseTool
_lc_core.tools = _lc_core_tools
_lc_core.messages = _lc_core_msgs

for _name in ("AIMessage", "HumanMessage", "SystemMessage", "BaseMessage"):
    setattr(_lc_core_msgs, _name, MagicMock(name=_name))

_pkg_stub("agent.react.action", REACT_DIR / "action")

sys.path.insert(0, str(SRC))

from agent.adapters.soul_tao.tools.memory_search import SoulMemorySearchAction


def make_soul(results=None):
    soul = MagicMock()
    soul.search_memory.return_value = {
        "mode": "hybrid",
        "count": len(results or []),
        "results": results or [],
    }
    return soul


def make_action(soul=None) -> SoulMemorySearchAction:
    return SoulMemorySearchAction(soul=soul)


def test_hybrid_delegates_to_soul():
    soul = make_soul([
        {"focus": "架构", "final_score": 0.8, "source": "ltm", "memory_type": "factual", "fact": "讨论微服务"},
    ])
    action = make_action(soul)
    out = action.execute(mode="hybrid", query="架构", top_k=3)
    soul.search_memory.assert_called_once()
    assert "架构" in out
    print("[OK] test_hybrid_delegates_to_soul")


def test_no_soul_returns_message():
    action = make_action(None)
    out = action.execute(mode="recent", top_k=3)
    assert "未就绪" in out
    print("[OK] test_no_soul_returns_message")


def test_semantic_without_query():
    action = make_action(make_soul())
    out = action.execute(mode="semantic", query="", top_k=3)
    assert "需要 query" in out
    print("[OK] test_semantic_without_query")


def test_empty_results():
    action = make_action(make_soul([]))
    out = action.execute(mode="hybrid", query="x", top_k=3)
    assert "暂无" in out
    print("[OK] test_empty_results")


def test_tool_metadata():
    action = make_action()
    assert action.name == "soul_memory_search"
    model = SoulMemorySearchAction.args_model
    assert "mode" in model.model_fields
    print("[OK] test_tool_metadata")


if __name__ == "__main__":
    print("  SoulMemorySearchAction Tests")
    test_hybrid_delegates_to_soul()
    test_no_soul_returns_message()
    test_semantic_without_query()
    test_empty_results()
    test_tool_metadata()
    print("  All passed.")
