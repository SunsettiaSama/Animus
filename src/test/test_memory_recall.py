"""
MemoryRecallAction 单元测试
============================
覆盖 memory_recall 工具的四种召回模式及边界情况：

  smart     → LongTermMemory.smart_recall + MilestoneMemory.retrieve
  semantic  → LongTermMemory.recall（纯向量）
  timeline  → LongTermMemory.recall_timeline(top_k)
  milestone → 仅 MilestoneMemory.retrieve

  边界：
    - 两个后端均为 None（工具未注册场景）
    - 仅一个后端存在
    - 两个后端均返回空字符串
    - top_k 正确传递给 recall_timeline

不依赖任何外部服务（无 LLM API、无 FAISS/BGE、无磁盘写入）。

运行方式：
  cd F:/ReAct
  conda run -n LLMs python src/test/test_memory_recall.py
  # 或
  conda run -n LLMs python -m pytest src/test/test_memory_recall.py -v
"""

from __future__ import annotations

import importlib.machinery
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# ── 环境准备（在导入任何项目模块之前执行）───────────────────────────────────────
#
# react/__init__.py 会 import TaoLoop → tao.py → langchain_core → transformers
# 用空壳包替换 react，但保留真实 __path__ 让子模块仍可按路径加载。
#
# langchain_community 在本环境可能未安装，桩住即可。
# ─────────────────────────────────────────────────────────────────────────────

SRC = Path(__file__).resolve().parent.parent
REACT_DIR = SRC / "react"


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


_pkg_stub("react", REACT_DIR)

# langchain_core.tools.BaseTool 是 pydantic BaseModel 的子类，
# 需要提供一个真实可继承的 stub，否则 BaseAction(BaseTool) 的 pydantic 元类会报错。
from pydantic import BaseModel as _PydanticBase

_lc_core      = _pkg_stub("langchain_core")
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
_lc_core.tools          = _lc_core_tools
_lc_core.messages       = _lc_core_msgs
_lc_core.documents      = _lc_core_docs

for _name in ("AIMessage", "HumanMessage", "SystemMessage", "BaseMessage"):
    setattr(_lc_core_msgs, _name, MagicMock(name=_name))

# react.action 包：跳过 __init__.py（它会触发 ToolManager → manager.py 的完整导入链）
_pkg_stub("react.action", REACT_DIR / "action")

_lc_comm = _pkg_stub("langchain_community")
_lc_emb  = _mod_stub("langchain_community.embeddings")
_lc_vs   = _mod_stub("langchain_community.vectorstores")
_lc_emb.HuggingFaceBgeEmbeddings = MagicMock(name="HuggingFaceBgeEmbeddings")
_lc_vs.FAISS                      = MagicMock(name="FAISS")
_lc_comm.embeddings               = _lc_emb
_lc_comm.vectorstores             = _lc_vs

# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, str(SRC))

from react.action.tools.impl.memory_recall import MemoryRecallAction


# ─────────────────────────────────────────────
# 辅助工厂
# ─────────────────────────────────────────────

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


def make_milestone(retrieve_result: str = "[milestone recalled]") -> MagicMock:
    ms = MagicMock()
    ms.retrieve.return_value = retrieve_result
    return ms


def make_action(
    long_term=None,
    milestone=None,
) -> MemoryRecallAction:
    return MemoryRecallAction(long_term=long_term, milestone=milestone)


# ─────────────────────────────────────────────
# 测试：smart 模式
# ─────────────────────────────────────────────

def test_smart_calls_smart_recall():
    """smart 模式应调用 LongTermMemory.smart_recall 并返回其结果。"""
    lt = make_long_term(smart_result="智能召回的内容")
    action = make_action(long_term=lt)

    result = action.execute(query="测试查询", mode="smart")

    lt.smart_recall.assert_called_once_with("测试查询")
    lt.recall.assert_not_called()
    lt.recall_timeline.assert_not_called()
    assert "智能召回的内容" in result
    assert "【长期记忆】" in result
    print("[OK] test_smart_calls_smart_recall")


def test_smart_also_queries_milestone():
    """smart 模式在有里程碑后端时，应同时查询 milestone.retrieve。"""
    lt = make_long_term(smart_result="长期结果")
    ms = make_milestone(retrieve_result="里程碑结果")
    action = make_action(long_term=lt, milestone=ms)

    result = action.execute(query="综合查询", mode="smart")

    lt.smart_recall.assert_called_once()
    ms.retrieve.assert_called_once_with("综合查询")
    assert "长期结果" in result
    assert "里程碑结果" in result
    assert "【长期记忆】" in result
    assert "【里程碑记忆】" in result
    print("[OK] test_smart_also_queries_milestone")


# ─────────────────────────────────────────────
# 测试：semantic 模式
# ─────────────────────────────────────────────

def test_semantic_calls_recall():
    """semantic 模式应调用 LongTermMemory.recall（纯向量），不调用 smart_recall。"""
    lt = make_long_term(recall_result="语义召回的内容")
    action = make_action(long_term=lt)

    result = action.execute(query="向量查询", mode="semantic")

    lt.recall.assert_called_once_with("向量查询")
    lt.smart_recall.assert_not_called()
    lt.recall_timeline.assert_not_called()
    assert "语义召回的内容" in result
    print("[OK] test_semantic_calls_recall")


def test_semantic_skips_milestone():
    """semantic 模式不应查询 milestone（仅 smart/milestone 两种模式访问它）。"""
    lt = make_long_term()
    ms = make_milestone()
    action = make_action(long_term=lt, milestone=ms)

    action.execute(query="测试", mode="semantic")

    ms.retrieve.assert_not_called()
    print("[OK] test_semantic_skips_milestone")


# ─────────────────────────────────────────────
# 测试：timeline 模式
# ─────────────────────────────────────────────

def test_timeline_calls_recall_timeline():
    """timeline 模式应调用 recall_timeline(top_k) 并传入正确的 top_k。"""
    lt = make_long_term(timeline_result="近期记忆")
    action = make_action(long_term=lt)

    result = action.execute(query="最近的事", top_k=7, mode="timeline")

    lt.recall_timeline.assert_called_once_with(7)
    lt.smart_recall.assert_not_called()
    lt.recall.assert_not_called()
    assert "近期记忆" in result
    print("[OK] test_timeline_calls_recall_timeline")


def test_timeline_default_top_k():
    """timeline 模式默认 top_k=5。"""
    lt = make_long_term()
    action = make_action(long_term=lt)

    action.execute(query="最近", mode="timeline")

    lt.recall_timeline.assert_called_once_with(5)
    print("[OK] test_timeline_default_top_k")


# ─────────────────────────────────────────────
# 测试：milestone 模式
# ─────────────────────────────────────────────

def test_milestone_only_queries_milestone():
    """milestone 模式不应查询 long_term，只查 milestone.retrieve。"""
    lt = make_long_term()
    ms = make_milestone(retrieve_result="重要里程碑")
    action = make_action(long_term=lt, milestone=ms)

    result = action.execute(query="重要承诺", mode="milestone")

    ms.retrieve.assert_called_once_with("重要承诺")
    lt.smart_recall.assert_not_called()
    lt.recall.assert_not_called()
    lt.recall_timeline.assert_not_called()
    assert "重要里程碑" in result
    assert "【里程碑记忆】" in result
    print("[OK] test_milestone_only_queries_milestone")


# ─────────────────────────────────────────────
# 测试：边界情况
# ─────────────────────────────────────────────

def test_no_backends_returns_empty_message():
    """两个后端均为 None 时，应返回'暂无相关记忆'提示，而非崩溃。"""
    action = make_action(long_term=None, milestone=None)
    result = action.execute(query="任意查询")
    assert "暂无" in result
    print("[OK] test_no_backends_returns_empty_message")


def test_only_long_term_no_milestone():
    """仅有 long_term 时，smart 模式只查长期记忆，milestone.retrieve 不被调用。"""
    lt = make_long_term(smart_result="只有长期")
    action = make_action(long_term=lt, milestone=None)

    result = action.execute(query="测试", mode="smart")

    lt.smart_recall.assert_called_once()
    assert "只有长期" in result
    print("[OK] test_only_long_term_no_milestone")


def test_only_milestone_no_long_term():
    """仅有 milestone 时，smart 模式只查里程碑，不调用 long_term。"""
    ms = make_milestone(retrieve_result="只有里程碑")
    action = make_action(long_term=None, milestone=ms)

    result = action.execute(query="测试", mode="smart")

    ms.retrieve.assert_called_once_with("测试")
    assert "只有里程碑" in result
    print("[OK] test_only_milestone_no_long_term")


def test_empty_recall_results():
    """两个后端均返回空字符串时，应返回'暂无相关记忆'提示。"""
    lt = make_long_term(smart_result="", recall_result="", timeline_result="")
    ms = make_milestone(retrieve_result="")
    action = make_action(long_term=lt, milestone=ms)

    result = action.execute(query="测试", mode="smart")
    assert "暂无" in result, f"Expected empty notice, got: {result!r}"
    print("[OK] test_empty_recall_results")


def test_milestone_mode_no_milestone_backend():
    """milestone 模式但 milestone=None，应返回'暂无'提示。"""
    lt = make_long_term()
    action = make_action(long_term=lt, milestone=None)

    result = action.execute(query="测试", mode="milestone")

    lt.smart_recall.assert_not_called()
    assert "暂无" in result
    print("[OK] test_milestone_mode_no_milestone_backend")


# ─────────────────────────────────────────────
# 测试：工具元信息
# ─────────────────────────────────────────────

def test_action_name_and_description():
    """工具 name 为 'memory_recall'，description 非空。"""
    action = make_action()
    assert action.name == "memory_recall"
    assert len(action.description) > 10
    print("[OK] test_action_name_and_description")


def test_action_args_model_validates():
    """args_model 应能成功校验合法参数并拒绝非法参数。"""
    model = MemoryRecallAction.args_model

    # 合法
    validated = model.model_validate({"query": "回忆一下", "top_k": 3, "mode": "timeline"})
    assert validated.query == "回忆一下"
    assert validated.top_k == 3

    # 非法：top_k 超出上限（1-20）
    import pytest
    from pydantic import ValidationError
    raised = False
    try:
        model.model_validate({"query": "q", "top_k": 999})
    except ValidationError:
        raised = True
    assert raised, "ValidationError expected for top_k=999"

    print("[OK] test_action_args_model_validates")


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

ALL_TESTS = [
    test_smart_calls_smart_recall,
    test_smart_also_queries_milestone,
    test_semantic_calls_recall,
    test_semantic_skips_milestone,
    test_timeline_calls_recall_timeline,
    test_timeline_default_top_k,
    test_milestone_only_queries_milestone,
    test_no_backends_returns_empty_message,
    test_only_long_term_no_milestone,
    test_only_milestone_no_long_term,
    test_empty_recall_results,
    test_milestone_mode_no_milestone_backend,
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
        except Exception:
            failed += 1
            print(f"  FAIL  {test_fn.__name__}")
            import traceback
            traceback.print_exc()
    print("=" * 60)
    print(f"  Result: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)
