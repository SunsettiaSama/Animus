"""
MemoryRecallAction 单元测试
============================
覆盖 memory_recall 工具的召回模式及边界：

  smart     → LongTermMemory.smart_recall
  semantic  → LongTermMemory.recall（纯向量）
  timeline  → LongTermMemory.recall_timeline(top_k)

不依赖任何外部服务。

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
_lc_core_docs = _mod_stub("langchain_core.documents")
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
_lc_core.documents = _lc_core_docs

for _name in ("AIMessage", "HumanMessage", "SystemMessage", "BaseMessage"):
    setattr(_lc_core_msgs, _name, MagicMock(name=_name))

_pkg_stub("agent.react.action", REACT_DIR / "action")

sys.path.insert(0, str(SRC))

from agent.react.action.tools.impl.memory_recall import MemoryRecallAction


def make_long_term(
    smart_result: str = "[smart recalled]",
    recall_result: str = "[semantic recalled]",
    timeline_result: str = "[timeline recalled]",
) -> MagicMock:
    lt = MagicMock()
    lt.smart_recall.return_value = smart_result
    lt.recall.return_value = recall_result
    lt.recall_timeline.return_value = timeline_result
    return lt


def make_action(long_term=None, soul_memory=None) -> MemoryRecallAction:
    return MemoryRecallAction(soul_memory=soul_memory, long_term=long_term)


def test_smart_calls_smart_recall():
    lt = make_long_term(smart_result="智能召回的内容")
    action = make_action(long_term=lt)

    result = action.execute(query="测试查询", mode="smart")

    lt.smart_recall.assert_called_once_with("测试查询")
    lt.recall.assert_not_called()
    lt.recall_timeline.assert_not_called()
    assert "智能召回的内容" in result
    assert "【长期记忆】" in result


def test_semantic_calls_recall():
    lt = make_long_term(recall_result="语义召回的内容")
    action = make_action(long_term=lt)

    result = action.execute(query="向量查询", mode="semantic")

    lt.recall.assert_called_once_with("向量查询")
    lt.smart_recall.assert_not_called()
    lt.recall_timeline.assert_not_called()
    assert "语义召回的内容" in result


def test_timeline_calls_recall_timeline():
    lt = make_long_term(timeline_result="近期记忆")
    action = make_action(long_term=lt)

    result = action.execute(query="最近的事", top_k=7, mode="timeline")

    lt.recall_timeline.assert_called_once_with(7)
    lt.smart_recall.assert_not_called()
    lt.recall.assert_not_called()
    assert "近期记忆" in result


def test_timeline_default_top_k():
    lt = make_long_term()
    action = make_action(long_term=lt)

    action.execute(query="最近", mode="timeline")

    lt.recall_timeline.assert_called_once_with(5)


def test_no_long_term_returns_empty_message():
    action = make_action(long_term=None)
    result = action.execute(query="任意查询")
    assert "暂无" in result


def test_empty_smart_result():
    lt = make_long_term(smart_result="")
    action = make_action(long_term=lt)

    result = action.execute(query="测试", mode="smart")
    assert "暂无" in result


def test_soul_memory_short_circuits():
    svc = MagicMock()
    block = MagicMock()
    block.is_empty.return_value = False
    block.render.return_value = "soul block"
    svc.recall.return_value = block
    action = make_action(long_term=make_long_term(), soul_memory=svc)

    result = action.execute(query="q", mode="smart")

    svc.recall.assert_called_once()
    assert result == "soul block"


def test_action_name_and_description():
    action = make_action()
    assert action.name == "memory_recall"
    assert len(action.description) > 10


def test_action_args_model_validates():
    model = MemoryRecallAction.args_model
    validated = model.model_validate({"query": "回忆一下", "top_k": 3, "mode": "timeline"})
    assert validated.query == "回忆一下"
    assert validated.top_k == 3

    from pydantic import ValidationError
    raised = False
    try:
        model.model_validate({"query": "q", "top_k": 999})
    except ValidationError:
        raised = True
    assert raised


ALL_TESTS = [
    test_smart_calls_smart_recall,
    test_semantic_calls_recall,
    test_timeline_calls_recall_timeline,
    test_timeline_default_top_k,
    test_no_long_term_returns_empty_message,
    test_empty_smart_result,
    test_soul_memory_short_circuits,
    test_action_name_and_description,
    test_action_args_model_validates,
]


if __name__ == "__main__":
    print("=" * 60)
    print("  MemoryRecallAction Tests")
    print("=" * 60)
    passed = 0
    failed = 0
    for test_fn in ALL_TESTS:
        try:
            test_fn()
            passed += 1
            print(f"[OK] {test_fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {test_fn.__name__}")
            import traceback
            traceback.print_exc()
    print("=" * 60)
    print(f"  Result: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)
